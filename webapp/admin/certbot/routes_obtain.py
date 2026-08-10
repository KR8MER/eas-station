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

"""Preparing to obtain a certificate: the dry run and the domain test.

These two validate and report; ``routes_obtain_execute`` is what actually
calls certbot.
"""

import socket
import subprocess

from flask import jsonify, request

from app_core.auth.roles import require_permission
from app_core.certbot_settings import get_certbot_settings

from .blueprint import DOMAIN_PATTERN, EMAIL_PATTERN, certbot_bp
from .log import logger
from .paths import CERTBOT_CONFIG_DIR, CERTBOT_LOGS_DIR, CERTBOT_WORK_DIR


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
