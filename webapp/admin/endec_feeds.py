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

"""ENDEC Device Feeds admin page.

Configures the Sage-ENDEC-compatible TCP "device feeds" (Generic Character
Generator, News Feed, decoder status, raw EAS encoder mirror) served by the
``services.endec_feeds`` subprocess. See
``docs/reference/protocols/SAGE_ENDEC.md``.
"""

import logging

from flask import Blueprint, jsonify, render_template, request
from werkzeug.exceptions import BadRequest

from app_core import db
from app_core.models import EASSettings
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger
from app_utils.endec_feeds import FEED_FORMATS

logger = logging.getLogger(__name__)

endec_feeds_bp = Blueprint('endec_feeds', __name__)


def _get_or_create_settings() -> EASSettings:
    settings = EASSettings.query.get(1)
    if settings is None:
        settings = EASSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    return settings


def _validate_feeds(raw):
    """Validate the posted feeds list, returning a clean list or raising."""
    if not isinstance(raw, list):
        raise BadRequest('feeds must be a list')
    cleaned = []
    seen_ports = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise BadRequest('each feed must be an object')
        fmt = str(entry.get('format', '')).strip().lower()
        if fmt not in FEED_FORMATS:
            raise BadRequest(f"invalid feed format: {entry.get('format')!r}")
        try:
            port = int(entry.get('port'))
        except (TypeError, ValueError):
            raise BadRequest(f"invalid port: {entry.get('port')!r}")
        if not (1 <= port <= 65535):
            raise BadRequest(f"port out of range: {port}")
        if port in seen_ports:
            raise BadRequest(f"duplicate port: {port}")
        seen_ports.add(port)
        cleaned.append({
            'name': (str(entry.get('name') or fmt).strip())[:64] or fmt,
            'format': fmt,
            'port': port,
            'enabled': bool(entry.get('enabled', True)),
        })
    return cleaned


@endec_feeds_bp.route('/admin/endec_feeds')
def endec_feeds_page():
    """Render the ENDEC device feeds settings page."""
    return render_template('admin/endec_feeds.html', feed_formats=list(FEED_FORMATS))


@endec_feeds_bp.route('/api/admin/endec_feeds/settings', methods=['GET'])
def get_endec_feeds_settings():
    """Return the current ENDEC feed configuration."""
    try:
        settings = _get_or_create_settings()
        return jsonify({
            'enabled': bool(settings.endec_feeds_enabled),
            'feeds': list(settings.endec_feeds or []),
            'formats': list(FEED_FORMATS),
        })
    except Exception as exc:
        logger.error('Error getting ENDEC feed settings: %s', exc, exc_info=True)
        return jsonify({'error': str(exc)}), 500


@endec_feeds_bp.route('/api/admin/endec_feeds/settings', methods=['PUT'])
@require_permission('system.configure')
def update_endec_feeds_settings():
    """Persist the ENDEC feed configuration and hot-reload the service."""
    try:
        data = request.get_json()
        if not isinstance(data, dict):
            raise BadRequest('Invalid JSON payload')

        settings = _get_or_create_settings()

        if 'enabled' in data:
            settings.endec_feeds_enabled = bool(data['enabled'])
        if 'feeds' in data:
            settings.endec_feeds = _validate_feeds(data['feeds'])

        db.session.commit()

        # Only record fields this handler actually processes/persists.
        allowed_keys = {'enabled', 'feeds'}
        AuditLogger.log_config_change(
            resource_type='endec_feeds_settings',
            resource_id=str(settings.id) if getattr(settings, 'id', None) is not None else None,
            details={'changed_fields': sorted(k for k in data if k in allowed_keys)},
        )

        # Tell the running feed service to pick up the new config immediately.
        try:
            from app_core.audio.endec_feed_publisher import publish_feed_reload
            publish_feed_reload(logger_instance=logger)
        except Exception as exc:
            logger.debug('ENDEC feed reload signal skipped: %s', exc)

        return jsonify({
            'message': 'ENDEC feed settings updated',
            'settings': {
                'enabled': bool(settings.endec_feeds_enabled),
                'feeds': list(settings.endec_feeds or []),
            },
        })
    except BadRequest:
        db.session.rollback()
        raise
    except Exception as exc:
        db.session.rollback()
        logger.error('Error updating ENDEC feed settings: %s', exc, exc_info=True)
        return jsonify({'error': str(exc)}), 500


def register_blueprint(app):
    """Register the blueprint with the Flask app."""
    app.register_blueprint(endec_feeds_bp)
