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

from __future__ import annotations

"""Flask blueprint for ``/api/hardware/gps/*`` endpoints.

Status, trends-archive read-out, and configuration-save (which also
restarts the GPS manager) live here.  The GPS manager and Redis client
are owned by the orchestrator, so the factory takes getters/callbacks
rather than instances directly.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import redis
from flask import Blueprint, jsonify, request

from services.gps.events import read_events
from services.gps.trends import (
    GPS_TRENDS_DEFAULT_WINDOW,
    GPS_TRENDS_TIERS,
    GPS_TRENDS_WINDOW_TO_TIER,
    redis_key_for_tier,
)

logger = logging.getLogger(__name__)


def create_blueprint(
    *,
    get_gps_manager: Callable[[], Optional[Any]],
    get_redis_client: Callable[[], Optional[redis.Redis]],
    restart_gps_manager: Callable[[bool], None],
) -> Blueprint:
    """Build and return the ``/api/hardware/gps/*`` blueprint.

    Parameters
    ----------
    get_gps_manager:
        Returns the orchestrator-owned ``GPSManager`` (or ``None``).
    get_redis_client:
        Returns the live Redis client (or ``None`` if not yet connected).
    restart_gps_manager:
        Called by ``/configure``; receives the desired ``enabled`` flag
        and is expected to stop any running manager and start a new one
        (inside the orchestrator's Flask app context) when ``enabled``.
    """
    bp = Blueprint("gps_api", __name__)

    @bp.route('/api/hardware/gps/status', methods=['GET'])
    def get_gps_status():
        """Return current GPS fix status from the GPS manager or Redis."""
        try:
            # Try live status from running manager first
            _gps_manager = get_gps_manager()
            if _gps_manager is not None:
                return jsonify(_gps_manager.get_status())

            # Fall back to last-known status from Redis
            _redis_client = get_redis_client()
            if _redis_client:
                try:
                    raw = _redis_client.get('gps:status')
                    if raw:
                        return jsonify(json.loads(raw))
                except Exception:
                    pass

            # GPS not configured or not started
            from app_core.hardware_settings import get_gps_settings
            gps_settings = get_gps_settings()
            return jsonify({
                'running': False,
                'has_fix': False,
                'status': 'disabled' if not gps_settings.get('enabled') else 'not_started',
                'serial_port': gps_settings.get('serial_port', '/dev/serial0'),
                'baudrate': gps_settings.get('baudrate', 9600),
                'pps_gpio_pin': gps_settings.get('pps_gpio_pin', 18),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error(f"Error getting GPS status: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/hardware/gps/trends', methods=['GET'])
    def get_gps_trends():
        """Return the server-side ring buffer of GPS / chrony trend samples.

        Accepts a ``?window=`` query parameter that selects which
        resolution tier to return.  Each tier is sized so the dashboard
        gets ~1000–2200 samples regardless of window — what changes is
        the time-resolution of each sample, not the sample count:

            window  →  tier   bucket    span
            -------    -----  --------  -------
            1h         raw    5 s       ≈ 1.1 h   (live tail)
            6h, 24h    1m     1 min     ≈ 25 h
            7d         10m    10 min    ≈ 7.6 d
            30d, 90d   1h     1 h       ≈ 91 d

        Unknown / missing windows fall back to ``raw`` for backward
        compatibility with the old single-tier client.
        """
        window = (request.args.get("window") or GPS_TRENDS_DEFAULT_WINDOW).lower()
        tier = GPS_TRENDS_WINDOW_TO_TIER.get(window, "raw")
        bucket_s, cap = GPS_TRENDS_TIERS.get(tier, GPS_TRENDS_TIERS["raw"])

        try:
            samples: list = []
            _redis_client = get_redis_client()
            if _redis_client:
                try:
                    raw_items = _redis_client.lrange(
                        redis_key_for_tier(tier), 0, cap - 1
                    ) or []
                except Exception as exc:
                    logger.debug("GPS trends: lrange failed: %s", exc)
                    raw_items = []
                # Stored newest-first, reverse for chronological output.
                for raw in reversed(raw_items):
                    try:
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="replace")
                        samples.append(json.loads(raw))
                    except Exception as exc:
                        # Skip malformed rows so one bad entry can't
                        # poison the whole chart, but log at debug so an
                        # operator can spot systematic corruption.
                        logger.debug("GPS trends: skipping malformed row: %s", exc)
                        continue
            return jsonify({
                'samples': samples,
                'tier': tier,
                'window': window,
                'bucket_seconds': bucket_s,
                'capacity': cap,
            })
        except Exception:
            # Log full detail server-side; return a generic message to
            # the client so we don't leak internal paths / library
            # exception text (CodeQL py/stack-trace-exposure).
            logger.error("Error getting GPS trends", exc_info=True)
            return jsonify({'success': False, 'error': 'gps_trends_unavailable'}), 500

    @bp.route('/api/hardware/gps/events', methods=['GET'])
    def get_gps_events():
        """Return the recent state-change events for the GPS dashboard.

        Events are produced by the subprocess-side detector on each
        trend tick and persisted in a capped Redis list (newest first).
        The dashboard hydrates from this on page load so alarms survive
        navigation away and reload.

        Optional ``?limit=N`` clamps how many to return (default 200,
        max 500).
        """
        try:
            _redis_client = get_redis_client()
            events = read_events(_redis_client, limit=request.args.get('limit', 200))
            return jsonify({'events': events})
        except Exception:
            logger.error("Error getting GPS events", exc_info=True)
            return jsonify({'success': False, 'error': 'gps_events_unavailable'}), 500

    @bp.route('/api/hardware/gps/configure', methods=['POST'])
    def configure_gps():
        """Save GPS configuration and restart the GPS manager."""
        try:
            data = request.json or {}

            from app_core.hardware_settings import get_hardware_settings, update_hardware_settings

            settings = get_hardware_settings()
            update_fields = {}

            if 'enabled' in data:
                update_fields['gps_enabled'] = bool(data['enabled'])
            if 'serial_port' in data:
                update_fields['gps_serial_port'] = str(data['serial_port'])
            if 'baudrate' in data:
                update_fields['gps_baudrate'] = int(data['baudrate'])
            if 'pps_gpio_pin' in data:
                update_fields['gps_pps_gpio_pin'] = int(data['pps_gpio_pin'])
            if 'use_for_location' in data:
                update_fields['gps_use_for_location'] = bool(data['use_for_location'])
            if 'use_for_time' in data:
                update_fields['gps_use_for_time'] = bool(data['use_for_time'])
            if 'min_satellites' in data:
                update_fields['gps_min_satellites'] = max(1, int(data['min_satellites']))

            if update_fields:
                update_hardware_settings(update_fields)

            # Restart GPS manager with new settings — the orchestrator
            # owns the manager lifetime (Flask-app-context, module-level
            # global) so we delegate to it rather than reaching across
            # the blueprint boundary.
            enabled = bool(update_fields.get('gps_enabled', settings.gps_enabled))
            restart_gps_manager(enabled)

            return jsonify({'success': True, 'message': 'GPS configuration saved'})

        except Exception as e:
            logger.error(f"Error configuring GPS: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    return bp
