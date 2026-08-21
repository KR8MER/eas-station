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

"""Icecast streaming server settings management routes."""

import logging
import os
import re
import requests
import secrets
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import BadRequest

from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger
from app_core.extensions import db
from app_core.icecast_settings import (
    get_icecast_settings,
    update_icecast_settings,
    invalidate_icecast_settings_cache,
)

logger = logging.getLogger(__name__)

# Create Blueprint for icecast routes
icecast_bp = Blueprint('icecast', __name__)


def _get_env_file_path() -> Path:
    """Get the path to the .env file.
    
    Returns the CONFIG_PATH if set (persistent volume), otherwise the .env
    file in the project root.
    """
    config_path = os.environ.get('CONFIG_PATH')
    if config_path:
        return Path(config_path)
    
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent.parent
    return project_root / '.env'


def _update_icecast_config_file(source_password: str, admin_password: str, admin_user: str = 'admin', max_sources: Optional[int] = None) -> tuple[bool, str]:
    """Update Icecast server configuration file with new credentials and limits.

    Args:
        source_password: New source password
        admin_password: New admin password
        admin_user: Admin username (default: 'admin')
        max_sources: Maximum concurrent sources (None/0 = unlimited, positive int = limit)

    Returns:
        Tuple of (success: bool, message: str)
    """
    config_file = '/etc/icecast2/icecast.xml'

    if not Path(config_file).exists():
        return False, f"Icecast config not found at {config_file}"

    try:
        # Read the current config using sudo (ProtectSystem blocks direct read)
        result = subprocess.run(
            ['sudo', '/usr/bin/cat', config_file],
            capture_output=True, timeout=10
        )
        if result.returncode != 0:
            return False, f"Failed to read config: {result.stderr.decode('utf-8', errors='replace')}"

        content = result.stdout.decode('utf-8')

        # Replace passwords using regex
        content = re.sub(r'<source-password>.*?</source-password>',
                        f'<source-password>{source_password}</source-password>', content)
        content = re.sub(r'<admin-user>.*?</admin-user>',
                        f'<admin-user>{admin_user}</admin-user>', content)
        content = re.sub(r'<admin-password>.*?</admin-password>',
                        f'<admin-password>{admin_password}</admin-password>', content)
        
        # Update max sources limit
        if max_sources is not None:
            # If max_sources is 0 or None, set unlimited (0)
            sources_limit = 0 if max_sources == 0 else max_sources
            
            # Check if <limits> section exists
            if '<limits>' in content:
                # Check if <sources> tag exists within <limits>
                if re.search(r'<limits>.*?<sources>\d+</sources>.*?</limits>', content, re.DOTALL):
                    # Replace existing <sources> tag
                    content = re.sub(
                        r'(<limits>.*?)<sources>\d+</sources>(.*?</limits>)',
                        rf'\1<sources>{sources_limit}</sources>\2',
                        content,
                        flags=re.DOTALL
                    )
                else:
                    # Add <sources> tag inside existing <limits> section
                    content = re.sub(
                        r'(<limits>)',
                        rf'\1\n        <sources>{sources_limit}</sources>',
                        content
                    )
            else:
                # Add entire <limits> section after <authentication> section
                limits_section = f'''
    <limits>
        <sources>{sources_limit}</sources>
    </limits>'''
                # Insert after </authentication> closing tag
                content = re.sub(
                    r'(</authentication>)',
                    rf'\1{limits_section}',
                    content
                )

        # Write to temp file then copy with sudo
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        # Make temp file readable by root for sudo cp
        os.chmod(tmp_path, 0o644)

        # Copy temp file to config location with sudo
        result = subprocess.run(
            ['sudo', '/usr/bin/cp', tmp_path, config_file],
            capture_output=True, timeout=10
        )
        os.unlink(tmp_path)  # Clean up temp file

        if result.returncode != 0:
            return False, f"Failed to copy config: {result.stderr.decode('utf-8', errors='replace')}"

        # Restart Icecast service
        result = subprocess.run(['sudo', '/usr/bin/systemctl', 'restart', 'icecast2'], capture_output=True, timeout=10)
        if result.returncode != 0:
            return False, f"Config updated but failed to restart icecast2: {result.stderr.decode('utf-8', errors='replace')}"

        # Restart audio service so it picks up new credentials
        result = subprocess.run(['sudo', '/usr/bin/systemctl', 'restart', 'eas-station-audio'], capture_output=True, timeout=30)
        if result.returncode != 0:
            logger.warning(f"Failed to restart audio service: {result.stderr.decode('utf-8', errors='replace')}")

        return True, "Icecast config updated and services restarted"

    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        logger.error(f"Error updating Icecast config: {e}")
        return False, str(e)


# Routes are relative to blueprint's url_prefix='/admin'
# e.g., route '/icecast' becomes '/admin/icecast'
@icecast_bp.route('/icecast')
@require_permission('system.configure')
def icecast_settings_page():
    """Display Icecast settings configuration page."""
    try:
        settings = get_icecast_settings()

        return render_template(
            'admin/icecast.html',
            settings=settings,
        )
    except Exception as exc:
        logger.error(f"Failed to load Icecast settings: {exc}")
        flash(f"Error loading Icecast settings: {exc}", "error")
        return redirect(url_for('dashboard.admin'))


@icecast_bp.route('/api/icecast/settings', methods=['GET'])
@require_permission('system.configure')
def get_settings():
    """Get current Icecast settings."""
    try:
        settings = get_icecast_settings()
        return jsonify({
            "success": True,
            "settings": settings.to_dict(),
        })
    except Exception as exc:
        logger.error(f"Failed to get Icecast settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@icecast_bp.route('/api/icecast/settings', methods=['PUT'])
@require_permission('system.configure')
def update_settings():
    """Update Icecast settings."""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        # Convert boolean fields
        bool_fields = ['enabled', 'stream_public']
        for field in bool_fields:
            if field in data:
                if isinstance(data[field], str):
                    data[field] = data[field].lower() in ('true', '1', 'yes', 'on')
                else:
                    data[field] = bool(data[field])

        # Convert integer fields
        int_fields = ['port', 'external_port', 'stream_bitrate', 'max_sources']
        for field in int_fields:
            if field in data and data[field] is not None:
                if data[field] == '' or data[field] == 'None':
                    data[field] = None
                else:
                    try:
                        data[field] = int(data[field])
                    except (TypeError, ValueError):
                        raise BadRequest(f"Invalid value for {field}: must be an integer")

        # Validate required fields
        if 'server' in data and not data['server']:
            raise BadRequest("Server hostname/IP is required")
        
        # SECURITY: Validate server hostname to prevent SSRF
        if 'server' in data and data['server']:
            if not re.match(r'^[a-zA-Z0-9\.\-]+$', data['server']):
                raise BadRequest("Invalid server hostname. Only alphanumeric characters, dots, and hyphens allowed.")
        
        if 'port' in data:
            port = data['port']
            if port is not None and (port < 1 or port > 65535):
                raise BadRequest("Port must be between 1 and 65535")
        
        if 'external_port' in data and data['external_port'] is not None:
            ext_port = data['external_port']
            if ext_port < 1 or ext_port > 65535:
                raise BadRequest("External port must be between 1 and 65535")
        
        if 'stream_bitrate' in data:
            bitrate = data['stream_bitrate']
            if bitrate is not None and (bitrate < 8 or bitrate > 320):
                raise BadRequest("Stream bitrate must be between 8 and 320 kbps")
        
        if 'max_sources' in data and data['max_sources'] is not None:
            max_src = data['max_sources']
            if max_src < 0:
                raise BadRequest("Max sources must be 0 (unlimited) or a positive integer")

        # Update settings
        settings = update_icecast_settings(data)
        invalidate_icecast_settings_cache()

        # Update Icecast XML config and restart service
        config_success, config_message = _update_icecast_config_file(
            settings.source_password,
            settings.admin_password,
            settings.admin_user or 'admin',
            settings.max_sources
        )

        logger.info(f"Icecast settings updated successfully. Config update: {config_message}")

        # Audit: record who changed Icecast settings. Passwords are stored as
        # field names only so credentials never enter the audit trail.
        _sensitive = ('password', 'secret', 'token')
        audit_details: Dict[str, Any] = {'changed_fields': sorted(data.keys())}
        for _k, _v in data.items():
            if not any(_s in _k.lower() for _s in _sensitive):
                audit_details[_k] = _v
        AuditLogger.log_config_change(
            resource_type='icecast_settings',
            resource_id=str(settings.id) if getattr(settings, 'id', None) is not None else None,
            details=audit_details,
        )

        if config_success:
            message = "Icecast settings updated and service restarted successfully."
        else:
            message = f"Icecast settings updated. Note: {config_message}"

        return jsonify({
            "success": True,
            "message": message,
            "config_updated": config_success,
            "settings": settings.to_dict(),
        })

    except BadRequest as exc:
        logger.warning(f"Bad request updating Icecast settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 400

    except Exception as exc:
        logger.error(f"Failed to update Icecast settings: {exc}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500


@icecast_bp.route('/api/icecast/test-connection', methods=['POST'])
@require_permission('system.configure')
def test_connection():
    """Test connection to Icecast server.
    
    SECURITY NOTE: This endpoint makes HTTP requests to user-specified servers.
    To prevent SSRF attacks:
    1. Validates port is in allowed range (1-65535)
    2. Validates server hostname format (alphanumeric, dots, hyphens only)
    3. Restricts to HTTP protocol only (no file://, gopher://, etc.)
    4. Uses short timeout (5s) to prevent hanging
    5. Disables redirects to prevent redirect-based SSRF
    6. Only accessible with system.configure permission
    """
    try:
        # Handle empty request body gracefully
        try:
            data = request.get_json(force=True, silent=True) or {}
        except Exception:
            data = {}
        
        # Get settings from request or use current settings
        settings = get_icecast_settings()
        server = data.get('server', settings.server)
        port = int(data.get('port', settings.port))
        admin_user = data.get('admin_user', settings.admin_user)
        admin_password = data.get('admin_password', settings.admin_password)
        
        # SECURITY: Validate server hostname to prevent SSRF attacks
        # Allow localhost, IP addresses, and domain names only
        # Reject URLs, paths, and suspicious characters
        if not re.match(r'^[a-zA-Z0-9\.\-]+$', server):
            return jsonify({
                "success": False,
                "error": f"Invalid server hostname. Only alphanumeric characters, dots, and hyphens allowed."
            }), 400
        
        # SECURITY: Validate port is in valid range
        if not (1 <= port <= 65535):
            return jsonify({
                "success": False,
                "error": f"Invalid port: {port}. Must be between 1 and 65535."
            }), 400

        # Try to connect to Icecast admin interface
        # SECURITY: Construct URL carefully to prevent injection
        test_url = f"http://{server}:{port}/admin/stats.xml"
        
        logger.info(f"Testing Icecast connection to {server}:{port}")
        
        try:
            # Test basic connectivity
            # SECURITY: Set allow_redirects=False to prevent redirect-based SSRF
            from app_core.http_defaults import get_default_user_agent
            response = requests.get(
                test_url,
                auth=(admin_user, admin_password) if admin_user and admin_password else None,
                timeout=5,
                allow_redirects=False,  # SSRF prevention
                headers={'User-Agent': get_default_user_agent()},
            )
            
            if response.status_code == 200:
                return jsonify({
                    "success": True,
                    "message": f"Successfully connected to Icecast server at {server}:{port}",
                    "details": {
                        "server": server,
                        "port": port,
                        "authenticated": bool(admin_user and admin_password),
                        "status_code": response.status_code
                    }
                })
            elif response.status_code == 401:
                return jsonify({
                    "success": False,
                    "error": "Authentication failed. Check admin username and password.",
                    "details": {
                        "server": server,
                        "port": port,
                        "status_code": response.status_code
                    }
                }), 401
            else:
                return jsonify({
                    "success": False,
                    "error": f"Icecast server returned status code {response.status_code}",
                    "details": {
                        "server": server,
                        "port": port,
                        "status_code": response.status_code
                    }
                }), 500
                
        except requests.exceptions.Timeout:
            return jsonify({
                "success": False,
                "error": f"Connection timeout. Server may be unreachable at {server}:{port}",
            }), 500
        except requests.exceptions.ConnectionError:
            return jsonify({
                "success": False,
                "error": f"Connection refused. Check if Icecast is running on {server}:{port}",
            }), 500
        except Exception as req_exc:
            return jsonify({
                "success": False,
                "error": f"Connection test failed: {str(req_exc)}",
            }), 500

    except Exception as exc:
        logger.error(f"Failed to test Icecast connection: {exc}", exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@icecast_bp.route('/api/icecast/regenerate-passwords', methods=['POST'])
@require_permission('system.configure')
def regenerate_passwords():
    """Regenerate Icecast passwords.
    
    Generates new secure passwords for source and admin authentication,
    updates the database, .env file, and Icecast server configuration file.
    """
    try:
        # Generate new secure passwords
        new_source_password = secrets.token_urlsafe(16)
        new_admin_password = secrets.token_urlsafe(16)
        
        # Update database
        settings = get_icecast_settings()
        settings.source_password = new_source_password
        # Ensure admin_user is set when updating admin_password
        # This fixes auth failures where admin_password is set but admin_user is None
        if not settings.admin_user:
            settings.admin_user = 'admin'
        settings.admin_password = new_admin_password
        db.session.commit()
        
        # Update .env file
        env_path = _get_env_file_path()
        
        # Read existing .env file
        existing_lines = []
        if env_path.exists():
            with open(env_path, 'r') as f:
                existing_lines = f.readlines()
        
        # Update password variables while preserving file structure
        new_lines = []
        processed_keys = set()
        
        for line in existing_lines:
            stripped = line.strip()
            
            # Preserve comments and empty lines
            if not stripped or stripped.startswith('#'):
                new_lines.append(line)
                continue
            
            # Update password and user variables
            if '=' in stripped:
                key = stripped.split('=', 1)[0].strip()
                if key == 'ICECAST_SOURCE_PASSWORD':
                    new_lines.append(f"{key}={new_source_password}\n")
                    processed_keys.add(key)
                elif key == 'ICECAST_ADMIN_USER':
                    new_lines.append(f"{key}={settings.admin_user}\n")
                    processed_keys.add(key)
                elif key == 'ICECAST_ADMIN_PASSWORD':
                    new_lines.append(f"{key}={new_admin_password}\n")
                    processed_keys.add(key)
                else:
                    new_lines.append(line)

        # Add new variables if they weren't in the file
        if 'ICECAST_SOURCE_PASSWORD' not in processed_keys:
            new_lines.append(f"ICECAST_SOURCE_PASSWORD={new_source_password}\n")
        if 'ICECAST_ADMIN_USER' not in processed_keys:
            new_lines.append(f"ICECAST_ADMIN_USER={settings.admin_user}\n")
        if 'ICECAST_ADMIN_PASSWORD' not in processed_keys:
            new_lines.append(f"ICECAST_ADMIN_PASSWORD={new_admin_password}\n")
        
        # Write back to file
        with open(env_path, 'w') as f:
            f.writelines(new_lines)
        
        # Update Icecast server configuration file
        config_success, config_message = _update_icecast_config_file(
            new_source_password,
            new_admin_password,
            settings.admin_user,
            settings.max_sources
        )
        
        # Invalidate cached settings
        invalidate_icecast_settings_cache()
        
        logger.info(f"Icecast passwords regenerated successfully. Config update: {config_message}")

        # Audit: record the credential rotation (never the new passwords).
        AuditLogger.log_config_change(
            resource_type='icecast_settings',
            resource_id=str(settings.id) if getattr(settings, 'id', None) is not None else None,
            details={'action': 'regenerated_passwords', 'config_updated': config_success},
        )

        # Build response message
        if config_success:
            message = "Passwords regenerated and Icecast server updated successfully."
        else:
            message = f"Passwords regenerated in database and .env file. Note: {config_message}"
        
        return jsonify({
            "success": True,
            "message": message,
            "config_updated": config_success,
            "config_message": config_message,
            "passwords": {
                "source_password": new_source_password,
                "admin_password": new_admin_password,
            }
        })
    
    except Exception as exc:
        logger.error(f"Failed to regenerate Icecast passwords: {exc}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500


@icecast_bp.route('/api/icecast/status', methods=['GET'])
@require_permission('system.configure')
def get_status():
    """Get current Icecast streaming status.
    
    SECURITY NOTE: Makes HTTP requests to configured Icecast server.
    SSRF prevention handled by hostname validation during settings save.
    """
    try:
        settings = get_icecast_settings()
        
        if not settings.enabled:
            return jsonify({
                "success": True,
                "enabled": False,
                "message": "Icecast streaming is disabled",
            })
        
        # SECURITY: Validate server hostname (defense in depth)
        server = settings.server or 'localhost'
        if not re.match(r'^[a-zA-Z0-9\.\-]+$', server):
            logger.error(f"Invalid Icecast server hostname in database: {server}")
            return jsonify({
                "success": False,
                "error": "Invalid server hostname in configuration"
            }), 500

        # Try to get stats from Icecast server
        stats_url = f"http://{server}:{settings.port}/admin/stats.xml"
        
        try:
            # SECURITY: Disable redirects to prevent redirect-based SSRF
            from app_core.http_defaults import get_default_user_agent
            response = requests.get(
                stats_url,
                auth=(settings.admin_user, settings.admin_password) if settings.admin_user and settings.admin_password else None,
                timeout=3,
                allow_redirects=False,  # SSRF prevention
                headers={'User-Agent': get_default_user_agent()},
            )

            if response.status_code == 200:
                # Parse stats from XML response
                content = response.text
                
                try:
                    # SECURITY: Basic validation before regex parsing
                    # Only parse XML-like responses from trusted Icecast server
                    content_stripped = content.strip()
                    if not (content_stripped.startswith('<?xml') or content_stripped.startswith('<icestats')):
                        logger.warning(f"Icecast stats response doesn't look like valid XML: {content_stripped[:100]}")
                        return jsonify({
                            "success": False,
                            "error": "Invalid XML response from Icecast server"
                        })
                    
                    # Use simple regex-based parsing for the two stats we need
                    # This is sufficient and more lightweight than xml.etree.ElementTree
                    # for extracting just 2 simple numeric values from well-formed Icecast XML
                    listeners_match = re.search(r'<listeners>(\d+)</listeners>', content)
                    total_listeners = int(listeners_match.group(1)) if listeners_match else 0
                    
                    sources_match = re.search(r'<sources>(\d+)</sources>', content)
                    total_sources = int(sources_match.group(1)) if sources_match else 0
                    
                    return jsonify({
                        "success": True,
                        "enabled": True,
                        "server_reachable": True,
                        "server": settings.server,
                        "port": settings.port,
                        "stats": {
                            "total_listeners": total_listeners,
                            "total_sources": total_sources,
                        }
                    })
                except (ValueError, AttributeError) as parse_err:
                    logger.warning(f"Failed to parse Icecast stats XML: {parse_err}")
                    return jsonify({
                        "success": True,
                        "enabled": True,
                        "server_reachable": True,
                        "server": settings.server,
                        "port": settings.port,
                        "stats": {
                            "total_listeners": 0,
                            "total_sources": 0,
                        },
                        "warning": "Unable to parse server statistics"
                    })
            else:
                return jsonify({
                    "success": True,
                    "enabled": True,
                    "server_reachable": False,
                    "error": f"Server returned status code {response.status_code}",
                })
                
        except requests.exceptions.RequestException as req_exc:
            return jsonify({
                "success": True,
                "enabled": True,
                "server_reachable": False,
                "error": f"Cannot reach Icecast server: {str(req_exc)}",
            })

    except Exception as exc:
        logger.error(f"Failed to get Icecast status: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


def register_icecast_routes(app, logger):
    """Register Icecast admin routes with the Flask app.
    
    Routes are registered with url_prefix='/admin', so Flask combines them:
    - Blueprint route '/icecast' becomes '/admin/icecast'
    - Blueprint route '/api/icecast/settings' becomes '/admin/api/icecast/settings'
    
    IMPORTANT: Do NOT add '/admin' prefix to route decorators above, as Flask
    will combine url_prefix with the route path, resulting in doubled paths
    like '/admin/admin/icecast' which will cause 404 errors.
    """
    app.register_blueprint(icecast_bp, url_prefix='/admin')
    logger.info("Icecast admin routes registered")


__all__ = ['icecast_bp', 'register_icecast_routes']
