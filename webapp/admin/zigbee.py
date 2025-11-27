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

"""Zigbee monitoring and status routes."""

import os
import serial
import serial.tools.list_ports
from flask import Blueprint, jsonify, render_template
from app_core.auth.decorators import require_permission
from app_core.extensions import get_redis_client
import json

zigbee_bp = Blueprint('zigbee', __name__)


def get_zigbee_config():
    """Get Zigbee configuration from environment."""
    from app_utils.config import get_config

    return {
        'enabled': get_config('ZIGBEE_ENABLED', 'false').lower() == 'true',
        'port': get_config('ZIGBEE_PORT', '/dev/ttyAMA0'),
        'baudrate': int(get_config('ZIGBEE_BAUDRATE', '115200')),
        'channel': int(get_config('ZIGBEE_CHANNEL', '15')),
        'pan_id': get_config('ZIGBEE_PAN_ID', '0x1A62')
    }


def check_serial_port(port, baudrate):
    """Check if a serial port is accessible and working."""
    try:
        if not os.path.exists(port):
            return {
                'accessible': False,
                'error': f'Port {port} does not exist'
            }

        # Try to open the port
        ser = serial.Serial(port, baudrate, timeout=1)
        ser.close()

        return {
            'accessible': True,
            'port': port,
            'baudrate': baudrate
        }
    except serial.SerialException as e:
        return {
            'accessible': False,
            'error': str(e)
        }
    except Exception as e:
        return {
            'accessible': False,
            'error': f'Unexpected error: {str(e)}'
        }


def get_available_serial_ports():
    """Get list of available serial ports."""
    ports = []
    for port in serial.tools.list_ports.comports():
        ports.append({
            'device': port.device,
            'description': port.description,
            'hwid': port.hwid
        })
    return ports


@zigbee_bp.route('/settings/zigbee')
@require_permission('admin.system')
def zigbee_settings():
    """Render the Zigbee monitoring page."""
    return render_template('settings/zigbee.html')


@zigbee_bp.route('/api/zigbee/status')
@require_permission('admin.system')
def get_zigbee_status():
    """Get Zigbee coordinator status and configuration."""
    try:
        config = get_zigbee_config()

        # Check if Zigbee is enabled
        if not config['enabled']:
            return jsonify({
                'success': True,
                'enabled': False,
                'message': 'Zigbee is disabled in configuration'
            })

        # Check serial port accessibility
        port_status = check_serial_port(config['port'], config['baudrate'])

        # Get available serial ports
        available_ports = get_available_serial_ports()

        # Try to get coordinator info from Redis (published by hardware service)
        coordinator_info = None
        try:
            redis_client = get_redis_client()
            if redis_client:
                zigbee_data = redis_client.hgetall('eas:zigbee:coordinator')
                if zigbee_data:
                    coordinator_info = {
                        k.decode() if isinstance(k, bytes) else k:
                        v.decode() if isinstance(v, bytes) else v
                        for k, v in zigbee_data.items()
                    }
        except Exception as e:
            coordinator_info = {'error': str(e)}

        return jsonify({
            'success': True,
            'enabled': True,
            'config': config,
            'port_status': port_status,
            'available_ports': available_ports,
            'coordinator': coordinator_info
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@zigbee_bp.route('/api/zigbee/devices')
@require_permission('admin.system')
def get_zigbee_devices():
    """Get list of discovered Zigbee devices."""
    try:
        config = get_zigbee_config()

        if not config['enabled']:
            return jsonify({
                'success': True,
                'devices': [],
                'message': 'Zigbee is disabled'
            })

        # Try to get device list from Redis (published by hardware service)
        devices = []
        try:
            redis_client = get_redis_client()
            if redis_client:
                # Get all device keys
                device_keys = redis_client.keys('eas:zigbee:device:*')
                for key in device_keys:
                    device_data = redis_client.hgetall(key)
                    if device_data:
                        device = {
                            k.decode() if isinstance(k, bytes) else k:
                            v.decode() if isinstance(v, bytes) else v
                            for k, v in device_data.items()
                        }
                        devices.append(device)
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Failed to retrieve devices from Redis: {str(e)}'
            }), 500

        return jsonify({
            'success': True,
            'devices': devices,
            'count': len(devices)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@zigbee_bp.route('/api/zigbee/diagnostics')
@require_permission('admin.system')
def get_zigbee_diagnostics():
    """Get detailed Zigbee diagnostics and troubleshooting info."""
    try:
        config = get_zigbee_config()
        diagnostics = {
            'config': config,
            'checks': []
        }

        # Check 1: Zigbee enabled
        diagnostics['checks'].append({
            'name': 'Zigbee Enabled',
            'status': 'pass' if config['enabled'] else 'warning',
            'message': 'Enabled' if config['enabled'] else 'Disabled in configuration'
        })

        if config['enabled']:
            # Check 2: Serial port exists
            port_exists = os.path.exists(config['port'])
            diagnostics['checks'].append({
                'name': 'Serial Port Exists',
                'status': 'pass' if port_exists else 'fail',
                'message': f"{config['port']} exists" if port_exists else f"{config['port']} not found"
            })

            # Check 3: Serial port accessible
            if port_exists:
                port_status = check_serial_port(config['port'], config['baudrate'])
                diagnostics['checks'].append({
                    'name': 'Serial Port Accessible',
                    'status': 'pass' if port_status['accessible'] else 'fail',
                    'message': 'Port can be opened' if port_status['accessible'] else port_status.get('error', 'Cannot open port')
                })

            # Check 4: Hardware service running
            try:
                redis_client = get_redis_client()
                hardware_status = None
                if redis_client:
                    hardware_status = redis_client.get('eas:health:hardware-service')

                if hardware_status:
                    diagnostics['checks'].append({
                        'name': 'Hardware Service',
                        'status': 'pass',
                        'message': 'Running and publishing metrics'
                    })
                else:
                    diagnostics['checks'].append({
                        'name': 'Hardware Service',
                        'status': 'warning',
                        'message': 'Not publishing metrics to Redis'
                    })
            except Exception as e:
                diagnostics['checks'].append({
                    'name': 'Hardware Service',
                    'status': 'fail',
                    'message': f'Error checking status: {str(e)}'
                })

            # Check 5: List available serial ports
            available_ports = get_available_serial_ports()
            diagnostics['available_ports'] = available_ports

        # Overall status
        failed_checks = [c for c in diagnostics['checks'] if c['status'] == 'fail']
        warning_checks = [c for c in diagnostics['checks'] if c['status'] == 'warning']

        if failed_checks:
            diagnostics['overall_status'] = 'fail'
            diagnostics['summary'] = f"{len(failed_checks)} check(s) failed"
        elif warning_checks:
            diagnostics['overall_status'] = 'warning'
            diagnostics['summary'] = f"{len(warning_checks)} warning(s)"
        else:
            diagnostics['overall_status'] = 'pass'
            diagnostics['summary'] = 'All checks passed'

        return jsonify({
            'success': True,
            'diagnostics': diagnostics
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def register_zigbee_routes(app, logger):
    """Register Zigbee routes with the Flask app."""
    app.register_blueprint(zigbee_bp)
    logger.info("Zigbee monitoring routes registered")
