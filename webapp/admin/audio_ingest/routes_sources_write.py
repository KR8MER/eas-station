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

"""Creating, updating and deleting audio sources.

Split from the read endpoints along the permission boundary: every handler
here carries ``@require_permission('receivers.configure')``, and every handler
in ``routes_sources`` carries none.
"""

import logging

from flask import jsonify, request

from app_core.cache import clear_audio_source_cache
from app_core.extensions import db
from app_core.models import AudioSourceConfigDB, RadioReceiver
from app_core.audio.ingest import AudioSourceConfig, AudioSourceType
from app_core.audio.sources import create_audio_source
from app_core.audio.redis_commands import get_audio_command_publisher
from app_core.auth.roles import require_permission

from .blueprint import audio_ingest_bp
from .controller import _get_audio_controller
from .probe import _probe_stream_url
from .serialization import (
    _read_redis_source_data,
    _serialize_audio_source,
    _serialize_audio_source_from_db,
)
from .streaming import _get_auto_streaming_service

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/sources', methods=['POST'])
@require_permission('receivers.configure')
def api_create_audio_source():
    """Create a new audio source."""
    try:
        # Clear cache before creating
        clear_audio_source_cache()
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        source_type = data.get('type')
        name = data.get('name')
        if not source_type or not name:
            return jsonify({'error': 'type and name are required'}), 400

        # Parse source type
        try:
            audio_type = AudioSourceType(source_type)
        except ValueError:
            return jsonify({'error': f'Invalid source type: {source_type}'}), 400

        # Preflight stream URLs so authentication-required streams (HTTP 401/403)
        # are reported clearly at add time instead of failing silently on start.
        # Callers can bypass with skip_url_check=true after acknowledging a warning.
        if audio_type == AudioSourceType.STREAM and not data.get('skip_url_check'):
            dp = data.get('device_params') or {}
            stream_url = dp.get('url')
            if stream_url:
                probe = _probe_stream_url(
                    stream_url,
                    username=dp.get('auth_username', '') or '',
                    password=dp.get('auth_password', '') or '',
                    auth_header=dp.get('auth_header', '') or '',
                )
                if not probe['ok']:
                    return jsonify({
                        'error': probe['message'],
                        'stream_check': probe,
                        'hint': 'Fix the URL/credentials, or resubmit with skip_url_check=true to add it anyway.'
                    }), 400

        # Get controller first to ensure it's initialized
        # (prevents duplicate adapter creation when controller initializes from DB)
        controller = _get_audio_controller()

        # Check if source already exists in DATABASE (source of truth)
        existing_db_config = AudioSourceConfigDB.query.filter_by(name=name).first()
        if existing_db_config:
            return jsonify({
                'error': f'Source "{name}" already exists in database',
                'hint': 'Use DELETE /api/audio/sources/{name} first, or use PATCH to update'
            }), 400

        # Also check if source exists in memory (shouldn't happen, but be safe)
        if name in controller._sources:
            return jsonify({
                'error': f'Source "{name}" exists in memory but not in database (inconsistent state)',
                'hint': 'Contact system administrator - database sync issue'
            }), 500

        # Create configuration
        config = AudioSourceConfig(
            source_type=audio_type,
            name=name,
            enabled=data.get('enabled', True),
            priority=data.get('priority', 100),
            sample_rate=data.get('sample_rate', 44100),  # Native rate for source/stream
            channels=data.get('channels', 1),
            buffer_size=data.get('buffer_size', 4096),
            silence_threshold_db=data.get('silence_threshold_db', -60.0),
            silence_duration_seconds=data.get('silence_duration_seconds', 5.0),
            device_params=data.get('device_params', {}),
        )

        # Create adapter
        adapter = create_audio_source(config)

        # Add to controller
        controller.add_source(adapter)

        # Save to database AFTER adding to controller
        db_config = AudioSourceConfigDB(
            name=name,
            source_type=source_type,
            config_params={
                'sample_rate': config.sample_rate,
                'channels': config.channels,
                'buffer_size': config.buffer_size,
                'silence_threshold_db': config.silence_threshold_db,
                'silence_duration_seconds': config.silence_duration_seconds,
                'device_params': config.device_params,
            },
            priority=config.priority,
            enabled=config.enabled,
            auto_start=data.get('auto_start', False),
            description=data.get('description', ''),
        )
        db.session.add(db_config)
        try:
            db.session.commit()
        except Exception:
            # If database commit fails, remove from controller to keep state consistent
            db.session.rollback()
            controller.remove_source(name)
            raise

        logger.info('Created audio source: %s (Type: %s)', name, source_type)

        streaming_service = _get_auto_streaming_service()
        if streaming_service and streaming_service.is_available():
            try:
                streaming_service.add_source(name, adapter)
                logger.info(f'✅ Registered {name} with Icecast streaming')
            except Exception as e:
                logger.warning(f'⚠️ Failed to register {name} with Icecast: {e}')

        # Notify audio-service so the new source is added to the running
        # process without a service restart.  Optionally auto-start it if
        # requested.
        try:
            publisher = get_audio_command_publisher()
            publisher.add_source({
                'name': name,
                'source_type': source_type,
                'enabled': config.enabled,
                'priority': config.priority,
                'sample_rate': config.sample_rate,
                'channels': config.channels,
                'buffer_size': config.buffer_size,
                'silence_threshold_db': config.silence_threshold_db,
                'silence_duration_seconds': config.silence_duration_seconds,
                'device_params': config.device_params,
            })
            if data.get('auto_start'):
                publisher.start_source(name, wait_for_response=False)
        except Exception as pub_exc:  # pylint: disable=broad-except
            logger.warning(
                'Failed to publish source_add for %s (DB row created, will load on next audio-service restart): %s',
                name, pub_exc,
            )

        # Clear cache so the next list call sees the new source immediately.
        clear_audio_source_cache(name)

        return jsonify({
            'source': _serialize_audio_source(name, adapter),
            'message': 'Audio source created successfully'
        }), 201

    except Exception as exc:
        logger.error('Error creating audio source: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/sources/<path:source_name>', methods=['PATCH'])
@require_permission('receivers.configure')
def api_update_audio_source(source_name: str):
    """Update audio source configuration.

    Updates the database (source of truth) and publishes a ``source_update``
    command to the audio-service so the running source picks up the new
    settings without a service restart.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if db_config is None:
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Check /api/audio/sources for available sources'
            }), 404

        if 'enabled' in data:
            db_config.enabled = bool(data['enabled'])
        if 'priority' in data:
            db_config.priority = int(data['priority'])
        if 'auto_start' in data:
            db_config.auto_start = bool(data['auto_start'])
        if 'description' in data:
            db_config.description = data['description']

        config_params = dict(db_config.config_params or {})
        if 'silence_threshold_db' in data:
            config_params['silence_threshold_db'] = float(data['silence_threshold_db'])
        if 'silence_duration_seconds' in data:
            config_params['silence_duration_seconds'] = float(data['silence_duration_seconds'])
        if 'device_params' in data and isinstance(data['device_params'], dict):
            device_params = dict(config_params.get('device_params', {}))
            device_params.update(data['device_params'])
            config_params['device_params'] = device_params
        db_config.config_params = config_params

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        # Mirror the change into the local controller (integrated mode); ignore
        # failures because in separated mode there is no local adapter.
        try:
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)
            if adapter is not None:
                cfg = adapter.config
                if 'enabled' in data:
                    cfg.enabled = bool(data['enabled'])
                if 'priority' in data:
                    cfg.priority = int(data['priority'])
                if 'silence_threshold_db' in data:
                    cfg.silence_threshold_db = float(data['silence_threshold_db'])
                if 'silence_duration_seconds' in data:
                    cfg.silence_duration_seconds = float(data['silence_duration_seconds'])
                if 'device_params' in data and isinstance(data['device_params'], dict):
                    cfg.device_params.update(data['device_params'])
        except Exception as local_exc:  # pylint: disable=broad-except
            logger.debug('Local adapter update skipped for %s: %s', source_name, local_exc)

        # Notify audio-service so the running source applies the new config
        # without a full service restart.
        try:
            publisher = get_audio_command_publisher()
            publisher.update_source(source_name, dict(data))
        except Exception as pub_exc:  # pylint: disable=broad-except
            logger.warning(
                'Failed to publish source_update for %s (DB updated, service will pick up on next restart): %s',
                source_name, pub_exc,
            )

        clear_audio_source_cache(source_name)

        logger.info('Updated audio source: %s', source_name)

        redis_source_data = _read_redis_source_data(source_name)
        return jsonify({
            'source': _serialize_audio_source_from_db(db_config, redis_source_data),
            'message': 'Audio source updated successfully'
        })

    except Exception as exc:
        logger.error('Error updating audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500


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
