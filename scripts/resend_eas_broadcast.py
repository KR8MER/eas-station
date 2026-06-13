#!/usr/bin/env python3
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

"""Re-broadcast a single stored EAS message in an isolated process.

The web UI's "Resend on Air" button hands the actual playout off to this
script via a detached subprocess.  Running here — rather than inline in the
Flask request handler — matters for two reasons:

1.  The web app is served by gunicorn **gevent** workers.  Driving GPIO means
    instantiating the ``lgpio`` backend, which starts a native notification
    thread that stalls the gevent hub for the whole alert (see the note in
    ``app_utils/gpio.py``).  That froze the entire site for minutes and let
    gunicorn's 300 s ``--timeout`` kill the worker mid-broadcast.  A plain
    Python subprocess has no gevent hub, so the hardware calls are safe and
    the web workers stay responsive.

2.  The relay must stay keyed for exactly the composite audio length.  In a
    dedicated process the hold window is deterministic: activate, play, hold
    until the audio duration has elapsed, then force-release — instead of the
    relay lingering until a watchdog or worker-timeout fires.

All connected browsers still get the live countdown overlay because it is
driven by the Redis broadcast-state marker this script sets and clears.
"""

import argparse
import os
import subprocess
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
        _wav_duration_seconds,
    )
    from app_utils.event_codes import EVENT_CODE_REGISTRY
    from app_utils.gpio import (
        GPIOController,
        GPIOActivationType,
        GPIOBehaviorManager,
        load_gpio_behavior_matrix_from_db,
        load_gpio_pin_configs_from_db,
    )

    with app.app_context():
        logger = app.logger.getChild('resend')

        message = EASMessage.query.get(message_id)
        if message is None:
            logger.error('Resend aborted: EASMessage #%s not found', message_id)
            return 2
        if not message.audio_data:
            logger.error('Resend aborted: EASMessage #%s has no stored audio', message_id)
            return 3

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

        gpio_controller = None
        gpio_behavior_manager = None
        activated_any = False
        manager_handled = False
        tmp_file = None
        audio_played = False

        try:
            # GPIO pins + behavior matrix live in the database and are loaded
            # via the same helpers the live broadcast path uses, so a resend
            # keys exactly the same relays as a fresh alert.
            try:
                from app_core.hardware_settings import get_gpio_settings, get_oled_settings
                gpio_enabled = get_gpio_settings().get('enabled', False)
                oled_enabled = get_oled_settings().get('enabled', False)
            except Exception:
                gpio_enabled = False
                oled_enabled = False

            gpio_logger = logger.getChild('gpio')
            gpio_configs = (
                load_gpio_pin_configs_from_db(gpio_logger, oled_enabled=oled_enabled)
                if gpio_enabled
                else []
            )
            if gpio_configs:
                try:
                    controller = GPIOController(db_session=db.session, logger=gpio_logger)
                    for cfg in gpio_configs:
                        controller.add_pin(cfg)
                    gpio_controller = controller
                    behavior_matrix = load_gpio_behavior_matrix_from_db(
                        gpio_logger, oled_enabled=oled_enabled
                    )
                    gpio_behavior_manager = GPIOBehaviorManager(
                        controller=controller,
                        pin_configs=gpio_configs,
                        behavior_matrix=behavior_matrix,
                        logger=gpio_logger.getChild('behavior'),
                    )
                    controller.behavior_manager = gpio_behavior_manager
                except Exception as exc:
                    logger.warning('Resend GPIO init failed: %s', exc)

            tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', prefix='eas_resend_', delete=False)
            tmp_file.write(message.audio_data)
            tmp_file.flush()
            tmp_path = tmp_file.name
            tmp_file.close()

            # Activate GPIO and anchor the hold window to this instant so the
            # relay stays keyed for exactly the composite audio duration.
            activation_ts = time.monotonic()
            if gpio_controller:
                try:
                    reason = f'Resend of EASMessage #{message_id} ({event_code or "unknown"})'
                    if gpio_behavior_manager:
                        gpio_behavior_manager.trigger_incoming_alert(
                            alert_id=str(message_id), event_code=event_code,
                        )
                        manager_handled = gpio_behavior_manager.start_alert(
                            alert_id=str(message_id), event_code=event_code, reason=reason,
                        )
                        activated_any = manager_handled
                    if not activated_any:
                        results = gpio_controller.activate_all(
                            activation_type=GPIOActivationType.AUTOMATIC,
                            operator=operator,
                            alert_id=str(message_id),
                            reason=reason,
                        )
                        activated_any = any(results.values())
                except Exception as exc:
                    logger.warning('Resend GPIO activation failed: %s', exc)

            set_broadcast_active(
                event_code=event_code,
                label=event_label,
                duration_seconds=playback_duration,
                source='resend',
            )

            if audio_player_cmd:
                try:
                    command = list(audio_player_cmd) + [tmp_path]
                    subprocess.run(command, check=False, timeout=float(playback_duration) + 30)
                    audio_played = True
                except subprocess.TimeoutExpired:
                    logger.warning('Resend audio playback timed out for message %s', message_id)
                except Exception as exc:
                    logger.warning('Resend audio playback failed: %s', exc)

            # Hold the air-chain for the full composite duration regardless of
            # whether a player was configured or blocked, measuring from the
            # GPIO activation so the relay duration matches the alert length.
            remaining = float(playback_duration) - (time.monotonic() - activation_ts)
            if remaining > 0:
                time.sleep(remaining)

        finally:
            if gpio_controller and activated_any:
                try:
                    if manager_handled and gpio_behavior_manager:
                        gpio_behavior_manager.end_alert(
                            alert_id=str(message_id), event_code=event_code,
                        )
                    else:
                        # force=True: playout is finished, drop the air chain
                        # immediately rather than waiting out each pin's
                        # min-hold (hold_seconds) with the relay still keyed.
                        gpio_controller.deactivate_all(force=True)
                except Exception as exc:
                    logger.warning('Resend GPIO release failed: %s', exc)
            clear_broadcast_active()
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
                        'gpio_activated': activated_any,
                        'audio_played': audio_played if audio_player_cmd else None,
                        'playback_duration_seconds': round(float(playback_duration), 2),
                        'resent_by': operator,
                    },
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

        logger.info(
            'Resend complete for EASMessage #%s (event=%s, gpio=%s, held=%.1fs)',
            message_id, event_code or 'unknown', activated_any, playback_duration,
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
