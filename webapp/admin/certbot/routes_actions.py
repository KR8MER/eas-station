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

"""The remaining one-shot certificate actions.

Enabling the auto-renewal timer, downloading the certificate bundle, and
installing an already-obtained certificate into nginx.
"""

import subprocess

from flask import jsonify, request, send_file

from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.certbot_settings import get_certbot_settings

from .blueprint import DOMAIN_PATTERN, certbot_bp
from .install import _install_certificate_internal
from .log import logger
from .paths import CERTBOT_CONFIG_DIR


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
