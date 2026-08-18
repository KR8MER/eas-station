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

"""IQ capture: request one from the SDR service, then download it."""

import io
import json
import os
import time
import uuid
from typing import Any

from flask import Flask, jsonify, request, send_file

from app_core.models import RadioReceiver
from app_core.radio import (
    ensure_radio_tables,
)
from app_core.auth.roles import require_permission
from app_core.radio.decimation import effective_sample_rate

from . import deps


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    @app.route(
        "/api/radio/diagnostics/capture/<int:receiver_id>", methods=["POST"]
    )
    @require_permission('receivers.configure')
    def api_radio_diagnostics_capture(receiver_id: int) -> Any:
        """Trigger an IQ capture-to-disk for a receiver.

        Sends a ``capture_iq`` command to sdr-service, which writes a
        complex64 ``.npy`` file under ``RADIO_CAPTURE_DIR``. The path is
        stashed in Redis keyed by a new ``capture_id`` so the user can
        download it via GET .../capture/<capture_id>/download.

        Request body (optional JSON):
            duration_sec: float, capture duration in seconds. Bounded by
                ``RADIO_CAPTURE_MAX_DURATION_SEC`` and the SDR ring buffer.
        """
        ensure_radio_tables(route_logger)
        receiver_record = RadioReceiver.query.get_or_404(receiver_id)

        payload = request.get_json(silent=True) or {}
        try:
            duration_sec = float(
                payload.get("duration_sec", deps.RADIO_CAPTURE_DEFAULT_DURATION_SEC)
            )
        except (TypeError, ValueError):
            duration_sec = deps.RADIO_CAPTURE_DEFAULT_DURATION_SEC
        duration_sec = max(0.05, min(duration_sec, deps.RADIO_CAPTURE_MAX_DURATION_SEC))

        # Captures are tapped from the ring buffer, i.e. *after* early
        # decimation, so the requested duration must be converted at the
        # effective rate. Using the configured hardware rate here asked
        # for decim-factor times too many samples -- an Airspy at 2.5 MHz
        # (decim 10) turned a 5 s request into a 50 s capture that always
        # blew the wait budget below.
        effective_rate = effective_sample_rate(receiver_record.sample_rate) or 250_000
        num_samples = int(duration_sec * effective_rate)

        try:
            command_id = str(uuid.uuid4())
            redis_client = deps.get_redis_client()

            command = {
                "action": "capture_iq",
                "receiver_id": receiver_record.identifier,
                "command_id": command_id,
                "num_samples": num_samples,
            }

            route_logger.info(
                "Sending capture_iq to sdr-service for receiver %s "
                "(num_samples=%d, command_id=%s)",
                receiver_record.identifier, num_samples, command_id,
            )
            redis_client.rpush("sdr:commands", json.dumps(command))

            # Wall-clock wait: the SDR service taps the publisher thread
            # to assemble exactly ``num_samples`` of complex64, which
            # takes real time. Add slack for settling and the disk write.
            timeout = duration_sec + deps.RADIO_CAPTURE_WAIT_SLACK_SEC
            start_time = time.time()
            result = None
            while time.time() - start_time < timeout:
                result_json = redis_client.get(
                    f"sdr:command_result:{command_id}"
                )
                if result_json:
                    result = json.loads(result_json)
                    break
                time.sleep(0.1)

            if not result:
                return jsonify({
                    "error": "Timeout waiting for sdr-service to write capture",
                    "hint": (
                        "Check if sdr-service is running: "
                        "sudo systemctl status eas-station-sdr.service"
                    ),
                }), 504

            if not result.get("success"):
                return jsonify({
                    "error": "Capture failed",
                    "hint": result.get("error", "Unknown error"),
                }), 503

            capture_path = result.get("path")
            if not capture_path or not deps._is_path_within(
                capture_path, deps.RADIO_CAPTURE_DIR
            ):
                # Defence-in-depth: refuse to register a capture whose
                # on-disk path falls outside the allow-list directory.
                route_logger.error(
                    "Rejecting capture with out-of-tree path: %s", capture_path
                )
                return jsonify({
                    "error": "Capture stored at unexpected location",
                }), 500

            capture_id = uuid.uuid4().hex
            metadata = {
                "path": capture_path,
                "filename": result.get("filename"),
                "num_samples": result.get("num_samples"),
                "sample_rate": result.get("sample_rate"),
                "frequency_hz": result.get("frequency_hz"),
                "size_bytes": result.get("size_bytes"),
                "dtype": result.get("dtype", "complex64"),
                "receiver_id": receiver_record.id,
                "receiver_identifier": receiver_record.identifier,
                "created_at": time.time(),
            }
            redis_client.setex(
                f"{deps.RADIO_CAPTURE_REDIS_PREFIX}{capture_id}",
                deps.RADIO_CAPTURE_REDIS_TTL_SEC,
                json.dumps(metadata),
            )

            deps._log_radio_event(
                "INFO",
                f"IQ capture written for {receiver_record.identifier}: "
                f"{metadata['num_samples']} samples, "
                f"{metadata['size_bytes']} bytes",
                module_suffix="diagnostics",
                details={
                    "receiver_id": receiver_record.id,
                    "capture_id": capture_id,
                    "filename": metadata["filename"],
                },
            )

            return jsonify({
                "capture_id": capture_id,
                "filename": metadata["filename"],
                "num_samples": metadata["num_samples"],
                "sample_rate": metadata["sample_rate"],
                "frequency_hz": metadata["frequency_hz"],
                "size_bytes": metadata["size_bytes"],
                "dtype": metadata["dtype"],
                "expires_in_sec": deps.RADIO_CAPTURE_REDIS_TTL_SEC,
                "download_url": (
                    f"/api/radio/diagnostics/capture/{capture_id}/download"
                ),
            })

        except Exception as exc:
            route_logger.error(
                "Failed to capture IQ for receiver %s: %s",
                receiver_id, exc, exc_info=True,
            )
            return jsonify({
                "error": "Failed to capture IQ samples",
            }), 500

    @app.route(
        "/api/radio/diagnostics/capture/<capture_id>/download", methods=["GET"]
    )
    def api_radio_diagnostics_capture_download(capture_id: str) -> Any:
        """Stream a previously-written IQ capture as a .npy attachment.

        The capture file is deleted after a successful download so the
        capture directory doesn't accumulate stale files on shared hosts.
        """
        # Reject anything that's not a hex UUID — capture IDs we mint are
        # ``uuid.uuid4().hex`` (32 hex chars). This blocks path traversal
        # via the URL segment before we even hit Redis.
        if not capture_id or len(capture_id) > 64 or not all(
            c in "0123456789abcdef" for c in capture_id
        ):
            return jsonify({"error": "Invalid capture id"}), 400

        try:
            redis_client = deps.get_redis_client()
            raw = redis_client.get(f"{deps.RADIO_CAPTURE_REDIS_PREFIX}{capture_id}")
            if not raw:
                return jsonify({
                    "error": "Capture not found or expired",
                }), 404

            metadata = json.loads(raw)
            capture_path = metadata.get("path")
            if not capture_path or not deps._is_path_within(
                capture_path, deps.RADIO_CAPTURE_DIR
            ):
                # Path-traversal guard: the on-disk path must live inside
                # the allow-list directory. Defends against a tampered
                # Redis value.
                route_logger.error(
                    "Refusing to serve capture %s with out-of-tree path: %s",
                    capture_id, capture_path,
                )
                return jsonify({"error": "Capture path not allowed"}), 400

            if not os.path.isfile(capture_path):
                redis_client.delete(
                    f"{deps.RADIO_CAPTURE_REDIS_PREFIX}{capture_id}"
                )
                return jsonify({
                    "error": "Capture file no longer exists",
                }), 410

            filename = metadata.get("filename") or os.path.basename(
                capture_path
            )

            # Read the file into memory and remove it immediately, then
            # serve from BytesIO. Capture files are bounded by
            # RADIO_CAPTURE_MAX_SAMPLES (~64 MB) so in-memory streaming is
            # acceptable, and it avoids relying on response.call_on_close
            # firing at the right moment to clean up.
            with open(capture_path, "rb") as fh:
                file_bytes = fh.read()
            try:
                os.remove(capture_path)
            except OSError as cleanup_exc:
                route_logger.debug(
                    "Failed to remove capture %s after read: %s",
                    capture_path, cleanup_exc,
                )
            redis_client.delete(
                f"{deps.RADIO_CAPTURE_REDIS_PREFIX}{capture_id}"
            )

            return send_file(
                io.BytesIO(file_bytes),
                mimetype="application/octet-stream",
                as_attachment=True,
                download_name=filename,
            )

        except Exception as exc:
            route_logger.error(
                "Failed to download capture %s: %s",
                capture_id, exc, exc_info=True,
            )
            return jsonify({"error": "Failed to download capture"}), 500


__all__ = ["register"]
