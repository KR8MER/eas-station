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

            if monitor is None:
                return jsonify({
                    "running": False,
                    "error": "EAS monitor not initialized",
                    "buffer_duration": 0,
                    "scan_interval": 0,
                    "buffer_utilization": 0,
                    "scans_performed": 0,
                    "alerts_detected": 0,
                    "last_scan_time": None,
                    "active_scans": 0,
                    "audio_flowing": False,
                    "sample_rate": 0
                })

            # Get status from monitor
            status = monitor.get_status()

            return jsonify({
                "running": status.get("running", False),
                "buffer_duration": status.get("buffer_duration", 0),
                "scan_interval": status.get("scan_interval", 0),
                "buffer_utilization": status.get("buffer_utilization", 0),
                "buffer_fill_seconds": status.get("buffer_fill_seconds", 0),
                "scans_performed": status.get("scans_performed", 0),
                "alerts_detected": status.get("alerts_detected", 0),
                "last_scan_time": status.get("last_scan_time"),
                "last_alert_time": status.get("last_alert_time"),
                "active_scans": status.get("active_scans", 0),
                "audio_flowing": status.get("audio_flowing", False),
                "sample_rate": status.get("sample_rate", 0),
                "scan_warnings": status.get("scan_warnings", 0)
            })

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
                "buffer_duration": monitor.buffer_duration
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
