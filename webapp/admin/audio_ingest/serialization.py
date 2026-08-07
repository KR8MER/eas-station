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

"""Turning audio sources into the JSON payloads the API returns."""

import logging
import json
import time
from typing import Any, Dict, Optional, Tuple
from app_core.models import (
    AudioSourceMetrics,
    AudioSourceConfigDB,
)
from app_core.audio import AudioIngestController
from app_core.audio.ingest import AudioSourceConfig, AudioSourceType
from app_core.audio.sources import create_audio_source

from .controller import _get_audio_controller, _read_audio_metrics_from_redis
from .sanitize import _merge_metadata, _redact_device_params, _sanitize_bool, _sanitize_float
from .streaming import _get_auto_streaming_service, _get_icecast_stream_url

logger = logging.getLogger(__name__)


def _restore_audio_source_from_db_config(
    controller: AudioIngestController,
    db_config: AudioSourceConfigDB,
) -> Optional[Any]:
    """Recreate an audio adapter from its persisted configuration."""

    config_params = db_config.config_params or {}

    try:
        source_type = AudioSourceType(db_config.source_type)
    except ValueError:
        logger.error(
            "Unknown audio source type %s for %s", db_config.source_type, db_config.name
        )
        return None

    runtime_config = AudioSourceConfig(
        source_type=source_type,
        name=db_config.name,
        enabled=db_config.enabled,
        priority=db_config.priority,
        sample_rate=config_params.get('sample_rate', 44100),  # Native rate for source/stream
        channels=config_params.get('channels', 1),
        buffer_size=config_params.get('buffer_size', 4096),
        silence_threshold_db=config_params.get('silence_threshold_db', -60.0),
        silence_duration_seconds=config_params.get('silence_duration_seconds', 5.0),
        device_params=config_params.get('device_params', {}),
    )

    adapter = create_audio_source(runtime_config)

    # Copy rather than mutate the adapter's own metadata dict, and redact first:
    # every device_params key is surfaced here, so without this the stream
    # credentials reach the API through metrics.metadata even on the paths that
    # redact `config.device_params` itself.
    metadata = dict(adapter.metrics.metadata or {})
    device_params = _redact_device_params(config_params.get('device_params'))
    if isinstance(device_params, dict):
        for key, value in device_params.items():
            if value is None:
                continue
            metadata.setdefault(str(key), value)
    adapter.metrics.metadata = metadata

    controller.add_source(adapter)

    started = False
    if db_config.auto_start:
        try:
            started = controller.start_source(db_config.name)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Failed to auto-start audio source %s during restore: %s",
                db_config.name,
                exc,
            )

    if started:
        auto_streaming = _get_auto_streaming_service()
        if auto_streaming and auto_streaming.is_available():
            try:
                auto_streaming.add_source(db_config.name, adapter)
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to attach Icecast stream for %s during restore: %s",
                    db_config.name,
                    exc,
                )

    logger.info("Restored audio source %s from database configuration", db_config.name)
    return adapter


def _get_controller_and_adapter(
    source_name: str,
) -> Tuple[AudioIngestController, Optional[Any], Optional[AudioSourceConfigDB], bool]:
    """Return the audio controller, adapter, DB config, and whether a restore occurred.
    
    Implements retry logic to reduce 503 errors when sources temporarily fail to load.
    """

    controller = _get_audio_controller()
    adapter = controller._sources.get(source_name)
    db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
    restored = False

    if adapter is None and db_config is not None:
        # Try to restore with retry logic (up to 2 retries)
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                adapter = _restore_audio_source_from_db_config(controller, db_config)
                restored = adapter is not None
                if restored:
                    logger.info(
                        "Successfully restored audio source %s on attempt %d",
                        source_name,
                        attempt + 1,
                    )
                    break
            except Exception as exc:  # pylint: disable=broad-except
                if attempt < max_retries:
                    logger.warning(
                        "Failed to restore audio source %s (attempt %d/%d): %s - retrying",
                        source_name,
                        attempt + 1,
                        max_retries + 1,
                        exc,
                    )
                    # Brief delay before retry
                    time.sleep(0.5)
                else:
                    logger.error(
                        "Failed to restore audio source %s after %d attempts: %s",
                        source_name,
                        max_retries + 1,
                        exc,
                        exc_info=True,
                    )
                adapter = None

    return controller, adapter, db_config, restored


def _read_redis_source_data(source_name: str) -> Optional[Dict[str, Any]]:
    """Look up live runtime data for a source from Redis (separated architecture).

    Returns the per-source dict published by audio-service via
    ``audio_controller.sources[<name>]`` or ``None`` if no fresh data exists.
    """
    try:
        redis_metrics = _read_audio_metrics_from_redis()
        if not redis_metrics or 'audio_controller' not in redis_metrics:
            return None

        audio_controller_data = redis_metrics.get('audio_controller')
        if isinstance(audio_controller_data, str):
            audio_controller_data = json.loads(audio_controller_data)

        if not isinstance(audio_controller_data, dict):
            return None

        sources = audio_controller_data.get('sources') or {}
        data = sources.get(source_name)
        if isinstance(data, dict):
            return data
        return None
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to read Redis source data for %s: %s", source_name, exc)
        return None


def _serialize_audio_source_from_db(
    db_config: AudioSourceConfigDB,
    redis_source_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Serialize an audio source from its persisted DB row (and optional live Redis data).

    Used by the edit/detail endpoints so they do not need to instantiate a local
    adapter — which would fail in the separated architecture where audio runs
    in a different process.
    """

    config_params = db_config.config_params or {}
    icecast_url = _get_icecast_stream_url(db_config.name)

    status = 'stopped'
    error_message = None
    if isinstance(redis_source_data, dict):
        status = redis_source_data.get('status') or 'stopped'
        error_message = redis_source_data.get('error_message')

    return {
        'id': db_config.name,
        'name': db_config.name,
        'type': db_config.source_type,
        'status': status,
        'error_message': error_message,
        'enabled': bool(db_config.enabled),
        'priority': db_config.priority,
        'auto_start': bool(db_config.auto_start),
        'description': db_config.description or '',
        'icecast_url': icecast_url,
        'config': {
            'sample_rate': config_params.get('sample_rate', 44100),
            'channels': config_params.get('channels', 1),
            'buffer_size': config_params.get('buffer_size', 4096),
            'silence_threshold_db': config_params.get('silence_threshold_db', -60.0),
            'silence_duration_seconds': config_params.get('silence_duration_seconds', 5.0),
            'device_params': _redact_device_params(config_params.get('device_params', {})),
        },
        'metrics': None,
        'streaming': None,
        'in_memory': bool(redis_source_data),
        'redis_mode': bool(redis_source_data),
    }


def _sanitize_streaming_stats(stats: Optional[Dict[str, Any]], icecast_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """Prepare streaming statistics for API output."""
    if not stats:
        return None

    sanitized: Dict[str, Any] = {}

    for key, value in stats.items():
        if key in {'bitrate_kbps', 'uptime_seconds'}:
            if value is None:
                sanitized[key] = None
            else:
                sanitized[key] = round(float(value), 2)
        elif key in {'bytes_sent', 'reconnect_count', 'port'}:
            sanitized[key] = int(value) if value is not None else None
        elif key == 'running' or key == 'public':
            sanitized[key] = _sanitize_bool(value)
        else:
            sanitized[key] = value

    if icecast_url:
        sanitized.setdefault('url', icecast_url)

    return sanitized


def _serialize_audio_source(
    source_name: str,
    adapter: Any,
    latest_metric: Optional[AudioSourceMetrics] = None,
    icecast_stats: Optional[Dict[str, Any]] = None,
    db_config: Optional[AudioSourceConfigDB] = None,
) -> Dict[str, Any]:
    """Serialize an audio source adapter to JSON-compatible dict."""
    config = adapter.config

    # Fetch database config for additional fields
    if db_config is None:
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()

    # Check if Icecast streaming is available for this source
    icecast_url = _get_icecast_stream_url(source_name)

    metadata = _merge_metadata(
        adapter.metrics.metadata if adapter.metrics else None,
        latest_metric.source_metadata if latest_metric else None,
        {
            'stream_url': icecast_url,
            'icecast_stream_url': icecast_url,
            'icecast_mount': icecast_stats.get('mount') if icecast_stats else None,
            'icecast_server': icecast_stats.get('server') if icecast_stats else None,
            'icecast_port': icecast_stats.get('port') if icecast_stats else None,
            'bitrate_kbps': icecast_stats.get('bitrate_kbps') if icecast_stats else None,
            'codec': (icecast_stats.get('format') or '').lower() if icecast_stats else None,
            'codec_version': (
                'Icecast MP3' if icecast_stats and (icecast_stats.get('format') or '').lower() == 'mp3'
                else 'Icecast OGG' if icecast_stats and (icecast_stats.get('format') or '').lower() == 'ogg'
                else None
            ),
            'icy_name': icecast_stats.get('name') if icecast_stats else None,
            'icy_genre': icecast_stats.get('genre') if icecast_stats else None,
        }
    )

    streaming = {
        'icecast': _sanitize_streaming_stats(icecast_stats, icecast_url)
    } if icecast_stats else None

    metrics_payload = None
    if adapter.metrics:
        metrics_payload = {
            'timestamp': adapter.metrics.timestamp,
            'peak_level_db': _sanitize_float(adapter.metrics.peak_level_db),
            'rms_level_db': _sanitize_float(adapter.metrics.rms_level_db),
            'sample_rate': adapter.metrics.sample_rate,
            'channels': adapter.metrics.channels,
            'frames_captured': adapter.metrics.frames_captured,
            'silence_detected': _sanitize_bool(adapter.metrics.silence_detected),
            'buffer_utilization': _sanitize_float(adapter.metrics.buffer_utilization),
            'metadata': metadata,
        }
    elif latest_metric:
        metrics_payload = {
            'timestamp': latest_metric.timestamp.isoformat() if latest_metric.timestamp else None,
            'peak_level_db': _sanitize_float(latest_metric.peak_level_db) if latest_metric.peak_level_db is not None else None,
            'rms_level_db': _sanitize_float(latest_metric.rms_level_db) if latest_metric.rms_level_db is not None else None,
            'sample_rate': latest_metric.sample_rate,
            'channels': latest_metric.channels,
            'frames_captured': latest_metric.frames_captured,
            'silence_detected': _sanitize_bool(latest_metric.silence_detected) if latest_metric.silence_detected is not None else False,
            'buffer_utilization': _sanitize_float(latest_metric.buffer_utilization) if latest_metric.buffer_utilization is not None else 0.0,
            'metadata': metadata,
        }

    if metadata and metrics_payload is None:
        # Ensure metadata is not lost when no metrics are available
        metrics_payload = {'metadata': metadata}

    return {
        'id': source_name,
        'name': config.name,
        'type': config.source_type.value,
        'status': adapter.status.value,
        'error_message': adapter.error_message,
        'enabled': _sanitize_bool(config.enabled),
        'priority': config.priority,
        'auto_start': _sanitize_bool(db_config.auto_start) if db_config else False,
        'description': db_config.description if db_config else '',
        'icecast_url': icecast_url,  # NEW: Icecast stream URL if available
        'config': {
            'sample_rate': config.sample_rate,
            'channels': config.channels,
            'buffer_size': config.buffer_size,
            'silence_threshold_db': config.silence_threshold_db,
            'silence_duration_seconds': config.silence_duration_seconds,
            'device_params': _redact_device_params(config.device_params),
        },
        'metrics': metrics_payload,
        'streaming': streaming,
    }
