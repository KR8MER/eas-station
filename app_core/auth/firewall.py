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


def resync_bans() -> int:
    """Push every active application blocklist entry into the firewall jail.

    fail2ban flushes all bans on restart, so this is called after applying the
    configuration (and after a service restart) to bring the firewall back in
    sync with the authoritative ``ip_filters`` table. Returns the number of IPs
    (re)banned.
    """
    if not is_enforcement_active():
        return 0
    try:
        from app_core.auth.ip_filter import IPFilter, IPFilterType
        from app_utils import utc_now
        entries = IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True,
        ).all()
    except Exception as exc:
        logger.debug("resync_bans could not load blocklist: %s", exc)
        return 0

    count = 0
    now = utc_now()
    for entry in entries:
        if entry.expires_at is not None and entry.expires_at <= now:
            continue
        ip = entry.ip_address
        if not ip or not _valid_ip(ip):
            continue  # CIDR ranges are skipped (fail2ban banip wants single IPs)
        try:
            if ipaddress.ip_address(ip).is_loopback:
                continue
        except ValueError:
            continue
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
