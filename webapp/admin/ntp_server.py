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

import concurrent.futures
import logging
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.network_info import detect_local_subnets as _detect_local_subnets
from app_core.network_info import validate_cidr as _validate_cidr

logger = logging.getLogger(__name__)

ntp_server_bp = Blueprint("ntp_server", __name__, url_prefix="/admin/ntp-server")

_CHRONY_SERVICE = "chrony"
_CHRONY_CONF_FILE = Path("/etc/chrony/conf.d/eas-station-ntp-server.conf")
_NTP_PORT = "123"

# Capped so one client with no PTR record (very common on a home LAN -- most
# phones/laptops/IoT devices never get one) can't stall the whole clients
# list. Best-effort display only, never a correctness concern.
_PTR_LOOKUP_TIMEOUT_SECONDS = 1.0

# NetBIOS Node Status (UDP/137) fallback timeout, tried only when PTR comes
# up empty. Kept short since it's the second of two sequential lookups per
# client.
_NETBIOS_LOOKUP_TIMEOUT_SECONDS = 0.5

# Hostname lookups for every client run concurrently (each one is a
# best-effort network round trip that can take up to _PTR_LOOKUP_TIMEOUT_SECONDS
# + _NETBIOS_LOOKUP_TIMEOUT_SECONDS on its own) so the page doesn't get
# slower every time a new device shows up in the clients list.
_MAX_CONCURRENT_HOSTNAME_LOOKUPS = 8

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


def _reverse_dns(ip: str) -> str | None:
    """Best-effort PTR lookup for the clients list. None if there's no
    record, the lookup errors, or it doesn't finish within
    _PTR_LOOKUP_TIMEOUT_SECONDS -- absence is normal (most LAN clients,
    especially phones and IoT devices, are never registered in reverse DNS,
    and a deployment whose resolver is a public DoH/DoT forwarder has no
    PTR data for RFC1918 addresses at all) and never treated as a failure
    worth logging.

    socket.gethostbyaddr() has no per-call timeout, only the process-global
    default, so concurrent lookups (see _client_summary()) briefly share
    whatever value the most recent setter installed. Harmless here since
    every caller sets the same constant before its own call and restores the
    same prior value after -- there's no case where one lookup's timeout
    could leak a *different* value into another's.
    """
    prior_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(_PTR_LOOKUP_TIMEOUT_SECONDS)
        hostname, _aliases, _addrs = socket.gethostbyaddr(ip)
        return hostname
    except (socket.herror, socket.gaierror, OSError):
        return None
    finally:
        socket.setdefaulttimeout(prior_timeout)


def _netbios_encode_wildcard() -> bytes:
    """RFC 1002 first-level NetBIOS name encoding of the 16-byte wildcard
    name "*" (padded with NULs) used in a Node Status query -- it asks
    whatever's listening on UDP/137 to identify itself, regardless of what
    name it's actually registered under.
    """
    padded = b"*" + b"\x00" * 15
    encoded = bytearray()
    for byte in padded:
        encoded.append(0x41 + (byte >> 4))
        encoded.append(0x41 + (byte & 0x0F))
    return bytes(encoded)


def _parse_netbios_response(data: bytes) -> str | None:
    """Pull the machine's own "unique" (non-group) NetBIOS name -- suffix
    0x00, the standard computer-name record -- out of a Node Status
    response. Best-effort: any malformed/short packet just yields None
    rather than raising, since this is parsing an untrusted UDP reply.
    """
    if len(data) < 13:
        return None
    pos = 12
    if data[pos] == 0xC0:  # name compression pointer, 2 bytes
        pos += 2
    else:  # length-prefixed encoded name: 1 length byte + bytes + null
        name_len = data[pos]
        pos += 1 + name_len + 1
    pos += 4 + 4  # TYPE + CLASS, then TTL
    if pos + 2 > len(data):
        return None
    pos += 2  # RDLENGTH -- unused, the per-name loop below is self-limiting
    if pos >= len(data):
        return None
    num_names = data[pos]
    pos += 1
    for _ in range(num_names):
        if pos + 18 > len(data):
            break
        raw_name, suffix = data[pos:pos + 15], data[pos + 15]
        flags = int.from_bytes(data[pos + 16:pos + 18], "big")
        pos += 18
        if suffix != 0x00 or flags & 0x8000:  # not the computer name, or a group name
            continue
        name = raw_name.decode("ascii", errors="replace").rstrip(" \x00")
        if name:
            return name
    return None


def _netbios_name(ip: str) -> str | None:
    """Best-effort NetBIOS (NBT-NS) Node Status query, UDP/137 -- the
    traditional way LAN tools get a Windows PC's real computer name when
    there's no PTR record for it, since Windows doesn't register itself in
    DNS by default. None for anything that doesn't answer: non-Windows
    devices, or a Windows PC with its firewall blocking 137/udp.
    """
    query = (
        b"\x13\x37"  # transaction ID -- arbitrary, fixed
        b"\x00\x00"  # flags: standard query
        b"\x00\x01"  # QDCOUNT=1
        b"\x00\x00\x00\x00\x00\x00"  # ANCOUNT/NSCOUNT/ARCOUNT=0
        + bytes([0x20]) + _netbios_encode_wildcard() + b"\x00"  # question name
        b"\x00\x21"  # QTYPE = NBSTAT
        b"\x00\x01"  # QCLASS = IN
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(_NETBIOS_LOOKUP_TIMEOUT_SECONDS)
        sock.sendto(query, (ip, 137))
        data, _addr = sock.recvfrom(1024)
        return _parse_netbios_response(data)
    except OSError:
        return None
    finally:
        sock.close()


def _lookup_client_hostname(ip: str) -> str | None:
    """Best-effort hostname for one clients-list entry: reverse DNS first,
    then NetBIOS as a fallback since a deployment's resolver commonly has no
    PTR records for LAN addresses at all (see _reverse_dns) while a Windows
    PC will usually still answer a Node Status query directly.
    """
    return _reverse_dns(ip) or _netbios_name(ip)


def _client_summary() -> dict[str, Any]:
    """A quick "is this actually being used" signal via `chronyc clients`:
    which hosts have queried this server for time, and how recently.
    Best-effort -- absent/parsed-empty is not treated as an error, since a
    freshly-enabled server legitimately has zero clients yet.
    """
    # -n: raw IPs only. Without it, chronyc does its own reverse-DNS
    # resolution and truncates long names to fit its fixed-width column --
    # both wrong here, since the parser below expects column 0 to be a
    # numeric address and this module does its own (untruncated, NetBIOS-
    # backed) hostname lookup per client afterward.
    ok, output = _run(["chronyc", "-n", "clients"], timeout=5)
    if not ok:
        # Distinguishable from a genuinely empty list in the logs -- the UI
        # itself intentionally shows the same "no clients yet" copy either
        # way (see templates/admin/ntp_server.html), since a freshly-enabled
        # server legitimately has zero clients and that shouldn't read as an
        # error. But a real failure (e.g. a missing sandbox capability) must
        # not vanish silently -- it did exactly that until this line existed.
        logger.warning("chronyc clients failed, reporting zero clients: %s", output)
        return {"available": False, "clients": []}

    rows: list[tuple[str, str]] = []
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
        rows.append((host, parts[5]))

    # Hostname lookups run concurrently -- each is a best-effort network
    # round trip (PTR, then a NetBIOS fallback) that can take up to
    # roughly a second and a half on its own, and doing them one at a time
    # would make the page progressively slower as more devices show up.
    hostnames: dict[str, str | None] = {}
    if rows:
        hosts = [host for host, _last_seen in rows]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(hosts), _MAX_CONCURRENT_HOSTNAME_LOOKUPS)
        ) as pool:
            future_to_host = {pool.submit(_lookup_client_hostname, host): host for host in hosts}
            for future in concurrent.futures.as_completed(future_to_host):
                host = future_to_host[future]
                try:
                    hostnames[host] = future.result()
                except Exception as exc:  # best-effort display only -- never fail the page over it
                    logger.warning("Hostname lookup failed for %s: %s", host, exc)
                    hostnames[host] = None

    clients = [
        {"host": host, "hostname": hostnames.get(host), "last_seen": _format_last_seen(last_seen)}
        for host, last_seen in rows
    ]
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


def _write_chrony_conf(content: str, *, retries: int = 1, retry_delay: float = 1.0) -> tuple[bool, str]:
    """Write *content* to the chrony conf.d fragment via sudo tee, retrying
    once after a brief pause on failure.

    Confirmed live 2026-09-02: this exact write hit a transient "Read-only
    file system" error for about 15 minutes right after this feature's
    first deploy, then self-resolved on its own -- no code change, no
    repeat since. The exact trigger was never confirmed (it wasn't real
    filesystem corruption: no matching kernel/dmesg errors, and the target
    path is directly writable when tested from inside this very service's
    mount namespace afterward), so this can't fix a specific root cause --
    but a short retry costs nothing on the common (successful) case and may
    ride out a similarly brief blip without forcing the admin to notice the
    error and click Apply again themselves.

    Returns ``(success, last_error)`` -- *last_error* is the stripped
    stderr/exception text from the final attempt, empty on success.
    """
    last_error = ""
    for attempt in range(retries + 1):
        try:
            proc = subprocess.run(
                ["sudo", "tee", str(_CHRONY_CONF_FILE)],
                input=content,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                return True, ""
            last_error = proc.stderr.strip()
        except Exception as exc:
            last_error = str(exc)

        if attempt < retries:
            logger.warning(
                "Chrony NTP-server config write failed (attempt %d/%d): %s -- retrying",
                attempt + 1, retries + 1, last_error,
            )
            time.sleep(retry_delay)

    logger.error(
        "Failed to write chrony NTP-server config after %d attempt(s): %s",
        retries + 1, last_error,
    )
    return False, last_error


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
    ok_write, _write_error = _write_chrony_conf(_render_conf(desired))
    if not ok_write:
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
