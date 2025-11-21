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
Global EAS Monitor Manager

Manages the singleton ContinuousEASMonitor instance for the application.
Provides thread-safe access and lifecycle management.
"""

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Global monitor instance
_monitor_instance: Optional['ContinuousEASMonitor'] = None
_monitor_lock = threading.Lock()


def get_eas_monitor_instance() -> Optional['ContinuousEASMonitor']:
    """Get the global EAS monitor instance (may be None if not initialized)."""
    return _monitor_instance


def initialize_eas_monitor(audio_manager, alert_callback=None, auto_start=True) -> bool:
    """
    Initialize the global EAS monitor instance.

    Args:
        audio_manager: AudioSourceManager or AudioIngestController instance
        alert_callback: Optional callback for alert detections
        auto_start: Whether to automatically start monitoring

    Returns:
        True if initialized successfully
    
    Environment Variables:
        MAX_CONCURRENT_EAS_SCANS: Maximum number of concurrent scan threads (default: 2)
                                  Increase for faster hardware or to reduce scan skipping
    """
    global _monitor_instance

    with _monitor_lock:
        if _monitor_instance is not None:
            logger.warning("EAS monitor already initialized")
            return False

        try:
            from .eas_monitor import ContinuousEASMonitor
            from .ingest import AudioIngestController
            from .broadcast_adapter import BroadcastAudioAdapter

            # If we got an AudioIngestController, use broadcast adapter for non-destructive audio access
            if isinstance(audio_manager, AudioIngestController):
                logger.info("Creating BroadcastAudioAdapter for EAS monitor (non-destructive subscription)")
                broadcast_queue = audio_manager.get_broadcast_queue()
                audio_manager = BroadcastAudioAdapter(
                    broadcast_queue=broadcast_queue,
                    subscriber_id="eas-monitor",
                    sample_rate=22050
                )
                logger.info(f"EAS monitor subscribed to broadcast queue: {broadcast_queue.name}")

            # Read max_concurrent_scans from environment variable
            max_concurrent_scans = 2  # default
            env_value = os.getenv('MAX_CONCURRENT_EAS_SCANS')
            if env_value:
                try:
                    max_concurrent_scans = int(env_value)
                    logger.info(f"Using MAX_CONCURRENT_EAS_SCANS={max_concurrent_scans} from environment")
                except ValueError:
                    logger.warning(f"Invalid MAX_CONCURRENT_EAS_SCANS value '{env_value}', using default: 2")

            _monitor_instance = ContinuousEASMonitor(
                audio_manager=audio_manager,
                buffer_duration=12.0,  # 12s captures full SAME sequence (3s × 3 bursts + margin)
                scan_interval=3.0,  # 3s interval creates 75% overlap to never miss alerts
                sample_rate=22050,
                alert_callback=alert_callback,
                save_audio_files=True,
                audio_archive_dir="/tmp/eas-audio",
                max_concurrent_scans=max_concurrent_scans
            )

            logger.info("Initialized ContinuousEASMonitor (not yet started)")

            if auto_start:
                started = _monitor_instance.start()
                if started:
                    logger.info("EAS monitor started automatically")
                else:
                    logger.warning("EAS monitor failed to auto-start")
                return started

            return True

        except Exception as e:
            logger.error(f"Failed to initialize EAS monitor: {e}", exc_info=True)
            _monitor_instance = None
            return False


def start_eas_monitor() -> bool:
    """Start the EAS monitor (must be initialized first)."""
    global _monitor_instance

    with _monitor_lock:
        if _monitor_instance is None:
            logger.error("Cannot start EAS monitor - not initialized")
            return False

        try:
            return _monitor_instance.start()
        except Exception as e:
            logger.error(f"Error starting EAS monitor: {e}", exc_info=True)
            return False


def stop_eas_monitor() -> bool:
    """Stop the EAS monitor."""
    global _monitor_instance

    with _monitor_lock:
        if _monitor_instance is None:
            logger.warning("Cannot stop EAS monitor - not initialized")
            return False

        try:
            _monitor_instance.stop()
            return True
        except Exception as e:
            logger.error(f"Error stopping EAS monitor: {e}", exc_info=True)
            return False


def shutdown_eas_monitor() -> None:
    """Shutdown and cleanup the EAS monitor."""
    global _monitor_instance

    with _monitor_lock:
        if _monitor_instance is not None:
            try:
                _monitor_instance.stop()
                logger.info("EAS monitor shut down")
            except Exception as e:
                logger.error(f"Error during EAS monitor shutdown: {e}", exc_info=True)
            finally:
                _monitor_instance = None
