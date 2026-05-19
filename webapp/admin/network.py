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
"""

from __future__ import annotations

"""Network configuration routes for WiFi management.

This module proxies all network management requests to hardware service process,
which has the necessary privileges and DBus access for NetworkManager (nmcli).

In the separated service architecture:
- Web application: Runs Flask web UI (no network privileges)
- Hardware service: Has NET_ADMIN cap and DBus access for nmcli
"""

import re
import subprocess

import requests
from flask import Blueprint, jsonify, request, render_template
from app_core.auth.decorators import require_permission
from app_core.config import HARDWARE_SERVICE_URL

network_bp = Blueprint('network', __name__)


def call_hardware_service(endpoint, method='GET', data=None):
    """Make HTTP request to hardware-service API."""
    try:
        url = f"{HARDWARE_SERVICE_URL}{endpoint}"
        if method == 'GET':
            response = requests.get(url, timeout=30)
        elif method == 'POST':
            response = requests.post(url, json=data, timeout=30)
        else:
            return {'success': False, 'error': f'Unsupported method: {method}'}

        # Return JSON response from hardware-service
        if response.status_code == 200:
            return response.json()
        else:
            return {
                'success': False,
                'error': f'Hardware service returned {response.status_code}',
                'details': response.text
            }

    except requests.Timeout:
        return {
            'success': False,
            'error': 'Hardware service timeout'
        }
    except requests.ConnectionError:
        return {
            'success': False,
            'error': 'Cannot connect to hardware service. Check if hardware service process is running.'
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Hardware service request failed: {e}")
        return {
            'success': False,
            'error': 'Hardware service request failed'
        }


@network_bp.route('/admin/network')
@require_permission('system.configure')
def network_settings():
    """Render the network configuration page."""
    return render_template('admin/network.html')


@network_bp.route('/api/network/status')
@require_permission('system.configure')
def get_network_status():
    """Get current network connection status via hardware-service."""
    return jsonify(call_hardware_service('/api/network/status', method='GET'))


@network_bp.route('/api/network/wifi/scan', methods=['POST'])
@require_permission('system.configure')
def scan_wifi():
    """Scan for available WiFi networks via hardware-service."""
    return jsonify(call_hardware_service('/api/network/scan', method='POST'))


@network_bp.route('/api/network/wifi/connect', methods=['POST'])
@require_permission('system.configure')
def connect_wifi():
    """Connect to a WiFi network via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/connect', method='POST', data=data))


@network_bp.route('/api/network/wifi/disconnect', methods=['POST'])
@require_permission('system.configure')
def disconnect_wifi():
    """Disconnect from current network via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/disconnect', method='POST', data=data))


@network_bp.route('/api/network/wifi/forget', methods=['POST'])
@require_permission('system.configure')
def forget_wifi():
    """Forget a saved network connection via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/forget', method='POST', data=data))


# Phase 2: Core DASDEC3 Network Features

@network_bp.route('/api/network/interfaces')
@require_permission('system.configure')
def get_interfaces():
    """Get all network interfaces (WiFi and Ethernet) via hardware-service.
    
    Returns interface details including device name, type, state, connection,
    and IP addresses for both wireless and wired interfaces.
    """
    return jsonify(call_hardware_service('/api/network/interfaces', method='GET'))


@network_bp.route('/api/network/interface/configure', methods=['POST'])
@require_permission('system.configure')
def configure_interface():
    """Configure network interface via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/interface/configure', method='POST', data=data))


@network_bp.route('/api/network/dns')
@require_permission('system.configure')
def get_dns():
    """Get DNS servers via hardware-service."""
    return jsonify(call_hardware_service('/api/network/dns', method='GET'))


@network_bp.route('/api/network/dns/configure', methods=['POST'])
@require_permission('system.configure')
def configure_dns():
    """Configure DNS servers via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/dns/configure', method='POST', data=data))


@network_bp.route('/api/network/diagnostics/ping', methods=['POST'])
@require_permission('system.configure')
def ping_host():
    """Ping a host via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/diagnostics/ping', method='POST', data=data))


@network_bp.route('/api/network/diagnostics/traceroute', methods=['POST'])
@require_permission('system.configure')
def traceroute_host():
    """Traceroute to a host via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/diagnostics/traceroute', method='POST', data=data))


@network_bp.route('/api/network/diagnostics/nslookup', methods=['POST'])
@require_permission('system.configure')
def nslookup_host():
    """DNS lookup via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/diagnostics/nslookup', method='POST', data=data))


@network_bp.route('/api/network/diagnostics/route')
@require_permission('system.configure')
def get_routing_table():
    """Get routing table via hardware-service."""
    return jsonify(call_hardware_service('/api/network/diagnostics/route', method='GET'))


@network_bp.route('/api/network/diagnostics/gateway')
@require_permission('system.configure')
def get_gateway():
    """Get default gateway via hardware-service."""
    return jsonify(call_hardware_service('/api/network/diagnostics/gateway', method='GET'))


@network_bp.route('/api/network/connections')
@require_permission('system.configure')
def get_connections():
    """Get all saved connections via hardware-service."""
    return jsonify(call_hardware_service('/api/network/connections', method='GET'))


@network_bp.route('/api/network/connection/activate', methods=['POST'])
@require_permission('system.configure')
def activate_connection():
    """Activate a connection via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/connection/activate', method='POST', data=data))


@network_bp.route('/api/network/connection/deactivate', methods=['POST'])
@require_permission('system.configure')
def deactivate_connection():
    """Deactivate a connection via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/connection/deactivate', method='POST', data=data))


@network_bp.route('/api/network/connection/autoconnect', methods=['POST'])
@require_permission('system.configure')
def set_autoconnect():
    """Set autoconnect status via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/connection/autoconnect', method='POST', data=data))


@network_bp.route('/api/network/hostname', methods=['GET'])
@require_permission('system.configure')
def get_hostname():
    """Get system hostname via hardware-service."""
    return jsonify(call_hardware_service('/api/network/hostname', method='GET'))


@network_bp.route('/api/network/hostname', methods=['POST'])
@require_permission('system.configure')
def set_hostname():
    """Set system hostname via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/network/hostname', method='POST', data=data))


def _parse_timedatectl_show(output: str) -> dict:
    """Parse key=value output from `timedatectl show-timesync --all`."""
    result = {}
    for line in output.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _run_cmd(cmd: list[str]) -> str:
    """Run a subprocess command and return stdout, or '' on error."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return proc.stdout if proc.returncode == 0 else ""
    except Exception:
        return ""


@network_bp.route('/api/system/ntp/status')
@require_permission('system.configure')
def get_ntp_status():
    """Return the current NTP / time-synchronisation status.

    Reads data from ``timedatectl show-timesync --all`` (systemd-timesyncd) and
    supplements it with the human-readable ``timedatectl status`` output.
    Falls back gracefully when systemd-timesyncd is not present.
    """
    # -- timedatectl show-timesync: machine-readable NTP details -------------
    sync_raw = _run_cmd(["timedatectl", "show-timesync", "--all"])
    sync_data = _parse_timedatectl_show(sync_raw)

    # -- timedatectl status: human-readable summary --------------------------
    status_raw = _run_cmd(["timedatectl", "status"])
    status_data = _parse_timedatectl_show(_run_cmd(["timedatectl", "show", "--all"]))

    # Synchronised flag can appear in both outputs
    synchronized_str = (
        sync_data.get("NTPSynchronized")
        or status_data.get("NTPSynchronized")
        or ""
    ).lower()
    synchronized = synchronized_str == "yes"

    ntp_enabled_str = (
        sync_data.get("NTP")
        or status_data.get("NTP")
        or ""
    ).lower()
    ntp_enabled = ntp_enabled_str in ("yes", "active")

    # Offset comes in microseconds from systemd-timesyncd; convert to ms
    offset_us_str = sync_data.get("NTPMessage", "")
    offset_ms: float | None = None
    # NTPMessage format: "To=... Offset=±NNNus ..."
    offset_match = re.search(r"Offset=([+-]?\d+)us", offset_us_str)
    if offset_match:
        try:
            offset_ms = int(offset_match.group(1)) / 1000.0
        except ValueError:
            pass

    # Server address
    server = sync_data.get("ServerName") or sync_data.get("ServerAddress") or None

    # Root distance (accuracy indicator) in microseconds
    root_dist_str = sync_data.get("RootDistanceMaxUSec") or ""
    root_dist_ms: float | None = None
    try:
        root_dist_ms = int(root_dist_str) / 1000.0 if root_dist_str else None
    except ValueError:
        pass

    # Last successful synchronisation time
    last_sync = (
        sync_data.get("LastSyncRealtimeUSec")
        or sync_data.get("TimeUSec")
        or None
    )

    # Extract local time string from human-readable status output
    local_time_match = re.search(r"Local time\s*:\s*(.+)", status_raw)
    local_time_str = local_time_match.group(1).strip() if local_time_match else None

    # Timezone
    timezone_str = status_data.get("Timezone") or None

    return jsonify({
        "synchronized": synchronized,
        "ntp_enabled": ntp_enabled,
        "server": server,
        "offset_ms": offset_ms,
        "root_distance_ms": root_dist_ms,
        "last_sync_raw": last_sync,
        "local_time": local_time_str,
        "timezone": timezone_str,
        "raw": {
            "show_timesync": sync_data,
            "show": status_data,
        } if request.args.get("debug") else None,
    })


@network_bp.route('/api/system/ntp/configure', methods=['POST'])
@require_permission('system.configure')
def configure_ntp():
    """Enable or disable NTP via timedatectl (requires sudo privilege).

    Body: {"enabled": true|false}
    """
    data = request.get_json() or {}
    enabled = bool(data.get("enabled", True))
    flag = "true" if enabled else "false"

    result = subprocess.run(
        ["sudo", "timedatectl", "set-ntp", flag],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return jsonify({"success": True, "ntp_enabled": enabled})
    return jsonify({
        "success": False,
        "error": result.stderr.strip() or "timedatectl set-ntp failed",
    }), 500


@network_bp.route('/api/hardware/gps/status')
@require_permission('system.configure')
def get_gps_status():
    """Get GPS receiver status via hardware-service."""
    return jsonify(call_hardware_service('/api/hardware/gps/status', method='GET'))


@network_bp.route('/api/hardware/gps/configure', methods=['POST'])
@require_permission('system.configure')
def configure_gps():
    """Configure GPS receiver via hardware-service."""
    data = request.get_json()
    return jsonify(call_hardware_service('/api/hardware/gps/configure', method='POST', data=data))


def register_network_routes(app, logger):
    """Register network management routes with the Flask app."""
    app.register_blueprint(network_bp)
    logger.info("Network management routes registered (proxied to hardware-service)")
