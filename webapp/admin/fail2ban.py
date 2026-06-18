from __future__ import annotations

"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app_core.auth.decorators import require_auth
from app_core.auth.firewall import EAS_JAIL, resync_bans
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
        result = subprocess.run(
            ["sudo"] + cmd,
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


def _status() -> dict:
    installed = _fail2ban_installed()
    active = _fail2ban_active() if installed else False
    settings = _get_settings()

    loaded = _loaded_jails() if (installed and active) else set()
    enforced = []
    if EAS_JAIL in loaded:
        enforced = _jail_banned_ips(EAS_JAIL)

    ssh_loaded = "sshd" in loaded
    ssh_banned = _jail_banned_ips("sshd") if ssh_loaded else []

    return {
        "installed": installed,
        "active": active,
        "enforcement_enabled": settings.enabled,
        "actuator_jail_loaded": EAS_JAIL in loaded,
        "app_ban_count": _app_ban_count(),       # authoritative list size
        "firewall_ban_count": len(enforced),     # mirrored into the firewall
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


def _write_via_sudo(path: str, content: str) -> tuple[bool, str]:
    """Write content to a root-owned path through `sudo tee`."""
    try:
        proc = subprocess.run(
            ["sudo", "tee", path],
            input=content,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return False, proc.stderr.strip()
        return True, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)


# ── Routes ──────────────────────────────────────────────────────────────────────

@fail2ban_bp.route("/status", methods=["GET"])
@require_auth
@require_permission("system.configure")
def fail2ban_status():
    return jsonify(_status())


@fail2ban_bp.route("/install", methods=["POST"])
@require_auth
@require_permission("system.configure")
def install_fail2ban():
    """Install fail2ban via apt-get (non-interactive)."""
    if _fail2ban_installed():
        return jsonify({"success": True, "message": "fail2ban is already installed."})

    ok, output = _run(
        ["env", "DEBIAN_FRONTEND=noninteractive",
         "apt-get", "install", "-y", "fail2ban"],
        timeout=180,
    )
    if not ok:
        logger.error("fail2ban install failed: %s", output)
        return jsonify({"success": False, "error": output}), 500

    logger.info("fail2ban installed successfully")
    return jsonify({"success": True, "message": "fail2ban installed successfully."})


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
        return jsonify({
            "success": True,
            "applied": False,
            "message": "Settings saved. Install fail2ban to enforce bans at the host firewall.",
            "settings": settings.to_dict(),
        })

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # The actuator jail needs its (never-matching) filter to exist.
    if settings.enabled:
        ok, err = _write_via_sudo(EMPTY_FILTER_PATH, _EMPTY_FILTER.format(generated=generated))
        if not ok:
            return jsonify({"success": False, "error": f"Failed to write filter: {err}"}), 500

    ok, err = _write_via_sudo(JAIL_LOCAL_PATH, _render_jail_local(settings))
    if not ok:
        return jsonify({"success": False, "error": f"Failed to write jail.local: {err}"}), 500

    _run(["systemctl", "enable", "fail2ban"])
    ok_restart, restart_out = _run(["systemctl", "restart", "fail2ban"])
    if not ok_restart:
        logger.error("fail2ban restart failed: %s", restart_out)
        return jsonify({
            "success": False,
            "error": f"Config written but fail2ban restart failed: {restart_out}",
        }), 500

    # Restart flushes all bans, so re-mirror the authoritative app ban list.
    synced = 0
    if settings.enabled:
        synced = resync_bans()

    logger.info(
        "fail2ban configured (enforcement=%s ssh=%s); resynced %d ban(s)",
        settings.enabled, settings.protect_ssh, synced,
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
    synced = resync_bans()
    return jsonify({"success": True, "message": f"Resynced {synced} ban(s) to the firewall."})


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

    ok, output = _run(["systemctl", action, "fail2ban"])
    if not ok:
        return jsonify({"success": False, "error": output}), 500

    # A fresh start/restart loses bans — repopulate from the database.
    if action in ("start", "restart"):
        resync_bans()

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

    logger.info("Unbanned %s from sshd jail", ip_address)
    return jsonify({"success": True, "message": f"Unbanned {ip_address} from the SSH jail."})


def register_fail2ban_routes(app, logger_):
    app.register_blueprint(fail2ban_bp)
    logger_.info("fail2ban management routes registered")
