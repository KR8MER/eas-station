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

"""Audio alert endpoints."""

import logging
from flask import jsonify, request
from sqlalchemy import desc
from app_core.cache import cache
from app_core.extensions import db
from app_core.models import (
    AudioAlert,
)
from app_core.auth.roles import require_permission
from app_utils import utc_now

from .blueprint import audio_ingest_bp
from .sanitize import _sanitize_bool

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/alerts', methods=['GET'])
@cache.cached(timeout=10, query_string=True, key_prefix='audio_alerts')
def api_get_audio_alerts():
    """Get audio system alerts."""
    try:
        # Parse query parameters
        limit = request.args.get('limit', 50, type=int)
        limit = min(max(limit, 1), 500)  # Clamp between 1 and 500

        unresolved_only = request.args.get('unresolved_only', 'false').lower() == 'true'

        # Build query
        query = AudioAlert.query

        if unresolved_only:
            query = query.filter(AudioAlert.resolved == False)

        alerts = (
            query
            .order_by(desc(AudioAlert.created_at))
            .limit(limit)
            .all()
        )

        alerts_list = []
        for alert in alerts:
            alerts_list.append({
                'id': alert.id,
                'source_name': alert.source_name,
                'alert_level': alert.alert_level,
                'alert_type': alert.alert_type,
                'message': alert.message,
                'details': alert.details,
                'threshold_value': alert.threshold_value,
                'actual_value': alert.actual_value,
                'acknowledged': _sanitize_bool(alert.acknowledged) if alert.acknowledged is not None else False,
                'acknowledged_by': alert.acknowledged_by,
                'acknowledged_at': alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                'resolved': _sanitize_bool(alert.resolved) if alert.resolved is not None else False,
                'resolved_by': alert.resolved_by,
                'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
                'created_at': alert.created_at.isoformat() if alert.created_at else None,
            })

        unresolved_count = AudioAlert.query.filter(AudioAlert.resolved == False).count()

        return jsonify({
            'alerts': alerts_list,
            'total': len(alerts_list),
            'unresolved_count': unresolved_count,
        })

    except Exception as exc:
        logger.error('Error getting audio alerts: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@require_permission('system.configure')
def api_acknowledge_alert(alert_id: int):
    """Acknowledge an audio alert."""
    try:
        alert = AudioAlert.query.get(alert_id)
        if not alert:
            return jsonify({'error': 'Alert not found'}), 404

        data = request.get_json() or {}
        acknowledged_by = data.get('acknowledged_by', 'system')

        alert.acknowledged = True
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = utc_now()
        alert.updated_at = utc_now()

        db.session.commit()

        logger.info('Acknowledged alert %d by %s', alert_id, acknowledged_by)

        return jsonify({'message': 'Alert acknowledged successfully'})

    except Exception as exc:
        logger.error('Error acknowledging alert %d: %s', alert_id, exc)
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/alerts/<int:alert_id>/resolve', methods=['POST'])
@require_permission('system.configure')
def api_resolve_alert(alert_id: int):
    """Resolve an audio alert."""
    try:
        alert = AudioAlert.query.get(alert_id)
        if not alert:
            return jsonify({'error': 'Alert not found'}), 404

        data = request.get_json() or {}
        resolved_by = data.get('resolved_by', 'system')
        resolution_notes = data.get('resolution_notes', '')

        alert.resolved = True
        alert.resolved_by = resolved_by
        alert.resolved_at = utc_now()
        alert.resolution_notes = resolution_notes
        alert.updated_at = utc_now()

        db.session.commit()

        logger.info('Resolved alert %d by %s', alert_id, resolved_by)

        return jsonify({'message': 'Alert resolved successfully'})

    except Exception as exc:
        logger.error('Error resolving alert %d: %s', alert_id, exc)
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/alerts/resolve-all', methods=['POST'])
@require_permission('system.configure')
def api_resolve_all_alerts():
    """Resolve every currently-unresolved audio alert in one operation.

    Silence/health alerts can accumulate into the tens of thousands, which makes
    clearing them one-by-one from the UI impractical. This bulk-resolves all
    outstanding alerts so the operator can reset the unresolved count.
    """
    try:
        data = request.get_json(silent=True) or {}
        resolved_by = data.get('resolved_by', 'web_user')
        resolution_notes = data.get('resolution_notes', 'Bulk resolved from UI')
        now = utc_now()

        updated = (
            AudioAlert.query
            .filter(AudioAlert.resolved == False)
            .update(
                {
                    AudioAlert.resolved: True,
                    AudioAlert.resolved_by: resolved_by,
                    AudioAlert.resolved_at: now,
                    AudioAlert.resolution_notes: resolution_notes,
                    AudioAlert.updated_at: now,
                },
                synchronize_session=False,
            )
        )

        db.session.commit()

        logger.info('Bulk-resolved %d audio alert(s) by %s', updated, resolved_by)

        return jsonify({
            'message': f'Resolved {updated} alert(s)',
            'resolved_count': updated,
        })

    except Exception as exc:
        logger.error('Error bulk-resolving audio alerts: %s', exc)
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500
