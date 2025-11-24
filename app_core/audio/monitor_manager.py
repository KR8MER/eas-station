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
    Initialize the global EAS monitor instance with real-time streaming decoder.

    IMPORTANT: In multi-worker setups, only the MASTER worker should initialize
    the EAS monitor. Slave workers will read shared metrics from the master.

    Args:
        audio_manager: AudioSourceManager or AudioIngestController instance
        alert_callback: Optional callback for alert detections
        auto_start: Whether to automatically start monitoring

    Returns:
        True if initialized successfully
    """
    global _monitor_instance

    # Check if this worker is authorized to run EAS monitor
    from .worker_coordinator import is_master_worker

    if not is_master_worker():
        logger.info(
            f"Worker PID {os.getpid()} is SLAVE - skipping EAS monitor initialization "
            "(master worker handles audio processing)"
        )
        return False

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

                # Get the active ingest source sample rate (the NATIVE rate of the audio stream).
                # Streams can be whatever rate they need (44.1k, 48k, etc.)
                # Default to 44100 Hz if no sources are configured yet
                ingest_sample_rate = audio_manager.get_active_sample_rate() or 44100

                audio_manager = BroadcastAudioAdapter(
                    broadcast_queue=broadcast_queue,
                    subscriber_id="eas-monitor",
                    sample_rate=int(ingest_sample_rate)
                )
                logger.info(
                    f"EAS monitor subscribed to broadcast queue: {broadcast_queue.name} "
                    f"(source_sample_rate={ingest_sample_rate}Hz)"
                )

                # CRITICAL: The EAS decoder MUST use 16 kHz (optimal rate with 7.7× Nyquist margin).
                # The EAS monitor will RESAMPLE from ingest_sample_rate to this 16 kHz decoder rate.
                # Streams keep their native sample rates - only the EAS decoder input is resampled.
                # DO NOT use 8 kHz - testing shows it's below recommended margins for production.
                # See docs/archive/root-docs/SAMPLE_RATE_OPTIMIZATION_COMPLETE.md for full analysis.
                target_sample_rate = 16000
            else:
                # For legacy AudioSourceManager, use 16 kHz decoder rate
                target_sample_rate = 16000

            _monitor_instance = ContinuousEASMonitor(
                audio_manager=audio_manager,
                sample_rate=target_sample_rate,
                alert_callback=alert_callback,
                save_audio_files=True,
                audio_archive_dir="/tmp/eas-audio"
            )

            logger.info("Initialized ContinuousEASMonitor (not yet started)")

            if auto_start:
                started = _monitor_instance.start()
                if started:
                    logger.info("✅ EAS monitor started automatically on MASTER worker")

                    # Start heartbeat writer to share metrics with slave workers
                    from .worker_coordinator import start_heartbeat_writer
                    start_heartbeat_writer(get_combined_metrics)
                    logger.info("Started metrics heartbeat writer for cross-worker coordination")
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

    # Stop heartbeat writer if running
    from .worker_coordinator import stop_heartbeat_writer
    stop_heartbeat_writer()


def get_combined_metrics() -> dict:
    """
    Get combined metrics from audio controller and EAS monitor.

    This function is called by the heartbeat writer to collect all metrics
    that should be shared across workers.

    Returns:
        Dictionary containing all relevant metrics
    """
    metrics = {
        "eas_monitor": None,
        "audio_controller": None,
        "broadcast_queue": None,
    }

    try:
        # Get EAS monitor stats
        if _monitor_instance is not None:
            try:
                monitor_stats = _monitor_instance.get_stats()
                metrics["eas_monitor"] = monitor_stats
            except Exception as e:
                logger.error(f"Error getting EAS monitor stats: {e}")

        # Get audio controller stats
        try:
            from webapp.admin.audio_ingest import _get_audio_controller
            controller = _get_audio_controller()

            if controller is not None:
                # Get controller stats
                controller_stats = {
                    "sources": {},
                    "active_source": controller.get_active_source_name(),
                }

                # Get per-source stats
                for name, source in controller._sources.items():
                    try:
                        source_stats = {
                            "status": source.status.value if hasattr(source.status, 'value') else str(source.status),
                            "sample_rate": getattr(source, 'sample_rate', None),
                        }

                        # Include VU meter metrics if available
                        if hasattr(source, 'metrics') and source.metrics:
                            metrics_obj = source.metrics
                            source_stats.update({
                                "peak_level_db": float(metrics_obj.peak_level_db) if metrics_obj.peak_level_db is not None else -120.0,
                                "rms_level_db": float(metrics_obj.rms_level_db) if metrics_obj.rms_level_db is not None else -120.0,
                                "buffer_utilization": float(metrics_obj.buffer_utilization) if metrics_obj.buffer_utilization is not None else 0.0,
                                "channels": metrics_obj.channels if hasattr(metrics_obj, 'channels') else 2,
                                "frames_captured": metrics_obj.frames_captured if hasattr(metrics_obj, 'frames_captured') else 0,
                                "silence_detected": bool(metrics_obj.silence_detected) if hasattr(metrics_obj, 'silence_detected') else False,
                                "timestamp": metrics_obj.timestamp if hasattr(metrics_obj, 'timestamp') else None,
                            })

                            if hasattr(metrics_obj, "metadata") and metrics_obj.metadata:
                                source_stats["metadata"] = metrics_obj.metadata

                        controller_stats["sources"][name] = source_stats
                    except Exception as e:
                        logger.error(f"Error getting stats for source '{name}': {e}")

                metrics["audio_controller"] = controller_stats

                # Get broadcast queue stats
                try:
                    broadcast_queue = controller.get_broadcast_queue()
                    if broadcast_queue:
                        metrics["broadcast_queue"] = broadcast_queue.get_stats()
                except Exception as e:
                    logger.error(f"Error getting broadcast queue stats: {e}")

        except Exception as e:
            logger.error(f"Error getting audio controller stats: {e}")

    except Exception as e:
        logger.error(f"Error collecting combined metrics: {e}")

    return metrics
