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

"""Certificate status and the certbot log tail."""

import subprocess

from flask import jsonify, request

from app_core.auth.roles import require_permission

from .blueprint import certbot_bp
from .log import logger
from .paths import CERTBOT_LOGS_DIR


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
