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

    with app.app_context():
        while not _stop_event.is_set():
            try:
                # Get audio metrics and sources
                from webapp.admin.audio_ingest import _get_audio_controller
                from app_core.audio import get_eas_monitor_instance

                controller = _get_audio_controller()

                # Audio metrics for VU meters
                source_metrics = []
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

                # Audio sources list
                audio_sources = []
                for source_name, adapter in controller._sources.items():
                    audio_sources.append({
                        'name': adapter.config.name,
                        'type': adapter.config.source_type.value,
                        'status': adapter.status.value,
                        'enabled': adapter.config.enabled,
                        'priority': adapter.config.priority,
                    })

                # EAS Monitor status
                monitor = get_eas_monitor_instance()
                eas_monitor_status = None
                if monitor:
                    status = monitor.get_status()
                    eas_monitor_status = {
                        'running': status.get('running', False),
                        'audio_flowing': status.get('audio_flowing', False),
                        'health_percentage': status.get('health_percentage', 0),
                        'samples_per_second': status.get('samples_per_second', 0),
                        'runtime_seconds': status.get('runtime_seconds', 0),
                        'alerts_detected': status.get('alerts_detected', 0),
                        'decoder_synced': status.get('decoder_synced', False),
                    }

                # Broadcast all data to connected clients
                socketio.emit('audio_monitoring_update', {
                    'audio_metrics': {
                        'live_metrics': source_metrics,
                        'total_sources': len(source_metrics),
                        'active_source': controller.get_active_source(),
                        'broadcast_stats': broadcast_stats,
                    },
                    'audio_sources': audio_sources,
                    'eas_monitor': eas_monitor_status,
                    'timestamp': time.time(),
                })

            except Exception as e:
                logger.warning(f"Error in WebSocket push worker: {e}")

            # Sleep for 1 second (real-time updates)
            _stop_event.wait(1.0)

    logger.info("WebSocket push worker stopped")
