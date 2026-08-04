from __future__ import annotations

"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station

fail2ban management routes.

fail2ban is used here as an optional *firewall actuator* for EAS Station's
application-level ban list (the ``ip_filters`` table, managed on the Security
Center "Banned IPs" tab). The ban list itself stays in the database — there is
only one list to maintain. When firewall enforcement is enabled, every app-level
ban/unban is mirrored (by app_core/auth/firewall.py) into a dedicated
``eas-station`` fail2ban jail (``bantime = -1``), so attackers are also dropped
at the host firewall before traffic reaches the web process.

This module installs/configures fail2ban, writes the actuator jail (plus an
optional ``sshd`` jail that protects the host SSH daemon — a separate concern
from the web ban list), and resyncs the firewall with the database on apply.
"""

import ipaddress
import logging
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app_core.auth.decorators import require_auth
from app_core.auth.firewall import (
    EAS_JAIL,
    heal_firewall_bans,
    import_ssh_bans,
    mirrorable_blocklist_ips,
    resync_bans,
    resync_ssh_bans,
)
from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import Fail2banSettings

logger = logging.getLogger(__name__)

fail2ban_bp = Blueprint("fail2ban", __name__, url_prefix="/admin/fail2ban")

SECURITY_LOG_PATH = "/var/log/eas-station/security.log"
JAIL_LOCAL_PATH = "/etc/fail2ban/jail.local"
EMPTY_FILTER_PATH = "/etc/fail2ban/filter.d/eas-station-empty.conf"

# Bound the SSH numeric tuning so the UI cannot generate a nonsensical jail.
_MIN_RETRY, _MAX_RETRY = 1, 100
_MIN_TIME, _MAX_TIME = 60, 31_536_000  # 1 minute .. 1 year (seconds)

# Filter for the actuator jail. It must be a valid fail2ban filter but must
# never match a real security-log line — the application performs detection and
# bans via the database; fail2ban only holds those bans at the firewall.
_EMPTY_FILTER = """\
# /etc/fail2ban/filter.d/eas-station-empty.conf
# Managed by EAS Station — generated {generated}
# Intentionally never matches: the EAS Station application detects abuse and
# records bans in its database; this jail only enforces them at the firewall.
[Definition]
failregex = ^__eas_station_never_match__ <HOST>$
ignoreregex =
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a privileged command via sudo. Returns (success, output)."""
    try:
        # -n (non-interactive): never block waiting for a sudo password. If the
        # required NOPASSWD sudoers entry is missing, sudo fails immediately with
        # a clear message instead of hanging until the worker times out.
        result = subprocess.run(
            ["sudo", "-n"] + cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


def _fail2ban_installed() -> bool:
    return shutil.which("fail2ban-client") is not None


def _fail2ban_active() -> bool:
    ok, _ = _run(["systemctl", "is-active", "--quiet", "fail2ban"])
    return ok


def _get_settings() -> Fail2banSettings:
    """Return the singleton settings row, creating defaults if absent."""
    settings = Fail2banSettings.query.get(1)
    if not settings:
        settings = Fail2banSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    return settings


def _loaded_jails() -> set[str]:
    ok, out = _run(["fail2ban-client", "status"])
    if not ok:
        return set()
    match = re.search(r"Jail list:\s*(.*)", out)
    if not match:
        return set()
    return {j.strip() for j in match.group(1).replace(",", " ").split() if j.strip()}


def _jail_banned_ips(jail: str) -> list[str]:
    ok, out = _run(["fail2ban-client", "status", jail])
    if not ok:
        return []
    match = re.search(r"Banned IP list:\s*(.*)", out)
    if not match:
        return []
    return [ip for ip in match.group(1).split() if ip]


def _app_ban_count() -> int:
    """Number of active application blocklist entries (the authoritative list)."""
    try:
        from app_core.auth.ip_filter import IPFilter, IPFilterType
        from app_utils import utc_now
        entries = IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value, is_active=True,
        ).all()
        now = utc_now()
        return sum(1 for e in entries if e.expires_at is None or e.expires_at > now)
    except Exception:
        return 0


def _import_ssh_bans() -> int:
    """Mirror current sshd-jail bans into the unified application ban list.

    Thin wrapper around :func:`app_core.auth.firewall.import_ssh_bans`. The
    detection + import logic lives in the firewall actuator bridge so it can run
    from a background thread (``app_core.fail2ban_sync``) without importing the
    web layer; this wrapper is kept so the existing route call sites read
    naturally and stay patchable in tests.
    """
    return import_ssh_bans()


def _ssh_bans_detailed() -> list:
    """Return sshd-jail bans as rich records mirroring the Banned IPs list.

    Each entry: ``{ip_address, reason, description, created_at, is_active,
    location:{country_code,country,city,region}}``. SSH offenders are imported
    into ip_filters, so we reuse that record (and the same MaxMind geolocation)
    when present, falling back to sensible defaults for an IP fail2ban just
    banned but that hasn't been imported yet.
    """
    ips = _jail_banned_ips("sshd")
    if not ips:
        return []

    classify_location = None
    db_path = None
    try:
        from app_core.analytics.geo import classify_location as _cl
        from app_core.analytics.web_traffic import TrafficAnalyticsSettings
        classify_location = _cl
        db_path = TrafficAnalyticsSettings.get_settings().geoip_database_path
    except Exception:
        pass

    records = {}
    try:
        from app_core.auth.ip_filter import IPFilter, IPFilterType
        for rec in IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value, is_active=True,
        ).filter(IPFilter.ip_address.in_(ips)).all():
            records[rec.ip_address] = rec
    except Exception:
        pass

    out = []
    for ip in ips:
        loc = {"country_code": None, "country": None, "city": None, "region": None}
        if classify_location is not None:
            try:
                info = classify_location(ip, db_path)
                loc = {
                    "country_code": info.get("country_code"),
                    "country": info.get("label") if info.get("country_code") else None,
                    "city": info.get("city"),
                    "region": info.get("region"),
                }
            except Exception:
                pass
        rec = records.get(ip)
        out.append({
            "ip_address": ip,
            "reason": rec.reason if rec else "auto_brute_force",
            "source": "ssh_brute_force",
            "source_label": "SSH Brute Force",
            "description": (rec.description if rec and rec.description
                            else "SSH brute-force detected by fail2ban (sshd jail)"),
            "created_at": rec.created_at.isoformat() if rec and rec.created_at else None,
            "is_active": True,
            "location": loc,
        })
    return out


def _status() -> dict:
    installed = _fail2ban_installed()
    active = _fail2ban_active() if installed else False
    settings = _get_settings()

    loaded = _loaded_jails() if (installed and active) else set()
    enforced = []
    if EAS_JAIL in loaded:
        enforced = _jail_banned_ips(EAS_JAIL)

    # Count only *mirrorable* bans (single, non-loopback IPs) that aren't in the
    # jail yet. CIDR ranges and loopback are app-layer only, so the firewall is
    # legitimately smaller than the ban list; counting them would flag a list
    # holding any range as permanently out of sync. Zero ⇒ fully mirrored.
    firewall_pending = 0
    if settings.enabled and EAS_JAIL in loaded:
        firewall_pending = len(mirrorable_blocklist_ips() - set(enforced))

    ssh_loaded = "sshd" in loaded
    ssh_banned = _ssh_bans_detailed() if ssh_loaded else []

    # When enforcement is on but the actuator jail failed to load, capture the
    # real fail2ban error so the UI can show *why* (instead of just "not loaded").
    actuator_error = ""
    if settings.enabled and active and EAS_JAIL not in loaded:
        actuator_error = _actuator_error()

    return {
        "installed": installed,
        "active": active,
        "enforcement_enabled": settings.enabled,
        "actuator_jail_loaded": EAS_JAIL in loaded,
        "actuator_error": actuator_error,
        "app_ban_count": _app_ban_count(),       # authoritative list size
        "firewall_ban_count": len(enforced),     # mirrored into the firewall
        "firewall_pending": firewall_pending,    # mirrorable bans not yet in jail
        "ssh_jail_loaded": ssh_loaded,
        "ssh_banned": ssh_banned,
        "log_path": SECURITY_LOG_PATH,
        "settings": settings.to_dict(),
    }


def _clamp(value, lo, hi, default) -> int:
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, ivalue))


def _render_jail_local(settings: Fail2banSettings) -> str:
    """Render /etc/fail2ban/jail.local from the stored settings."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    blocks = [
        "# /etc/fail2ban/jail.local",
        f"# EAS Station fail2ban configuration — generated {generated}",
        "# Managed by the EAS Station Security Center. Manual edits are overwritten",
        "# the next time the configuration is applied from the web UI.",
        "",
    ]

    if settings.enabled:
        # Actuator jail: never bans from logs (the app does detection); it only
        # holds app-driven bans at the firewall, permanently (bantime = -1) so
        # the database remains the single source of truth for ban lifecycle.
        blocks.append(f"""[{EAS_JAIL}]
enabled = true
filter = eas-station-empty
logpath = {SECURITY_LOG_PATH}
backend = polling
bantime = -1
findtime = 600
maxretry = 1000000
banaction = %(banaction_allports)s
""")

    if settings.protect_ssh:
        blocks.append(f"""[sshd]
enabled = true
maxretry = {settings.ssh_maxretry}
bantime = {settings.ssh_bantime}
""")

    return "\n".join(blocks).rstrip() + "\n"


def _ensure_security_log() -> bool:
    """Make sure the actuator jail's logpath exists before fail2ban (re)starts.

    The ``eas-station`` jail declares ``logpath = SECURITY_LOG_PATH``. If that
    file is absent, fail2ban refuses to start the jail — so app bans silently
    never reach the firewall and "Mirrored to host firewall" stays 0. Nothing
    else writes this file (the app's security logger goes to the journal), so we
    create it here.

    The web service runs under ProtectSystem=strict and may be unable to write
    /var/log/eas-station, so try a direct write first and fall back to creating
    the file as root via sudo. Best-effort; returns True if the file exists.
    """
    import os
    # Fast path: write directly (works when /var/log/eas-station is writable).
    try:
        os.makedirs(os.path.dirname(SECURITY_LOG_PATH), exist_ok=True)
        if not os.path.exists(SECURITY_LOG_PATH):
            with open(SECURITY_LOG_PATH, "a", encoding="utf-8"):
                pass
    except Exception as exc:
        logger.info("Direct security-log create failed (%s); trying via sudo", exc)

    if os.path.exists(SECURITY_LOG_PATH):
        return True

    # Fallback: create it as root, outside the web service's sandbox.
    _run(["mkdir", "-p", os.path.dirname(SECURITY_LOG_PATH)])
    try:
        subprocess.run(
            ["sudo", "-n", "tee", "-a", SECURITY_LOG_PATH],
            input="", capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("sudo create of %s failed: %s", SECURITY_LOG_PATH, exc)

    exists = os.path.exists(SECURITY_LOG_PATH)
    if not exists:
        logger.error("Could not create actuator log %s — eas-station jail will not load",
                     SECURITY_LOG_PATH)
    return exists


def _actuator_error() -> str:
    """Best-effort reason the eas-station jail failed to load (for the UI).

    Runs fail2ban's own config self-test and returns the relevant error lines,
    so an operator can see *why* the jail isn't loaded instead of just that it
    isn't. Never raises.
    """
    msgs = []
    ok, out = _run(["fail2ban-client", "-t"])
    for line in (out or "").splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if "error" in low or "eas-station" in low or "have not been read" in low:
            msgs.append(line)
    # De-dup, keep the most relevant tail.
    seen = []
    for m in msgs:
        if m not in seen:
            seen.append(m)
    return " | ".join(seen[-4:])


def _write_via_sudo(path: str, content: str) -> tuple[bool, str]:
    """Write content to a root-owned path through `sudo tee`."""
    try:
        proc = subprocess.run(
            ["sudo", "-n", "tee", path],
            input=content,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return False, (proc.stderr.strip() or "permission denied")
        return True, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


def run_background_sync() -> dict:
    """Import new sshd-jail bans into the unified ban list, self-heal the
    firewall mirror, and return the resulting status dict.

    fail2ban's ``sshd`` jail blocks SSH brute-force at the host firewall in real
    time, but those bans only become visible in the Global Ban List once they
    are copied into the ``ip_filters`` table by :func:`_import_ssh_bans`. That
    copy used to happen *only* while the Security Center page was open and
    polling this module's ``/status`` route — so overnight SSH attacks were
    enforced but never recorded, and their ``created_at`` reflected when an
    operator next opened the UI rather than when fail2ban actually banned them.

    The actual work now lives in ``app_core.auth.firewall`` so it can also run
    from the background sync scheduler (``app_core.fail2ban_sync``) without
    importing the web layer; this function keeps the UI's behaviour (import +
    self-heal, then return the rich status dict) in one place. Must be called
    inside a Flask app context. Never raises.
    """
    # Pull any new SSH-jail bans into the unified ban list before reporting.
    try:
        import_ssh_bans()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("SSH ban import skipped: %s", exc)

    # Self-heal: if enforcement is on and the actuator jail is loaded but not all
    # active bans are mirrored (e.g. after a fail2ban restart flushed them),
    # re-push the ban list into the firewall.
    try:
        heal_firewall_bans()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("fail2ban self-heal resync skipped: %s", exc)

    # This function mutates jail state, so any cached snapshot is now stale.
    invalidate_status_cache()
    return _status()


#: Seconds a computed status snapshot is served before fail2ban is shelled
#: again.  One _status() call costs roughly a dozen `sudo fail2ban-client`
#: round trips, which on a Pi is a large fraction of a second; the Security
#: Center polls it and several operators may have the page open at once.
_STATUS_CACHE_TTL_S = 10.0
_status_cache: dict = {"value": None, "ts": 0.0}
_status_cache_lock = threading.Lock()


def invalidate_status_cache() -> None:
    """Drop the cached status so the next read reflects a just-applied change."""
    with _status_cache_lock:
        _status_cache["value"] = None
        _status_cache["ts"] = 0.0


def _cached_status() -> dict:
    """Return a recent status snapshot, recomputing at most every few seconds."""
    with _status_cache_lock:
        cached = _status_cache["value"]
        if cached is not None and (time.monotonic() - _status_cache["ts"]) < _STATUS_CACHE_TTL_S:
            return cached

    value = _status()

    with _status_cache_lock:
        _status_cache["value"] = value
        _status_cache["ts"] = time.monotonic()
    return value


# ── Routes ──────────────────────────────────────────────────────────────────────

@fail2ban_bp.route("/status", methods=["GET"])
@require_auth
@require_permission("system.configure")
def fail2ban_status():
    """Report fail2ban state. Read-only and cached — never mutates.

    This used to call :func:`run_background_sync`, so simply opening the
    Security Center ran ``import_ssh_bans`` **and** ``heal_firewall_bans``
    inside the HTTP request. The latter re-pushes the whole ban list into the
    firewall one ``sudo fail2ban-client set … banip`` subprocess *per banned
    IP*; after any fail2ban restart (which flushes the jails) the first page
    load therefore paid for hundreds of privileged subprocess round trips
    before it could render — the "this page takes forever" report.

    That work is not needed here: ``app_core.fail2ban_sync`` has run both
    functions on a 60-second background schedule since it was added, precisely
    so the ban list stays current with the UI closed. Doing it again per page
    view was duplicated effort in the worst possible place.
    """
    return jsonify(_cached_status())


@fail2ban_bp.route("/configure", methods=["POST"])
@require_auth
@require_permission("system.configure")
def configure_fail2ban():
    """Persist settings, render jail/filter files, restart, and resync bans."""
    data = request.get_json(silent=True) or {}

    def as_bool(key, current):
        val = data.get(key, current)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "1", "yes", "on")

    try:
        settings = _get_settings()
        settings.enabled = as_bool("enabled", settings.enabled)
        settings.protect_ssh = as_bool("protect_ssh", settings.protect_ssh)
        settings.ssh_maxretry = _clamp(data.get("ssh_maxretry"), _MIN_RETRY, _MAX_RETRY, settings.ssh_maxretry)
        settings.ssh_bantime = _clamp(data.get("ssh_bantime"), _MIN_TIME, _MAX_TIME, settings.ssh_bantime)
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.error("DB error saving fail2ban settings: %s", exc)
        return jsonify({"success": False, "error": "Database error"}), 500

    if not _fail2ban_installed():
        # fail2ban ships pre-installed via install.sh / update.sh. If it is
        # somehow missing, settings are still saved; updating EAS Station
        # (sudo bash update.sh) reinstalls it.
        return jsonify({
            "success": True,
            "applied": False,
            "message": ("Settings saved, but fail2ban isn't installed on this host. "
                        "It ships pre-installed — run the EAS Station updater "
                        "(sudo bash update.sh) to restore it, then apply again."),
            "settings": settings.to_dict(),
        })

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # If a privileged write is denied, the cause is almost always a stale
    # sudoers file on the host — point the operator at the updater.
    sudoers_hint = (" This usually means the host's sudoers is out of date — "
                    "run 'sudo bash update.sh' to redeploy it, then apply again.")

    # The actuator jail needs its (never-matching) filter AND its logpath to
    # exist, or fail2ban won't start the jail and nothing gets mirrored.
    if settings.enabled:
        ok, err = _write_via_sudo(EMPTY_FILTER_PATH, _EMPTY_FILTER.format(generated=generated))
        if not ok:
            return jsonify({"success": False, "error": f"Failed to write filter: {err}.{sudoers_hint}"}), 500
        _ensure_security_log()

    ok, err = _write_via_sudo(JAIL_LOCAL_PATH, _render_jail_local(settings))
    if not ok:
        return jsonify({"success": False, "error": f"Failed to write jail.local: {err}.{sudoers_hint}"}), 500

    # A restart flushes every live ban. Snapshot the sshd jail's current bans
    # into the durable ban list first so they aren't lost (they're re-applied
    # to the sshd jail after the restart, below).
    if settings.protect_ssh:
        try:
            _import_ssh_bans()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("pre-restart SSH ban import skipped: %s", exc)

    _run(["systemctl", "enable", "fail2ban"])
    ok_restart, restart_out = _run(["systemctl", "restart", "fail2ban"])
    if not ok_restart:
        logger.error("fail2ban restart failed: %s", restart_out)
        return jsonify({
            "success": False,
            "error": f"Config written but fail2ban restart failed: {restart_out}",
        }), 500

    # Verify the jail actually loaded before claiming success — a valid-looking
    # write can still fail to produce a running jail (missing logpath, bad
    # banaction, etc.). Don't report "enabled" if it isn't really enforcing.
    if settings.enabled and EAS_JAIL not in _loaded_jails():
        detail = _actuator_error()
        logger.error("eas-station jail did not load after configure: %s", detail)
        return jsonify({
            "success": False,
            "error": ("Configuration applied, but the eas-station firewall jail did not load, "
                      "so bans are NOT being mirrored to the host firewall."
                      + (f" fail2ban: {detail}" if detail else "")),
            "settings": settings.to_dict(),
        }), 500

    # Restart flushes all bans, so re-apply the authoritative lists. Web bans go
    # back into the eas-station all-ports jail; SSH offenders go back into the
    # sshd jail (so an "apply" never silently un-bans known SSH attackers).
    synced = 0
    if settings.enabled:
        synced = resync_bans()
    ssh_synced = 0
    if settings.protect_ssh:
        ssh_synced = resync_ssh_bans()

    logger.info(
        "fail2ban configured (enforcement=%s ssh=%s); resynced %d web ban(s), %d ssh ban(s)",
        settings.enabled, settings.protect_ssh, synced, ssh_synced,
    )
    msg = ("Firewall enforcement enabled — "
           f"{synced} active ban(s) mirrored to the host firewall."
           if settings.enabled else
           "Firewall enforcement disabled. Web bans remain enforced at the application layer.")
    return jsonify({
        "success": True,
        "applied": True,
        "message": msg,
        "settings": settings.to_dict(),
    })


@fail2ban_bp.route("/resync", methods=["POST"])
@require_auth
@require_permission("system.configure")
def resync_fail2ban():
    """Re-push the authoritative app ban list into the firewall jail."""
    if not _fail2ban_installed() or not _fail2ban_active():
        return jsonify({"success": False, "error": "fail2ban is not installed/active."}), 400
    imported = _import_ssh_bans()          # pull SSH offenders into the ban list
    synced = resync_bans()                 # push the ban list into the eas-station jail
    ssh_synced = resync_ssh_bans()         # re-apply SSH offenders into the sshd jail
    msg = f"Resynced {synced} ban(s) to the firewall."
    if ssh_synced:
        msg += f" Re-applied {ssh_synced} SSH ban(s) to the sshd jail."
    if imported:
        msg += f" Imported {imported} SSH offender(s) into the ban list."
    invalidate_status_cache()
    return jsonify({"success": True, "message": msg})


@fail2ban_bp.route("/service", methods=["POST"])
@require_auth
@require_permission("system.configure")
def fail2ban_service():
    """Start, stop, or restart the fail2ban service."""
    if not _fail2ban_installed():
        return jsonify({"success": False, "error": "fail2ban is not installed."}), 400

    data = request.get_json(silent=True) or {}
    action = data.get("action", "").strip().lower()
    if action not in ("start", "stop", "restart"):
        return jsonify({"success": False, "error": "action must be start, stop, or restart"}), 400

    # A stop/restart flushes every live ban. Snapshot the sshd jail's current
    # bans into the durable ban list first so they survive (re-applied below).
    if action in ("stop", "restart"):
        try:
            _import_ssh_bans()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("pre-%s SSH ban import skipped: %s", action, exc)

    ok, output = _run(["systemctl", action, "fail2ban"])
    if not ok:
        return jsonify({"success": False, "error": output}), 500

    # A fresh start/restart loses bans — repopulate both jails from the database.
    if action in ("start", "restart"):
        resync_bans()
        resync_ssh_bans()

    invalidate_status_cache()
    return jsonify({"success": True, "message": f"fail2ban {action}ed.", "output": output})


@fail2ban_bp.route("/ssh-unban", methods=["POST"])
@require_auth
@require_permission("system.configure")
def ssh_unban():
    """Unban an IP from the host sshd jail (separate from the web ban list)."""
    if not _fail2ban_installed():
        return jsonify({"success": False, "error": "fail2ban is not installed."}), 400

    data = request.get_json(silent=True) or {}
    ip_address = (data.get("ip_address") or "").strip()
    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        return jsonify({"success": False, "error": "A valid IP address is required."}), 400

    ok, output = _run(["fail2ban-client", "set", "sshd", "unbanip", ip_address])
    if not ok:
        return jsonify({"success": False, "error": output}), 500

    # Also clear it from the unified ban list, otherwise it stays globally
    # blocked (and a leftover sshd entry would just be re-imported). remove_filter
    # also lifts the matching all-ports firewall ban.
    removed = 0
    try:
        from app_core.auth.ip_filter import IPFilter, IPFilterType
        entries = IPFilter.query.filter_by(
            ip_address=ip_address,
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True,
        ).all()
        for entry in entries:
            if IPFilter.remove_filter(entry.id):
                removed += 1
    except Exception as exc:
        logger.warning("Failed to clear %s from ban list during SSH unban: %s", ip_address, exc)

    logger.info("Unbanned %s from sshd jail (and %d ban-list entr(y/ies))", ip_address, removed)
    msg = f"Unbanned {ip_address} from the SSH jail."
    if removed:
        msg += " Also removed it from the global ban list."
    invalidate_status_cache()
    return jsonify({"success": True, "message": msg})


def register_fail2ban_routes(app, logger_):
    app.register_blueprint(fail2ban_bp)
    logger_.info("fail2ban management routes registered")
