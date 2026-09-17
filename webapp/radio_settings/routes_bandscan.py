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

"""Full FM-band sweep ("Bandscan") -- start/progress/cancel.

A deliberate, disruptive action (same risk tier as
routes_receiver_control.py's restart): the sweep retunes the live
receiver away from its assigned frequency for the whole scan, so that
receiver is not monitoring for real alerts until it finishes. Unlike
restart (seconds), a full sweep takes minutes, so this does NOT reuse
restart's block-the-HTTP-request-and-poll pattern for the sweep itself --
`start` only waits long enough to confirm the sdr-service actually picked
up the command and spawned its background thread (see
sdr_hardware_service.py's `_run_bandscan_sweep`), then returns. The
frontend polls `progress` separately on its own slower cadence appropriate
to the sweep's ~1 channel/second-ish rate.
"""

import json
import time
import uuid
from typing import Any

from flask import Flask, jsonify, request

from app_core.auth.roles import require_permission
from app_core.config.redis_config import RedisChannels
from app_core.models import RadioReceiver
from app_core.radio import ensure_radio_tables

from . import deps

# Mirrors sdr_hardware_service.py's BANDSCAN_START_HZ/BANDSCAN_END_HZ.
# Duplicated rather than imported -- that module is the SDR hardware
# service's own entrypoint (SoapySDR-adjacent imports the webapp process
# has no business pulling in), the same reason the frontend's own copy of
# these two numbers (BANDSCAN_START_MHZ/BANDSCAN_END_MHZ in
# radio_diagnostics.html) is independent too.
_BANDSCAN_START_HZ = 87_500_000
_BANDSCAN_END_HZ = 108_000_000


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""

    @app.route("/api/radio/bandscan/<int:receiver_id>/start", methods=["POST"])
    @require_permission('receivers.configure')
    def api_bandscan_start(receiver_id: int) -> Any:
        """Start a full FM-band sweep (87.5-108.0 MHz, 100 kHz steps) on a receiver.

        Retunes the receiver across the whole band, measuring signal level
        at each step, then automatically retunes back to its assigned
        frequency when the scan finishes, is cancelled, or errors. The
        receiver does not monitor for real alerts for the scan's duration
        (typically 2-4 minutes) -- this is a deliberate, disruptive action,
        the same risk tier as the existing Restart Receiver button.

        Returns:
            200 with {started: true} once the sdr-service confirms it
            spawned the sweep. 409 if a scan is already running for this
            receiver. 504 if the sdr-service didn't acknowledge in time.
        """
        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        try:
            command_id = str(uuid.uuid4())
            redis_client = deps.get_redis_client()

            command = {
                "action": "bandscan_sweep",
                "receiver_id": receiver.identifier,
                "command_id": command_id,
            }
            route_logger.info(
                "Sending bandscan_sweep to sdr-service for receiver %s (command_id=%s)",
                receiver.identifier, command_id,
            )
            redis_client.rpush("sdr:commands", json.dumps(command))

            # Only waiting for the "did it start" ack, not the sweep
            # itself -- a few seconds is plenty for the sdr-service to
            # pop the command and spawn the background thread.
            timeout = 5.0
            start_time = time.time()
            result = None
            while time.time() - start_time < timeout:
                result_json = redis_client.get(f"sdr:command_result:{command_id}")
                if result_json:
                    result = json.loads(result_json)
                    break
                time.sleep(0.1)

            if not result:
                return jsonify({
                    "error": "Timeout waiting for sdr-service to acknowledge the bandscan request",
                    "hint": "Check if sdr-service is running: sudo systemctl status eas-station-sdr.service",
                }), 504

            if not result.get("success"):
                error = result.get("error", "Unknown error")
                status_code = 409 if "already running" in error else 400
                return jsonify({"error": error}), status_code

            return jsonify({"started": True})
        except Exception as exc:
            route_logger.error(
                "Failed to start bandscan for receiver %s: %s", receiver_id, exc, exc_info=True,
            )
            deps._log_radio_event(
                "ERROR",
                f"Failed to start bandscan: {exc}",
                module_suffix="bandscan",
                details={"receiver_id": receiver_id, "error": str(exc)},
            )
            return jsonify({"error": "Failed to start bandscan"}), 500

    @app.route("/api/radio/bandscan/<int:receiver_id>/progress", methods=["GET"])
    def api_bandscan_progress(receiver_id: int) -> Any:
        """Return the current (or most recently finished) bandscan's progress.

        Returns:
            200 with {status, start_freq_hz, end_freq_hz, step_hz,
            original_frequency_hz, results, started_at, updated_at}.
            status is "unavailable" (with no other fields but that one)
            if no scan has run recently enough for the progress key to
            still exist.
        """
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        try:
            redis_client = deps.get_redis_client()
            progress_key = f"{RedisChannels.BANDSCAN_PROGRESS_PREFIX}{receiver.identifier}"
            raw = redis_client.get(progress_key)
            if not raw:
                return jsonify({"status": "unavailable"})

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return jsonify(json.loads(raw))
        except Exception as exc:
            route_logger.error(
                "Failed to get bandscan progress for receiver %s: %s", receiver_id, exc, exc_info=True,
            )
            return jsonify({"error": "Failed to get bandscan progress"}), 500

    @app.route("/api/radio/bandscan/<int:receiver_id>/cancel", methods=["POST"])
    @require_permission('receivers.configure')
    def api_bandscan_cancel(receiver_id: int) -> Any:
        """Cancel an in-progress bandscan; the receiver is retuned back to
        its assigned frequency as soon as the sweep thread notices.

        Returns:
            200 with {cancelling: true}. 404 (via the underlying
            sdr-service error) if no scan is currently running.
        """
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        try:
            command_id = str(uuid.uuid4())
            redis_client = deps.get_redis_client()

            command = {
                "action": "bandscan_cancel",
                "receiver_id": receiver.identifier,
                "command_id": command_id,
            }
            redis_client.rpush("sdr:commands", json.dumps(command))

            timeout = 5.0
            start_time = time.time()
            result = None
            while time.time() - start_time < timeout:
                result_json = redis_client.get(f"sdr:command_result:{command_id}")
                if result_json:
                    result = json.loads(result_json)
                    break
                time.sleep(0.1)

            if not result:
                return jsonify({
                    "error": "Timeout waiting for sdr-service to acknowledge cancellation",
                }), 504
            if not result.get("success"):
                return jsonify({"error": result.get("error", "Unknown error")}), 400

            return jsonify({"cancelling": True})
        except Exception as exc:
            route_logger.error(
                "Failed to cancel bandscan for receiver %s: %s", receiver_id, exc, exc_info=True,
            )
            return jsonify({"error": "Failed to cancel bandscan"}), 500

    @app.route("/api/radio/bandscan/<int:receiver_id>/identify/start", methods=["POST"])
    @require_permission('receivers.configure')
    def api_bandscan_identify_start(receiver_id: int) -> Any:
        """Start "Identify Stations": retune to each given peak frequency
        long enough to attempt an RDS PS (station name) decode.

        A second, explicit pass over frequencies a prior Bandscan sweep
        already found interesting -- RDS sync needs real dwell time per
        frequency (~1-2.5s), unlike the sweep's near-instant per-channel
        level measurement, so this can't be folded into the sweep itself.
        Shares the sweep's "receiver not monitoring for real alerts, and
        already-running-scan" guard (see _run_bandscan_identify /
        _state.active_bandscans in sdr_hardware_service.py) and its
        `POST .../cancel` endpoint above -- no separate cancel route.

        Body:
            frequencies_hz (list[number], required): target frequencies in
                Hz, each within the Bandscan band (87.5-108.0 MHz). Usually
                the peak list the frontend already computed and is
                displaying from the receiver's last sweep.

        Returns:
            200 with {started: true} once the sdr-service confirms it
            spawned the pass. 400 if frequencies_hz is missing, empty, or
            contains a value outside the band. 409 if a scan is already
            running for this receiver. 504 if the sdr-service didn't
            acknowledge in time.
        """
        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        payload = request.get_json(silent=True) or {}
        frequencies_hz = payload.get('frequencies_hz')
        if not frequencies_hz or not isinstance(frequencies_hz, list):
            return jsonify({"error": "frequencies_hz (non-empty list) is required"}), 400
        try:
            frequencies_hz = [float(f) for f in frequencies_hz]
        except (TypeError, ValueError):
            return jsonify({"error": "frequencies_hz must be numbers"}), 400
        out_of_band = [
            f for f in frequencies_hz
            if f < _BANDSCAN_START_HZ or f > _BANDSCAN_END_HZ
        ]
        if out_of_band:
            return jsonify({
                "error": f"frequencies_hz must fall within "
                         f"{_BANDSCAN_START_HZ / 1e6:.1f}-{_BANDSCAN_END_HZ / 1e6:.1f} MHz",
            }), 400

        try:
            command_id = str(uuid.uuid4())
            redis_client = deps.get_redis_client()

            command = {
                "action": "bandscan_identify",
                "receiver_id": receiver.identifier,
                "command_id": command_id,
                "target_freqs_hz": frequencies_hz,
            }
            route_logger.info(
                "Sending bandscan_identify to sdr-service for receiver %s "
                "(command_id=%s, %d frequencies)",
                receiver.identifier, command_id, len(frequencies_hz),
            )
            redis_client.rpush("sdr:commands", json.dumps(command))

            timeout = 5.0
            start_time = time.time()
            result = None
            while time.time() - start_time < timeout:
                result_json = redis_client.get(f"sdr:command_result:{command_id}")
                if result_json:
                    result = json.loads(result_json)
                    break
                time.sleep(0.1)

            if not result:
                return jsonify({
                    "error": "Timeout waiting for sdr-service to acknowledge the identify request",
                    "hint": "Check if sdr-service is running: sudo systemctl status eas-station-sdr.service",
                }), 504

            if not result.get("success"):
                error = result.get("error", "Unknown error")
                status_code = 409 if "already running" in error else 400
                return jsonify({"error": error}), status_code

            return jsonify({"started": True})
        except Exception as exc:
            route_logger.error(
                "Failed to start bandscan identify for receiver %s: %s", receiver_id, exc, exc_info=True,
            )
            deps._log_radio_event(
                "ERROR",
                f"Failed to start bandscan identify: {exc}",
                module_suffix="bandscan",
                details={"receiver_id": receiver_id, "error": str(exc)},
            )
            return jsonify({"error": "Failed to start bandscan identify"}), 500

    @app.route("/api/radio/bandscan/<int:receiver_id>/identify/progress", methods=["GET"])
    def api_bandscan_identify_progress(receiver_id: int) -> Any:
        """Return the current (or most recently finished) identify pass's progress.

        Returns:
            200 with {status, target_freqs_hz, results, started_at,
            updated_at}. status is "unavailable" (with no other fields)
            if no identify pass has run recently enough for the key to
            still exist.
        """
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        try:
            redis_client = deps.get_redis_client()
            progress_key = f"{RedisChannels.BANDSCAN_IDENTIFY_PROGRESS_PREFIX}{receiver.identifier}"
            raw = redis_client.get(progress_key)
            if not raw:
                return jsonify({"status": "unavailable"})

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return jsonify(json.loads(raw))
        except Exception as exc:
            route_logger.error(
                "Failed to get bandscan identify progress for receiver %s: %s", receiver_id, exc, exc_info=True,
            )
            return jsonify({"error": "Failed to get bandscan identify progress"}), 500


__all__ = ["register"]
