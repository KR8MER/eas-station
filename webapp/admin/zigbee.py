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

"""Zigbee monitoring and status routes.

This module proxies Zigbee serial port operations to hardware-service container,
which has direct access to serial devices (/dev/ttyUSB*, /dev/ttyACM*, etc).

In the separated container architecture:
- App container: Runs Flask web UI (no serial port access)
- Hardware-service container: Has device access for serial ports and Zigbee coordinator
"""

import requests
from flask import Blueprint, jsonify, render_template
from app_core.auth.decorators import require_permission
from app_core.extensions import get_redis_client

zigbee_bp = Blueprint('zigbee', __name__)

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


def get_zigbee_config():
    """Get Zigbee configuration from environment."""
    from app_utils.config import get_config

    return {
        'enabled': get_config('ZIGBEE_ENABLED', 'false').lower() in ('true', '1', 'yes'),
        'port': get_config('ZIGBEE_PORT', '/dev/ttyAMA0'),
        'baudrate': int(get_config('ZIGBEE_BAUDRATE', '115200')),
        'channel': int(get_config('ZIGBEE_CHANNEL', '15')),
        'pan_id': get_config('ZIGBEE_PAN_ID', '0x1A62'),
    }


@zigbee_bp.route('/settings/zigbee')
@require_permission('system.configure')
def zigbee_settings():
    """Render the Zigbee monitoring page."""
    return render_template('settings/zigbee.html')


@zigbee_bp.route('/api/zigbee/status')
@require_permission('system.configure')
def get_zigbee_status():
    """Get Zigbee coordinator status and configuration."""
    try:
        config = get_zigbee_config()

        if not config['enabled']:
            return jsonify({
                'success': True,
                'enabled': False,
                'message': 'Zigbee is disabled in configuration'
            })

        # Get available serial ports from hardware-service
        ports_result = call_hardware_service('/api/zigbee/ports', method='GET')
        available_ports = ports_result.get('ports', []) if ports_result.get('success') else []

        # Check configured port accessibility via hardware-service
        port_test_result = call_hardware_service(
            '/api/zigbee/test_port',
            method='POST',
            data={'port': config['port']}
        )

        # Try to get coordinator info from Redis (published by hardware service)
        coordinator_info = None
        try:
            redis_client = get_redis_client()
            zigbee_data = redis_client.get('zigbee:coordinator')
            if zigbee_data:
                import json
                coordinator_info = json.loads(zigbee_data)
        except Exception:
            pass

        return jsonify({
            'success': True,
            'enabled': True,
            'config': config,
            'port_status': port_test_result,
            'available_ports': available_ports,
            'coordinator': coordinator_info
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@zigbee_bp.route('/api/zigbee/devices')
@require_permission('system.configure')
def get_zigbee_devices():
    """Get list of discovered Zigbee devices from Redis."""
    try:
        config = get_zigbee_config()

        if not config['enabled']:
            return jsonify({
                'success': True,
                'enabled': False,
                'devices': []
            })

        # Get device list from Redis (published by hardware service)
        try:
            redis_client = get_redis_client()
            import json

            devices = []
            device_keys = redis_client.keys('zigbee:device:*')

            for key in device_keys:
                device_data = redis_client.get(key)
                if device_data:
                    devices.append(json.loads(device_data))

            return jsonify({
                'success': True,
                'enabled': True,
                'devices': devices,
                'count': len(devices)
            })

        except Exception as e:
            return jsonify({
                'success': True,
                'enabled': True,
                'devices': [],
                'warning': f'Could not retrieve devices from Redis: {str(e)}'
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@zigbee_bp.route('/api/zigbee/diagnostics')
@require_permission('system.configure')
def get_zigbee_diagnostics():
    """Get detailed Zigbee diagnostics and troubleshooting info."""
    try:
        config = get_zigbee_config()

        # Get available ports
        ports_result = call_hardware_service('/api/zigbee/ports', method='GET')
        available_ports = ports_result.get('ports', []) if ports_result.get('success') else []

        # Test configured port
        port_test = None
        if config['enabled']:
            port_test = call_hardware_service(
                '/api/zigbee/test_port',
                method='POST',
                data={'port': config['port']}
            )

        diagnostics = {
            'config': config,
            'available_ports': available_ports,
            'configured_port_test': port_test,
            'recommendations': []
        }

        # Add recommendations
        if not config['enabled']:
            diagnostics['recommendations'].append({
                'level': 'info',
                'message': 'Zigbee is disabled. Enable via ZIGBEE_ENABLED environment variable.'
            })
        elif config['enabled'] and not port_test.get('success'):
            diagnostics['recommendations'].append({
                'level': 'error',
                'message': f"Configured port {config['port']} is not accessible. Check device connection and permissions."
            })
        elif not available_ports:
            diagnostics['recommendations'].append({
                'level': 'warning',
                'message': 'No serial ports detected. Connect a Zigbee coordinator device.'
            })

        return jsonify({
            'success': True,
            'diagnostics': diagnostics
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
