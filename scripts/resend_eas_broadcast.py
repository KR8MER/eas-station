#!/usr/bin/env python3
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

"""Re-broadcast a single stored EAS message in an isolated process.

The web UI's "Resend on Air" button hands the actual playout off to this
script via a detached subprocess.  Running here — rather than inline in the
Flask request handler — keeps the playout (audio player + holding the
broadcast-state marker for the full composite duration) off the gunicorn
**gevent** workers, which would otherwise be blocked for the entire alert.

GPIO is **not** keyed here.  The ``eas-station-gpio`` subprocess owns the
physical relay lines and keys them off the Redis broadcast-state marker this
script sets and clears (the same marker that drives every browser's live
countdown overlay), so the relay stays asserted for exactly the broadcast
window without any other process claiming the pins.
"""

import argparse
import os
import sys
import tempfile
import time

# Make the project root importable when invoked by absolute path.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _run(message_id: int, operator: str | None) -> int:
    # Imported lazily so ``--help`` doesn't pay the full app-import cost.
    from app import app, db, EASMessage
    from app_core.models import SystemLog
    from app_utils.eas import (
        set_broadcast_active,
        clear_broadcast_active,
        play_broadcast_audio,
        _wav_duration_seconds,
    )
    from app_utils.event_codes import EVENT_CODE_REGISTRY

    with app.app_context():
        logger = app.logger.getChild('resend')

        message = EASMessage.query.get(message_id)
        if message is None:
            logger.error('Resend aborted: EASMessage #%s not found', message_id)
            return 2
        if not message.audio_data:
            logger.error('Resend aborted: EASMessage #%s has no stored audio', message_id)
            return 3

        # Needed so a GPIO-triggered Dump/Abort mid-resend can still send a
        # compliant EOM burst -- see play_broadcast_audio() below.
        eom_wav = message.eom_audio_data

        metadata = message.metadata_payload or {}
        event_code = metadata.get('event_code') or ''
        # Prefer the real WAV length so the relay is held for the exact
        # composite duration even if no audio device is configured here.
        actual_audio_duration = _wav_duration_seconds(message.audio_data) or 0.0
        metadata_duration = (
            metadata.get('playback_duration_seconds')
            or metadata.get('duration_seconds')
            or 0.0
        )
        playback_duration = actual_audio_duration or float(metadata_duration) or 60.0

        event_info = EVENT_CODE_REGISTRY.get(event_code, {})
        event_label = (
            event_info.get('name', event_code) if isinstance(event_info, dict) else event_code
        ) or 'EAS Alert'

        audio_player_cmd_raw = app.config.get('AUDIO_PLAYER_CMD') or os.environ.get('AUDIO_PLAYER_CMD')
        if isinstance(audio_player_cmd_raw, str):
            audio_player_cmd = audio_player_cmd_raw.split() if audio_player_cmd_raw.strip() else None
        elif isinstance(audio_player_cmd_raw, list):
            audio_player_cmd = audio_player_cmd_raw or None
        else:
            audio_player_cmd = None

        tmp_file = None
        audio_played = False
        audio_injected = False
        airchain_signalled = False

        try:
            tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', prefix='eas_resend_', delete=False)
            tmp_file.write(message.audio_data)
            tmp_file.flush()
            tmp_path = tmp_file.name
            tmp_file.close()

            # Anchor the hold window to this instant.  Publishing the
            # broadcast-state marker is the rising edge the eas-station-gpio
            # subprocess watches to key the relay, so the relay stays asserted
            # for exactly the composite audio duration without this process
            # touching GPIO.
            activation_ts = time.monotonic()
            airchain_signalled = set_broadcast_active(
                event_code=event_code,
                label=event_label,
                duration_seconds=playback_duration,
                source='resend',
                identifier=str(message_id),
            )

            # Re-inject the stored composite audio into the live Icecast
            # air-chain so stream listeners hear the resend exactly as they
            # hear a fresh alert (the live path does this via
            # EASBroadcaster.handle_alert → inject_eas_audio).  The broadcast
            # queues and IcecastStreamer threads live in the audio-service
            # process; this detached resend process cannot reach those in-memory
            # objects directly, so it asks the audio-service to do the injection
            # over the Redis command channel.  Failure here is non-fatal: GPIO
            # is still keyed and the air-chain is still held for the full
            # duration below.
            try:
                from app_core.audio.redis_commands import get_audio_command_publisher
                publisher = get_audio_command_publisher()
                # Short timeout: a healthy audio-service queues the audio and
                # confirms in well under a second.  Keeping it short means an
                # absent/unresponsive audio-service does not inflate the
                # GPIO hold (which is anchored before this call).
                inject_resp = publisher.inject_eas_audio(message_id, timeout=10.0)
                audio_injected = bool(inject_resp.get('success'))
                if audio_injected:
                    logger.info('Resend audio injected into air-chain for message %s', message_id)
                else:
                    logger.info(
                        'Resend air-chain injection reported no audio for message %s: %s',
                        message_id, inject_resp.get('message'),
                    )
            except Exception as exc:
                logger.warning('Resend air-chain injection failed (non-fatal): %s', exc)

            if audio_player_cmd:
                try:
                    command = list(audio_player_cmd) + [tmp_path]
                    # play_broadcast_audio() (not a bare subprocess.run()) so
                    # a GPIO-triggered Dump/Abort can find this process's PID
                    # and the isolated EOM burst -- see
                    # app_core.audio.gpio_input_actions.abort_current_broadcast.
                    play_broadcast_audio(
                        command, logger=logger, eom_wav=eom_wav,
                        timeout=float(playback_duration) + 30,
                    )
                    audio_played = True
                except Exception as exc:
                    logger.warning('Resend audio playback failed: %s', exc)

            # Hold the broadcast marker for the full composite duration
            # regardless of whether a player was configured or blocked,
            # measuring from the marker write so the relay duration (released by
            # the GPIO subprocess on the marker's falling edge) matches the
            # alert length.
            remaining = float(playback_duration) - (time.monotonic() - activation_ts)
            if remaining > 0:
                time.sleep(remaining)

        finally:
            # Falling edge: clearing the marker releases the relay in the GPIO
            # subprocess (which also self-releases on the marker TTL).  Pass the
            # identifier so an overlapping newer broadcast's marker isn't erased.
            clear_broadcast_active(identifier=str(message_id))
            if tmp_file is not None:
                try:
                    os.unlink(tmp_file.name)
                except OSError:
                    pass

        try:
            db.session.add(
                SystemLog(
                    level='INFO',
                    message='EAS message resent',
                    module='eas',
                    details={
                        'message_id': message_id,
                        'event_code': event_code,
                        # The GPIO subprocess keys the relay off the broadcast
                        # marker we published; record whether that marker was
                        # actually written rather than a per-process activation
                        # result (the write is best-effort).
                        'airchain_signalled': airchain_signalled,
                        'audio_played': audio_played if audio_player_cmd else None,
                        'audio_injected': audio_injected,
                        'playback_duration_seconds': round(float(playback_duration), 2),
                        'resent_by': operator,
                    },
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

        logger.info(
            'Resend complete for EASMessage #%s (event=%s, injected=%s, held=%.1fs)',
            message_id, event_code or 'unknown', audio_injected, playback_duration,
        )
        return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Re-broadcast a single stored EAS message (GPIO + audio playout).'
    )
    parser.add_argument('--message-id', type=int, required=True, help='EASMessage primary key to resend.')
    parser.add_argument('--operator', default=None, help='Username that triggered the resend (for audit logs).')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return _run(args.message_id, args.operator)
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        print(f'resend_eas_broadcast failed: {exc}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
