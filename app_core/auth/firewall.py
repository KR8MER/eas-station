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

fail2ban firewall actuator bridge.

EAS Station's application-level ban list (``ip_filters``) is the single source
of truth. This module mirrors those bans to a dedicated fail2ban jail named
``eas-station`` so banned IPs are also dropped at the host firewall, before
traffic reaches the web process.

Every function here is **best-effort and never raises**: if fail2ban is not
installed, not active, or firewall enforcement is disabled, the call is a no-op.
Application-level banning (the global ``before_request`` gate) continues to work
regardless, so the firewall layer is purely additive defence-in-depth.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Dedicated jail that exists only to hold app-driven bans (bantime = -1).
EAS_JAIL = "eas-station"
# Standard fail2ban jail that watches the host SSH daemon's log.
SSH_JAIL = "sshd"


def _fail2ban_available() -> bool:
    """True only when fail2ban is installed AND the service is active."""
    if shutil.which("fail2ban-client") is None:
        return False
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "is-active", "--quiet", "fail2ban"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def is_enforcement_active() -> bool:
    """True when the operator has enabled firewall mirroring and fail2ban is up.

    The settings lookup is imported lazily to avoid an import cycle
    (``ip_filter`` imports this module, and the models import the auth package).
    """
    try:
        from app_core.models import Fail2banSettings
        settings = Fail2banSettings.query.get(1)
        if not settings or not settings.enabled:
            return False
    except Exception:
        # No app context / table not migrated yet / DB error — stay a no-op.
        return False
    return _fail2ban_available()


def _valid_ip(ip_address: str) -> bool:
    try:
        ipaddress.ip_address(ip_address)
        return True
    except ValueError:
        return False


def _client(*args: str, timeout: int = 15) -> bool:
    """Run `sudo fail2ban-client <args>`; return success, never raise."""
    try:
        result = subprocess.run(
            ["sudo", "-n", "fail2ban-client", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("fail2ban-client %s failed: %s", " ".join(args), exc)
        return False


def _client_output(*args: str, timeout: int = 15) -> tuple[bool, str]:
    """Run `sudo fail2ban-client <args>` and return (success, combined output)."""
    try:
        result = subprocess.run(
            ["sudo", "-n", "fail2ban-client", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("fail2ban-client %s failed: %s", " ".join(args), exc)
        return False, ""


def _loaded_jails() -> set[str]:
    """Return the set of jail names fail2ban currently has loaded."""
    ok, out = _client_output("status")
    if not ok:
        return set()
    match = re.search(r"Jail list:\s*(.*)", out)
    if not match:
        return set()
    return {j.strip() for j in match.group(1).replace(",", " ").split() if j.strip()}


def _jail_banned_ips(jail: str) -> list[str]:
    """Return the IPs currently banned in *jail* (empty list on any error)."""
    ok, out = _client_output("status", jail)
    if not ok:
        return []
    match = re.search(r"Banned IP list:\s*(.*)", out)
    if not match:
        return []
    return [ip for ip in match.group(1).split() if ip]


def firewall_ban(ip_address: str) -> None:
    """Mirror an application ban to the host firewall (best-effort)."""
    if not ip_address or not _valid_ip(ip_address):
        return
    if not is_enforcement_active():
        return
    # Loopback is always exempt — never firewall-ban ourselves.
    try:
        if ipaddress.ip_address(ip_address).is_loopback:
            return
    except ValueError:
        return
    if _client("set", EAS_JAIL, "banip", ip_address):
        logger.info("Mirrored ban of %s to host firewall (fail2ban)", ip_address)


def firewall_unban(ip_address: str) -> None:
    """Remove a host-firewall ban when an application ban is lifted."""
    if not ip_address or not _valid_ip(ip_address):
        return
    if not is_enforcement_active():
        return
    if _client("set", EAS_JAIL, "unbanip", ip_address):
        logger.info("Removed host-firewall ban of %s (fail2ban)", ip_address)


def mirrorable_blocklist_ips() -> set[str]:
    """The set of ban-list IPs that *can* be held in the firewall jail.

    The actuator jail enforces bans with ``fail2ban-client ... banip``, which
    only accepts single routable IPs. CIDR ranges and loopback addresses on the
    application ban list are therefore deliberately never mirrored — they are
    enforced at the application layer only. The firewall jail consequently tops
    out at *this* set, not the full ban-list size.

    This is the correct baseline for every "is the firewall in sync?" check.
    Comparing the jail's IP count against the raw ban-list count instead makes a
    list holding even one CIDR range look permanently out of sync: the self-heal
    fires a no-op ``resync_bans`` on every cycle and the Security Center shows a
    "Some bans aren't mirrored yet — click Resync bans" banner that Resync can
    never clear (the missing entry is unmirrorable by design).

    Best-effort; returns an empty set on any error.
    """
    try:
        from app_core.auth.ip_filter import IPFilter, IPFilterType
        from app_utils import utc_now
        entries = IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True,
        ).all()
    except Exception as exc:
        logger.debug("mirrorable_blocklist_ips could not load blocklist: %s", exc)
        return set()

    from datetime import timezone

    now = utc_now()
    ips: set[str] = set()
    for entry in entries:
        # Coerce naive timestamps (e.g. from SQLite, which drops tzinfo) to UTC
        # so the expiry comparison can never raise.
        expires_at = entry.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                continue
        ip = entry.ip_address
        if not ip or not _valid_ip(ip):
            continue  # CIDR ranges are skipped (fail2ban banip wants single IPs)
        try:
            if ipaddress.ip_address(ip).is_loopback:
                continue
        except ValueError:
            continue
        ips.add(ip)
    return ips


def resync_bans() -> int:
    """Push every mirrorable application blocklist entry into the firewall jail.

    fail2ban flushes all bans on restart, so this is called after applying the
    configuration (and after a service restart) to bring the firewall back in
    sync with the authoritative ``ip_filters`` table. Returns the number of IPs
    (re)banned.
    """
    if not is_enforcement_active():
        return 0
    count = 0
    for ip in mirrorable_blocklist_ips():
        if _client("set", EAS_JAIL, "banip", ip):
            count += 1
    logger.info("Resynced %d application ban(s) into host firewall (fail2ban)", count)
    return count


def resync_ssh_bans() -> int:
    """Re-apply still-active SSH-sourced bans back into the ``sshd`` jail.

    fail2ban flushes every live ban when it restarts. SSH offenders are imported
    into the application ban list (``ip_filters`` with
    ``source = ssh_brute_force``), but unlike web bans they were not being
    restored to any jail on restart — so a fail2ban restart (which the Security
    Center triggers on every "Save & Apply") silently un-banned known SSH
    attackers until they were re-detected. This re-pushes the durable list into
    the ``sshd`` jail so those bans survive a restart.

    Unlike :func:`resync_bans`, this does not require web-ban mirroring
    (``Fail2banSettings.enabled``) to be on — only that SSH protection is
    enabled and fail2ban is up. Returns the number of IPs (re)banned.
    Best-effort; never raises.
    """
    if not _fail2ban_available():
        return 0
    try:
        from app_core.models import Fail2banSettings
        settings = Fail2banSettings.query.get(1)
        if not settings or not settings.protect_ssh:
            return 0
    except Exception:
        return 0
    try:
        from app_core.auth.ip_filter import IPFilter, IPFilterType, IPFilterSource
        from app_utils import utc_now
        entries = IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True,
            source=IPFilterSource.SSH_BRUTE_FORCE.value,
        ).all()
    except Exception as exc:
        logger.debug("resync_ssh_bans could not load SSH bans: %s", exc)
        return 0

    from datetime import timezone

    count = 0
    now = utc_now()
    for entry in entries:
        # Coerce naive timestamps (e.g. from SQLite, which drops tzinfo) to UTC
        # so the expiry comparison can never raise.
        expires_at = entry.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                continue
        ip = entry.ip_address
        if not ip or not _valid_ip(ip):
            continue
        try:
            if ipaddress.ip_address(ip).is_loopback:
                continue
        except ValueError:
            continue
        if _client("set", SSH_JAIL, "banip", ip):
            count += 1
    if count:
        logger.info("Re-applied %d SSH ban(s) to the sshd jail after restart", count)
    return count


def active_blocklist_count() -> int:
    """Number of active, non-expired application blocklist entries.

    This is the authoritative Global Ban List size that the firewall jail
    should mirror. Best-effort; returns 0 on any error.
    """
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


def import_ssh_bans() -> int:
    """Mirror current ``sshd``-jail bans into the unified application ban list.

    SSH brute-force attempts hit port 22 directly, where the web application
    can't see them — only the host SSH (``sshd``) jail catches them. When that
    jail is enabled, an offender hammering port 22 should be banned *globally*,
    not just on SSH: this copies each sshd-jail ban into ``ip_filters``, which
    blocks it at the web layer and (via ``add_to_blocklist``) mirrors it into
    the all-ports ``eas-station`` firewall jail.

    One-way and idempotent — only IPs not already on the active blocklist are
    added. Returns the number of newly imported IPs. Best-effort; never raises.

    Historically this ran *only* while the Security Center page was polling the
    status endpoint, so overnight SSH bans were enforced at the firewall but
    never recorded in the ban list. It is now also driven by a background
    scheduler (``app_core.fail2ban_sync``) so the list stays current with the
    UI closed.
    """
    if not _fail2ban_available():
        return 0
    try:
        from app_core.models import Fail2banSettings
        settings = Fail2banSettings.query.get(1)
        if not settings or not settings.protect_ssh:
            return 0
    except Exception:
        return 0

    banned = _jail_banned_ips(SSH_JAIL)
    if not banned:
        return 0

    try:
        from app_core.auth.ip_filter import (
            IPFilter, IPFilterType, IPFilterReason, IPFilterSource,
        )
    except Exception:
        return 0

    # Carry over the sshd jail's ban time so the imported entry expires when the
    # fail2ban ban would — rather than becoming a permanent ban. The import runs
    # shortly after fail2ban bans the IP, so "now + ssh_bantime" closely tracks
    # the jail's own expiry. A non-positive bantime means permanent.
    ban_seconds = settings.ssh_bantime or 0
    expires_in_hours = (ban_seconds / 3600.0) if ban_seconds and ban_seconds > 0 else None
    if expires_in_hours is not None:
        expiry_note = f"; expires with the sshd jail ban (~{ban_seconds}s)"
    else:
        expiry_note = " (permanent)"

    added = 0
    for ip in banned:
        if not _valid_ip(ip):
            continue
        existing = IPFilter.query.filter_by(
            ip_address=ip,
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True,
        ).first()
        if existing:
            continue
        try:
            IPFilter.add_to_blocklist(
                ip_address=ip,
                reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
                description="SSH brute-force detected by fail2ban (sshd jail)" + expiry_note,
                source=IPFilterSource.SSH_BRUTE_FORCE.value,
                expires_in_hours=expires_in_hours,
            )
            added += 1
        except Exception as exc:
            logger.warning("Failed to import SSH ban %s into ban list: %s", ip, exc)

    if added:
        logger.info("Imported %d SSH-jail ban(s) into the application ban list", added)
    return added


def firewall_pending_bans() -> int:
    """How many *mirrorable* ban-list IPs are not yet present in the firewall jail.

    Zero means the firewall is fully in sync with the mirrorable subset of the
    ban list (CIDR ranges and loopback are app-layer only and never counted).
    This — not ``app_ban_count > firewall_ban_count`` — is the correct "needs a
    resync" signal: the raw-count comparison reports a list holding any range as
    permanently out of sync. Best-effort; returns 0 on any error.
    """
    try:
        if not is_enforcement_active():
            return 0
        if EAS_JAIL not in _loaded_jails():
            return 0
        return len(mirrorable_blocklist_ips() - set(_jail_banned_ips(EAS_JAIL)))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("firewall_pending_bans skipped: %s", exc)
        return 0


def heal_firewall_bans() -> bool:
    """Re-push the ban list into the firewall jail when the two have drifted.

    fail2ban flushes its jails on restart (host reboot, package upgrade, etc.),
    which leaves the ``eas-station`` jail holding fewer bans than the
    authoritative blocklist. When enforcement is on, the jail is loaded, and a
    *mirrorable* ban is missing from it, re-sync from the database. Returns True
    if a resync ran.

    The drift check compares against :func:`mirrorable_blocklist_ips`, not the
    raw blocklist size: CIDR ranges and loopback can never live in the jail, so
    counting them would make a list holding any range look permanently drifted
    and trigger a wasteful no-op resync on every cycle. Best-effort; never raises.
    """
    try:
        if not is_enforcement_active():
            return False
        if EAS_JAIL not in _loaded_jails():
            return False
        if mirrorable_blocklist_ips() - set(_jail_banned_ips(EAS_JAIL)):
            resync_bans()
            return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("heal_firewall_bans skipped: %s", exc)
    return False
