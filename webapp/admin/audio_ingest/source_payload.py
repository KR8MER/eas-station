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

"""Rendering one audio source into the JSON object the sources list returns.

Two shapes, one per live-state origin: ``_serialize_from_redis`` for a source
the audio service is reporting on, ``_serialize_db_only`` for one nothing is.
The third origin — a live adapter in the local controller — is already served
by ``serialization._serialize_audio_source``, which the detail endpoints share.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app_core.models import AudioSourceConfigDB, AudioSourceMetrics

from .sanitize import (
    _merge_metadata,
    _redact_device_params,
    _sanitize_bool,
    _sanitize_float,
)
from .serialization import _sanitize_streaming_stats

logger = logging.getLogger(__name__)


def _first_defined(*candidates):
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None


def _config_block(db_config: AudioSourceConfigDB) -> Dict[str, Any]:
    """The stored config, with the documented defaults filled in.

    ``device_params`` goes through ``_redact_device_params``: it comes straight
    off the database row and holds the stream credentials.
    """
    config_params = db_config.config_params or {}
    return {
        'sample_rate': config_params.get('sample_rate', 44100),
        'channels': config_params.get('channels', 1),
        'buffer_size': config_params.get('buffer_size', 4096),
        'silence_threshold_db': config_params.get('silence_threshold_db', -60.0),
        'silence_duration_seconds': config_params.get('silence_duration_seconds', 5.0),
        'dead_air_enabled': config_params.get('dead_air_enabled', False),
        'dead_air_level_threshold_db': config_params.get('dead_air_level_threshold_db', -65.0),
        'dead_air_detect_open_carrier': config_params.get('dead_air_detect_open_carrier', True),
        'dead_air_flatness_threshold_pct': config_params.get('dead_air_flatness_threshold_pct', 25),
        'dead_air_duration_seconds': config_params.get('dead_air_duration_seconds', 20.0),
        'device_params': _redact_device_params(config_params.get('device_params', {})),
    }


def _redis_metrics_timestamp(
    redis_source_data: Optional[Dict[str, Any]],
    latest_metric: Optional[AudioSourceMetrics],
) -> Optional[str]:
    """Redis publishes the timestamp as an epoch float, a datetime or a string."""
    redis_timestamp = redis_source_data.get('timestamp') if redis_source_data else None

    if isinstance(redis_timestamp, (int, float)):
        return datetime.fromtimestamp(redis_timestamp).isoformat()
    if isinstance(redis_timestamp, datetime):
        return redis_timestamp.isoformat()
    if isinstance(redis_timestamp, str):
        return redis_timestamp
    if latest_metric and latest_metric.timestamp:
        return latest_metric.timestamp.isoformat()
    return None


def _serialize_from_redis(
    db_config: AudioSourceConfigDB,
    redis_source_data: Dict[str, Any],
    latest_metric: Optional[AudioSourceMetrics],
    icecast_stats: Optional[Dict[str, Any]],
    icecast_url: Optional[str],
) -> Dict[str, Any]:
    """Describe a source from the audio service's Redis snapshot.

    Live values win; the persisted metric row fills any field Redis omitted.
    """
    redis_streaming_stats = (
        redis_source_data.get('streaming') if isinstance(redis_source_data, dict) else None
    )
    if not icecast_stats and redis_streaming_stats:
        if isinstance(redis_streaming_stats, dict):
            icecast_stats = redis_streaming_stats.get('icecast') or redis_streaming_stats

    if not icecast_url and icecast_stats and isinstance(icecast_stats, dict):
        mount = icecast_stats.get('mount')
        server = icecast_stats.get('server')
        port = icecast_stats.get('port')
        if mount and server and port:
            icecast_url = f"http://{server}:{port}/{mount}"

    metadata = _merge_metadata(
        redis_source_data.get('metadata'),
        latest_metric.source_metadata if latest_metric else None,
        {
            'stream_url': icecast_url,
            'icecast_stream_url': icecast_url,
        }
    )

    metrics_payload: Optional[Dict[str, Any]] = None
    if latest_metric or redis_source_data:
        peak_value = _first_defined(
            redis_source_data.get('peak_level_db') if redis_source_data else None,
            latest_metric.peak_level_db if latest_metric else None,
        )
        rms_value = _first_defined(
            redis_source_data.get('rms_level_db') if redis_source_data else None,
            latest_metric.rms_level_db if latest_metric else None,
        )
        buffer_utilization_value = _first_defined(
            redis_source_data.get('buffer_utilization') if redis_source_data else None,
            latest_metric.buffer_utilization if latest_metric else None,
            0.0,
        )

        metrics_payload = {
            'timestamp': _redis_metrics_timestamp(redis_source_data, latest_metric),
            'peak_level_db': _sanitize_float(peak_value) if peak_value is not None else None,
            'rms_level_db': _sanitize_float(rms_value) if rms_value is not None else None,
            'sample_rate': _first_defined(
                redis_source_data.get('sample_rate') if redis_source_data else None,
                latest_metric.sample_rate if latest_metric else None,
            ),
            'channels': _first_defined(
                redis_source_data.get('channels') if redis_source_data else None,
                latest_metric.channels if latest_metric else None,
            ),
            'frames_captured': _first_defined(
                redis_source_data.get('frames_captured') if redis_source_data else None,
                latest_metric.frames_captured if latest_metric else None,
            ),
            'silence_detected': _sanitize_bool(
                _first_defined(
                    redis_source_data.get('silence_detected') if redis_source_data else None,
                    latest_metric.silence_detected if latest_metric else False,
                    False,
                )
            ),
            'buffer_utilization': _sanitize_float(buffer_utilization_value),
            'metadata': metadata,
        }
    elif metadata:
        metrics_payload = {'metadata': metadata}

    return {
        'id': db_config.name,  # Add id field for JavaScript compatibility
        'name': db_config.name,
        'type': db_config.source_type,
        'status': _first_defined(
            redis_source_data.get('status') if redis_source_data else None, 'unknown'
        ),
        'enabled': db_config.enabled,
        'priority': db_config.priority,
        'auto_start': db_config.auto_start,
        'description': db_config.description or '',
        'config': _config_block(db_config),
        'metrics': metrics_payload,
        'error_message': None,
        'in_memory': True,  # Running in audio-service process
        'icecast_url': icecast_url,
        'streaming': {
            'icecast': _sanitize_streaming_stats(icecast_stats, icecast_url)
        } if icecast_stats else None,
        'redis_mode': True,  # Indicate data came from Redis
    }


def _serialize_db_only(
    db_config: AudioSourceConfigDB,
    latest_metric: Optional[AudioSourceMetrics],
    icecast_stats: Optional[Dict[str, Any]],
    icecast_url: Optional[str],
    audio_service_dead: bool,
) -> Dict[str, Any]:
    """Describe a source that nothing is currently reporting on."""
    icecast_format = (icecast_stats.get('format') or '').lower() if icecast_stats else None

    metadata = _merge_metadata(
        latest_metric.source_metadata if latest_metric else None,
        {
            'stream_url': icecast_url,
            'icecast_stream_url': icecast_url,
            'icecast_mount': icecast_stats.get('mount') if icecast_stats else None,
            'icecast_server': icecast_stats.get('server') if icecast_stats else None,
            'icecast_port': icecast_stats.get('port') if icecast_stats else None,
            'bitrate_kbps': icecast_stats.get('bitrate_kbps') if icecast_stats else None,
            'codec': icecast_format,
            'codec_version': (
                'Icecast MP3' if icecast_format == 'mp3'
                else 'Icecast OGG' if icecast_format == 'ogg'
                else None
            ),
            'icy_name': icecast_stats.get('name') if icecast_stats else None,
            'icy_genre': icecast_stats.get('genre') if icecast_stats else None,
        }
    )

    metrics_payload: Optional[Dict[str, Any]] = None
    if latest_metric:
        metrics_payload = {
            'timestamp': latest_metric.timestamp.isoformat() if latest_metric.timestamp else None,
            'peak_level_db': (
                _sanitize_float(latest_metric.peak_level_db)
                if latest_metric.peak_level_db is not None else None
            ),
            'rms_level_db': (
                _sanitize_float(latest_metric.rms_level_db)
                if latest_metric.rms_level_db is not None else None
            ),
            'sample_rate': latest_metric.sample_rate,
            'channels': latest_metric.channels,
            'frames_captured': latest_metric.frames_captured,
            'silence_detected': (
                _sanitize_bool(latest_metric.silence_detected)
                if latest_metric.silence_detected is not None else False
            ),
            'buffer_utilization': (
                _sanitize_float(latest_metric.buffer_utilization)
                if latest_metric.buffer_utilization is not None else 0.0
            ),
            'metadata': metadata,
        }
    elif metadata:
        metrics_payload = {'metadata': metadata}

    # When the audio-service is dead and this source should auto-start,
    # report it as 'error' so the UI shows a clear failure badge rather
    # than the misleading grey "Stopped" badge.
    failed_to_start = audio_service_dead and db_config.auto_start
    fallback_status = 'error' if failed_to_start else 'stopped'
    fallback_error = (
        'Audio service is not running – source failed to start'
        if failed_to_start
        else 'Not started'
    )

    return {
        'id': db_config.name,  # Add id field for JavaScript compatibility
        'name': db_config.name,
        'type': db_config.source_type,
        'status': fallback_status,
        'enabled': db_config.enabled,
        'priority': db_config.priority,
        'auto_start': db_config.auto_start,
        'description': db_config.description or '',
        'config': _config_block(db_config),
        'metrics': metrics_payload,
        'error_message': fallback_error,
        'in_memory': False,
        'icecast_url': icecast_url,
        'streaming': {
            'icecast': _sanitize_streaming_stats(icecast_stats, icecast_url)
        } if icecast_stats else None,
    }
