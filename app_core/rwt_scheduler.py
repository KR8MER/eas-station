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

"""RWT (Required Weekly Test) automatic scheduler.

This module provides scheduled background tasks for automatically sending
RWT broadcasts according to configured schedules.
"""

import logging
import os
import random
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, current_app, has_app_context
from app_core.extensions import db
from app_core.models import RWTScheduleConfig, ManualEASActivation, SystemLog
from app_utils import utc_now
from app_utils.eas import (
    EASAudioGenerator,
    _wav_duration_seconds,
    build_same_header,
    clear_broadcast_active,
    load_eas_config,
    manual_default_same_codes,
    play_broadcast_audio,
    samples_to_wav_bytes,
    set_broadcast_active,
    truncate_wav_to_max_seconds,
)

logger = logging.getLogger(__name__)


def week_key(moment: datetime) -> Tuple[int, int]:
    """Return the ISO ``(year, week)`` the given local datetime falls in.

    An RWT is a *weekly* obligation, so every "have we already run?" decision is
    made per ISO week rather than per calendar date.
    """
    iso = moment.isocalendar()
    return int(iso[0]), int(iso[1])


def _window_minutes(config: RWTScheduleConfig) -> Tuple[int, int]:
    """Return the configured window as ``(start, end)`` minutes past midnight.

    An end before the start is treated as a zero-length window at the start
    rather than an error, so a mis-entered schedule still fires once at the
    start time instead of never firing.
    """
    start = int(config.start_hour or 0) * 60 + int(config.start_minute or 0)
    end = int(config.end_hour or 0) * 60 + int(config.end_minute or 0)
    if end < start:
        end = start
    return start, end


def _eligible_days(config: RWTScheduleConfig, monday: date) -> List[int]:
    """Configured weekdays in the week starting *monday*, minus skipped ones."""
    configured = sorted({int(d) for d in (config.days_of_week or []) if 0 <= int(d) <= 6})
    skip_until = getattr(config, 'skip_until', None)
    if not skip_until:
        return configured
    return [d for d in configured if (monday + timedelta(days=d)) > skip_until]


def weekly_fire_slot(
    config: RWTScheduleConfig,
    reference_local: datetime,
) -> Optional[datetime]:
    """Pick this week's single RWT slot: one configured day, at a random time.

    A Required Weekly Test is sent **once per week**, not once on every day the
    operator ticked.  The day list is the set of days the broadcast is *allowed*
    to land on; the scheduler chooses exactly one of them each week — which is
    also what makes the test unpredictable, as 47 CFR §11.61(a)(2) intends.  The
    time is drawn at random from inside the configured window for the same
    reason.

    The choice is derived from a seed of (schedule id, ISO year, ISO week), so
    it is:

    * **stable** — every poll during the week resolves to the same slot, and the
      UI's "next scheduled fire" does not jump around;
    * **identical in every Gunicorn worker** — each worker runs its own copy of
      this scheduler, and they must agree on the slot without coordinating; and
    * **different each week** — the day and minute move around within the
      operator's constraints instead of settling on a fixed weekly pattern.

    Returns ``None`` when the config is disabled or no day in this week is
    eligible (no days configured, or all of them covered by ``skip_until``).
    """
    if not config.enabled:
        return None

    monday = reference_local.date() - timedelta(days=reference_local.weekday())
    days = _eligible_days(config, monday)
    if not days:
        return None

    iso_year, iso_week = week_key(reference_local)
    rng = random.Random(f"eas-rwt-slot:{config.id}:{iso_year}:{iso_week}")

    chosen_day = rng.choice(days)
    start_min, end_min = _window_minutes(config)
    chosen_minute = rng.randint(start_min, end_min)

    slot_date = monday + timedelta(days=chosen_day)
    return datetime(
        slot_date.year,
        slot_date.month,
        slot_date.day,
        chosen_minute // 60,
        chosen_minute % 60,
        tzinfo=reference_local.tzinfo,
    )


def _ran_in_week(config: RWTScheduleConfig, reference_local: datetime) -> bool:
    """True when a successful RWT is already recorded for *reference_local*'s week."""
    if not config.last_run_at or config.last_run_status != 'success':
        return False
    last_run = config.last_run_at
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    return week_key(last_run.astimezone(reference_local.tzinfo)) == week_key(reference_local)


def _window_bounds(config: RWTScheduleConfig, day: date, tz) -> Tuple[datetime, datetime]:
    """Return the local ``(start, end)`` datetimes of the window on *day*."""
    start_min, end_min = _window_minutes(config)
    return (
        datetime(day.year, day.month, day.day, start_min // 60, start_min % 60, tzinfo=tz),
        datetime(day.year, day.month, day.day, end_min // 60, end_min % 60, tzinfo=tz),
    )


def compute_next_fire(
    config: RWTScheduleConfig,
    now_local: Optional[datetime] = None,
) -> Optional[datetime]:
    """Compute the next datetime (local timezone, aware) at which this
    configuration will fire an automatic RWT broadcast.

    Returns ``None`` when the config is disabled, has no eligible days, or
    would otherwise never fire.

    One RWT is sent per **week**, on one of the configured days — not on every
    configured day.  :func:`weekly_fire_slot` makes that choice; this function
    reports it, and rolls forward when the week's test has already gone out or
    its slot has passed:

      * If this week's test has already been sent, report next week's slot.
      * If this week's slot is still ahead, report it.
      * If the slot has passed without the test going out (the station was down
        during it), report the start of the next configured window still left in
        the week — the scheduler catches up rather than losing the week.  When
        no window remains, report next week's slot.
      * Days on or before ``skip_until`` are never eligible; a week with no
        eligible day at all rolls to the next week that has one.
    """
    if not config.enabled:
        return None

    if now_local is None:
        now_local = datetime.now(timezone.utc).astimezone()

    tz = now_local.tzinfo

    def _next_week_slot(from_moment: datetime) -> Optional[datetime]:
        # Look ahead a few weeks so a skip_until spanning a holiday still
        # resolves to a real date instead of "never".
        probe = from_moment
        for _ in range(8):
            probe = probe + timedelta(days=7)
            slot = weekly_fire_slot(config, probe)
            if slot is not None:
                return slot
        return None

    if _ran_in_week(config, now_local):
        return _next_week_slot(now_local)

    slot = weekly_fire_slot(config, now_local)
    if slot is None:
        return _next_week_slot(now_local)

    if slot >= now_local:
        return slot

    # The slot has passed and nothing was sent.  Offer the next configured
    # window remaining in this week so a missed slot still gets caught up.
    monday = now_local.date() - timedelta(days=now_local.weekday())
    for day in _eligible_days(config, monday):
        window_start, window_end = _window_bounds(config, monday + timedelta(days=day), tz)
        if now_local <= window_end:
            return max(window_start, slot)

    return _next_week_slot(now_local)


def _drive_rwt_airchain(
    activation_record: ManualEASActivation,
    composite_wav: Optional[bytes],
    eom_wav: Optional[bytes],
    header_seconds: float,
    eom_seconds: float,
    eas_config: Dict[str, Any],
    log: logging.Logger,
) -> bool:
    """Play the composite WAV for an automated RWT and hold the broadcast marker.

    GPIO is **not** keyed here.  The ``eas-station-gpio`` subprocess owns the
    physical relay lines (lgpio claims are exclusive per process) and keys them
    off the ``eas:broadcast_active`` marker this function maintains — so the
    relay stays asserted for exactly the broadcast window without this process
    ever touching the GPIO chip.  This also keeps the RWT scheduler (which runs
    inside the gunicorn web process) from importing lgpio, whose native thread
    stalls the gevent event loop.

    Returns ``True`` once the playout window has been held.
    """
    if not composite_wav:
        log.warning("RWT %s has no composite audio; skipping airchain.",
                    activation_record.identifier)
        return False

    max_activation_seconds = int(eas_config.get('max_activation_seconds', 300) or 300)
    audio_data = composite_wav
    if _wav_duration_seconds(audio_data) > max_activation_seconds:
        audio_data = truncate_wav_to_max_seconds(
            audio_data, eom_wav, max_activation_seconds,
        )
    playback_duration = _wav_duration_seconds(audio_data)

    alert_id = activation_record.identifier
    event_code = activation_record.event_code or 'RWT'
    tmp_file = None

    try:
        # Re-anchor the broadcast-state marker to the *actual* playout start.
        # trigger_rwt_broadcast sets it synchronously so the air-chain overlay
        # (and the GPIO subprocess's relay keying) react the instant the request
        # returns; re-anchoring here keeps the countdown finishing exactly when
        # we clear the marker below, so the overlay never lingers at 0:00.
        set_broadcast_active(
            event_code=event_code,
            label='Required Weekly Test',
            duration_seconds=playback_duration,
            source='automated_rwt',
            identifier=alert_id,
            header_seconds=header_seconds,
            eom_seconds=eom_seconds,
        )

        # Inject into the live Icecast air-chain, same as every other
        # broadcast path (live auto-forward, resend, manual Send -- see
        # webapp/eas/workflow.py). This function drives BOTH the fully
        # automated weekly RWT and the operator-triggered "Send Test RWT"
        # button (both call _drive_rwt_airchain via _dispatch_rwt_airchain),
        # and neither ever reached Icecast before this fix -- only
        # audio_player_cmd (local aplay) playback below did. The weekly
        # compliance test was airing nowhere a stream listener could hear
        # it. This process (the gunicorn web worker) has no
        # AudioIngestController of its own, so it asks the audio-service to
        # inject over the Redis command channel, same as resend/manual Send.
        try:
            from app_core.audio.redis_commands import get_audio_command_publisher
            inject_resp = get_audio_command_publisher().inject_raw_eas_audio(
                audio_data, timeout=10.0,
            )
            if inject_resp.get('success'):
                log.info(
                    'RWT audio injected into air-chain for %s', alert_id,
                )
            else:
                log.info(
                    'RWT air-chain injection reported no audio for %s: %s',
                    alert_id, inject_resp.get('message'),
                )
        except Exception as exc:
            log.warning(
                'RWT air-chain injection failed (non-fatal) for %s: %s',
                alert_id, exc,
            )

        audio_player_cmd = eas_config.get('audio_player_cmd')
        playout_start = time.monotonic()
        if audio_player_cmd:
            try:
                tmp_file = tempfile.NamedTemporaryFile(
                    suffix='.wav', prefix='rwt_auto_', delete=False,
                )
                tmp_file.write(audio_data)
                tmp_file.flush()
                tmp_file.close()
                command = list(audio_player_cmd) + [tmp_file.name]
                log.info("Playing automated RWT audio: %s", ' '.join(command))
                # Bound the player to this broadcast's own length, not the
                # global max.  A hung player (busy/blocked audio device,
                # stalled network sink) must never keep this worker — and
                # therefore the on-air overlay — blocked past the broadcast.
                # play_broadcast_audio() (not a bare subprocess.run()) so a
                # GPIO-triggered Dump/Abort can find this process's PID and
                # the isolated EOM burst (already embedded at the end of
                # this composite, but needed separately in case abort kills
                # playback before reaching it) -- see
                # app_core.audio.gpio_input_actions.abort_current_broadcast.
                play_broadcast_audio(
                    command, logger=log, eom_wav=eom_wav,
                    timeout=float(playback_duration) + 30,
                )
            except Exception as exc:
                log.warning("Audio playback failed for RWT %s: %s",
                            alert_id, exc)
        else:
            log.info("No audio player configured; holding broadcast marker for "
                     "%.1fs while encoder plays RWT %s",
                     playback_duration, alert_id)

        # Hold the broadcast marker for the full composite duration regardless
        # of whether the player blocked — on hosts without an audio device the
        # player can exit immediately, which would otherwise drop the relay
        # (released by the subprocess on the marker's falling edge) before the
        # encoder finishes the SAME burst.
        remaining = playback_duration - (time.monotonic() - playout_start)
        if remaining > 0:
            time.sleep(remaining)

    finally:
        # Clearing the marker is the falling edge the GPIO subprocess watches to
        # release the relay.  Pass the identifier so an overlapping newer
        # broadcast's marker is never erased by this RWT finishing.
        clear_broadcast_active(identifier=alert_id)
        if tmp_file is not None:
            try:
                os.unlink(tmp_file.name)
            except OSError:
                pass

    return True


def _dispatch_rwt_airchain(
    app: Flask,
    activation_id: int,
    composite_wav: Optional[bytes],
    eom_wav: Optional[bytes],
    header_seconds: float,
    eom_seconds: float,
    eas_config: Dict[str, Any],
    log: logging.Logger,
) -> threading.Thread:
    """Run :func:`_drive_rwt_airchain` on a daemon thread.

    Holding the airchain plays the composite WAV for the full activation
    duration (potentially several minutes) and only releases the GPIO relay
    and the Redis broadcast-state marker afterwards.  Doing that inline blocks
    whichever thread called :func:`trigger_rwt_broadcast`:

    * the Flask request thread for the manual "Send Test RWT" button, whose
      ``fetch('/api/rwt-schedule/test')`` then hangs for the entire broadcast
      (operators saw an endless "Sending..." spinner), and
    * on single-threaded deployments that same blocked request also starves
      the ``/api/broadcast/state`` poll that drives the "air-chain under EAS
      Station control" overlay, so the popup never appeared.

    Backgrounding lets the caller return immediately while the broadcast-state
    marker keeps the overlay/countdown alive for the full duration.  The
    activation row is re-loaded inside the worker's own application context so
    it isn't tied to the caller's (soon-to-close) database session.
    """
    def _worker() -> None:
        try:
            with app.app_context():
                record = ManualEASActivation.query.get(activation_id)
                if record is None:
                    log.warning(
                        "RWT airchain: activation %s no longer exists; "
                        "skipping playback.", activation_id,
                    )
                    return
                _drive_rwt_airchain(
                    activation_record=record,
                    composite_wav=composite_wav,
                    eom_wav=eom_wav,
                    header_seconds=header_seconds,
                    eom_seconds=eom_seconds,
                    eas_config=eas_config,
                    log=log,
                )
        except Exception as exc:  # pragma: no cover - defensive
            log.error(
                "RWT airchain playback thread failed: %s", exc, exc_info=True,
            )

    thread = threading.Thread(
        target=_worker,
        name=f"rwt-airchain-{activation_id}",
        daemon=True,
    )
    thread.start()
    return thread


def trigger_rwt_broadcast(config: RWTScheduleConfig, logger_instance=None) -> Dict[str, Any]:
    """Trigger an RWT broadcast with the given configuration.

    Args:
        config: RWT schedule configuration
        logger_instance: Logger to use (defaults to module logger)

    Returns:
        Dictionary with broadcast result information
    """
    log = logger_instance or logger

    try:
        from datetime import datetime, timezone
        from types import SimpleNamespace

        # Build RWT identifier
        now = datetime.now(timezone.utc)
        identifier = f"RWT-AUTO-{now.strftime('%Y%m%d%H%M%S')}"

        # Load EAS config (includes originator and station_id from environment)
        eas_config = load_eas_config()

        # Create alert object for RWT
        alert_object = SimpleNamespace(
            identifier=identifier,
            event='Required Weekly Test',
            headline='Automated Required Weekly Test',
            description='This is an automated Required Weekly Test of the Emergency Alert System.',
            instruction='No action required. This is only a test.',
            sent=now,
            expires=now + timedelta(minutes=15),
            status='Test',
            message_type='Alert',
        )

        same_codes = [code for code in (config.same_codes or []) if code]

        # IMPORTANT: RWT broadcasts should ONLY use explicitly configured SAME codes.
        # We do NOT fall back to location filtering FIPS codes because:
        # 1. Location FIPS codes are for FILTERING incoming alerts (includes nationwide 000000)
        # 2. RWT should only target the station's local broadcast area
        # 3. Broadcasting RWT to nationwide would be inappropriate
        if not same_codes:
            raise ValueError(
                "No SAME/FIPS codes configured for RWT broadcasts. "
                "Please configure specific SAME codes for RWT on the RWT Schedule page. "
                "Do NOT use your alert filtering FIPS codes - RWT should only target "
                "your local broadcast area, not nationwide or all monitored areas."
            )

        # Prepare payload wrapper
        payload_wrapper = {
            'identifier': identifier,
            'sent': now,
            'expires': now + timedelta(minutes=15),
            'status': 'Test',
            'message_type': 'Alert',
            'raw_json': {
                'properties': {
                    'geocode': {
                        'SAME': same_codes,
                    }
                }
            },
        }

        # Build SAME header
        header, formatted_locations, resolved_event_code = build_same_header(
            alert_object,
            payload_wrapper,
            eas_config,
            location_settings=None,
        )

        # Generate audio components. RWT enforcement (no Attention Signal,
        # no TTS) is hardcoded inside build_manual_components() per
        # FCC 47 CFR §11.61(a)(1)(ii); we don't pass tone_profile/include_tts
        # here so there is no way for this path to request otherwise.
        generator = EASAudioGenerator(eas_config, logger=log)
        components = generator.build_manual_components(alert_object, header)

        if not components:
            raise ValueError("Failed to generate RWT audio components")

        sample_rate = int(eas_config.get('sample_rate', 16000) or 16000)

        # Render the in-memory sample arrays to WAV blobs for the database.
        # Automated RWTs never write to disk — playback streams from these
        # blob columns (see admin/audio.py:1153 and the activation detail
        # page), and storage_path stays empty so _remove_manual_eas_files()
        # treats the row as "no on-disk files to delete".
        def _wav(key: str) -> Optional[bytes]:
            samples = components.get(key) or []
            if not samples:
                return None
            return samples_to_wav_bytes(samples, sample_rate)

        def _meta(key: str, suffix: str, wav_bytes: Optional[bytes]) -> Optional[Dict[str, Any]]:
            if not wav_bytes:
                return None
            samples = components.get(key) or []
            return {
                'filename': f'{identifier}_{suffix}.wav',
                'duration_seconds': round(len(samples) / sample_rate, 3),
                'size_bytes': len(wav_bytes),
                'storage_subpath': '',
            }

        same_wav = _wav('same_samples')
        eom_wav = _wav('eom_samples')
        composite_wav = _wav('composite_samples')
        pre_chime_wav = _wav('pre_chime_samples')
        post_chime_wav = _wav('post_chime_samples')

        # Phase breakpoints for the countdown overlay -- see
        # set_broadcast_active()'s docstring. Chime audio (when configured)
        # plays immediately before the header / after the EOM, so its
        # duration folds into those same two phases rather than needing a
        # phase of its own.
        header_seconds = (
            _wav_duration_seconds(pre_chime_wav or b'')
            + _wav_duration_seconds(same_wav or b'')
        )
        eom_seconds = (
            _wav_duration_seconds(eom_wav or b'')
            + _wav_duration_seconds(post_chime_wav or b'')
        )

        components_payload: Dict[str, Any] = {}
        for component_key, sample_key, suffix, wav in (
            ('same', 'same_samples', 'same', same_wav),
            ('eom', 'eom_samples', 'eom', eom_wav),
            ('composite', 'composite_samples', 'full', composite_wav),
            ('pre_chime', 'pre_chime_samples', 'pre_chime', pre_chime_wav),
            ('post_chime', 'post_chime_samples', 'post_chime', post_chime_wav),
        ):
            entry = _meta(sample_key, suffix, wav)
            if entry:
                if component_key == 'pre_chime':
                    entry['profile'] = components.get('pre_chime_profile')
                elif component_key == 'post_chime':
                    entry['profile'] = components.get('post_chime_profile')
                components_payload[component_key] = entry

        # Archive any previously-active rows so the detail page surfaces the
        # newest RWT as the current activation (mirrors the manual workflow
        # at webapp/eas/workflow.py:695-697).
        ManualEASActivation.query.filter(
            ManualEASActivation.archived_at.is_(None)
        ).update({'archived_at': now}, synchronize_session=False)

        activation_record = ManualEASActivation(
            identifier=identifier,
            event_code='RWT',
            event_name='Required Weekly Test',
            status='Test',
            message_type='Alert',
            same_header=header,
            same_locations=formatted_locations,
            tone_profile='none',
            tone_seconds=0.0,
            sample_rate=sample_rate,
            includes_tts=False,
            sent_at=now,
            expires_at=now + timedelta(minutes=15),
            headline='Automated Required Weekly Test',
            message_text='This is an automated Required Weekly Test of the Emergency Alert System.',
            instruction_text='No action required. This is only a test.',
            duration_minutes=15,
            storage_path='',
            components_payload=components_payload,
            metadata_payload={
                'automated': True,
                'schedule_id': config.id,
                'signaling': components.get('signaling') or {},
            },
            composite_audio_data=composite_wav,
            same_audio_data=same_wav,
            eom_audio_data=eom_wav,
            pre_chime_audio_data=pre_chime_wav,
            post_chime_audio_data=post_chime_wav,
        )

        db.session.add(activation_record)

        # Log the broadcast
        db.session.add(SystemLog(
            level='INFO',
            message='Automated RWT broadcast sent',
            module='rwt_scheduler',
            details={
                'identifier': identifier,
                'same_header': header,
                'location_count': len(same_codes),
                'schedule_id': config.id,
            }
        ))

        # Update config last run status
        config.last_run_at = now
        config.last_run_status = 'success'
        config.last_run_details = {
            'identifier': identifier,
            'activation_id': activation_record.id,
            'timestamp': now.isoformat(),
        }
        db.session.add(config)

        db.session.commit()

        log.info("RWT broadcast sent successfully: %s", identifier)

        # Light the global air-chain control overlay *synchronously*, on the
        # calling thread, before handing playback to the background worker.
        #
        # The overlay is driven by the Redis broadcast-state marker (read 1 Hz
        # by the WebSocket push loop / the /api/broadcast/state poll).  When the
        # marker was written from inside the daemon thread it only landed *after*
        # GPIO initialisation, and on a Pi the blocking GPIO C calls can stall
        # the gevent hub long enough that the popup never appeared during the
        # short RWT broadcast.  Writing it here — mirroring the inline manual
        # send path (webapp/eas/workflow.py:1382-1396) — guarantees the popup
        # is visible the instant the request returns, independent of how soon
        # the daemon thread is scheduled.  Compute the duration with the same
        # truncation the worker applies so the countdown matches the airchain.
        max_activation_seconds = int(eas_config.get('max_activation_seconds', 300) or 300)
        broadcast_audio = composite_wav
        if broadcast_audio and _wav_duration_seconds(broadcast_audio) > max_activation_seconds:
            broadcast_audio = truncate_wav_to_max_seconds(
                broadcast_audio, eom_wav, max_activation_seconds,
            )
        broadcast_duration = _wav_duration_seconds(broadcast_audio) if broadcast_audio else 0.0
        if broadcast_duration > 0:
            set_broadcast_active(
                event_code='RWT',
                label='Required Weekly Test',
                duration_seconds=broadcast_duration,
                source='automated_rwt',
                identifier=identifier,
                header_seconds=header_seconds,
                eom_seconds=eom_seconds,
            )

        # Drive the airchain: hold GPIO and play the composite WAV for the
        # full duration so the encoder actually broadcasts the tones. The
        # manual send route (webapp/eas/workflow.py:1198-1357) does this for
        # operator-triggered RWTs; without it the automated path silently
        # creates a database row but never asserts the relay, so no GPIO
        # log entries appear and downstream encoders never hear the SAME
        # burst — operators see archived RWT rows but no audit trail.
        #
        # This runs on a background thread so the caller returns immediately:
        # the manual "Send Test RWT" button fires a blocking fetch, and
        # holding the request open for the entire broadcast froze that button
        # on "Sending..." while suppressing the air-chain-control overlay.  The
        # broadcast-state marker set above keeps the overlay/countdown alive for
        # the full duration; the worker clears it when playback finishes.
        activation_id = activation_record.id
        _dispatch_rwt_airchain(
            app=current_app._get_current_object(),
            activation_id=activation_id,
            composite_wav=composite_wav,
            eom_wav=eom_wav,
            header_seconds=header_seconds,
            eom_seconds=eom_seconds,
            eas_config=eas_config,
            log=log,
        )

        return {
            'success': True,
            'identifier': identifier,
            'activation_id': activation_id,
            'same_header': header,
            'airchain_dispatched': True,
        }

    except Exception as exc:
        log.error("Failed to trigger RWT broadcast: %s", exc, exc_info=True)
        try:
            config.last_run_at = utc_now()
            config.last_run_status = 'failed'
            config.last_run_details = {
                'error': str(exc),
                'timestamp': utc_now().isoformat(),
            }
            db.session.add(config)
            db.session.commit()
        except Exception as db_exc:
            log.error("Failed to update config after error: %s", db_exc)

        return {
            'success': False,
            'error': str(exc),
        }


class RWTScheduler:
    """Manages automatic RWT broadcast scheduling."""

    def __init__(self, app: Flask, check_interval_minutes: int = 1):
        """Initialize the RWT scheduler.

        Args:
            check_interval_minutes: How often to check if RWT should be sent (default: 1 minute)
        """
        if app is None:
            raise ValueError("A Flask application instance is required for the RWT scheduler")

        self.check_interval = timedelta(minutes=check_interval_minutes)
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.logger = logger
        self.app = app
        # Iteration counter for periodic heartbeat logging. Without this the
        # scheduler is silent when no config matches the current time, which
        # makes it impossible to tell whether the loop is running at all.
        self._iteration = 0

    def start(self):
        """Start the scheduler in a background thread."""
        if self.running:
            self.logger.warning("RWT scheduler is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self.logger.info("RWT scheduler started")

    def stop(self):
        """Stop the scheduler."""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("RWT scheduler stopped")

    def _write_heartbeat(self, config: RWTScheduleConfig) -> None:
        """Persist a heartbeat timestamp so the UI can show liveness across
        all Gunicorn workers.  Uses a narrow UPDATE so we never accidentally
        rewrite operator-managed columns from this thread.
        """
        try:
            config.last_heartbeat_at = utc_now()
            db.session.add(config)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            # Heartbeat write failure is not fatal — keep the loop running.
            self.logger.debug("Failed to write RWT heartbeat: %s", exc)

    def _run_loop(self):
        """Main scheduler loop."""
        self.logger.info(
            "RWT scheduler loop started (check interval: %.0f seconds)",
            self.check_interval.total_seconds(),
        )
        while self.running:
            try:
                with self.app.app_context():
                    self._check_and_send_rwt()
            except Exception as e:
                self.logger.error("Error in RWT scheduler loop: %s", e, exc_info=True)
                time.sleep(60)  # Wait before retrying
                continue

            # Sleep for the check interval outside the application context
            time.sleep(self.check_interval.total_seconds())

    def _check_and_send_rwt(self):
        """Check if RWT should be sent and send it if conditions are met.

        Schedule times (start_hour/start_minute, end_hour/end_minute) and
        days_of_week are entered by operators in their local timezone via the
        web UI — the UI shows no timezone selector and displays clocks in
        local time.  Historically this method compared against UTC, which
        silently shifted the firing window by the local UTC offset (so a
        configured "Wed 8 AM–4 PM EDT" really fired "4 AM–12 PM EDT" and
        skipped Wednesday entirely after 8 PM local because that's already
        Thursday in UTC).  Comparing against local time matches the
        operator's mental model.
        """
        ctx = None
        if not has_app_context():
            ctx = self.app.app_context()
            ctx.push()

        try:
            self._iteration += 1

            # Get active configuration
            config = RWTScheduleConfig.query.filter_by(enabled=True).first()
            if config is None:
                # Heartbeat once an hour so operators can confirm the loop is
                # alive even with no enabled config in the database.
                if self._iteration % 60 == 1:
                    self.logger.info(
                        "RWT scheduler loop alive — no enabled RWT schedule configured"
                    )
                return

            # Persist a heartbeat on every iteration so the UI can show the
            # scheduler is alive even when no fire conditions are met.
            self._write_heartbeat(config)

            # Use local time for day/window comparisons because operators
            # configure the schedule in local time via the UI.
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone()  # System local timezone

            # An RWT is a *weekly* obligation.  The configured days are the days
            # the broadcast is allowed to land on; exactly one of them is chosen
            # each week (see weekly_fire_slot), so ticking Sunday and Tuesday
            # means "one test, on a Sunday or a Tuesday" — not one on each.
            if _ran_in_week(config, now_local):
                if self._iteration % 60 == 1:
                    self.logger.info(
                        "RWT already sent this week (%s) at %s — skipping",
                        "%d-W%02d" % week_key(now_local),
                        config.last_run_at.isoformat(timespec='seconds'),
                    )
                return

            slot = weekly_fire_slot(config, now_local)
            if slot is None:
                if self._iteration % 60 == 1:
                    self.logger.info(
                        "RWT scheduler loop alive — no eligible day this week "
                        "(configured days %s, skip_until=%s)",
                        list(config.days_of_week or []), config.skip_until,
                    )
                return

            if now_local < slot:
                if self._iteration % 30 == 1:
                    self.logger.info(
                        "RWT scheduler waiting for this week's slot: %s (now %s)",
                        slot.isoformat(timespec='minutes'),
                        now_local.isoformat(timespec='minutes'),
                    )
                return

            # Past the slot.  Fire only inside a configured window on a
            # configured day, so a slot missed while the station was down is
            # caught up later the same week rather than firing at an arbitrary
            # hour (or being lost entirely).
            monday = now_local.date() - timedelta(days=now_local.weekday())
            if now_local.weekday() not in _eligible_days(config, monday):
                if self._iteration % 60 == 1:
                    self.logger.info(
                        "RWT slot %s missed; waiting for the next configured day "
                        "this week to catch up",
                        slot.isoformat(timespec='minutes'),
                    )
                return

            window_start, window_end = _window_bounds(config, now_local.date(), now_local.tzinfo)
            if not (window_start <= now_local <= window_end):
                if self._iteration % 30 == 1:
                    self.logger.info(
                        "RWT scheduler waiting for window: local time %02d:%02d, "
                        "window %02d:%02d–%02d:%02d",
                        now_local.hour, now_local.minute,
                        config.start_hour, config.start_minute,
                        config.end_hour, config.end_minute,
                    )
                return

            # All conditions met - send RWT.
            #
            # Cross-worker lock: this module is imported by every Gunicorn
            # worker, so each worker's process has its own RWTScheduler
            # thread that hits this branch at the same minute.  Without a
            # lock, an N-worker deployment would record N duplicate
            # ManualEASActivation rows per window every minute (visible
            # in production journals as identifier RWT-AUTO-<same ts>
            # logged by multiple gunicorn PIDs in the same second).  Use
            # Redis SETNX keyed on (schedule_id, ISO week) so exactly one
            # worker per *week* wins the race; losers silently skip.  The
            # key is the week rather than the date because the test is a
            # weekly obligation — a date key would let a second broadcast
            # through on the next configured day of the same week.  TTL is
            # 8 days so the key outlives its week even when the slot lands
            # on a Monday.  If Redis is unreachable we fall back to the
            # historical behaviour (best-effort fire from every worker)
            # rather than block RWT entirely on a Redis outage.
            try:
                from app_core.extensions import get_redis_client
                redis_client = get_redis_client()
                lock_key = "rwt:fired:%s:%d-W%02d" % ((config.id,) + week_key(now_local))
                acquired = redis_client.set(lock_key, str(now_local), nx=True, ex=8 * 86400)
                if not acquired:
                    if self._iteration % 60 == 1:
                        self.logger.info(
                            "RWT fire-lock already held for %s — another worker "
                            "is handling this week's broadcast, skipping",
                            lock_key,
                        )
                    return
            except Exception as lock_exc:
                self.logger.warning(
                    "Could not acquire RWT fire-lock (Redis unreachable?): %s — "
                    "proceeding without cross-worker deduplication",
                    lock_exc,
                )

            self.logger.info(
                "Triggering automatic RWT broadcast for week %d-W%02d "
                "(slot %s, local now %s)",
                week_key(now_local)[0], week_key(now_local)[1],
                slot.isoformat(timespec='minutes'),
                now_local.isoformat(timespec='seconds'),
            )
            result = trigger_rwt_broadcast(config, self.logger)

            if result.get('success'):
                self.logger.info("Automatic RWT broadcast completed successfully")
            else:
                self.logger.error("Automatic RWT broadcast failed: %s", result.get('error'))

        except Exception as exc:
            self.logger.error("Failed to check/send RWT: %s", exc, exc_info=True)
        finally:
            if ctx is not None:
                ctx.pop()


# Global scheduler instance
_scheduler: Optional[RWTScheduler] = None


def get_scheduler(app: Optional[Flask] = None) -> RWTScheduler:
    """Get the global RWT scheduler instance."""
    global _scheduler
    if _scheduler is None:
        if app is None:
            raise RuntimeError(
                "A Flask application must be provided the first time the RWT scheduler is accessed"
            )
        _scheduler = RWTScheduler(app)
    return _scheduler


def start_scheduler(app: Optional[Flask] = None):
    """Start the global RWT scheduler."""
    scheduler = get_scheduler(app)
    scheduler.start()


def stop_scheduler():
    """Stop the global RWT scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None


__all__ = [
    "RWTScheduler",
    "compute_next_fire",
    "get_scheduler",
    "start_scheduler",
    "stop_scheduler",
    "trigger_rwt_broadcast",
    "week_key",
    "weekly_fire_slot",
]
