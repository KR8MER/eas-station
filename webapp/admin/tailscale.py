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

"""Tailscale VPN management routes.

Provides web UI and API endpoints for configuring Tailscale on the EAS Station.
Tailscale operations require elevated privileges (sudo) since they interact
with the tailscaled daemon and network configuration.
"""

import logging
import re
import subprocess

from flask import Blueprint, jsonify, request, render_template
from werkzeug.exceptions import BadRequest

from app_core.auth.decorators import require_permission
from app_core.extensions import db
from app_core.tailscale_settings import (
    get_tailscale_settings,
    update_tailscale_settings,
)

logger = logging.getLogger(__name__)

tailscale_bp = Blueprint('tailscale', __name__)

# Validation patterns
HOSTNAME_PATTERN = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?$')
CIDR_PATTERN = re.compile(r'^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$')


def _run_tailscale_cmd(args, timeout=30):
    """Run a tailscale CLI command.

    Tailscale CLI commands communicate with tailscaled via a Unix socket and
    do not require sudo. Only systemctl operations on the daemon need root.

    Args:
        args: List of arguments to pass after 'tailscale'
        timeout: Command timeout in seconds

    Returns:
        dict with 'success', 'stdout', 'stderr', and 'returncode'
    """
    cmd = ['tailscale'] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip(),
            'returncode': result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'stdout': '',
            'stderr': 'Command timed out',
            'returncode': -1,
        }
    except FileNotFoundError:
        return {
            'success': False,
            'stdout': '',
            'stderr': 'Tailscale is not installed on this system',
            'returncode': -1,
        }
    except Exception as e:
        logger.error(f"Tailscale command failed: {e}")
        return {
            'success': False,
            'stdout': '',
            'stderr': str(e),
            'returncode': -1,
        }


def _check_tailscale_installed():
    """Check if tailscale binary is available.

    Returns:
        dict with 'installed' bool and 'version' string if installed
    """
    try:
        result = subprocess.run(
            ['which', 'tailscale'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {'installed': False, 'version': None}

        ver = _run_tailscale_cmd(['version'], timeout=5)
        version = ver['stdout'].split('\n')[0] if ver['success'] else 'unknown'
        return {'installed': True, 'version': version}
    except Exception:
        return {'installed': False, 'version': None}


def _check_tailscaled_running():
    """Check if the tailscaled daemon is running.

    Tries systemctl first (may need sudo), then falls back to pgrep.

    Returns:
        bool
    """
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', 'tailscaled'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip() == 'active':
            return True

        # Fallback: check via process list (no sudo needed)
        pgrep = subprocess.run(
            ['pgrep', '-x', 'tailscaled'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return pgrep.returncode == 0
    except Exception:
        return False


def _validate_routes(routes_str):
    """Validate comma-separated CIDR routes.

    Args:
        routes_str: Comma-separated CIDR strings

    Returns:
        tuple of (valid: bool, cleaned: str, error: str or None)
    """
    if not routes_str or not routes_str.strip():
        return True, '', None

    routes = [r.strip() for r in routes_str.split(',') if r.strip()]
    for route in routes:
        if not CIDR_PATTERN.match(route):
            return False, routes_str, f"Invalid CIDR notation: {route}"
    return True, ','.join(routes), None


# ============================================================================
# UI Route
# ============================================================================

@tailscale_bp.route('/tailscale')
@require_permission('system.configure')
def tailscale_settings_page():
    """Display Tailscale VPN configuration page."""
    try:
        settings = get_tailscale_settings()
        return render_template(
            'admin/tailscale.html',
            settings=settings,
        )
    except Exception as exc:
        logger.error(f"Failed to load Tailscale settings: {exc}")
        from flask import flash, redirect, url_for
        flash(f"Error loading Tailscale settings: {exc}", "error")
        return redirect(url_for('dashboard.admin'))


# ============================================================================
# Settings API
# ============================================================================

@tailscale_bp.route('/api/tailscale/settings', methods=['GET'])
@require_permission('system.configure')
def get_settings():
    """Get current Tailscale settings."""
    try:
        settings = get_tailscale_settings()
        return jsonify({
            "success": True,
            "settings": settings.to_dict(),
        })
    except Exception as exc:
        logger.error(f"Failed to get Tailscale settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@tailscale_bp.route('/api/tailscale/settings', methods=['PUT'])
@require_permission('system.configure')
def update_settings():
    """Update Tailscale settings."""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        # Convert boolean fields
        bool_fields = [
            'enabled', 'advertise_exit_node', 'accept_routes',
            'shields_up', 'accept_dns',
        ]
        for field in bool_fields:
            if field in data:
                if isinstance(data[field], str):
                    data[field] = data[field].lower() in ('true', '1', 'yes', 'on')
                else:
                    data[field] = bool(data[field])

        # Validate hostname
        if 'hostname' in data and data['hostname']:
            hostname = data['hostname'].strip()
            if not HOSTNAME_PATTERN.match(hostname):
                raise BadRequest(
                    "Invalid hostname. Only alphanumeric characters and hyphens allowed. "
                    "Must start and end with alphanumeric."
                )
            if len(hostname) > 63:
                raise BadRequest("Hostname must be 63 characters or fewer")
            data['hostname'] = hostname

        # Validate advertise_routes
        if 'advertise_routes' in data and data['advertise_routes']:
            valid, cleaned, error = _validate_routes(data['advertise_routes'])
            if not valid:
                raise BadRequest(error)
            data['advertise_routes'] = cleaned

        settings = update_tailscale_settings(data)

        logger.info("Tailscale settings updated successfully")

        return jsonify({
            "success": True,
            "message": "Tailscale settings updated successfully.",
            "settings": settings.to_dict(),
        })

    except BadRequest as exc:
        logger.warning(f"Bad request updating Tailscale settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 400

    except Exception as exc:
        logger.error(f"Failed to update Tailscale settings: {exc}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500


# ============================================================================
# Status & Control API
# ============================================================================

@tailscale_bp.route('/api/tailscale/status', methods=['GET'])
@require_permission('system.configure')
def get_status():
    """Get Tailscale daemon and connection status."""
    try:
        install_info = _check_tailscale_installed()
        if not install_info['installed']:
            return jsonify({
                "success": True,
                "installed": False,
                "status": "not_installed",
                "message": "Tailscale is not installed on this system",
            })

        daemon_running = _check_tailscaled_running()

        # Even if the process check says the daemon is not running, try getting
        # the status anyway — the socket may still be accessible (e.g. process
        # detection failed, or the service is managed differently).
        if not daemon_running:
            probe = _run_tailscale_cmd(['status', '--json'], timeout=5)
            if probe['success']:
                daemon_running = True

        status_info = {
            "success": True,
            "installed": True,
            "version": install_info['version'],
            "daemon_running": daemon_running,
            "status": "stopped" if not daemon_running else "unknown",
            "ip": None,
            "tailnet": None,
            "backend_state": None,
            "peers": [],
        }

        if daemon_running:
            # Get tailscale status
            result = _run_tailscale_cmd(['status', '--json'], timeout=10)
            if result['success']:
                import json
                try:
                    status_data = json.loads(result['stdout'])
                    backend_state = status_data.get('BackendState', 'Unknown')
                    status_info['backend_state'] = backend_state

                    if backend_state == 'Running':
                        status_info['status'] = 'connected'
                    elif backend_state == 'NeedsLogin':
                        status_info['status'] = 'needs_login'
                    elif backend_state == 'Stopped':
                        status_info['status'] = 'stopped'
                    else:
                        status_info['status'] = backend_state.lower()

                    # Get self node info
                    self_node = status_data.get('Self', {})
                    if self_node:
                        ts_ips = self_node.get('TailscaleIPs', [])
                        if ts_ips:
                            status_info['ip'] = ts_ips[0]
                        status_info['hostname'] = self_node.get('HostName', '')
                        status_info['dns_name'] = self_node.get('DNSName', '')
                        status_info['online'] = self_node.get('Online', False)
                        status_info['exit_node'] = self_node.get('ExitNode', False)

                    # Get tailnet name
                    current_tailnet = status_data.get('CurrentTailnet', {})
                    if current_tailnet:
                        status_info['tailnet'] = current_tailnet.get('Name', '')
                        status_info['magic_dns_suffix'] = current_tailnet.get('MagicDNSSuffix', '')

                    # Get peer info
                    peers = status_data.get('Peer', {})
                    peer_list = []
                    for peer_id, peer_data in peers.items():
                        peer_list.append({
                            'hostname': peer_data.get('HostName', ''),
                            'dns_name': peer_data.get('DNSName', ''),
                            'ips': peer_data.get('TailscaleIPs', []),
                            'online': peer_data.get('Online', False),
                            'exit_node': peer_data.get('ExitNode', False),
                            'os': peer_data.get('OS', ''),
                        })
                    status_info['peers'] = peer_list

                except json.JSONDecodeError:
                    status_info['status'] = 'error'
                    status_info['message'] = 'Failed to parse status output'
            else:
                # tailscale status failed, get basic info
                status_info['status'] = 'error'
                status_info['message'] = result['stderr'] or 'Failed to get status'

        return jsonify(status_info)

    except Exception as exc:
        logger.error(f"Failed to get Tailscale status: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@tailscale_bp.route('/api/tailscale/start', methods=['POST'])
@require_permission('system.configure')
def start_tailscale():
    """Start the tailscaled daemon and bring up the connection."""
    try:
        install_info = _check_tailscale_installed()
        if not install_info['installed']:
            return jsonify({
                "success": False,
                "error": "Tailscale is not installed on this system",
            }), 400

        settings = get_tailscale_settings()

        # Ensure tailscaled daemon is running
        if not _check_tailscaled_running():
            daemon_result = subprocess.run(
                ['sudo', 'systemctl', 'start', 'tailscaled'],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if daemon_result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": f"Failed to start tailscaled daemon: {daemon_result.stderr}",
                }), 500

            # Enable daemon to start on boot
            subprocess.run(
                ['sudo', 'systemctl', 'enable', 'tailscaled'],
                capture_output=True,
                text=True,
                timeout=10,
            )

        # Build tailscale up command
        up_args = ['up']

        if settings.auth_key:
            up_args.extend(['--authkey', settings.auth_key])

        if settings.hostname:
            up_args.extend(['--hostname', settings.hostname])

        if settings.advertise_exit_node:
            up_args.append('--advertise-exit-node')

        if settings.advertise_routes:
            up_args.extend(['--advertise-routes', settings.advertise_routes])

        if settings.shields_up:
            up_args.append('--shields-up')

        if settings.accept_routes:
            up_args.append('--accept-routes')

        if not settings.accept_dns:
            up_args.extend(['--accept-dns=false'])

        up_args.append('--reset')

        result = _run_tailscale_cmd(up_args, timeout=30)

        if result['success']:
            logger.info("Tailscale started successfully")
            return jsonify({
                "success": True,
                "message": "Tailscale started successfully",
                "output": result['stdout'],
            })
        else:
            # Check if login is needed
            if 'login' in result['stderr'].lower() or 'auth' in result['stderr'].lower():
                return jsonify({
                    "success": False,
                    "needs_login": True,
                    "error": "Authentication required. Provide an auth key in settings or use the login URL.",
                    "output": result['stderr'],
                }), 400
            return jsonify({
                "success": False,
                "error": f"Failed to start Tailscale: {result['stderr']}",
                "output": result['stdout'],
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error": "Operation timed out",
        }), 500
    except Exception as exc:
        logger.error(f"Failed to start Tailscale: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@tailscale_bp.route('/api/tailscale/stop', methods=['POST'])
@require_permission('system.configure')
def stop_tailscale():
    """Disconnect Tailscale and optionally stop the daemon."""
    try:
        install_info = _check_tailscale_installed()
        if not install_info['installed']:
            return jsonify({
                "success": False,
                "error": "Tailscale is not installed on this system",
            }), 400

        # Bring down the tailscale connection
        result = _run_tailscale_cmd(['down'], timeout=15)

        if result['success']:
            logger.info("Tailscale disconnected successfully")
            return jsonify({
                "success": True,
                "message": "Tailscale disconnected successfully",
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to disconnect Tailscale: {result['stderr']}",
            }), 500

    except Exception as exc:
        logger.error(f"Failed to stop Tailscale: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@tailscale_bp.route('/api/tailscale/login-url', methods=['POST'])
@require_permission('system.configure')
def get_login_url():
    """Generate a Tailscale login URL for browser-based authentication."""
    try:
        install_info = _check_tailscale_installed()
        if not install_info['installed']:
            return jsonify({
                "success": False,
                "error": "Tailscale is not installed on this system",
            }), 400

        # Ensure daemon is running first
        if not _check_tailscaled_running():
            daemon_result = subprocess.run(
                ['sudo', 'systemctl', 'start', 'tailscaled'],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if daemon_result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": f"Failed to start tailscaled daemon: {daemon_result.stderr}",
                }), 500

        settings = get_tailscale_settings()

        # Build login command
        login_args = ['login']
        if settings.hostname:
            login_args.extend(['--hostname', settings.hostname])

        result = _run_tailscale_cmd(login_args, timeout=15)

        # The login URL is usually in stderr for interactive login
        output = result['stderr'] or result['stdout']

        # Extract URL from output
        import re as _re
        url_match = _re.search(r'(https://login\.tailscale\.com/\S+)', output)
        if url_match:
            login_url = url_match.group(1)
            return jsonify({
                "success": True,
                "login_url": login_url,
                "message": "Open this URL in a browser to authenticate",
            })
        elif result['success']:
            return jsonify({
                "success": True,
                "message": "Already authenticated",
                "output": output,
            })
        else:
            return jsonify({
                "success": False,
                "error": output or "Failed to generate login URL",
            }), 500

    except Exception as exc:
        logger.error(f"Failed to get Tailscale login URL: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@tailscale_bp.route('/api/tailscale/logout', methods=['POST'])
@require_permission('system.configure')
def logout_tailscale():
    """Log out of Tailscale, removing this node from the tailnet."""
    try:
        result = _run_tailscale_cmd(['logout'], timeout=15)

        if result['success']:
            logger.info("Tailscale logged out successfully")
            return jsonify({
                "success": True,
                "message": "Logged out of Tailscale. This node has been removed from the tailnet.",
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Failed to logout: {result['stderr']}",
            }), 500

    except Exception as exc:
        logger.error(f"Failed to logout from Tailscale: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@tailscale_bp.route('/api/tailscale/ping', methods=['POST'])
@require_permission('system.configure')
def ping_peer():
    """Ping a Tailscale peer to check connectivity."""
    try:
        data = request.get_json()
        target = data.get('target', '').strip()

        if not target:
            return jsonify({
                "success": False,
                "error": "Target hostname or IP is required",
            }), 400

        # Basic input validation to prevent command injection
        if not re.match(r'^[a-zA-Z0-9.\-:]+$', target):
            return jsonify({
                "success": False,
                "error": "Invalid target. Only alphanumeric characters, dots, hyphens, and colons allowed.",
            }), 400

        result = _run_tailscale_cmd(['ping', '-c', '3', target], timeout=15)

        return jsonify({
            "success": result['success'],
            "output": result['stdout'] or result['stderr'],
            "message": "Ping completed" if result['success'] else "Ping failed",
        })

    except Exception as exc:
        logger.error(f"Tailscale ping failed: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@tailscale_bp.route('/api/tailscale/install', methods=['POST'])
@require_permission('system.configure')
def install_tailscale():
    """Install Tailscale using the official install script."""
    try:
        install_info = _check_tailscale_installed()
        if install_info['installed']:
            return jsonify({
                "success": True,
                "already_installed": True,
                "message": f"Tailscale is already installed (version {install_info['version']})",
            })

        # Run the official Tailscale install script
        result = subprocess.run(
            ['sudo', 'sh', '-c', 'curl -fsSL https://tailscale.com/install.sh | sh'],
            capture_output=True,
            text=True,
            timeout=180,
        )

        output = (result.stdout + result.stderr).strip()

        if result.returncode == 0:
            # Enable and start the daemon after install
            subprocess.run(
                ['sudo', 'systemctl', 'enable', '--now', 'tailscaled'],
                capture_output=True,
                text=True,
                timeout=15,
            )
            logger.info("Tailscale installed successfully")
            return jsonify({
                "success": True,
                "message": "Tailscale installed successfully. You can now connect from the Status tab.",
                "output": output,
            })
        else:
            logger.error(f"Tailscale install failed (rc={result.returncode}): {output}")
            return jsonify({
                "success": False,
                "error": "Installation failed. See output for details.",
                "output": output,
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error": "Installation timed out after 3 minutes.",
        }), 500
    except Exception as exc:
        logger.error(f"Tailscale install error: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


def register_tailscale_routes(app, logger):
    """Register Tailscale admin routes with the Flask app.

    Routes are registered with url_prefix='/admin', so Flask combines them:
    - Blueprint route '/tailscale' becomes '/admin/tailscale'
    - Blueprint route '/api/tailscale/settings' becomes '/admin/api/tailscale/settings'
    """
    app.register_blueprint(tailscale_bp, url_prefix='/admin')
    logger.info("Tailscale admin routes registered")


__all__ = ['tailscale_bp', 'register_tailscale_routes']
