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

LAN NTP server management: lets an admin serve chrony's already-synced time
to a chosen set of subnets, from the web UI, with no SSH required.

Why this exists: chrony is installed and running on every deployment (it's
the box's own time sync, and on GPS-HAT hardware the stratum-1 source), but
by default it only ever acts as a *client* -- nothing in chrony.conf grants
any subnet permission to query it, so a request from a LAN device gets
silently ignored. Which subnets should be trusted is inherently a
per-deployment decision (a home LAN, an office VLAN, a Tailscale range, or
nothing at all) with no correct default, so this is admin-configured rather
than something install.sh could set up once.

Deliberately stateless like webapp.admin.mail_server: the *file on disk* --
a dedicated chrony conf.d fragment, never chrony.conf itself -- is the
single source of truth, read back fresh on every status check rather than
mirrored into a DB row that could drift from what's actually applied. The
firewall side follows the same idempotent, least-disturbance pattern as
webapp.admin.security_checkup's UFW fix: every rule this module creates is
tagged with a fixed comment, so reconciliation only ever touches rules it
tagged itself, never anything an operator added by hand (Icecast's 8000,
pgweb's 8081, etc.).
"""

import ipaddress
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission

logger = logging.getLogger(__name__)

ntp_server_bp = Blueprint("ntp_server", __name__, url_prefix="/admin/ntp-server")

_CHRONY_SERVICE = "chrony"
_CHRONY_CONF_FILE = Path("/etc/chrony/conf.d/eas-station-ntp-server.conf")
_NTP_PORT = "123"

# Fixed, literal tag -- never derived from user input -- so the sudoers
# entries for `ufw allow`/`ufw delete allow` can be scoped to this exact
# comment rather than an open wildcard, and so reconciliation can tell "a
# rule this feature created" apart from anything an operator added by hand.
_UFW_TAG = "eas-station-ntp-server"

_UFW_RULE_RE = re.compile(
    r"^(\d+)/udp\s+ALLOW\s+IN\s+(\S+)\s+#\s*(.+)$", re.MULTILINE
)
_CONF_ALLOW_RE = re.compile(r"^allow\s+(\S+)\s*$", re.MULTILINE)


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


def _validate_cidr(value: str) -> str:
    """Normalize and validate one subnet. Raises ValueError on anything
    that isn't a real IPv4/IPv6 network or host address.
    """
    value = (value or "").strip()
    if not value:
        raise ValueError("empty subnet")
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(f"'{value}' is not a valid IP address or CIDR range") from exc
    return str(network)


def _chronyd_installed() -> bool:
    return shutil.which("chronyd") is not None


def _chronyd_active() -> bool:
    ok, _ = _run(["systemctl", "is-active", "--quiet", _CHRONY_SERVICE])
    return ok


def _configured_subnets() -> list[str]:
    """Subnets currently allowed, read straight from our conf.d fragment --
    not a DB record, so this can never drift from what chrony actually has
    loaded (short of the operator hand-editing the file, which they're free
    to do and this will faithfully reflect back).
    """
    try:
        text = _CHRONY_CONF_FILE.read_text()
    except OSError:
        return []
    return _CONF_ALLOW_RE.findall(text)


def _firewall_subnets() -> list[str]:
    """Subnets with a UFW allow rule for udp/123 tagged by this feature."""
    ok, output = _run(["ufw", "status", "verbose"])
    if not ok:
        return []
    subnets = []
    for port, source, comment in _UFW_RULE_RE.findall(output):
        if port == _NTP_PORT and comment.strip() == _UFW_TAG:
            subnets.append(source)
    return subnets


def _detect_local_subnets() -> list[str]:
    """Best-effort suggestions for the admin: the actual subnet(s) this
    box's own non-loopback interfaces sit on. Purely informational --
    never applied automatically, since a cloud box's "local" interface
    subnet is usually a provider-internal range, not the operator's LAN.
    """
    try:
        result = subprocess.run(
            ["ip", "-json", "addr", "show"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        import json
        interfaces = json.loads(result.stdout or "[]")
    except Exception:
        return []

    subnets: list[str] = []
    for iface in interfaces:
        if "LOOPBACK" in (iface.get("flags") or []):
            continue
        for addr in iface.get("addr_info") or []:
            if addr.get("family") != "inet":
                continue
            local = addr.get("local")
            prefixlen = addr.get("prefixlen")
            if not local or prefixlen is None:
                continue
            try:
                network = ipaddress.ip_interface(f"{local}/{prefixlen}").network
            except ValueError:
                continue
            candidate = str(network)
            if candidate not in subnets:
                subnets.append(candidate)
    return subnets


def _format_last_seen(raw: str) -> str:
    """`chronyc clients`' NTP "Last" column: seconds since that client's most
    recent request, "-" if it has never made one. Older/newer chrony builds
    are inconsistent about pre-formatting large values with a unit suffix
    (e.g. "12m") -- pass anything that isn't a bare integer through as-is
    rather than mis-parsing it.
    """
    if raw == "-":
        return "never"
    try:
        seconds = int(raw)
    except ValueError:
        return raw
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _client_summary() -> dict[str, Any]:
    """A quick "is this actually being used" signal via `chronyc clients`:
    which hosts have queried this server for time, and how recently.
    Best-effort -- absent/parsed-empty is not treated as an error, since a
    freshly-enabled server legitimately has zero clients yet.
    """
    ok, output = _run(["chronyc", "clients"], timeout=5)
    if not ok:
        return {"available": False, "clients": []}

    clients = []
    for line in output.splitlines()[2:]:  # skip the two header lines
        # Hostname, NTP, Drop, Int, IntL, Last, Cmd, Drop, Int, Last -- the
        # 6th column (index 5) is time since this client's last plain-NTP
        # request, which is what matters here (the last two columns cover
        # the separate chronyc *command* protocol, e.g. this very query).
        parts = line.split()
        if len(parts) < 6:
            continue
        host = parts[0]
        if host == "127.0.0.1" or host == "localhost":
            continue
        clients.append({"host": host, "last_seen": _format_last_seen(parts[5])})
    return {"available": True, "clients": clients}


def _ntp_status() -> dict[str, Any]:
    installed = _chronyd_installed()
    active = _chronyd_active() if installed else False
    configured = _configured_subnets()
    firewall = _firewall_subnets()

    return {
        "installed": installed,
        "active": active,
        "enabled": bool(configured),
        "configured_subnets": configured,
        "firewall_subnets": firewall,
        "firewall_in_sync": set(configured) == set(firewall),
        "detected_local_subnets": _detect_local_subnets(),
        "clients": _client_summary(),
    }


def _render_conf(subnets: list[str]) -> str:
    if not subnets:
        return (
            "# Managed by EAS Station -- LAN NTP Server (Settings -> Network -> NTP Server).\n"
            "# No subnets currently allowed; this host only syncs its own clock.\n"
        )
    lines = [
        "# Managed by EAS Station -- LAN NTP Server (Settings -> Network -> NTP Server).",
        "# Regenerated on every Apply; hand edits here will be overwritten on next Apply.",
        "",
    ]
    for subnet in subnets:
        lines.append(f"allow {subnet}")
    lines.append("")
    # Lets this box keep answering client queries with its own (unsynced-
    # looking but still locally consistent) clock during a brief upstream
    # outage, instead of refusing all requests the moment it loses its own
    # sources. Harmless while a real source is selected -- chrony only
    # falls back to this when nothing else is available.
    lines.append("local stratum 10")
    lines.append("")
    return "\n".join(lines)


@ntp_server_bp.route("/", methods=["GET"])
@require_auth
@require_permission("system.configure")
def ntp_server_page():
    return render_template("admin/ntp_server.html", status=_ntp_status())


@ntp_server_bp.route("/status", methods=["GET"])
@require_auth
@require_permission("system.configure")
def ntp_server_status():
    return jsonify(_ntp_status())


@ntp_server_bp.route("/configure", methods=["POST"])
@require_auth
@require_permission("system.configure")
def configure_ntp_server():
    if not _chronyd_installed():
        return jsonify({"success": False, "error": "chrony is not installed on this host."}), 400

    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    raw_subnets = data.get("subnets") or []
    if not isinstance(raw_subnets, list):
        return jsonify({"success": False, "error": "subnets must be a list."}), 400

    desired: list[str] = []
    if enabled:
        if not raw_subnets:
            return jsonify({
                "success": False,
                "error": "At least one subnet is required to enable the NTP server.",
            }), 400
        try:
            for value in raw_subnets:
                normalized = _validate_cidr(value)
                if normalized not in desired:
                    desired.append(normalized)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400

    # Write the conf.d fragment (web process can't write /etc/chrony directly).
    try:
        proc = subprocess.run(
            ["sudo", "tee", str(_CHRONY_CONF_FILE)],
            input=_render_conf(desired),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip())
    except Exception as exc:
        logger.error("Failed to write chrony NTP-server config: %s", exc)
        return jsonify({"success": False, "error": "Failed to write chrony configuration. Check server logs."}), 500

    ok_restart, restart_out = _run(["systemctl", "restart", _CHRONY_SERVICE])
    if not ok_restart:
        logger.error("chrony restart failed: %s", restart_out)
        return jsonify({"success": False, "error": f"Config written but chrony restart failed: {restart_out}"}), 500

    # Reconcile UFW: touch only rules this feature tagged, add what's
    # missing, remove what's no longer desired -- an operator's own rules
    # for other ports/services are never inspected or altered.
    current = set(_firewall_subnets())
    desired_set = set(desired)

    for stale in current - desired_set:
        ok, out = _run(["ufw", "delete", "allow", "from", stale, "to", "any", "port", _NTP_PORT, "proto", "udp"])
        if not ok:
            logger.warning("Failed to remove stale NTP firewall rule for %s: %s", stale, out)

    for missing in desired_set - current:
        ok, out = _run([
            "ufw", "allow", "from", missing, "to", "any", "port", _NTP_PORT, "proto", "udp",
            "comment", _UFW_TAG,
        ])
        if not ok:
            logger.warning("Failed to add NTP firewall rule for %s: %s", missing, out)

    logger.info("NTP server %s for subnets: %s", "enabled" if desired else "disabled", desired)
    message = (
        f"NTP server enabled for {len(desired)} subnet(s)." if desired
        else "NTP server disabled -- no subnets are allowed to query this host."
    )
    return jsonify({"success": True, "message": message, **_ntp_status()})


def register_ntp_server_routes(app, logger_):
    app.register_blueprint(ntp_server_bp)
    logger_.info("NTP server management routes registered")
