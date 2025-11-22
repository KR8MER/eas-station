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
            # Import here to avoid circular dependencies
            from app_core.audio import get_eas_monitor_instance

            monitor = get_eas_monitor_instance()
            initialization_attempted = False

            if monitor is None:
                # Attempt to initialize the monitoring system on-demand so the
                # status endpoint and UI don't get stuck showing stale data.
                try:
                    from app_core.audio.startup_integration import initialize_eas_monitoring_system

                    initialization_attempted = True
                    logger.info("EAS monitor missing; attempting on-demand initialization")
                    initialize_eas_monitoring_system()
                    monitor = get_eas_monitor_instance()
                except Exception as init_error:  # pragma: no cover - defensive
                    logger.error("On-demand EAS monitor initialization failed: %s", init_error, exc_info=True)
                    return jsonify({
                        "running": False,
                        "error": f"EAS monitor not initialized: {init_error}",
                        "initialization_attempted": True
                    }), 500

            if monitor is None:
                return jsonify({
                    "running": False,
                    "error": "EAS monitor not initialized. Configure audio sources and restart monitoring.",
                    "buffer_duration": 0,
                    "scan_interval": 0,
                    "buffer_utilization": 0,
                    "scans_performed": 0,
                    "alerts_detected": 0,
                    "last_scan_time": None,
                    "active_scans": 0,
                    "audio_flowing": False,
                    "sample_rate": 0,
                    "initialization_attempted": initialization_attempted
                })

            # Get status from monitor
            status = monitor.get_status()

            response_data: Dict[str, Any] = {
                # Basic status
                "running": status.get("running", False),
                "audio_flowing": status.get("audio_flowing", False),
                "mode": status.get("mode", "streaming"),
                "sample_rate": status.get("sample_rate", 0),
                "health_percentage": status.get("health_percentage", 0),

                # Streaming decoder metrics (what the UI renders today)
                "samples_processed": status.get("samples_processed", 0),
                "samples_per_second": status.get("samples_per_second", 0),
                "runtime_seconds": status.get("runtime_seconds", 0),
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

                # Backward-compatible fields expected by older dashboards
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
                "scan_warnings": status.get("scan_warnings", 0),  # Alias for backward compat
                "active_scans": status.get("active_scans", 0),
                "dynamic_max_concurrent_scans": status.get("dynamic_max_concurrent_scans", 0),
                "avg_scan_duration_seconds": status.get("avg_scan_duration_seconds"),
                "min_scan_duration_seconds": status.get("min_scan_duration_seconds"),
                "max_scan_duration_seconds": status.get("max_scan_duration_seconds"),
                "last_scan_duration_seconds": status.get("last_scan_duration_seconds"),
                "scan_history_size": status.get("scan_history_size", 0),
            }

            # Surface whether the route needed to self-heal the monitor
            response_data["initialization_attempted"] = initialization_attempted

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
        """
        try:
            from app_core.audio import get_eas_monitor_instance

            monitor = get_eas_monitor_instance()

            if monitor is None:
                return jsonify({
                    "history": [],
                    "error": "EAS monitor not initialized"
                })

            history = monitor.get_buffer_history()

            return jsonify({
                "history": history,
                "sample_rate": monitor.sample_rate,
                "mode": "streaming"
            })

        except Exception as e:
            logger.error(f"Error getting buffer history: {e}", exc_info=True)
            return jsonify({
                "history": [],
                "error": str(e)
            }), 500

    @app.route("/api/eas-monitor/control", methods=["POST"])
    def api_eas_monitor_control() -> Any:
        """Start or stop the EAS monitor.

        POST body: {"action": "start" or "stop"}
        """
        try:
            from app_core.audio import get_eas_monitor_instance, start_eas_monitor, stop_eas_monitor

            payload = request.get_json() or {}
            action = payload.get("action", "").lower()

            if action not in ["start", "stop"]:
                return jsonify({
                    "success": False,
                    "error": "Invalid action. Must be 'start' or 'stop'"
                }), 400

            if action == "start":
                result = start_eas_monitor()
                return jsonify({
                    "success": result,
                    "action": "start",
                    "message": "EAS monitor started" if result else "EAS monitor already running or failed to start"
                })
            else:  # stop
                result = stop_eas_monitor()
                return jsonify({
                    "success": result,
                    "action": "stop",
                    "message": "EAS monitor stopped" if result else "EAS monitor was not running"
                })

        except Exception as e:
            logger.error(f"Error controlling EAS monitor: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    logger.info("Registered EAS monitor status routes")
