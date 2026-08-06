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

"""Icecast configuration and stream control endpoints."""

import logging
from flask import Blueprint, Flask, jsonify, render_template, request, current_app, Response, stream_with_context
from werkzeug.exceptions import BadRequest
from app_core.auth.roles import require_permission

from .blueprint import audio_ingest_bp
from .streaming import _reload_auto_streaming_from_env, _start_auto_streaming_service, _stop_auto_streaming_service

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/icecast/config', methods=['GET'])
def api_get_icecast_config():
    """Get Icecast rebroadcast configuration."""
    try:
        from app_core.icecast_settings import get_icecast_settings

        settings = get_icecast_settings()

        config = {
            'enabled': settings.enabled,
            'server': settings.server,
            'port': settings.port,
            'external_port': settings.external_port,
            'password': settings.source_password,
            'admin_user': settings.admin_user or '',
            'admin_password': settings.admin_password or '',
            'public_hostname': settings.public_hostname or '',
            'mount': settings.default_mount,
            'name': settings.stream_name,
            'description': settings.stream_description,
            'genre': settings.stream_genre,
            'bitrate': settings.stream_bitrate,
            'format': settings.stream_format,
            'public': settings.stream_public,
        }

        return jsonify(config)
    except Exception as exc:
        logger.error('Error getting Icecast config: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/icecast/config', methods=['POST'])
@require_permission('system.configure')
def api_update_icecast_config():
    """Update Icecast rebroadcast configuration."""
    try:
        data = request.get_json()
        if not isinstance(data, dict):
            raise BadRequest('Invalid JSON payload')

        required_fields = ['server', 'port', 'password', 'mount']
        for field in required_fields:
            value = data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise BadRequest(f'Missing required field: {field}')

        server = str(data['server']).strip()
        try:
            port = int(data.get('port', 8000))
        except (TypeError, ValueError):
            raise BadRequest('Port must be an integer')

        external_port = data.get('external_port')
        if external_port not in (None, ''):
            try:
                external_port = int(external_port)
            except (TypeError, ValueError):
                raise BadRequest('External port must be an integer')
        else:
            external_port = None

        password = str(data['password']).strip()
        admin_user = str(data.get('admin_user', '') or '').strip()
        admin_password = str(data.get('admin_password', '') or '')
        public_hostname = str(data.get('public_hostname', '') or '').strip()

        mount = str(data['mount']).strip().lstrip('/') or 'monitor.mp3'
        name = str(data.get('name', 'EAS Station Audio') or 'EAS Station Audio').strip()
        description = str(
            data.get('description', 'Emergency Alert System Audio Monitor')
            or 'Emergency Alert System Audio Monitor'
        ).strip()
        genre = str(data.get('genre', 'Emergency') or 'Emergency').strip()
        try:
            bitrate = int(data.get('bitrate', 128))
        except (TypeError, ValueError):
            raise BadRequest('Bitrate must be an integer')

        format_value = str(data.get('format', 'mp3') or 'mp3').lower()
        if format_value not in {'mp3', 'ogg'}:
            raise BadRequest('Format must be either "mp3" or "ogg"')

        enabled = bool(data.get('enabled', True))
        public = bool(data.get('public', False))

        from app_core.icecast_settings import update_icecast_settings, invalidate_icecast_settings_cache

        # Update database
        settings = update_icecast_settings({
            'enabled': enabled,
            'server': server,
            'port': port,
            'external_port': external_port,
            'public_hostname': public_hostname,
            'source_password': password,
            'admin_user': admin_user,
            'admin_password': admin_password,
            'default_mount': mount,
            'stream_name': name,
            'stream_description': description,
            'stream_genre': genre,
            'stream_bitrate': bitrate,
            'stream_format': format_value,
            'stream_public': public,
        })

        # Invalidate cache to force reload
        invalidate_icecast_settings_cache()
        _reload_auto_streaming_from_env()

        response_config = {
            'enabled': enabled,
            'server': server,
            'port': port,
            'external_port': external_port,
            'password': password,
            'admin_user': admin_user,
            'admin_password': admin_password,
            'public_hostname': public_hostname,
            'mount': mount,
            'name': name,
            'description': description,
            'genre': genre,
            'bitrate': bitrate,
            'format': format_value,
            'public': public,
        }

        return jsonify({
            'message': 'Icecast configuration updated',
            'config': response_config
        })

    except Exception as exc:
        logger.error('Error updating Icecast config: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/icecast/start', methods=['POST'])
@require_permission('system.configure')
def api_start_icecast_stream():
    """Start the Icecast auto-streaming service."""

    try:
        success, message, status = _start_auto_streaming_service()
        response = {'message': message}
        if status is not None:
            response['status'] = status

        return jsonify(response), 200 if success else 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('Error starting Icecast streaming service: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/icecast/stop', methods=['POST'])
@require_permission('system.configure')
def api_stop_icecast_stream():
    """Stop the Icecast auto-streaming service."""

    try:
        success, message, status = _stop_auto_streaming_service()
        response = {'message': message}
        if status is not None:
            response['status'] = status

        return jsonify(response), 200 if success else 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('Error stopping Icecast streaming service: %s', exc)
        return jsonify({'error': str(exc)}), 500
