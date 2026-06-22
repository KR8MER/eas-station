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

"""Flask blueprint for ``/api/network/*`` endpoints.

All routes are pure proxies onto the helpers in ``app_utils.network``
(nmcli wrappers, hostname helpers).  No orchestrator-owned runtime
state is required, so ``create_blueprint`` takes no arguments.
"""

import ipaddress
import logging
import time

from flask import Blueprint, jsonify, request

from app_utils.network import (
    check_nmcli_available,
    enhance_error_message,
    get_hostname,
    get_wifi_interface,
    run_command,
    set_hostname,
)

logger = logging.getLogger(__name__)


def create_blueprint() -> Blueprint:
    """Build and return the ``/api/network/*`` blueprint."""
    bp = Blueprint("network_api", __name__)

    @bp.route('/api/network/status', methods=['GET'])
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

    @bp.route('/api/network/scan', methods=['POST'])
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

    @bp.route('/api/network/connect', methods=['POST'])
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

    @bp.route('/api/network/disconnect', methods=['POST'])
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

    @bp.route('/api/network/forget', methods=['POST'])
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

    @bp.route('/api/network/interfaces', methods=['GET'])
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

    @bp.route('/api/network/interface/configure', methods=['POST'])
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

    @bp.route('/api/network/dns', methods=['GET'])
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

    @bp.route('/api/network/dns/configure', methods=['POST'])
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

    @bp.route('/api/network/diagnostics/ping', methods=['POST'])
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

    @bp.route('/api/network/diagnostics/traceroute', methods=['POST'])
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

    @bp.route('/api/network/diagnostics/nslookup', methods=['POST'])
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

    @bp.route('/api/network/diagnostics/route', methods=['GET'])
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

    @bp.route('/api/network/diagnostics/gateway', methods=['GET'])
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

    @bp.route('/api/network/connections', methods=['GET'])
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

    @bp.route('/api/network/connection/activate', methods=['POST'])
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

    @bp.route('/api/network/connection/deactivate', methods=['POST'])
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

    @bp.route('/api/network/connection/autoconnect', methods=['POST'])
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

    # Hostname Configuration Endpoints

    @bp.route('/api/network/hostname', methods=['GET'])
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

    @bp.route('/api/network/hostname', methods=['POST'])
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

    return bp
