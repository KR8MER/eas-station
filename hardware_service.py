#!/usr/bin/env python3
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

"""
Dedicated Hardware Service

This service handles GPIO, displays, and Zigbee hardware:
- GPIO pin control (relays, transmitter keying)
- OLED/LED/VFD display management
- Screen rotation and rendering
- Zigbee coordinator (if configured)
- Hardware status monitoring

Architecture Benefits:
- Fault isolation - display/GPIO issues don't affect SDR
- Independent restart - can restart hardware service without affecting audio
- Clean separation - one service per hardware type
- Better debugging - clear responsibility boundaries

The web UI communicates with this service via HTTP API for hardware control.
"""

import os
import sys
import time
import logging
import json
import redis
import subprocess
import threading
import ipaddress
from typing import Optional
from datetime import datetime, timezone
from flask import Flask, jsonify, request

# Network utilities (extracted for reuse)
from app_utils.network import (
    run_command,
    check_nmcli_available,
    get_wifi_interface,
    enhance_error_message,
    get_hostname,
    set_hostname,
    HOSTNAME_PATTERN,
)

# Shared bootstrap scaffolding for all split hardware-side services.
# See services/common/bootstrap.py for the full rationale (glibc tuning,
# memdiag hooks, etc.) — this is the exact same startup behaviour that
# used to be inlined here, factored out so the per-subsystem services
# can reuse it.
from services.common import (
    configure_logging,
    init_database,
    init_runtime,
    install_signal_handlers,
    load_environment,
    get_redis,
    publish_hardware_metrics as _publish_hardware_metrics_impl,
)

# Per-subsystem services extracted from this module in Phase 2 of the
# hardware_service.py split.  Each package exposes a pure ``initialize``
# function that returns the controller (so the orchestrator below owns
# the lifetime via module-level globals) plus any periodic helpers.
from services.displays import (
    initialize_led_controller as _initialize_led_controller_impl,
    initialize_oled_display as _initialize_oled_display_impl,
    initialize_screen_manager as _initialize_screen_manager_impl,
    initialize_vfd_controller as _initialize_vfd_controller_impl,
)
from services.gpio import (
    initialize_gpio_controller as _initialize_gpio_controller_impl,
    initialize_neopixel_controller as _initialize_neopixel_controller_impl,
    initialize_tower_light_controller as _initialize_tower_light_controller_impl,
    update_alert_indicators as _update_alert_indicators_impl,
)
from services.gps import (
    GPS_TRENDS_DEFAULT_WINDOW,
    GPS_TRENDS_INTERVAL_S,
    GPS_TRENDS_MAX_SAMPLES,
    GPS_TRENDS_RAW_MAX_SAMPLES,
    GPS_TRENDS_REDIS_KEY,
    GPS_TRENDS_TIERS,
    GPS_TRENDS_WINDOW_TO_TIER,
    initialize_gps_manager as _initialize_gps_manager_impl,
    new_last_bucket_ids as _new_gps_last_bucket_ids,
)
from services.gps import trends as _gps_trends
from services.zigbee import (
    ZigpyController,
    detect_zigbee_coordinator,
    initialize_zigbee_coordinator as _initialize_zigbee_coordinator_impl,
    publish_zigbee_status as _publish_zigbee_status_impl,
)

configure_logging()
logger = logging.getLogger(__name__)

# Load environment variables from persistent config volume
# This must happen before initializing hardware controllers
load_environment(logger)

# Global state
_running = True
_redis_client: Optional[redis.Redis] = None
_flask_app: Optional[Flask] = None
_screen_manager = None
_gpio_controller = None
_neopixel_controller = None
_tower_light_controller = None
_gps_manager = None
_zigpy_controller = None


def _on_shutdown_signal(signum: int) -> None:
    """Flip the process-local _running flag in response to SIGTERM/SIGINT."""
    global _running
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _running = False


def get_redis_client() -> redis.Redis:
    """Get or create Redis client with retry logic.

    Thin wrapper around ``services.common.bootstrap.get_redis`` that
    keeps the module-level ``_redis_client`` in sync so downstream
    helpers can continue to read it directly.
    """
    global _redis_client
    _redis_client = get_redis()
    return _redis_client


def initialize_database():
    """Initialize database connection for hardware configuration."""
    return init_database()


def initialize_led_controller():
    """Initialize LED sign controller (delegates to ``services.displays``)."""
    _initialize_led_controller_impl()


def initialize_vfd_controller():
    """Initialize VFD display controller (delegates to ``services.displays``)."""
    _initialize_vfd_controller_impl()


def initialize_oled_display():
    """Initialize OLED display (delegates to ``services.displays``)."""
    _initialize_oled_display_impl()


def initialize_zigbee_coordinator():
    """Initialize Zigbee coordinator (delegates to ``services.zigbee``).

    Captures the returned ``ZigpyController`` (if any) in
    ``_zigpy_controller`` so the Flask API and the shutdown handler can
    drive it.
    """
    global _zigpy_controller
    _zigpy_controller = _initialize_zigbee_coordinator_impl(_redis_client)


def initialize_gps_manager():
    """Initialize the GPS receiver manager (delegates to ``services.gps``).

    Captures the returned ``GPSManager`` (if any) in ``_gps_manager`` so
    the Flask API can serve live status from it and the shutdown handler
    can stop it.
    """
    global _gps_manager
    _gps_manager = _initialize_gps_manager_impl(_redis_client, logger)


def initialize_screen_manager(app):
    """Initialize screen manager (delegates to ``services.displays``)."""
    global _screen_manager
    _screen_manager = _initialize_screen_manager_impl(app)


def initialize_gpio_controller(db_session=None):
    """Initialize GPIO controller (delegates to ``services.gpio``)."""
    global _gpio_controller
    _gpio_controller = _initialize_gpio_controller_impl(db_session=db_session)


def initialize_tower_light_controller():
    """Initialize USB tower light controller (delegates to ``services.gpio``)."""
    global _tower_light_controller
    _tower_light_controller = _initialize_tower_light_controller_impl()


def initialize_neopixel_controller():
    """Initialize NeoPixel controller (delegates to ``services.gpio``)."""
    global _neopixel_controller
    _neopixel_controller = _initialize_neopixel_controller_impl()


# ---------------------------------------------------------------------------
# GPS / chrony trend sampler — thin wrappers around ``services.gps.trends``.
#
# The implementation lives in ``services/gps/trends.py`` as pure functions
# that accept the redis client and per-tier bucket-id dict as arguments.
# This module owns the runtime state (``_redis_client``,
# ``_gps_trend_last_bucket_ids``, ``_gps_manager``) and passes it in so
# the orchestrator stays the single source of process-wide state.
#
# Constants (``GPS_TRENDS_TIERS`` etc.) are re-exported at the top of the
# file so the Flask API in this module and ``tests/test_gps_trends_archive``
# can both keep their existing import paths working.
# ---------------------------------------------------------------------------
_gps_trend_last_bucket_ids: "dict[str, Optional[int]]" = _new_gps_last_bucket_ids()


def _gps_trend_redis_key(tier: str) -> str:
    return _gps_trends.redis_key_for_tier(tier)


def _collect_chrony_tracking_for_trends() -> dict:
    return _gps_trends.collect_chrony_tracking()


def _collect_gps_for_trends() -> dict:
    return _gps_trends.collect_gps_status(_gps_manager)


def _aggregate_gps_trend_samples(
    rows: list, bucket_start_ms: int, bucket_end_ms: int
) -> Optional[dict]:
    return _gps_trends.aggregate_samples(rows, bucket_start_ms, bucket_end_ms)


def _emit_gps_trend_rollups(now_ms: int) -> None:
    _gps_trends.emit_rollups(_redis_client, _gps_trend_last_bucket_ids, now_ms)


def publish_gps_trend_sample() -> None:
    """Append one trend sample to the Redis ring buffer.

    Thin wrapper that hands the orchestrator-owned state to the pure
    sampler in ``services.gps.trends``.
    """
    _gps_trends.publish_sample(
        _redis_client, _gps_manager, _gps_trend_last_bucket_ids
    )


def publish_hardware_metrics():
    """Publish hardware status and metrics to Redis.

    Thin wrapper that hands the orchestrator-owned state to the
    cross-subsystem publisher in ``services.common.metrics``.
    """
    _publish_hardware_metrics_impl(
        redis_client=_redis_client,
        flask_app=_flask_app,
        screen_manager=_screen_manager,
        gpio_controller=_gpio_controller,
    )


def publish_display_state():
    """Publish detailed display state (delegates to ``services.displays``)."""
    from services.displays import publish_display_state as _impl
    _impl(_redis_client, _screen_manager)


def publish_zigbee_status():
    """Refresh Zigbee coordinator status (delegates to ``services.zigbee``)."""
    _publish_zigbee_status_impl(_redis_client)


def create_api_app():
    """Create Flask API application for hardware proxy operations."""
    api_app = Flask(__name__)

    @api_app.route('/health', methods=['GET'])
    def health():
        """Health check endpoint."""
        return jsonify({
            'status': 'ok',
            'service': 'hardware-service',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Network Management Proxy Endpoints

    @api_app.route('/api/network/status', methods=['GET'])
    def get_network_status():
        """Get current network connection status via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                logger.error("nmcli not available - NetworkManager may not be installed")
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get WiFi interface
            wifi_interface = get_wifi_interface()
            if not wifi_interface:
                logger.warning("No WiFi interface detected")
                return jsonify({
                    'success': True,
                    'wifi': None,
                    'interfaces': {}
                })

            # Get active WiFi connection on WiFi interface
            result = run_command([
                'nmcli', '-t', '-f', 
                'GENERAL.CONNECTION,GENERAL.STATE,IP4.ADDRESS,IP6.ADDRESS',
                'device', 'show', wifi_interface
            ], check=False, timeout=10)

            wifi_data = None
            interfaces = {}

            if result['success'] and result['stdout']:
                connection_name = None
                state = None
                ipv4_addrs = []
                ipv6_addrs = []

                for line in result['stdout'].split('\n'):
                    if line.strip():
                        if line.startswith('GENERAL.CONNECTION:'):
                            connection_name = line.split(':', 1)[1].strip()
                        elif line.startswith('GENERAL.STATE:'):
                            state = line.split(':', 1)[1].strip()
                        elif line.startswith('IP4.ADDRESS'):
                            addr_str = line.split(':', 1)[1].strip()
                            if addr_str and '/' in addr_str:
                                addr, prefix = addr_str.split('/')
                                ipv4_addrs.append({
                                    'family': 'inet',
                                    'address': addr,
                                    'prefixlen': int(prefix)
                                })
                        elif line.startswith('IP6.ADDRESS'):
                            addr_str = line.split(':', 1)[1].strip()
                            if addr_str and '/' in addr_str:
                                addr, prefix = addr_str.rsplit('/', 1)
                                ipv6_addrs.append({
                                    'family': 'inet6',
                                    'address': addr,
                                    'prefixlen': int(prefix)
                                })

                # Check if WiFi is connected
                if connection_name and connection_name != '--' and state and 'connected' in state.lower():
                    wifi_data = {
                        'ssid': connection_name,
                        'interface': wifi_interface,
                        'state': state
                    }
                    
                    # Add IP addresses to interfaces dict
                    if ipv4_addrs or ipv6_addrs:
                        interfaces[wifi_interface] = ipv4_addrs + ipv6_addrs

            return jsonify({
                'success': True,
                'wifi': wifi_data,
                'interfaces': interfaces
            })

        except Exception as e:
            logger.error(f"Error getting network status: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/scan', methods=['POST'])
    def scan_wifi():
        """Scan for available WiFi networks via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                logger.error("nmcli not available for WiFi scan")
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get WiFi interface
            wifi_interface = get_wifi_interface()
            if not wifi_interface:
                logger.error("No WiFi interface detected for scan")
                return jsonify({
                    'success': False,
                    'error': 'No WiFi interface found. Check if WiFi hardware is available.'
                }), 500

            logger.info(f"Starting WiFi scan on interface {wifi_interface}...")

            # Rescan networks on specific interface
            rescan_result = run_command(
                ['nmcli', 'device', 'wifi', 'rescan', 'ifname', wifi_interface],
                check=False,
                timeout=15
            )

            # Check if rescan failed
            if not rescan_result['success']:
                # Note: rescan often returns exit code 10 but still works
                # Only fail if there's a real error message
                if rescan_result.get('stderr') and 'not found' in rescan_result['stderr'].lower():
                    logger.error(f"WiFi rescan failed: {rescan_result.get('error', 'Unknown error')}")
                    return jsonify({
                        'success': False,
                        'error': f"WiFi scan failed: {rescan_result.get('stderr', 'Unknown error')}"
                    }), 500

            # Wait for scan to complete - use multiple shorter waits to check for completion
            max_wait = 10  # Maximum 10 seconds
            wait_interval = 1  # Check every 1 second
            waited = 0
            
            while waited < max_wait:
                time.sleep(wait_interval)
                waited += wait_interval
                
                # Try to get scan results
                list_result = run_command(
                    ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY,IN-USE', 'device', 'wifi', 'list', 'ifname', wifi_interface],
                    check=False,
                    timeout=10
                )
                
                # If we got results with content, break early
                if list_result['success'] and list_result['stdout']:
                    break

            # Get list of available networks
            result = run_command(
                ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY,IN-USE', 'device', 'wifi', 'list', 'ifname', wifi_interface],
                check=False,
                timeout=10
            )

            if not result['success']:
                logger.error(f"Failed to get WiFi list: {result.get('error', 'Unknown error')}")
                return jsonify({
                    'success': False,
                    'error': f"Failed to get WiFi networks: {result.get('stderr', result.get('error', 'Unknown error'))}"
                }), 500

            networks = []
            seen_ssids = set()  # Deduplicate networks (same SSID on multiple BSSIDs)

            if result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        parts = line.split(':')
                        if len(parts) >= 4:
                            ssid = parts[0].strip()
                            
                            # Skip empty SSIDs (hidden networks)
                            if not ssid or ssid == '--':
                                continue
                            
                            # Skip duplicates (keep the one with strongest signal)
                            if ssid in seen_ssids:
                                # Find existing network and update if this signal is stronger
                                for net in networks:
                                    if net['ssid'] == ssid:
                                        new_signal = int(parts[1]) if parts[1].isdigit() else 0
                                        if new_signal > net['signal']:
                                            net['signal'] = new_signal
                                            net['security'] = parts[2]
                                            net['in_use'] = parts[3] == '*'
                                        break
                                continue
                            
                            seen_ssids.add(ssid)
                            networks.append({
                                'ssid': ssid,
                                'signal': int(parts[1]) if parts[1].isdigit() else 0,
                                'security': parts[2],
                                'in_use': parts[3] == '*'
                            })

            # Sort networks by signal strength (strongest first)
            networks.sort(key=lambda x: x['signal'], reverse=True)

            logger.info(f"WiFi scan completed: found {len(networks)} networks")

            if not networks:
                logger.warning("WiFi scan returned no networks - this may indicate no networks in range or a hardware issue")

            return jsonify({
                'success': True,
                'networks': networks,
                'interface': wifi_interface
            })

        except Exception as e:
            logger.error(f"Error scanning WiFi: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connect', methods=['POST'])
    def connect_wifi():
        """Connect to a WiFi network via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            ssid = data.get('ssid')
            password = data.get('password', '')

            if not ssid:
                return jsonify({'success': False, 'error': 'SSID required'}), 400

            # Get WiFi interface
            wifi_interface = get_wifi_interface()
            if not wifi_interface:
                logger.warning("No WiFi interface detected, attempting connection anyway")

            logger.info(f"Attempting to connect to WiFi network: {ssid}")

            # Build nmcli command safely using list (prevents command injection)
            if password:
                cmd = ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password]
            else:
                cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]

            result = run_command(cmd, check=False, timeout=30)

            if result['success']:
                logger.info(f"Successfully connected to {ssid}")
                return jsonify({
                    'success': True,
                    'message': f'Connected to {ssid}'
                })
            else:
                error_msg = result.get('stderr', result.get('error', 'Connection failed'))
                logger.error(f"Failed to connect to {ssid}: {error_msg}")
                enhanced = enhance_error_message(error_msg, 'connect')
                return jsonify({
                    'success': False,
                    'error': enhanced['message'],
                    'hint': enhanced.get('hint', ''),
                    'technical': enhanced.get('technical', '')
                })

        except Exception as e:
            logger.error(f"Error connecting to WiFi: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/disconnect', methods=['POST'])
    def disconnect_network():
        """Disconnect from current network via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get WiFi interface
            wifi_interface = get_wifi_interface()
            if not wifi_interface:
                return jsonify({
                    'success': False,
                    'error': 'No WiFi interface found'
                }), 500

            # Get active connection on WiFi interface
            result = run_command([
                'nmcli', '-t', '-f', 'GENERAL.CONNECTION',
                'device', 'show', wifi_interface
            ], check=False, timeout=10)

            connection_name = None
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.startswith('GENERAL.CONNECTION:'):
                        connection_name = line.split(':', 1)[1].strip()
                        break

            if not connection_name or connection_name == '--':
                return jsonify({
                    'success': False,
                    'error': 'No active WiFi connection to disconnect'
                }), 400

            logger.info(f"Disconnecting from WiFi network: {connection_name}")

            # Disconnect using connection name
            cmd = ['nmcli', 'connection', 'down', connection_name]
            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                logger.info(f"Successfully disconnected from {connection_name}")
                return jsonify({
                    'success': True,
                    'message': f'Disconnected from {connection_name}'
                })
            else:
                logger.error(f"Failed to disconnect: {result.get('stderr', result.get('error', 'Unknown error'))}")
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to disconnect'))
                })

        except Exception as e:
            logger.error(f"Error disconnecting network: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/forget', methods=['POST'])
    def forget_network():
        """Forget a saved network connection via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection_name = data.get('connection')

            if not connection_name:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Forgetting WiFi network: {connection_name}")

            # Use list arguments to prevent command injection
            cmd = ['nmcli', 'connection', 'delete', connection_name]
            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                logger.info(f"Successfully forgot network {connection_name}")
                return jsonify({
                    'success': True,
                    'message': f'Forgot network {connection_name}'
                })
            else:
                logger.error(f"Failed to forget network: {result.get('stderr', result.get('error', 'Unknown error'))}")
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to forget network'))
                })

        except Exception as e:
            logger.error(f"Error forgetting network: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # Phase 2: Core DASDEC3 Network Features

    @api_app.route('/api/network/interfaces', methods=['GET'])
    def get_network_interfaces():
        """Get all network interfaces (both WiFi and Ethernet)."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get all devices with their types and states
            result = run_command([
                'nmcli', '-t', '-f',
                'DEVICE,TYPE,STATE,CONNECTION',
                'device'
            ], check=False, timeout=10)

            interfaces = []
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        parts = line.split(':')
                        if len(parts) >= 4:
                            device = parts[0]
                            iface_type = parts[1]
                            state = parts[2]
                            connection = parts[3] if parts[3] != '--' else None

                            # Get detailed info for this interface
                            detail_result = run_command([
                                'nmcli', '-t', '-f',
                                'IP4.ADDRESS,IP4.GATEWAY,IP6.ADDRESS',
                                'device', 'show', device
                            ], check=False, timeout=10)

                            ipv4_addrs = []
                            ipv4_gateway = None
                            ipv6_addrs = []

                            if detail_result['success'] and detail_result['stdout']:
                                for detail_line in detail_result['stdout'].split('\n'):
                                    if detail_line.startswith('IP4.ADDRESS'):
                                        addr_str = detail_line.split(':', 1)[1].strip()
                                        if addr_str and '/' in addr_str:
                                            addr, prefix = addr_str.split('/')
                                            ipv4_addrs.append({
                                                'address': addr,
                                                'prefixlen': int(prefix)
                                            })
                                    elif detail_line.startswith('IP4.GATEWAY'):
                                        ipv4_gateway = detail_line.split(':', 1)[1].strip()
                                    elif detail_line.startswith('IP6.ADDRESS'):
                                        addr_str = detail_line.split(':', 1)[1].strip()
                                        if addr_str and '/' in addr_str:
                                            addr, prefix = addr_str.rsplit('/', 1)
                                            ipv6_addrs.append({
                                                'address': addr,
                                                'prefixlen': int(prefix)
                                            })

                            interfaces.append({
                                'device': device,
                                'type': iface_type,
                                'state': state,
                                'connection': connection,
                                'ipv4_addresses': ipv4_addrs,
                                'ipv4_gateway': ipv4_gateway,
                                'ipv6_addresses': ipv6_addrs
                            })

            return jsonify({
                'success': True,
                'interfaces': interfaces
            })

        except Exception as e:
            logger.error(f"Error getting network interfaces: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/interface/configure', methods=['POST'])
    def configure_interface():
        """Configure network interface with static IP or DHCP."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')
            method = data.get('method', 'auto')  # 'auto' (DHCP) or 'manual' (static)
            ip_address = data.get('ip_address')
            netmask = data.get('netmask')
            gateway = data.get('gateway')

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Configuring interface {connection} with method {method}")

            if method == 'manual':
                # Static IP configuration
                if not ip_address or not netmask:
                    return jsonify({
                        'success': False,
                        'error': 'IP address and netmask required for static configuration'
                    }), 400

                # Calculate CIDR prefix from netmask
                try:
                    prefix = ipaddress.IPv4Network(f'0.0.0.0/{netmask}').prefixlen
                except ValueError:
                    return jsonify({
                        'success': False,
                        'error': 'Invalid netmask format'
                    }), 400

                # Set static IP
                cmd = [
                    'nmcli', 'connection', 'modify', connection,
                    'ipv4.method', 'manual',
                    'ipv4.addresses', f'{ip_address}/{prefix}'
                ]

                if gateway:
                    cmd.extend(['ipv4.gateway', gateway])

                result = run_command(cmd, check=False, timeout=15)

                if not result['success']:
                    return jsonify({
                        'success': False,
                        'error': result.get('stderr', result.get('error', 'Failed to configure static IP'))
                    })

            else:
                # DHCP configuration
                cmd = [
                    'nmcli', 'connection', 'modify', connection,
                    'ipv4.method', 'auto',
                    'ipv4.addresses', '',
                    'ipv4.gateway', ''
                ]
                result = run_command(cmd, check=False, timeout=15)

                if not result['success']:
                    return jsonify({
                        'success': False,
                        'error': result.get('stderr', result.get('error', 'Failed to configure DHCP'))
                    })

            # Restart connection to apply changes
            restart_cmd = ['nmcli', 'connection', 'up', connection]
            restart_result = run_command(restart_cmd, check=False, timeout=20)

            if restart_result['success']:
                logger.info(f"Successfully configured {connection} with {method}")
                return jsonify({
                    'success': True,
                    'message': f'Interface configured with {method}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Configuration saved but failed to restart connection'
                })

        except Exception as e:
            logger.error(f"Error configuring interface: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/dns', methods=['GET'])
    def get_dns_servers():
        """Get current DNS server configuration."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get DNS servers from active connections
            result = run_command([
                'nmcli', '-t', '-f', 'IP4.DNS,IP6.DNS',
                'device', 'show'
            ], check=False, timeout=10)

            dns_servers = []
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip() and (line.startswith('IP4.DNS') or line.startswith('IP6.DNS')):
                        server = line.split(':', 1)[1].strip()
                        if server and server not in dns_servers:
                            dns_servers.append(server)

            return jsonify({
                'success': True,
                'dns_servers': dns_servers
            })

        except Exception as e:
            logger.error(f"Error getting DNS servers: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/dns/configure', methods=['POST'])
    def configure_dns():
        """Configure DNS servers for a connection."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')
            dns_servers = data.get('dns_servers', [])

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            # Validate DNS servers are valid IP addresses
            if dns_servers:
                for server in dns_servers:
                    try:
                        ipaddress.ip_address(server)
                    except ValueError:
                        return jsonify({
                            'success': False,
                            'error': f'Invalid DNS server IP address: {server}'
                        }), 400

            logger.info(f"Configuring DNS servers for {connection}")

            # Set DNS servers (space-separated list)
            dns_list = ' '.join(dns_servers) if dns_servers else ''
            cmd = [
                'nmcli', 'connection', 'modify', connection,
                'ipv4.dns', dns_list
            ]

            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                # Restart connection to apply changes
                restart_cmd = ['nmcli', 'connection', 'up', connection]
                restart_result = run_command(restart_cmd, check=False, timeout=20)

                if restart_result['success']:
                    logger.info(f"Successfully configured DNS for {connection}")
                    return jsonify({
                        'success': True,
                        'message': 'DNS servers configured'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'DNS configuration saved but failed to restart connection'
                    })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to configure DNS'))
                })

        except Exception as e:
            logger.error(f"Error configuring DNS: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/ping', methods=['POST'])
    def ping_host():
        """Ping a host to test connectivity."""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            host = data.get('host')
            count = data.get('count', 4)

            if not host:
                return jsonify({'success': False, 'error': 'Host required'}), 400

            # Validate count is reasonable
            try:
                count = int(count)
                if count < 1 or count > 10:
                    count = 4
            except ValueError:
                count = 4

            logger.info(f"Pinging {host} ({count} packets)")

            # Use ping command (works on most Linux systems)
            cmd = ['ping', '-c', str(count), '-W', '2', host]
            result = run_command(cmd, check=False, timeout=30)

            return jsonify({
                'success': result['success'],
                'output': result.get('stdout', ''),
                'error': result.get('stderr', '') if not result['success'] else None
            })

        except Exception as e:
            logger.error(f"Error pinging host: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/traceroute', methods=['POST'])
    def traceroute_host():
        """Traceroute to a host to see network path."""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            host = data.get('host')

            if not host:
                return jsonify({'success': False, 'error': 'Host required'}), 400

            logger.info(f"Traceroute to {host}")

            # Use traceroute command (may need to be installed)
            # Try traceroute first, fall back to tracepath
            cmd = ['traceroute', '-m', '15', '-w', '2', host]
            result = run_command(cmd, check=False, timeout=60)

            if not result['success'] and 'not found' in result.get('error', '').lower():
                # Try tracepath as fallback
                cmd = ['tracepath', '-m', '15', host]
                result = run_command(cmd, check=False, timeout=60)

            return jsonify({
                'success': result['success'],
                'output': result.get('stdout', ''),
                'error': result.get('stderr', '') if not result['success'] else None
            })

        except Exception as e:
            logger.error(f"Error traceroute: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/nslookup', methods=['POST'])
    def nslookup_host():
        """DNS lookup for a hostname."""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            host = data.get('host')

            if not host:
                return jsonify({'success': False, 'error': 'Host required'}), 400

            logger.info(f"DNS lookup for {host}")

            # Use nslookup or dig
            cmd = ['nslookup', host]
            result = run_command(cmd, check=False, timeout=15)

            if not result['success'] and 'not found' in result.get('error', '').lower():
                # Try dig as fallback
                cmd = ['dig', '+short', host]
                result = run_command(cmd, check=False, timeout=15)

            return jsonify({
                'success': result['success'],
                'output': result.get('stdout', ''),
                'error': result.get('stderr', '') if not result['success'] else None
            })

        except Exception as e:
            logger.error(f"Error DNS lookup: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/route', methods=['GET'])
    def get_routing_table():
        """Get system routing table."""
        try:
            logger.info("Getting routing table")

            # Use ip route command
            cmd = ['ip', 'route', 'show']
            result = run_command(cmd, check=False, timeout=10)

            if result['success']:
                return jsonify({
                    'success': True,
                    'output': result.get('stdout', '')
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to get routing table'))
                })

        except Exception as e:
            logger.error(f"Error getting routing table: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/gateway', methods=['GET'])
    def get_default_gateway():
        """Get default gateway information."""
        try:
            logger.info("Getting default gateway")

            # Get default route
            cmd = ['ip', 'route', 'show', 'default']
            result = run_command(cmd, check=False, timeout=10)

            gateway = None
            interface = None

            if result['success'] and result['stdout']:
                # Parse output: "default via 192.168.1.1 dev eth0"
                parts = result['stdout'].split()
                if 'via' in parts:
                    gateway_idx = parts.index('via') + 1
                    if gateway_idx < len(parts):
                        gateway = parts[gateway_idx]
                if 'dev' in parts:
                    dev_idx = parts.index('dev') + 1
                    if dev_idx < len(parts):
                        interface = parts[dev_idx]

            return jsonify({
                'success': True,
                'gateway': gateway,
                'interface': interface,
                'raw_output': result.get('stdout', '')
            })

        except Exception as e:
            logger.error(f"Error getting default gateway: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connections', methods=['GET'])
    def get_connections():
        """Get all saved NetworkManager connections."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get all connections with details
            result = run_command([
                'nmcli', '-t', '-f',
                'NAME,TYPE,DEVICE,AUTOCONNECT',
                'connection', 'show'
            ], check=False, timeout=10)

            connections = []
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        parts = line.split(':')
                        if len(parts) >= 4:
                            connections.append({
                                'name': parts[0],
                                'type': parts[1],
                                'device': parts[2] if parts[2] != '--' else None,
                                'autoconnect': parts[3] == 'yes'
                            })

            return jsonify({
                'success': True,
                'connections': connections
            })

        except Exception as e:
            logger.error(f"Error getting connections: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connection/activate', methods=['POST'])
    def activate_connection():
        """Activate a saved connection."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Activating connection: {connection}")

            cmd = ['nmcli', 'connection', 'up', connection]
            result = run_command(cmd, check=False, timeout=20)

            if result['success']:
                logger.info(f"Successfully activated {connection}")
                return jsonify({
                    'success': True,
                    'message': f'Activated {connection}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to activate connection'))
                })

        except Exception as e:
            logger.error(f"Error activating connection: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connection/deactivate', methods=['POST'])
    def deactivate_connection():
        """Deactivate an active connection."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Deactivating connection: {connection}")

            cmd = ['nmcli', 'connection', 'down', connection]
            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                logger.info(f"Successfully deactivated {connection}")
                return jsonify({
                    'success': True,
                    'message': f'Deactivated {connection}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to deactivate connection'))
                })

        except Exception as e:
            logger.error(f"Error deactivating connection: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connection/autoconnect', methods=['POST'])
    def set_connection_autoconnect():
        """Set autoconnect status for a connection."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')
            autoconnect = data.get('autoconnect', True)

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Setting autoconnect for {connection} to {autoconnect}")

            cmd = [
                'nmcli', 'connection', 'modify', connection,
                'connection.autoconnect', 'yes' if autoconnect else 'no'
            ]
            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                logger.info(f"Successfully set autoconnect for {connection}")
                return jsonify({
                    'success': True,
                    'message': f'Autoconnect {"enabled" if autoconnect else "disabled"}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to set autoconnect'))
                })

        except Exception as e:
            logger.error(f"Error setting autoconnect: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # Zigbee Serial Port Proxy Endpoints

    @api_app.route('/api/zigbee/ports', methods=['GET'])
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

    @api_app.route('/api/zigbee/test_port', methods=['POST'])
    def test_serial_port():
        """Test if a serial port is accessible."""
        try:
            data = request.json
            port = data.get('port')

            if not port:
                return jsonify({'success': False, 'error': 'Port required'}), 400

            # If the zigpy controller is running on this exact port, it holds the
            # serial lock — report it as accessible rather than "busy".
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

    @api_app.route('/api/zigbee/detect', methods=['GET'])
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

    @api_app.route('/api/zigbee/permit_join', methods=['POST'])
    def api_permit_join():
        """Open the Zigbee join window so new devices can pair.

        Body (JSON): { "duration": 60 }   — duration in seconds (1-254, default 60)
        """
        try:
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

    @api_app.route('/api/zigbee/permit_join', methods=['DELETE'])
    def api_close_join():
        """Close the Zigbee join window immediately."""
        try:
            if not _zigpy_controller:
                return jsonify({'success': False, 'error': 'Zigbee coordinator not initialised'}), 503
            _zigpy_controller.close_join()
            return jsonify({'success': True, 'permit_join_active': False})
        except Exception as e:
            logger.error(f"close_join error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/zigbee/join_status', methods=['GET'])
    def api_join_status():
        """Return current join-window state."""
        try:
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

    # Hostname Configuration Endpoints

    @api_app.route('/api/network/hostname', methods=['GET'])
    def api_get_hostname():
        """Get the current system hostname."""
        try:
            result = get_hostname()
            if result['success']:
                return jsonify(result)
            else:
                return jsonify(result), 500
        except Exception as e:
            logger.error(f"Error getting hostname: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/hostname', methods=['POST'])
    def api_set_hostname():
        """Set the system hostname."""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            new_hostname = data.get('hostname')
            if not new_hostname:
                return jsonify({'success': False, 'error': 'Hostname required'}), 400

            result = set_hostname(new_hostname)
            if result['success']:
                return jsonify(result)
            else:
                return jsonify(result), 400

        except Exception as e:
            logger.error(f"Error setting hostname: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # GPS Hardware Endpoints

    @api_app.route('/api/hardware/gps/status', methods=['GET'])
    def get_gps_status():
        """Return current GPS fix status from the GPS manager or Redis."""
        try:
            # Try live status from running manager first
            if _gps_manager is not None:
                return jsonify(_gps_manager.get_status())

            # Fall back to last-known status from Redis
            if _redis_client:
                try:
                    raw = _redis_client.get('gps:status')
                    if raw:
                        return jsonify(json.loads(raw))
                except Exception:
                    pass

            # GPS not configured or not started
            from app_core.hardware_settings import get_gps_settings
            gps_settings = get_gps_settings()
            return jsonify({
                'running': False,
                'has_fix': False,
                'status': 'disabled' if not gps_settings.get('enabled') else 'not_started',
                'serial_port': gps_settings.get('serial_port', '/dev/serial0'),
                'baudrate': gps_settings.get('baudrate', 9600),
                'pps_gpio_pin': gps_settings.get('pps_gpio_pin', 18),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error(f"Error getting GPS status: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/hardware/gps/trends', methods=['GET'])
    def get_gps_trends():
        """Return the server-side ring buffer of GPS / chrony trend samples.

        Accepts a ``?window=`` query parameter that selects which
        resolution tier to return.  Each tier is sized so the dashboard
        gets ~1000–2200 samples regardless of window — what changes is
        the time-resolution of each sample, not the sample count:

            window  →  tier   bucket    span
            -------    -----  --------  -------
            1h         raw    5 s       ≈ 1.1 h   (live tail)
            6h, 24h    1m     1 min     ≈ 25 h
            7d         10m    10 min    ≈ 7.6 d
            30d, 90d   1h     1 h       ≈ 91 d

        Unknown / missing windows fall back to ``raw`` for backward
        compatibility with the old single-tier client.
        """
        window = (request.args.get("window") or GPS_TRENDS_DEFAULT_WINDOW).lower()
        tier = GPS_TRENDS_WINDOW_TO_TIER.get(window, "raw")
        bucket_s, cap = GPS_TRENDS_TIERS.get(tier, GPS_TRENDS_TIERS["raw"])

        try:
            samples: list = []
            if _redis_client:
                try:
                    raw_items = _redis_client.lrange(
                        _gps_trend_redis_key(tier), 0, cap - 1
                    ) or []
                except Exception as exc:
                    logger.debug("GPS trends: lrange failed: %s", exc)
                    raw_items = []
                # Stored newest-first, reverse for chronological output.
                for raw in reversed(raw_items):
                    try:
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="replace")
                        samples.append(json.loads(raw))
                    except Exception as exc:
                        # Skip malformed rows so one bad entry can't
                        # poison the whole chart, but log at debug so an
                        # operator can spot systematic corruption.
                        logger.debug("GPS trends: skipping malformed row: %s", exc)
                        continue
            return jsonify({
                'samples': samples,
                'tier': tier,
                'window': window,
                'bucket_seconds': bucket_s,
                'capacity': cap,
            })
        except Exception:
            # Log full detail server-side; return a generic message to
            # the client so we don't leak internal paths / library
            # exception text (CodeQL py/stack-trace-exposure).
            logger.error("Error getting GPS trends", exc_info=True)
            return jsonify({'success': False, 'error': 'gps_trends_unavailable'}), 500

    @api_app.route('/api/hardware/gps/configure', methods=['POST'])
    def configure_gps():
        """Save GPS configuration and restart the GPS manager."""
        try:
            data = request.json or {}

            from app_core.hardware_settings import get_hardware_settings, update_hardware_settings

            settings = get_hardware_settings()
            update_fields = {}

            if 'enabled' in data:
                update_fields['gps_enabled'] = bool(data['enabled'])
            if 'serial_port' in data:
                update_fields['gps_serial_port'] = str(data['serial_port'])
            if 'baudrate' in data:
                update_fields['gps_baudrate'] = int(data['baudrate'])
            if 'pps_gpio_pin' in data:
                update_fields['gps_pps_gpio_pin'] = int(data['pps_gpio_pin'])
            if 'use_for_location' in data:
                update_fields['gps_use_for_location'] = bool(data['use_for_location'])
            if 'use_for_time' in data:
                update_fields['gps_use_for_time'] = bool(data['use_for_time'])
            if 'min_satellites' in data:
                update_fields['gps_min_satellites'] = max(1, int(data['min_satellites']))

            if update_fields:
                update_hardware_settings(update_fields)

            # Restart GPS manager with new settings
            global _gps_manager
            if _gps_manager is not None:
                _gps_manager.stop()
                _gps_manager = None

            if update_fields.get('gps_enabled', settings.gps_enabled):
                with api_app.app_context() if hasattr(api_app, 'app_context') else _flask_app.app_context():
                    initialize_gps_manager()

            return jsonify({'success': True, 'message': 'GPS configuration saved'})

        except Exception as e:
            logger.error(f"Error configuring GPS: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # ------------------------------------------------------------------
    # Display push endpoint
    # Called by the web service (port 5000) to push a configured screen
    # to OLED / LED / VFD hardware without the web worker touching I2C
    # directly (which deadlocks the gevent event loop).
    # ------------------------------------------------------------------

    @api_app.route('/api/hardware/display/push', methods=['POST'])
    def push_screen_to_display():
        """Render a DisplayScreen and push it to the physical display.

        The web service proxies POST /api/screens/<id>/display here so that
        all blocking I2C / GPIO / serial ioctl() calls happen in this process
        (eas-station-hardware.service), never in the gevent web workers.

        Request body (JSON): { "screen_id": <int> }
        """
        try:
            data = request.json or {}
            screen_id = data.get('screen_id')
            if not screen_id:
                return jsonify({'success': False, 'error': 'screen_id is required'}), 400

            with _flask_app.app_context():
                from app_core.models import DisplayScreen
                from scripts.screen_renderer import ScreenRenderer

                screen = DisplayScreen.query.get(int(screen_id))
                if not screen:
                    return jsonify({'success': False, 'error': 'Screen not found'}), 404

                renderer = ScreenRenderer(allow_preview_samples=False)
                rendered = renderer.render_screen(screen.to_dict())
                if not rendered:
                    return jsonify({'success': False, 'error': 'Failed to render screen'}), 500

                if screen.display_type == 'oled':
                    from app_core.oled import oled_controller, OLEDLine
                    if not oled_controller:
                        return jsonify({'success': False, 'error': 'OLED controller not available'}), 503

                    # New elements-based format (bar graphs, shapes, icons, etc.)
                    raw_elements = rendered.get('elements')
                    if raw_elements is not None and isinstance(raw_elements, list):
                        oled_controller.render_frame(
                            raw_elements,
                            clear=rendered.get('clear', True),
                            invert=rendered.get('invert'),
                        )
                    else:
                        # Legacy lines-based format
                        raw_lines = rendered.get('lines', [])
                        line_objects = []
                        for entry in raw_lines:
                            if not isinstance(entry, dict):
                                continue
                            try:
                                x_val = int(entry.get('x', 0) or 0)
                            except (TypeError, ValueError):
                                x_val = 0
                            y_raw = entry.get('y')
                            try:
                                y_val = int(y_raw) if y_raw is not None else None
                            except (TypeError, ValueError):
                                y_val = None
                            mw_raw = entry.get('max_width')
                            try:
                                mw_val = int(mw_raw) if mw_raw is not None else None
                            except (TypeError, ValueError):
                                mw_val = None
                            try:
                                sp_val = int(entry.get('spacing', 2))
                            except (TypeError, ValueError):
                                sp_val = 2
                            line_objects.append(OLEDLine(
                                text=str(entry.get('text', '')),
                                x=x_val,
                                y=y_val,
                                font=str(entry.get('font', 'small')),
                                wrap=bool(entry.get('wrap', True)),
                                max_width=mw_val,
                                spacing=sp_val,
                                invert=entry.get('invert'),
                                allow_empty=bool(entry.get('allow_empty', False)),
                            ))
                        oled_controller.display_lines(
                            line_objects,
                            clear=rendered.get('clear', True),
                            invert=rendered.get('invert'),
                        )

                elif screen.display_type == 'led':
                    import app_core.led as led_module
                    if not led_module.led_controller:
                        return jsonify({'success': False, 'error': 'LED controller not available'}), 503
                    from webapp.routes_screens import _convert_led_enum
                    lines = rendered.get('lines', [])
                    color_str = rendered.get('color', 'AMBER')
                    mode_str = rendered.get('mode', 'HOLD')
                    speed_str = rendered.get('speed', 'SPEED_3')
                    color = _convert_led_enum(led_module.Color, color_str,
                                             led_module.Color.AMBER if led_module.Color else color_str)
                    mode = _convert_led_enum(led_module.DisplayMode, mode_str,
                                            led_module.DisplayMode.HOLD if led_module.DisplayMode else mode_str)
                    speed = _convert_led_enum(led_module.Speed, speed_str,
                                             led_module.Speed.SPEED_3 if led_module.Speed else speed_str)
                    led_module.led_controller.send_message(lines=lines, color=color, mode=mode, speed=speed)

                elif screen.display_type == 'vfd':
                    from app_core.vfd import vfd_controller
                    if not vfd_controller:
                        return jsonify({'success': False, 'error': 'VFD controller not available'}), 503
                    for command in rendered:
                        cmd_type = command.get('type')
                        if cmd_type == 'clear':
                            vfd_controller.clear_display()
                        elif cmd_type == 'text':
                            vfd_controller.draw_text(
                                command.get('text', ''), command.get('x', 0), command.get('y', 0))
                        elif cmd_type == 'rectangle':
                            vfd_controller.draw_rectangle(
                                command.get('x1', 0), command.get('y1', 0),
                                command.get('x2', 10), command.get('y2', 10),
                                filled=command.get('filled', False))
                        elif cmd_type == 'line':
                            vfd_controller.draw_line(
                                command.get('x1', 0), command.get('y1', 0),
                                command.get('x2', 10), command.get('y2', 10))
                else:
                    return jsonify({'success': False,
                                    'error': f"Unknown display_type '{screen.display_type}'"}), 400

                # Update display statistics
                screen.display_count = (screen.display_count or 0) + 1
                from app_utils import utc_now as _utc_now
                screen.last_displayed_at = _utc_now()
                from app_core.extensions import db as _db
                _db.session.commit()

            return jsonify({'success': True,
                            'message': f"Screen '{screen.name}' displayed on {screen.display_type}"})

        except Exception as exc:
            logger.error('Error pushing screen to display: %s', exc, exc_info=True)
            return jsonify({'success': False, 'error': str(exc)}), 500

    return api_app


def run_api_server():
    """Run Flask API server in background thread."""
    try:
        api_app = create_api_app()
        # Run on port 5001 (app uses 5000)
        api_app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Error running API server: {e}", exc_info=True)


def _update_alert_indicators(
    broadcast_was_active: bool,
    incoming_was_active: bool,
) -> tuple:
    """Drive tower light + NeoPixel based on broadcast / incoming alert state.

    Thin wrapper that hands the orchestrator-owned controllers to the
    pure state-machine in ``services.gpio.alert_indicators``.
    """
    return _update_alert_indicators_impl(
        broadcast_was_active,
        incoming_was_active,
        tower_light_controller=_tower_light_controller,
        neopixel_controller=_neopixel_controller,
    )


def health_check_loop():
    """Periodic health check and metrics publishing."""
    global _running

    logger.info("📊 Hardware monitoring started")
    last_metrics_publish = 0
    metrics_interval = 5  # Publish metrics every 5 seconds
    broadcast_was_active = False  # Track last-known broadcast state
    incoming_was_active = False   # Track last-known incoming-alert state

    while _running:
        try:
            current_time = time.time()

            # Drive alert indicators (tower light, NeoPixel) based on
            # broadcast state; runs every loop iteration (1 s resolution).
            if _redis_client and (_tower_light_controller or _neopixel_controller):
                broadcast_was_active, incoming_was_active = _update_alert_indicators(
                    broadcast_was_active, incoming_was_active
                )

            # Publish metrics periodically
            if current_time - last_metrics_publish >= metrics_interval:
                publish_hardware_metrics()
                # The trend sampler runs at the same cadence as the metrics
                # publish (5 s) — see GPS_TRENDS_INTERVAL_S.  Keeping them
                # in lockstep avoids adding a second timer to this loop.
                publish_gps_trend_sample()
                last_metrics_publish = current_time

            # Sleep briefly
            time.sleep(1)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error in health check loop: {e}", exc_info=True)
            time.sleep(5)


def main():
    """Main entry point for hardware service."""
    global _running, _flask_app

    logger.info("=" * 60)
    logger.info("🔌 EAS Station - Dedicated Hardware Service")
    logger.info("=" * 60)

    # Apply glibc tuning + start the malloc_trim ticker + install the
    # SIGUSR1/SIGUSR2 memory-diagnostic handlers in one call.  Must
    # happen before any worker threads spawn — see
    # services/common/bootstrap.py for the full rationale.
    init_runtime("hardware")

    install_signal_handlers(_on_shutdown_signal)

    try:
        # Initialize Redis
        logger.info("Connecting to Redis...")
        get_redis_client()
        logger.info("✅ Connected to Redis")

        # Initialize database
        logger.info("Initializing database connection...")
        app, db = initialize_database()
        _flask_app = app  # Store for health check loop (publish_hardware_metrics needs app context)
        logger.info("✅ Database connected")

        # Initialize hardware controllers (must be done before screen manager)
        with app.app_context():
            logger.info("Initializing LED controller...")
            initialize_led_controller()

            logger.info("Initializing VFD controller...")
            initialize_vfd_controller()

            logger.info("Initializing OLED display...")
            initialize_oled_display()

        # Initialize screen manager (depends on LED/VFD/OLED controllers)
        logger.info("Initializing screen manager...")
        initialize_screen_manager(app)

        # Initialize GPIO controller (needs db session for audit logging)
        logger.info("Initializing GPIO controller...")
        with app.app_context():
            initialize_gpio_controller(db_session=db.session)

        # Initialize NeoPixel controller
        logger.info("Initializing NeoPixel controller...")
        with app.app_context():
            initialize_neopixel_controller()

        # Initialize USB tower light controller
        logger.info("Initializing USB tower light controller...")
        with app.app_context():
            initialize_tower_light_controller()

        # Initialize Zigbee coordinator (if configured)
        logger.info("Initializing Zigbee coordinator...")
        with app.app_context():
            initialize_zigbee_coordinator()

        # Initialize GPS receiver (if configured)
        logger.info("Initializing GPS receiver...")
        with app.app_context():
            initialize_gps_manager()

        # Start Flask API server in background thread
        logger.info("Starting hardware proxy API server on port 5001...")
        api_thread = threading.Thread(target=run_api_server, daemon=True)
        api_thread.start()
        logger.info("✅ Hardware proxy API server started")

        # Start health check loop
        health_check_loop()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error in hardware service: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        logger.info("Shutting down hardware service...")

        if _screen_manager:
            try:
                if hasattr(_screen_manager, 'stop'):
                    _screen_manager.stop()
            except Exception as e:
                logger.error(f"Error stopping screen manager: {e}")

        if _gpio_controller:
            try:
                if hasattr(_gpio_controller, 'cleanup'):
                    _gpio_controller.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up GPIO: {e}")

        if _neopixel_controller:
            try:
                _neopixel_controller.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up NeoPixel controller: {e}")

        if _tower_light_controller:
            try:
                _tower_light_controller.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up USB tower light: {e}")

        if _zigpy_controller:
            try:
                _zigpy_controller.stop()
            except Exception as e:
                logger.error(f"Error stopping Zigbee controller: {e}")

        if _gps_manager:
            try:
                _gps_manager.stop()
            except Exception as e:
                logger.error(f"Error stopping GPS manager: {e}")

        if _redis_client:
            try:
                _redis_client.close()
            except Exception:
                pass

        logger.info("✅ Hardware service stopped cleanly")


if __name__ == "__main__":
    main()
