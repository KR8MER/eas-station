"""Administrative routes for managing generated EAS messages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from flask import g, jsonify, request, url_for

from app_core.extensions import db
from app_core.models import EASMessage, SystemLog
from app_core.eas_storage import get_eas_static_prefix, remove_eas_files
from app_utils import utc_now


def register_message_admin_routes(app, logger) -> None:
    """Register administrative endpoints for audio messages."""

    @app.route('/admin/eas_messages', methods=['GET'])
    def admin_eas_messages():
        if not app.config.get('EAS_BROADCAST_ENABLED', False):
            return jsonify({'messages': [], 'total': 0})

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

            return jsonify({'messages': items, 'total': total})
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error('Failed to list EAS messages: %s', exc)
            return jsonify({'error': 'Unable to load EAS messages'}), 500

    @app.route('/admin/eas_messages/<int:message_id>', methods=['DELETE'])
    def admin_delete_eas_message(message_id: int):
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

    @app.route('/admin/eas_messages/purge', methods=['POST'])
    def admin_purge_eas_messages():
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


def _static_text_url(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    static_prefix = get_eas_static_prefix()
    text_path = '/'.join(part for part in [static_prefix, filename] if part)
    return url_for('static', filename=text_path) if text_path else None
