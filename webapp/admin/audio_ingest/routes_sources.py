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

"""Reading audio sources: the collection listing and one source's detail.

The write endpoints live in ``routes_sources_write``; the reconciliation
behind the collection listing lives in ``listing``.
"""

import logging
from flask import jsonify
from app_core.cache import cache
from app_core.models import (
    AudioSourceConfigDB,
)

from .blueprint import audio_ingest_bp
from .controller import _get_audio_controller
from .listing import build_source_listing
from .serialization import _read_redis_source_data, _serialize_audio_source, _serialize_audio_source_from_db

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/sources', methods=['GET'])
@cache.cached(timeout=30, key_prefix='audio_source_list')
def api_get_audio_sources():
    """List all configured audio sources.

    Cached for 30 seconds to reduce database load during rapid polling.

    The reconciliation between the database, the local controller and the audio
    service's Redis snapshot lives in ``listing.build_source_listing``.
    """
    try:
        return jsonify(build_source_listing())
    except Exception as exc:
        logger.error('Error getting audio sources: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/sources/<path:source_name>', methods=['GET'])
def api_get_audio_source(source_name: str):
    """Get details of a specific audio source.

    The configuration is sourced from the database (the source of truth) so the
    endpoint succeeds even when the audio-service is running in a separate
    process and the web process has no local adapter.  Live status, when
    available, is overlaid from Redis.
    """
    try:
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()

        if db_config is None:
            # Fall back to a local adapter if one happens to exist in this process
            controller = _get_audio_controller()
            adapter = controller._sources.get(source_name)
            if adapter is not None:
                return jsonify(_serialize_audio_source(source_name, adapter))
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Check /api/audio/sources for available sources'
            }), 404

        redis_source_data = _read_redis_source_data(source_name)
        return jsonify(_serialize_audio_source_from_db(db_config, redis_source_data))

    except Exception as exc:
        logger.error('Error getting audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500
