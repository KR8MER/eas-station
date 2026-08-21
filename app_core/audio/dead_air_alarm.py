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

"""Dead-air alarm acknowledgement -- the Redis-backed logic shared by the
web route (webapp/admin/audio_ingest/routes_dead_air.py) and the
GPIO-triggered Acknowledge Dead Air input action
(app_core/audio/gpio_input_actions.py).

Acknowledgement is station-wide, bound to one alarm "episode" id rather than
a specific source: dead-air *detection* is per-source, but the alarm output
(one rack buzzer, one tower light) and its acknowledgement are aggregated --
see routes_dead_air.py's module docstring for the full rationale. A caller
therefore never needs to name a source, only (optionally) the episode it
expects to be acknowledging, as a guard against acknowledging a *new* outage
with a stale reference to an old one.
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def acknowledge_dead_air(
    acknowledged: bool = True,
    requested_episode: Optional[str] = None,
) -> Dict[str, Any]:
    """Acknowledge (or clear the acknowledgement of) the current dead-air alarm.

    Returns a dict always carrying ``"ok"``. On failure it also carries
    ``"error"`` and the HTTP status a route caller should use (``"status"``);
    a non-HTTP caller (e.g. a GPIO input) only needs to check ``"ok"``.
    """
    from app_core.config.redis_config import RedisChannels
    from app_core.redis_client import get_redis_client

    client = get_redis_client()
    if client is None:
        return {"ok": False, "error": "Redis unavailable", "status": 503}

    if not acknowledged:
        client.delete(RedisChannels.DEAD_AIR_ACK_KEY)
        logger.info("Dead-air acknowledgement cleared")
        return {"ok": True, "acknowledged": False}

    # An acknowledgement is only meaningful against a live alarm, and it is
    # stored as that episode's id rather than a bare flag. Writing an
    # unbound ack while nothing was wrong would sit in Redis for its whole
    # TTL and silently mute the *next* outage -- the failure mode an alarm
    # panel must never have.
    raw = client.get(RedisChannels.DEAD_AIR_KEY)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    state = json.loads(raw) if raw else {}
    if not state.get("active"):
        return {"ok": False, "error": "No dead-air alarm is currently active", "status": 409}

    episode = state.get("episode")
    if not episode:
        return {
            "ok": False,
            "error": "Alarm state carries no episode id; cannot acknowledge",
            "status": 409,
        }

    if requested_episode and requested_episode != episode:
        # The caller's picture of the world was showing an older outage.
        return {
            "ok": False,
            "error": "That alarm has already cleared; refresh to see current state",
            "status": 409,
        }

    client.setex(RedisChannels.DEAD_AIR_ACK_KEY, 86400, episode)
    logger.warning("Dead-air alarm acknowledged (episode %s)", episode)
    return {"ok": True, "acknowledged": True, "episode": episode}
