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

"""Audio ingest controller singleton, startup and the Redis metrics bridge."""

import logging
from typing import Any, Dict, List, Optional, Tuple
from flask import Blueprint, Flask, jsonify, render_template, request, current_app, Response, stream_with_context
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

logger = logging.getLogger(__name__)


def _read_audio_metrics_from_redis() -> Optional[Dict[str, Any]]:
    """
    Read audio metrics from Redis (published by audio-service process).

    In separated architecture, the audio-service process publishes metrics to Redis.
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


# Global audio ingest controller instance
_audio_controller: Optional[AudioIngestController] = None


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


def _peek_audio_controller() -> Optional[AudioIngestController]:
    """Return the controller singleton, or ``None`` if one was never created.

    The sibling of ``_get_auto_streaming_service``. Callers in other modules of
    this package must go through this rather than importing ``_audio_controller``
    directly: ``from .controller import _audio_controller`` snapshots the value
    at import time, which is ``None``, and would never see the singleton that
    ``_get_audio_controller`` later installs.
    """
    return _audio_controller


def _get_audio_controller() -> AudioIngestController:
    """Get or create the global audio ingest controller."""
    global _audio_controller, _initialization_started

    if _audio_controller is None:
        # Capture Flask app for background thread context
        app = current_app._get_current_object()
        
        # Create the controller immediately (lightweight)
        # Pass Flask app so background threads can use app context
        _audio_controller = AudioIngestController(flask_app=app)

        # Register the controller with the EAS stream injector so that
        # generated alert audio is published to Icecast broadcast queues.
        try:
            from app_core.audio.eas_stream_injector import set_controller as _set_injector_controller
            _set_injector_controller(_audio_controller)
        except Exception as _inj_reg_exc:
            logger.warning("Could not register EAS stream injector controller: %s", _inj_reg_exc)

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

    SEPARATED ARCHITECTURE: This function should NOT run in the web application process.
    Audio processing is handled entirely by the dedicated audio-service process.
    The web application process only serves the UI and reads metrics from Redis.
    """
    # The pre-split version also declared ``_streaming_lock_file`` global here.
    # That name now lives in ``streaming``, and this function returns before it
    # could ever be read or assigned, so the declaration was dropped rather than
    # dragging a circular import in to preserve a statement with no effect.
    global _audio_controller, _audio_initialization_lock_file

    # Separated architecture: Audio processing handled by dedicated audio-service process
    # Skip ALL audio initialization in web application process
    logger.info("🌐 Web application in separated architecture - skipping audio source startup")
    logger.info("   Audio processing handled by dedicated audio-service process")
    return
