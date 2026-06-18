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

Lets an operator install, configure, and apply host-level fail2ban jails
entirely from the Security Center — no SSH or hand-editing of
/etc/fail2ban/jail.local required. EAS Station already writes malicious /
failed-login events to /var/log/eas-station/security.log in a
fail2ban-parseable format; this module renders the matching jail + filter
files and (re)starts the fail2ban service so attacking IPs are banned at the
firewall level.
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
from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import Fail2banSettings

logger = logging.getLogger(__name__)

fail2ban_bp = Blueprint("fail2ban", __name__, url_prefix="/admin/fail2ban")

SECURITY_LOG_PATH = "/var/log/eas-station/security.log"
JAIL_LOCAL_PATH = "/etc/fail2ban/jail.local"
MALICIOUS_FILTER_PATH = "/etc/fail2ban/filter.d/eas-station-malicious.conf"
AUTH_FILTER_PATH = "/etc/fail2ban/filter.d/eas-station-auth.conf"

EAS_JAILS = ("eas-station-malicious", "eas-station-auth")

# Bound the numeric tuning values so the UI cannot generate a nonsensical jail.
_MIN_RETRY, _MAX_RETRY = 1, 100
_MIN_TIME, _MAX_TIME = 60, 31_536_000  # 1 minute .. 1 year (seconds)

_MALICIOUS_FILTER = """\
# /etc/fail2ban/filter.d/eas-station-malicious.conf
# Managed by EAS Station — generated {generated}
[Definition]
failregex = ^.*MALICIOUS_LOGIN from <HOST>.*$
ignoreregex =
"""

_AUTH_FILTER = """\
# /etc/fail2ban/filter.d/eas-station-auth.conf
# Managed by EAS Station — generated {generated}
[Definition]
failregex = ^.*(FAILED_LOGIN|RATE_LIMIT_EXCEEDED) from <HOST>.*$
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


def _jail_banned_ips(jail: str) -> list[str]:
    """Return the currently banned IPs for a jail via fail2ban-client."""
    ok, out = _run(["fail2ban-client", "status", jail])
    if not ok:
        return []
    # The "Banned IP list:" line carries space-separated addresses.
    match = re.search(r"Banned IP list:\s*(.*)", out)
    if not match:
        return []
    return [ip for ip in match.group(1).split() if ip]


def _active_eas_jails() -> list[str]:
    """Return which EAS jails fail2ban currently reports as loaded."""
    ok, out = _run(["fail2ban-client", "status"])
    if not ok:
        return []
    match = re.search(r"Jail list:\s*(.*)", out)
    if not match:
        return []
    loaded = {j.strip() for j in match.group(1).replace(",", " ").split() if j.strip()}
    return [j for j in EAS_JAILS if j in loaded]


def _status() -> dict:
    installed = _fail2ban_installed()
    active = _fail2ban_active() if installed else False

    banned: dict[str, list[str]] = {}
    loaded_jails: list[str] = []
    if installed and active:
        loaded_jails = _active_eas_jails()
        for jail in loaded_jails:
            banned[jail] = _jail_banned_ips(jail)

    settings = _get_settings()

    return {
        "installed": installed,
        "active": active,
        "loaded_jails": loaded_jails,
        "banned": banned,
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
        f"# EAS Station security jail configuration — generated {generated}",
        "# Managed by the EAS Station Security Center. Manual edits are overwritten",
        "# the next time the configuration is applied from the web UI.",
        "",
    ]

    blocks.append(f"""[eas-station-malicious]
enabled = true
port = http,https
filter = eas-station-malicious
logpath = {SECURITY_LOG_PATH}
maxretry = {settings.maxretry}
bantime = {settings.bantime}
findtime = {settings.findtime}
""")

    if settings.protect_auth:
        blocks.append(f"""[eas-station-auth]
enabled = true
port = http,https
filter = eas-station-auth
logpath = {SECURITY_LOG_PATH}
maxretry = {settings.auth_maxretry}
bantime = {settings.auth_bantime}
findtime = {settings.findtime}
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
    """Persist settings, render jail + filter files, and (re)start fail2ban."""
    data = request.get_json(silent=True) or {}

    def as_bool(key, current):
        val = data.get(key, current)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "1", "yes", "on")

    try:
        settings = _get_settings()

        settings.enabled = as_bool("enabled", settings.enabled)
        settings.maxretry = _clamp(data.get("maxretry"), _MIN_RETRY, _MAX_RETRY, settings.maxretry)
        settings.bantime = _clamp(data.get("bantime"), _MIN_TIME, _MAX_TIME, settings.bantime)
        settings.findtime = _clamp(data.get("findtime"), _MIN_TIME, _MAX_TIME, settings.findtime)

        settings.protect_auth = as_bool("protect_auth", settings.protect_auth)
        settings.auth_maxretry = _clamp(data.get("auth_maxretry"), _MIN_RETRY, _MAX_RETRY, settings.auth_maxretry)
        settings.auth_bantime = _clamp(data.get("auth_bantime"), _MIN_TIME, _MAX_TIME, settings.auth_bantime)

        settings.protect_ssh = as_bool("protect_ssh", settings.protect_ssh)
        settings.ssh_maxretry = _clamp(data.get("ssh_maxretry"), _MIN_RETRY, _MAX_RETRY, settings.ssh_maxretry)
        settings.ssh_bantime = _clamp(data.get("ssh_bantime"), _MIN_TIME, _MAX_TIME, settings.ssh_bantime)

        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.error("DB error saving fail2ban settings: %s", exc)
        return jsonify({"success": False, "error": "Database error"}), 500

    # Settings saved. If fail2ban itself isn't installed we still keep the
    # stored configuration, but cannot apply it to the host yet.
    if not _fail2ban_installed():
        return jsonify({
            "success": True,
            "applied": False,
            "message": "Settings saved. Install fail2ban to apply them to the host.",
            "settings": settings.to_dict(),
        })

    # When disabled, leave the host config in place but make sure the EAS jails
    # are not active by removing our managed jail.local. fail2ban falls back to
    # its packaged defaults.
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not settings.enabled:
        disabled_stub = (
            "# /etc/fail2ban/jail.local\n"
            f"# EAS Station jails disabled from the Security Center — {generated}\n"
        )
        ok, err = _write_via_sudo(JAIL_LOCAL_PATH, disabled_stub)
        if not ok:
            return jsonify({"success": False, "error": f"Failed to write jail.local: {err}"}), 500
        _run(["systemctl", "reload-or-restart", "fail2ban"])
        return jsonify({
            "success": True,
            "applied": True,
            "message": "EAS Station fail2ban jails disabled.",
            "settings": settings.to_dict(),
        })

    # Write filter definitions first so the jails resolve.
    ok, err = _write_via_sudo(MALICIOUS_FILTER_PATH, _MALICIOUS_FILTER.format(generated=generated))
    if not ok:
        return jsonify({"success": False, "error": f"Failed to write malicious filter: {err}"}), 500

    if settings.protect_auth:
        ok, err = _write_via_sudo(AUTH_FILTER_PATH, _AUTH_FILTER.format(generated=generated))
        if not ok:
            return jsonify({"success": False, "error": f"Failed to write auth filter: {err}"}), 500

    ok, err = _write_via_sudo(JAIL_LOCAL_PATH, _render_jail_local(settings))
    if not ok:
        return jsonify({"success": False, "error": f"Failed to write jail.local: {err}"}), 500

    # Enable on boot and apply the new configuration.
    _run(["systemctl", "enable", "fail2ban"])
    ok_restart, restart_out = _run(["systemctl", "restart", "fail2ban"])
    if not ok_restart:
        logger.error("fail2ban restart failed: %s", restart_out)
        return jsonify({
            "success": False,
            "error": f"Config written but fail2ban restart failed: {restart_out}",
        }), 500

    logger.info(
        "fail2ban configured (maxretry=%s bantime=%s findtime=%s auth=%s ssh=%s) and restarted",
        settings.maxretry, settings.bantime, settings.findtime,
        settings.protect_auth, settings.protect_ssh,
    )
    return jsonify({
        "success": True,
        "applied": True,
        "message": "fail2ban configuration applied and service restarted.",
        "settings": settings.to_dict(),
    })


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

    return jsonify({"success": True, "message": f"fail2ban {action}ed.", "output": output})


@fail2ban_bp.route("/unban", methods=["POST"])
@require_auth
@require_permission("system.configure")
def unban_ip():
    """Unban an IP from one (or all) EAS Station jails."""
    if not _fail2ban_installed():
        return jsonify({"success": False, "error": "fail2ban is not installed."}), 400

    data = request.get_json(silent=True) or {}
    ip_address = (data.get("ip_address") or "").strip()
    jail = (data.get("jail") or "").strip()

    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        return jsonify({"success": False, "error": "A valid IP address is required."}), 400

    target_jails = [jail] if jail in EAS_JAILS else _active_eas_jails()
    if not target_jails:
        return jsonify({"success": False, "error": "No EAS Station jails are active."}), 400

    unbanned = []
    for j in target_jails:
        ok, _ = _run(["fail2ban-client", "set", j, "unbanip", ip_address])
        if ok:
            unbanned.append(j)

    if not unbanned:
        return jsonify({"success": False, "error": f"{ip_address} was not banned in any jail."}), 400

    logger.info("Unbanned %s from jails: %s", ip_address, ", ".join(unbanned))
    return jsonify({
        "success": True,
        "message": f"Unbanned {ip_address} from {', '.join(unbanned)}.",
    })


@fail2ban_bp.route("/ban", methods=["POST"])
@require_auth
@require_permission("system.configure")
def ban_ip():
    """Manually ban an IP in the eas-station-malicious jail."""
    if not _fail2ban_installed() or not _fail2ban_active():
        return jsonify({"success": False, "error": "fail2ban is not installed/active."}), 400

    data = request.get_json(silent=True) or {}
    ip_address = (data.get("ip_address") or "").strip()

    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        return jsonify({"success": False, "error": "A valid IP address is required."}), 400

    if "eas-station-malicious" not in _active_eas_jails():
        return jsonify({
            "success": False,
            "error": "The eas-station-malicious jail is not active. Apply configuration first.",
        }), 400

    ok, output = _run(["fail2ban-client", "set", "eas-station-malicious", "banip", ip_address])
    if not ok:
        return jsonify({"success": False, "error": output}), 500

    logger.info("Manually banned %s in eas-station-malicious", ip_address)
    return jsonify({"success": True, "message": f"Banned {ip_address}."})


def register_fail2ban_routes(app, logger_):
    app.register_blueprint(fail2ban_bp)
    logger_.info("fail2ban management routes registered")
