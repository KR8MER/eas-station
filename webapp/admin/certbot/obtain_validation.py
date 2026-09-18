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

"""Pre-flight validation for ``obtain-certificate-execute``."""

import subprocess
from typing import Any, Optional, Tuple

from flask import jsonify

from .blueprint import DOMAIN_PATTERN, EMAIL_PATTERN
from .log import logger


def _validate_obtain_request(settings, method: str) -> Tuple[Optional[str], Optional[str], Any]:
    """Validate settings and the requested method.

    Returns ``(domain, email, error_response)``. ``error_response`` is
    ``None`` on success and a Flask ``(jsonify(...), status)`` tuple on
    failure, in which case ``domain``/``email`` are also ``None``.
    """

    if not settings.enabled:
        return None, None, (jsonify({
            "success": False,
            "error": "Certbot is not enabled in settings"
        }), 400)

    if not settings.domain_name:
        return None, None, (jsonify({
            "success": False,
            "error": "Domain name is not configured"
        }), 400)

    if not settings.email:
        return None, None, (jsonify({
            "success": False,
            "error": "Email address is not configured"
        }), 400)

    # SECURITY: Validate domain name (defense in depth)
    domain = settings.domain_name.strip()
    if not DOMAIN_PATTERN.match(domain):
        logger.error(f"Invalid domain name in database: {domain}")
        return None, None, (jsonify({
            "success": False,
            "error": "Invalid domain name in configuration"
        }), 500)

    # SECURITY: Validate email
    email = settings.email.strip()
    if not EMAIL_PATTERN.match(email):
        logger.error(f"Invalid email in database: {email}")
        return None, None, (jsonify({
            "success": False,
            "error": "Invalid email address in configuration"
        }), 500)

    # SECURITY: Validate method
    if method not in ['standalone', 'nginx', 'webroot']:
        return None, None, (jsonify({
            "success": False,
            "error": "Invalid method. Must be 'standalone', 'nginx', or 'webroot'"
        }), 400)

    return domain, email, None


def _check_certbot_installed() -> Any:
    """Return an error response if certbot isn't installed, else ``None``."""

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

    return None
