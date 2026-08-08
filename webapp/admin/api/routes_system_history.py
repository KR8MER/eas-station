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

"""``/api/system_health/history`` — persisted samples for the trend charts.

The cache key is computed from the query string by
``_system_health_history_cache_key`` so each range gets its own entry;
a static ``key_prefix`` would collapse every range onto one.
"""

from flask import jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app_core.cache import cache
from app_core.extensions import db
from app_utils import utc_now

from .blueprint import api_bp


_HISTORY_RANGE_HOURS = {
    '1h': 1,
    '6h': 6,
    '12h': 12,
    '24h': 24,
    '3d': 72,
    '7d': 168,
    '30d': 720,
}

def _system_health_history_cache_key():
    return f"system_health_history:{request.query_string.decode('utf-8')}"

@api_bp.route('/api/system_health/history')
@cache.cached(timeout=15, key_prefix=_system_health_history_cache_key)
def api_system_health_history():
    """Return persisted system-health samples for sparklines and trend chart.

    Query parameters:
    - range: time window — one of 1h, 6h, 12h, 24h, 3d, 7d, 30d (default 24h)
    - points: max number of points to return (default 300, capped at 2000).
      The series is uniformly downsampled to at most this many points so
      the front-end can render long windows without shipping every raw row.
    """
    from datetime import timedelta as _td

    from app_core.analytics.models import SystemMetricSample

    range_key = (request.args.get('range') or '24h').lower()
    hours = _HISTORY_RANGE_HOURS.get(range_key, 24)

    try:
        max_points = int(request.args.get('points', 300))
    except (TypeError, ValueError):
        max_points = 300
    max_points = max(10, min(max_points, 2000))

    cutoff = utc_now() - _td(hours=hours)

    try:
        rows = (
            SystemMetricSample.query
            .filter(SystemMetricSample.recorded_at >= cutoff)
            .order_by(SystemMetricSample.recorded_at.asc())
            .all()
        )
    except SQLAlchemyError as exc:
        api_bp.logger.error('Failed to load system metric samples: %s', exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'error': 'Failed to load history'}), 500

    # Uniform downsampling — pick every Nth row so a 30-day @ 30s window
    # (~86k rows) collapses to a chart-friendly 300 points.
    total = len(rows)
    if total > max_points:
        step = total / max_points
        sampled = [rows[int(i * step)] for i in range(max_points)]
        # Always include the most recent row so the live tail lines up.
        if sampled[-1] is not rows[-1]:
            sampled.append(rows[-1])
        rows = sampled

    series = {
        'timestamps': [],
        'cpu': [],
        'memory': [],
        'swap': [],
        'load_1m': [],
        'load_5m': [],
        'load_15m': [],
        'storage': [],
        'temperature': [],
        'net_rx_bytes': [],
        'net_tx_bytes': [],
    }
    for row in rows:
        series['timestamps'].append(row.recorded_at.isoformat() if row.recorded_at else None)
        series['cpu'].append(row.cpu_percent)
        series['memory'].append(row.memory_percent)
        series['swap'].append(row.swap_percent)
        series['load_1m'].append(row.load_1m)
        series['load_5m'].append(row.load_5m)
        series['load_15m'].append(row.load_15m)
        series['storage'].append(row.storage_percent)
        series['temperature'].append(row.temperature_c)
        series['net_rx_bytes'].append(row.net_rx_bytes)
        series['net_tx_bytes'].append(row.net_tx_bytes)

    return jsonify({
        'range': range_key,
        'hours': hours,
        'count': len(rows),
        'total_raw_samples': total,
        'series': series,
    })
