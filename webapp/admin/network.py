"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Network configuration routes for WiFi management."""

import json
import subprocess
from flask import Blueprint, jsonify, request, render_template
from app_core.auth.decorators import require_permission

network_bp = Blueprint('network', __name__)


def run_command(cmd, check=True):
    """Execute a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=check,
            timeout=30
        )
        return {
            'success': True,
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip(),
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Command timeout',
            'returncode': -1
        }
    except subprocess.CalledProcessError as e:
        return {
            'success': False,
            'stdout': e.stdout.strip() if e.stdout else '',
            'stderr': e.stderr.strip() if e.stderr else '',
            'returncode': e.returncode,
            'error': str(e)
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'returncode': -1
        }


@network_bp.route('/settings/network')
@require_permission('system.configure')
def network_settings():
    """Render the network configuration page."""
    return render_template('settings/network.html')


@network_bp.route('/api/network/status')
@require_permission('system.configure')
def get_network_status():
    """Get current network connection status."""
    try:
        # Get all connections
        result = run_command('nmcli -t -f NAME,TYPE,DEVICE,STATE connection show', check=False)

        connections = []
        if result['success'] and result['stdout']:
            for line in result['stdout'].split('\n'):
                if line.strip():
                    parts = line.split(':')
                    if len(parts) >= 4:
                        connections.append({
                            'name': parts[0],
                            'type': parts[1],
                            'device': parts[2],
                            'state': parts[3]
                        })

        # Get active WiFi connection details
        wifi_info = None
        result = run_command('nmcli -t -f active,ssid,signal,security dev wifi list | grep "^yes"', check=False)
        if result['success'] and result['stdout']:
            parts = result['stdout'].split(':')
            if len(parts) >= 4:
                wifi_info = {
                    'ssid': parts[1],
                    'signal': parts[2],
                    'security': parts[3]
                }

        # Get IP address info
        ip_info = {}
        result = run_command('ip -j addr show', check=False)
        if result['success'] and result['stdout']:
            try:
                ip_data = json.loads(result['stdout'])
                for interface in ip_data:
                    if interface.get('operstate') == 'UP' and 'addr_info' in interface:
                        addrs = []
                        for addr in interface['addr_info']:
                            if addr.get('family') in ['inet', 'inet6']:
                                addrs.append({
                                    'family': addr['family'],
                                    'address': addr['local'],
                                    'prefixlen': addr.get('prefixlen')
                                })
                        if addrs:
                            ip_info[interface['ifname']] = addrs
            except json.JSONDecodeError:
                pass

        return jsonify({
            'success': True,
            'connections': connections,
            'wifi': wifi_info,
            'interfaces': ip_info
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@network_bp.route('/api/network/wifi/scan')
@require_permission('system.configure')
def scan_wifi():
    """Scan for available WiFi networks."""
    try:
        # Request a fresh scan
        run_command('nmcli dev wifi rescan', check=False)

        # Get scan results
        result = run_command(
            'nmcli -t -f SSID,SIGNAL,SECURITY,IN-USE dev wifi list',
            check=False
        )

        networks = []
        seen_ssids = set()

        if result['success'] and result['stdout']:
            for line in result['stdout'].split('\n'):
                if line.strip():
                    parts = line.split(':')
                    if len(parts) >= 3:
                        ssid = parts[0]
                        # Skip hidden networks and duplicates (keep strongest signal)
                        if ssid and ssid not in seen_ssids:
                            seen_ssids.add(ssid)
                            networks.append({
                                'ssid': ssid,
                                'signal': int(parts[1]) if parts[1].isdigit() else 0,
                                'security': parts[2] if len(parts) > 2 else '',
                                'in_use': parts[3] == '*' if len(parts) > 3 else False
                            })

        # Sort by signal strength
        networks.sort(key=lambda x: x['signal'], reverse=True)

        return jsonify({
            'success': True,
            'networks': networks
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@network_bp.route('/api/network/wifi/connect', methods=['POST'])
@require_permission('system.configure')
def connect_wifi():
    """Connect to a WiFi network."""
    try:
        data = request.get_json()
        ssid = data.get('ssid')
        password = data.get('password', '')

        if not ssid:
            return jsonify({
                'success': False,
                'error': 'SSID is required'
            }), 400

        # Check if connection already exists
        check_cmd = f"nmcli -t -f NAME connection show | grep -x '{ssid}'"
        check_result = run_command(check_cmd, check=False)

        if check_result['success'] and check_result['stdout']:
            # Connection exists, try to activate it
            if password:
                # Update password first
                result = run_command(
                    f"nmcli connection modify '{ssid}' wifi-sec.psk '{password}'",
                    check=False
                )
                if not result['success']:
                    return jsonify({
                        'success': False,
                        'error': f"Failed to update password: {result.get('stderr', 'Unknown error')}"
                    }), 500

            # Activate connection
            result = run_command(f"nmcli connection up '{ssid}'", check=False)
        else:
            # Create new connection
            if password:
                cmd = f"nmcli dev wifi connect '{ssid}' password '{password}'"
            else:
                cmd = f"nmcli dev wifi connect '{ssid}'"

            result = run_command(cmd, check=False)

        if result['success']:
            return jsonify({
                'success': True,
                'message': f"Connected to {ssid}"
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('stderr') or result.get('error', 'Connection failed')
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@network_bp.route('/api/network/wifi/disconnect', methods=['POST'])
@require_permission('system.configure')
def disconnect_wifi():
    """Disconnect from current WiFi network."""
    try:
        data = request.get_json()
        device = data.get('device', 'wlan0')

        result = run_command(f"nmcli device disconnect '{device}'", check=False)

        if result['success']:
            return jsonify({
                'success': True,
                'message': 'Disconnected from WiFi'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('stderr', 'Disconnect failed')
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@network_bp.route('/api/network/wifi/forget', methods=['POST'])
@require_permission('system.configure')
def forget_wifi():
    """Forget a saved WiFi network."""
    try:
        data = request.get_json()
        ssid = data.get('ssid')

        if not ssid:
            return jsonify({
                'success': False,
                'error': 'SSID is required'
            }), 400

        result = run_command(f"nmcli connection delete '{ssid}'", check=False)

        if result['success']:
            return jsonify({
                'success': True,
                'message': f"Forgot network {ssid}"
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('stderr', 'Failed to forget network')
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def register_network_routes(app, logger):
    """Register network routes with the Flask app."""
    app.register_blueprint(network_bp)
    logger.info("Network configuration routes registered")
