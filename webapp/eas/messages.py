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

        The actual playout (GPIO activation, audio playback, and the hold for
        the full composite duration) is delegated to a detached helper process
        (``scripts/resend_eas_broadcast.py``) so this request returns at once.
        Doing the work inline would key GPIO from inside a gunicorn *gevent*
        worker: instantiating the ``lgpio`` backend there stalls the gevent
        hub for the whole alert (see ``app_utils/gpio.py``), which made the
        entire site unresponsive for minutes and let gunicorn's 300 s
        ``--timeout`` kill the worker mid-broadcast.  Every other broadcast in
        the system already runs in a non-gevent service process; the resend
        now does too.  Browsers still get the live countdown overlay because
        it is driven by the Redis broadcast-state marker the helper sets and
        clears (see ``set_broadcast_active``).
        """
        import os
        import subprocess
        import sys

        from app_utils.eas import get_broadcast_state

        message = EASMessage.query.get_or_404(message_id)

        if not message.audio_data:
            return jsonify({'error': 'No audio data stored for this message — cannot resend.'}), 422

        metadata = message.metadata_payload or {}
        event_code = metadata.get('event_code') or ''

        # Refuse to stack a second broadcast on top of one already on the air.
        # The air-chain overlay tells operators not to do this, but guard the
        # endpoint too so a double-click — or a forwarded alert already in
        # flight — cannot key the same relays from two processes at once.
        if get_broadcast_state().get('active'):
            return jsonify({
                'error': 'A broadcast is already on the air. Wait for it to finish before resending.',
            }), 409

        username = getattr(g.current_user, 'username', None)
        script_path = os.path.join(current_app.root_path, 'scripts', 'resend_eas_broadcast.py')
        command = [sys.executable, script_path, '--message-id', str(message_id)]
        if username:
            command += ['--operator', username]

        try:
            # start_new_session detaches the child so it survives this worker
            # and is never reaped/killed when the request greenlet ends.
            subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                command,
                cwd=current_app.root_path,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            logger.error('Failed to launch resend worker for message %s: %s', message_id, exc)
            return jsonify({'error': 'Unable to start re-transmission.'}), 500

        logger.info('Re-transmission started for EASMessage #%s by %s', message_id, username or 'system')

        return jsonify({
            'message': f'EAS message #{message_id} re-transmission started.',
            'id': message_id,
            'event_code': event_code,
            'status': 'started',
        }), 202


def _static_text_url(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    static_prefix = get_eas_static_prefix()
    text_path = '/'.join(part for part in [static_prefix, filename] if part)
    return url_for('static', filename=text_path) if text_path else None
