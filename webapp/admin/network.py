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

"""Network configuration routes for WiFi management.

This module proxies all network management requests to hardware-service container,
which has the necessary privileges and DBus access for NetworkManager (nmcli).

In the separated container architecture:
- App container: Runs Flask web UI (no network privileges)
- Hardware-service container: Has NET_ADMIN cap and DBus access for nmcli
"""

import requests
from flask import Blueprint, jsonify, request, render_template
from app_core.auth.decorators import require_permission

network_bp = Blueprint('network', __name__)

# Hardware service API endpoint (runs on port 5001)
HARDWARE_SERVICE_URL = "http://hardware-service:5001"


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
            'error': 'Cannot connect to hardware service. Check if hardware-service container is running.'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@network_bp.route('/settings/network')
@require_permission('system.configure')
def network_settings():
    """Render the network configuration page."""
    return render_template('settings/network.html')


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
