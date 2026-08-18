from __future__ import annotations
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

"""Dead-air (silence) detection policy, and the live alarm state.

These endpoints own the *detection* half of dead-air monitoring: what
counts as silence on a monitored source, and whether a source is silent
right now. They live under the audio blueprint because every threshold
here is an audio quantity -- dBFS, spectral flatness, a hold-off in
seconds -- and because detection must not live inside any one of its
consumers.

The *output* half (which GPIO pin sounds the rack buzzer, what colour the
tower light shows) stays in hardware settings, where the rest of the
physical wiring is configured. That split matters beyond tidiness: the
GPIO relay and the tower light are only today's outputs, and an email or
SMS notifier added later must be able to subscribe to the same detection
policy without it being buried in the GPIO page.

Storage is still ``HardwareSettings`` -- one settings row, no migration
needed to move a control between pages.
"""

import logging

from flask import jsonify, request

from app_core.auth.roles import (
    has_permission,
    require_any_permission,
    require_permission,
)

from .blueprint import audio_ingest_bp

logger = logging.getLogger(__name__)

#: Bounds applied to every write. A level threshold above roughly -30 dBFS
#: would alarm on normal programme audio, and a flatness threshold at zero
#: would alarm on everything, so neither is left to a hand-edited post.
_BOUNDS = {
    'dead_air_level_threshold_db': (-120, -30),
    'dead_air_flatness_threshold_pct': (1, 99),
    'dead_air_duration_seconds': (1, 3600),
}


def _detection_payload(settings) -> dict:
    """Shape the detection half of the settings row for the UI."""
    return {
        'enabled': bool(getattr(settings, 'dead_air_enabled', False)),
        'duration_seconds': int(
            getattr(settings, 'dead_air_duration_seconds', 20) or 20
        ),
        'level_threshold_db': int(
            getattr(settings, 'dead_air_level_threshold_db', -65) or -65
        ),
        'detect_open_carrier': bool(
            getattr(settings, 'dead_air_detect_open_carrier', True)
        ),
        'flatness_threshold_pct': int(
            getattr(settings, 'dead_air_flatness_threshold_pct', 25) or 25
        ),
    }


@audio_ingest_bp.route('/api/audio/dead-air/settings', methods=['GET'])
@require_permission('system.configure')
def audio_dead_air_settings_get():
    """Return the dead-air detection policy."""
    try:
        from app_core.hardware_settings import get_hardware_settings

        return jsonify({'ok': True, **_detection_payload(get_hardware_settings())})
    except Exception as exc:
        logger.exception("Dead-air settings read failed")
        return jsonify({'ok': False, 'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/dead-air/settings', methods=['POST'])
@require_permission('system.configure')
def audio_dead_air_settings_post():
    """Update the dead-air detection policy.

    Only the detection fields are writable here; the buzzer pin and the
    tower-light colour are deliberately not, so the two pages cannot
    fight over the same values.
    """
    try:
        from app_core.hardware_settings import update_hardware_settings

        payload = request.get_json(silent=True) or {}
        updates = {}

        if 'enabled' in payload:
            updates['dead_air_enabled'] = _as_bool(payload['enabled'])
        if 'detect_open_carrier' in payload:
            updates['dead_air_detect_open_carrier'] = _as_bool(
                payload['detect_open_carrier']
            )

        for key, column in (
            ('duration_seconds', 'dead_air_duration_seconds'),
            ('level_threshold_db', 'dead_air_level_threshold_db'),
            ('flatness_threshold_pct', 'dead_air_flatness_threshold_pct'),
        ):
            if key not in payload:
                continue
            low, high = _BOUNDS[column]
            try:
                updates[column] = max(low, min(high, int(payload[key])))
            except (TypeError, ValueError):
                return jsonify({
                    'ok': False,
                    'error': f"{key} must be a whole number between {low} and {high}",
                }), 400

        if not updates:
            return jsonify({'ok': False, 'error': 'No settings supplied'}), 400

        settings = update_hardware_settings(updates)
        logger.info("Dead-air detection policy updated: %s", sorted(updates))
        return jsonify({'ok': True, **_detection_payload(settings)})
    except Exception as exc:
        logger.exception("Dead-air settings write failed")
        return jsonify({'ok': False, 'error': str(exc)}), 500


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ('true', '1', 'yes', 'on')
    return bool(value)


@audio_ingest_bp.route('/api/audio/dead-air/status', methods=['GET'])
@require_any_permission('alerts.view', 'receivers.view', 'logs.view',
                        'system.configure')
def audio_dead_air_status():
    """Report whether any monitored source is currently silent.

    Authorized at the same level as the Audio Health dashboard that renders
    it, which the navigation registry gates on the *view* role trio
    (``alerts.view`` / ``receivers.view`` / ``logs.view``). Requiring
    ``system.configure`` here instead meant a radio watcher could open the
    dashboard while every status poll 403'd -- so an active dead-air alarm
    was silently invisible to exactly the people meant to watch for it.

    Acknowledging stays restricted to ``system.configure``; the response
    carries ``can_acknowledge`` so the UI can hide the control rather than
    offering a button that will fail.
    """
    try:
        import json as _json

        from app_core.config.redis_config import RedisChannels
        from app_core.redis_client import get_redis_client

        client = get_redis_client()
        if client is None:
            return jsonify({'ok': False, 'error': 'Redis unavailable'}), 503
        raw = client.get(RedisChannels.DEAD_AIR_KEY)
        if not raw:
            return jsonify({
                'ok': True, 'active': False, 'enabled': False,
                'acknowledged': False, 'sources': {},
                'can_acknowledge': has_permission('system.configure'),
            })
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        payload = _json.loads(raw)
        # The acknowledgement is bound to an episode id, so a stale ack
        # left over from an earlier outage cannot mute a new one.
        ack = client.get(RedisChannels.DEAD_AIR_ACK_KEY)
        if isinstance(ack, bytes):
            ack = ack.decode('utf-8')
        episode = payload.get('episode')
        payload['acknowledged'] = bool(ack) and bool(episode) and ack == episode
        payload['can_acknowledge'] = has_permission('system.configure')
        payload['ok'] = True
        return jsonify(payload)
    except Exception as exc:
        logger.exception("Dead-air status read failed")
        return jsonify({'ok': False, 'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/dead-air/acknowledge', methods=['POST'])
@require_permission('system.configure')
def audio_dead_air_acknowledge():
    """Silence the rack buzzer for the current dead-air episode.

    Standard alarm-panel behaviour: acknowledging stops the noise but
    leaves the tower light lit, because the fault has been noticed, not
    fixed. The audio service clears the acknowledgement when audio
    returns, so the next outage sounds again rather than starting
    pre-silenced.
    """
    try:
        from app_core.config.redis_config import RedisChannels
        from app_core.redis_client import get_redis_client

        import json as _json

        payload = request.get_json(silent=True) or {}
        acknowledged = _as_bool(payload.get('acknowledged', True))

        client = get_redis_client()
        if client is None:
            return jsonify({'ok': False, 'error': 'Redis unavailable'}), 503

        if not acknowledged:
            client.delete(RedisChannels.DEAD_AIR_ACK_KEY)
            logger.info("Dead-air acknowledgement cleared by operator")
            return jsonify({'ok': True, 'acknowledged': False})

        # An acknowledgement is only meaningful against a live alarm, and it
        # is stored as that episode's id rather than a bare flag. Writing an
        # unbound ack while nothing was wrong would sit in Redis for its
        # whole TTL and silently mute the *next* outage -- the failure mode
        # an alarm panel must never have.
        raw = client.get(RedisChannels.DEAD_AIR_KEY)
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        state = _json.loads(raw) if raw else {}
        if not state.get('active'):
            return jsonify({
                'ok': False,
                'error': 'No dead-air alarm is currently active',
            }), 409

        episode = state.get('episode')
        if not episode:
            return jsonify({
                'ok': False,
                'error': 'Alarm state carries no episode id; cannot acknowledge',
            }), 409

        requested = payload.get('episode')
        if requested and requested != episode:
            # The operator's page was showing an older outage.
            return jsonify({
                'ok': False,
                'error': 'That alarm has already cleared; refresh to see current state',
            }), 409

        client.setex(RedisChannels.DEAD_AIR_ACK_KEY, 86400, episode)
        logger.warning("Dead-air alarm acknowledged by operator (episode %s)", episode)
        return jsonify({'ok': True, 'acknowledged': True, 'episode': episode})
    except Exception as exc:
        logger.exception("Dead-air acknowledge failed")
        return jsonify({'ok': False, 'error': str(exc)}), 500
