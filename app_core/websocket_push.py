"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""WebSocket push service for real-time updates.

This service pushes multiple event types at different intervals:
- audio_monitoring_update: 4Hz (250ms) - VU meters, EAS monitor status
- system_health_update: 0.0167Hz (60s) - system health, status indicators
- audio_sources_update: 0.033Hz (30s) - audio source list
- audio_health_update: 0.033Hz (30s) - audio health dashboard data
- operation_status_update: 0.1Hz (10s) - admin operations status
- ipaws_status_update: 0.033Hz (30s) - IPAWS connection status
- gpio_status_update: 0.33Hz (3s) - GPIO pin states
- led_status_update: 0.033Hz (30s) - LED controller state
- analytics_update: 0.033Hz (30s) - analytics dashboard rollup
- radio_status_update: 0.067Hz (15s) - radio receiver list
- logs_update: 0.1Hz (10s) - recent log entries for real-time log viewer
- broadcast_state_update: 1Hz (1s) - airchain broadcast active state
- alerts_update: 0.2Hz (5s) - active CAP alert summary list
"""

import json
import logging
import math
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from flask import Flask
    from flask_socketio import SocketIO

logger = logging.getLogger(__name__)


def _sanitize_float(value: float) -> float:
    """Sanitize float values to be JSON-safe (no inf/nan, convert numpy types)."""
    import numpy as np
    
    # Handle None values
    if value is None:
        return -120.0
    
    # Convert numpy types to regular Python float first
    if isinstance(value, (np.floating, np.integer)):
        value = float(value)
    
    # Handle non-numeric types
    try:
        value = float(value)
    except (TypeError, ValueError):
        return -120.0
    
    if math.isinf(value):
        return -120.0 if value < 0 else 120.0
    if math.isnan(value):
        return -120.0
    return value


def _sanitize_for_json(obj):
    """
    Recursively sanitize objects to be JSON-safe.
    
    Converts inf, -inf, nan to valid numbers.
    Handles nested dicts, lists, and numpy types.
    """
    if obj is None:
        return None
    
    if isinstance(obj, bool):
        return obj
    
    if isinstance(obj, (int, str)):
        return obj
    
    if isinstance(obj, float):
        if math.isinf(obj):
            return -120.0 if obj < 0 else 120.0
        if math.isnan(obj):
            return -120.0
        return obj
    
    # Handle numpy types
    try:
        import numpy as np
        if isinstance(obj, np.floating):
            value = float(obj)
            if math.isinf(value):
                return -120.0 if value < 0 else 120.0
            if math.isnan(value):
                return -120.0
            return value
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
    except ImportError:
        pass
    
    if isinstance(obj, dict):
        return {key: _sanitize_for_json(value) for key, value in obj.items()}
    
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    
    # Fallback: convert to string
    return str(obj)


def _safe_emit(socketio, event_name, data):
    """
    Safely emit WebSocket event with sanitized data.
    
    This ensures no inf, nan, or other invalid JSON values are sent to clients.
    """
    sanitized_data = _sanitize_for_json(data)
    socketio.emit(event_name, sanitized_data)

_push_thread = None
_stop_event = threading.Event()

# Timing intervals in seconds
AUDIO_MONITORING_INTERVAL = 0.25   # 4Hz - real-time VU meters (was 10Hz; 4Hz is plenty for meters)
SYSTEM_HEALTH_INTERVAL = 60.0      # System health updates
AUDIO_SOURCES_INTERVAL = 30.0      # Audio source list
AUDIO_HEALTH_INTERVAL = 30.0       # Audio health dashboard
OPERATION_STATUS_INTERVAL = 10.0   # Admin operation status
IPAWS_STATUS_INTERVAL = 30.0       # IPAWS connection status
GPIO_STATUS_INTERVAL = 3.0         # GPIO pin states
LED_STATUS_INTERVAL = 30.0         # LED status
ANALYTICS_INTERVAL = 30.0          # Analytics dashboard
RADIO_STATUS_INTERVAL = 15.0       # Radio diagnostics
LOGS_UPDATE_INTERVAL = 10.0        # Log viewer updates
BROADCAST_STATE_INTERVAL = 1.0     # Airchain broadcast state (1Hz during broadcast)
ALERTS_UPDATE_INTERVAL = 5.0       # Active CAP alert list (changes infrequently;
                                   # 5 s gives near-real-time feel without DB load)


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
    """Background worker that pushes real-time updates via WebSocket.

    All events are rate-limited via explicit timers.  The loop itself sleeps
    for AUDIO_MONITORING_INTERVAL (250 ms / 4 Hz) between iterations, keeping
    CPU usage low while still delivering smooth VU-meter updates.
    """
    logger.info("WebSocket push worker started")

    # Cache audio source configs to avoid hammering the database every second
    config_cache = {}
    config_cache_loaded_at = 0.0

    # Timers for different event types (last emit time)
    last_audio_monitoring_emit = 0.0
    last_system_health_emit = 0.0
    last_audio_sources_emit = 0.0
    last_audio_health_emit = 0.0
    last_operation_status_emit = 0.0
    last_ipaws_status_emit = 0.0
    last_gpio_status_emit = 0.0
    last_led_status_emit = 0.0
    last_analytics_emit = 0.0
    last_radio_status_emit = 0.0
    last_logs_emit = 0.0
    last_broadcast_state_emit = 0.0
    last_alerts_emit = 0.0
    # Cache of last-emitted alert signature so we can short-circuit the JSON
    # serialization when nothing has changed (most ticks).  Cleared on app
    # restart only.
    last_alerts_signature: Optional[str] = None

    with app.app_context():
        while not _stop_event.is_set():
            now = time.time()

            # ================================================================
            # AUDIO MONITORING UPDATE (4Hz - every 250ms)
            # Real-time VU meters and EAS monitor status.
            # Previously ran unconditionally at 10Hz, burning CPU with Redis
            # reads that returned the same stale value 50 times per second.
            # ================================================================
            if now - last_audio_monitoring_emit >= AUDIO_MONITORING_INTERVAL:
                try:
                    _emit_audio_monitoring_update(app, socketio, config_cache)
                    last_audio_monitoring_emit = now
                except Exception as e:
                    logger.warning(f"Error emitting audio_monitoring_update: {e}")

            # Refresh config cache periodically
            if now - config_cache_loaded_at > 30:
                try:
                    from webapp.admin.audio_ingest import AudioSourceConfigDB
                    config_cache = {cfg.name: cfg for cfg in AudioSourceConfigDB.query.all()}
                    config_cache_loaded_at = now
                except Exception as e:
                    logger.debug(f"Error refreshing audio config cache: {e}")

            # ================================================================
            # SYSTEM HEALTH UPDATE (every 60s)
            # System status indicator in header
            # ================================================================
            if now - last_system_health_emit >= SYSTEM_HEALTH_INTERVAL:
                try:
                    _emit_system_health_update(app, socketio)
                    last_system_health_emit = now
                except Exception as e:
                    logger.warning(f"Error emitting system_health_update: {e}")

            # ================================================================
            # AUDIO SOURCES UPDATE (every 30s)
            # Audio source list for monitoring page
            # ================================================================
            if now - last_audio_sources_emit >= AUDIO_SOURCES_INTERVAL:
                try:
                    _emit_audio_sources_update(app, socketio)
                    last_audio_sources_emit = now
                except Exception as e:
                    logger.warning(f"Error emitting audio_sources_update: {e}")

            # ================================================================
            # AUDIO HEALTH UPDATE (every 30s)
            # Audio health dashboard data
            # ================================================================
            if now - last_audio_health_emit >= AUDIO_HEALTH_INTERVAL:
                try:
                    _emit_audio_health_update(app, socketio)
                    last_audio_health_emit = now
                except Exception as e:
                    logger.warning(f"Error emitting audio_health_update: {e}")

            # ================================================================
            # OPERATION STATUS UPDATE (every 10s)
            # Admin operations status
            # ================================================================
            if now - last_operation_status_emit >= OPERATION_STATUS_INTERVAL:
                try:
                    _emit_operation_status_update(app, socketio)
                    last_operation_status_emit = now
                except Exception as e:
                    logger.warning(f"Error emitting operation_status_update: {e}")

            # ================================================================
            # IPAWS STATUS UPDATE (every 30s)
            # IPAWS connection status
            # ================================================================
            if now - last_ipaws_status_emit >= IPAWS_STATUS_INTERVAL:
                try:
                    _emit_ipaws_status_update(app, socketio)
                    last_ipaws_status_emit = now
                except Exception as e:
                    logger.warning(f"Error emitting ipaws_status_update: {e}")

            # ================================================================
            # GPIO STATUS UPDATE (every 3s)
            # GPIO pin states
            # ================================================================
            if now - last_gpio_status_emit >= GPIO_STATUS_INTERVAL:
                try:
                    _emit_gpio_status_update(app, socketio)
                    last_gpio_status_emit = now
                except Exception as e:
                    logger.debug(f"Error emitting gpio_status_update: {e}")

            # ================================================================
            # LED STATUS UPDATE (every 30s)
            # LED controller status
            # ================================================================
            if now - last_led_status_emit >= LED_STATUS_INTERVAL:
                try:
                    _emit_led_status_update(app, socketio)
                    last_led_status_emit = now
                except Exception as e:
                    logger.debug(f"Error emitting led_status_update: {e}")

            # ================================================================
            # ANALYTICS UPDATE (every 30s)
            # Analytics dashboard data
            # ================================================================
            if now - last_analytics_emit >= ANALYTICS_INTERVAL:
                try:
                    _emit_analytics_update(app, socketio)
                    last_analytics_emit = now
                except Exception as e:
                    logger.debug(f"Error emitting analytics_update: {e}")

            # ================================================================
            # RADIO STATUS UPDATE (every 15s)
            # Radio diagnostics status
            # ================================================================
            if now - last_radio_status_emit >= RADIO_STATUS_INTERVAL:
                try:
                    _emit_radio_status_update(app, socketio)
                    last_radio_status_emit = now
                except Exception as e:
                    logger.debug(f"Error emitting radio_status_update: {e}")

            # ================================================================
            # LOGS UPDATE (every 10s)
            # Recent log entries for real-time log viewer
            # ================================================================
            if now - last_logs_emit >= LOGS_UPDATE_INTERVAL:
                try:
                    _emit_logs_update(app, socketio)
                    last_logs_emit = now
                except Exception as e:
                    logger.debug(f"Error emitting logs_update: {e}")

            # ================================================================
            # BROADCAST STATE UPDATE (1Hz)
            # Airchain active state for the global countdown timer overlay.
            # ================================================================
            if now - last_broadcast_state_emit >= BROADCAST_STATE_INTERVAL:
                try:
                    _emit_broadcast_state_update(socketio)
                    last_broadcast_state_emit = now
                except Exception as e:
                    logger.debug(f"Error emitting broadcast_state_update: {e}")

            # ================================================================
            # ALERTS UPDATE (every 5s, change-detected)
            # Active CAP alert summary so the alerts page and dashboard widgets
            # don't have to poll /api/alerts on a timer.
            # ================================================================
            if now - last_alerts_emit >= ALERTS_UPDATE_INTERVAL:
                try:
                    new_sig = _emit_alerts_update(app, socketio, last_alerts_signature)
                    if new_sig is not None:
                        last_alerts_signature = new_sig
                    last_alerts_emit = now
                except Exception as e:
                    logger.debug(f"Error emitting alerts_update: {e}")

            # Sleep for 250ms (4Hz base loop) — low CPU, smooth VU meters
            _stop_event.wait(AUDIO_MONITORING_INTERVAL)

    logger.info("WebSocket push worker stopped")


def _emit_audio_monitoring_update(app: 'Flask', socketio: 'SocketIO', config_cache: dict) -> None:
    """Emit real-time audio monitoring metrics (VU meters, EAS monitor)."""
    from webapp.admin.audio_ingest import _read_audio_metrics_from_redis

    source_metrics = []
    audio_sources = []
    broadcast_stats = {}
    eas_monitor_status = None
    active_source = None

    redis_metrics = _read_audio_metrics_from_redis()

    if redis_metrics:
        audio_controller_data = redis_metrics.get('audio_controller')
        
        # Handle case where audio_controller is a JSON string (legacy) or already parsed dict
        if isinstance(audio_controller_data, str):
            # Skip empty strings to avoid JSON parse errors
            if audio_controller_data.strip():
                try:
                    audio_controller_data = json.loads(audio_controller_data)
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse audio_controller JSON: {e}")
                    audio_controller_data = None
            else:
                audio_controller_data = None

        if audio_controller_data:
            active_source = audio_controller_data.get('active_source')
            redis_sources = audio_controller_data.get('sources', {})
            for source_name, source_data in redis_sources.items():
                config_lookup_name = source_name.replace("redis-", "", 1) if source_name.startswith("redis-") else source_name
                config = config_cache.get(config_lookup_name)
                # Use _sanitize_float to handle None, inf, nan values from Redis
                peak_db = source_data.get('peak_level_db')
                rms_db = source_data.get('rms_level_db')
                buffer_util = source_data.get('buffer_utilization')
                
                source_metrics.append({
                    'source_id': config_lookup_name,
                    'source_name': config_lookup_name,
                    'source_type': getattr(config.source_type, 'value', None) if config else 'unknown',
                    'source_status': source_data.get('status', 'unknown'),
                    'timestamp': source_data.get('timestamp', redis_metrics.get('timestamp', time.time())),
                    'sample_rate': source_data.get('sample_rate'),
                    'channels': source_data.get('channels') or 2,
                    'peak_level_db': _sanitize_float(peak_db) if peak_db is not None else -120.0,
                    'rms_level_db': _sanitize_float(rms_db) if rms_db is not None else -120.0,
                    'frames_captured': source_data.get('frames_captured') or 0,
                    'silence_detected': bool(source_data.get('silence_detected', False)),
                    'buffer_utilization': _sanitize_float(buffer_util) if buffer_util is not None else 0.0,
                    'metrics': {
                        'metadata': source_data.get('metadata')
                    },
                })

            for name, data in redis_sources.items():
                config_lookup_name = name.replace("redis-", "", 1) if name.startswith("redis-") else name
                config = config_cache.get(config_lookup_name)
                audio_sources.append({
                    'name': config_lookup_name,
                    'type': getattr(getattr(config, 'source_type', None), 'value', None) if config else 'unknown',
                    'status': data.get('status', 'unknown'),
                    'enabled': getattr(config, 'enabled', None),
                    'priority': getattr(config, 'priority', None),
                })

        broadcast_stats = redis_metrics.get('broadcast_queue') or {}
        if isinstance(broadcast_stats, str):
            # Skip empty strings to avoid JSON parse errors
            if broadcast_stats.strip():
                try:
                    broadcast_stats = json.loads(broadcast_stats)
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse broadcast_stats JSON: {e}")
                    broadcast_stats = {}
            else:
                broadcast_stats = {}

        eas_monitor_status = redis_metrics.get('eas_monitor')

    _safe_emit(socketio, 'audio_monitoring_update', {
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


def _emit_system_health_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit system health status for header indicator."""
    from app_core.system_health import get_system_health

    health_data = get_system_health(logger)

    # Extract key fields for header display
    status = health_data.get('status', 'unknown')
    status_summary = health_data.get('status_summary', '')

    _safe_emit(socketio, 'system_health_update', {
        'status': status,
        'status_summary': status_summary,
        'timestamp': time.time(),
        # Include full data for pages that need it
        'full_data': health_data,
    })


def _emit_audio_sources_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit audio source list update with runtime status from Redis."""
    from webapp.admin.audio_ingest import AudioSourceConfigDB, _read_audio_metrics_from_redis

    try:
        # Build status lookup from Redis so frontend gets live status, not 'stopped' default
        redis_status_map = {}
        try:
            redis_metrics = _read_audio_metrics_from_redis()
            if redis_metrics:
                audio_controller_data = redis_metrics.get('audio_controller', {})
                if isinstance(audio_controller_data, str):
                    if audio_controller_data.strip():
                        try:
                            audio_controller_data = json.loads(audio_controller_data)
                        except (json.JSONDecodeError, ValueError):
                            audio_controller_data = {}
                    else:
                        audio_controller_data = {}
                for name, data in audio_controller_data.get('sources', {}).items():
                    clean_name = name.replace("redis-", "", 1) if name.startswith("redis-") else name
                    redis_status_map[clean_name] = data.get('status', 'unknown')
        except Exception:
            pass  # Redis unavailable — omit status field so frontend keeps existing state

        sources = AudioSourceConfigDB.query.all()
        source_list = []
        for source in sources:
            entry = {
                'id': source.id,
                'name': source.name,
                'type': getattr(source.source_type, 'value', None) if source.source_type else 'unknown',
                'enabled': source.enabled,
                'priority': source.priority,
                'auto_start': source.auto_start,
            }
            if source.name in redis_status_map:
                entry['status'] = redis_status_map[source.name]
            source_list.append(entry)

        _safe_emit(socketio, 'audio_sources_update', {
            'sources': source_list,
            'total': len(source_list),
            'active_count': sum(1 for s in source_list if s.get('enabled')),
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.debug(f"Error fetching audio sources: {e}")


def _emit_audio_health_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit audio health dashboard data.

    Reads from Redis to get actual audio-service health status.
    """
    try:
        from webapp.admin.audio_ingest import _read_audio_metrics_from_redis

        redis_metrics = _read_audio_metrics_from_redis()
        health_data = {'overall_health_score': 0, 'sources': []}

        if redis_metrics:
            audio_controller = redis_metrics.get('audio_controller', {})
            eas_monitor = redis_metrics.get('eas_monitor', {})
            heartbeat = redis_metrics.get('_heartbeat', 0)
            age = time.time() - heartbeat

            # Calculate health score based on metrics freshness and status
            sources = audio_controller.get('sources', {})
            running_sources = sum(1 for s in sources.values() if s.get('status') == 'running')
            total_sources = len(sources)

            # Health score: 100 if fresh metrics and sources running, degrades with stale data
            health_score = 100
            if age > 5:
                health_score -= min(30, age * 2)  # Degrade up to 30 for stale data
            if total_sources > 0 and running_sources == 0:
                health_score -= 40  # No running sources

            health_data = {
                'overall_health_score': max(0, health_score),
                'metrics_age_seconds': age,
                'total_sources': total_sources,
                'running_sources': running_sources,
                'eas_monitor_running': eas_monitor.get('running', False),
            }

        _safe_emit(socketio, 'audio_health_update', {
            **health_data,
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.debug(f"Error fetching audio health: {e}")


def _emit_operation_status_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit admin operation status."""
    from webapp.admin.maintenance import get_operation_status

    try:
        status = get_operation_status()
        _safe_emit(socketio, 'operation_status_update', {
            **status,
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.debug(f"Error fetching operation status: {e}")


def _emit_ipaws_status_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit IPAWS connection status."""
    try:
        from flask import current_app
        from app_core.extensions import db
        from app_core.models import PollHistory

        # Build IPAWS status similar to the API endpoint
        ipaws_enabled = bool(current_app.config.get('IPAWS_ENABLED', False))
        status_data = {
            'enabled': ipaws_enabled,
            'connected': False,
            'last_poll': None,
            'alerts_count': 0,
        }

        if ipaws_enabled:
            try:
                last_poll = PollHistory.query.order_by(PollHistory.timestamp.desc()).first()
                if last_poll:
                    status_data['last_poll'] = last_poll.timestamp.isoformat() if last_poll.timestamp else None
                    status_data['connected'] = (last_poll.status or '').lower() == 'success'
                    status_data['alerts_count'] = last_poll.alerts_fetched or 0
            except Exception:
                pass

        _safe_emit(socketio, 'ipaws_status_update', {
            **status_data,
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.debug(f"Error fetching IPAWS status: {e}")


def _emit_gpio_status_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit GPIO pin states.

    GPIO may not be available on all systems (e.g., non-Raspberry Pi).
    """
    try:
        from app_core.models import GPIOConfig

        pins = GPIOConfig.query.all()
        pin_states = []
        for pin in pins:
            pin_states.append({
                'id': pin.id,
                'pin_number': pin.pin_number,
                'name': pin.name,
                'direction': pin.direction,
                'current_state': pin.current_state,
                'enabled': pin.enabled,
            })

        _safe_emit(socketio, 'gpio_status_update', {
            'pins': pin_states,
            'total': len(pin_states),
            'timestamp': time.time(),
        })
    except Exception:
        # GPIO may not be available on all systems - silently skip
        pass


def _emit_led_status_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit LED controller status.

    LED controller may not be available on all systems.
    """
    try:
        from app_core.models import LEDConfig

        configs = LEDConfig.query.all()
        led_status = []
        for config in configs:
            led_status.append({
                'id': config.id,
                'name': config.name,
                'enabled': config.enabled,
                'brightness': getattr(config, 'brightness', 100),
            })

        _safe_emit(socketio, 'led_status_update', {
            'leds': led_status,
            'total': len(led_status),
            'timestamp': time.time(),
        })
    except Exception:
        # LED controller may not be available - silently skip
        pass


def _emit_analytics_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit analytics dashboard data."""
    try:
        from sqlalchemy import func
        from app_core.extensions import db
        from app_core.models import CAPAlert, EASMessage

        # Calculate basic analytics
        total_alerts = db.session.query(func.count(CAPAlert.id)).scalar() or 0
        total_messages = db.session.query(func.count(EASMessage.id)).scalar() or 0

        # Get recent activity counts (last 24 hours)
        from datetime import datetime, timedelta, timezone
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        recent_alerts = db.session.query(func.count(CAPAlert.id)).filter(
            CAPAlert.received_at >= yesterday
        ).scalar() or 0

        _safe_emit(socketio, 'analytics_update', {
            'total_alerts': total_alerts,
            'total_messages': total_messages,
            'recent_alerts_24h': recent_alerts,
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.debug(f"Error fetching analytics data: {e}")


def _emit_radio_status_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit radio diagnostics status."""
    try:
        from app_core.models import RadioReceiver

        receivers = RadioReceiver.query.all()
        receiver_list = []
        for receiver in receivers:
            receiver_list.append({
                'id': receiver.id,
                'identifier': receiver.identifier,
                'display_name': receiver.display_name,
                'driver': receiver.driver,
                'enabled': receiver.enabled,
            })

        _safe_emit(socketio, 'radio_status_update', {
            'receivers': receiver_list,
            'total': len(receiver_list),
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.debug(f"Error fetching radio status: {e}")


def _emit_logs_update(app: 'Flask', socketio: 'SocketIO') -> None:
    """Emit recent log entries for real-time log viewer."""
    try:
        from app_core.models import SystemLog, AudioAlert

        logs = []

        # Get recent system logs (last 20)
        for log in SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(20).all():
            logs.append({
                'id': f'sys_{log.id}',
                'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                'level': log.level or 'INFO',
                'module': log.module or 'system',
                'message': log.message,
                'category': 'system',
            })

        # Get recent audio alerts (last 5)
        for log in AudioAlert.query.order_by(AudioAlert.created_at.desc()).limit(5).all():
            logs.append({
                'id': f'audio_{log.id}',
                'timestamp': log.created_at.isoformat() if log.created_at else None,
                'level': (log.alert_level or 'INFO').upper(),
                'module': f'audio:{log.source_name}' if log.source_name else 'audio',
                'message': log.message,
                'category': 'audio',
            })

        # Sort by timestamp and limit
        logs.sort(key=lambda x: x['timestamp'] or '', reverse=True)
        logs = logs[:25]

        _safe_emit(socketio, 'logs_update', {
            'logs': logs,
            'count': len(logs),
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.debug(f"Error fetching logs data: {e}")


def _emit_alerts_update(
    app: 'Flask',
    socketio: 'SocketIO',
    last_signature: Optional[str],
) -> Optional[str]:
    """Emit a lightweight summary of currently-active CAP alerts.

    Pushes a compact list (id, identifier, event, severity, urgency, headline,
    expires) so the active-alerts page and dashboard widgets can render
    immediately without their own polling loop.  When the active set hasn't
    changed since the previous tick we still emit (so newly-connected clients
    get a value) but skip the JSON payload churn cheaply.

    Returns the new signature so the caller can cache it.  Returning None
    means "no change, leave the previous signature in place".
    """
    import hashlib
    from datetime import datetime, timezone

    try:
        from app_core.models import CAPAlert
    except Exception as e:
        logger.debug(f"alerts_update unavailable: {e}")
        return None

    try:
        now_utc = datetime.now(timezone.utc)
        rows = (
            CAPAlert.query
            .filter(CAPAlert.expires > now_utc)
            .order_by(CAPAlert.received_at.desc())
            .limit(50)
            .all()
        )
    except Exception as e:
        logger.debug(f"alerts_update DB query failed: {e}")
        return None

    alerts = []
    for a in rows:
        alerts.append({
            'id': a.id,
            'identifier': a.identifier,
            'event': a.event,
            'severity': a.severity,
            'urgency': a.urgency,
            'headline': a.headline,
            'expires': a.expires.isoformat() if a.expires else None,
            'received_at': a.received_at.isoformat() if a.received_at else None,
            'eas_forwarded': bool(getattr(a, 'eas_forwarded', False)),
        })

    # Cheap signature: just the (id, expires) pairs.  Captures inserts, deletes,
    # and updates that change expiry time.  Doesn't catch in-place edits to e.g.
    # the headline, which is fine — those don't drive UI urgency.
    sig_input = '|'.join(f"{a['id']}:{a['expires']}" for a in alerts)
    signature = hashlib.sha256(sig_input.encode('utf-8')).hexdigest()

    payload = {
        'alerts': alerts,
        'count': len(alerts),
        'changed': signature != last_signature,
        'timestamp': time.time(),
    }
    _safe_emit(socketio, 'alerts_update', payload)
    return signature


def _emit_broadcast_state_update(socketio: 'SocketIO') -> None:
    """Emit current airchain broadcast state to all connected clients.

    Reads the ``eas:broadcast_active`` Redis key written by
    :func:`~app_utils.eas.set_broadcast_active` and pushes it so every page
    can show or hide the global countdown timer overlay.  Also includes a
    count of active (unexpired) CAP alerts so the blue stack light can illuminate.
    """
    try:
        from app_utils.eas import get_broadcast_state
        state = get_broadcast_state()

        # Count active unexpired alerts for the blue stack-light indicator
        active_alert_count = 0
        try:
            from datetime import datetime, timezone as _tz
            from app_core.models import CAPAlert
            now_utc = datetime.now(_tz.utc)
            active_alert_count = (
                CAPAlert.query
                .filter(CAPAlert.expires > now_utc)
                .count()
            )
        except Exception:
            pass

        _safe_emit(socketio, 'broadcast_state_update', {
            **state,
            'active_alert_count': active_alert_count,
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.debug(f"Error fetching broadcast state: {e}")
