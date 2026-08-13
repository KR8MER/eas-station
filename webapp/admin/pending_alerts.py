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

from flask import Blueprint, render_template, request, jsonify

from app_core.extensions import db
from app_core.models import CAPAlert, GatedAlert
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission, get_current_user, has_permission
from app_core.auth.audit import AuditLogger

logger = logging.getLogger(__name__)

pending_alerts_bp = Blueprint('pending_alerts', __name__, url_prefix='/admin/pending-alerts')


def _serialize_pending(rows):
    return [row.to_dict() for row in rows]


@pending_alerts_bp.route('/', methods=['GET'])
@require_auth
@require_permission('eas.view')
def pending_alerts_list():
    """Display the gated-alerts Pending Alerts queue."""
    rows = (
        GatedAlert.without_audio()
        .filter_by(status='pending')
        .order_by(GatedAlert.hold_until.asc())
        .all()
    )
    return render_template(
        'admin/pending_alerts.html',
        pending_alerts=rows,
        can_approve=has_permission('eas.manual_activate'),
        can_cancel=has_permission('eas.cancel'),
    )


@pending_alerts_bp.route('/api/list', methods=['GET'])
@require_auth
@require_permission('eas.view')
def pending_alerts_api_list():
    """JSON list of pending gated alerts (polling fallback for the websocket push)."""
    rows = (
        GatedAlert.without_audio()
        .filter_by(status='pending')
        .order_by(GatedAlert.hold_until.asc())
        .all()
    )
    return jsonify({'alerts': _serialize_pending(rows), 'count': len(rows)})


@pending_alerts_bp.route('/<int:gate_id>/approve', methods=['POST'])
@require_auth
@require_permission('eas.manual_activate')
def approve_pending_alert(gate_id):
    """Approve a pending gated alert, releasing it for immediate broadcast."""
    gate_row = db.session.get(GatedAlert, gate_id)
    if gate_row is None:
        return jsonify({'success': False, 'error': 'Pending alert not found'}), 404
    if gate_row.status != 'pending':
        return jsonify({'success': False, 'error': f'Alert is no longer pending (status={gate_row.status})'}), 409

    user = get_current_user()
    from app_utils import utc_now

    gate_row.status = 'approved'
    gate_row.resolved_at = utc_now()
    gate_row.resolved_by = user.username if user else None
    gate_row.resolved_by_ip = request.remote_addr
    gate_row.resolution_reason = 'Approved by operator'
    db.session.add(gate_row)
    db.session.commit()

    broadcast_result = _release_gate_row(gate_row)

    AuditLogger.log_config_change(
        resource_type='gated_alert',
        resource_id=str(gate_row.id),
        details={'action': 'approve', 'source': gate_row.source, 'identifier': gate_row.identifier},
    )

    return jsonify({
        'success': True,
        'message': 'Alert approved and released for broadcast',
        'broadcast_result': broadcast_result,
    })


@pending_alerts_bp.route('/<int:gate_id>/cancel', methods=['POST'])
@require_auth
@require_permission('eas.cancel')
def cancel_pending_alert(gate_id):
    """Cancel a pending gated alert, permanently blocking its broadcast."""
    gate_row = db.session.get(GatedAlert, gate_id)
    if gate_row is None:
        return jsonify({'success': False, 'error': 'Pending alert not found'}), 404
    if gate_row.status != 'pending':
        return jsonify({'success': False, 'error': f'Alert is no longer pending (status={gate_row.status})'}), 409

    user = get_current_user()
    from app_utils import utc_now

    gate_row.status = 'cancelled'
    gate_row.resolved_at = utc_now()
    gate_row.resolved_by = user.username if user else None
    gate_row.resolved_by_ip = request.remote_addr
    gate_row.resolution_reason = 'Cancelled by operator'
    db.session.add(gate_row)

    # Stamp the CAPAlert row directly rather than waiting for a future
    # re-invocation of auto_forward_cap_alert() that may never happen, so
    # alert-history views reflect the cancellation immediately.
    if gate_row.cap_alert_id:
        cap_alert = db.session.get(CAPAlert, gate_row.cap_alert_id)
        if cap_alert is not None:
            cap_alert.eas_forwarded = False
            cap_alert.eas_forwarding_reason = 'Cancelled by operator via gated-alert queue'[:255]
            db.session.add(cap_alert)

    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='gated_alert',
        resource_id=str(gate_row.id),
        details={'action': 'cancel', 'source': gate_row.source, 'identifier': gate_row.identifier},
    )

    return jsonify({'success': True, 'message': 'Alert cancelled'})


def _release_gate_row(gate_row):
    """Replay a just-approved gated alert through the normal broadcast path.

    Re-invokes the same auto_forward_*() function used at ingest time; the
    gate sees the row is no longer 'pending' and falls through to the
    unchanged dedup + broadcast tail. Must run inside a Flask app context
    (this route always has one).
    """
    try:
        if gate_row.source == 'cap':
            from app_core.audio.auto_forward import auto_forward_cap_alert
            from app_core.models import EASMessage
            from app_core.location import get_location_settings
            from app_utils.eas import load_eas_config

            cap_alert = db.session.get(CAPAlert, gate_row.cap_alert_id) if gate_row.cap_alert_id else None
            if cap_alert is None:
                logger.warning(
                    "Cannot release gated CAP alert id=%s: no matching cap_alerts row (id=%s)",
                    gate_row.id, gate_row.cap_alert_id,
                )
                return None

            eas_config = load_eas_config()
            location_settings = get_location_settings()
            result = auto_forward_cap_alert(
                cap_alert=cap_alert,
                alert_data={'raw_json': cap_alert.raw_json or {}},
                db_session=db.session,
                eas_message_cls=EASMessage,
                eas_config=eas_config,
                location_settings=location_settings,
                logger_instance=logger,
            )
        else:
            from app_core.audio.alert_forwarding import _auto_forward_to_air_chain

            alert_dict = dict(gate_row.ota_payload or {})
            alert_dict['identifier'] = gate_row.identifier
            if gate_row.ota_audio_wav:
                alert_dict['relay_audio_wav'] = gate_row.ota_audio_wav
            result = _auto_forward_to_air_chain(alert_dict)

        gate_row.broadcast_result = result
        db.session.add(gate_row)
        db.session.commit()
        return result
    except Exception as exc:
        logger.error("Failed to release approved gated alert id=%s: %s", gate_row.id, exc, exc_info=True)
        return {'forwarded': False, 'reason': f'Release failed: {exc}'}
