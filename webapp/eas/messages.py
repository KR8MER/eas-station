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

"""Administrative routes for managing generated EAS messages."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from flask import current_app, g, jsonify, request, url_for

from app_core.extensions import db
from app_core.models import EASMessage, SystemLog
from app_core.eas_storage import get_eas_static_prefix, remove_eas_files
from app_utils import utc_now


def register_message_routes(bp, logger) -> None:
    """Register endpoints for managing generated EAS messages."""

    @bp.route('/messages', methods=['GET'])
    def list_eas_messages():
        eas_enabled = current_app.config.get('EAS_BROADCAST_ENABLED', False)

        try:
            limit = request.args.get('limit', type=int) or 50
            limit = min(max(limit, 1), 500)
            base_query = EASMessage.query.order_by(EASMessage.created_at.desc())
            messages = base_query.limit(limit).all()
            total = base_query.count()

            items = []
            for message in messages:
                data = message.to_dict()
                audio_url = url_for('eas_message_audio', message_id=message.id)
                if message.text_payload:
                    text_url = url_for('eas_message_summary', message_id=message.id)
                else:
                    text_url = _static_text_url(message.text_filename)

                items.append(
                    {
                        **data,
                        'audio_url': audio_url,
                        'text_url': text_url,
                        'detail_url': url_for('audio_detail', message_id=message.id),
                    }
                )

            return jsonify({'messages': items, 'total': total, 'eas_enabled': eas_enabled})
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error('Failed to list EAS messages: %s', exc)
            return jsonify({'error': 'Unable to load EAS messages'}), 500

    @bp.route('/messages/<int:message_id>', methods=['DELETE'])
    def delete_eas_message(message_id: int):
        message = EASMessage.query.get_or_404(message_id)

        try:
            remove_eas_files(message)
            db.session.delete(message)
            db.session.add(
                SystemLog(
                    level='WARNING',
                    message='EAS message deleted',
                    module='eas',
                    details={
                        'message_id': message_id,
                        'deleted_by': getattr(g.current_user, 'username', None),
                    },
                )
            )
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error('Failed to delete EAS message %s: %s', message_id, exc)
            db.session.rollback()
            return jsonify({'error': 'Failed to delete EAS message.'}), 500

        return jsonify({'message': 'EAS message deleted.', 'id': message_id})

    @bp.route('/messages/purge', methods=['POST'])
    def purge_eas_messages():
        if g.current_user is None:
            return jsonify({'error': 'Authentication required.'}), 401

        payload = request.get_json(silent=True) or {}

        ids = payload.get('ids')
        cutoff: Optional[datetime] = None

        if ids:
            try:
                id_list = [int(item) for item in ids if item is not None]
            except (TypeError, ValueError):
                return jsonify({'error': 'ids must be a list of integers.'}), 400
            query = EASMessage.query.filter(EASMessage.id.in_(id_list))
        else:
            before_text = payload.get('before')
            older_than_days = payload.get('older_than_days')

            if before_text:
                normalised = before_text.strip().replace('Z', '+00:00')
                try:
                    cutoff = datetime.fromisoformat(normalised)
                except ValueError:
                    return jsonify({'error': 'Unable to parse the provided cutoff timestamp.'}), 400
            elif older_than_days is not None:
                try:
                    days = int(older_than_days)
                except (TypeError, ValueError):
                    return jsonify({'error': 'older_than_days must be an integer.'}), 400
                if days < 0:
                    return jsonify({'error': 'older_than_days must be non-negative.'}), 400
                cutoff = utc_now() - timedelta(days=days)
            else:
                return jsonify(
                    {'error': 'Provide ids, before, or older_than_days to select messages to purge.'},
                    400,
                )

            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            query = EASMessage.query.filter(EASMessage.created_at < cutoff)

        messages = query.all()
        if not messages:
            return jsonify({'message': 'No EAS messages matched the purge criteria.', 'deleted': 0})

        deleted_ids: List[int] = []
        for message in messages:
            deleted_ids.append(message.id)
            remove_eas_files(message)
            db.session.delete(message)

        try:
            db.session.add(
                SystemLog(
                    level='WARNING',
                    message='EAS messages purged',
                    module='eas',
                    details={
                        'deleted_ids': deleted_ids,
                        'deleted_by': getattr(g.current_user, 'username', None),
                    },
                )
            )
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error('Failed to purge EAS messages: %s', exc)
            db.session.rollback()
            return jsonify({'error': 'Failed to purge EAS messages.'}), 500

        return jsonify(
            {
                'message': f'Deleted {len(deleted_ids)} EAS messages.',
                'deleted': len(deleted_ids),
                'ids': deleted_ids,
            }
        )


    @bp.route('/messages/<int:message_id>/resend', methods=['POST'])
    def resend_eas_message(message_id: int):
        """Re-broadcast a previously generated EAS message.

        Replays the stored composite audio through the configured audio player
        and activates GPIO relays, exactly as if the alert were being sent for
        the first time.  The original EASMessage record is not modified; a new
        SystemLog entry is written instead.
        """
        import os
        import subprocess
        import tempfile
        import time

        from app_utils.eas import set_broadcast_active, clear_broadcast_active, _wav_duration_seconds
        from app_utils.gpio import (
            GPIOController,
            GPIOActivationType,
            GPIOBehaviorManager,
            load_gpio_behavior_matrix_from_db,
            load_gpio_pin_configs_from_db,
        )

        message = EASMessage.query.get_or_404(message_id)

        if not message.audio_data:
            return jsonify({'error': 'No audio data stored for this message — cannot resend.'}), 422

        audio_player_cmd_raw = current_app.config.get('AUDIO_PLAYER_CMD')
        if isinstance(audio_player_cmd_raw, str):
            audio_player_cmd = audio_player_cmd_raw.split() if audio_player_cmd_raw.strip() else None
        elif isinstance(audio_player_cmd_raw, list):
            audio_player_cmd = audio_player_cmd_raw or None
        else:
            audio_player_cmd = None

        metadata = message.metadata_payload or {}
        event_code = metadata.get('event_code') or ''
        # Prefer the actual WAV length so we hold GPIO for the right window
        # even when the audio player exits early (no audio device, etc.).
        actual_audio_duration = _wav_duration_seconds(message.audio_data) if message.audio_data else 0.0
        metadata_duration = metadata.get('playback_duration_seconds') or metadata.get('duration_seconds') or 0.0
        playback_duration = actual_audio_duration or float(metadata_duration) or 60.0

        from app_utils.event_codes import EVENT_CODE_REGISTRY as _ECR
        _ei = _ECR.get(event_code, {})
        _elabel = (_ei.get('name', event_code) if isinstance(_ei, dict) else event_code) or 'EAS Alert'

        gpio_controller = None
        gpio_behavior_manager = None
        activated_any = False
        manager_handled = False
        tmp_file = None
        audio_played = False

        try:
            # Hardware settings (GPIO pins + behavior matrix) live in the
            # database and are loaded via the same helpers the live broadcast
            # path uses, so a resend keys exactly the same relays as a fresh
            # alert.  Reserved-pin filtering honours the OLED setting.
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

            # Activate GPIO
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
                            operator=getattr(g.current_user, 'username', None),
                            alert_id=str(message_id),
                            reason=reason,
                        )
                        activated_any = any(results.values())
                except Exception as exc:
                    logger.warning('Resend GPIO activation failed: %s', exc)

            set_broadcast_active(
                event_code=event_code,
                label=_elabel,
                duration_seconds=playback_duration,
                source='resend',
            )

            audio_played = False
            # Hold the airchain for the full composite duration regardless of
            # whether the player actually blocks (e.g. no audio device on this
            # host) — otherwise GPIO drops as soon as the player exits.
            playout_start = time.monotonic()
            if audio_player_cmd:
                try:
                    command = list(audio_player_cmd) + [tmp_path]
                    subprocess.run(command, check=False, timeout=float(playback_duration) + 30)
                    audio_played = True
                except subprocess.TimeoutExpired:
                    logger.warning('Resend audio playback timed out for message %s', message_id)
                except Exception as exc:
                    logger.warning('Resend audio playback failed: %s', exc)

            remaining_playout = float(playback_duration) - (time.monotonic() - playout_start)
            if remaining_playout > 0:
                time.sleep(remaining_playout)

        finally:
            if gpio_controller and activated_any:
                try:
                    if manager_handled and gpio_behavior_manager:
                        gpio_behavior_manager.end_alert(
                            alert_id=str(message_id), event_code=event_code,
                        )
                    else:
                        # force=True: resend playout is finished, drop the air
                        # chain immediately rather than waiting out each pin's
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
                        'resent_by': getattr(g.current_user, 'username', None),
                    },
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

        return jsonify({
            'message': f'EAS message #{message_id} resent.',
            'id': message_id,
            'event_code': event_code,
            'gpio_activated': activated_any,
            'audio_played': audio_played if audio_player_cmd else False,
        })


def _static_text_url(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    static_prefix = get_eas_static_prefix()
    text_path = '/'.join(part for part in [static_prefix, filename] if part)
    return url_for('static', filename=text_path) if text_path else None
