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

Was one 387-line ``try`` block (see
``docs/development/LARGE_FILE_REFACTOR_PLAN.md`` Phase 4a-ii cont.).
Pre-flight validation lives in ``obtain_validation.py``; the three certbot
methods (standalone, nginx plugin, webroot) live in ``obtain_methods.py``.
This module is now just the route handler: validate, check prerequisites,
clean up a staging→production switch, and dispatch to one method.
"""

from flask import jsonify, request

from app_core.auth.roles import require_permission
from app_core.certbot_settings import get_certbot_settings

from .blueprint import certbot_bp
from .log import logger
from .obtain_methods import _obtain_nginx, _obtain_standalone, _obtain_webroot
from .obtain_validation import _check_certbot_installed, _validate_obtain_request
from .paths import _ensure_certbot_directories, clear_stale_locks
from .staging import _delete_staging_certs, _is_existing_cert_staging

_OBTAIN_METHODS = {
    'standalone': _obtain_standalone,
    'nginx': _obtain_nginx,
    'webroot': _obtain_webroot,
}


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

        domain, email, error_response = _validate_obtain_request(settings, method)
        if error_response:
            return error_response

        # Clear any lock left by a previous run that was killed or crashed
        # before it could clean up after itself (see clear_stale_locks()).
        clear_stale_locks()

        install_error = _check_certbot_installed()
        if install_error:
            return install_error

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

        return _OBTAIN_METHODS[method](domain, email, staging_flag)

    except Exception as exc:
        logger.error(f"Failed to obtain certificate: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500
