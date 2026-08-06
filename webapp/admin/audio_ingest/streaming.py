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

"""Auto-streaming (Icecast) service lifecycle."""

import logging
import os
from typing import Any, Dict, Optional, Tuple
from app_core.audio.ingest import AudioSourceStatus

from .controller import _get_audio_controller, _read_audio_metrics_from_redis, _try_acquire_lock

logger = logging.getLogger(__name__)


# Global auto-streaming service instance
_auto_streaming_service = None


# Global lock file to prevent duplicate streaming services across workers
_streaming_lock_file = None


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
        from flask import current_app

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
                audio_controller=controller,
                flask_app=current_app._get_current_object(),
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
        from flask import current_app

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
                audio_controller=controller,
                flask_app=current_app._get_current_object(),
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

    # Separated deployments run the streaming service in the audio-service process.
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
