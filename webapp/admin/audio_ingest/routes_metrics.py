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

"""Audio metrics endpoints."""

import logging
import time
from flask import jsonify
from sqlalchemy import desc
from app_core.models import (
    AudioSourceMetrics,
    AudioSourceConfigDB,
)

from .blueprint import audio_ingest_bp
from .controller import _read_audio_metrics_from_redis
from .sanitize import _db_to_linear, _sanitize_bool, _sanitize_float

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/metrics', methods=['GET'])
def api_get_audio_metrics():
    """Get real-time metrics for all audio sources."""
    try:
        # SEPARATED ARCHITECTURE: Try Redis first
        redis_metrics = _read_audio_metrics_from_redis()
        source_metrics = []
        broadcast_stats = {}
        active_source = None
        # Build a quick lookup of configured sources so we can enrich Redis metrics
        db_configs = {cfg.name: cfg for cfg in AudioSourceConfigDB.query.all()}

        if redis_metrics:
            # Parse audio controller data from Redis
            try:
                import json
                audio_controller_data = redis_metrics.get('audio_controller')
                if isinstance(audio_controller_data, str):
                    audio_controller_data = json.loads(audio_controller_data)

                if audio_controller_data:
                    active_source = audio_controller_data.get('active_source')
                    redis_sources = audio_controller_data.get('sources', {})

                    # Build source metrics from Redis data
                    for source_name, source_data in redis_sources.items():
                        config = db_configs.get(source_name)
                        source_metrics.append({
                            'source_id': source_name,
                            'source_name': source_name,
                            'source_type': getattr(config.source_type, 'value', None) if config else 'unknown',
                            'source_description': config.description if config else None,
                            'priority': config.priority if config else None,
                            'source_status': source_data.get('status', 'unknown'),
                            'timestamp': source_data.get('timestamp', redis_metrics.get('timestamp', time.time())),
                            'sample_rate': source_data.get('sample_rate'),
                            'channels': source_data.get('channels', 2),
                            'peak_level_db': _sanitize_float(source_data.get('peak_level_db', -120.0)),
                            'rms_level_db': _sanitize_float(source_data.get('rms_level_db', -120.0)),
                            'buffer_utilization': _sanitize_float(source_data.get('buffer_utilization', 0.0)),
                            'frames_captured': source_data.get('frames_captured', 0),
                            'silence_detected': source_data.get('silence_detected', False),
                            'redis_mode': True,
                        })

                # Parse broadcast queue data
                broadcast_queue_data = redis_metrics.get('broadcast_queue')
                if isinstance(broadcast_queue_data, str):
                    broadcast_queue_data = json.loads(broadcast_queue_data)
                if broadcast_queue_data:
                    broadcast_stats = broadcast_queue_data

                logger.debug(f"Using Redis metrics: {len(source_metrics)} sources, active={active_source}")
            except Exception as e:
                logger.warning(f"Failed to parse Redis metrics: {e}")
                redis_metrics = None

        # SEPARATED ARCHITECTURE: No fallback to local controller
        # In separated architecture, web application process doesn't run audio processing.
        # Audio-service publishes metrics to Redis. If Redis has no metrics,
        # return empty arrays (audio-service not running or not publishing).
        if not redis_metrics:
            logger.debug("No Redis metrics available - audio-service may not be running")

        # Also get recent database metrics
        db_metrics = (
            AudioSourceMetrics.query
            .order_by(desc(AudioSourceMetrics.timestamp))
            .limit(100)
            .all()
        )

        db_metrics_list = []
        for metric in db_metrics:
            db_metrics_list.append({
                'id': metric.id,
                'source_name': metric.source_name,
                'source_type': metric.source_type,
                'peak_level_db': _sanitize_float(metric.peak_level_db) if metric.peak_level_db is not None else -120.0,
                'rms_level_db': _sanitize_float(metric.rms_level_db) if metric.rms_level_db is not None else -120.0,
                'sample_rate': metric.sample_rate,
                'channels': metric.channels,
                'frames_captured': metric.frames_captured,
                'silence_detected': _sanitize_bool(metric.silence_detected) if metric.silence_detected is not None else False,
                'clipping_detected': _sanitize_bool(metric.clipping_detected) if metric.clipping_detected is not None else False,
                'buffer_utilization': _sanitize_float(metric.buffer_utilization) if metric.buffer_utilization is not None else 0.0,
                'timestamp': metric.timestamp.isoformat() if metric.timestamp else None,
            })

        response = jsonify({
            'live_metrics': source_metrics,
            'recent_metrics': db_metrics_list,
            'total_sources': len(source_metrics),
            'active_source': active_source,
            'broadcast_stats': broadcast_stats,
        })

        # Explicitly disable HTTP caching so VU meters stay real-time
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

        return response

    except Exception as exc:
        logger.error('Error getting audio metrics: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/metrics/latest', methods=['GET'])
def api_get_audio_metrics_latest():
    """Get latest audio metrics snapshot for display screens.

    Returns a simplified view of current audio state, optimized for
    LED/VFD/OLED displays that need quick access to current values.

    Response format:
    {
        "peak_level_db": -12.5,
        "rms_level_db": -18.2,
        "peak_level_linear": 0.75,
        "rms_level_linear": 0.45,
        "silence_detected": false,
        "active_source": "noaa_radio",
        "source_status": "capturing",
        "timestamp": "2025-01-15T12:00:00Z"
    }
    """
    try:
        # Read metrics from Redis (published by audio-service)
        redis_metrics = _read_audio_metrics_from_redis()

        if redis_metrics:
            audio_controller_data = redis_metrics.get('audio_controller')
            if isinstance(audio_controller_data, str):
                import json
                audio_controller_data = json.loads(audio_controller_data)

            if audio_controller_data:
                active_source = audio_controller_data.get('active_source')
                sources = audio_controller_data.get('sources', {})

                # Get metrics from active source, or first available source
                source_data = None
                if active_source and active_source in sources:
                    source_data = sources[active_source]
                elif sources:
                    # Use first available source
                    first_source = next(iter(sources.keys()))
                    source_data = sources[first_source]
                    active_source = first_source

                if source_data:
                    peak_linear = _db_to_linear(_sanitize_float(source_data.get('peak_level_db', -120.0)))
                    rms_linear = _db_to_linear(_sanitize_float(source_data.get('rms_level_db', -120.0)))
                    response = jsonify({
                        'peak_level_db': _sanitize_float(source_data.get('peak_level_db', -120.0)),
                        'rms_level_db': _sanitize_float(source_data.get('rms_level_db', -120.0)),
                        'peak_level_linear': peak_linear,
                        'rms_level_linear': rms_linear,
                        'peak_level_percent': round(peak_linear * 100.0, 1),
                        'rms_level_percent': round(rms_linear * 100.0, 1),
                        'silence_detected': source_data.get('silence_detected', False),
                        'active_source': active_source,
                        'source_status': source_data.get('status', 'unknown'),
                        'timestamp': source_data.get('timestamp', time.time()),
                    })
                    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                    return response

        # No metrics available - return defaults
        response = jsonify({
            'peak_level_db': -120.0,
            'rms_level_db': -120.0,
            'peak_level_linear': 0.0,
            'rms_level_linear': 0.0,
            'peak_level_percent': 0.0,
            'rms_level_percent': 0.0,
            'silence_detected': True,
            'active_source': None,
            'source_status': 'no_data',
            'timestamp': time.time(),
            'error': 'No audio metrics available from audio-service',
        })
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response

    except Exception as exc:
        logger.error('Error getting latest audio metrics: %s', exc)
        return jsonify({'error': str(exc)}), 500
