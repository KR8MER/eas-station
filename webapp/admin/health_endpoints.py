"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""
Health check endpoints for separated architecture.

These endpoints properly read from Redis to show actual audio-service status,
not the empty local controller in the app container.
"""

import logging
import time
from typing import Dict, Any, Optional

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

# Create blueprint
health_bp = Blueprint('health', __name__)


def _read_audio_metrics_from_redis() -> Optional[Dict[str, Any]]:
    """
    Read audio metrics from Redis (published by audio-service container).

    Returns:
        Dict with audio metrics or None if unavailable
    """
    try:
        from app_core.audio.worker_coordinator_redis import read_shared_metrics
        return read_shared_metrics()
    except Exception as e:
        logger.warning(f"Failed to read audio metrics from Redis: {e}")
        return None


@health_bp.route('/api/health/audio-service', methods=['GET'])
def api_audio_service_health():
    """
    Check if audio-service container is alive and publishing metrics.

    This is the primary health check for separated architecture.

    Returns:
        200: Audio-service healthy
        503: Audio-service down or stale
        500: Error checking health
    """
    try:
        redis_metrics = _read_audio_metrics_from_redis()

        if not redis_metrics:
            return jsonify({
                'status': 'down',
                'message': 'No metrics from audio-service',
                'healthy': False,
                'redis_available': False
            }), 503

        # Check heartbeat age
        heartbeat = redis_metrics.get('_heartbeat', 0)
        age = time.time() - heartbeat

        # Stale threshold: 15 seconds
        if age > 15:
            return jsonify({
                'status': 'stale',
                'message': f'Metrics stale ({age:.1f}s old)',
                'healthy': False,
                'age_seconds': age,
                'last_heartbeat': heartbeat,
                'redis_available': True
            }), 503

        # Extract key info
        audio_controller = redis_metrics.get('audio_controller', {})
        eas_monitor = redis_metrics.get('eas_monitor', {})

        return jsonify({
            'status': 'healthy',
            'message': 'Audio-service publishing metrics',
            'healthy': True,
            'age_seconds': age,
            'last_heartbeat': heartbeat,
            'redis_available': True,
            'audio_controller': {
                'sources_count': len(audio_controller.get('sources', {})),
                'active_source': audio_controller.get('active_source'),
            },
            'eas_monitor': {
                'running': eas_monitor.get('running', False),
                'samples_processed': eas_monitor.get('samples_processed', 0),
            }
        })

    except Exception as e:
        logger.error(f"Error checking audio-service health: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'healthy': False
        }), 500


@health_bp.route('/api/health/redis', methods=['GET'])
def api_redis_health():
    """
    Check Redis connection health.

    Returns:
        200: Redis healthy
        503: Redis unavailable
        500: Error checking Redis
    """
    try:
        import redis
        import os

        redis_host = os.getenv('REDIS_HOST', 'redis')
        redis_port = int(os.getenv('REDIS_PORT', '6379'))
        redis_db = int(os.getenv('REDIS_DB', '0'))

        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            socket_connect_timeout=2,
            socket_timeout=2
        )

        # Test connection
        start = time.time()
        r.ping()
        latency_ms = (time.time() - start) * 1000

        # Get info
        info = r.info()

        return jsonify({
            'status': 'healthy',
            'message': 'Redis connection OK',
            'healthy': True,
            'host': redis_host,
            'port': redis_port,
            'db': redis_db,
            'latency_ms': round(latency_ms, 2),
            'version': info.get('redis_version'),
            'uptime_seconds': info.get('uptime_in_seconds'),
            'connected_clients': info.get('connected_clients'),
            'used_memory_human': info.get('used_memory_human'),
        })

    except redis.ConnectionError as e:
        logger.error(f"Redis connection failed: {e}")
        return jsonify({
            'status': 'unavailable',
            'message': f'Cannot connect to Redis: {str(e)}',
            'healthy': False
        }), 503

    except Exception as e:
        logger.error(f"Error checking Redis health: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'healthy': False
        }), 500


@health_bp.route('/api/health/system', methods=['GET'])
def api_system_health():
    """
    Overall system health check (app + audio-service + Redis).

    Returns:
        200: All systems healthy
        503: One or more systems down
        500: Error checking health
    """
    try:
        results = {
            'redis': {'healthy': False},
            'audio_service': {'healthy': False},
            'app': {'healthy': True}  # If we're responding, app is up
        }

        # Check Redis
        try:
            redis_metrics = _read_audio_metrics_from_redis()
            results['redis']['healthy'] = redis_metrics is not None
            if redis_metrics:
                heartbeat = redis_metrics.get('_heartbeat', 0)
                age = time.time() - heartbeat
                results['redis']['age_seconds'] = age
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            results['redis']['error'] = str(e)

        # Check audio-service
        try:
            if results['redis']['healthy']:
                redis_metrics = _read_audio_metrics_from_redis()
                heartbeat = redis_metrics.get('_heartbeat', 0)
                age = time.time() - heartbeat
                results['audio_service']['healthy'] = age < 15
                results['audio_service']['age_seconds'] = age
            else:
                results['audio_service']['healthy'] = False
                results['audio_service']['message'] = 'Redis unavailable, cannot check'
        except Exception as e:
            logger.warning(f"Audio-service health check failed: {e}")
            results['audio_service']['error'] = str(e)

        # Calculate overall status
        all_healthy = all(results[service]['healthy'] for service in results)

        status_code = 200 if all_healthy else 503

        return jsonify({
            'status': 'healthy' if all_healthy else 'degraded',
            'healthy': all_healthy,
            'services': results,
            'timestamp': time.time()
        }), status_code

    except Exception as e:
        logger.error(f"Error checking system health: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'healthy': False
        }), 500


def register_health_routes(app):
    """Register health check routes on Flask app."""
    app.register_blueprint(health_bp)
    logger.info("✅ Health check routes registered")
