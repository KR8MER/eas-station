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

"""Deleting audio sources.

Split out of ``routes_sources_write`` (which still owns create/update) once
that module crossed the ~400-line module-size guidance in AGENTS.md.
"""

import logging

from flask import jsonify

from app_core.cache import clear_audio_source_cache
from app_core.extensions import db
from app_core.models import AudioSourceConfigDB, RadioReceiver
from app_core.audio.redis_commands import get_audio_command_publisher
from app_core.auth.roles import require_permission

from .blueprint import audio_ingest_bp

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/sources/<path:source_name>', methods=['DELETE'])
@require_permission('receivers.configure')
def api_delete_audio_source(source_name: str):
    """Delete an audio source.

    Queries the database directly without attempting to restore the source in
    memory.  A fire-and-forget stop command is sent to the audio-service so
    that delete succeeds even when the audio-service is unresponsive.

    For radio-managed (SDR) sources the corresponding RadioReceiver row has
    its ``audio_output`` flag cleared so that ``sync_radio_receiver_audio_sources``
    does not silently recreate the source on the next audio-service restart.
    """
    try:
        # Clear cache before deleting
        clear_audio_source_cache(source_name)

        # Query DB directly – do NOT call _get_controller_and_adapter, which
        # would try to restore/start the source and time out when the
        # audio-service is dead.
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()

        if not db_config:
            # Source already absent from DB — still clean up Redis/in-memory state so
            # the source stops appearing in the UI (it may linger in Redis metrics from
            # the last time the audio service had it loaded).
            try:
                publisher = get_audio_command_publisher()
                publisher.delete_source(source_name, wait_for_response=False)
            except Exception:
                pass
            logger.info('Source %s already absent from DB — cleaned up runtime state', source_name)
            return jsonify({'message': 'Audio source deleted successfully'})

        config_params = db_config.config_params or {}
        is_radio_managed = config_params.get('managed_by') == 'radio'

        # For radio-managed sources, disable audio_output on the RadioReceiver
        # so that sync_radio_receiver_audio_sources() does not recreate this
        # source the next time the audio service starts.
        if is_radio_managed:
            receiver_id = config_params.get('device_params', {}).get('receiver_id')
            if receiver_id:
                try:
                    receiver = RadioReceiver.query.filter_by(identifier=receiver_id).first()
                    if receiver and receiver.audio_output:
                        receiver.audio_output = False
                        logger.info(
                            'Disabled audio_output on RadioReceiver %s to prevent '
                            'source %s from being recreated by sync',
                            receiver_id, source_name,
                        )
                except Exception as recv_exc:
                    logger.warning(
                        'Could not disable audio_output on receiver %s (continuing): %s',
                        receiver_id, recv_exc,
                    )

        # Tell the audio-service to delete the source (fire-and-forget so that a
        # dead audio-service never blocks the delete).  Using source_delete rather
        # than source_stop ensures the audio-service also removes the source from
        # memory and stops any associated Icecast stream.
        try:
            publisher = get_audio_command_publisher()
            publisher.delete_source(source_name, wait_for_response=False)
        except Exception as stop_exc:
            logger.warning(
                'Could not send delete command to audio-service for %s (continuing with delete): %s',
                source_name, stop_exc,
            )

        # Remove from database and commit in a single transaction.
        # The RadioReceiver update (if any) is included in the same commit.
        db.session.delete(db_config)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        logger.info('Deleted audio source from database: %s', source_name)
        return jsonify({'message': 'Audio source deleted successfully'})

    except Exception as exc:
        logger.error('Error deleting audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500
