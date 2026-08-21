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

"""Dead-air (silence) alarm status, acknowledgement, and buzzer output.

Detection policy -- what counts as silence on a given source, and whether
dead-air alarming is even enabled for it -- is per-source now, configured
through the same create/update routes as every other source setting (see
``routes_sources_write.py`` and ``AudioSourceConfig.dead_air_*`` in
``app_core/audio/ingest.py``). A single station-wide policy could not
express "alarm on silence for this continuous broadcast monitor, but never
for that state-relay source that's supposed to be silent except when
relaying an actual alert" -- it was either on for everyone or off for
everyone.

What remains here is legitimately station-wide: whether *any* monitored
source is silent right now (aggregated across all of them), and
acknowledging the one physical rack buzzer / tower light that fault
drives. Those outputs don't move -- see ``app_core.hardware_settings``'s
``get_dead_air_settings()`` for the buzzer GPIO pin.
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
        from app_core.audio.dead_air_alarm import acknowledge_dead_air

        payload = request.get_json(silent=True) or {}
        acknowledged = _as_bool(payload.get('acknowledged', True))
        requested_episode = payload.get('episode')

        result = acknowledge_dead_air(
            acknowledged=acknowledged, requested_episode=requested_episode,
        )
        status = result.pop('status', 200 if result.get('ok') else 500)
        return jsonify(result), status
    except Exception as exc:
        logger.exception("Dead-air acknowledge failed")
        return jsonify({'ok': False, 'error': str(exc)}), 500
