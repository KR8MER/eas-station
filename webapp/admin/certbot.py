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

"""Certbot/SSL certificate management routes."""

import logging
import os
import re
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for, send_file
from werkzeug.exceptions import BadRequest

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.certbot_settings import (
    get_certbot_settings,
    update_certbot_settings,
)

logger = logging.getLogger(__name__)

# Certbot writable directories configuration
# In containerized/sandboxed environments, /var/log/letsencrypt, /etc/letsencrypt,
# and /var/lib/letsencrypt may be read-only. Use writable directories instead.
CERTBOT_BASE_DIR = Path(__file__).parent.parent.parent / 'certbot_data'
CERTBOT_CONFIG_DIR = CERTBOT_BASE_DIR / 'config'
CERTBOT_WORK_DIR = CERTBOT_BASE_DIR / 'work'
CERTBOT_LOGS_DIR = CERTBOT_BASE_DIR / 'logs'

# Nginx log files that need to exist for certbot nginx plugin
NGINX_LOG_FILES = [
    '/var/log/nginx/error.log',
    '/var/log/nginx/access.log',
    '/var/log/nginx/eas-station-error.log',
    '/var/log/nginx/eas-station-access.log'
]


def _ensure_certbot_directories():
    """Ensure certbot directories exist with proper permissions.

    Creates directories if they don't exist and sets permissions to allow
    both the web app user and root (via sudo) to write to them.
    Also removes stale lock files that can cause permission errors.
    
    Additionally ensures nginx log directory exists with proper permissions,
    which is required for certbot nginx plugin to run config tests.

    Uses sudo for all operations since certbot runs as root and creates
    root-owned files that the web app user cannot modify.
    """
    # Always use sudo to ensure we can fix root-owned directories/files
    try:
        # Create directories with sudo
        for directory in [CERTBOT_CONFIG_DIR, CERTBOT_WORK_DIR, CERTBOT_LOGS_DIR]:
            subprocess.run(
                ['sudo', 'mkdir', '-p', str(directory)],
                capture_output=True,
                timeout=5
            )

        # Fix permissions on the entire certbot_data directory tree
        subprocess.run(
            ['sudo', 'chmod', '-R', '777', str(CERTBOT_BASE_DIR)],
            capture_output=True,
            timeout=10
        )

        # Remove ALL .certbot.lock files (they're root-owned, need sudo)
        # Use find command which handles the case where files don't exist
        subprocess.run(
            ['sudo', 'find', str(CERTBOT_BASE_DIR), '-name', '.certbot.lock', '-delete'],
            capture_output=True,
            timeout=10
        )

        # Ensure nginx log directory exists with proper permissions
        # This is required for certbot nginx plugin which runs nginx config tests
        subprocess.run(
            ['sudo', 'mkdir', '-p', '/var/log/nginx'],
            capture_output=True,
            timeout=5
        )
        
        # Create log files if they don't exist
        for log_file in NGINX_LOG_FILES:
            subprocess.run(
                ['sudo', 'touch', log_file],
                capture_output=True,
                timeout=5
            )
        
        # Set proper permissions on nginx log directory
        subprocess.run(
            ['sudo', 'chmod', '-R', '755', '/var/log/nginx'],
            capture_output=True,
            timeout=5
        )
        
        # Set ownership to www-data (nginx user)
        subprocess.run(
            ['sudo', 'chown', '-R', 'www-data:www-data', '/var/log/nginx'],
            capture_output=True,
            timeout=5
        )

        logger.info(f"Certbot and nginx directories configured: {CERTBOT_BASE_DIR}, /var/log/nginx")
    except subprocess.TimeoutExpired:
        logger.warning("Timeout while configuring certbot directories")
    except Exception as e:
        logger.warning(f"Error configuring certbot directories: {e}")


# Ensure directories exist at module load time
_ensure_certbot_directories()

# Create Blueprint for certbot routes
certbot_bp = Blueprint('certbot', __name__)

# Precompile regex patterns for better performance
DOMAIN_PATTERN = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*$')
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


def _ensure_nginx_running():
    """Ensure nginx is running, attempt to start it if not.
    
    This is a safety function called in exception handlers to ensure
    nginx is not left in a stopped state after certificate operations.
    
    Returns:
        bool: True if nginx is running or successfully started, False otherwise
    """
    try:
        # Check if nginx is already running
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', 'nginx'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.stdout.strip() == 'active':
            return True
        
        # Try to start nginx
        logger.warning("Nginx not running, attempting to start...")
        start_result = subprocess.run(
            ['sudo', 'systemctl', 'start', 'nginx'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if start_result.returncode == 0:
            logger.info("Successfully started nginx")
            return True
        else:
            logger.error(f"Failed to start nginx: {start_result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Timeout while checking/starting nginx")
        return False
    except Exception as e:
        logger.error(f"Error ensuring nginx is running: {e}")
        return False


def _check_nginx_status():
    """Check if nginx is currently running.
    
    Returns:
        bool: True if nginx is active, False otherwise
    """
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', 'nginx'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout.strip() == 'active'
    except Exception as e:
        logger.warning(f"Could not check nginx status: {e}")
        return False


# Routes are relative to blueprint's url_prefix='/admin'
# e.g., route '/certbot' becomes '/admin/certbot'
@certbot_bp.route('/certbot')
@require_permission('system.configure')
def certbot_settings_page():
    """Display Certbot/SSL certificate settings configuration page."""
    try:
        settings = get_certbot_settings()

        return render_template(
            'admin/certbot.html',
            settings=settings,
        )
    except Exception as exc:
        logger.error(f"Failed to load Certbot settings: {exc}")
        flash(f"Error loading Certbot settings: {exc}", "error")
        return redirect(url_for('admin.index'))


@certbot_bp.route('/api/certbot/settings', methods=['GET'])
@require_permission('system.configure')
def get_settings():
    """Get current Certbot settings."""
    try:
        settings = get_certbot_settings()
        return jsonify({
            "success": True,
            "settings": settings.to_dict(),
        })
    except Exception as exc:
        logger.error(f"Failed to get Certbot settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/settings', methods=['PUT'])
@require_permission('system.configure')
def update_settings():
    """Update Certbot settings."""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        # Convert boolean fields
        bool_fields = ['enabled', 'staging', 'auto_renew_enabled']
        for field in bool_fields:
            if field in data:
                if isinstance(data[field], str):
                    data[field] = data[field].lower() in ('true', '1', 'yes', 'on')
                else:
                    data[field] = bool(data[field])

        # Convert integer fields
        int_fields = ['renew_days_before_expiry']
        for field in int_fields:
            if field in data and data[field] is not None:
                if data[field] == '' or data[field] == 'None':
                    data[field] = None
                else:
                    try:
                        data[field] = int(data[field])
                    except (TypeError, ValueError):
                        raise BadRequest(f"Invalid value for {field}: must be an integer")

        # Validate required fields when enabled
        if data.get('enabled', False):
            if 'domain_name' in data and not data['domain_name']:
                raise BadRequest("Domain name is required when Certbot is enabled")
            if 'email' in data and not data['email']:
                raise BadRequest("Email is required when Certbot is enabled")

        # SECURITY: Validate domain name to prevent command injection and SSRF
        if 'domain_name' in data and data['domain_name']:
            domain = data['domain_name'].strip()
            # Allow alphanumeric, dots, and hyphens only (standard domain format)
            # Prevent consecutive dots and dots at start/end
            if not DOMAIN_PATTERN.match(domain):
                raise BadRequest("Invalid domain name. Only alphanumeric characters, dots, and hyphens allowed. No consecutive dots or dots at start/end.")
            # Prevent localhost and internal IPs
            if domain.lower() in ['localhost', '127.0.0.1', '0.0.0.0']:
                raise BadRequest("Cannot use localhost or loopback addresses for SSL certificates")
            data['domain_name'] = domain

        # SECURITY: Validate email format
        if 'email' in data and data['email']:
            email = data['email'].strip()
            if not EMAIL_PATTERN.match(email):
                raise BadRequest("Invalid email address format")
            data['email'] = email

        # Validate renew_days_before_expiry
        if 'renew_days_before_expiry' in data and data['renew_days_before_expiry'] is not None:
            days = data['renew_days_before_expiry']
            if days < 1 or days > 90:
                raise BadRequest("Renewal days before expiry must be between 1 and 90")

        # Update settings
        settings = update_certbot_settings(data)

        logger.info(f"Certbot settings updated successfully")

        return jsonify({
            "success": True,
            "message": "Certbot settings updated successfully. Changes take effect on next certificate operation.",
            "settings": settings.to_dict(),
        })

    except BadRequest as exc:
        logger.warning(f"Bad request updating Certbot settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 400

    except Exception as exc:
        logger.error(f"Failed to update Certbot settings: {exc}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/certificate-status', methods=['GET'])
@require_permission('system.configure')
def get_certificate_status():
    """Get current SSL certificate status and information."""
    try:
        from app_core.ssl_utils import get_ssl_certificate_info, get_certificate_renewal_status

        cert_info = get_ssl_certificate_info()
        renewal_status = get_certificate_renewal_status()

        # Combine the information
        status = {
            "success": True,
            "certificate": cert_info,
            "renewal": renewal_status,
        }

        return jsonify(status)

    except Exception as exc:
        logger.error(f"Failed to get certificate status: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/renew-certificate', methods=['POST'])
@require_permission('system.configure')
def renew_certificate():
    """Check renewal timer status and provide renewal instructions.
    
    Certificate renewal is handled automatically by systemd timer (certbot.timer).
    This endpoint provides status and manual renewal instructions.
    """
    try:
        settings = get_certbot_settings()

        if not settings.enabled:
            return jsonify({
                "success": False,
                "error": "Certbot is not enabled in settings"
            }), 400

        if not settings.domain_name:
            return jsonify({
                "success": False,
                "error": "Domain name is not configured"
            }), 400

        # SECURITY: Validate domain name (defense in depth)
        domain = settings.domain_name.strip()
        if not DOMAIN_PATTERN.match(domain):
            logger.error(f"Invalid domain name in database: {domain}")
            return jsonify({
                "success": False,
                "error": "Invalid domain name in configuration"
            }), 500

        # Check if certbot is installed
        try:
            result = subprocess.run(
                ['which', 'certbot'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": "Certbot is not installed on this system"
                }), 500
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Failed to check certbot installation: {str(e)}"
            }), 500

        # Check certbot.timer status
        timer_info = {
            'enabled': False,
            'active': False,
            'next_run': 'Unknown'
        }
        
        try:
            # Check if timer is enabled
            enabled_result = subprocess.run(
                ['sudo', 'systemctl', 'is-enabled', 'certbot.timer'],
                capture_output=True,
                text=True,
                timeout=5
            )
            timer_info['enabled'] = (enabled_result.returncode == 0)
            
            # Check if timer is active
            active_result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', 'certbot.timer'],
                capture_output=True,
                text=True,
                timeout=5
            )
            timer_info['active'] = (active_result.stdout.strip() == 'active')
            
            # Get next run time
            if timer_info['active']:
                status_result = subprocess.run(
                    ['sudo', 'systemctl', 'status', 'certbot.timer'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in status_result.stdout.split('\n'):
                    if 'Trigger:' in line:
                        timer_info['next_run'] = line.split('Trigger:')[1].strip()
                        break
        except Exception as e:
            logger.warning(f"Could not check certbot.timer status: {e}")

        # Build response with instructions
        staging_flag = ' --staging' if settings.staging else ''
        dir_flags = (
            f" --config-dir {CERTBOT_CONFIG_DIR} "
            f"--work-dir {CERTBOT_WORK_DIR} "
            f"--logs-dir {CERTBOT_LOGS_DIR}"
        )
        instructions = {
            'timer_status': timer_info,
            'manual_commands': {
                'dry_run_test': f'certbot renew --dry-run{staging_flag}{dir_flags}',
                'force_renew': f'certbot renew --force-renewal{staging_flag}{dir_flags}',
                'obtain_new': f'certbot certonly --standalone -d {domain} --email {settings.email}{staging_flag}{dir_flags}'
            },
            'note': 'Certificate operations are executed from within the application container.'
        }

        if timer_info['active']:
            message = f"Certbot automatic renewal is active. Next run: {timer_info['next_run']}"
        elif timer_info['enabled']:
            message = "Certbot timer is enabled but not currently active. Start it with: systemctl start certbot.timer"
        else:
            message = "Certbot timer is not enabled. Enable it with: systemctl enable --now certbot.timer"

        return jsonify({
            "success": True,
            "message": message,
            "instructions": instructions
        })

    except Exception as exc:
        logger.error(f"Failed to check renewal status: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/obtain-certificate', methods=['POST'])
@require_permission('system.configure')
def obtain_certificate():
    """Provide instructions for obtaining a new SSL certificate.
    
    Certificate acquisition requires root privileges and must be done via command line.
    This endpoint validates settings and provides the correct command to run.
    """
    try:
        settings = get_certbot_settings()

        if not settings.enabled:
            return jsonify({
                "success": False,
                "error": "Certbot is not enabled in settings"
            }), 400

        if not settings.domain_name:
            return jsonify({
                "success": False,
                "error": "Domain name is not configured"
            }), 400

        if not settings.email:
            return jsonify({
                "success": False,
                "error": "Email address is not configured"
            }), 400

        # SECURITY: Validate domain name (defense in depth)
        domain = settings.domain_name.strip()
        if not DOMAIN_PATTERN.match(domain):
            logger.error(f"Invalid domain name in database: {domain}")
            return jsonify({
                "success": False,
                "error": "Invalid domain name in configuration"
            }), 500

        # SECURITY: Validate email
        email = settings.email.strip()
        if not EMAIL_PATTERN.match(email):
            logger.error(f"Invalid email in database: {email}")
            return jsonify({
                "success": False,
                "error": "Invalid email address in configuration"
            }), 500

        # Check if certbot is installed
        try:
            result = subprocess.run(
                ['which', 'certbot'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": "Certbot is not installed on this system"
                }), 500
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Failed to check certbot installation: {str(e)}"
            }), 500

        # Build command instructions
        staging_flag = ' --staging' if settings.staging else ''
        dir_flags = (
            f" --config-dir {CERTBOT_CONFIG_DIR} "
            f"--work-dir {CERTBOT_WORK_DIR} "
            f"--logs-dir {CERTBOT_LOGS_DIR}"
        )

        # Method 1: Standalone (requires stopping nginx)
        standalone_cmd = (
            f"systemctl stop nginx && "
            f"certbot certonly --standalone --non-interactive --agree-tos "
            f"--email {email} -d {domain}{staging_flag}{dir_flags} && "
            f"systemctl start nginx"
        )

        # Method 2: Nginx plugin (no downtime)
        nginx_cmd = (
            f"certbot --nginx --non-interactive --agree-tos "
            f"--email {email} -d {domain}{staging_flag}{dir_flags}"
        )

        # Method 3: Webroot (if nginx is serving files)
        webroot_cmd = (
            f"certbot certonly --webroot -w /var/www/certbot "
            f"--non-interactive --agree-tos --email {email} -d {domain}{staging_flag}{dir_flags}"
        )

        instructions = {
            'domain': domain,
            'email': email,
            'staging': settings.staging,
            'methods': {
                'nginx': {
                    'name': 'Nginx Plugin (Recommended - No Downtime)',
                    'command': nginx_cmd,
                    'description': 'Uses nginx plugin to obtain and configure certificate automatically without stopping the web server',
                    'requirements': ['Nginx must be running', 'Domain must be configured in nginx and accessible on port 80']
                },
                'standalone': {
                    'name': 'Standalone (Alternative)',
                    'command': standalone_cmd,
                    'description': 'Temporarily stops nginx, obtains certificate, then restarts nginx. Causes brief downtime.',
                    'requirements': ['Port 80 must be accessible from internet', 'Nginx can be temporarily stopped']
                },
                'webroot': {
                    'name': 'Webroot (Advanced)',
                    'command': webroot_cmd,
                    'description': 'Uses existing web server without stopping it, requires webroot directory configured',
                    'requirements': ['Nginx serving ACME challenges from /var/www/certbot']
                }
            },
            'post_install': [
                f'Certificate will be saved to: /etc/letsencrypt/live/{domain}/',
                'Update nginx configuration to use the new certificate',
                'Restart nginx: systemctl restart nginx',
                'Verify certificate status on this page'
            ],
            'note': 'Certificate acquisition is performed from within the application container.'
        }

        logger.info(f"Generated certificate acquisition instructions for domain: {domain}")

        return jsonify({
            "success": True,
            "message": f"Certificate acquisition instructions prepared for {domain}",
            "instructions": instructions
        })

    except Exception as exc:
        logger.error(f"Failed to generate certificate instructions: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/test-domain', methods=['POST'])
@require_permission('system.configure')
def test_domain():
    """Test domain DNS resolution and HTTP accessibility.
    
    SECURITY NOTE: This endpoint performs DNS lookups and HTTP checks.
    Domain validation prevents SSRF attacks.
    """
    try:
        # Handle both JSON and form data, and empty requests
        data = {}
        if request.is_json:
            data = request.get_json() or {}
        elif request.form:
            data = request.form.to_dict()
        
        settings = get_certbot_settings()
        domain = data.get('domain_name', settings.domain_name)

        if not domain:
            return jsonify({
                "success": False,
                "error": "Domain name is required"
            }), 400

        # SECURITY: Validate domain name to prevent SSRF
        domain = domain.strip()
        if not DOMAIN_PATTERN.match(domain):
            return jsonify({
                "success": False,
                "error": "Invalid domain name. Only alphanumeric characters, dots, and hyphens allowed. No consecutive dots or dots at start/end."
            }), 400

        # Prevent localhost and internal IPs
        if domain.lower() in ['localhost', '127.0.0.1', '0.0.0.0']:
            return jsonify({
                "success": False,
                "error": "Cannot use localhost or loopback addresses"
            }), 400

        results = {
            "domain": domain,
            "dns_resolution": {"success": False},
            "http_accessible": {"success": False},
        }

        # Test DNS resolution
        try:
            ip_address = socket.gethostbyname(domain)
            results["dns_resolution"] = {
                "success": True,
                "ip_address": ip_address,
                "message": f"Domain resolves to {ip_address}"
            }
        except socket.gaierror as e:
            results["dns_resolution"] = {
                "success": False,
                "error": f"DNS resolution failed: {str(e)}"
            }

        # Test HTTP accessibility (port 80 required for Let's Encrypt HTTP-01 challenge)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((domain, 80))
            sock.close()

            if result == 0:
                results["http_accessible"] = {
                    "success": True,
                    "message": f"Port 80 is accessible on {domain}"
                }
            else:
                results["http_accessible"] = {
                    "success": False,
                    "error": f"Port 80 is not accessible. Let's Encrypt requires port 80 for HTTP-01 challenge."
                }
        except Exception as e:
            results["http_accessible"] = {
                "success": False,
                "error": f"Failed to test port 80 accessibility: {str(e)}"
            }

        overall_success = results["dns_resolution"]["success"] and results["http_accessible"]["success"]

        return jsonify({
            "success": overall_success,
            "results": results,
            "message": "Domain tests completed" if overall_success else "Domain has issues that need to be resolved"
        })

    except Exception as exc:
        logger.error(f"Failed to test domain: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/obtain-certificate-execute', methods=['POST'])
@require_permission('system.configure')
def obtain_certificate_execute():
    """Execute certbot to obtain a new SSL certificate.
    
    This endpoint actually runs certbot with the configured settings.
    Requires proper system permissions to execute certbot.
    """
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        method = data.get('method', 'nginx')  # nginx (default), standalone, or webroot
        
        settings = get_certbot_settings()

        if not settings.enabled:
            return jsonify({
                "success": False,
                "error": "Certbot is not enabled in settings"
            }), 400

        if not settings.domain_name:
            return jsonify({
                "success": False,
                "error": "Domain name is not configured"
            }), 400

        if not settings.email:
            return jsonify({
                "success": False,
                "error": "Email address is not configured"
            }), 400

        # SECURITY: Validate domain name (defense in depth)
        domain = settings.domain_name.strip()
        if not DOMAIN_PATTERN.match(domain):
            logger.error(f"Invalid domain name in database: {domain}")
            return jsonify({
                "success": False,
                "error": "Invalid domain name in configuration"
            }), 500

        # SECURITY: Validate email
        email = settings.email.strip()
        if not EMAIL_PATTERN.match(email):
            logger.error(f"Invalid email in database: {email}")
            return jsonify({
                "success": False,
                "error": "Invalid email address in configuration"
            }), 500

        # SECURITY: Validate method
        if method not in ['standalone', 'nginx', 'webroot']:
            return jsonify({
                "success": False,
                "error": "Invalid method. Must be 'standalone', 'nginx', or 'webroot'"
            }), 400

        # Check if certbot is installed
        try:
            result = subprocess.run(
                ['which', 'certbot'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": "Certbot is not installed on this system"
                }), 500
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Failed to check certbot installation: {str(e)}"
            }), 500

        # Ensure certbot directories exist with proper permissions and clean up stale locks
        _ensure_certbot_directories()

        # Build certbot command based on method
        staging_flag = ['--staging'] if settings.staging else []

        if method == 'standalone':
            # Stop nginx, run certbot, start nginx
            try:
                # Stop nginx
                logger.info("Stopping nginx for standalone certificate acquisition")
                stop_result = subprocess.run(
                    ['sudo', 'systemctl', 'stop', 'nginx'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if stop_result.returncode != 0:
                    return jsonify({
                        "success": False,
                        "error": f"Failed to stop nginx: {stop_result.stderr}"
                    }), 500

                # Wait for port 80 to be released
                logger.info("Waiting for port 80 to be released...")
                time.sleep(2)
                
                # Verify nginx is actually stopped
                if _check_nginx_status():
                    logger.error("Nginx is still active after stop command")
                    return jsonify({
                        "success": False,
                        "error": "Nginx is still running after stop command. Please check system logs."
                    }), 500
                logger.info("Nginx confirmed stopped, port 80 should be available")

                # Run certbot with explicit port binding
                logger.info(f"Running certbot for domain: {domain}")
                certbot_cmd = [
                    'sudo', 'certbot', 'certonly', '--standalone',
                    '--non-interactive', '--agree-tos',
                    '--preferred-challenges', 'http',
                    '--http-01-port', '80',
                    '--email', email,
                    '-d', domain,
                    '--config-dir', str(CERTBOT_CONFIG_DIR),
                    '--work-dir', str(CERTBOT_WORK_DIR),
                    '--logs-dir', str(CERTBOT_LOGS_DIR)
                ] + staging_flag
                
                certbot_result = subprocess.run(
                    certbot_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                # Always restart nginx, even if certbot failed
                logger.info("Restarting nginx")
                start_result = subprocess.run(
                    ['sudo', 'systemctl', 'start', 'nginx'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if start_result.returncode != 0:
                    logger.error(f"Failed to restart nginx: {start_result.stderr}")
                
                if certbot_result.returncode != 0:
                    error_msg = certbot_result.stderr
                    
                    # Check for common permission errors and provide helpful messages
                    if "Permission denied" in error_msg or "Errno 13" in error_msg:
                        error_msg = (
                            "Permission error: Certbot requires root privileges. "
                            "This error may occur if: (1) sudo is not configured properly in /etc/sudoers.d/eas-station, "
                            "(2) port 80 is already in use by another process, or "
                            "(3) nginx log files have incorrect permissions. "
                            "Try using the 'nginx' plugin method instead, or ensure sudo is properly configured. "
                            "Original error: " + error_msg
                        )
                    elif "port 80" in error_msg.lower() or "address already in use" in error_msg.lower():
                        error_msg = (
                            "Port 80 is already in use. Another process may be using it, or nginx may not have stopped completely. "
                            "Try using the 'nginx' plugin method instead, which doesn't require stopping nginx. "
                            "Original error: " + error_msg
                        )
                    elif "nginx" in error_msg.lower() and "test failed" in error_msg.lower():
                        error_msg = (
                            "Nginx configuration test failed. This may be due to log file permission issues. "
                            "Ensure /var/log/nginx directory exists and nginx user can write to it. "
                            "Original error: " + error_msg
                        )
                    
                    return jsonify({
                        "success": False,
                        "error": f"Certbot failed: {error_msg}",
                        "output": certbot_result.stdout,
                        "suggestion": "Consider using the 'nginx' plugin method which doesn't require stopping nginx, or check system logs for more details."
                    }), 500
                
                logger.info(f"Successfully obtained certificate for {domain}")
                return jsonify({
                    "success": True,
                    "message": f"Successfully obtained SSL certificate for {domain}",
                    "output": certbot_result.stdout,
                    "note": "Certificate installed. You may need to restart nginx to use the new certificate."
                })
                
            except subprocess.TimeoutExpired:
                # Ensure nginx is restarted even on timeout
                _ensure_nginx_running()
                return jsonify({
                    "success": False,
                    "error": "Certbot operation timed out"
                }), 500
            except Exception as e:
                # Ensure nginx is restarted on any error
                _ensure_nginx_running()
                logger.error(f"Certbot execution failed: {e}")
                return jsonify({
                    "success": False,
                    "error": f"Failed to execute certbot: {str(e)}"
                }), 500
                
        elif method == 'nginx':
            # Use nginx plugin (no downtime)
            # First check if nginx is running
            if not _check_nginx_status():
                return jsonify({
                    "success": False,
                    "error": "Nginx must be running to use the nginx plugin. Start nginx or use the standalone method instead."
                }), 400
                
            certbot_cmd = [
                'sudo', 'certbot', '--nginx',
                '--non-interactive', '--agree-tos',
                '--email', email,
                '-d', domain,
                '--config-dir', str(CERTBOT_CONFIG_DIR),
                '--work-dir', str(CERTBOT_WORK_DIR),
                '--logs-dir', str(CERTBOT_LOGS_DIR)
            ] + staging_flag
            
            try:
                result = subprocess.run(
                    certbot_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                if result.returncode != 0:
                    error_msg = result.stderr
                    
                    # Check for common nginx plugin errors
                    if "Permission denied" in error_msg or "Errno 13" in error_msg:
                        error_msg = (
                            "Permission error: The nginx plugin requires proper permissions to test nginx configuration and write to log files. "
                            "Ensure /var/log/nginx directory exists with proper permissions (755) and is owned by www-data. "
                            "Original error: " + error_msg
                        )
                    elif "nginx" in error_msg.lower() and "test failed" in error_msg.lower():
                        error_msg = (
                            "Nginx configuration test failed. This is usually caused by log file permission issues. "
                            "The system has attempted to fix log permissions automatically. If this persists, check that "
                            "/var/log/nginx directory exists and nginx can write to it. "
                            "Original error: " + error_msg
                        )
                    
                    return jsonify({
                        "success": False,
                        "error": f"Certbot failed: {error_msg}",
                        "output": result.stdout
                    }), 500
                
                logger.info(f"Successfully obtained certificate for {domain} using nginx plugin")
                return jsonify({
                    "success": True,
                    "message": f"Successfully obtained and configured SSL certificate for {domain}",
                    "output": result.stdout
                })
                
            except subprocess.TimeoutExpired:
                return jsonify({
                    "success": False,
                    "error": "Certbot operation timed out"
                }), 500
            except Exception as e:
                logger.error(f"Certbot execution failed: {e}")
                return jsonify({
                    "success": False,
                    "error": f"Failed to execute certbot: {str(e)}"
                }), 500
                
        elif method == 'webroot':
            # Use webroot method
            certbot_cmd = [
                'sudo', 'certbot', 'certonly', '--webroot',
                '-w', '/var/www/certbot',
                '--non-interactive', '--agree-tos',
                '--email', email,
                '-d', domain,
                '--config-dir', str(CERTBOT_CONFIG_DIR),
                '--work-dir', str(CERTBOT_WORK_DIR),
                '--logs-dir', str(CERTBOT_LOGS_DIR)
            ] + staging_flag
            
            try:
                result = subprocess.run(
                    certbot_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                if result.returncode != 0:
                    return jsonify({
                        "success": False,
                        "error": f"Certbot failed: {result.stderr}",
                        "output": result.stdout
                    }), 500
                
                logger.info(f"Successfully obtained certificate for {domain} using webroot")
                return jsonify({
                    "success": True,
                    "message": f"Successfully obtained SSL certificate for {domain}",
                    "output": result.stdout,
                    "note": "Certificate installed. You may need to configure nginx to use the new certificate."
                })
                
            except subprocess.TimeoutExpired:
                return jsonify({
                    "success": False,
                    "error": "Certbot operation timed out"
                }), 500
            except Exception as e:
                logger.error(f"Certbot execution failed: {e}")
                return jsonify({
                    "success": False,
                    "error": f"Failed to execute certbot: {str(e)}"
                }), 500

    except Exception as exc:
        logger.error(f"Failed to obtain certificate: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/renew-certificate-execute', methods=['POST'])
@require_permission('system.configure')
def renew_certificate_execute():
    """Execute certbot renewal operation.
    
    This endpoint actually runs certbot renew with the configured settings.
    """
    try:
        data = request.get_json() if request.is_json else {}
        dry_run = data.get('dry_run', False)
        force = data.get('force', False)
        
        settings = get_certbot_settings()

        if not settings.enabled:
            return jsonify({
                "success": False,
                "error": "Certbot is not enabled in settings"
            }), 400

        # Check if certbot is installed
        try:
            result = subprocess.run(
                ['which', 'certbot'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": "Certbot is not installed on this system"
                }), 500
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Failed to check certbot installation: {str(e)}"
            }), 500

        # Build certbot renew command
        staging_flag = ['--staging'] if settings.staging else []
        certbot_cmd = [
            'sudo', 'certbot', 'renew',
            '--config-dir', str(CERTBOT_CONFIG_DIR),
            '--work-dir', str(CERTBOT_WORK_DIR),
            '--logs-dir', str(CERTBOT_LOGS_DIR)
        ]

        if dry_run:
            certbot_cmd.append('--dry-run')

        if force:
            certbot_cmd.append('--force-renewal')

        certbot_cmd.extend(staging_flag)
        
        try:
            logger.info(f"Running certbot renewal (dry_run={dry_run}, force={force})")
            result = subprocess.run(
                certbot_cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": f"Certbot renew failed: {result.stderr}",
                    "output": result.stdout
                }), 500
            
            action = "tested (dry run)" if dry_run else ("force renewed" if force else "renewed")
            logger.info(f"Successfully {action} certificate")
            
            return jsonify({
                "success": True,
                "message": f"Certificate successfully {action}",
                "output": result.stdout,
                "note": "Certificate renewal completed. Nginx will automatically use the new certificate on next reload." if not dry_run else "Dry run completed successfully. No changes were made."
            })
            
        except subprocess.TimeoutExpired:
            return jsonify({
                "success": False,
                "error": "Certbot renewal operation timed out"
            }), 500
        except Exception as e:
            logger.error(f"Certbot renewal failed: {e}")
            return jsonify({
                "success": False,
                "error": f"Failed to execute certbot renewal: {str(e)}"
            }), 500

    except Exception as exc:
        logger.error(f"Failed to renew certificate: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/enable-auto-renewal', methods=['POST'])
@require_permission('system.configure')
def enable_auto_renewal():
    """Enable or disable the certbot.timer for automatic certificate renewal."""
    try:
        data = request.get_json() if request.is_json else {}
        enable = data.get('enable', True)
        
        if enable:
            # Enable and start the timer
            try:
                result = subprocess.run(
                    ['sudo', 'systemctl', 'enable', '--now', 'certbot.timer'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode != 0:
                    return jsonify({
                        "success": False,
                        "error": f"Failed to enable certbot timer: {result.stderr}"
                    }), 500
                
                logger.info("Enabled and started certbot.timer for automatic renewal")
                return jsonify({
                    "success": True,
                    "message": "Automatic certificate renewal enabled and started"
                })
                
            except subprocess.TimeoutExpired:
                return jsonify({
                    "success": False,
                    "error": "Operation timed out"
                }), 500
            except Exception as e:
                logger.error(f"Failed to enable certbot timer: {e}")
                return jsonify({
                    "success": False,
                    "error": f"Failed to enable automatic renewal: {str(e)}"
                }), 500
        else:
            # Stop and disable the timer
            try:
                result = subprocess.run(
                    ['sudo', 'systemctl', 'disable', '--now', 'certbot.timer'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode != 0:
                    return jsonify({
                        "success": False,
                        "error": f"Failed to disable certbot timer: {result.stderr}"
                    }), 500
                
                logger.info("Disabled and stopped certbot.timer")
                return jsonify({
                    "success": True,
                    "message": "Automatic certificate renewal disabled"
                })
                
            except subprocess.TimeoutExpired:
                return jsonify({
                    "success": False,
                    "error": "Operation timed out"
                }), 500
            except Exception as e:
                logger.error(f"Failed to disable certbot timer: {e}")
                return jsonify({
                    "success": False,
                    "error": f"Failed to disable automatic renewal: {str(e)}"
                }), 500

    except Exception as exc:
        logger.error(f"Failed to manage certbot timer: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/download-certificate', methods=['GET'])
@require_permission('system.configure')
def download_certificate():
    """Download the current SSL certificate.
    
    SECURITY NOTE: This endpoint allows downloading certificates.
    Access is logged and restricted to system.configure permission.
    Private keys require separate endpoint with additional warnings.
    """
    try:
        cert_type = request.args.get('type', 'fullchain')

        # SECURITY: Validate cert_type to prevent path traversal
        if cert_type not in ['fullchain', 'cert', 'chain']:
            return jsonify({
                "success": False,
                "error": "Invalid certificate type. Must be 'fullchain', 'cert', or 'chain'"
            }), 400

        # Find certificate directory (use custom config directory)
        letsencrypt_dir = CERTBOT_CONFIG_DIR / 'live'
        if not letsencrypt_dir.exists():
            return jsonify({
                "success": False,
                "error": "Let's Encrypt certificate directory not found"
            }), 404

        # Find first domain directory
        domains = [d.name for d in letsencrypt_dir.iterdir()
                   if d.is_dir() and d.name != 'README']

        if not domains:
            return jsonify({
                "success": False,
                "error": "No SSL certificates found"
            }), 404

        domain = domains[0]
        cert_file = f"{cert_type}.pem"
        cert_path = letsencrypt_dir / domain / cert_file

        if not cert_path.exists():
            return jsonify({
                "success": False,
                "error": f"Certificate file not found: {cert_file}"
            }), 404

        logger.info(f"Certificate download requested: {cert_type}.pem for domain {domain}")

        return send_file(
            str(cert_path),
            as_attachment=True,
            download_name=f"{domain}-{cert_file}",
            mimetype='application/x-pem-file'
        )

    except Exception as exc:
        logger.error(f"Failed to download certificate: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@certbot_bp.route('/api/certbot/logs', methods=['GET'])
@require_permission('system.configure')
def get_certbot_logs():
    """Get certbot log file contents.

    Returns the last N lines of the certbot log file for debugging.
    """
    try:
        lines = request.args.get('lines', 100, type=int)
        # Limit to prevent abuse
        lines = min(lines, 1000)

        log_file = CERTBOT_LOGS_DIR / 'letsencrypt.log'

        if not log_file.exists():
            return jsonify({
                "success": True,
                "log": "",
                "message": "No log file found. Logs will appear after running certbot."
            })

        # Read the log file
        try:
            with open(log_file, 'r') as f:
                all_lines = f.readlines()
                # Get last N lines
                log_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                log_content = ''.join(log_lines)
        except PermissionError:
            # Try with sudo cat
            result = subprocess.run(
                ['sudo', 'cat', str(log_file)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                all_lines = result.stdout.splitlines(keepends=True)
                log_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                log_content = ''.join(log_lines)
            else:
                return jsonify({
                    "success": False,
                    "error": f"Cannot read log file: {result.stderr}"
                }), 500

        return jsonify({
            "success": True,
            "log": log_content,
            "log_file": str(log_file),
            "lines_returned": len(log_content.splitlines())
        })

    except Exception as exc:
        logger.error(f"Failed to read certbot logs: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


def register_certbot_routes(app, logger):
    """Register Certbot admin routes with the Flask app.
    
    Routes are registered with url_prefix='/admin', so Flask combines them:
    - Blueprint route '/certbot' becomes '/admin/certbot'
    - Blueprint route '/api/certbot/settings' becomes '/admin/api/certbot/settings'
    
    IMPORTANT: Do NOT add '/admin' prefix to route decorators above, as Flask
    will combine url_prefix with the route path, resulting in doubled paths
    like '/admin/admin/certbot' which will cause 404 errors.
    """
    app.register_blueprint(certbot_bp, url_prefix='/admin')
    logger.info("Certbot admin routes registered")


__all__ = ['certbot_bp', 'register_certbot_routes']
