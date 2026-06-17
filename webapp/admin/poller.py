"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

import json
import logging

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import PollerSettings
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger

logger = logging.getLogger(__name__)

poller_bp = Blueprint('poller', __name__, url_prefix='/admin/poller')


def _get_or_create_settings() -> PollerSettings:
    """Get poller settings, creating defaults if none exist."""
    settings = PollerSettings.query.first()
    if not settings:
        settings = PollerSettings(
            enabled=True,
            poll_interval_sec=120,
            cap_timeout=30,
            noaa_user_agent='EAS Station (+https://github.com/KR8MER/eas-station; support@easstation.com)',
            cap_endpoints=[],
            ipaws_feed_urls=[],
            ipaws_default_lookback_hours=12,
            log_fetched_alerts=False,
        )
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default poller settings")
    return settings


@poller_bp.route('/', methods=['GET'])
@require_auth
@require_permission('system.configure')
def poller_settings():
    """Display poller configuration settings page."""
    try:
        settings = _get_or_create_settings()
        return render_template('admin/poller.html', settings=settings)
    except SQLAlchemyError as e:
        logger.error(f"Database error loading poller settings: {str(e)}")
        db.session.rollback()
        flash('Database error loading poller settings', 'danger')
        return redirect(url_for('dashboard.admin'))


@poller_bp.route('/update', methods=['POST'])
@require_auth
@require_permission('system.configure')
def update_poller_settings():
    """Update poller configuration settings."""
    try:
        settings = PollerSettings.query.first()
        if not settings:
            settings = PollerSettings()
            db.session.add(settings)

        # Basic poller config
        settings.enabled = request.form.get('enabled', 'false').lower() == 'true'
        poll_interval_sec = int(request.form.get('poll_interval_sec', 120))
        if poll_interval_sec < 30:
            return jsonify({'success': False, 'error': 'Poll interval must be at least 30 seconds'}), 400
        settings.poll_interval_sec = poll_interval_sec

        cap_timeout = int(request.form.get('cap_timeout', 30))
        if cap_timeout < 5:
            return jsonify({'success': False, 'error': 'Request timeout must be at least 5 seconds'}), 400
        settings.cap_timeout = cap_timeout

        settings.noaa_user_agent = request.form.get('noaa_user_agent', '').strip()

        # CAP endpoints: textarea -> list of non-empty lines
        cap_endpoints_raw = request.form.get('cap_endpoints', '').strip()
        settings.cap_endpoints = [
            url.strip() for url in cap_endpoints_raw.splitlines() if url.strip()
        ]

        # IPAWS feed URLs: textarea -> list of non-empty lines
        ipaws_feed_urls_raw = request.form.get('ipaws_feed_urls', '').strip()
        settings.ipaws_feed_urls = [
            url.strip() for url in ipaws_feed_urls_raw.splitlines() if url.strip()
        ]

        ipaws_lookback = int(request.form.get('ipaws_default_lookback_hours', 12))
        if ipaws_lookback < 1:
            return jsonify({'success': False, 'error': 'IPAWS lookback must be at least 1 hour'}), 400
        settings.ipaws_default_lookback_hours = ipaws_lookback

        settings.log_fetched_alerts = request.form.get('log_fetched_alerts', 'false').lower() == 'true'

        db.session.commit()
        logger.info(
            "Updated poller settings: enabled=%s, interval=%ss, cap_timeout=%ss, "
            "cap_endpoints=%d, ipaws_urls=%d",
            settings.enabled, settings.poll_interval_sec, settings.cap_timeout,
            len(settings.cap_endpoints), len(settings.ipaws_feed_urls),
        )

        AuditLogger.log_config_change(
            resource_type='poller_settings',
            resource_id=str(settings.id) if settings.id is not None else None,
            details={
                'enabled': settings.enabled,
                'poll_interval_sec': settings.poll_interval_sec,
                'cap_timeout': settings.cap_timeout,
                'noaa_user_agent': settings.noaa_user_agent,
                'cap_endpoint_count': len(settings.cap_endpoints),
                'ipaws_feed_url_count': len(settings.ipaws_feed_urls),
                'ipaws_default_lookback_hours': settings.ipaws_default_lookback_hours,
                'log_fetched_alerts': settings.log_fetched_alerts,
            },
        )

        return jsonify({'success': True, 'message': 'Poller settings updated successfully',
                        'settings': settings.to_dict()})

    except ValueError as e:
        logger.error(f"Invalid value in poller settings: {str(e)}")
        return jsonify({'success': False, 'error': f'Invalid value: {str(e)}'}), 400
    except SQLAlchemyError as e:
        logger.error(f"Database error updating poller settings: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving poller settings'}), 500


@poller_bp.route('/status', methods=['GET'])
@require_auth
@require_permission('system.view_config')
def poller_status():
    """Get current poller settings as JSON."""
    try:
        settings = PollerSettings.query.first()
        if not settings:
            return jsonify({'success': False, 'error': 'Poller settings not configured'}), 404
        return jsonify({'success': True, 'settings': settings.to_dict()})
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching poller status: {str(e)}")
        return jsonify({'success': False, 'error': 'Database error'}), 500
