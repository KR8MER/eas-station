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

"""Acting on a configured receiver: restart, and audio-monitor wiring."""

import json
import time
import uuid
from typing import Any, Dict

from flask import Flask, jsonify, request

from app_core.models import RadioReceiver
from app_core.radio import (
    ensure_radio_tables,
)
from app_core.auth.roles import require_permission
from webapp.admin.audio_ingest import (
    ensure_sdr_audio_monitor_source,
    _get_audio_controller,
    _get_icecast_stream_url,
)

from . import deps


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    @app.route("/api/radio/receivers/<int:receiver_id>/restart", methods=["POST"])
    @require_permission('receivers.configure')
    def api_restart_receiver(receiver_id: int) -> Any:
        """Restart a receiver to recover from errors.

        This sends a restart command via Redis to SDR hardware service process,
        which has direct access to RadioManager and SDR hardware.
        """
        ensure_radio_tables(route_logger)
        receiver_record = RadioReceiver.query.get_or_404(receiver_id)

        try:
            # Generate unique command ID for tracking
            command_id = str(uuid.uuid4())

            # Get Redis client
            redis_client = deps.get_redis_client()

            # Send restart command to sdr-service
            command = {
                "action": "restart",
                "receiver_id": receiver_record.identifier,
                "command_id": command_id,
            }

            route_logger.info(
                "Sending restart command to sdr-service for receiver %s (command_id=%s)",
                receiver_record.identifier,
                command_id
            )

            redis_client.rpush("sdr:commands", json.dumps(command))

            # Wait for result (with timeout)
            timeout = 10  # seconds
            start_time = time.time()
            result = None

            while time.time() - start_time < timeout:
                result_json = redis_client.get(f"sdr:command_result:{command_id}")
                if result_json:
                    result = json.loads(result_json)
                    break
                time.sleep(0.2)  # Poll every 200ms

            if not result:
                route_logger.error(
                    "Timeout waiting for restart command result (command_id=%s)",
                    command_id
                )
                return jsonify({
                    "error": "Timeout waiting for sdr-service to process restart command",
                    "hint": "Check if sdr-service is running: sudo systemctl status eas-station-sdr.service"
                }), 504

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                route_logger.error(
                    "Failed to restart receiver %s: %s",
                    receiver_record.identifier,
                    error_msg
                )
                deps._log_radio_event(
                    "ERROR",
                    f"Failed to restart receiver {receiver_record.identifier}: {error_msg}",
                    module_suffix="actions",
                    details={
                        "identifier": receiver_record.identifier,
                        "error": error_msg,
                    },
                )
                return jsonify({
                    "error": f"Failed to restart receiver: {error_msg}"
                }), 500

            # Success!
            receiver_status = result.get("status", {})

            deps._log_radio_event(
                "INFO",
                f"Restarted receiver {receiver_record.identifier}",
                module_suffix="actions",
                details={
                    "identifier": receiver_record.identifier,
                    "locked": receiver_status.get("locked"),
                    "signal_strength": receiver_status.get("signal_strength"),
                },
            )

            return jsonify({
                "success": True,
                "message": f"Receiver '{receiver_record.display_name}' restarted successfully",
                "status": receiver_status
            })

        except Exception as exc:
            route_logger.error(
                "Failed to send restart command for receiver %s: %s",
                receiver_record.identifier,
                exc,
                exc_info=True
            )
            deps._log_radio_event(
                "ERROR",
                f"Failed to restart receiver {receiver_record.identifier}: {exc}",
                module_suffix="actions",
                details={
                    "identifier": receiver_record.identifier,
                    "error": str(exc),
                },
            )
            return jsonify({
                "error": f"Failed to restart receiver: {str(exc)}"
            }), 500

    @app.route("/api/radio/receivers/<int:receiver_id>/audio-monitor", methods=["POST"])
    @require_permission('receivers.configure')
    def api_ensure_audio_monitor(receiver_id: int) -> Any:
        """Ensure an SDR audio monitor exists for the receiver and optionally start it."""

        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)
        payload = request.get_json(silent=True) or {}
        start_now = bool(payload.get("start"))

        try:
            result = ensure_sdr_audio_monitor_source(
                receiver,
                start_immediately=start_now,
                commit=True,
            )
        except Exception as exc:
            route_logger.error(
                "Failed to ensure audio monitor for %s: %s",
                receiver.identifier,
                exc,
                exc_info=True,
            )
            deps._log_radio_event(
                "ERROR",
                f"Failed to ensure audio monitor for {receiver.identifier}: {exc}",
                module_suffix="audio.ensure",
                details={
                    "identifier": receiver.identifier,
                    "error": str(exc),
                },
            )
            return jsonify({"error": "Unable to provision audio monitor."}), 500

        source_name = result.get("source_name")
        controller = None
        adapter = None
        status_value = None
        metadata = None
        icecast_url = None

        try:
            controller = _get_audio_controller()
        except Exception:
            controller = None

        if controller and source_name:
            adapter = controller._sources.get(source_name)
            if adapter is not None:
                status = getattr(adapter, "status", None)
                status_value = status.value if status else None
                metrics = getattr(adapter, "metrics", None)
                metadata = getattr(metrics, "metadata", None)
                icecast_url = _get_icecast_stream_url(source_name)

        response_payload: Dict[str, Any] = {
            "success": True,
            "source_name": source_name,
            "created": bool(result.get("created")),
            "updated": bool(result.get("updated")),
            "removed": bool(result.get("removed")),
            "started": bool(result.get("started")),
            "icecast_started": bool(result.get("icecast_started")),
            "status": status_value,
            "icecast_url": icecast_url,
            "metadata": metadata,
            "receiver_enabled": bool(receiver.enabled),
            "audio_output": bool(receiver.audio_output),
        }

        if start_now:
            response_payload["message"] = (
                "Audio monitor started successfully." if response_payload["started"]
                else "Audio monitor start requested."
            )

        return jsonify(response_payload)


__all__ = ["register"]
