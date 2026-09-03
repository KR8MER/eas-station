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
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.models import TickstemSettings
from app_core.auth.decorators import require_auth
from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger
from app_core import tickstem_client
from app_utils import utc_now

logger = logging.getLogger(__name__)

tickstem_bp = Blueprint('tickstem', __name__, url_prefix='/admin/tickstem')


def _get_or_create_settings() -> TickstemSettings:
    settings = TickstemSettings.query.first()
    if not settings:
        settings = TickstemSettings(monitor_name='', monitor_url='', interval_secs=60, timeout_secs=10)
        db.session.add(settings)
        db.session.commit()
        logger.info("Created default Tickstem settings")
    return settings


@tickstem_bp.route('/', methods=['GET'])
@require_auth
@require_permission('system.configure')
def tickstem_settings():
    """Display Tickstem uptime-monitor configuration page."""
    from app_core.config import get_eas_services
    from app_core.models import TickstemServiceHeartbeat

    try:
        settings = _get_or_create_settings()
        default_health_url = request.url_root.rstrip('/') + '/health'
        service_heartbeats = TickstemServiceHeartbeat.query.order_by(TickstemServiceHeartbeat.service_name).all()
        unmonitored_services = [
            s for s in get_eas_services() if s not in {row.service_name for row in service_heartbeats}
        ]
        return render_template(
            'admin/tickstem.html', settings=settings, default_health_url=default_health_url,
            service_heartbeats=service_heartbeats, unmonitored_services=unmonitored_services,
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error loading Tickstem settings: {str(e)}")
        db.session.rollback()
        return render_template(
            'admin/tickstem.html', settings=None, default_health_url='',
            service_heartbeats=[], unmonitored_services=[],
        )


@tickstem_bp.route('/save-key', methods=['POST'])
@require_auth
@require_permission('system.configure')
def save_api_key():
    """Save (or clear) the Tickstem account API key. Blank input leaves the existing key untouched."""
    try:
        settings = _get_or_create_settings()
        api_key = (request.get_json(silent=True) or {}).get('api_key', '').strip()
        if api_key:
            settings.api_key = api_key
            db.session.commit()
            AuditLogger.log_config_change(
                resource_type='tickstem_settings',
                resource_id=str(settings.id),
                details={'action': 'api_key_updated'},
            )
        return jsonify({'success': True, 'settings': settings.to_dict()})
    except SQLAlchemyError as e:
        logger.error(f"Database error saving Tickstem API key: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Database error saving API key'}), 500


@tickstem_bp.route('/create-monitor', methods=['POST'])
@require_auth
@require_permission('system.configure')
def create_monitor():
    """Create the Tickstem uptime monitor using the saved API key."""
    settings = TickstemSettings.query.first()
    if not settings or not settings.api_key:
        return jsonify({'success': False, 'error': 'Save a Tickstem API key first'}), 400
    if settings.monitor_id:
        return jsonify({'success': False, 'error': 'A monitor already exists -- delete it first to recreate'}), 400

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip() or 'EAS Station'
    url = (data.get('url') or '').strip()
    interval_secs = int(data.get('interval_secs') or 60)
    timeout_secs = int(data.get('timeout_secs') or 10)

    if not url.startswith('https://'):
        return jsonify({'success': False, 'error': 'Monitor URL must be a public https:// address'}), 400

    try:
        monitor = tickstem_client.create_monitor(
            settings.api_key, name=name, url=url,
            interval_secs=interval_secs, timeout_secs=timeout_secs,
        )
    except tickstem_client.TickstemAPIError as e:
        logger.error(f"Tickstem create_monitor failed: {e}")
        settings.last_sync_error = str(e)
        db.session.commit()
        return jsonify({'success': False, 'error': str(e)}), 502

    settings.monitor_id = monitor.get('id')
    settings.monitor_name = monitor.get('name', name)
    settings.monitor_url = monitor.get('url', url)
    settings.interval_secs = monitor.get('interval_secs', interval_secs)
    settings.timeout_secs = monitor.get('timeout_secs', timeout_secs)
    settings.monitor_status = monitor.get('status')
    settings.last_synced_at = utc_now()
    settings.last_sync_error = None
    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='tickstem_settings',
        resource_id=str(settings.id),
        details={'action': 'monitor_created', 'monitor_id': settings.monitor_id, 'url': settings.monitor_url},
    )

    return jsonify({'success': True, 'settings': settings.to_dict()})


def _monitor_action(action_fn, audit_action: str):
    settings = TickstemSettings.query.first()
    if not settings or not settings.api_key or not settings.monitor_id:
        return jsonify({'success': False, 'error': 'No Tickstem monitor configured'}), 400
    try:
        action_fn(settings.api_key, settings.monitor_id)
    except tickstem_client.TickstemAPIError as e:
        logger.error(f"Tickstem {audit_action} failed: {e}")
        settings.last_sync_error = str(e)
        db.session.commit()
        return jsonify({'success': False, 'error': str(e)}), 502

    settings.last_synced_at = utc_now()
    settings.last_sync_error = None
    if audit_action == 'monitor_paused':
        settings.monitor_status = 'paused'
    elif audit_action == 'monitor_resumed':
        settings.monitor_status = 'active'
    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='tickstem_settings',
        resource_id=str(settings.id),
        details={'action': audit_action, 'monitor_id': settings.monitor_id},
    )
    return jsonify({'success': True, 'settings': settings.to_dict()})


@tickstem_bp.route('/pause', methods=['POST'])
@require_auth
@require_permission('system.configure')
def pause_monitor():
    return _monitor_action(tickstem_client.pause_monitor, 'monitor_paused')


@tickstem_bp.route('/resume', methods=['POST'])
@require_auth
@require_permission('system.configure')
def resume_monitor():
    return _monitor_action(tickstem_client.resume_monitor, 'monitor_resumed')


@tickstem_bp.route('/delete', methods=['POST'])
@require_auth
@require_permission('system.configure')
def delete_monitor():
    settings = TickstemSettings.query.first()
    if not settings or not settings.monitor_id:
        return jsonify({'success': False, 'error': 'No Tickstem monitor configured'}), 400

    if settings.api_key:
        try:
            tickstem_client.delete_monitor(settings.api_key, settings.monitor_id)
        except tickstem_client.TickstemAPIError as e:
            logger.error(f"Tickstem delete_monitor failed: {e}")
            return jsonify({'success': False, 'error': str(e)}), 502

    deleted_id = settings.monitor_id
    settings.monitor_id = None
    settings.monitor_status = None
    settings.last_synced_at = utc_now()
    settings.last_sync_error = None
    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='tickstem_settings',
        resource_id=str(settings.id),
        details={'action': 'monitor_deleted', 'monitor_id': deleted_id},
    )
    return jsonify({'success': True, 'settings': settings.to_dict()})


@tickstem_bp.route('/service-heartbeats/create-all', methods=['POST'])
@require_auth
@require_permission('system.configure')
def create_all_service_heartbeats():
    """Create one Tickstem heartbeat per selected critical service that doesn't already have one.

    "Critical" = app_core.config.get_eas_services() -- the 11 EAS
    subsystems plus the poller. Each gets its own named heartbeat (e.g.
    "EAS Station -- poller.service") so a missed ping identifies exactly
    which subsystem failed, rather than only "something is wrong" the way
    one aggregate heartbeat's alert would. No public URL needed -- these
    are outbound, pinged by the heartbeat worker only while the matching
    service is active.

    Body:
        service_names (list[str], optional): Which services to create
            heartbeats for. Defaults to every not-yet-monitored EAS service
            if omitted -- but Tickstem plans cap the number of heartbeats
            (free tier: 5), so a caller close to that limit should pass an
            explicit subset rather than attempting all of them.
        interval_secs (int, optional): Ping interval for newly created
            heartbeats. Default 300.

    Stops as soon as Tickstem reports the plan's heartbeat quota is
    reached (HTTP 402) rather than continuing to retry the same failure
    for every remaining service.
    """
    from app_core.config import get_eas_services
    from app_core.models import TickstemServiceHeartbeat

    settings = _get_or_create_settings()
    if not settings.api_key:
        return jsonify({'success': False, 'error': 'Save a Tickstem API key first'}), 400

    data = request.get_json(silent=True) or {}
    interval_secs = int(data.get('interval_secs') or 300)
    requested = data.get('service_names')
    valid_services = set(get_eas_services())
    wanted = [s for s in requested if s in valid_services] if requested else list(get_eas_services())

    existing = {row.service_name for row in TickstemServiceHeartbeat.query.all()}
    created, errors = [], []
    quota_reached = False

    for service_name in wanted:
        if service_name in existing:
            continue
        try:
            heartbeat = tickstem_client.create_heartbeat(
                settings.api_key, name=f'EAS Station -- {service_name}',
                interval_secs=interval_secs, grace_secs=max(interval_secs, 300),
            )
        except tickstem_client.TickstemAPIError as e:
            logger.error(f"Tickstem create_heartbeat failed for {service_name}: {e}")
            errors.append(f'{service_name}: {e}')
            if e.status_code == 402:
                quota_reached = True
                break
            continue

        token = heartbeat.get('token', '')
        row = TickstemServiceHeartbeat(
            service_name=service_name,
            heartbeat_id=heartbeat.get('id'),
            ping_url=f'https://api.tickstem.dev/v1/heartbeats/{token}/ping',
            interval_secs=heartbeat.get('interval_secs', interval_secs),
            status=heartbeat.get('status'),
            enabled=True,
        )
        db.session.add(row)
        created.append(service_name)

    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='tickstem_service_heartbeats',
        resource_id='bulk',
        details={'action': 'created', 'services': created, 'errors': errors, 'quota_reached': quota_reached},
    )
    return jsonify({
        'success': not errors or bool(created),
        'created': created,
        'errors': errors,
        'quota_reached': quota_reached,
        'heartbeats': [row.to_dict() for row in TickstemServiceHeartbeat.query.order_by(
            TickstemServiceHeartbeat.service_name).all()],
    })


@tickstem_bp.route('/service-heartbeats', methods=['GET'])
@require_auth
@require_permission('system.view_config')
def list_service_heartbeats():
    from app_core.models import TickstemServiceHeartbeat
    rows = TickstemServiceHeartbeat.query.order_by(TickstemServiceHeartbeat.service_name).all()
    return jsonify({'success': True, 'heartbeats': [row.to_dict() for row in rows]})


def _find_service_heartbeat(heartbeat_row_id: int):
    from app_core.models import TickstemServiceHeartbeat
    return TickstemServiceHeartbeat.query.get(heartbeat_row_id)


def _service_heartbeat_status_action(heartbeat_row_id: int, status: str, audit_action: str):
    settings = TickstemSettings.query.first()
    row = _find_service_heartbeat(heartbeat_row_id)
    if not settings or not settings.api_key or not row:
        return jsonify({'success': False, 'error': 'No such service heartbeat'}), 404
    try:
        tickstem_client.set_heartbeat_status(settings.api_key, row.heartbeat_id, status)
    except tickstem_client.TickstemAPIError as e:
        logger.error(f"Tickstem {audit_action} failed for {row.service_name}: {e}")
        row.last_ping_error = str(e)
        db.session.commit()
        return jsonify({'success': False, 'error': str(e)}), 502

    row.status = status
    row.enabled = (status == 'active')
    row.last_ping_error = None
    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='tickstem_service_heartbeats',
        resource_id=str(row.id),
        details={'action': audit_action, 'service_name': row.service_name},
    )
    return jsonify({'success': True, 'heartbeat': row.to_dict()})


@tickstem_bp.route('/service-heartbeats/<int:heartbeat_row_id>/pause', methods=['POST'])
@require_auth
@require_permission('system.configure')
def pause_service_heartbeat(heartbeat_row_id):
    return _service_heartbeat_status_action(heartbeat_row_id, 'paused', 'service_heartbeat_paused')


@tickstem_bp.route('/service-heartbeats/<int:heartbeat_row_id>/resume', methods=['POST'])
@require_auth
@require_permission('system.configure')
def resume_service_heartbeat(heartbeat_row_id):
    return _service_heartbeat_status_action(heartbeat_row_id, 'active', 'service_heartbeat_resumed')


@tickstem_bp.route('/service-heartbeats/<int:heartbeat_row_id>/delete', methods=['POST'])
@require_auth
@require_permission('system.configure')
def delete_service_heartbeat(heartbeat_row_id):
    """Delete one per-service heartbeat, both on Tickstem and locally."""
    settings = TickstemSettings.query.first()
    row = _find_service_heartbeat(heartbeat_row_id)
    if not row:
        return jsonify({'success': False, 'error': 'No such service heartbeat'}), 404

    if settings and settings.api_key:
        try:
            tickstem_client.delete_heartbeat(settings.api_key, row.heartbeat_id)
        except tickstem_client.TickstemAPIError as e:
            logger.error(f"Tickstem delete_heartbeat failed for {row.service_name}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 502

    service_name = row.service_name
    db.session.delete(row)
    db.session.commit()

    AuditLogger.log_config_change(
        resource_type='tickstem_service_heartbeats',
        resource_id=str(heartbeat_row_id),
        details={'action': 'service_heartbeat_deleted', 'service_name': service_name},
    )
    return jsonify({'success': True})


@tickstem_bp.route('/checks', methods=['GET'])
@require_auth
@require_permission('system.view_config')
def recent_checks():
    """Fetch the monitor's recent check history from Tickstem (proxied so the API key never reaches the browser)."""
    settings = TickstemSettings.query.first()
    if not settings or not settings.api_key or not settings.monitor_id:
        return jsonify({'success': False, 'error': 'No Tickstem monitor configured'}), 400
    try:
        checks = tickstem_client.get_checks(settings.api_key, settings.monitor_id, limit=20)
    except tickstem_client.TickstemAPIError as e:
        logger.error(f"Tickstem get_checks failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 502
    return jsonify({'success': True, 'checks': checks})
