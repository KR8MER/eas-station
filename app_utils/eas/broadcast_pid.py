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

"""Tracking the currently-running playback subprocess: its PID and isolated
EOM audio, published to Redis so a GPIO-triggered abort can signal it."""

import base64
import subprocess
from typing import Optional, Sequence



#: Redis key holding the PID of the currently-running playback subprocess,
#: published by ``_run_command()`` while it's blocked in ``.wait()`` and read
#: by ``app_core.audio.gpio_input_actions.abort_current_broadcast()`` to
#: signal it. Not the same key/lifecycle as ``_BROADCAST_STATE_KEY`` -- that
#: one describes the broadcast (label, duration, identifier) for the UI/GPIO
#: relay-keying; this one is purely "which OS process is playing audio right
#: now", scoped to the lifetime of a single subprocess call.
_BROADCAST_PID_KEY = 'eas:broadcast_pid'



#: Redis key holding the isolated EOM tone-burst WAV for whatever broadcast
#: is currently in flight, published alongside the PID above. A GPIO-
#: triggered abort kills the in-progress player but must still end with a
#: compliant End-Of-Message burst per 47 CFR 11.61(a) -- this is how
#: ``abort_current_broadcast()`` gets audio to play for that burst without
#: reaching back into whichever caller (RWT scheduler, manual Send workflow,
#: resend script, or the live/auto-forward path) happened to trigger it.
_BROADCAST_EOM_KEY = 'eas:broadcast_eom_wav'



#: Safety-expiry TTL, well beyond any plausible single broadcast's duration --
#: a crash between setting this key and the `finally` clearing it must not
#: leave a stale PID pointing at a long-dead (or worse, reused) process id
#: forever.
_BROADCAST_PID_TTL = 1800




def _publish_broadcast_pid(pid: int, eom_wav: Optional[bytes] = None) -> None:
    """Best-effort: a Redis hiccup here must never interrupt playback.

    *eom_wav* is base64-encoded before storage: ``get_redis_client()``
    returns a client configured with ``decode_responses=True`` (every other
    key this module publishes is text), which UTF-8-decodes every value on
    read -- raw WAV bytes are not valid UTF-8 and that decode raises,
    silently discarded by ``get_broadcast_eom_audio()``'s own best-effort
    ``except Exception: return None``. Base64 keeps the payload text-safe
    for that same client.
    """
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is not None:
            client.set(_BROADCAST_PID_KEY, str(pid), ex=_BROADCAST_PID_TTL)
            if eom_wav:
                encoded = base64.b64encode(eom_wav).decode('ascii')
                client.set(_BROADCAST_EOM_KEY, encoded, ex=_BROADCAST_PID_TTL)
            else:
                client.delete(_BROADCAST_EOM_KEY)
    except Exception:
        pass




def _clear_broadcast_pid() -> None:
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is not None:
            client.delete(_BROADCAST_PID_KEY)
            client.delete(_BROADCAST_EOM_KEY)
    except Exception:
        pass




def get_broadcast_pid() -> Optional[int]:
    """Return the PID of the currently-running playback subprocess, or
    ``None`` if nothing is playing (or the marker expired/was never set)."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return None
        raw = client.get(_BROADCAST_PID_KEY)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        return int(raw)
    except Exception:
        return None




def get_broadcast_eom_audio() -> Optional[bytes]:
    """Return the isolated EOM tone-burst WAV bytes for the broadcast
    currently in flight, or ``None`` if nothing is playing / no EOM audio
    was published for it. Read by
    ``app_core.audio.gpio_input_actions.abort_current_broadcast()`` so a
    GPIO-forced abort can still send a compliant EOM burst.

    ``_publish_broadcast_pid()`` stores this base64-encoded (see its
    docstring) -- decode back to raw WAV bytes here.
    """
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return None
        raw = client.get(_BROADCAST_EOM_KEY)
        if not raw:
            return None
        return base64.b64decode(raw)
    except Exception:
        return None




def _run_command(
    command: Sequence[str],
    logger,
    eom_wav: Optional[bytes] = None,
    timeout: Optional[float] = None,
) -> None:
    """Run *command* to completion, publishing its PID (and, if given, the
    isolated EOM tone-burst audio) while it runs.

    Was a bare ``subprocess.run(...)`` until the GPIO "Dump/Abort Broadcast"
    input action needed a way to signal a running playback process from a
    different process. Behaviourally unchanged for every existing caller when
    *timeout* is omitted: still blocks until the command exits, still
    swallows and logs any exception rather than raising --
    ``subprocess.Popen(...).wait()`` is functionally ``subprocess.run(...)``
    with the PID observable in between. *timeout* additionally lets the three
    other broadcast-playback call sites (RWT airchain, manual Send workflow,
    resend script) route through here too -- on expiry the process is killed
    and the timeout swallowed/logged, matching their prior
    ``subprocess.run(..., timeout=...)`` + ``except TimeoutExpired`` handling.
    The PID/EOM markers are always cleared in ``finally``, so a normal
    completion (or a launch failure, or an exception mid-wait) never leaves a
    stale entry for a later abort attempt to act on.
    """
    try:
        process = subprocess.Popen(list(command))
    except Exception as exc:  # pragma: no cover - subprocess errors are logged
        if logger:
            logger.warning(f"Failed to run command {' '.join(command)}: {exc}")
        return

    _publish_broadcast_pid(process.pid, eom_wav=eom_wav)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if logger:
            logger.warning(f"Command timed out after {timeout}s: {' '.join(command)}")
        try:
            process.kill()
            process.wait()
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover - subprocess errors are logged
        if logger:
            logger.warning(f"Failed to run command {' '.join(command)}: {exc}")
    finally:
        _clear_broadcast_pid()




def play_broadcast_audio(
    command: Sequence[str],
    logger=None,
    eom_wav: Optional[bytes] = None,
    timeout: Optional[float] = None,
) -> None:
    """Public entry point for launching a broadcast audio player while
    tracking it for GPIO-triggered abort.

    ``EASBroadcaster._play_audio()`` (the live/auto-forwarded alert path)
    calls ``_run_command()`` directly since it lives in this module; the
    other three playback call sites -- ``app_core.rwt_scheduler``
    (RWT airchain), ``webapp.eas.workflow`` (manual Send), and
    ``scripts/resend_eas_broadcast.py`` (resend/forward) -- call this
    instead of their own inline ``subprocess.run(...)`` so every broadcast,
    regardless of trigger, publishes its PID and EOM audio the same way.
    """
    _run_command(command, logger, eom_wav=eom_wav, timeout=timeout)
