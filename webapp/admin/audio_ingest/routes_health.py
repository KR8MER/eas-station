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

"""Audio health endpoints and the health dashboard page."""

import logging
import json
import time
from flask import Blueprint, Flask, jsonify, render_template, request, current_app, Response, stream_with_context
from sqlalchemy import desc
from app_core.cache import cache, clear_audio_source_cache
from app_core.models import (
    AudioAlert,
    AudioHealthStatus,
    AudioSourceMetrics,
    AudioSourceConfigDB,
    RadioReceiver,
)
from app_core.audio.ingest import AudioSourceConfig, AudioSourceType, AudioSourceStatus

from .blueprint import audio_ingest_bp
from .controller import _get_audio_controller, _read_audio_metrics_from_redis
from .sanitize import _sanitize_bool, _sanitize_float

logger = logging.getLogger(__name__)


@audio_ingest_bp.route('/api/audio/health', methods=['GET'])
@cache.cached(timeout=20, key_prefix='audio_health')
def api_get_audio_health():
    """Get audio system health status."""
    try:
        # Get recent health status from database
        health_records = (
            AudioHealthStatus.query
            .order_by(desc(AudioHealthStatus.timestamp))
            .limit(50)
            .all()
        )

        health_list = []
        for record in health_records:
            health_list.append({
                'id': record.id,
                'source_name': record.source_name,
                'health_score': _sanitize_float(record.health_score) if record.health_score is not None else 0.0,
                'is_active': _sanitize_bool(record.is_active) if record.is_active is not None else False,
                'is_healthy': _sanitize_bool(record.is_healthy) if record.is_healthy is not None else False,
                'silence_detected': _sanitize_bool(record.silence_detected) if record.silence_detected is not None else False,
                'error_detected': _sanitize_bool(record.error_detected) if record.error_detected is not None else False,
                'uptime_seconds': _sanitize_float(record.uptime_seconds) if record.uptime_seconds is not None else 0.0,
                'silence_duration_seconds': _sanitize_float(record.silence_duration_seconds) if record.silence_duration_seconds is not None else 0.0,
                'time_since_last_signal_seconds': _sanitize_float(record.time_since_last_signal_seconds) if record.time_since_last_signal_seconds is not None else 0.0,
                'level_trend': record.level_trend,
                'trend_value_db': _sanitize_float(record.trend_value_db) if record.trend_value_db is not None else 0.0,
                'timestamp': record.timestamp.isoformat() if record.timestamp else None,
            })

        # Get controller status
        controller = _get_audio_controller()
        active_sources = sum(
            1 for adapter in controller._sources.values()
            if adapter.status == AudioSourceStatus.RUNNING
        )

        # Calculate overall health
        if health_list:
            avg_health = sum(h['health_score'] for h in health_list[:10]) / min(len(health_list), 10)
            avg_health = _sanitize_float(avg_health)
            overall_status = 'healthy' if avg_health >= 80 else 'degraded' if avg_health >= 50 else 'critical'
        else:
            avg_health = 0.0
            overall_status = 'unknown'

        return jsonify({
            'health_records': health_list,
            'overall_health_score': avg_health,
            'health_score': avg_health,  # Add for UI compatibility
            'overall_status': overall_status,
            'active_sources': active_sources,
            'total_sources': len(controller._sources),
        })

    except Exception as exc:
        logger.error('Error getting audio health: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/health/dashboard', methods=['GET'])
def api_get_health_dashboard():
    """Get comprehensive health metrics for dashboard display.

    In separated architecture, reads from Redis where audio-service publishes metrics.
    """
    try:
        # SEPARATED ARCHITECTURE: Read from Redis
        redis_metrics = _read_audio_metrics_from_redis()

        source_health = {}
        categorized_sources = {
            'healthy': [],
            'degraded': [],
            'failed': []
        }
        healthy_count = 0
        degraded_count = 0
        failed_count = 0
        active_source = None
        total_sources = 0

        if redis_metrics:
            try:
                import json
                audio_controller_data = redis_metrics.get('audio_controller')
                if isinstance(audio_controller_data, str):
                    audio_controller_data = json.loads(audio_controller_data)

                if audio_controller_data:
                    active_source = audio_controller_data.get('active_source')
                    redis_sources = audio_controller_data.get('sources', {})
                    total_sources = len(redis_sources)

                    for source_name, source_data in redis_sources.items():
                        status = source_data.get('status', 'unknown')
                        silence_detected = source_data.get('silence_detected', True)
                        peak_level_db = _sanitize_float(source_data.get('peak_level_db', -120.0))
                        rms_level_db = _sanitize_float(source_data.get('rms_level_db', -120.0))

                        # Determine health status
                        if status == 'running':
                            if not silence_detected:
                                health_status = 'healthy'
                                healthy_count += 1
                                categorized_sources['healthy'].append(source_name)
                            else:
                                health_status = 'degraded'
                                degraded_count += 1
                                categorized_sources['degraded'].append(source_name)
                        else:
                            health_status = 'failed'
                            failed_count += 1
                            categorized_sources['failed'].append(source_name)

                        # Build source health data
                        source_health[source_name] = {
                            'status': health_status,
                            'uptime_seconds': source_data.get('uptime_seconds', 0),
                            'peak_level_db': peak_level_db,
                            'rms_level_db': rms_level_db,
                            'is_silent': silence_detected,
                            'buffer_fill_percentage': _sanitize_float(source_data.get('buffer_utilization', 0.0)) * 100,
                            'restart_count': source_data.get('restart_count', 0),
                            'error_message': source_data.get('error_message'),
                        }

            except Exception as e:
                logger.warning(f"Failed to parse Redis metrics for health dashboard: {e}")

        # Calculate overall health score (0-100)
        if total_sources > 0:
            health_score = (
                (healthy_count * 100) +
                (degraded_count * 50) +
                (failed_count * 0)
            ) / total_sources
        else:
            health_score = 0

        return jsonify({
            'overall_health_score': health_score,
            'total_sources': total_sources,
            'healthy_count': healthy_count,
            'degraded_count': degraded_count,
            'failed_count': failed_count,
            'categorized_sources': categorized_sources,
            'source_health': source_health,
            'active_source': active_source,
            'timestamp': time.time(),
            'redis_mode': redis_metrics is not None,
        })

    except Exception as exc:
        logger.error('Error getting health dashboard: %s', exc, exc_info=True)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/api/audio/health/metrics', methods=['GET'])
def api_get_health_metrics():
    """Get real-time metrics for all sources.

    In separated architecture, reads from Redis where audio-service publishes metrics.
    """
    try:
        # SEPARATED ARCHITECTURE: Read from Redis
        redis_metrics = _read_audio_metrics_from_redis()
        metrics_list = []

        if redis_metrics:
            try:
                import json
                audio_controller_data = redis_metrics.get('audio_controller')
                if isinstance(audio_controller_data, str):
                    audio_controller_data = json.loads(audio_controller_data)

                if audio_controller_data:
                    redis_sources = audio_controller_data.get('sources', {})

                    for source_name, source_data in redis_sources.items():
                        metrics_list.append({
                            'source_name': source_name,
                            'timestamp': source_data.get('timestamp', time.time()),
                            'peak_level_db': _sanitize_float(source_data.get('peak_level_db', -120.0)),
                            'rms_level_db': _sanitize_float(source_data.get('rms_level_db', -120.0)),
                            'sample_rate': source_data.get('sample_rate', 0),
                            'frames_captured': source_data.get('frames_captured', 0),
                            'silence_detected': source_data.get('silence_detected', True),
                            'buffer_utilization': _sanitize_float(source_data.get('buffer_utilization', 0.0)) * 100,
                        })

            except Exception as e:
                logger.warning(f"Failed to parse Redis metrics: {e}")

        return jsonify({
            'metrics': metrics_list,
            'timestamp': time.time(),
            'redis_mode': redis_metrics is not None,
        })

    except Exception as exc:
        logger.error('Error getting health metrics: %s', exc)
        return jsonify({'error': str(exc)}), 500


@audio_ingest_bp.route('/audio/health/dashboard')
def audio_health_dashboard():
    """Render the health monitoring dashboard page."""
    return render_template('audio/health_dashboard.html')
