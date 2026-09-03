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

Firewall: one page for every host-firewall (UFW) decision this app makes,
instead of a rule-management widget bolted onto each feature's own settings
page.

Why this exists: the baseline UFW check already lived in
webapp.admin.security_checkup, and the LAN NTP server
(webapp.admin.ntp_server) grew its own inline "which subnets get a firewall
hole" widget because opening port 123/udp is *part of* configuring that
feature. Icecast's port needed exactly the same kind of rule (see
docs/troubleshooting/FIREWALL_REQUIREMENTS.md's "Router Port Forwarding"
section for the WAN side of this) and adding a second scattered, bespoke
widget for it -- rather than one place an operator learns once -- was the
wrong direction. This module is that one place.

It does not re-implement rule application: baseline fixes still go through
security_checkup.fix_ufw(), and NTP subnet changes still go through
ntp_server.configure_ntp_server() (that endpoint has to run *together* with
writing chrony's own config, so splitting it apart would let the two drift).
Icecast's port is the one rule genuinely independent of any other config
write, so its reconciliation lives here.
"""

import logging
import re
import subprocess

from flask import Blueprint, jsonify, render_template, request

from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.icecast_settings import get_icecast_settings
from app_core.network_info import detect_local_subnets, validate_cidr

logger = logging.getLogger(__name__)

firewall_bp = Blueprint("firewall", __name__, url_prefix="/admin/firewall")

# Fixed, literal tag -- never derived from user input -- so the sudoers
# entries for `ufw allow`/`ufw delete allow` can be scoped to this exact
# comment, and so reconciliation can tell "a rule this feature created"
# apart from anything an operator added by hand.
_ICECAST_UFW_TAG = "eas-station-icecast"

_UFW_TCP_RULE_RE = re.compile(
    r"^(\d+)/tcp\s+ALLOW\s+IN\s+(\S+)\s+#\s*(.+)$", re.MULTILINE
)


def _run(cmd: list[str], timeout: int = 15) -> tuple[bool, str]:
    """Run a privileged command via sudo. Returns (success, output).

    -n: a missing NOPASSWD sudoers entry fails immediately with a clear
    message instead of hanging the request until it times out (same
    reasoning as webapp.admin.fail2ban._run / security_checkup._run).
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


def _icecast_firewall_subnets(port: int) -> list[str]:
    """Subnets with a UFW allow rule for tcp/<port> tagged by this feature."""
    ok, output = _run(["ufw", "status", "verbose"])
    if not ok:
        return []
    subnets = []
    for rule_port, source, comment in _UFW_TCP_RULE_RE.findall(output):
        if rule_port == str(port) and comment.strip() == _ICECAST_UFW_TAG:
            subnets.append(source)
    return subnets


def _icecast_status() -> dict:
    settings = get_icecast_settings()
    port = settings.port or 8000
    firewall_subnets = _icecast_firewall_subnets(port)
    return {
        "enabled": bool(settings.enabled),
        "port": port,
        "firewall_subnets": firewall_subnets,
        "reachable": bool(firewall_subnets),
        "detected_local_subnets": detect_local_subnets(),
    }


@firewall_bp.route("/", methods=["GET"])
@require_auth
@require_permission("system.configure")
def firewall_page():
    from webapp.admin.ntp_server import _ntp_status
    from webapp.admin.security_checkup import _build_checks

    return render_template(
        "admin/firewall.html",
        checkup=_build_checks(),
        ntp=_ntp_status(),
        icecast=_icecast_status(),
    )


@firewall_bp.route("/api/icecast/status", methods=["GET"])
@require_auth
@require_permission("system.configure")
def icecast_firewall_status():
    return jsonify(_icecast_status())


@firewall_bp.route("/api/icecast", methods=["POST"])
@require_auth
@require_permission("system.configure")
def configure_icecast_firewall():
    """Reconcile the tagged UFW rule(s) for Icecast's configured port to
    exactly the subnet list the admin submits here. Idempotent -- safe to
    call repeatedly with the same list.
    """
    settings = get_icecast_settings()
    port = settings.port or 8000

    data = request.get_json(silent=True) or {}
    raw_subnets = data.get("subnets") or []
    if not isinstance(raw_subnets, list):
        return jsonify({"success": False, "error": "subnets must be a list."}), 400

    desired: list[str] = []
    try:
        for value in raw_subnets:
            normalized = validate_cidr(value)
            if normalized not in desired:
                desired.append(normalized)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    current = set(_icecast_firewall_subnets(port))
    desired_set = set(desired)

    for stale in current - desired_set:
        ok, out = _run(["ufw", "delete", "allow", "from", stale, "to", "any", "port", str(port), "proto", "tcp"])
        if not ok:
            logger.warning("Failed to remove stale Icecast firewall rule for %s: %s", stale, out)

    for missing in desired_set - current:
        ok, out = _run([
            "ufw", "allow", "from", missing, "to", "any", "port", str(port), "proto", "tcp",
            "comment", _ICECAST_UFW_TAG,
        ])
        if not ok:
            logger.warning("Failed to add Icecast firewall rule for %s: %s", missing, out)
            return jsonify({
                "success": False,
                "error": f"Failed to allow {missing}: {out}",
                **_icecast_status(),
            }), 500

    logger.info("Icecast firewall (port %s) reconciled to subnets: %s", port, desired)
    message = (
        f"Icecast port {port}/tcp open to {len(desired)} subnet(s)." if desired
        else f"Icecast port {port}/tcp closed -- no subnets are allowed to reach it."
    )
    return jsonify({"success": True, "message": message, **_icecast_status()})


def register_firewall_routes(app, logger_):
    app.register_blueprint(firewall_bp)
