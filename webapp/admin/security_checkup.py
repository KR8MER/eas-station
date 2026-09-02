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

Security Checkup: detects a host missing the baseline UFW firewall
install.sh has configured automatically since v2.19.7, and repairs it
on request.

Why this exists: update.sh only updates the application -- it never re-runs
install.sh's one-time host provisioning. A deployment first installed before
v2.19.7 (or one where UFW was later removed) silently stays without a
firewall through every subsequent update, no matter how current the
application code is. That gap was found and fixed by hand on one such
deployment; this makes the same check (and fix) available to every
deployment from the web UI, with no SSH required, instead of relying on an
operator having read docs/troubleshooting/FIREWALL_REQUIREMENTS.md.

This intentionally only reproduces install.sh's own baseline (default-deny
incoming, 22/80/443 allowed, enabled) -- it does not touch or remove any
rule an operator has added beyond that baseline (Icecast's 8000, pgweb's
LAN-restricted 8081, etc.); those stay exactly as configured.

fail2ban's actual jail-load state is already tracked accurately by
webapp.admin.fail2ban._status() (see EAS_JAIL / actuator_jail_loaded there)
-- this module reuses that rather than duplicating it, and only adds the one
check that had no existing detection anywhere: the firewall baseline itself.
"""

import logging
import re
import shutil
import subprocess

from flask import Blueprint, jsonify

from app_core.auth.roles import require_permission

logger = logging.getLogger(__name__)

security_checkup_bp = Blueprint(
    "security_checkup", __name__, url_prefix="/admin/security-checkup"
)

_BASELINE_PORTS = ("22", "80", "443")


def _run(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a privileged command via sudo. Returns (success, output).

    Mirrors webapp.admin.fail2ban._run() -- -n so a missing NOPASSWD sudoers
    entry fails immediately with a clear message instead of hanging the
    request until it times out.
    """
    try:
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


def _ufw_installed() -> bool:
    return shutil.which("ufw") is not None


def parse_ufw_status(output: str) -> dict:
    """Parse `ufw status verbose` output into a structured summary.

    Pure function (no subprocess call) so the parsing logic itself is
    directly unit-testable against captured real output.
    """
    active = bool(re.search(r"^Status:\s*active\s*$", output, re.MULTILINE))
    default_deny_incoming = bool(
        re.search(r"^Default:\s*deny\s*\(incoming\)", output, re.MULTILINE)
    )
    allowed_ports = set()
    for line in output.splitlines():
        match = re.match(r"^(\d+)(?:/(tcp|udp))?\s+ALLOW\s+IN\s+", line.strip())
        if match:
            allowed_ports.add(match.group(1))
    missing_baseline = [p for p in _BASELINE_PORTS if p not in allowed_ports]
    return {
        "active": active,
        "default_deny_incoming": default_deny_incoming,
        "allowed_ports": sorted(allowed_ports, key=int),
        "missing_baseline_ports": missing_baseline,
        "raw": output,
    }


def _ufw_status() -> dict:
    if not _ufw_installed():
        return {
            "installed": False,
            "active": False,
            "default_deny_incoming": False,
            "allowed_ports": [],
            "missing_baseline_ports": list(_BASELINE_PORTS),
            "raw": "",
        }
    ok, output = _run(["ufw", "status", "verbose"])
    parsed = parse_ufw_status(output if ok else "")
    parsed["installed"] = True
    if not ok:
        parsed["error"] = output
    return parsed


def _build_checks() -> dict:
    """Aggregate every checkup item into one status payload for the UI."""
    from webapp.admin.fail2ban import _status as _fail2ban_status

    ufw = _ufw_status()
    fail2ban = _fail2ban_status()

    ufw_ok = ufw["installed"] and ufw["active"] and ufw["default_deny_incoming"] and not ufw["missing_baseline_ports"]
    if not ufw["installed"]:
        ufw_detail = "UFW is not installed on this host. No firewall is filtering incoming traffic at all."
    elif not ufw["active"]:
        ufw_detail = "UFW is installed but not active. No firewall is currently filtering incoming traffic."
    elif not ufw["default_deny_incoming"]:
        ufw_detail = "UFW is active but its default incoming policy is not deny — unlisted ports may be reachable."
    elif ufw["missing_baseline_ports"]:
        ufw_detail = f"UFW is active but missing the baseline allow rule(s) for port(s) {', '.join(ufw['missing_baseline_ports'])}."
    else:
        ufw_detail = f"UFW active, default-deny-incoming, baseline ports allowed. {len(ufw['allowed_ports'])} port(s)/rules configured."

    fail2ban_ok = fail2ban["installed"] and fail2ban["active"] and (
        not fail2ban["enforcement_enabled"] or fail2ban["actuator_jail_loaded"]
    )
    if not fail2ban["installed"]:
        fail2ban_detail = "fail2ban is not installed."
    elif not fail2ban["active"]:
        fail2ban_detail = "fail2ban is installed but not running."
    elif fail2ban["enforcement_enabled"] and not fail2ban["actuator_jail_loaded"]:
        fail2ban_detail = (
            "Enforcement is turned on in settings, but the eas-station jail never loaded — "
            "bans are NOT being mirrored to the host firewall."
            + (f" ({fail2ban['actuator_error']})" if fail2ban.get("actuator_error") else "")
        )
    elif not fail2ban["enforcement_enabled"]:
        fail2ban_detail = "fail2ban is running, but host-firewall enforcement of the ban list is turned off (Security Center → Host Firewall tab)."
    else:
        fail2ban_detail = f"fail2ban running, eas-station jail loaded, {fail2ban['firewall_ban_count']} ban(s) mirrored."

    return {
        "checks": [
            {
                "id": "ufw",
                "label": "Host firewall (UFW)",
                "ok": ufw_ok,
                "detail": ufw_detail,
                "fixable": not ufw_ok,
                "fix_endpoint": "/admin/security-checkup/fix-ufw",
            },
            {
                "id": "fail2ban",
                "label": "Ban-list firewall enforcement (fail2ban)",
                "ok": fail2ban_ok,
                "detail": fail2ban_detail,
                "fixable": False,
                "fix_hint": "Configure and Apply on the Host Firewall tab.",
            },
        ],
        "ufw": ufw,
        "fail2ban": fail2ban,
    }


@security_checkup_bp.route("/status", methods=["GET"])
@require_permission("system.configure")
def checkup_status():
    return jsonify(_build_checks())


@security_checkup_bp.route("/fix-ufw", methods=["POST"])
@require_permission("system.configure")
def fix_ufw():
    """Reproduce install.sh's Step 11 baseline: default-deny incoming,
    22/80/443 allowed, outgoing allowed, enabled. Idempotent -- safe to run
    on a host that already has some or all of this configured; existing
    rules beyond this baseline (Icecast, pgweb, etc.) are untouched.
    """
    sudoers_hint = (
        " This usually means the host's sudoers is out of date — "
        "run 'sudo bash update.sh' to redeploy it, then apply again."
    )

    if not _ufw_installed():
        ok, out = _run(["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "ufw"])
        if not ok:
            return jsonify({"success": False, "error": f"Failed to install ufw: {out}.{sudoers_hint}"}), 500

    steps = [
        (["ufw", "default", "deny", "incoming"], "set default-deny-incoming"),
        (["ufw", "default", "allow", "outgoing"], "set default-allow-outgoing"),
        (["ufw", "allow", "22/tcp"], "allow 22/tcp"),
        (["ufw", "allow", "80/tcp"], "allow 80/tcp"),
        (["ufw", "allow", "443/tcp"], "allow 443/tcp"),
        (["ufw", "--force", "enable"], "enable ufw"),
    ]
    for cmd, description in steps:
        ok, out = _run(cmd)
        if not ok:
            logger.error("Security Checkup: failed to %s: %s", description, out)
            return jsonify({
                "success": False,
                "error": f"Failed to {description}: {out}.{sudoers_hint}",
            }), 500

    logger.info("Security Checkup: UFW baseline applied")
    return jsonify({"success": True, "message": "UFW baseline applied.", **_build_checks()})


def register_security_checkup_routes(app, logger_):
    app.register_blueprint(security_checkup_bp)
    logger_.info("Security checkup routes registered")
