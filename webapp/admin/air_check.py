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

"""Air-Check page: did what we sent actually make it onto the air?"""

import logging
from datetime import timedelta

from flask import Blueprint, g, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

from app_core.air_check import (
    MAX_GRACE_SECONDS,
    MIN_GRACE_SECONDS,
    air_check_receivers,
    get_grace_seconds,
    summarize,
    sweep_overdue,
)
from app_core.auth.audit import AuditLogger
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import AirCheckRecord, AirCheckSettings
from app_core._models_air_check import AIR_CHECK_STATUSES
from app_utils import utc_now

logger = logging.getLogger(__name__)

air_check_bp = Blueprint('air_check', __name__)

_MAX_DAYS = 90
_MAX_RECORDS = 500


@air_check_bp.route('/air-check', methods=['GET'])
@require_auth
@require_permission('receivers.view')
def air_check_page():
    """Air-Check results, air-check receivers and grace-period setting."""
    return render_template(
        'admin/air_check.html',
        receivers=air_check_receivers(),
        grace_seconds=get_grace_seconds(),
        min_grace=MIN_GRACE_SECONDS,
        max_grace=MAX_GRACE_SECONDS,
        statuses=AIR_CHECK_STATUSES,
    )


@air_check_bp.route('/api/air-check/records', methods=['GET'])
@require_auth
@require_permission('receivers.view')
def api_air_check_records():
    """List air-check records with a 24-hour status summary.

    Closes out any overdue pending records first, so the list never shows a
    transmission as "pending" after its deadline has passed.

    Query:
        days (int, optional): Look-back window in days, 1-90. Default 7.
        status (str, optional): Only records with this status (pending,
            verified, mismatch, missed, unexpected).

    Returns:
        200 with {success, summary, records: [<record dict>...]}.
        400 if status is not a known value.
        500 on a database error.
    """
    try:
        days = max(1, min(int(request.args.get('days', 7)), _MAX_DAYS))
    except (TypeError, ValueError):
        days = 7
    status = (request.args.get('status') or '').strip().lower()
    if status and status not in AIR_CHECK_STATUSES:
        return jsonify({'success': False, 'error': f'Unknown status: {status}'}), 400

    try:
        sweep_overdue()
        query = AirCheckRecord.query.filter(
            AirCheckRecord.created_at >= utc_now() - timedelta(days=days)
        )
        if status:
            query = query.filter(AirCheckRecord.status == status)
        records = query.order_by(AirCheckRecord.created_at.desc()).limit(_MAX_RECORDS).all()
        return jsonify({
            'success': True,
            'summary': summarize(24),
            'records': [record.to_dict() for record in records],
        })
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.error(f"Database error listing air-check records: {exc}")
        return jsonify({'success': False, 'error': 'Database error'}), 500


@air_check_bp.route('/api/air-check/records/<int:record_id>/acknowledge', methods=['POST'])
@require_auth
@require_permission('receivers.configure')
def api_air_check_acknowledge(record_id: int):
    """Acknowledge a missed, mismatched or unexpected air-check.

    Acknowledged records stay in the history but stop counting as open
    problems for the health-alert emails and the summary tiles.

    Path:
        record_id (int): The air-check record to acknowledge.

    Returns:
        200 with {success, record}.
        404 if the record does not exist.
        500 on a database error.
    """
    record = AirCheckRecord.query.get(record_id)
    if record is None:
        return jsonify({'success': False, 'error': 'Air-check record not found'}), 404
    try:
        record.acknowledged_at = utc_now()
        record.acknowledged_by = getattr(getattr(g, 'current_user', None), 'username', None)
        db.session.commit()
        AuditLogger.log_config_change(
            resource_type='air_check_record',
            resource_id=str(record.id),
            details={'action': 'acknowledge', 'status': record.status},
        )
        return jsonify({'success': True, 'record': record.to_dict()})
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.error("Database error acknowledging air-check %d: %s", record.id, exc)
        return jsonify({'success': False, 'error': 'Database error'}), 500


@air_check_bp.route('/api/air-check/settings', methods=['POST'])
@require_auth
@require_permission('receivers.configure')
def api_air_check_settings():
    """Save the air-check grace period.

    Body:
        grace_seconds (int, required): Seconds allowed past the end of
            playout for an air-check receiver to decode the header before
            the transmission is declared missed (10-900).

    Returns:
        200 with {success, settings}.
        400 if grace_seconds is missing or out of range.
        500 on a database error.
    """
    data = request.get_json(silent=True) or {}
    try:
        grace = int(data.get('grace_seconds'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Grace period must be a whole number'}), 400
    if not MIN_GRACE_SECONDS <= grace <= MAX_GRACE_SECONDS:
        return jsonify({
            'success': False,
            'error': f'Grace period must be between {MIN_GRACE_SECONDS} and '
                     f'{MAX_GRACE_SECONDS} seconds',
        }), 400
    try:
        settings = AirCheckSettings.query.get(1)
        if settings is None:
            settings = AirCheckSettings(id=1)
            db.session.add(settings)
        settings.grace_seconds = grace
        db.session.commit()
        AuditLogger.log_config_change(
            resource_type='air_check_settings',
            resource_id='1',
            details={'grace_seconds': grace},
        )
        return jsonify({'success': True, 'settings': settings.to_dict()})
    except SQLAlchemyError as exc:
        db.session.rollback()
        logger.error(f"Database error saving air-check settings: {exc}")
        return jsonify({'success': False, 'error': 'Database error'}), 500
