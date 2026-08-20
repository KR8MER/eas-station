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
from app_core.models import HeartbeatSettings
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger
from app_core.heartbeat_worker import send_heartbeat_ping
from app_utils import utc_now

logger = logging.getLogger(__name__)

heartbeat_bp = Blueprint('heartbeat', __name__, url_prefix='/admin/heartbeat')


def _get_or_create_settings() -> HeartbeatSettings:
    """Get heartbeat settings, creating defaults if none exist."""
    settings = HeartbeatSettings.query.first()
    if not settings:
        settings = HeartbeatSettings(
            enabled=False,
            ping_url='',
            interval_seconds=300,
        )
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default heartbeat settings")
    return settings


@heartbeat_bp.route('/', methods=['GET'])
@require_auth
@require_permission('system.configure')
def heartbeat_settings():
    """Display uptime heartbeat configuration page."""
    try:
        settings = _get_or_create_settings()
        return render_template('admin/heartbeat.html', settings=settings)
    except SQLAlchemyError as e:
        logger.error(f"Database error loading heartbeat settings: {str(e)}")
        db.session.rollback()
        flash('Database error loading heartbeat settings', 'danger')
        return redirect(url_for('dashboard.admin'))


@heartbeat_bp.route('/update', methods=['POST'])
@require_auth
@require_permission('system.configure')
def update_heartbeat_settings():
    """Update uptime heartbeat configuration."""
    try:
        settings = HeartbeatSettings.query.first()
        if not settings:
            settings = HeartbeatSettings()
            db.session.add(settings)

        settings.enabled = request.form.get('enabled', 'false').lower() == 'true'

        ping_url = request.form.get('ping_url', '').strip()
        if settings.enabled:
            if not ping_url:
                return jsonify({'success': False, 'error': 'Ping URL is required when the heartbeat is enabled'}), 400
            if not (ping_url.startswith('http://') or ping_url.startswith('https://')):
                return jsonify({'success': False, 'error': 'Ping URL must start with http:// or https://'}), 400
        settings.ping_url = ping_url

        interval_seconds = int(request.form.get('interval_seconds', 300))
        if interval_seconds < 60:
            return jsonify({'success': False, 'error': 'Interval must be at least 60 seconds'}), 400
        settings.interval_seconds = interval_seconds

        db.session.commit()
        logger.info(
            "Updated heartbeat settings: enabled=%s, interval=%ss",
            settings.enabled, settings.interval_seconds,
        )

        AuditLogger.log_config_change(
            resource_type='heartbeat_settings',
            resource_id=str(settings.id) if settings.id is not None else None,
            details={
                'enabled': settings.enabled,
                'interval_seconds': settings.interval_seconds,
            },
        )

        return jsonify({'success': True, 'message': 'Heartbeat settings updated successfully',
                        'settings': settings.to_dict()})

    except ValueError as e:
        logger.error(f"Invalid value in heartbeat settings: {str(e)}")
        return jsonify({'success': False, 'error': f'Invalid value: {str(e)}'}), 400
    except SQLAlchemyError as e:
        logger.error(f"Database error updating heartbeat settings: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving heartbeat settings'}), 500


@heartbeat_bp.route('/test', methods=['POST'])
@require_auth
@require_permission('system.configure')
def test_heartbeat():
    """Send one immediate test ping using the currently saved (or posted) URL."""
    ping_url = (request.get_json(silent=True) or {}).get('ping_url', '').strip()
    if not ping_url:
        settings = HeartbeatSettings.query.first()
        ping_url = settings.ping_url if settings else ''

    if not ping_url:
        return jsonify({'success': False, 'error': 'No ping URL configured'}), 400

    success, error = send_heartbeat_ping(ping_url)
    if success:
        return jsonify({'success': True, 'message': 'Ping sent successfully'})
    return jsonify({'success': False, 'error': error or 'Ping failed'}), 502


@heartbeat_bp.route('/status', methods=['GET'])
@require_auth
@require_permission('system.view_config')
def heartbeat_status():
    """Get current heartbeat settings/status as JSON."""
    try:
        settings = HeartbeatSettings.query.first()
        if not settings:
            return jsonify({'success': False, 'error': 'Heartbeat settings not configured'}), 404
        return jsonify({'success': True, 'settings': settings.to_dict()})
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching heartbeat status: {str(e)}")
        return jsonify({'success': False, 'error': 'Database error'}), 500
