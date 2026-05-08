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

Local Postfix mail server management routes.
"""

import logging
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import NotificationSettings

logger = logging.getLogger(__name__)

mail_server_bp = Blueprint("mail_server", __name__, url_prefix="/admin/mail-server")

# Postfix main.cf template for direct outbound delivery (no relay host).
# Bound to loopback only — EAS Station connects via smtp://localhost:25.
_POSTFIX_MAIN_CF = """\
# Postfix main.cf — managed by EAS Station
# Generated: {generated}
# ──────────────────────────────────────────────────────────────────────────────
# Identity
myhostname = {myhostname}
myorigin   = $myhostname

# Local delivery: accept only mail destined for this host itself
mydestination = $myhostname, localhost.$mydomain, localhost

# Direct internet delivery (no relay host)
relayhost =

# Trusted local networks only — do NOT relay for external hosts
mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128

# Only listen on the loopback interface
inet_interfaces = loopback-only
inet_protocols  = all

# Opportunistic TLS for outbound connections
smtp_tls_security_level = may
smtp_tls_loglevel       = 1

# No local mailbox delivery (alerts go outbound only)
mailbox_size_limit  = 0
message_size_limit  = 10240000

# Sender address shown on outbound mail
sender_canonical_maps = static:{from_address}

# Postfix compatibility
compatibility_level = 3.6
"""


# ── Helpers ──────────────────────────────────────────────────────────────────

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
    except Exception as exc:
        return False, str(exc)


def _postfix_installed() -> bool:
    return shutil.which("postfix") is not None


def _postfix_active() -> bool:
    ok, out = _run(["systemctl", "is-active", "--quiet", "postfix"])
    return ok


def _port25_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 25), timeout=2):
            return True
    except OSError:
        return False


def _detect_hostname() -> str:
    try:
        return socket.getfqdn()
    except Exception:
        return socket.gethostname()


def _postfix_status() -> dict:
    installed = _postfix_installed()
    active = _postfix_active() if installed else False
    port_open = _port25_open()

    # Read current myhostname from postconf if installed
    current_hostname = ""
    current_from = ""
    if installed:
        ok, out = _run(["postconf", "myhostname"])
        if ok and "=" in out:
            current_hostname = out.split("=", 1)[1].strip()
        ok2, out2 = _run(["postconf", "sender_canonical_maps"])
        if ok2 and "static:" in out2:
            current_from = out2.split("static:", 1)[1].strip()

    return {
        "installed": installed,
        "active": active,
        "port_open": port_open,
        "current_hostname": current_hostname,
        "current_from": current_from,
        "detected_hostname": _detect_hostname(),
        "smtp_url": "smtp://localhost:25" if port_open else "",
    }


def _sanitize_postfix_value(value: str) -> str:
    """Strip characters that would allow Postfix config injection (newlines, null bytes)."""
    sanitized = value.replace('\r', '').replace('\n', '').replace('\x00', '')
    if sanitized != value:
        raise ValueError(f"Invalid characters in Postfix configuration value")
    return sanitized


# ── Routes ────────────────────────────────────────────────────────────────────

@mail_server_bp.route("/", methods=["GET"])
@require_auth
@require_permission("system.configure")
def mail_server_page():
    status = _postfix_status()
    return render_template("admin/mail_server.html", status=status)


@mail_server_bp.route("/status", methods=["GET"])
@require_auth
@require_permission("system.configure")
def mail_server_status():
    return jsonify(_postfix_status())


@mail_server_bp.route("/install", methods=["POST"])
@require_auth
@require_permission("system.configure")
def install_postfix():
    """Install Postfix via apt-get (non-interactive)."""
    if _postfix_installed():
        return jsonify({"success": True, "message": "Postfix is already installed."})

    # DEBIAN_FRONTEND=noninteractive suppresses debconf prompts.
    # Postfix is installed with 'No configuration' type so we write main.cf ourselves.
    ok, output = _run(
        ["env", "DEBIAN_FRONTEND=noninteractive",
         "apt-get", "install", "-y", "postfix", "libsasl2-modules"],
        timeout=120,
    )
    if not ok:
        logger.error("Postfix install failed: %s", output)
        return jsonify({"success": False, "error": output}), 500

    logger.info("Postfix installed successfully")
    return jsonify({"success": True, "message": "Postfix installed successfully."})


@mail_server_bp.route("/configure", methods=["POST"])
@require_auth
@require_permission("system.configure")
def configure_postfix():
    """Write Postfix main.cf and restart the service."""
    if not _postfix_installed():
        return jsonify({"success": False, "error": "Postfix is not installed."}), 400

    data = request.get_json(silent=True) or {}
    hostname = (data.get("hostname") or _detect_hostname()).strip()
    from_address = (data.get("from_address") or f"alerts@{hostname}").strip()

    if not hostname:
        return jsonify({"success": False, "error": "Hostname is required."}), 400

    try:
        hostname = _sanitize_postfix_value(hostname)
        from_address = _sanitize_postfix_value(from_address)
    except ValueError:
        return jsonify({"success": False, "error": "Hostname and from address must not contain newlines or null bytes."}), 400

    config_content = _POSTFIX_MAIN_CF.format(
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        myhostname=hostname,
        from_address=from_address,
    )

    # Write config via sudo tee (web process cannot write /etc/postfix directly)
    try:
        proc = subprocess.run(
            ["sudo", "tee", "/etc/postfix/main.cf"],
            input=config_content,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip())
    except Exception as exc:
        logger.error("Failed to write Postfix config: %s", exc)
        return jsonify({"success": False, "error": "Failed to write Postfix configuration. Check server logs."}), 500

    # Validate the new config before restarting
    ok_check, check_out = _run(["postfix", "check"])
    if not ok_check:
        logger.warning("postfix check warnings: %s", check_out)

    # Enable and restart
    _run(["systemctl", "enable", "postfix"])
    ok_restart, restart_out = _run(["systemctl", "restart", "postfix"])
    if not ok_restart:
        logger.error("Postfix restart failed: %s", restart_out)
        return jsonify({"success": False, "error": f"Config written but restart failed: {restart_out}"}), 500

    logger.info("Postfix configured (hostname=%s, from=%s) and restarted", hostname, from_address)
    return jsonify({
        "success": True,
        "message": f"Postfix configured and restarted. Sending as {from_address}.",
        "smtp_url": "smtp://localhost:25",
    })


@mail_server_bp.route("/service", methods=["POST"])
@require_auth
@require_permission("system.configure")
def postfix_service():
    """Start, stop, or restart the Postfix service."""
    data = request.get_json(silent=True) or {}
    action = data.get("action", "").strip().lower()

    if action not in ("start", "stop", "restart"):
        return jsonify({"success": False, "error": "action must be start, stop, or restart"}), 400

    ok, output = _run(["systemctl", action, "postfix"])
    if not ok:
        return jsonify({"success": False, "error": output}), 500

    return jsonify({"success": True, "message": f"Postfix {action}ed.", "output": output})


@mail_server_bp.route("/apply-to-notifications", methods=["POST"])
@require_auth
@require_permission("system.configure")
def apply_to_notifications():
    """Set the notification SMTP config to use local Postfix on localhost:25."""
    if not _port25_open():
        return jsonify({
            "success": False,
            "error": "Postfix is not listening on localhost:25. "
                     "Install and configure it first.",
        }), 400

    try:
        settings = NotificationSettings.query.first()
        if not settings:
            settings = NotificationSettings(
                id=1, email_enabled=False,
                smtp_host="", smtp_port=587, smtp_username="",
                smtp_password="", smtp_security="starttls",
                compliance_alert_emails=[], alert_emails=[],
                email_attach_audio=False, sms_enabled=False,
                sms_provider="twilio", sms_account_sid="",
                sms_auth_token="", sms_from_number="", sms_recipients=[],
            )
            db.session.add(settings)

        settings.smtp_host = "localhost"
        settings.smtp_port = 25
        settings.smtp_username = ""
        settings.smtp_password = ""
        settings.smtp_security = "none"
        db.session.commit()
        logger.info("Notification SMTP set to localhost:25 (no auth, no TLS)")
        return jsonify({
            "success": True,
            "message": "Notification settings updated to use local Postfix (localhost:25).",
        })
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.error("DB error updating notification settings: %s", exc)
        return jsonify({"success": False, "error": "Database error"}), 500


def register_mail_server_routes(app, logger_):
    app.register_blueprint(mail_server_bp)
    logger_.info("Mail server management routes registered")
