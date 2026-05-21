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

from app_core.auth.decorators import require_auth
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


# Removed _ensure_nginx_log_permissions() function (removed in this version)
# The nginx plugin has fundamental permission issues that cannot be reliably solved
# by changing file permissions. The nginx plugin runs 'nginx -t' which may execute
# in a different security context (AppArmor, SELinux, etc.) that prevents write access
# to /var/log/nginx/error.log even with permissive file permissions.
# Use standalone or webroot modes instead.


def _ensure_webroot_directory():
    """Ensure webroot directory exists with proper permissions for certbot.
    
    The webroot directory must be writable by root (certbot runs as root via sudo)
    and readable by nginx (www-data) to serve the ACME challenge files.
    
    Certbot creates challenge files as root, then nginx serves them to Let's Encrypt.
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        webroot_path = '/var/www/certbot'
        challenge_path = '/var/www/certbot/.well-known/acme-challenge'
        
        # Create directories with sudo (certbot runs as root)
        subprocess.run(
            ['sudo', 'mkdir', '-p', challenge_path],
            capture_output=True,
            timeout=5
        )
        
        # Set ownership to root:root (certbot needs to write as root)
        subprocess.run(
            ['sudo', 'chown', '-R', 'root:root', webroot_path],
            capture_output=True,
            timeout=5
        )
        
        # Set permissions to 755 (owner=rwx, group=rx, other=rx)
        # This allows root to write, and www-data (nginx) to read
        subprocess.run(
            ['sudo', 'chmod', '-R', '755', webroot_path],
            capture_output=True,
            timeout=5
        )
        
        logger.info(f"Webroot directory configured: {webroot_path}")
        return True
        
    except subprocess.TimeoutExpired:
        logger.warning("Timeout while configuring webroot directory")
        return False
    except Exception as e:
        logger.warning(f"Error configuring webroot directory: {e}")
        return False


def _ensure_certbot_directories():
    """Ensure certbot directories exist with proper permissions.

    Creates directories if they don't exist and sets permissions to allow
    both the web app user and root (via sudo) to write to them.
    Also removes stale lock files that can cause permission errors.

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

        logger.info(f"Certbot directories configured: {CERTBOT_BASE_DIR}")
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


def _is_existing_cert_staging(domain: str) -> bool:
    """Check if an existing certificate for the domain is from the staging server.

    Checks both the renewal config (for acme-staging server URL) and the cert
    issuer (for STAGING / Fake LE indicators).

    Args:
        domain: Domain name to check

    Returns:
        True if a staging certificate exists for this domain
    """
    # Check renewal config files for staging ACME server URL
    renewal_dir = CERTBOT_CONFIG_DIR / 'renewal'
    if renewal_dir.exists():
        for conf_file in renewal_dir.iterdir():
            if not conf_file.name.endswith('.conf'):
                continue
            # Match domain.conf or domain-0001.conf
            base = conf_file.stem
            if base != domain and not (base.startswith(f"{domain}-") and base[len(domain)+1:].isdigit()):
                continue
            try:
                content = conf_file.read_text()
                if 'acme-staging' in content:
                    return True
            except Exception:
                continue

    # Check certificate issuer as a fallback
    live_dir = CERTBOT_CONFIG_DIR / 'live'
    if live_dir.exists():
        for entry in live_dir.iterdir():
            if not entry.is_dir() or entry.name == 'README':
                continue
            if entry.name != domain and not (entry.name.startswith(f"{domain}-") and entry.name[len(domain)+1:].isdigit()):
                continue
            cert_path = entry / 'fullchain.pem'
            if cert_path.exists():
                try:
                    result = subprocess.run(
                        ['openssl', 'x509', '-in', str(cert_path), '-noout', '-issuer'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        issuer = result.stdout
                        if '(STAGING)' in issuer or 'Fake LE' in issuer or 'Fake Let\'s Encrypt' in issuer:
                            return True
                except Exception:
                    continue

    return False


def _delete_staging_certs(domain: str) -> Dict[str, Any]:
    """Delete all staging certificates for a domain so a production cert can be obtained.

    Uses 'certbot delete' for each matching cert name, which cleanly removes
    the certificate, renewal config, and associated files.

    Args:
        domain: Domain name whose staging certs should be deleted

    Returns:
        Dict with 'success', 'deleted' (list of deleted cert names), and optionally 'error'
    """
    deleted = []
    errors = []

    # Find all cert names that match this domain
    renewal_dir = CERTBOT_CONFIG_DIR / 'renewal'
    if not renewal_dir.exists():
        return {"success": True, "deleted": []}

    cert_names = []
    for conf_file in renewal_dir.iterdir():
        if not conf_file.name.endswith('.conf'):
            continue
        base = conf_file.stem
        if base == domain or (base.startswith(f"{domain}-") and base[len(domain)+1:].isdigit()):
            # Only delete if it's actually a staging cert
            try:
                content = conf_file.read_text()
                if 'acme-staging' in content:
                    cert_names.append(base)
            except Exception:
                continue

    for cert_name in cert_names:
        try:
            result = subprocess.run(
                [
                    'sudo', 'certbot', 'delete',
                    '--cert-name', cert_name,
                    '--non-interactive',
                    '--config-dir', str(CERTBOT_CONFIG_DIR),
                    '--work-dir', str(CERTBOT_WORK_DIR),
                    '--logs-dir', str(CERTBOT_LOGS_DIR),
                ],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                deleted.append(cert_name)
                logger.info(f"Deleted staging certificate: {cert_name}")
            else:
                errors.append(f"{cert_name}: {result.stderr.strip()}")
                logger.error(f"Failed to delete staging cert {cert_name}: {result.stderr}")
        except Exception as e:
            errors.append(f"{cert_name}: {str(e)}")

    return {
        "success": len(errors) == 0,
        "deleted": deleted,
        "error": "; ".join(errors) if errors else None,
    }


def _install_certificate_internal(domain: str) -> Dict[str, Any]:
    """Internal helper to install a certificate after it's been obtained.

    Simplified approach:
    1. Find the most recent certificate directory for the domain
    2. Verify certificate files exist
    3. Write an nginx SSL snippet pointing directly to the cert files
    4. Reload nginx

    Args:
        domain: Domain name for the certificate

    Returns:
        Dict with 'success' boolean and either 'message' or 'error' string
    """
    try:
        # Find certificate directory - certbot may create domain-0001, domain-0002, etc.
        # when obtaining multiple certs for the same domain (e.g., switching staging to production)
        live_dir = CERTBOT_CONFIG_DIR / 'live'
        
        if not live_dir.exists():
            return {
                "success": False,
                "error": f"Certificate directory not found: {live_dir}"
            }
        
        # Find all directories matching the domain (including numbered variants)
        matching_dirs = []
        try:
            for entry in live_dir.iterdir():
                if entry.is_dir() and entry.name != 'README':
                    # Match exact domain or domain-#### pattern (certbot numbered variants)
                    # Example: example.com or example.com-0001
                    # Do NOT match: example.com.test or example.com-backup
                    if entry.name == domain:
                        matching_dirs.append(entry)
                    elif entry.name.startswith(f"{domain}-"):
                        # Verify the suffix is a number (certbot style)
                        suffix = entry.name[len(domain)+1:]  # Everything after "domain-"
                        if suffix.isdigit():
                            matching_dirs.append(entry)
        except Exception as e:
            return {
                "success": False,
                "error": f"Error reading certificate directory: {str(e)}"
            }
        
        if not matching_dirs:
            return {
                "success": False,
                "error": f"Certificate not found for domain {domain}. Run 'Obtain Certificate' first."
            }
        
        # Use the most recently modified directory (latest certificate)
        if len(matching_dirs) == 1:
            # Optimization: Skip stat() calls if only one directory
            cert_dir = matching_dirs[0]
        else:
            # Cache stat results for performance
            dirs_with_mtime = [(d, d.stat().st_mtime) for d in matching_dirs]
            cert_dir = max(dirs_with_mtime, key=lambda x: x[1])[0]
        logger.info(f"Using certificate directory: {cert_dir}")
        
        fullchain_path = cert_dir / 'fullchain.pem'
        privkey_path = cert_dir / 'privkey.pem'

        # Verify certificate files exist
        if not fullchain_path.exists():
            return {
                "success": False,
                "error": f"Certificate file missing: fullchain.pem"
            }
        if not privkey_path.exists():
            return {
                "success": False,
                "error": f"Certificate file missing: privkey.pem"
            }

        # Write nginx SSL snippet that points directly to our cert files
        # This avoids all the symlink and sed complexity
        ssl_snippet_path = Path('/etc/nginx/snippets/ssl-letsencrypt.conf')
        ssl_snippet_content = f"""# Let's Encrypt SSL certificate for {domain}
# Auto-generated by EAS Station certbot manager
ssl_certificate {fullchain_path};
ssl_certificate_key {privkey_path};
"""

        # Ensure the snippets directory exists. On distros without snippets/
        # (or freshly minimal nginx installs) the subsequent `sudo tee` would
        # fail with "No such file or directory", which surfaces in the UI as
        # an inability to override the previous certificate. The sudoers
        # entry for `mkdir -p /etc/nginx/snippets` is provided for exactly
        # this reason.
        mkdir_result = subprocess.run(
            ['sudo', 'mkdir', '-p', str(ssl_snippet_path.parent)],
            capture_output=True,
            text=True,
            timeout=5
        )
        if mkdir_result.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to create nginx snippets directory: {mkdir_result.stderr.strip()}"
            }

        # Write the snippet file
        write_result = subprocess.run(
            ['sudo', 'tee', str(ssl_snippet_path)],
            input=ssl_snippet_content,
            capture_output=True,
            text=True,
            timeout=5
        )

        if write_result.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to write SSL snippet: {write_result.stderr.strip()}"
            }

        logger.info(f"Created SSL snippet at {ssl_snippet_path}")

        # Update the main nginx config to include our snippet instead of self-signed certs
        nginx_config_path = Path('/etc/nginx/sites-available/eas-station')

        # First, check if we need to update the config (only if it's using self-signed)
        # Use a simple sed to comment out self-signed and add our snippet include

        # Comment out any existing ssl_certificate lines and add our include
        # This is idempotent - running it multiple times is safe
        sed_commands = [
            # Comment out self-signed cert lines if present
            's|^\\(\\s*\\)ssl_certificate /etc/ssl/|\\1# ssl_certificate /etc/ssl/|g',
            's|^\\(\\s*\\)ssl_certificate_key /etc/ssl/|\\1# ssl_certificate_key /etc/ssl/|g',
            # Comment out any existing direct letsencrypt certificate path lines
            # Use \\.pem to match only direct certificate file paths, not include statements
            's|^\\(\\s*\\)ssl_certificate.*/letsencrypt/.*\\.pem|\\1# ssl_certificate_DISABLED /letsencrypt/|g',
            's|^\\(\\s*\\)ssl_certificate_key.*/letsencrypt/.*\\.pem|\\1# ssl_certificate_key_DISABLED /letsencrypt/|g',
        ]

        for sed_cmd in sed_commands:
            subprocess.run(
                ['sudo', 'sed', '-i', sed_cmd, str(nginx_config_path)],
                capture_output=True,
                text=True,
                timeout=5
            )

        # Check if the include line already exists. Use sudo for the read so
        # we don't silently treat a "permission denied" as "include missing"
        # and end up appending a duplicate include line on every install.
        grep_result = subprocess.run(
            ['sudo', 'grep', '-q', 'ssl-letsencrypt.conf', str(nginx_config_path)],
            capture_output=True,
            timeout=5
        )

        if grep_result.returncode != 0:
            # Include line doesn't exist, add it after the ssl_protocols line
            subprocess.run(
                ['sudo', 'sed', '-i',
                 '/ssl_protocols/a\\    include snippets/ssl-letsencrypt.conf;',
                 str(nginx_config_path)],
                capture_output=True,
                text=True,
                timeout=5
            )
            logger.info("Added SSL snippet include to nginx config")

        logger.info(f"Updated nginx configuration to use Let's Encrypt certificate for {domain}")

        # Validate nginx config before touching the running service. `systemctl
        # reload nginx` reports a generic non-zero exit on config errors, but
        # `nginx -t` returns the actual problem (e.g. missing snippet file,
        # syntax error from a stale ssl_certificate line) — surface that to
        # the user so the "issue overriding the old one" is debuggable.
        test_result = subprocess.run(
            ['sudo', 'nginx', '-t'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if test_result.returncode != 0:
            nginx_diag = (test_result.stderr or test_result.stdout or '').strip()
            logger.error(f"nginx -t rejected the updated config: {nginx_diag}")
            return {
                "success": False,
                "error": f"nginx configuration test failed: {nginx_diag}"
            }

        # Check if nginx is running before attempting reload
        nginx_running = _check_nginx_status()

        if nginx_running:
            # Nginx is running - use reload (graceful, no downtime)
            logger.info("Reloading nginx to apply certificate changes")
            reload_result = subprocess.run(
                ['sudo', 'systemctl', 'reload', 'nginx'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if reload_result.returncode != 0:
                # Reload failed, try restart as fallback
                logger.warning(f"Nginx reload failed: {reload_result.stderr}, attempting restart")
                restart_result = subprocess.run(
                    ['sudo', 'systemctl', 'restart', 'nginx'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if restart_result.returncode != 0:
                    return {
                        "success": False,
                        "error": f"Failed to reload/restart nginx: {restart_result.stderr.strip()}"
                    }
                logger.info("Nginx restarted successfully with new certificate")
            else:
                logger.info("Nginx reloaded successfully with new certificate")
        else:
            # Nginx is not running - start it
            logger.warning("Nginx not running, starting it with new certificate configuration")
            start_result = subprocess.run(
                ['sudo', 'systemctl', 'start', 'nginx'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if start_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to start nginx: {start_result.stderr}"
                }
            logger.info("Nginx started successfully with new certificate")
        
        return {
            "success": True,
            "message": f"Certificate installed successfully for {domain}",
            "details": {
                "domain": domain,
                "cert_path": str(cert_dir),
                "ssl_snippet": str(ssl_snippet_path),
                "nginx_config": str(nginx_config_path)
            }
        }

    except subprocess.TimeoutExpired as e:
        logger.error(f"Timeout during certificate installation: {e.cmd}")
        return {
            "success": False,
            "error": f"Timeout during certificate installation (command: {' '.join(str(c) for c in e.cmd) if hasattr(e, 'cmd') else 'unknown'})"
        }
    except Exception as e:
        logger.error(f"Failed to install certificate: {e}")
        return {
            "success": False,
            "error": f"Failed to install certificate: {str(e)}"
        }


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
        return redirect(url_for('dashboard.admin'))


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


@certbot_bp.route('/api/certbot/status', methods=['GET'])
@require_permission('system.configure')
def get_status():
    """Alias for certificate-status endpoint for frontend compatibility."""
    return get_certificate_status()


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
        # Note: --staging is only shown for the obtain command (where it
        # actually selects the ACME server).  For 'certbot renew', the server
        # is read from the stored renewal config, so the flag is meaningless.
        staging_flag = ' --staging' if settings.staging else ''
        dir_flags = (
            f" --config-dir {CERTBOT_CONFIG_DIR} "
            f"--work-dir {CERTBOT_WORK_DIR} "
            f"--logs-dir {CERTBOT_LOGS_DIR}"
        )
        instructions = {
            'timer_status': timer_info,
            'manual_commands': {
                'dry_run_test': f'certbot renew --dry-run{dir_flags}',
                'force_renew': f'certbot renew --force-renewal{dir_flags}',
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
                'standalone': {
                    'name': 'Standalone (Recommended - Most Reliable)',
                    'command': standalone_cmd,
                    'description': 'Temporarily stops nginx, obtains certificate, then restarts nginx. Causes brief downtime (~10 seconds).',
                    'requirements': ['Port 80 must be accessible from internet', 'Nginx can be temporarily stopped']
                },
                'webroot': {
                    'name': 'Webroot (No Downtime Alternative)',
                    'command': webroot_cmd,
                    'description': 'Uses existing web server without stopping it. Requires webroot directory to be configured.',
                    'requirements': ['Nginx serving ACME challenges from /var/www/certbot', 'Webroot directory exists and is writable']
                },
                'nginx': {
                    'name': 'Nginx Plugin (Not Recommended - Permission Issues)',
                    'command': nginx_cmd,
                    'description': 'Uses nginx plugin but often fails due to permission issues when testing nginx configuration. Only use if standalone and webroot fail.',
                    'requirements': ['Nginx must be running', 'Domain must be configured in nginx', 'Nginx must have write access to /var/log/nginx/error.log']
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
        method = data.get('method', 'standalone')  # standalone (default - most reliable), webroot, or nginx
        
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

        # If switching from staging to production, delete existing staging certs first.
        # Without this, certbot sees the existing (staging) cert is not due for renewal
        # and silently exits with code 0, leaving the staging cert in place.
        if not settings.staging and _is_existing_cert_staging(domain):
            logger.info(f"Production mode selected but staging cert exists for {domain}. "
                        "Deleting staging cert(s) before obtaining production cert.")
            delete_result = _delete_staging_certs(domain)
            if delete_result['deleted']:
                logger.info(f"Deleted staging certs: {delete_result['deleted']}")
            if delete_result.get('error'):
                logger.warning(f"Some staging certs could not be deleted: {delete_result['error']}")

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
                logger.info(f"Running certbot standalone for domain: {domain}")
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
                
                logger.info(f"Certbot command: {' '.join(certbot_cmd)}")
                
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
                    
                    # Log the full error for debugging
                    logger.error(f"Certbot standalone failed with return code {certbot_result.returncode}")
                    logger.error(f"Certbot stderr: {error_msg}")
                    logger.error(f"Certbot stdout: {certbot_result.stdout}")
                    
                    # Check for common permission errors and provide helpful messages
                    if "Permission denied" in error_msg or "Errno 13" in error_msg:
                        error_msg = (
                            "Permission error: Certbot standalone mode requires root privileges to bind to port 80. "
                            "Try using the 'nginx' plugin method instead, which doesn't require stopping nginx or "
                            "binding to privileged ports. Original error: " + error_msg
                        )
                    elif "port 80" in error_msg.lower() or "address already in use" in error_msg.lower():
                        error_msg = (
                            "Port 80 is already in use. Another process may be using it. "
                            "Try using the 'nginx' plugin method instead. Original error: " + error_msg
                        )
                    
                    return jsonify({
                        "success": False,
                        "error": f"Certbot failed: {error_msg}",
                        "output": certbot_result.stdout,
                        "suggestion": "Consider using the 'nginx' plugin method which doesn't require stopping nginx or binding to port 80."
                    }), 500
                
                logger.info(f"Successfully obtained certificate for {domain}")
                
                # Automatically install the certificate
                logger.info(f"Installing certificate for {domain}")
                install_result = _install_certificate_internal(domain)
                
                if install_result["success"]:
                    return jsonify({
                        "success": True,
                        "message": f"Successfully obtained and installed SSL certificate for {domain}",
                        "output": certbot_result.stdout,
                        "installation": install_result.get("details", {}),
                        "note": "Certificate installed and nginx reloaded. Your site should now be using the Let's Encrypt certificate."
                    })
                else:
                    # Certificate obtained but installation failed
                    return jsonify({
                        "success": True,
                        "message": f"Successfully obtained SSL certificate for {domain}, but installation failed",
                        "output": certbot_result.stdout,
                        "installation_error": install_result.get("error", "Unknown installation error"),
                        "note": "Certificate obtained successfully but automatic installation failed. You may need to install it manually using the 'Install Certificate' button."
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
            # Use nginx plugin (not recommended due to permission issues)
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
                logger.info(f"Running certbot with nginx plugin for domain: {domain}")
                # Note: User has been warned about permission issues in UI
                # Only log once per execution attempt to avoid log noise
                if result := subprocess.run(
                    certbot_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120
                ):
                    pass  # Process result below
                
                if result.returncode != 0:
                    original_error = result.stderr
                    logger.error(f"Certbot nginx plugin failed: {original_error}")
                    logger.error(f"Certbot stdout: {result.stdout}")
                    
                    # Check for permission errors and provide helpful guidance
                    error_msg = original_error
                    if "Permission denied" in original_error or "/var/log/nginx/error.log" in original_error:
                        error_msg = (
                            "Nginx plugin failed due to permission issues with /var/log/nginx/error.log. "
                            "This is a known limitation of the nginx plugin when running in certain environments. "
                            "Please use the 'standalone' or 'webroot' method instead. "
                            f"Original error: {original_error}"
                        )
                    
                    return jsonify({
                        "success": False,
                        "error": error_msg,
                        "output": result.stdout,
                        "suggestion": "Use the 'standalone' method (most reliable) or 'webroot' method (no downtime) instead."
                    }), 500
                
                logger.info(f"Successfully obtained certificate for {domain} using nginx plugin")
                return jsonify({
                    "success": True,
                    "message": f"Successfully obtained and configured SSL certificate for {domain}",
                    "output": result.stdout
                })
                
            except subprocess.TimeoutExpired:
                logger.error("Certbot nginx plugin operation timed out")
                return jsonify({
                    "success": False,
                    "error": "Certbot operation timed out"
                }), 500
            except Exception as e:
                logger.error(f"Certbot nginx plugin execution failed: {e}")
                return jsonify({
                    "success": False,
                    "error": f"Failed to execute certbot: {str(e)}"
                }), 500
                
        elif method == 'webroot':
            # Use webroot method
            # Ensure webroot directory exists with proper permissions
            logger.info("Ensuring webroot directory exists and has proper permissions...")
            if not _ensure_webroot_directory():
                return jsonify({
                    "success": False,
                    "error": "Failed to configure webroot directory. Check logs for details."
                }), 500
            
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
                logger.info(f"Running certbot webroot method for domain: {domain}")
                result = subprocess.run(
                    certbot_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                if result.returncode != 0:
                    original_error = result.stderr
                    logger.error(f"Certbot webroot failed: {original_error}")
                    logger.error(f"Certbot stdout: {result.stdout}")
                    
                    # Check for common permission/path errors and provide helpful guidance
                    error_msg = original_error
                    if "Permission denied" in original_error or "Errno 13" in original_error:
                        error_msg = (
                            "Permission error accessing webroot directory. "
                            "The webroot directory must be accessible by both root (certbot) and www-data (nginx). "
                            f"Original error: {original_error}"
                        )
                    elif "No such file or directory" in original_error or "Errno 2" in original_error:
                        error_msg = (
                            "Webroot directory not found or inaccessible. "
                            "Ensure /var/www/certbot exists and nginx is configured to serve .well-known/acme-challenge. "
                            f"Original error: {original_error}"
                        )
                    
                    return jsonify({
                        "success": False,
                        "error": f"Certbot failed: {error_msg}",
                        "output": result.stdout
                    }), 500
                
                logger.info(f"Successfully obtained certificate for {domain} using webroot")
                
                # Automatically install the certificate
                logger.info(f"Installing certificate for {domain}")
                install_result = _install_certificate_internal(domain)
                
                if install_result["success"]:
                    return jsonify({
                        "success": True,
                        "message": f"Successfully obtained and installed SSL certificate for {domain}",
                        "output": result.stdout,
                        "installation": install_result.get("details", {}),
                        "note": "Certificate installed and nginx reloaded. Your site should now be using the Let's Encrypt certificate."
                    })
                else:
                    # Certificate obtained but installation failed
                    return jsonify({
                        "success": True,
                        "message": f"Successfully obtained SSL certificate for {domain}, but installation failed",
                        "output": result.stdout,
                        "installation_error": install_result.get("error", "Unknown installation error"),
                        "note": "Certificate obtained successfully but automatic installation failed. You may need to install it manually using the 'Install Certificate' button."
                    })
                
            except subprocess.TimeoutExpired:
                logger.error("Certbot webroot operation timed out")
                return jsonify({
                    "success": False,
                    "error": "Certbot operation timed out"
                }), 500
            except Exception as e:
                logger.error(f"Certbot webroot execution failed: {e}")
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

        # Detect staging-to-production mismatch.
        # 'certbot renew' reads the ACME server URL from the stored renewal
        # config, so passing or omitting --staging has no effect — it will
        # always renew from whichever server was used during the original
        # 'certbot certonly'.  If the current cert is staging but the user
        # wants production, they must re-obtain, not renew.
        domain = settings.domain_name.strip()
        if not settings.staging and domain and _is_existing_cert_staging(domain):
            return jsonify({
                "success": False,
                "error": (
                    "Cannot renew: the current certificate was issued by the Let's Encrypt "
                    "staging server, but your settings are now set to production. "
                    "Renewal would only produce another staging certificate. "
                    "Please use 'Obtain Certificate' to get a new production certificate — "
                    "the staging certificate will be cleaned up automatically."
                ),
            }), 400

        # Build certbot renew command
        # Note: --staging is intentionally NOT appended here.  certbot renew
        # uses the ACME server stored in each renewal config file, so the flag
        # is meaningless and could be misleading in logs.
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
        
        try:
            logger.info(f"Running certbot renewal (dry_run={dry_run}, force={force})")
            logger.info(f"Certbot renewal command: {' '.join(certbot_cmd)}")
            result = subprocess.run(
                certbot_cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode != 0:
                logger.error(f"Certbot renewal failed: {result.stderr}")
                logger.error(f"Certbot stdout: {result.stdout}")
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


@certbot_bp.route('/api/certbot/install-certificate', methods=['POST'])
@require_auth
@require_permission('system.configure')
def install_certificate():
    """Install obtained certificate by creating symlink and updating nginx configuration.
    
    This endpoint:
    1. Creates symlink from custom certbot location to standard /etc/letsencrypt location
    2. Updates nginx configuration to use the Let's Encrypt certificates
    3. Reloads nginx to apply changes
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

        # SECURITY: Validate domain name
        domain = settings.domain_name.strip()
        if not DOMAIN_PATTERN.match(domain):
            logger.error(f"Invalid domain name in database: {domain}")
            return jsonify({
                "success": False,
                "error": "Invalid domain name in configuration"
            }), 500

        # Use the internal helper to do the installation
        result = _install_certificate_internal(domain)
        
        if result["success"]:
            return jsonify(result)
        else:
            # Return appropriate status code based on error
            status_code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), status_code

    except Exception as exc:
        logger.error(f"Failed to install certificate: {exc}")
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
