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

"""Reading and writing the stored Certbot settings."""

from flask import jsonify, request
from werkzeug.exceptions import BadRequest

from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger
from app_core.extensions import db
from app_core.certbot_settings import get_certbot_settings, update_certbot_settings

from .blueprint import DOMAIN_PATTERN, EMAIL_PATTERN, certbot_bp
from .log import logger


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

        AuditLogger.log_config_change(
            resource_type='certbot_settings',
            resource_id=str(settings.id) if getattr(settings, 'id', None) is not None else None,
            details={'changed_fields': sorted(data.keys())},
        )

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
