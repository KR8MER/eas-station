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
"""

from __future__ import annotations

"""Flask blueprint for ``/api/zigbee/*`` endpoints.

Hosts the serial-port enumeration helpers and the join-window controls
that drive ``services.zigbee.controller.ZigpyController``.  The
controller itself is owned by the orchestrator (it has process-wide
lifetime) so the blueprint factory takes a getter callback rather than
the instance directly — this lets the routes pick up controller
restarts without having to be re-registered.
"""

import logging
import os
from typing import Callable, Optional

from flask import Blueprint, jsonify, request

from services.zigbee.controller import ZigpyController
from services.zigbee.detection import (
    _ZIGBEE_BYID_KEYWORDS,
    _ZIGBEE_USB_SIGNATURES,
    detect_zigbee_coordinator,
)

logger = logging.getLogger(__name__)


def create_blueprint(
    *,
    get_zigpy_controller: Callable[[], Optional[ZigpyController]],
) -> Blueprint:
    """Build and return the ``/api/zigbee/*`` blueprint.

    Parameters
    ----------
    get_zigpy_controller:
        Zero-arg callable returning the orchestrator-owned
        ``ZigpyController`` (or ``None`` if Zigbee isn't configured).
    """
    bp = Blueprint("zigbee_api", __name__)

    @bp.route('/api/zigbee/ports', methods=['GET'])
    def list_serial_ports():
        """List available serial ports for Zigbee coordinator."""
        try:
            import serial.tools.list_ports
            port_objects = []
            for p in sorted(serial.tools.list_ports.comports(), key=lambda x: x.device):
                if any(p.device.startswith(prefix) for prefix in ('/dev/ttyUSB', '/dev/ttyACM', '/dev/ttyAMA')):
                    port_objects.append({
                        'device': p.device,
                        'description': p.description or p.device,
                    })
            return jsonify({
                'success': True,
                'ports': port_objects,
            })
        except Exception as e:
            logger.error(f"Error listing serial ports: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/zigbee/test_port', methods=['POST'])
    def test_serial_port():
        """Test if a serial port is accessible."""
        try:
            data = request.json
            port = data.get('port')

            if not port:
                return jsonify({'success': False, 'error': 'Port required'}), 400

            # If the zigpy controller is running on this exact port, it holds the
            # serial lock — report it as accessible rather than "busy".
            _zigpy_controller = get_zigpy_controller()
            if (_zigpy_controller and _zigpy_controller.port == port
                    and (_zigpy_controller.running or _zigpy_controller._starting)):
                return jsonify({
                    'success': True,
                    'accessible': True,
                    'message': 'Port in use by Zigbee coordinator',
                })

            if os.path.exists(port):
                import serial
                try:
                    ser = serial.Serial(port, 115200, timeout=1)
                    ser.close()
                    return jsonify({'success': True, 'accessible': True, 'message': 'Port accessible'})
                except serial.SerialException as e:
                    return jsonify({'success': False, 'accessible': False, 'error': f'Cannot open port: {str(e)}'})
            else:
                return jsonify({'success': False, 'accessible': False, 'error': 'Port does not exist'})

        except Exception as e:
            logger.error(f"Error testing serial port: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/zigbee/detect', methods=['GET'])
    def detect_zigbee_port():
        """Auto-detect Zigbee coordinator USB devices by VID/PID and /dev/serial/by-id.

        Add ?debug=1 to return full diagnostic information including all ports seen
        by pyserial, all /dev/serial/by-id entries, and any errors encountered.
        """
        debug = request.args.get('debug', '').lower() in ('1', 'true', 'yes')
        try:
            if not debug:
                results = detect_zigbee_coordinator()
                return jsonify({
                    'success': True,
                    'devices': results,
                    'count': len(results),
                })

            # Debug mode: capture all intermediate data and errors
            diag = {
                'all_serial_ports': [],
                'by_id_entries': [],
                'dev_tty_glob': [],
                'errors': [],
                'matched_devices': [],
            }

            # All ports pyserial can see
            try:
                from serial.tools import list_ports
                for p in list_ports.comports():
                    diag['all_serial_ports'].append({
                        'device': p.device,
                        'description': p.description,
                        'hwid': p.hwid,
                        'vid': f"0x{p.vid:04x}" if p.vid else None,
                        'pid': f"0x{p.pid:04x}" if p.pid else None,
                        'manufacturer': p.manufacturer,
                        'product': p.product,
                        'serial_number': p.serial_number,
                    })
            except ImportError:
                diag['errors'].append("pyserial not installed (pip install pyserial)")
            except Exception as e:
                diag['errors'].append(f"pyserial list_ports error: {e}")

            # /dev/serial/by-id entries
            try:
                import glob as _g
                for sym in sorted(_g.glob('/dev/serial/by-id/*')):
                    diag['by_id_entries'].append({
                        'symlink': sym,
                        'name': os.path.basename(sym),
                        'real_path': os.path.realpath(sym),
                    })
                if not diag['by_id_entries']:
                    diag['by_id_entries'] = []
            except Exception as e:
                diag['errors'].append(f"/dev/serial/by-id scan error: {e}")

            # Raw /dev/tty* globs
            try:
                import glob as _g
                for pattern in ('/dev/ttyUSB*', '/dev/ttyACM*', '/dev/ttyAMA*', '/dev/ttyS*'):
                    diag['dev_tty_glob'].extend(sorted(_g.glob(pattern)))
            except Exception as e:
                diag['errors'].append(f"/dev/tty glob error: {e}")

            # VID/PID signatures we're scanning for
            diag['known_signatures'] = [
                {'vid': f"0x{v:04x}", 'pid': f"0x{p:04x}", 'label': l}
                for v, p, l in _ZIGBEE_USB_SIGNATURES
            ]
            diag['known_byid_keywords'] = _ZIGBEE_BYID_KEYWORDS

            diag['matched_devices'] = detect_zigbee_coordinator()

            return jsonify({'success': True, 'debug': diag})

        except Exception as e:
            logger.error(f"Error detecting Zigbee coordinator: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/zigbee/permit_join', methods=['POST'])
    def api_permit_join():
        """Open the Zigbee join window so new devices can pair.

        Body (JSON): { "duration": 60 }   — duration in seconds (1-254, default 60)
        """
        try:
            _zigpy_controller = get_zigpy_controller()
            if not _zigpy_controller:
                return jsonify({'success': False, 'error': 'Zigbee coordinator not initialised'}), 503
            body = request.get_json(silent=True) or {}
            duration = int(body.get('duration', 60))
            duration = max(1, min(duration, 254))
            _zigpy_controller.permit_join(duration)
            return jsonify({
                'success': True,
                'permit_join_active': True,
                'duration': duration,
                'deadline': _zigpy_controller.permit_join_deadline,
            })
        except RuntimeError as e:
            return jsonify({'success': False, 'error': str(e)}), 503
        except Exception as e:
            logger.error(f"permit_join error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/zigbee/permit_join', methods=['DELETE'])
    def api_close_join():
        """Close the Zigbee join window immediately."""
        try:
            _zigpy_controller = get_zigpy_controller()
            if not _zigpy_controller:
                return jsonify({'success': False, 'error': 'Zigbee coordinator not initialised'}), 503
            _zigpy_controller.close_join()
            return jsonify({'success': True, 'permit_join_active': False})
        except Exception as e:
            logger.error(f"close_join error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/zigbee/join_status', methods=['GET'])
    def api_join_status():
        """Return current join-window state."""
        try:
            _zigpy_controller = get_zigpy_controller()
            if not _zigpy_controller:
                return jsonify({'success': True, 'running': False, 'permit_join_active': False})
            return jsonify({
                'success': True,
                'running': _zigpy_controller.running,
                'permit_join_active': _zigpy_controller.permit_join_active,
                'deadline': _zigpy_controller.permit_join_deadline,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    return bp
