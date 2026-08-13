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

import logging

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import AlertGatingSettings
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger

logger = logging.getLogger(__name__)

alert_gating_bp = Blueprint('alert_gating', __name__, url_prefix='/admin/alert-gating')


def _get_or_create_settings() -> AlertGatingSettings:
    """Get gated-alerts settings, creating defaults if none exist."""
    settings = AlertGatingSettings.query.first()
    if not settings:
        settings = AlertGatingSettings(enabled=False, hold_off_seconds=120)
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default alert gating settings")
    return settings


@alert_gating_bp.route('/', methods=['GET'])
@require_auth
@require_permission('system.configure')
def alert_gating_settings():
    """Display gated-alerts hold-off timer settings page."""
    try:
        settings = _get_or_create_settings()
        return render_template('admin/alert_gating.html', settings=settings)
    except SQLAlchemyError as e:
        logger.error(f"Database error loading alert gating settings: {str(e)}")
        db.session.rollback()
        flash('Database error loading alert gating settings', 'danger')
        return redirect(url_for('dashboard.admin'))


@alert_gating_bp.route('/update', methods=['POST'])
@require_auth
@require_permission('system.configure')
def update_alert_gating_settings():
    """Update gated-alerts hold-off timer settings."""
    try:
        settings = AlertGatingSettings.query.first()
        if not settings:
            settings = AlertGatingSettings()
            db.session.add(settings)

        settings.enabled = request.form.get('enabled', 'false').lower() == 'true'

        hold_off_seconds = int(request.form.get('hold_off_seconds', 120))
        if hold_off_seconds < 10:
            return jsonify({'success': False, 'error': 'Hold-off duration must be at least 10 seconds'}), 400
        if hold_off_seconds > 3600:
            return jsonify({'success': False, 'error': 'Hold-off duration must be at most 3600 seconds (1 hour)'}), 400
        settings.hold_off_seconds = hold_off_seconds

        db.session.commit()
        logger.info(
            "Updated alert gating settings: enabled=%s, hold_off_seconds=%s",
            settings.enabled, settings.hold_off_seconds,
        )

        AuditLogger.log_config_change(
            resource_type='alert_gating_settings',
            resource_id=str(settings.id) if settings.id is not None else None,
            details={
                'enabled': settings.enabled,
                'hold_off_seconds': settings.hold_off_seconds,
            },
        )

        return jsonify({'success': True, 'message': 'Alert gating settings updated successfully',
                        'settings': settings.to_dict()})

    except ValueError as e:
        logger.error(f"Invalid value in alert gating settings: {str(e)}")
        return jsonify({'success': False, 'error': f'Invalid value: {str(e)}'}), 400
    except SQLAlchemyError as e:
        logger.error(f"Database error updating alert gating settings: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving alert gating settings'}), 500
