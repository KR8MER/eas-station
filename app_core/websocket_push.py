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

"""WebSocket push service for real-time updates."""

import json
import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    from flask_socketio import SocketIO

logger = logging.getLogger(__name__)

_push_thread = None
_stop_event = threading.Event()


def start_websocket_push(app: 'Flask', socketio: 'SocketIO') -> None:
    """Start the WebSocket push service."""
    global _push_thread

    if _push_thread is not None and _push_thread.is_alive():
        logger.warning("WebSocket push thread already running")
        return

    _stop_event.clear()
    _push_thread = threading.Thread(
        target=_push_worker,
        args=(app, socketio),
        daemon=True,
        name="WebSocketPush"
    )
    _push_thread.start()
    logger.info("WebSocket push service started")


def stop_websocket_push() -> None:
    """Stop the WebSocket push service."""
    global _push_thread

    if _push_thread is None:
        return

    _stop_event.set()
    _push_thread.join(timeout=5.0)
    _push_thread = None
    logger.info("WebSocket push service stopped")


def _push_worker(app: 'Flask', socketio: 'SocketIO') -> None:
    """Background worker that pushes real-time updates via WebSocket."""
    logger.info("WebSocket push worker started")

    # Cache audio source configs to avoid hammering the database every second
    config_cache = {}
    config_cache_loaded_at = 0.0

    with app.app_context():
        while not _stop_event.is_set():
            try:
                # Get audio metrics and sources
                from webapp.admin.audio_ingest import (
                    _get_audio_controller,
                    _read_audio_metrics_from_redis,
                    AudioSourceConfigDB,
                )

                source_metrics = []
                audio_sources = []
                broadcast_stats = {}
                eas_monitor_status = None
                active_source = None

                # Prefer Redis metrics (audio-service publishes them in separated architecture)
                redis_metrics = _read_audio_metrics_from_redis()

                if redis_metrics:
                    # Refresh config cache periodically to keep type/priority info current
                    now = time.time()
                    if now - config_cache_loaded_at > 30:
                        config_cache = {cfg.name: cfg for cfg in AudioSourceConfigDB.query.all()}
                        config_cache_loaded_at = now

                    audio_controller_data = redis_metrics.get('audio_controller')
                    if isinstance(audio_controller_data, str):
                        audio_controller_data = json.loads(audio_controller_data)

                    if audio_controller_data:
                        active_source = audio_controller_data.get('active_source')
                        redis_sources = audio_controller_data.get('sources', {})
                        for source_name, source_data in redis_sources.items():
                            config = config_cache.get(source_name)
                            source_metrics.append({
                                'source_id': source_name,
                                'source_name': source_name,
                                'source_type': getattr(config.source_type, 'value', None) if config else 'unknown',
                                'source_status': source_data.get('status', 'unknown'),
                                'timestamp': source_data.get('timestamp', redis_metrics.get('timestamp', time.time())),
                                'sample_rate': source_data.get('sample_rate'),
                                'channels': source_data.get('channels', 2),
                                'peak_level_db': float(source_data.get('peak_level_db', -120.0)),
                                'rms_level_db': float(source_data.get('rms_level_db', -120.0)),
                                'frames_captured': source_data.get('frames_captured', 0),
                                'silence_detected': bool(source_data.get('silence_detected', False)),
                                'buffer_utilization': float(source_data.get('buffer_utilization', 0.0)),
                            })

                        audio_sources = []
                        for name, data in redis_sources.items():
                            config = config_cache.get(name)
                            audio_sources.append({
                                'name': name,
                                'type': getattr(getattr(config, 'source_type', None), 'value', None) if config else 'unknown',
                                'status': data.get('status', 'unknown'),
                                'enabled': getattr(config, 'enabled', None),
                                'priority': getattr(config, 'priority', None),
                            })

                    broadcast_stats = redis_metrics.get('broadcast_queue') or {}
                    if isinstance(broadcast_stats, str):
                        broadcast_stats = json.loads(broadcast_stats)

                    eas_monitor_status = redis_metrics.get('eas_monitor')

                # Fall back to local controller metrics when Redis is unavailable
                # NOTE: In separated architecture, audio processing happens in audio-service
                # container. The app container may have an empty local controller.
                if not redis_metrics:
                    controller = _get_audio_controller()

                    for source_name, adapter in controller._sources.items():
                        if adapter.metrics:
                            source_metrics.append({
                                'source_id': source_name,
                                'source_name': adapter.config.name,
                                'source_type': adapter.config.source_type.value,
                                'source_status': adapter.status.value,
                                'timestamp': adapter.metrics.timestamp,
                                'peak_level_db': float(adapter.metrics.peak_level_db) if adapter.metrics.peak_level_db is not None else -120.0,
                                'rms_level_db': float(adapter.metrics.rms_level_db) if adapter.metrics.rms_level_db is not None else -120.0,
                                'sample_rate': adapter.metrics.sample_rate,
                                'channels': adapter.metrics.channels,
                                'frames_captured': adapter.metrics.frames_captured,
                                'silence_detected': bool(adapter.metrics.silence_detected),
                                'buffer_utilization': float(adapter.metrics.buffer_utilization) if adapter.metrics.buffer_utilization is not None else 0.0,
                            })

                    broadcast_stats = controller.get_broadcast_queue().get_stats()
                    active_source = controller.get_active_source()

                    audio_sources = []
                    for source_name, adapter in controller._sources.items():
                        audio_sources.append({
                            'name': adapter.config.name,
                            'type': adapter.config.source_type.value,
                            'status': adapter.status.value,
                            'enabled': adapter.config.enabled,
                            'priority': adapter.config.priority,
                        })

                    # NOTE: EAS monitor is NOT available in app container in separated architecture
                    # It runs exclusively in audio-service container. EAS status comes from Redis.

                # Broadcast all data to connected clients
                socketio.emit('audio_monitoring_update', {
                    'audio_metrics': {
                        'live_metrics': source_metrics,
                        'total_sources': len(source_metrics),
                        'active_source': active_source,
                        'broadcast_stats': broadcast_stats,
                    },
                    'audio_sources': audio_sources,
                    'eas_monitor': eas_monitor_status,
                    'timestamp': time.time(),
                })

            except Exception as e:
                logger.warning(f"Error in WebSocket push worker: {e}")

            # Sleep for 100ms (10Hz updates) - good balance between responsiveness and server load
            # Client-side Web Audio API provides 60Hz for active audio players
            _stop_event.wait(0.1)

    logger.info("WebSocket push worker stopped")
