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

"""healthchecks.io API action routes.

No page of its own: the Uptime Monitoring page (webapp/admin/tickstem.py,
templates/admin/tickstem.html) renders both Tickstem's and healthchecks.io's
settings together, so an operator manages every uptime-monitoring provider
from one place instead of hopping between per-provider pages. This blueprint
exists only for the POST/GET *action* endpoints the page's JS calls
(save the API key, create/pause/resume/delete per-service heartbeats) --
mirroring how Tickstem's own actions live in webapp/admin/tickstem.py
alongside its page route, just split into a separate module since
healthchecks.io is a distinct account/API surface.
"""

import logging

from flask import Blueprint, request, jsonify
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import HealthchecksSettings
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger
from app_core import healthchecks_client

logger = logging.getLogger(__name__)

healthchecks_bp = Blueprint('healthchecks', __name__, url_prefix='/admin/healthchecks')


def _safe_api_error_message(e: "healthchecks_client.HealthchecksAPIError") -> str:
    """A message safe to log, store, or return to a client: carries the HTTP
    status code only, never the exception's own text (which echoes whatever
    healthchecks.io's API put in its response body). CodeQL's stack-trace/
    exception-exposure checks flag any raw exception object reaching a
    response or a stored field, regardless of how that message was built."""
    if e.status_code:
        return f'healthchecks.io API error (HTTP {e.status_code})'
    return 'healthchecks.io API error'


def get_or_create_settings() -> HealthchecksSettings:
    """Public (no leading underscore) since webapp/admin/tickstem.py's page
    route calls this too, to load healthchecks.io settings for the shared
    Uptime Monitoring page."""
    settings = HealthchecksSettings.query.first()
    if not settings:
        settings = HealthchecksSettings()
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default healthchecks.io settings")
    return settings


@healthchecks_bp.route('/save-key', methods=['POST'])
@require_auth
@require_permission('system.configure')
def save_api_key():
    """Save (or clear) the healthchecks.io account API key. Blank input leaves the existing key untouched."""
    try:
        settings = get_or_create_settings()
        api_key = (request.get_json(silent=True) or {}).get('api_key', '').strip()
        if api_key:
            settings.api_key = api_key
            db.session.commit()
            AuditLogger.log_config_change(
                resource_type='healthchecks_settings',
                resource_id=str(settings.id),
                details={'action': 'api_key_updated'},
            )
        return jsonify({'success': True, 'settings': settings.to_dict()})
    except SQLAlchemyError as e:
        logger.error(f"Database error saving healthchecks.io API key: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving API key'}), 500


@healthchecks_bp.route('/service-heartbeats/create-all', methods=['POST'])
@require_auth
@require_permission('system.configure')
def create_all_service_heartbeats():
    """Create one healthchecks.io check per selected critical service that doesn't already have one.

    "Critical" = app_core.config.get_eas_services() -- the 11 EAS
    subsystems plus the poller. Each gets its own named check (e.g.
    "EAS Station -- poller.service") so a missed ping identifies exactly
    which subsystem failed, rather than only "something is wrong" the way
    one aggregate heartbeat's alert would. No public URL needed -- these
    are outbound, pinged by the heartbeat worker only while the matching
    service is active.

    Body:
        service_names (list[str], optional): Which services to create
            checks for. Defaults to every not-yet-monitored EAS service
            if omitted -- but healthchecks.io's free plan caps the number
            of checks (20), so a caller close to that limit should pass an
            explicit subset rather than attempting all of them.
        interval_secs (int, optional): Ping interval (used as both the
            check's timeout and, floored at 300s, its grace period) for
            newly created checks. Default 300.

    Stops as soon as healthchecks.io reports the plan's check quota is
    reached (HTTP 403) rather than continuing to retry the same failure
    for every remaining service.
    """
    from app_core.config import get_eas_services
    from app_core.models import HealthchecksServiceHeartbeat

    settings = get_or_create_settings()
    if not settings.api_key:
        return jsonify({'success': False, 'error': 'Save a healthchecks.io API key first'}), 400

    data = request.get_json(silent=True) or {}
    interval_secs = int(data.get('interval_secs') or 300)
    requested = data.get('service_names')
    all_services = list(get_eas_services())
    # Build `wanted` by filtering the trusted service list against the
    # request, rather than filtering the request against the trusted list --
    # so every value ever assigned to `service_name` below is sourced from
    # get_eas_services(), never echoed straight from the request body. Same
    # result, but breaks the taint flow CodeQL's log-injection check follows
    # from request.get_json() into the logger.error() call further down.
    if requested:
        requested_set = set(requested)
        wanted = [s for s in all_services if s in requested_set]
    else:
        wanted = all_services

    existing = {row.service_name for row in HealthchecksServiceHeartbeat.query.all()}
    created, errors = [], []
    quota_reached = False

    for service_name in wanted:
        if service_name in existing:
            continue
        try:
            check = healthchecks_client.create_check(
                settings.api_key, name=f'EAS Station -- {service_name}',
                timeout_secs=interval_secs, grace_secs=max(interval_secs, 300),
                tags='eas-station',
            )
        except healthchecks_client.HealthchecksAPIError as e:
            logger.error(f"healthchecks.io create_check failed for {service_name}: {e}")
            errors.append(f'{service_name}: {_safe_api_error_message(e)}')
            if e.status_code == 403:
                quota_reached = True
                break
            continue

        row = HealthchecksServiceHeartbeat(
            service_name=service_name,
            check_uuid=check.get('uuid'),
            ping_url=check.get('ping_url'),
            interval_secs=check.get('timeout') or interval_secs,
            status=check.get('status'),
            enabled=True,
        )
        db.session.add(row)
        created.append(service_name)

    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='healthchecks_service_heartbeats',
        resource_id='bulk',
        details={'action': 'created', 'services': created, 'errors': errors, 'quota_reached': quota_reached},
    )
    return jsonify({
        'success': not errors or bool(created),
        'created': created,
        'errors': errors,
        'quota_reached': quota_reached,
        'heartbeats': [row.to_dict() for row in HealthchecksServiceHeartbeat.query.order_by(
            HealthchecksServiceHeartbeat.service_name).all()],
    })


@healthchecks_bp.route('/service-heartbeats', methods=['GET'])
@require_auth
@require_permission('system.view_config')
def list_service_heartbeats():
    from app_core.models import HealthchecksServiceHeartbeat
    rows = HealthchecksServiceHeartbeat.query.order_by(HealthchecksServiceHeartbeat.service_name).all()
    return jsonify({'success': True, 'heartbeats': [row.to_dict() for row in rows]})


def _find_service_heartbeat(heartbeat_row_id: int):
    from app_core.models import HealthchecksServiceHeartbeat
    return HealthchecksServiceHeartbeat.query.get(heartbeat_row_id)


def _service_heartbeat_status_action(heartbeat_row_id: int, action_fn, new_status: str, audit_action: str):
    settings = HealthchecksSettings.query.first()
    row = _find_service_heartbeat(heartbeat_row_id)
    if not settings or not settings.api_key or not row:
        return jsonify({'success': False, 'error': 'No such service heartbeat'}), 404
    try:
        action_fn(settings.api_key, row.check_uuid)
    except healthchecks_client.HealthchecksAPIError as e:
        logger.error(f"healthchecks.io {audit_action} failed for {row.service_name}: {e}")
        row.last_ping_error = _safe_api_error_message(e)
        db.session.commit()
        return jsonify({'success': False, 'error': _safe_api_error_message(e)}), 502

    row.status = new_status
    row.enabled = (new_status != 'paused')
    row.last_ping_error = None
    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='healthchecks_service_heartbeats',
        resource_id=str(row.id),
        details={'action': audit_action, 'service_name': row.service_name},
    )
    return jsonify({'success': True, 'heartbeat': row.to_dict()})


@healthchecks_bp.route('/service-heartbeats/<int:heartbeat_row_id>/pause', methods=['POST'])
@require_auth
@require_permission('system.configure')
def pause_service_heartbeat(heartbeat_row_id):
    return _service_heartbeat_status_action(
        heartbeat_row_id, healthchecks_client.pause_check, 'paused', 'service_heartbeat_paused')


@healthchecks_bp.route('/service-heartbeats/<int:heartbeat_row_id>/resume', methods=['POST'])
@require_auth
@require_permission('system.configure')
def resume_service_heartbeat(heartbeat_row_id):
    return _service_heartbeat_status_action(
        heartbeat_row_id, healthchecks_client.resume_check, 'new', 'service_heartbeat_resumed')


@healthchecks_bp.route('/service-heartbeats/<int:heartbeat_row_id>/delete', methods=['POST'])
@require_auth
@require_permission('system.configure')
def delete_service_heartbeat(heartbeat_row_id):
    """Delete one per-service heartbeat, both on healthchecks.io and locally."""
    settings = HealthchecksSettings.query.first()
    row = _find_service_heartbeat(heartbeat_row_id)
    if not row:
        return jsonify({'success': False, 'error': 'No such service heartbeat'}), 404

    if settings and settings.api_key:
        try:
            healthchecks_client.delete_check(settings.api_key, row.check_uuid)
        except healthchecks_client.HealthchecksAPIError as e:
            logger.error(f"healthchecks.io delete_check failed for {row.service_name}: {e}")
            return jsonify({'success': False, 'error': _safe_api_error_message(e)}), 502

    service_name = row.service_name
    db.session.delete(row)
    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='healthchecks_service_heartbeats',
        resource_id=str(heartbeat_row_id),
        details={'action': 'service_heartbeat_deleted', 'service_name': service_name},
    )
    return jsonify({'success': True})
