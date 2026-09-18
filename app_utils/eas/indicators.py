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

"""Redis-backed broadcast/incoming-alert indicator state."""

import json
import time


def _get_oled_enabled_status():
    """Get OLED enabled status from database."""
    try:
        from app_core.hardware_settings import get_oled_settings
        oled_settings = get_oled_settings()
        return oled_settings.get('enabled', False)
    except Exception:
        return False




_BROADCAST_STATE_KEY = 'eas:broadcast_active'


_INCOMING_STATE_KEY = 'eas:incoming_alert'


# Seconds the GPIO relay is keyed before actual audio playout begins, and
# held after it ends -- giving the transmitter time to come up to full power
# and stabilize before the SAME burst starts, and preventing the tail of the
# broadcast from being clipped by an instant carrier drop.
#
# This is a *program*-level timing concern (how long the relay stays
# asserted relative to actual audio playback), not audio content. It used
# to be implemented as literal silence samples embedded in the generated
# WAV -- which broke the moment a stored alert was resent (resend replays
# the exact stored bytes rather than regenerating audio, so padding baked
# in at generation time can never retroactively apply to already-stored
# messages), and meant every consumer of that audio -- Icecast stream
# listeners, FCC-compliance exports, archived recordings -- got artificial
# dead air mixed into the actual alert content. Every caller that drives
# the airchain (EASBroadcaster.handle_alert, the manual send route, the RWT
# scheduler, and the resend script) instead sleeps this long immediately
# after set_broadcast_active() (before starting real playout) and again
# immediately before clear_broadcast_active() (after playout ends), so the
# relay's on-air window brackets the actual audio symmetrically without
# the audio file itself ever containing the padding.
BROADCAST_LEAD_IN_SECONDS = 1.0


BROADCAST_LEAD_OUT_SECONDS = 1.0


# Seconds the on-air overlay / tower light may linger past the broadcast's own
# end-of-message (start_ts + duration_seconds) before the state is reported
# inactive.  This decouples the indicators from the send worker: the worker
# normally calls clear_broadcast_active() the moment playout finishes, but if
# that thread is delayed, blocked, or dies before its finally runs, the marker
# would otherwise sit at active=True until its TTL.  A short grace lets the
# "END OF MESSAGE" confirmation show briefly, then the indicators self-clear.
_BROADCAST_STATE_GRACE_SECONDS = 5.0


# Pub/sub channel the GPIO subsystem subscribes to so tower-light / NeoPixel
# transitions fire the instant broadcast or incoming-alert state changes,
# instead of waiting for the next 1-second poll.  The payload is just a wake-up
# nudge ("changed"); the subscriber re-reads the state keys above to decide what
# to do.  A periodic poll still runs in the subscriber as a safety net in case a
# notification is ever missed (e.g. Redis reconnect).
_INDICATOR_CHANNEL = 'eas:indicator_events'




def _notify_indicator_change() -> None:
    """Publish a wake-up nudge so indicator hardware reacts without polling lag."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return
        client.publish(_INDICATOR_CHANNEL, 'changed')
    except Exception:
        pass




def set_incoming_alert(event_code: str = '', identifier: str = '') -> None:
    """Record in Redis that an alert has been received but broadcast has not started.

    Called when an alert is first processed so hardware indicators (tower light)
    can show a pre-broadcast "incoming" state (e.g. yellow blink) while audio
    is being generated and the playout decision is being made.  The key carries
    a short TTL so stale entries self-expire if the broadcast never starts.

    *identifier* is the originating alert id; it is carried in the marker so the
    GPIO subprocess can attribute the INCOMING_ALERT pulse to the right alert in
    the activation audit log.
    """
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return
        payload = json.dumps({
            'incoming': True,
            'event_code': event_code or '',
            'identifier': identifier or '',
            'ts': time.time(),
        })
        client.set(_INCOMING_STATE_KEY, payload, ex=300)  # 5-minute safety TTL
    except Exception:
        pass
    _notify_indicator_change()




def clear_incoming_alert() -> None:
    """Remove the incoming alert marker from Redis."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return
        client.delete(_INCOMING_STATE_KEY)
    except Exception:
        pass
    _notify_indicator_change()




def get_incoming_alert_state() -> dict:
    """Return current incoming-alert state dict, or ``{'incoming': False}`` if none."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return {'incoming': False}
        raw = client.get(_INCOMING_STATE_KEY)
        if raw is None:
            return {'incoming': False}
        return json.loads(raw)
    except Exception:
        return {'incoming': False}




def set_broadcast_active(
    event_code: str,
    label: str,
    duration_seconds: float,
    source: str = 'manual',
    identifier: str = '',
    header_seconds: float = 0.0,
    eom_seconds: float = 0.0,
) -> bool:
    """Record in Redis that an EAS broadcast is in progress.

    Called just before audio playback begins so all connected clients can
    display a live countdown timer regardless of which page they are on.

    *identifier* is the alert identifier (e.g. ``RWT-AUTO-...`` or a CAP id).
    It is carried in the marker so the GPIO subprocess — which now keys the
    relay off this marker rather than each producer keying its own controller —
    can record the originating alert in the GPIO activation audit log.

    *header_seconds* / *eom_seconds* are elapsed-time thresholds (from the
    start of the composite audio) marking the end of the SAME header burst
    and the start of the EOM burst, respectively -- everything in between is
    the narration/attention-tone phase. Each caller folds any pre-alert or
    post-alert chime duration into these (chimes play immediately before the
    header / after the EOM, so they read as part of those phases). Zero
    means "unknown" -- the countdown overlay falls back to a plain,
    phase-less countdown when either is 0, so older/partial callers degrade
    gracefully rather than showing a wrong phase.

    Returns ``True`` when the marker was actually written to Redis, so callers
    can report whether the airchain was really signalled rather than assuming
    success (the write is best-effort and Redis failures are swallowed).
    """
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return False
        payload = json.dumps({
            'active': True,
            'start_ts': time.time(),
            'duration_seconds': float(duration_seconds),
            'event_code': event_code or '',
            'label': label or event_code or 'EAS Alert',
            'source': source,
            'identifier': identifier or '',
            'header_seconds': float(header_seconds or 0.0),
            'eom_seconds': float(eom_seconds or 0.0),
        })
        # TTL = duration + 60 s safety margin so stale entries self-expire
        ttl = max(60, int(duration_seconds) + 60)
        client.set(_BROADCAST_STATE_KEY, payload, ex=ttl)
        # Broadcast starting supersedes the incoming-alert state
        client.delete(_INCOMING_STATE_KEY)
        _notify_indicator_change()
        return True
    except Exception:
        _notify_indicator_change()
        return False




def clear_broadcast_active(identifier: str = '') -> None:
    """Remove the active broadcast marker from Redis once playback ends.

    When *identifier* is supplied, only clear the marker if it still belongs to
    that broadcast.  Broadcasts share one global marker key, so without this
    guard an older playout finishing could erase the marker a newer overlapping
    broadcast just wrote — releasing the relay (which the GPIO subprocess keys
    off this marker) mid-broadcast.  The compare-and-delete window is sub-ms on
    single-threaded Redis; on any error we fall back to an unconditional delete
    (the safe direction — the relay drops rather than sticks).
    """
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return
        if identifier:
            try:
                raw = client.get(_BROADCAST_STATE_KEY)
                if raw:
                    current_id = (json.loads(raw) or {}).get('identifier', '')
                    if current_id and current_id != identifier:
                        # A newer broadcast owns the marker now; leave it.
                        _notify_indicator_change()
                        return
            except Exception:
                # Fall through to an unconditional delete on any read/parse error.
                pass
        client.delete(_BROADCAST_STATE_KEY)
    except Exception:
        pass
    _notify_indicator_change()




def get_broadcast_state() -> dict:
    """Return current broadcast state dict, or ``{'active': False}`` if idle.

    The stored marker is reported inactive once the broadcast's own
    ``start_ts + duration_seconds`` has elapsed (plus
    :data:`_BROADCAST_STATE_GRACE_SECONDS`), even if the marker key still
    exists.  The send worker clears the marker the instant playout finishes,
    but the indicators (air-chain overlay, tower light) must not stay lit past
    end-of-message if that clear is ever delayed — so the elapsed broadcast is
    treated as over here, at the single point every consumer reads through.
    """
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return {'active': False}
        raw = client.get(_BROADCAST_STATE_KEY)
        if raw is None:
            return {'active': False}
        state = json.loads(raw)
        if state.get('active'):
            start_ts = state.get('start_ts')
            duration = state.get('duration_seconds')
            if start_ts is not None and duration is not None:
                ends_at = float(start_ts) + float(duration) + _BROADCAST_STATE_GRACE_SECONDS
                if time.time() >= ends_at:
                    # Broadcast is over; lazily drop the marker so repeated
                    # reads / WebSocket pushes don't keep re-broadcasting it.
                    try:
                        client.delete(_BROADCAST_STATE_KEY)
                    except Exception:
                        pass
                    return {'active': False}
        return state
    except Exception:
        return {'active': False}
