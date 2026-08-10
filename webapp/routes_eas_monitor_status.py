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

"""
EAS Monitor Status API Routes

Provides real-time status of continuous EAS monitoring including:
- Monitor running state
- Buffer status and utilization
- Scan performance metrics
- Recent alert detections
"""

import logging
from typing import Any, Dict
from flask import Flask, jsonify, request
from app_core.auth.roles import require_permission

logger = logging.getLogger(__name__)


def register_eas_monitor_routes(app: Flask, logger_instance) -> None:
    """Register EAS monitoring status routes."""
    # Use passed logger if provided
    global logger
    if logger_instance:
        logger = logger_instance

    @app.route("/api/eas-monitor/status")
    def api_eas_monitor_status() -> Any:
        """Get current EAS monitor status and metrics.

        IMPORTANT: In multi-worker setups, SLAVE workers read metrics from
        shared file written by MASTER worker. This ensures consistent metrics
        across all workers.

        Returns JSON with:
        - running: bool - Is monitor active
        - buffer_duration: float - Buffer size in seconds
        - scan_interval: float - Time between scans
        - buffer_utilization: float - How full the buffer is (0-100%)
        - scans_performed: int - Total scans completed
        - alerts_detected: int - Total alerts found
        - last_scan_time: float - Unix timestamp of last scan
        - active_scans: int - Number of concurrent scans
        - audio_flowing: bool - Is audio being captured
        - sample_rate: int - Audio sample rate
        """
        try:
            # Separated architecture: Always read from Redis (published by audio-service)
            # Import here to avoid circular dependencies
            from app_core.audio.worker_coordinator import read_shared_metrics

            logger.debug("Reading EAS monitor status from Redis (published by audio-service process)")
            shared_metrics = read_shared_metrics()

            # Debug: Log what we actually got from Redis
            if shared_metrics is None:
                logger.warning("read_shared_metrics() returned None - Redis may be unreachable or empty")
            else:
                logger.debug(f"read_shared_metrics() returned keys: {list(shared_metrics.keys())}")

            if shared_metrics is None or "eas_monitor" not in shared_metrics:
                # Distinguish between "service never published" and "metrics expired/stale"
                if shared_metrics is None:
                    error_msg = (
                        "Audio service metrics are unavailable. "
                        "The audio-service may not be running or Redis is unreachable."
                    )
                else:
                    # Metrics hash exists in Redis but has no eas_monitor key — the
                    # audio-service is running but the EAS monitor has not yet published
                    # its first status snapshot (usually ready within 5 seconds).
                    error_msg = (
                        "EAS monitor status not yet available from audio-service "
                        "(service is running — status will appear within a few seconds)."
                    )
                return jsonify({
                    "running": False,
                    "error": error_msg,
                    "worker_role": "app",
                    "initialization_attempted": False,
                    "debug_metrics_is_none": shared_metrics is None,
                    "debug_metrics_keys": list(shared_metrics.keys()) if shared_metrics else None
                })

            # Extract EAS monitor stats from shared metrics
            status = shared_metrics.get("eas_monitor", {})

            # Ensure status is a dictionary, not a string or other type.
            # Non-dict values indicate the EAS monitor was not yet initialized
            # when the last metrics snapshot was published.
            if not isinstance(status, dict):
                logger.warning(f"EAS monitor status has unexpected type: {type(status).__name__}, value: {status}")
                return jsonify({
                    "running": False,
                    "error": (
                        "EAS monitor status has an unexpected format from audio-service. "
                        "The service may be initializing — please wait a few seconds."
                    ),
                    "worker_role": "app",
                    "initialization_attempted": False,
                    "debug_metrics_is_none": False,
                    "debug_metrics_keys": list(shared_metrics.keys()) if shared_metrics else None
                })

            if not status:
                return jsonify({
                    "running": False,
                    "error": "EAS monitor not running in audio-service",
                    "worker_role": "app",
                    "initialization_attempted": False
                })

            # HANDLE MULTI-MONITOR AGGREGATED FORMAT
            # If status has a "monitors" key, it's aggregated stats from MultiMonitorManager
            # Preserve aggregated fields while extracting detailed stats from first monitor
            aggregated_status = None
            if "monitors" in status and isinstance(status["monitors"], dict):
                # Save the aggregated status before extracting individual monitor stats
                aggregated_status = status.copy()
                
                monitors_dict = status["monitors"]
                if monitors_dict:
                    # Get the first monitor's stats (usually there's only one or two)
                    # Use next() with a default to handle empty dict gracefully
                    first_monitor_key = next(iter(monitors_dict.keys()), None)
                    if first_monitor_key:
                        first_monitor_stats = monitors_dict[first_monitor_key]
                        
                        # Verify it's a dict before copying
                        if isinstance(first_monitor_stats, dict):
                            logger.debug(f"Using stats from monitor '{first_monitor_key}' for UI display")
                            # Use the individual monitor's stats
                            status = first_monitor_stats.copy()
                            # CRITICAL: Preserve aggregated fields that UI needs
                            # These fields must come from aggregated_status, not individual monitor
                            status["running"] = aggregated_status.get("running", False)
                            status["monitor_count"] = aggregated_status.get("monitor_count", 0)
                            status["active_sources"] = aggregated_status.get("active_sources", 0)
                            status["audio_flowing"] = aggregated_status.get("audio_flowing", False)
                            status["source_names"] = aggregated_status.get("source_names", [])
                            # CRITICAL FIX: Use aggregated samples/rate, not per-source values
                            status["samples_processed"] = aggregated_status.get("samples_processed", 0)
                            status["samples_per_second"] = aggregated_status.get("samples_per_second", 0)
                            status["wall_clock_runtime_seconds"] = aggregated_status.get("wall_clock_runtime_seconds", 0)
                            status["runtime_seconds"] = aggregated_status.get("runtime_seconds", 0)
                            status["health_percentage"] = aggregated_status.get("health_percentage", 0)
                            status["alerts_detected"] = aggregated_status.get("alerts_detected", 0)
                            status["decoder_synced"] = aggregated_status.get("decoder_synced", False)
                            status["decoder_in_message"] = aggregated_status.get("decoder_in_message", False)
                            status["decoder_bytes_decoded"] = aggregated_status.get("decoder_bytes_decoded", 0)
                        else:
                            logger.warning(f"Monitor '{first_monitor_key}' stats is not a dict: {type(first_monitor_stats)}")
                    else:
                        logger.warning("Monitors dict is empty")

            # Build response from shared metrics
            monitor_count = status.get("monitor_count", 0)
            response_data: Dict[str, Any] = {
                # Basic status
                "running": status.get("running", False),
                "audio_flowing": status.get("audio_flowing", False),
                "mode": status.get("mode", "streaming"),
                "sample_rate": status.get("sample_rate", 0),
                "source_sample_rate": status.get("source_sample_rate"),
                "resample_ratio": status.get("resample_ratio"),
                "health_percentage": status.get("health_percentage", 0),
                
                # Multi-monitor aggregated fields (CRITICAL for UI logic)
                "monitor_count": monitor_count,
                "active_sources": status.get("active_sources", 0),
                "source_names": status.get("source_names", []),

                # Surfaced when the EAS monitor is running but has discovered no
                # active audio sources yet (e.g. all sources are stopped or the
                # service just started and discovery hasn't run).  The frontend
                # uses this flag to show actionable guidance instead of a generic
                # error.
                "no_sources_running": status.get("running", False) and monitor_count == 0,

                # Streaming decoder metrics
                "samples_processed": status.get("samples_processed", 0),
                "samples_per_second": status.get("samples_per_second", 0),
                "runtime_seconds": status.get("runtime_seconds", 0),
                "wall_clock_runtime_seconds": status.get("wall_clock_runtime_seconds", 0),
                "decoder_synced": status.get("decoder_synced", False),
                "decoder_in_message": status.get("decoder_in_message", False),
                "decoder_bytes_decoded": status.get("decoder_bytes_decoded", 0),

                # Alert detection
                "alerts_detected": status.get("alerts_detected", 0),
                "last_scan_time": status.get("last_scan_time"),
                "last_alert_time": status.get("last_alert_time"),

                # Health metrics
                "last_activity": status.get("last_activity"),
                "time_since_activity": status.get("time_since_activity", 0),
                "restart_count": status.get("restart_count", 0),
                "watchdog_timeout": status.get("watchdog_timeout", 0),

                # Backward-compatible fields
                "buffer_duration": status.get("buffer_duration", 0),
                "buffer_utilization": status.get("buffer_utilization", 0),
                "buffer_fill_seconds": status.get("buffer_fill_seconds", 0),
                "scan_interval": status.get("scan_interval", 0),
                "effective_scan_interval": status.get("effective_scan_interval", 0),
                "scan_interval_auto_adjusted": status.get("scan_interval_auto_adjusted", False),
                "max_concurrent_scans": status.get("max_concurrent_scans", 0),
                "scans_performed": status.get("scans_performed", 0),
                "scans_skipped": status.get("scans_skipped", 0),
                "scans_no_signature": status.get("scans_no_signature", 0),
                "total_scan_attempts": status.get("total_scan_attempts", 0),
                "scan_warnings": status.get("scan_warnings", 0),
                "active_scans": status.get("active_scans", 0),
                "dynamic_max_concurrent_scans": status.get("dynamic_max_concurrent_scans", 0),
                "avg_scan_duration_seconds": status.get("avg_scan_duration_seconds"),
                "min_scan_duration_seconds": status.get("min_scan_duration_seconds"),
                "max_scan_duration_seconds": status.get("max_scan_duration_seconds"),
                "last_scan_duration_seconds": status.get("last_scan_duration_seconds"),
                "scan_history_size": status.get("scan_history_size", 0),

                # Audio subscription health
                "audio_buffer_samples": status.get("audio_buffer_samples"),
                "audio_buffer_seconds": status.get("audio_buffer_seconds"),
                "audio_queue_depth": status.get("audio_queue_depth"),
                "audio_underruns": status.get("audio_underruns"),
                "audio_underrun_rate_percent": status.get("audio_underrun_rate_percent"),
                "audio_last_audio_time": status.get("audio_last_audio_time"),
                "audio_health": status.get("audio_health"),
                "audio_subscriber_id": status.get("audio_subscriber_id"),

                # Container architecture metadata
                "worker_role": "app",
                "initialization_attempted": False,
                "audio_service_pid": shared_metrics.get("_master_pid"),
                "metrics_age": shared_metrics.get("_heartbeat"),
            }

            return jsonify(response_data)

        except Exception as e:
            logger.error(f"Error getting EAS monitor status: {e}", exc_info=True)
            return jsonify({
                "running": False,
                "error": str(e)
            }), 500

    @app.route("/api/eas-monitor/buffer-history")
    def api_eas_monitor_buffer_history() -> Any:
        """Get buffer utilization history for graphing.

        Returns last 60 data points (typically 5 minutes at 5s intervals).

        In separated architecture, buffer history is published by audio-service
        to Redis. The web application process reads it from there.
        """
        try:
            # Separated architecture: Read buffer history from Redis
            from app_core.audio.worker_coordinator import read_shared_metrics

            shared_metrics = read_shared_metrics()

            if shared_metrics is None or "eas_monitor" not in shared_metrics:
                return jsonify({
                    "history": [],
                    "error": "EAS monitor metrics not available from audio-service"
                })

            eas_status = shared_metrics.get("eas_monitor", {})
            if eas_status is None:
                return jsonify({
                    "history": [],
                    "error": "EAS monitor not running in audio-service"
                })

            # Buffer history may not be published to Redis to avoid large payloads
            # Return buffer fill percentage history if available
            buffer_history = eas_status.get("buffer_history", [])
            sample_rate = eas_status.get("sample_rate", 16000)

            return jsonify({
                "history": buffer_history,
                "sample_rate": sample_rate,
                "mode": "streaming"
            })

        except Exception as e:
            logger.error(f"Error getting buffer history: {e}", exc_info=True)
            return jsonify({
                "history": [],
                "error": str(e)
            }), 500

    @app.route("/api/eas-monitor/control", methods=["POST"])
    @require_permission('system.configure')
    def api_eas_monitor_control() -> Any:
        """Start or stop the EAS monitor.

        POST body: {"action": "start" or "stop"}

        In separated architecture, this sends a command to audio-service via Redis
        Pub/Sub to control the EAS monitor running there.
        """
        try:
            payload = request.get_json() or {}
            action = payload.get("action", "").lower()

            if action not in ["start", "stop"]:
                return jsonify({
                    "success": False,
                    "error": "Invalid action. Must be 'start' or 'stop'"
                }), 400

            # Send command to audio-service via Redis Pub/Sub
            from app_core.audio.redis_commands import get_audio_command_publisher

            try:
                publisher = get_audio_command_publisher()

                if action == "start":
                    result = publisher.start_eas_monitor()
                else:
                    result = publisher.stop_eas_monitor()

                if result.get('success'):
                    return jsonify({
                        "success": True,
                        "action": action,
                        "message": f"EAS monitor {action} command sent to audio-service",
                        "command_id": result.get('command_id')
                    })

                # No subscribers means the audio service is down — that is a
                # dependency failure (503), not an internal error (500), and
                # the operator needs to be told which service to start.
                status_code = 503 if result.get('no_subscribers') else 500
                return jsonify({
                    "success": False,
                    "action": action,
                    "error": result.get('message', f'Failed to send {action} command'),
                    "message": result.get('message', f'Failed to send {action} command'),
                    "hint": (
                        "Start the eas-station-audio service from "
                        "Settings → Services, then retry."
                        if result.get('no_subscribers') else None
                    ),
                }), status_code

            except Exception as redis_error:
                logger.error(f"Redis communication failed: {redis_error}")
                return jsonify({
                    "success": False,
                    "error": f"Cannot communicate with audio-service: {str(redis_error)}",
                    "hint": "Check that Redis and audio-service processes are running"
                }), 503

        except Exception as e:
            logger.error(f"Error controlling EAS monitor: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    logger.info("Registered EAS monitor status routes")
