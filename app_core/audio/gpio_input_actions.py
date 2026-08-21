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

"""Actions triggerable from a GPIO input pin.

A distinct concern from the automatic forwarding pipeline
(``app_core/audio/auto_forward.py``) or the manual resend route
(``webapp/eas/messages.py``) -- those act on an alert/message the caller
already identified. A GPIO input only has "which pin fired", so each
function here first has to answer "which alert/message does that mean" on
its own, then reuse the existing, already-reviewed trigger path for it.
"""

import logging
import os
import subprocess
import sys
import tempfile

logger = logging.getLogger(__name__)


def forward_most_recent_alert(operator: str = "gpio-input") -> None:
    """Re-broadcast whichever EASMessage was most recently generated.

    Mirrors ``POST /messages/<id>/resend`` (``webapp/eas/messages.py``)
    exactly once the message is identified: same live-broadcast guard, same
    detached-subprocess launch (``scripts/resend_eas_broadcast.py``) so GPIO
    is never keyed from inside this process. Never raises -- this runs
    inside the GPIO input-event dispatch loop, which must stay alive
    regardless of what it finds.
    """
    from flask import current_app

    from app_core.models import EASMessage, db
    from app_utils.eas import get_broadcast_state

    result = (
        db.session.query(EASMessage.id)
        .filter(EASMessage.audio_data.isnot(None))
        .order_by(EASMessage.created_at.desc())
        .first()
    )
    if result is None:
        logger.warning("GPIO-triggered Forward Last Alert skipped: no broadcastable EAS message found")
        return
    message_id = result[0]

    if get_broadcast_state().get("active"):
        logger.warning(
            "GPIO-triggered Forward Last Alert skipped: a broadcast is already in progress"
        )
        return

    script_path = os.path.join(current_app.root_path, "scripts", "resend_eas_broadcast.py")
    command = [sys.executable, script_path, "--message-id", str(message_id), "--operator", operator]

    try:
        # start_new_session detaches the child so it survives this process
        # and is never reaped when the request/dispatch that launched it ends
        # -- same rationale as the manual resend route.
        subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            command,
            cwd=current_app.root_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        logger.error("GPIO-triggered Forward Last Alert failed to launch: %s", exc)
        return

    logger.info("GPIO-triggered Forward Last Alert: re-transmitting EASMessage #%s", message_id)


def acknowledge_dead_air_alarm() -> None:
    """Acknowledge the current dead-air alarm (silence the rack buzzer).

    Reuses the exact same Redis-backed logic as the web UI's Acknowledge
    button (``app_core.audio.dead_air_alarm.acknowledge_dead_air``).
    Station-wide by design -- dead-air acknowledgement is scoped to one
    alarm episode, not a specific source, so a GPIO input needs no source
    targeting; it always acknowledges whatever the current episode is.
    No-ops (logged) when there is nothing to acknowledge; never raises.
    """
    from app_core.audio.dead_air_alarm import acknowledge_dead_air

    result = acknowledge_dead_air(acknowledged=True)
    if result.get("ok"):
        logger.info(
            "GPIO-triggered Acknowledge Dead Air: episode %s silenced", result.get("episode")
        )
    else:
        logger.warning("GPIO-triggered Acknowledge Dead Air skipped: %s", result.get("error"))


#: Grace period between SIGTERM and SIGKILL when aborting playback -- long
#: enough for a well-behaved audio player to release its device/file handles
#: cleanly, short enough that a physical abort input still feels immediate.
_ABORT_GRACE_SECONDS = 2.0

#: How long to wait, after a SIGKILL, for the OS to actually reap the process
#: and free its audio device before the EOM burst is played on the same
#: device -- SIGKILL is near-instant but not synchronous with reaping.
_ABORT_POST_KILL_SETTLE_SECONDS = 1.0


def _play_abort_eom_burst(eom_wav: bytes) -> bool:
    """Synchronously play the isolated EOM tone-burst so an aborted broadcast
    still ends with the End-Of-Message burst required by 47 CFR 11.61(a) --
    a GPIO-triggered Dump/Abort must interrupt the *message*, never the EOM.
    Returns ``True`` on a clean exit.
    """
    from app_utils.eas import _wav_duration_seconds, load_eas_config

    eas_config = load_eas_config()
    audio_player_cmd = eas_config.get('audio_player_cmd')
    if not audio_player_cmd:
        logger.error(
            "GPIO-triggered Dump/Abort Broadcast: no audio player configured -- "
            "cannot send the required EOM burst"
        )
        return False

    fd, tmp_path = tempfile.mkstemp(suffix='.wav', prefix='eas_abort_eom_')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(eom_wav)
        command = list(audio_player_cmd) + [tmp_path]
        eom_duration = _wav_duration_seconds(eom_wav) or 3.0
        logger.info("GPIO-triggered Dump/Abort Broadcast: playing EOM burst: %s",
                    ' '.join(command))
        result = subprocess.run(command, check=False, timeout=eom_duration + 10)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("GPIO-triggered Dump/Abort Broadcast: EOM burst playback timed out")
        return False
    except Exception as exc:
        logger.error("GPIO-triggered Dump/Abort Broadcast: EOM burst playback failed: %s", exc)
        return False
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def abort_current_broadcast(
    reason: str = "GPIO dump input triggered", operator: str = "gpio-input",
) -> None:
    """Forcibly stop an in-flight broadcast -- but never without an EOM.

    Signals the PID ``app_utils.eas.play_broadcast_audio()`` (or, for the
    live/auto-forward path, ``_run_command()``) published while the
    audio-player subprocess is running (SIGTERM, then SIGKILL if it hasn't
    exited after a grace period). This stops the *message* audio, but per
    47 CFR 11.61(a) every EAS message must end with an EOM burst -- a
    broadcast must never simply go silent. So before the broadcast is
    considered over, this plays the isolated EOM tone-burst that whichever
    caller (RWT scheduler, manual Send workflow, resend script, or the
    live/auto-forward path) published alongside the PID. Only once that EOM
    attempt has completed (successfully or not -- an unrecoverable failure,
    e.g. no audio player configured, must not leave the relay stuck forever)
    is the broadcast-active marker released, dropping the transmitter relay
    on the GPIO subprocess's next poll -- reusing the same falling-edge
    release path a broadcast ending normally already uses. Writes an entry
    to the tamper-evident audit ledger, including whether the EOM burst was
    actually sent: an operator-forced abort of a life-safety broadcast is
    exactly the class of event that ledger exists for, and "was this
    FCC-compliant" is core to that record. No-ops (logged) when nothing is
    currently playing. Never raises -- this runs inside the GPIO input-event
    dispatch loop, which must stay alive regardless of outcome.
    """
    import os
    import signal
    import time

    from app_utils.eas import (
        clear_broadcast_active,
        get_broadcast_eom_audio,
        get_broadcast_pid,
        get_broadcast_state,
    )

    pid = get_broadcast_pid()
    if pid is None:
        logger.info("GPIO-triggered Dump/Abort Broadcast: nothing is currently playing")
        return

    state = get_broadcast_state()
    label = state.get("label") or state.get("event_code") or "unknown broadcast"
    identifier = state.get("identifier") or None
    eom_wav = get_broadcast_eom_audio()

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        logger.info("GPIO-triggered Dump/Abort Broadcast: process %s already exited", pid)
        clear_broadcast_active()
        return
    except Exception as exc:
        logger.warning(
            "GPIO-triggered Dump/Abort Broadcast: could not check process %s: %s", pid, exc
        )
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        logger.warning("GPIO-triggered Dump/Abort Broadcast: SIGTERM to %s failed: %s", pid, exc)

    deadline = time.monotonic() + _ABORT_GRACE_SECONDS
    exited = False
    while time.monotonic() < deadline:
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            exited = True
            break

    if not exited:
        try:
            os.kill(pid, signal.SIGKILL)
            logger.warning(
                "GPIO-triggered Dump/Abort Broadcast: SIGKILL sent to %s after grace period", pid
            )
        except ProcessLookupError:
            exited = True  # exited between the last poll and here
        except Exception as exc:
            logger.error("GPIO-triggered Dump/Abort Broadcast: SIGKILL to %s failed: %s", pid, exc)

        if not exited:
            # Give the OS a moment to actually reap the process and free its
            # audio device before the EOM burst tries to use the same device.
            settle_deadline = time.monotonic() + _ABORT_POST_KILL_SETTLE_SECONDS
            while time.monotonic() < settle_deadline:
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break

    # The message audio is stopped -- now the mandatory part: an EAS
    # broadcast must never end without its EOM burst, so this is not
    # optional cleanup, it's the reason abort has to synchronously wait here
    # rather than releasing the relay the instant the player dies.
    eom_sent = False
    if eom_wav:
        eom_sent = _play_abort_eom_burst(eom_wav)
        if not eom_sent:
            logger.error(
                "GPIO-triggered Dump/Abort Broadcast: '%s' (pid %s) ended WITHOUT a "
                "successful EOM burst -- see prior error", label, pid,
            )
    else:
        logger.error(
            "GPIO-triggered Dump/Abort Broadcast: no EOM audio was published for "
            "'%s' (pid %s) -- ending WITHOUT a compliant EOM burst", label, pid,
        )

    clear_broadcast_active()

    from app_core.auth.audit import AuditAction, AuditLogger
    AuditLogger.log(
        action=AuditAction.EAS_CANCELLATION,
        username=operator,
        resource_type="eas_broadcast",
        resource_id=identifier,
        details={"reason": reason, "label": label, "pid": pid, "eom_sent": eom_sent},
    )

    logger.warning(
        "GPIO-triggered Dump/Abort Broadcast: aborted '%s' (pid %s), eom_sent=%s",
        label, pid, eom_sent,
    )
