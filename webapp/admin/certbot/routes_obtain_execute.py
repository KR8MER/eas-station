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

"""``/api/certbot/obtain-certificate-execute`` — the real certificate run.

**Over the 400-line guidance, and knowingly so.** The handler is one 387-line
``try`` block, so module-level splitting cannot shrink it — that needs
collaborators extracted from the body, which is a behavioural refactor and
needs the behaviour pinned by tests first. This module had no test coverage at
all before the split. Tracked as a follow-up in
``docs/development/LARGE_FILE_REFACTOR_PLAN.md``.
"""

import subprocess
import time

from flask import jsonify, request

from app_core.auth.roles import require_permission
from app_core.certbot_settings import get_certbot_settings

from .blueprint import DOMAIN_PATTERN, EMAIL_PATTERN, certbot_bp
from .failures import _explain_certbot_failure
from .install import _install_certificate_internal
from .log import logger
from .nginx import _check_nginx_status, _ensure_nginx_running
from .paths import (
    CERTBOT_CONFIG_DIR,
    CERTBOT_LOGS_DIR,
    CERTBOT_WORK_DIR,
    _ensure_certbot_directories,
    _ensure_webroot_directory,
)
from .staging import _delete_staging_certs, _is_existing_cert_staging


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
                    error_msg = _explain_certbot_failure(certbot_result.stderr, certbot_result.stdout)

                    # Log the full error for debugging
                    logger.error(f"Certbot standalone failed with return code {certbot_result.returncode}")
                    logger.error(f"Certbot stderr: {certbot_result.stderr}")
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
