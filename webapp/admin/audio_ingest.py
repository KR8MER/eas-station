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

from __future__ import annotations

"""Audio Ingest API routes for managing audio sources and monitoring."""

import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, Flask, jsonify, render_template, request, current_app
from sqlalchemy import desc
from werkzeug.exceptions import BadRequest

from app_core.cache import cache, clear_audio_source_cache
from app_core.extensions import db
from app_core.models import (
    AudioAlert,
    AudioHealthStatus,
    AudioSourceMetrics,
    AudioSourceConfigDB,
    RadioReceiver,
)
from app_core.audio import AudioIngestController
from app_core.audio.ingest import AudioSourceConfig, AudioSourceType, AudioSourceStatus
from app_core.audio.sources import create_audio_source
from app_core.audio.redis_commands import get_audio_command_publisher
from app_utils import utc_now

logger = logging.getLogger(__name__)


def _read_audio_metrics_from_redis() -> Optional[Dict[str, Any]]:
    """
    Read audio metrics from Redis (published by audio-service container).

    In separated architecture, the audio-service container publishes metrics to Redis.
    This function reads those metrics if available.

    Returns:
        Dict with keys: audio_controller, broadcast_queue, eas_monitor, timestamp
        Or None if Redis is unavailable or metrics are stale
    """
    try:
        from app_core.audio.worker_coordinator_redis import read_shared_metrics

        metrics = read_shared_metrics()
        if metrics:
            logger.debug(f"Read audio metrics from Redis: {list(metrics.keys())}")
            return metrics
        else:
            logger.debug("No metrics available in Redis")
            return None

    except Exception as e:
        logger.warning(f"Failed to read audio metrics from Redis: {e}")
        return None


# Create Blueprint for audio ingest routes
audio_ingest_bp = Blueprint('audio_ingest', __name__)

# Global audio ingest controller instance
_audio_controller: Optional[AudioIngestController] = None

# Global auto-streaming service instance
_auto_streaming_service = None

# Global lock file to prevent duplicate streaming services across workers
_streaming_lock_file = None

# Global lock file to prevent duplicate audio source initialization across workers
_audio_initialization_lock_file = None

# Initialization state
_initialization_started = False
_initialization_lock = None


def _try_acquire_lock(lock_file_path: str, mode: str = 'a'):
    """Attempt to acquire an exclusive file lock.

    On platforms without ``fcntl`` (e.g., Windows) we log a warning and
    proceed without locking so that audio ingestion still functions.

    Returns a tuple of ``(file_handle, acquired)``. ``file_handle`` will be
    ``None`` when locking isn't supported or when the lock could not be
    obtained. ``acquired`` indicates whether initialization should proceed.
    """
    try:
        import fcntl  # type: ignore
    except ImportError:
        logger.warning(
            "POSIX file locking (fcntl) not available on this platform; "
            "continuing without an exclusive lock for %s",
            lock_file_path
        )
        return None, True

    try:
        lock_file = open(lock_file_path, mode)
    except OSError as exc:
        logger.warning(
            "Failed to open lock file %s (%s); continuing without exclusive lock",
            lock_file_path,
            exc
        )
        return None, True

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file, True
    except (IOError, OSError):
        lock_file.close()
        return None, False


def _get_audio_controller() -> AudioIngestController:
    """Get or create the global audio ingest controller."""
    global _audio_controller, _initialization_started

    if _audio_controller is None:
        # Capture Flask app for background thread context
        app = current_app._get_current_object()
        
        # Create the controller immediately (lightweight)
        # Pass Flask app so background threads can use app context
        _audio_controller = AudioIngestController(flask_app=app)

        # Load audio source configs from database (fast - just DB query)
        # This makes sources visible in UI immediately
        _load_audio_source_configs(_audio_controller)

        # Start sources and streaming in background to avoid blocking worker
        if not _initialization_started:
            _initialization_started = True
            import threading
            init_thread = threading.Thread(
                target=_start_audio_sources_background,
                args=(app,),
                daemon=True,
                name="AudioSourceStarter"
            )
            init_thread.start()
            logger.info("Started audio source initialization in background thread")

    return _audio_controller


def _load_audio_source_configs(controller: AudioIngestController) -> None:
    """Load audio source configurations from database (fast, synchronous)."""
    try:
        saved_configs = AudioSourceConfigDB.query.all()
        logger.info(f"Loading {len(saved_configs)} audio source configurations from database")

        for db_config in saved_configs:
            try:
                # Parse source type
                source_type = AudioSourceType(db_config.source_type)

                # Create runtime configuration from database config
                config_params = db_config.config_params or {}
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

                # Create and add adapter (fast - doesn't connect yet)
                adapter = create_audio_source(runtime_config)
                controller.add_source(adapter)
                logger.debug(f"Loaded audio source config: {db_config.name}")

            except Exception as e:
                logger.error(f'Failed to load audio source {db_config.name}: {e}')

        logger.info(f"Loaded {len(controller._sources)} audio source configurations")

    except Exception as e:
        logger.error(f'Failed to load audio sources from database: {e}')


def _start_audio_sources_background(app: Flask) -> None:
    """
    Start audio sources and streaming in background (slow, async).

    SEPARATED ARCHITECTURE: This function should NOT run in the app container.
    Audio processing is handled entirely by the dedicated audio-service container.
    The app container only serves the UI and reads metrics from Redis.
    """
    global _audio_controller, _streaming_lock_file, _audio_initialization_lock_file

    # Separated architecture: Audio processing handled by dedicated audio-service container
    # Skip ALL audio initialization in app container
    logger.info("🌐 App container in separated architecture - skipping audio source startup")
    logger.info("   Audio processing handled by dedicated audio-service container")
    return


def _get_auto_streaming_service():
    """Get the global auto-streaming service (may be None if not initialized)."""
    return _auto_streaming_service


def _initialize_auto_streaming() -> None:
    """Initialize the auto-streaming service from environment variables."""
    global _auto_streaming_service, _streaming_lock_file

    # CRITICAL: Prevent duplicate streaming services in multi-worker environments
    # With multiple gunicorn workers, each worker would initialize its own streaming
    # service, causing multiple FFmpeg processes to fight for the same Icecast mount.
    # Use a file lock to ensure only ONE worker starts the streaming service.
    import os

    lock_file_path = '/tmp/eas-auto-streaming.lock'

    lock_file, acquired = _try_acquire_lock(lock_file_path, mode='w')
    if not acquired:
        # Lock is already held by another worker - skip initialization
        logger.info(
            f"Auto-streaming already initialized by another worker (PID {os.getpid()}) - skipping"
        )
        _auto_streaming_service = None
        return

    if lock_file:
        # Keep lock file open for the lifetime of the process to maintain the lock
        _streaming_lock_file = lock_file
        logger.info(
            f"Acquired streaming lock (PID {os.getpid()}) - initializing auto-streaming service"
        )
    else:
        logger.info(
            f"Proceeding without exclusive auto-streaming lock (PID {os.getpid()})"
        )

    try:
        from app_core.audio.icecast_auto_config import get_icecast_auto_config
        from app_core.audio.auto_streaming import AutoStreamingService

        auto_config = get_icecast_auto_config()

        if auto_config.is_enabled():
            logger.info("Initializing auto-streaming service from environment config")
            # Get controller for broadcast queue access (non-destructive audio)
            controller = _get_audio_controller()
            _auto_streaming_service = AutoStreamingService(
                icecast_server=auto_config.server,
                icecast_port=auto_config.port,
                icecast_password=auto_config.source_password,
                icecast_admin_user=auto_config.admin_user,
                icecast_admin_password=auto_config.admin_password,
                default_bitrate=128,
                enabled=True,
                audio_controller=controller
            )
            _auto_streaming_service.start()
            logger.info("Auto-streaming service initialized and started")

            # Start streaming for any already-running sources
            for source_name, adapter in controller._sources.items():
                if adapter.status == AudioSourceStatus.RUNNING:
                    try:
                        _auto_streaming_service.add_source(source_name, adapter)
                        logger.info(f'Auto-started Icecast stream for already-running source: {source_name}')
                    except Exception as e:
                        logger.warning(f'Failed to auto-start Icecast stream for {source_name}: {e}')
        else:
            logger.info("Icecast auto-config not enabled, auto-streaming disabled")
            _auto_streaming_service = None

    except Exception as e:
        logger.warning(f"Failed to initialize auto-streaming service: {e}")
        _auto_streaming_service = None


def _reload_auto_streaming_from_env() -> None:
    """Reload auto-streaming configuration after Icecast settings change."""

    global _auto_streaming_service

    service = _get_auto_streaming_service()
    if service:
        try:
            service.stop()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Error stopping existing auto-streaming service: %s", exc)
        finally:
            _auto_streaming_service = None

    try:
        from app_core.audio.icecast_auto_config import get_icecast_auto_config
        from app_core.audio.auto_streaming import AutoStreamingService

        auto_config = get_icecast_auto_config()
        if auto_config.is_enabled():
            logger.info("Re-initializing auto-streaming service with updated Icecast settings")
            # Get controller for broadcast queue access (non-destructive audio)
            controller = _get_audio_controller()
            _auto_streaming_service = AutoStreamingService(
                icecast_server=auto_config.server,
                icecast_port=auto_config.port,
                icecast_password=auto_config.source_password,
                icecast_admin_user=auto_config.admin_user,
                icecast_admin_password=auto_config.admin_password,
                default_bitrate=128,
                enabled=True,
                audio_controller=controller
            )
            _auto_streaming_service.start()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to reload auto-streaming configuration: %s", exc)


def _safe_auto_stream_status(service) -> Optional[Dict[str, Any]]:
    """Return the current auto-streaming status, handling errors gracefully."""

    status: Optional[Dict[str, Any]] = None

    if service and hasattr(service, 'get_status'):
        try:
            status = service.get_status()
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Unable to read auto-streaming status: %s", exc)

    # Separated deployments run the streaming service in the audio-service container.
    # When the UI worker doesn't host the service locally, fall back to Redis metrics
    # so the UI still shows accurate active stream counts.
    if not status:
        try:
            metrics = _read_audio_metrics_from_redis()
            if metrics and 'audio_controller' in metrics:
                import json

                controller_data = metrics.get('audio_controller')
                if isinstance(controller_data, str):
                    try:
                        controller_data = json.loads(controller_data)
                    except Exception:  # pylint: disable=broad-except
                        logger.debug('Failed to decode Redis controller data for streaming status')

                if isinstance(controller_data, dict):
                    streaming_status = controller_data.get('streaming')
                    if isinstance(streaming_status, str):
                        try:
                            streaming_status = json.loads(streaming_status)
                        except Exception:  # pylint: disable=broad-except
                            logger.debug('Failed to decode Redis streaming status string')

                    if isinstance(streaming_status, dict):
                        status = streaming_status
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Redis fallback failed for streaming status: %s", exc)

    return status


def _start_auto_streaming_service() -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Start the AutoStreamingService if configured and available."""

    service = _get_auto_streaming_service()
    if service is None:
        logger.info("Auto-streaming service not initialized; attempting reload")
        _reload_auto_streaming_from_env()
        service = _get_auto_streaming_service()
        if service is None:
            return False, 'Icecast streaming is not configured', None

    try:
        if hasattr(service, 'is_available') and not service.is_available():
            status = _safe_auto_stream_status(service)
            return False, 'Icecast streaming service is not available', status

        started = service.start()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('Failed to start auto-streaming service: %s', exc)
        raise

    status = _safe_auto_stream_status(service)
    if started:
        return True, 'Icecast streaming service started', status

    return False, 'Icecast streaming service could not be started', status


def _stop_auto_streaming_service() -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Stop the AutoStreamingService if it is running."""

    service = _get_auto_streaming_service()
    if service is None:
        return False, 'Icecast streaming is not configured', None

    try:
        service.stop()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('Failed to stop auto-streaming service: %s', exc)
        raise

    status = _safe_auto_stream_status(service)
    return True, 'Icecast streaming service stopped', status



def _sanitize_float(value: float) -> float:
    """Sanitize float values to be JSON-safe (no inf/nan, convert numpy types)."""
    import math
    import numpy as np

    # Convert numpy types to regular Python float first
    if isinstance(value, (np.floating, np.integer)):
        value = float(value)

    if math.isinf(value):
        return -120.0 if value < 0 else 120.0
    if math.isnan(value):
        return -120.0
    return value


def _sanitize_bool(value) -> bool:
    """Sanitize boolean values to be JSON-safe (convert numpy bool_ types)."""
    import numpy as np

    # Convert numpy bool_ to Python bool
    if isinstance(value, np.bool_):
        return bool(value)

    return bool(value)


def _get_icecast_stream_url(source_name: str) -> Optional[str]:
    """Resolve the external Icecast URL for a source when configured."""
    try:
        from app_core.audio.icecast_auto_config import get_icecast_auto_config

        auto_config = get_icecast_auto_config()
        if auto_config.is_enabled():
            return auto_config.get_stream_url(source_name, external=True)
    except Exception:
        # Icecast may not be configured or auto-config import could fail; ignore gracefully
        return None

    return None


def _derive_sdr_source_name(identifier: str) -> str:
    """Generate a deterministic audio source name for a receiver identifier."""

    slug = re.sub(r"[^a-z0-9]+", "-", identifier.strip().lower()).strip("-")
    if not slug:
        slug = "receiver"
    return f"sdr-{slug}"


def _recommend_audio_stream(receiver: RadioReceiver) -> Tuple[int, int]:
    """Return (sample_rate, channels) best suited for the receiver's modulation.
    
    These are the NATIVE sample rates for the audio sources/streams.
    The EAS monitor will resample to 16 kHz internally for SAME decoding.
    """

    modulation = (receiver.modulation_type or "IQ").upper()

    if modulation in {"FM", "WFM"}:
        # FM broadcast quality - native rate for demodulated audio
        return (48000 if receiver.stereo_enabled else 32000, 2 if receiver.stereo_enabled else 1)
    if modulation in {"AM", "NFM"}:
        # AM/NFM - narrower bandwidth, lower sample rate sufficient
        return 24000, 1

    # Default for IQ/unknown - standard audio rate
    return 44100, 1


def _format_receiver_frequency(frequency_hz: float) -> str:
    """Format an arbitrary receiver frequency for human-readable display."""

    if frequency_hz >= 1_000_000:
        return f"{frequency_hz / 1_000_000:.3f} MHz"
    if frequency_hz >= 1_000:
        return f"{frequency_hz / 1_000:.0f} kHz"
    return f"{frequency_hz:.0f} Hz"


def _base_radio_metadata(receiver: RadioReceiver, source_name: str) -> Dict[str, Any]:
    """Build baseline metadata payload for SDR-backed audio sources."""

    frequency_hz = float(receiver.frequency_hz or 0.0)
    frequency_mhz = frequency_hz / 1_000_000 if frequency_hz else 0.0
    return {
        'receiver_identifier': receiver.identifier,
        'receiver_display_name': receiver.display_name,
        'receiver_driver': receiver.driver,
        'receiver_frequency_hz': frequency_hz,
        'receiver_frequency_mhz': round(frequency_mhz, 6),
        'receiver_frequency_display': _format_receiver_frequency(frequency_hz) if frequency_hz else None,
        'receiver_modulation': (receiver.modulation_type or "IQ").upper(),
        'receiver_audio_output': bool(receiver.audio_output),
        'receiver_auto_start': bool(receiver.auto_start),
        'rbds_enabled': bool(receiver.enable_rbds),
        'squelch_enabled': bool(receiver.squelch_enabled),
        'squelch_threshold_db': float(receiver.squelch_threshold_db or -65.0),
        'squelch_open_ms': int(receiver.squelch_open_ms or 150),
        'squelch_close_ms': int(receiver.squelch_close_ms or 750),
        'carrier_alarm_enabled': bool(receiver.squelch_alarm),
        'source_category': 'sdr',
        'icecast_mount': f"/{source_name}",
    }


def list_radio_managed_audio_sources() -> List[AudioSourceConfigDB]:
    """Return AudioSourceConfig rows that are managed automatically for SDR receivers."""

    configs = AudioSourceConfigDB.query.filter_by(source_type=AudioSourceType.SDR.value).all()
    managed: List[AudioSourceConfigDB] = []
    for config in configs:
        params = config.config_params or {}
        if params.get('managed_by') == 'radio':
            managed.append(config)
    return managed


def remove_radio_managed_audio_source(
    source_name: str,
    *,
    commit: bool = True,
    stop_stream: bool = True,
) -> bool:
    """Remove a radio-managed SDR audio source from memory, streaming, and database."""

    db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
    if not db_config:
        return False

    params = db_config.config_params or {}
    if params.get('managed_by') != 'radio':
        return False

    controller = _audio_controller
    if controller and source_name in controller._sources:
        controller.remove_source(source_name)

    if stop_stream:
        auto_streaming = _get_auto_streaming_service()
        if auto_streaming:
            try:
                auto_streaming.remove_source(source_name)
            except Exception as exc:
                logger.warning('Failed to stop Icecast stream for %s: %s', source_name, exc)

    db.session.delete(db_config)
    if commit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    logger.info('Removed SDR audio monitor %s', source_name)
    return True


def ensure_sdr_audio_monitor_source(
    receiver: RadioReceiver,
    *,
    start_immediately: Optional[bool] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """Ensure an SDR receiver has a corresponding audio monitor source configured."""

    source_name = _derive_sdr_source_name(receiver.identifier)
    should_enable = bool(receiver.audio_output and receiver.enabled)

    if not should_enable:
        removed = remove_radio_managed_audio_source(source_name, commit=commit)
        return {
            'source_name': source_name,
            'created': False,
            'updated': False,
            'started': False,
            'icecast_started': False,
            'removed': removed,
        }

    controller = _get_audio_controller()
    sample_rate, channels = _recommend_audio_stream(receiver)
    buffer_size = 4096 if channels == 1 else 8192
    silence_threshold = float(receiver.squelch_threshold_db or -60.0)
    silence_duration = max(float(receiver.squelch_close_ms or 750) / 1000.0, 0.1)
    squelch_open = int(receiver.squelch_open_ms or 150)
    squelch_close = int(receiver.squelch_close_ms or 750)
    squelch_enabled = bool(receiver.squelch_enabled)
    carrier_alarm_enabled = bool(receiver.squelch_alarm)

    device_params = {
        'receiver_id': receiver.identifier,
        'receiver_display_name': receiver.display_name,
        'receiver_driver': receiver.driver,
        'receiver_frequency_hz': float(receiver.frequency_hz or 0.0),
        'receiver_modulation': (receiver.modulation_type or 'IQ').upper(),
        'rbds_enabled': bool(receiver.enable_rbds),
        'squelch_enabled': squelch_enabled,
        'squelch_threshold_db': silence_threshold,
        'squelch_open_ms': squelch_open,
        'squelch_close_ms': squelch_close,
        'carrier_alarm_enabled': carrier_alarm_enabled,
    }

    config_params = {
        'sample_rate': sample_rate,
        'channels': channels,
        'buffer_size': buffer_size,
        'silence_threshold_db': silence_threshold,
        'silence_duration_seconds': silence_duration,
        'device_params': device_params,
        'managed_by': 'radio',
        'squelch_enabled': squelch_enabled,
        'squelch_threshold_db': silence_threshold,
        'squelch_open_ms': squelch_open,
        'squelch_close_ms': squelch_close,
        'carrier_alarm_enabled': carrier_alarm_enabled,
    }

    start_flag = bool(start_immediately if start_immediately is not None else receiver.auto_start)

    freq_display = _format_receiver_frequency(float(receiver.frequency_hz or 0.0)) if receiver.frequency_hz else "Unknown"
    description = f"SDR monitor for {receiver.display_name} · {freq_display}"

    created = False
    updated = False

    db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
    priority = 10

    if db_config is None:
        db_config = AudioSourceConfigDB(
            name=source_name,
            source_type=AudioSourceType.SDR.value,
            config_params=config_params,
            priority=priority,
            enabled=True,
            auto_start=start_flag,
            description=description,
        )
        db.session.add(db_config)
        created = True
    else:
        if (db_config.config_params or {}) != config_params:
            db_config.config_params = config_params
            updated = True
        if not db_config.enabled:
            db_config.enabled = True
            updated = True
        if db_config.auto_start != start_flag:
            db_config.auto_start = start_flag
            updated = True
        if (db_config.description or '') != description:
            db_config.description = description
            updated = True
        if db_config.priority != priority:
            db_config.priority = priority
            updated = True
        if db_config.source_type != AudioSourceType.SDR.value:
            db_config.source_type = AudioSourceType.SDR.value
            updated = True

    if commit and (created or updated):
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    auto_streaming = _get_auto_streaming_service()

    if controller._sources.get(source_name):
        if auto_streaming:
            try:
                auto_streaming.remove_source(source_name)
            except Exception as exc:
                logger.debug('Auto-stream removal for %s during reconfigure failed: %s', source_name, exc)
        controller.remove_source(source_name)

    runtime_config = AudioSourceConfig(
        source_type=AudioSourceType.SDR,
        name=source_name,
        enabled=True,
        priority=priority,
        sample_rate=sample_rate,
        channels=channels,
        buffer_size=buffer_size,
        silence_threshold_db=silence_threshold,
        silence_duration_seconds=silence_duration,
        device_params=device_params,
    )

    adapter = create_audio_source(runtime_config)
    metadata = adapter.metrics.metadata or {}
    metadata.update({k: v for k, v in _base_radio_metadata(receiver, source_name).items() if v is not None})
    metadata.setdefault('carrier_present', None)
    metadata.setdefault('squelch_state', 'open' if not squelch_enabled else 'pending')
    metadata.setdefault('squelch_last_rms_db', None)
    metadata.setdefault('carrier_alarm', False)
    metadata.setdefault('rbds_program_type_name', None)
    metadata.setdefault('rbds_last_updated', None)
    adapter.metrics.metadata = metadata
    controller.add_source(adapter)

    started = False
    icecast_started = False

    if start_flag:
        try:
            started = controller.start_source(source_name)
        except Exception as exc:
            logger.warning('Failed to auto-start SDR audio source %s: %s', source_name, exc)
        else:
            if started and auto_streaming and auto_streaming.is_available():
                try:
                    icecast_started = bool(auto_streaming.add_source(source_name, adapter))
                except Exception as exc:
                    logger.warning('Failed to start Icecast stream for %s: %s', source_name, exc)

    return {
        'source_name': source_name,
        'created': created,
        'updated': updated,
        'started': started,
        'icecast_started': icecast_started,
        'removed': False,
    }


def _sanitize_metadata_value(value: Any) -> Any:
    """Sanitize a metadata value to ensure JSON serialization safety."""
    if value is None:
        return None

    if isinstance(value, (str, int)):
        return value

    if isinstance(value, float):
        return _sanitize_float(value)

    if isinstance(value, bool):
        return _sanitize_bool(value)

    if isinstance(value, (list, tuple)):
        return [
            _sanitize_metadata_value(item)
            for item in value
        ]

    if isinstance(value, dict):
        return {
            str(key): _sanitize_metadata_value(item)
            for key, item in value.items()
        }

    if isinstance(value, datetime):
        return value.isoformat()

    try:
        import numpy as np  # type: ignore

        if isinstance(value, (np.floating, np.integer)):
            return _sanitize_float(float(value))

        if isinstance(value, np.bool_):
            return _sanitize_bool(bool(value))
    except Exception:
        # numpy may not be installed in some environments
        pass

    return str(value)


def _merge_metadata(*metadata_sources: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Merge multiple metadata dictionaries into a sanitized structure."""
    merged: Dict[str, Any] = {}

    for metadata in metadata_sources:
        if not metadata:
            continue

        for key, value in metadata.items():
            sanitized_value = _sanitize_metadata_value(value)
            if sanitized_value is None:
                continue

            key_str = str(key)
            if key_str in merged and merged[key_str] is not None:
                continue

            merged[key_str] = sanitized_value

    return merged or None


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

    metadata = adapter.metrics.metadata or {}
    device_params = config_params.get('device_params')
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
            'device_params': config.device_params,
        },
        'metrics': metrics_payload,
        'streaming': streaming,
    }


def register_audio_ingest_routes(app: Flask, logger_instance: Any) -> None:
    """Register audio ingest API routes."""
    global logger
    logger = logger_instance
    
    # Register the blueprint with the app
    app.register_blueprint(audio_ingest_bp)
    logger_instance.info("Audio ingest routes registered")


# Route definitions

@audio_ingest_bp.route('/api/audio/sources', methods=['GET'])
@cache.cached(timeout=30, key_prefix='audio_source_list')
def api_get_audio_sources():
    """List all configured audio sources.

    Cached for 30 seconds to reduce database load during rapid polling.
    """
    try:
        # SEPARATED ARCHITECTURE: Try to read runtime status from Redis first
        redis_metrics = _read_audio_metrics_from_redis()
        redis_sources = {}
        use_redis = False

        redis_streaming_status = None

        if redis_metrics and 'audio_controller' in redis_metrics:
            try:
                import json
                audio_controller_data = redis_metrics.get('audio_controller')
                if isinstance(audio_controller_data, str):
                    audio_controller_data = json.loads(audio_controller_data)

                if audio_controller_data and 'sources' in audio_controller_data:
                    redis_sources = audio_controller_data['sources']
                    use_redis = True
                    logger.info(f"Using Redis for audio source status (separated architecture): {list(redis_sources.keys())}")

                if audio_controller_data and isinstance(audio_controller_data, dict):
                    redis_streaming_status = audio_controller_data.get('streaming')
                    if isinstance(redis_streaming_status, str):
                        try:
                            redis_streaming_status = json.loads(redis_streaming_status)
                        except Exception:
                            logger.debug('Failed to decode Redis streaming status string; using raw value')
            except Exception as e:
                logger.warning(f"Failed to parse Redis audio controller data: {e}")

        # Get local controller (may be empty in separated architecture)
        controller = _get_audio_controller()
        sources: List[Dict[str, Any]] = []

        # Query DATABASE for all sources (source of truth)
        db_configs = AudioSourceConfigDB.query.all()

        source_names = [config.name for config in db_configs]

        latest_metrics_map: Dict[str, AudioSourceMetrics] = {}
        if source_names:
            recent_metrics = (
                AudioSourceMetrics.query
                .filter(AudioSourceMetrics.source_name.in_(source_names))
                .order_by(AudioSourceMetrics.source_name, desc(AudioSourceMetrics.timestamp))
                .all()
            )

            for metric in recent_metrics:
                if metric.source_name not in latest_metrics_map:
                    latest_metrics_map[metric.source_name] = metric

        icecast_status_map: Dict[str, Dict[str, Any]] = {}
        auto_streaming = _get_auto_streaming_service()
        if auto_streaming:
            try:
                streaming_status = auto_streaming.get_status()
                active_streams = streaming_status.get('active_streams', {}) if streaming_status else {}
                icecast_status_map = {
                    name: dict(stats)
                    for name, stats in active_streams.items()
                }
            except Exception as status_exc:
                logger.warning('Failed to get Icecast streaming status: %s', status_exc)

        if not icecast_status_map and redis_streaming_status:
            try:
                active_streams = redis_streaming_status.get('active_streams', {}) if isinstance(redis_streaming_status, dict) else {}
                icecast_status_map = {
                    name: dict(stats)
                    for name, stats in active_streams.items()
                }
            except Exception as status_exc:
                logger.warning('Failed to parse Redis streaming status: %s', status_exc)

        for db_config in db_configs:
            latest_metric = latest_metrics_map.get(db_config.name)
            icecast_stats = icecast_status_map.get(db_config.name)
            icecast_url = _get_icecast_stream_url(db_config.name)

            # Try Redis first (separated architecture), then fall back to local controller
            adapter = None
            redis_source_data = None

            if use_redis and db_config.name in redis_sources:
                redis_source_data = redis_sources[db_config.name]

                if not isinstance(redis_source_data, dict):
                    logger.warning(
                        "Redis audio source data for %s is not a dict (type=%s); ignoring",
                        db_config.name,
                        type(redis_source_data),
                    )
                    redis_source_data = {}

                logger.debug(f"Found Redis data for source '{db_config.name}': {redis_source_data}")
            else:
                # Fall back to local controller (integrated mode or Redis unavailable)
                adapter = controller._sources.get(db_config.name)

            # If we have an actual adapter (integrated mode), serialize it
            if adapter:
                sources.append(
                    _serialize_audio_source(
                        db_config.name,
                        adapter,
                        latest_metric,
                        icecast_stats,
                    )
                )
                continue

            # If we have Redis data (separated mode), use it
            if redis_source_data:
                redis_streaming_stats = redis_source_data.get('streaming') if isinstance(redis_source_data, dict) else None
                if not icecast_stats and redis_streaming_stats:
                    if isinstance(redis_streaming_stats, dict):
                        icecast_stats = redis_streaming_stats.get('icecast') or redis_streaming_stats

                if not icecast_url and icecast_stats and isinstance(icecast_stats, dict):
                    mount = icecast_stats.get('mount')
                    server = icecast_stats.get('server')
                    port = icecast_stats.get('port')
                    if mount and server and port:
                        icecast_url = f"http://{server}:{port}/{mount}"

                # Build a simplified source object from Redis data
                redis_metadata = redis_source_data.get('metadata')
                metadata = _merge_metadata(
                    redis_metadata,
                    latest_metric.source_metadata if latest_metric else None,
                    {
                        'stream_url': icecast_url,
                        'icecast_stream_url': icecast_url,
                    }
                )

                redis_timestamp = redis_source_data.get('timestamp') if redis_source_data else None
                metrics_timestamp = None
                if isinstance(redis_timestamp, (int, float)):
                    metrics_timestamp = datetime.fromtimestamp(redis_timestamp).isoformat()
                elif isinstance(redis_timestamp, datetime):
                    metrics_timestamp = redis_timestamp.isoformat()
                elif isinstance(redis_timestamp, str):
                    metrics_timestamp = redis_timestamp
                elif latest_metric and latest_metric.timestamp:
                    metrics_timestamp = latest_metric.timestamp.isoformat()

                def _first_defined(*candidates):
                    for candidate in candidates:
                        if candidate is not None:
                            return candidate
                    return None

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
                        'timestamp': metrics_timestamp,
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

                # Extract config parameters from JSONB field
                config_params = db_config.config_params or {}
                
                sources.append({
                    'id': db_config.name,  # Add id field for JavaScript compatibility
                    'name': db_config.name,
                    'type': db_config.source_type,
                    'status': _first_defined(redis_source_data.get('status') if redis_source_data else None, 'unknown'),
                    'enabled': db_config.enabled,
                    'priority': db_config.priority,
                    'auto_start': db_config.auto_start,
                    'description': db_config.description or '',
                    'config': {
                        'sample_rate': config_params.get('sample_rate', 44100),
                        'channels': config_params.get('channels', 1),
                        'buffer_size': config_params.get('buffer_size', 4096),
                        'silence_threshold_db': config_params.get('silence_threshold_db', -60.0),
                        'silence_duration_seconds': config_params.get('silence_duration_seconds', 5.0),
                        'device_params': config_params.get('device_params', {}),
                    },
                    'metrics': metrics_payload,
                    'error_message': None,
                    'in_memory': True,  # Running in audio-service container
                    'icecast_url': icecast_url,
                    'streaming': {
                        'icecast': _sanitize_streaming_stats(icecast_stats, icecast_url)
                    } if icecast_stats else None,
                    'redis_mode': True,  # Indicate data came from Redis
                })
                continue

            metadata = _merge_metadata(
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

            metrics_payload: Optional[Dict[str, Any]] = None
            if latest_metric:
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
            elif metadata:
                metrics_payload = {'metadata': metadata}

            # Extract config parameters from JSONB field
            config_params = db_config.config_params or {}
            
            sources.append({
                'id': db_config.name,  # Add id field for JavaScript compatibility
                'name': db_config.name,
                'type': db_config.source_type,
                'status': 'stopped',
                'enabled': db_config.enabled,
                'priority': db_config.priority,
                'auto_start': db_config.auto_start,
                'description': db_config.description or '',
                'config': {
                    'sample_rate': config_params.get('sample_rate', 44100),
                    'channels': config_params.get('channels', 1),
                    'buffer_size': config_params.get('buffer_size', 4096),
                    'silence_threshold_db': config_params.get('silence_threshold_db', -60.0),
                    'silence_duration_seconds': config_params.get('silence_duration_seconds', 5.0),
                    'device_params': config_params.get('device_params', {}),
                },
                'metrics': metrics_payload,
                'error_message': 'Not loaded in memory (restart required)',
                'in_memory': False,
                'icecast_url': icecast_url,
                'streaming': {
                    'icecast': _sanitize_streaming_stats(icecast_stats, icecast_url)
                } if icecast_stats else None,
            })

        return jsonify({
            'sources': sources,
            'total': len(sources),
            'active_count': sum(1 for s in sources if s['status'] == 'running'),
            'db_only_count': sum(1 for s in sources if not s.get('in_memory', True))
        })
    except Exception as exc:
        logger.error('Error getting audio sources: %s', exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/sources', methods=['POST'])
def api_create_audio_source():
    """Create a new audio source."""
    try:
        # Clear cache before creating
        clear_audio_source_cache()
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        source_type = data.get('type')
        name = data.get('name')
        if not source_type or not name:
            return jsonify({'error': 'type and name are required'}), 400

        # Parse source type
        try:
            audio_type = AudioSourceType(source_type)
        except ValueError:
            return jsonify({'error': f'Invalid source type: {source_type}'}), 400

        # Get controller first to ensure it's initialized
        # (prevents duplicate adapter creation when controller initializes from DB)
        controller = _get_audio_controller()

        # Check if source already exists in DATABASE (source of truth)
        existing_db_config = AudioSourceConfigDB.query.filter_by(name=name).first()
        if existing_db_config:
            return jsonify({
                'error': f'Source "{name}" already exists in database',
                'hint': 'Use DELETE /api/audio/sources/{name} first, or use PATCH to update'
            }), 400

        # Also check if source exists in memory (shouldn't happen, but be safe)
        if name in controller._sources:
            return jsonify({
                'error': f'Source "{name}" exists in memory but not in database (inconsistent state)',
                'hint': 'Contact system administrator - database sync issue'
            }), 500

        # Create configuration
        config = AudioSourceConfig(
            source_type=audio_type,
            name=name,
            enabled=data.get('enabled', True),
            priority=data.get('priority', 100),
            sample_rate=data.get('sample_rate', 44100),  # Native rate for source/stream
            channels=data.get('channels', 1),
            buffer_size=data.get('buffer_size', 4096),
            silence_threshold_db=data.get('silence_threshold_db', -60.0),
            silence_duration_seconds=data.get('silence_duration_seconds', 5.0),
            device_params=data.get('device_params', {}),
        )

        # Create adapter
        adapter = create_audio_source(config)

        # Add to controller
        controller.add_source(adapter)

        # Save to database AFTER adding to controller
        db_config = AudioSourceConfigDB(
            name=name,
            source_type=source_type,
            config_params={
                'sample_rate': config.sample_rate,
                'channels': config.channels,
                'buffer_size': config.buffer_size,
                'silence_threshold_db': config.silence_threshold_db,
                'silence_duration_seconds': config.silence_duration_seconds,
                'device_params': config.device_params,
            },
            priority=config.priority,
            enabled=config.enabled,
            auto_start=data.get('auto_start', False),
            description=data.get('description', ''),
        )
        db.session.add(db_config)
        try:
            db.session.commit()
        except Exception:
            # If database commit fails, remove from controller to keep state consistent
            db.session.rollback()
            controller.remove_source(name)
            raise

        logger.info('Created audio source: %s (Type: %s)', name, source_type)

        return jsonify({
            'source': _serialize_audio_source(name, adapter),
            'message': 'Audio source created successfully'
        }), 201

    except Exception as exc:
        logger.error('Error creating audio source: %s', exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/sources/<source_name>', methods=['GET'])
def api_get_audio_source(source_name: str):
    """Get details of a specific audio source."""
    try:
        controller, adapter, db_config, _ = _get_controller_and_adapter(source_name)

        if adapter is None:
            if db_config:
                return jsonify({
                    'error': 'Source exists in database but could not be loaded',
                    'hint': 'Check audio ingest logs for initialization errors',
                }), 503
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Check /api/audio/sources for available sources'
            }), 404

        return jsonify(_serialize_audio_source(source_name, adapter, db_config=db_config))

    except Exception as exc:
        logger.error('Error getting audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/sources/<source_name>', methods=['PATCH'])
def api_update_audio_source(source_name: str):
    """Update audio source configuration."""
    try:
        # Clear cache before updating
        clear_audio_source_cache(source_name)
        
        controller, adapter, db_config, _restored = _get_controller_and_adapter(source_name)

        if adapter is None:
            if db_config:
                return jsonify({
                    'error': 'Source exists in database but could not be loaded',
                    'hint': 'Check audio ingest logs for initialization errors',
                }), 503
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Check /api/audio/sources for available sources'
            }), 404

        config = adapter.config
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Update database configuration FIRST, before touching the in-memory config
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if db_config:
            if 'enabled' in data:
                db_config.enabled = data['enabled']
            if 'priority' in data:
                db_config.priority = data['priority']
            if 'auto_start' in data:
                db_config.auto_start = data['auto_start']
            if 'description' in data:
                db_config.description = data['description']

            # Update config params
            config_params = db_config.config_params or {}
            if 'silence_threshold_db' in data:
                config_params['silence_threshold_db'] = data['silence_threshold_db']
            if 'silence_duration_seconds' in data:
                config_params['silence_duration_seconds'] = data['silence_duration_seconds']
            if 'device_params' in data:
                device_params = config_params.get('device_params', {})
                device_params.update(data['device_params'])
                config_params['device_params'] = device_params

            db_config.config_params = config_params
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise

        # Update in-memory configuration AFTER the database transaction succeeds
        # This prevents inconsistency if the commit fails
        if 'enabled' in data:
            config.enabled = data['enabled']
        if 'priority' in data:
            config.priority = data['priority']
        if 'silence_threshold_db' in data:
            config.silence_threshold_db = data['silence_threshold_db']
        if 'silence_duration_seconds' in data:
            config.silence_duration_seconds = data['silence_duration_seconds']
        if 'device_params' in data:
            config.device_params.update(data['device_params'])

        logger.info('Updated audio source: %s', source_name)

        return jsonify({
            'source': _serialize_audio_source(source_name, adapter),
            'message': 'Audio source updated successfully'
        })

    except Exception as exc:
        logger.error('Error updating audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/sources/<source_name>', methods=['DELETE'])
def api_delete_audio_source(source_name: str):
    """Delete an audio source."""
    try:
        # Clear cache before deleting
        clear_audio_source_cache(source_name)
        
        controller, adapter, db_config, _ = _get_controller_and_adapter(source_name)

        if not db_config:
            return jsonify({'error': 'Source not found in database'}), 404

        # Stop if running (only if in memory)
        if adapter and adapter.status == AudioSourceStatus.RUNNING:
            controller.stop_source(source_name)

        # Remove from database FIRST
        db.session.delete(db_config)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        # Remove from controller AFTER database transaction succeeds
        # (only if it was in memory)
        if adapter:
            controller.remove_source(source_name)
            logger.info('Deleted audio source from both database and memory: %s', source_name)
        else:
            logger.info('Deleted audio source from database (was not in memory): %s', source_name)

        return jsonify({'message': 'Audio source deleted successfully'})

    except Exception as exc:
        logger.error('Error deleting audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/sources/<source_name>/start', methods=['POST'])
def api_start_audio_source(source_name: str):
    """
    Start audio ingestion from a source.

    In separated architecture, this publishes a command to Redis for audio-service to execute.
    """
    try:
        # Check if source exists in database
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if not db_config:
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Create the source first using POST /api/audio/sources'
            }), 404

        # Publish command to audio-service via Redis
        try:
            publisher = get_audio_command_publisher()
            result = publisher.start_source(source_name)

            if result['success']:
                logger.info('Published start command for audio source: %s', source_name)
                return jsonify({
                    'message': f'Start command sent to audio-service for source: {source_name}',
                    'command_id': result.get('command_id')
                })
            else:
                logger.error('Failed to publish start command: %s', result.get('message'))
                return jsonify({'error': result.get('message')}), 500

        except Exception as e:
            logger.error('Redis Pub/Sub unavailable, cannot send start command: %s', e)
            return jsonify({
                'error': 'Audio service communication unavailable',
                'hint': 'Check Redis connection and audio-service container status'
            }), 503

    except Exception as exc:
        logger.error('Error starting audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/sources/<source_name>/stop', methods=['POST'])
def api_stop_audio_source(source_name: str):
    """
    Stop audio ingestion from a source.

    In separated architecture, this publishes a command to Redis for audio-service to execute.
    """
    try:
        # Check if source exists in database
        db_config = AudioSourceConfigDB.query.filter_by(name=source_name).first()
        if not db_config:
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Create the source first using POST /api/audio/sources'
            }), 404

        # Publish command to audio-service via Redis
        try:
            publisher = get_audio_command_publisher()
            result = publisher.stop_source(source_name)

            if result['success']:
                logger.info('Published stop command for audio source: %s', source_name)
                return jsonify({
                    'message': f'Stop command sent to audio-service for source: {source_name}',
                    'command_id': result.get('command_id')
                })
            else:
                logger.error('Failed to publish stop command: %s', result.get('message'))
                return jsonify({'error': result.get('message')}), 500

        except Exception as e:
            logger.error('Redis Pub/Sub unavailable, cannot send stop command: %s', e)
            return jsonify({
                'error': 'Audio service communication unavailable',
                'hint': 'Check Redis connection and audio-service container status'
            }), 503

    except Exception as exc:
        logger.error('Error stopping audio source %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

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
                            'peak_level_db': source_data.get('peak_level_db', -120.0),
                            'rms_level_db': source_data.get('rms_level_db', -120.0),
                            'buffer_utilization': source_data.get('buffer_utilization', 0.0),
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
        # In separated architecture, app container doesn't run audio processing.
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

@audio_ingest_bp.route('/api/audio/alerts', methods=['GET'])
@cache.cached(timeout=10, query_string=True, key_prefix='audio_alerts')
def api_get_audio_alerts():
    """Get audio system alerts."""
    try:
        # Parse query parameters
        limit = request.args.get('limit', 50, type=int)
        limit = min(max(limit, 1), 500)  # Clamp between 1 and 500

        unresolved_only = request.args.get('unresolved_only', 'false').lower() == 'true'

        # Build query
        query = AudioAlert.query

        if unresolved_only:
            query = query.filter(AudioAlert.resolved == False)

        alerts = (
            query
            .order_by(desc(AudioAlert.created_at))
            .limit(limit)
            .all()
        )

        alerts_list = []
        for alert in alerts:
            alerts_list.append({
                'id': alert.id,
                'source_name': alert.source_name,
                'alert_level': alert.alert_level,
                'alert_type': alert.alert_type,
                'message': alert.message,
                'details': alert.details,
                'threshold_value': alert.threshold_value,
                'actual_value': alert.actual_value,
                'acknowledged': _sanitize_bool(alert.acknowledged) if alert.acknowledged is not None else False,
                'acknowledged_by': alert.acknowledged_by,
                'acknowledged_at': alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                'resolved': _sanitize_bool(alert.resolved) if alert.resolved is not None else False,
                'resolved_by': alert.resolved_by,
                'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
                'created_at': alert.created_at.isoformat() if alert.created_at else None,
            })

        unresolved_count = AudioAlert.query.filter(AudioAlert.resolved == False).count()

        return jsonify({
            'alerts': alerts_list,
            'total': len(alerts_list),
            'unresolved_count': unresolved_count,
        })

    except Exception as exc:
        logger.error('Error getting audio alerts: %s', exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/alerts/<int:alert_id>/acknowledge', methods=['POST'])
def api_acknowledge_alert(alert_id: int):
    """Acknowledge an audio alert."""
    try:
        alert = AudioAlert.query.get(alert_id)
        if not alert:
            return jsonify({'error': 'Alert not found'}), 404

        data = request.get_json() or {}
        acknowledged_by = data.get('acknowledged_by', 'system')

        alert.acknowledged = True
        alert.acknowledged_by = acknowledged_by
        alert.acknowledged_at = utc_now()
        alert.updated_at = utc_now()

        db.session.commit()

        logger.info('Acknowledged alert %d by %s', alert_id, acknowledged_by)

        return jsonify({'message': 'Alert acknowledged successfully'})

    except Exception as exc:
        logger.error('Error acknowledging alert %d: %s', alert_id, exc)
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/alerts/<int:alert_id>/resolve', methods=['POST'])
def api_resolve_alert(alert_id: int):
    """Resolve an audio alert."""
    try:
        alert = AudioAlert.query.get(alert_id)
        if not alert:
            return jsonify({'error': 'Alert not found'}), 404

        data = request.get_json() or {}
        resolved_by = data.get('resolved_by', 'system')
        resolution_notes = data.get('resolution_notes', '')

        alert.resolved = True
        alert.resolved_by = resolved_by
        alert.resolved_at = utc_now()
        alert.resolution_notes = resolution_notes
        alert.updated_at = utc_now()

        db.session.commit()

        logger.info('Resolved alert %d by %s', alert_id, resolved_by)

        return jsonify({'message': 'Alert resolved successfully'})

    except Exception as exc:
        logger.error('Error resolving alert %d: %s', alert_id, exc)
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/devices', methods=['GET'])
def api_discover_audio_devices():
    """Discover available audio input devices."""
    try:
        devices = []

        # Try to discover ALSA devices
        try:
            import alsaaudio
            alsa_devices = alsaaudio.pcms(alsaaudio.PCM_CAPTURE)
            for idx, device_name in enumerate(alsa_devices):
                devices.append({
                    'type': 'alsa',
                    'device_id': device_name,
                    'device_index': idx,
                    'name': device_name,
                    'description': f'ALSA Device: {device_name}',
                })
        except ImportError:
            logger.debug('alsaaudio not available for device discovery')
        except Exception as exc:
            logger.warning('Error discovering ALSA devices: %s', exc)

        # Try to discover PulseAudio/PyAudio devices
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            for idx in range(pa.get_device_count()):
                device_info = pa.get_device_info_by_index(idx)
                if device_info['maxInputChannels'] > 0:
                    devices.append({
                        'type': 'pulse',
                        'device_id': str(idx),
                        'device_index': idx,
                        'name': device_info['name'],
                        'description': f"PulseAudio: {device_info['name']}",
                        'sample_rate': int(device_info['defaultSampleRate']),
                        'max_channels': device_info['maxInputChannels'],
                    })
            pa.terminate()
        except ImportError:
            logger.debug('pyaudio not available for device discovery')
        except Exception as exc:
            logger.warning('Error discovering PulseAudio devices: %s', exc)

        return jsonify({
            'devices': devices,
            'total': len(devices),
        })

    except Exception as exc:
        logger.error('Error discovering audio devices: %s', exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/waveform/<source_name>', methods=['GET'])
def api_get_waveform(source_name: str):
    """Get waveform data for a specific audio source.

    Reads waveform data from Redis, published by the audio-service.
    """
    try:
        from app_core.redis_client import get_redis_client
        
        # Get waveform data from Redis
        r = get_redis_client()
        waveform_key = f"eas:waveform:{source_name}"
        waveform_json = r.get(waveform_key)
        
        if not waveform_json:
            # No waveform data available - source may not be running
            return jsonify({
                'source_name': source_name,
                'waveform': [],
                'sample_count': 0,
                'timestamp': time.time(),
                'status': 'no_data',
                'message': 'No waveform data available - source may not be running'
            }), 200
        
        # Parse and return waveform data
        waveform_data = json.loads(waveform_json)
        return jsonify(waveform_data), 200

    except Exception as exc:
        logger.error('Error getting waveform for %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/spectrogram/<source_name>')
def api_get_spectrogram(source_name: str):
    """Get spectrogram data for a specific audio source (for waterfall display).

    Reads spectrogram data from Redis, published by the audio-service.
    """
    try:
        from app_core.redis_client import get_redis_client
        
        # Get spectrogram data from Redis
        r = get_redis_client()
        spectrogram_key = f"eas:spectrogram:{source_name}"
        spectrogram_json = r.get(spectrogram_key)
        
        if not spectrogram_json:
            # No spectrogram data available - source may not be running
            return jsonify({
                'source_name': source_name,
                'spectrogram': [],
                'time_frames': 0,
                'frequency_bins': 0,
                'sample_rate': 48000,
                'fft_size': 1024,
                'timestamp': time.time(),
                'status': 'no_data',
                'message': 'No spectrogram data available - source may not be running'
            }), 200
        
        # Parse and return spectrogram data
        spectrogram_data = json.loads(spectrogram_json)
        return jsonify(spectrogram_data), 200

    except Exception as exc:
        logger.error('Error getting spectrogram for %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/stream/<source_name>')
def api_stream_audio(source_name: str):
    """Stream live audio from a specific source as WAV."""
    import struct
    import io
    from flask import Response, stream_with_context

    def generate_wav_stream(active_adapter: Any):
        """Generator that yields WAV-formatted audio chunks with resilient error handling.
        
        This generator is designed to NEVER fail - it will stream silence if needed to keep
        the connection alive, allowing clients to maintain continuous audio monitoring even
        through source failures or transient errors.
        """
        import numpy as np

        # Get configuration - even if source not running, we can stream silence
        sample_rate = active_adapter.config.sample_rate
        channels = active_adapter.config.channels
        bits_per_sample = 16  # 16-bit PCM

        # Constants for resilience
        SILENCE_CHUNK_DURATION = 0.05  # 50ms chunks of silence
        MAX_CONSECUTIVE_ERRORS = 50
        MAX_REALTIME_BLOCK_SECONDS = 0.25  # Cap live bursts to ~250ms to avoid chunky playback
        max_realtime_samples = int(sample_rate * channels * MAX_REALTIME_BLOCK_SECONDS)
        
        if active_adapter.status != AudioSourceStatus.RUNNING:
            logger.warning(
                f'Audio source not running for streaming: {source_name} (status={active_adapter.status.value}). '
                f'Will stream silence and wait for recovery.'
            )

        logger.info(f'Setting up WAV stream for {source_name}: {sample_rate}Hz, {channels}ch, {bits_per_sample}-bit')

        # Build streaming-friendly WAV header - always send this regardless of source status
        # If header generation fails, we'll build a minimal default header and continue
        header_sent = False
        try:
            wav_header = io.BytesIO()
            wav_header.write(b'RIFF')
            wav_header.write(struct.pack('<I', 0xFFFFFFFF))  # Placeholder for file size
            wav_header.write(b'WAVE')

            # fmt chunk
            wav_header.write(b'fmt ')
            wav_header.write(struct.pack('<I', 16))  # fmt chunk size
            wav_header.write(struct.pack('<H', 1))   # PCM format
            wav_header.write(struct.pack('<H', channels))
            wav_header.write(struct.pack('<I', sample_rate))
            wav_header.write(struct.pack('<I', sample_rate * channels * bits_per_sample // 8))  # byte rate
            wav_header.write(struct.pack('<H', channels * bits_per_sample // 8))  # block align
            wav_header.write(struct.pack('<H', bits_per_sample))

            # data chunk header
            wav_header.write(b'data')
            wav_header.write(struct.pack('<I', 0xFFFFFFFF))  # Placeholder for data size

            yield wav_header.getvalue()
            header_sent = True
            logger.debug(f'WAV header sent for {source_name}')
        except Exception as e:
            logger.error(f'Failed to generate WAV header for {source_name}: {e}', exc_info=True)
            # Try to send a minimal fallback header so stream can continue
            if not header_sent:
                try:
                    # Minimal WAV header with safe defaults (44100Hz mono)
                    fallback_header = (
                        b'RIFF\xff\xff\xff\xff'  # RIFF + size placeholder
                        b'WAVE'
                        b'fmt \x10\x00\x00\x00'  # fmt chunk (16 bytes)
                        b'\x01\x00'  # PCM format
                        b'\x01\x00'  # 1 channel
                        b'\x44\xac\x00\x00'  # 44100 Hz sample rate
                        b'\x88\x58\x01\x00'  # byte rate (44100 * 1 * 2)
                        b'\x02\x00'  # block align (1 * 2)
                        b'\x10\x00'  # 16 bits per sample
                        b'data\xff\xff\xff\xff'  # data chunk header
                    )
                    yield fallback_header
                    logger.warning(f'Sent fallback WAV header for {source_name}')
                except Exception as fallback_error:
                    logger.error(f'Even fallback header failed for {source_name}: {fallback_error}')
                    # Continue anyway - will stream raw PCM which some players can handle

        # Pre-buffer audio for smooth playback - continue even if we can't fill buffer
        logger.info(f'Pre-buffering audio for {source_name}')
        prebuffer = []
        prebuffer_target = int(sample_rate * 5)  # 5 seconds of audio for smooth playback on Pi
        prebuffer_samples = 0
        prebuffer_timeout = 10.0  # Max 10 seconds to fill prebuffer (increased for larger buffer)
        prebuffer_start = time.time()
        prebuffer_errors = 0

        while prebuffer_samples < prebuffer_target:
            if time.time() - prebuffer_start > prebuffer_timeout:
                logger.warning(
                    f'Prebuffer timeout for {source_name}, continuing with {prebuffer_samples}/{prebuffer_target} samples'
                )
                break

            try:
                audio_chunk = active_adapter.get_audio_chunk(timeout=0.5)  # Increased from 0.2s to 0.5s
                if audio_chunk is not None:
                    if not isinstance(audio_chunk, np.ndarray):
                        audio_chunk = np.array(audio_chunk, dtype=np.float32)

                    prebuffer.append(audio_chunk)
                    prebuffer_samples += len(audio_chunk)
            except Exception as e:
                prebuffer_errors += 1
                logger.warning(f'Error reading chunk during prebuffer for {source_name} (error {prebuffer_errors}): {e}')
                # Don't abort - just continue with what we have
                if prebuffer_errors > 10:
                    logger.warning(f'Multiple prebuffer errors for {source_name}, continuing anyway')
                    break

        # Yield pre-buffered audio
        logger.info(f'Streaming {len(prebuffer)} pre-buffered chunks for {source_name}')
        for chunk in prebuffer:
            try:
                pcm_data = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
                yield pcm_data.tobytes()
            except Exception as e:
                logger.warning(f'Error converting prebuffered chunk for {source_name}: {e}')
                # Continue with next chunk instead of failing

        # Stream audio chunks - this loop should NEVER exit except on client disconnect
        logger.info(f'Starting live audio stream for {source_name} (will stream forever until client disconnects)')
        chunk_count = len(prebuffer)
        silence_count = 0
        last_reported_status = active_adapter.status
        conversion_error_count = 0
        last_error_log_time = 0
        error_log_interval = 10.0  # Only log repeated errors every 10 seconds

        try:
            while True:  # Stream forever until client disconnects
                audio_chunk = None
                
                # Wrap chunk read in try/except to prevent read errors from terminating stream
                try:
                    # Get audio chunk from adapter (increased timeout to prevent underruns)
                    audio_chunk = active_adapter.get_audio_chunk(timeout=0.2)  # Optimal for Raspberry Pi stability
                except Exception as e:
                    current_time = time.time()
                    if current_time - last_error_log_time > error_log_interval:
                        logger.warning(f'Error reading audio chunk from {source_name}: {e}')
                        last_error_log_time = current_time
                    audio_chunk = None

                if audio_chunk is None:
                    # No data available - yield silence to keep HTTP stream alive
                    # This allows the stream to continue even if the source stops or has issues
                    current_status = active_adapter.status
                    
                    # Only log status changes to avoid log spam
                    if current_status != last_reported_status:
                        if current_status == AudioSourceStatus.STOPPED:
                            logger.warning(
                                f'Audio source stopped: {source_name} - streaming silence and waiting for recovery'
                            )
                        else:
                            logger.warning(
                                'Audio source %s status transitioned to %s - streaming silence until recovery',
                                source_name,
                                current_status.value,
                            )
                        last_reported_status = current_status

                    # Yield a small chunk of silence (50ms)
                    # This keeps the HTTP connection alive and prevents browser timeout
                    silence_samples = int(sample_rate * channels * SILENCE_CHUNK_DURATION)
                    silence_chunk = np.zeros(silence_samples, dtype=np.int16)
                    yield silence_chunk.tobytes()

                    silence_count += 1
                    
                    # Small sleep to avoid busy-waiting when source is idle
                    time.sleep(0.01)
                    continue

                # Reset silence counter when we get real data
                if silence_count > 0:
                    logger.info(f'Audio resumed for {source_name} after {silence_count} silent chunks')
                    silence_count = 0
                last_reported_status = active_adapter.status

                # Wrap conversion in try/except to prevent a single bad chunk from terminating stream
                try:
                    # Convert float32 [-1, 1] to int16 PCM
                    # Ensure we have a numpy array
                    if not isinstance(audio_chunk, np.ndarray):
                        audio_chunk = np.array(audio_chunk, dtype=np.float32)

                    if max_realtime_samples > 0 and len(audio_chunk) > max_realtime_samples:
                        # Trim to most recent audio to keep latency low and avoid bursty playback
                        audio_chunk = audio_chunk[-max_realtime_samples:]

                    # Clip to [-1, 1] range and convert to int16
                    audio_chunk = np.clip(audio_chunk, -1.0, 1.0)
                    pcm_data = (audio_chunk * 32767).astype(np.int16)

                    # Convert to bytes and yield
                    yield pcm_data.tobytes()
                    
                    chunk_count += 1
                    conversion_error_count = 0  # Reset error count on success
                    
                except Exception as e:
                    conversion_error_count += 1
                    current_time = time.time()
                    if current_time - last_error_log_time > error_log_interval:
                        logger.warning(
                            f'Error converting audio chunk for {source_name} '
                            f'(error {conversion_error_count} total): {e}'
                        )
                        last_error_log_time = current_time
                    
                    # Always yield silence on conversion error - NEVER stop the stream
                    silence_samples = int(sample_rate * channels * SILENCE_CHUNK_DURATION)
                    silence_chunk = np.zeros(silence_samples, dtype=np.int16)
                    yield silence_chunk.tobytes()

        except GeneratorExit:
            logger.info(f'Client disconnected from audio stream: {source_name} (streamed {chunk_count} chunks)')
        except Exception as exc:
            logger.error(f'Unexpected error in audio stream generator for {source_name}: {exc}', exc_info=True)

    try:
        # Get or restore audio source adapter on-demand to eliminate 503 errors
        # This allows audio streaming even if the source wasn't loaded at startup
        controller, adapter, db_config, restored = _get_controller_and_adapter(source_name)

        if adapter is None:
            if db_config:
                return jsonify({
                    'error': f'Audio source "{source_name}" exists but could not be loaded',
                    'hint': 'Check audio ingest logs for initialization errors. The source may require configuration.',
                    'alternative': 'Configure Icecast in Environment settings for production streaming'
                }), 503
            return jsonify({
                'error': f'Audio source "{source_name}" not found',
                'hint': 'Create the audio source first using POST /api/audio/sources',
                'alternative': 'Check /api/audio/sources for available sources'
            }), 404

        # If source was just restored, start it automatically for streaming
        if restored and adapter.status != AudioSourceStatus.RUNNING:
            try:
                logger.info(f'Auto-starting restored audio source for streaming: {source_name}')
                controller.start_source(source_name)
                # Give it a moment to initialize
                time.sleep(0.5)
            except Exception as start_exc:
                logger.warning(f'Failed to auto-start restored source {source_name}: {start_exc}')

        # Now stream the audio using the WAV generator
        return Response(
            stream_with_context(generate_wav_stream(adapter)),
            mimetype='audio/wav',
            headers={
                'Content-Disposition': f'inline; filename="{source_name}.wav"',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'X-Content-Type-Options': 'nosniff',
            }
        )

    except Exception as exc:
        logger.error('Error setting up audio stream for %s: %s', source_name, exc)
        return jsonify({'error': str(exc)}), 500

# NOTE: Legacy audio streaming code removed (lines 2094-2350)
# In separated architecture, audio streaming requires direct adapter access
# which only exists in audio-service container. Use Icecast instead.

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
                        peak_level_db = source_data.get('peak_level_db', -120.0)
                        rms_level_db = source_data.get('rms_level_db', -120.0)

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
                            'buffer_fill_percentage': source_data.get('buffer_utilization', 0.0) * 100,
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
                            'peak_level_db': source_data.get('peak_level_db', -120.0),
                            'rms_level_db': source_data.get('rms_level_db', -120.0),
                            'sample_rate': source_data.get('sample_rate', 0),
                            'frames_captured': source_data.get('frames_captured', 0),
                            'silence_detected': source_data.get('silence_detected', True),
                            'buffer_utilization': source_data.get('buffer_utilization', 0.0) * 100,
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

@audio_ingest_bp.route('/api/audio/icecast/config', methods=['GET'])
def api_get_icecast_config():
    """Get Icecast rebroadcast configuration."""
    try:
        from .environment import read_env_file

        env_vars = read_env_file()

        def _get(key: str, default: Optional[str] = None) -> Optional[str]:
            if key in env_vars:
                return env_vars[key]
            return os.environ.get(key, default)

        def _get_bool(key: str, default: bool = False) -> bool:
            value = _get(key)
            if value is None:
                return default
            return str(value).strip().lower() in {"1", "true", "yes", "on"}

        def _get_int(key: str, default: int) -> int:
            try:
                return int(_get(key, str(default)) or default)
            except (TypeError, ValueError):
                return default

        config = {
            'enabled': _get_bool('ICECAST_ENABLED', True),
            'server': _get('ICECAST_SERVER', 'icecast'),
            'port': _get_int('ICECAST_PORT', 8000),
            'external_port': _get_int('ICECAST_EXTERNAL_PORT', 8001),
            'password': _get('ICECAST_SOURCE_PASSWORD', ''),
            'admin_user': _get('ICECAST_ADMIN_USER', ''),
            'admin_password': _get('ICECAST_ADMIN_PASSWORD', ''),
            'public_hostname': _get('ICECAST_PUBLIC_HOSTNAME', ''),
            'mount': _get('ICECAST_DEFAULT_MOUNT', 'monitor.mp3'),
            'name': _get('ICECAST_STREAM_NAME', 'EAS Station Audio'),
            'description': _get('ICECAST_STREAM_DESCRIPTION', 'Emergency Alert System Audio Monitor'),
            'genre': _get('ICECAST_STREAM_GENRE', 'Emergency'),
            'bitrate': _get_int('ICECAST_STREAM_BITRATE', 128),
            'format': (_get('ICECAST_STREAM_FORMAT', 'mp3') or 'mp3').lower(),
            'public': _get_bool('ICECAST_STREAM_PUBLIC', False),
        }

        return jsonify(config)
    except Exception as exc:
        logger.error('Error getting Icecast config: %s', exc)
        return jsonify({'error': str(exc)}), 500

@audio_ingest_bp.route('/api/audio/icecast/config', methods=['POST'])
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

        from .environment import read_env_file, write_env_file

        env_vars = read_env_file()
        env_vars.update({
            'ICECAST_ENABLED': 'true' if enabled else 'false',
            'ICECAST_SERVER': server,
            'ICECAST_PORT': str(port),
            'ICECAST_SOURCE_PASSWORD': password,
            'ICECAST_ADMIN_USER': admin_user,
            'ICECAST_ADMIN_PASSWORD': admin_password,
            'ICECAST_PUBLIC_HOSTNAME': public_hostname,
            'ICECAST_STREAM_NAME': name,
            'ICECAST_STREAM_DESCRIPTION': description,
            'ICECAST_STREAM_GENRE': genre,
            'ICECAST_STREAM_BITRATE': str(bitrate),
            'ICECAST_STREAM_FORMAT': format_value,
            'ICECAST_STREAM_PUBLIC': 'true' if public else 'false',
            'ICECAST_DEFAULT_MOUNT': mount,
        })

        if external_port is not None:
            env_vars['ICECAST_EXTERNAL_PORT'] = str(external_port)
        elif 'ICECAST_EXTERNAL_PORT' in env_vars and data.get('external_port') in (None, ''):
            env_vars.pop('ICECAST_EXTERNAL_PORT', None)

        write_env_file(env_vars)

        os.environ['ICECAST_ENABLED'] = 'true' if enabled else 'false'
        os.environ['ICECAST_SERVER'] = server
        os.environ['ICECAST_PORT'] = str(port)
        os.environ['ICECAST_SOURCE_PASSWORD'] = password
        os.environ['ICECAST_ADMIN_USER'] = admin_user
        os.environ['ICECAST_ADMIN_PASSWORD'] = admin_password
        os.environ['ICECAST_PUBLIC_HOSTNAME'] = public_hostname
        os.environ['ICECAST_STREAM_FORMAT'] = format_value

        if external_port is not None:
            os.environ['ICECAST_EXTERNAL_PORT'] = str(external_port)

        current_app.config.update({
            'ICECAST_ENABLED': enabled,
            'ICECAST_SERVER': server,
            'ICECAST_PORT': port,
            'ICECAST_SOURCE_PASSWORD': password,
            'ICECAST_ADMIN_USER': admin_user,
            'ICECAST_ADMIN_PASSWORD': admin_password,
        })

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

@audio_ingest_bp.route('/audio/health/dashboard')
def audio_health_dashboard():
    """Render the health monitoring dashboard page."""
    return render_template('audio/health_dashboard.html')


__all__ = ['register_audio_ingest_routes']
