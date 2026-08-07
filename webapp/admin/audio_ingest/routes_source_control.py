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

"""Start/stop and stream-test endpoints for audio sources."""

import logging
from flask import jsonify, request
from app_core.cache import clear_audio_source_cache
from app_core.models import (
    AudioSourceConfigDB,
)
from app_core.audio.redis_commands import get_audio_command_publisher
from app_core.auth.roles import require_permission

from .blueprint import audio_ingest_bp
from .probe import _probe_stream_url

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/sources/test-stream', methods=['POST'])
@require_permission('receivers.configure')
def api_test_stream_url():
    """Preflight a stream URL and report whether it is reachable.

    Surfaces authentication-required streams (HTTP 401/403) with an explicit
    message instead of letting them fail silently when the source later starts.
    """
    try:
        data = request.get_json(silent=True) or {}
        url = data.get('url') or data.get('stream_url')
        if not url:
            return jsonify({'ok': False, 'message': 'Stream URL is required.'}), 400

        result = _probe_stream_url(
            url,
            username=data.get('auth_username', '') or '',
            password=data.get('auth_password', '') or '',
            auth_header=data.get('auth_header', '') or '',
        )
        if result['ok']:
            logger.info('Stream preflight OK for %s (HTTP %s)', url, result.get('status'))
        else:
            logger.warning('Stream preflight failed for %s: %s', url, result.get('message'))
        return jsonify(result), 200
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('Error testing stream URL: %s', exc)
        return jsonify({'ok': False, 'message': f'Internal error testing stream: {exc}'}), 500


@audio_ingest_bp.route('/api/audio/sources/<path:source_name>/start', methods=['POST'])
@require_permission('receivers.configure')
def api_start_audio_source(source_name: str):
    """
    Start audio ingestion from a source.

    In separated architecture, this publishes a command to Redis for audio-service to execute.
    """
    try:
        # Check if source exists in database
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if not db_config:
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Create the source first using POST /api/audio/sources'
            }), 404

        # Publish command to audio-service via Redis
        try:
            publisher = get_audio_command_publisher()
            result = publisher.start_source(source_name)

            if result['success']:
                # Drop the cached source list so the next /api/audio/sources
                # call reflects the new running state immediately.
                clear_audio_source_cache(source_name)
                logger.info('Published start command for audio source: %s', source_name)
                return jsonify({
                    'message': f'Start command sent to audio-service for source: {source_name}',
                    'command_id': result.get('command_id')
                })
            else:
                logger.error('Failed to publish start command: %s', result.get('message'))
                return jsonify({'error': result.get('message')}), 500

        except Exception as e:
            logger.error('Redis Pub/Sub unavailable, cannot send start command: %s', e)
            return jsonify({
                'error': 'Audio service communication unavailable',
                'hint': 'Check Redis connection and audio-service process status'
            }), 503

    except Exception as exc:
        logger.error('Error starting audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/sources/<path:source_name>/stop', methods=['POST'])
@require_permission('receivers.configure')
def api_stop_audio_source(source_name: str):
    """
    Stop audio ingestion from a source.

    In separated architecture, this publishes a command to Redis for audio-service to execute.
    """
    try:
        # Check if source exists in database
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if not db_config:
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Create the source first using POST /api/audio/sources'
            }), 404

        # Publish command to audio-service via Redis
        try:
            publisher = get_audio_command_publisher()
            result = publisher.stop_source(source_name)

            if result['success']:
                # Drop the cached source list so the next /api/audio/sources
                # call reflects the stopped state immediately.
                clear_audio_source_cache(source_name)
                logger.info('Published stop command for audio source: %s', source_name)
                return jsonify({
                    'message': f'Stop command sent to audio-service for source: {source_name}',
                    'command_id': result.get('command_id')
                })
            else:
                logger.error('Failed to publish stop command: %s', result.get('message'))
                return jsonify({'error': result.get('message')}), 500

        except Exception as e:
            logger.error('Redis Pub/Sub unavailable, cannot send stop command: %s', e)
            return jsonify({
                'error': 'Audio service communication unavailable',
                'hint': 'Check Redis connection and audio-service process status'
            }), 503

    except Exception as exc:
        logger.error('Error stopping audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500
