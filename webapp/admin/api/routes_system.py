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

"""``/api/system_status`` and ``/api/system_health`` — the live status feeds.

``api_system_status`` is the dashboard's heartbeat: database reachability,
alert and poll counts, host CPU/memory/disk and uptime, assembled defensively
so that one failing collector cannot take the whole payload down. Its database
block catches ``SQLAlchemyError`` specifically and rolls the session back —
pinned by ``tests/test_api_field_fixes.py``.
"""

import socket

import psutil
from flask import jsonify
from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError

from app_core.cache import cache
from app_core.extensions import db
from app_core.models import Boundary, PollHistory
from app_core.system_health import get_system_health
from app_utils import (
    UTC_TZ,
    format_uptime,
    get_location_timezone,
    get_location_timezone_name,
    local_now,
    utc_now,
)
from app_core.alerts import get_active_alerts_query

from .blueprint import api_bp
from .hostinfo import _get_cpu_usage_percent, _get_primary_ip_address


@api_bp.route('/api/system_status')
@cache.cached(timeout=10, key_prefix='system_status')
def api_system_status():
    """Get system status information using new helper functions with timezone support"""
    try:
        # Collect system metrics first (these don't require database)
        cpu = _get_cpu_usage_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        current_utc = utc_now()
        current_local = local_now()
        hostname = socket.gethostname()
        ip_address = _get_primary_ip_address()
        uptime_seconds = max(current_utc.timestamp() - psutil.boot_time(), 0.0)

        # Location settings (county/state) for display screens
        county_name = ''
        state_code = ''
        try:
            from app_core.location import get_location_settings
            loc = get_location_settings()
            county_name = loc.get('county_name', '') or ''
            state_code = loc.get('state_code', '') or ''
        except Exception:
            pass

        status = 'healthy'
        status_reasons = []

        def _record_status(level: str, message: str) -> None:
            nonlocal status
            status_reasons.append({'level': level, 'message': message})
            if level == 'critical':
                status = 'critical'
            elif level == 'warning' and status != 'critical':
                status = 'warning'

        # Database queries with proper error handling
        total_boundaries = None
        active_alerts = None
        last_poll = None
        database_status = 'unknown'

        try:
            # Rollback any existing failed transaction before new queries.
            # This is a defensive measure to recover from "current transaction is
            # aborted" errors in PostgreSQL. We silently ignore rollback failures
            # because the session may not have an active transaction, which is fine.
            try:
                db.session.rollback()
            except SQLAlchemyError:
                pass  # No active transaction to rollback, which is expected

            total_boundaries = Boundary.query.count()
            active_alerts = get_active_alerts_query().count()
            last_poll = PollHistory.query.order_by(desc(PollHistory.timestamp)).first()
            database_status = 'connected'
        except SQLAlchemyError as db_exc:
            api_bp.logger.warning('Database error in system_status: %s', db_exc)
            database_status = 'error'
            _record_status(
                'critical',
                f'Database connection error: {str(db_exc)[:100]}'
            )
            # Try to rollback to recover the session for subsequent requests.
            # Rollback failure here is logged at debug level since the session
            # may already be in an unusable state.
            try:
                db.session.rollback()
            except SQLAlchemyError as rollback_exc:
                api_bp.logger.debug('Rollback after DB error also failed: %s', rollback_exc)

        if cpu >= 90:
            _record_status(
                'critical',
                f'CPU usage is {cpu:.1f}%, exceeding the 90% critical threshold.',
            )
        elif cpu >= 75:
            _record_status(
                'warning',
                f'CPU usage is {cpu:.1f}%, above the 75% warning threshold.',
            )

        if memory.percent >= 92:
            _record_status(
                'critical',
                (
                    'Memory usage is '
                    f'{memory.percent:.1f}%, exceeding the 92% critical threshold.'
                ),
            )
        elif memory.percent >= 80:
            _record_status(
                'warning',
                (
                    'Memory usage is '
                    f'{memory.percent:.1f}%, above the 80% warning threshold.'
                ),
            )

        if disk.percent >= 95:
            _record_status(
                'critical',
                (
                    'Disk usage is '
                    f'{disk.percent:.1f}% on the root volume with '
                    f"{disk.free // (1024 * 1024 * 1024)} GB free, exceeding the "
                    '95% critical threshold.'
                ),
            )
        elif disk.percent >= 85:
            _record_status(
                'warning',
                (
                    'Disk usage is '
                    f'{disk.percent:.1f}% on the root volume with '
                    f"{disk.free // (1024 * 1024 * 1024)} GB free, above the "
                    '85% warning threshold.'
                ),
            )

        poll_snapshot = None
        location_tz = get_location_timezone()
        if last_poll:
            poll_timestamp = last_poll.timestamp
            if poll_timestamp.tzinfo is None:
                poll_timestamp = poll_timestamp.replace(tzinfo=UTC_TZ)
            poll_age_minutes = (current_utc - poll_timestamp).total_seconds() / 60.0
            poll_local_time = poll_timestamp.astimezone(location_tz)
            poll_time_display = poll_local_time.strftime('%Y-%m-%d %H:%M %Z')
            if poll_age_minutes >= 60:
                _record_status(
                    'critical',
                    (
                        'Last poll ran '
                        f'{poll_age_minutes:.0f} minutes ago '
                        f'(local time {poll_time_display}).'
                    ),
                )
            elif poll_age_minutes >= 15:
                _record_status(
                    'warning',
                    (
                        'Last poll ran '
                        f'{poll_age_minutes:.0f} minutes ago '
                        f'(local time {poll_time_display}).'
                    ),
                )

            poll_status = (last_poll.status or '').strip().lower()
            if poll_status and poll_status not in {'success', 'ok', 'completed'}:
                level = 'critical' if poll_status in {'failed', 'error'} else 'warning'
                error_detail = (last_poll.error_message or '').strip()
                detail_suffix = f" Details: {error_detail}" if error_detail else ''
                _record_status(
                    level,
                    f"Last poll reported status '{last_poll.status}'.{detail_suffix}",
                )

            poll_snapshot = {
                'timestamp': poll_timestamp.isoformat(),
                'local_timestamp': poll_timestamp.astimezone(location_tz).isoformat(),
                'status': last_poll.status,
                'alerts_fetched': last_poll.alerts_fetched or 0,
                'alerts_new': last_poll.alerts_new or 0,
                'error_message': (last_poll.error_message or '').strip() or None,
                'data_source': last_poll.data_source,
            }
        elif database_status == 'connected':
            # Only record this warning if database is connected but no polls exist.
            # When database_status is 'error' or 'unknown', we already reported a
            # critical database error above, so we skip this warning to avoid confusion.
            _record_status(
                'warning',
                'No poll activity has been recorded yet; verify the poller service is '
                'running and configured.',
            )

        status_summary = 'All systems operational.'
        if status_reasons:
            summary_source = next(
                (reason for reason in status_reasons if reason['level'] == status),
                status_reasons[0],
            )
            status_summary = summary_source['message']

        return jsonify(
            {
                'status': status,
                'status_summary': status_summary,
                'status_reasons': status_reasons,
                'timestamp': current_utc.isoformat(),
                'local_timestamp': current_local.isoformat(),
                'timezone': get_location_timezone_name(),
                'hostname': hostname,
                'ip_address': ip_address,
                'county_name': county_name,
                'state_code': state_code,
                'boundaries_count': total_boundaries,
                'active_alerts_count': active_alerts,
                'database_status': database_status,
                'last_poll': poll_snapshot,
                'system_resources': {
                    'cpu_usage_percent': cpu,
                    'memory_usage_percent': memory.percent,
                    'disk_usage_percent': disk.percent,
                    'disk_free_gb': disk.free // (1024 * 1024 * 1024),
                },
                'uptime_seconds': uptime_seconds,
                'uptime_human': format_uptime(uptime_seconds),
            }
        )
    except Exception as exc:
        api_bp.logger.error('Error getting system status: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to get system status'}), 500


def build_gps_status_payload(redis_client) -> dict:
    """Flatten the `gps:status` Redis hash into the handful of fields a
    display template needs, plus a satellite-SNR array pre-sorted for a
    bar-chart style display.

    Pulled out of the route as a plain function (takes an already-resolved
    Redis client rather than looking one up itself) so it's testable
    without a Flask request/app context -- no DB touches a full
    `app.test_client()` call would otherwise trigger.
    """
    result = {
        'enabled': False,
        'has_fix': False,
        'fix_mode': None,
        'fix_quality': None,
        'latitude': None,
        'longitude': None,
        'altitude_m': None,
        'speed_knots': None,
        'track_angle': None,
        'satellites': 0,
        'satellites_in_view_count': 0,
        'hdop': None,
        'satellite_snrs': [],
        'fix_label': 'NO FIX',
        'fix_summary': 'NO FIX 0/0',
    }
    try:
        if redis_client:
            raw = redis_client.get('gps:status')
            if raw:
                import json
                data = json.loads(raw)
                result['enabled'] = True
                result['has_fix'] = bool(data.get('has_fix'))
                result['fix_mode'] = data.get('fix_mode')
                result['fix_quality'] = data.get('fix_quality')
                result['latitude'] = data.get('latitude')
                result['longitude'] = data.get('longitude')
                result['altitude_m'] = data.get('altitude_m')
                result['speed_knots'] = data.get('speed_knots')
                result['track_angle'] = data.get('track_angle')
                result['satellites'] = data.get('satellites', 0) or 0
                result['hdop'] = data.get('hdop')

                sats_in_view = data.get('satellites_in_view') or []
                result['satellites_in_view_count'] = len(sats_in_view)
                snrs = sorted(
                    (
                        s.get('snr') for s in sats_in_view
                        if isinstance(s, dict) and isinstance(s.get('snr'), (int, float))
                    ),
                    reverse=True,
                )
                result['satellite_snrs'] = [round(v) for v in snrs[:8]]

                # Pre-formatted labels for display templates -- the OLED/LED/VFD
                # template engine only does variable substitution, not
                # conditionals, so the fix-mode -> label mapping happens here
                # (same idiom as api_system_status's status_summary field).
                fix_mode = result['fix_mode']
                if fix_mode == 3:
                    result['fix_label'] = '3D FIX'
                elif fix_mode == 2:
                    result['fix_label'] = '2D FIX'
                else:
                    result['fix_label'] = 'NO FIX'
                result['fix_summary'] = (
                    f"{result['fix_label']} {result['satellites']}/{result['satellites_in_view_count']}"
                )
    except Exception as exc:
        api_bp.logger.debug('gps_status: failed to read gps:status from Redis: %s', exc)

    return result


@api_bp.route('/api/gps_status')
@cache.cached(timeout=3, key_prefix='gps_status')
def api_gps_status():
    """GPS fix status for hardware displays (the GPS OLED screen) and dashboards.

    Reads the `gps:status` Redis key published by GPSManager -- the same
    source the GPS admin dashboard uses. Unauthenticated like
    /api/system_status, since DisplayScreen data_sources are fetched with
    a plain requests.get() and carry no session.
    """
    from app_core.redis_client import get_redis_client
    redis_client = get_redis_client(max_retries=1)
    return jsonify(build_gps_status_payload(redis_client))


@api_bp.route('/api/system_health')
@cache.cached(timeout=10, key_prefix='system_health')
def api_system_health():
    """Get comprehensive system health information via API"""
    try:
        health_data = get_system_health()
        return jsonify(health_data)
    except Exception as exc:
        api_bp.logger.error('Error getting system health via API: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to get system health'}), 500
