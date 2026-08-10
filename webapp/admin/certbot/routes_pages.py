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

"""The rendered Certbot settings page."""

from flask import flash, redirect, render_template, url_for

from app_core.auth.roles import require_permission
from app_core.certbot_settings import get_certbot_settings

from .blueprint import certbot_bp
from .log import logger


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
