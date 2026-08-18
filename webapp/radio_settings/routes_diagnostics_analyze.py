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

"""Offline analysis of a capture, and the auto-gain sweep."""

import json
import os
import time
import uuid
from typing import Any

from flask import Flask, jsonify, request

from app_core.extensions import db
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
        "/api/radio/diagnostics/analyze/<int:receiver_id>", methods=["POST"]
    )
    @require_permission('receivers.configure')
    def api_radio_diagnostics_analyze(receiver_id: int) -> Any:
        """Capture a short IQ window and return a full diagnostic report.

        Reuses the existing ``capture_iq`` Redis command flow to obtain
        a short .npz from the SDR service, then runs the analyzers in
        ``app_utils.radio_diagnostics`` against it.  Returns the dict
        produced by ``diagnostic_to_dict`` — the dashboard renders this
        directly into the "Run Diagnostic" results card.

        The capture file is deleted immediately after analysis (same
        single-use semantics as the waterfall endpoint) so the capture
        directory doesn't accumulate stale files.

        Request body (optional JSON):
            duration_sec: float, capture duration in seconds. Default 2.0,
                clamped to [0.5, 10.0].  A 2 s window gives the FFT enough
                resolution to find the 19 kHz pilot and 57 kHz RBDS lobe
                without ballooning the JSON payload.
        """
        try:
            import numpy as np
            # Import the analyzer directly so the diagnostics endpoint
            # works even if the app_utils package __init__ pulls in
            # optional dependencies that aren't installed on this host.
            from app_utils.radio_diagnostics import (
                analyze_capture,
                diagnostic_to_dict,
            )
        except ImportError as exc:
            # Log the underlying ImportError details server-side but don't
            # echo them back — the exception string can contain filesystem
            # paths and module-search information that we don't want to
            # expose on the operator-facing API.
            route_logger.warning(
                "Diagnostic analyzer unavailable on this host: %s", exc,
            )
            return jsonify({
                "error": "Diagnostic analyzer requires numpy and scipy on the web host",
            }), 503

        ensure_radio_tables(route_logger)
        receiver_record = RadioReceiver.query.get_or_404(receiver_id)

        payload = request.get_json(silent=True) or {}
        try:
            duration_sec = float(payload.get("duration_sec", 2.0))
        except (TypeError, ValueError):
            duration_sec = 2.0
        # Bound the capture: 0.5 s is the floor below which RBDS detection
        # becomes unreliable (need a few RBDS group cycles' worth of data);
        # 10 s caps the JSON payload and the wall-clock wait.
        duration_sec = max(0.5, min(duration_sec, 10.0))

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
                "Sending capture_iq for diagnostic analysis on receiver %s "
                "(num_samples=%d, command_id=%s)",
                receiver_record.identifier, num_samples, command_id,
            )
            redis_client.rpush("sdr:commands", json.dumps(command))

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
                # Same defence-in-depth as the download / waterfall
                # endpoints: refuse to load a capture from outside the
                # allow-list directory.
                route_logger.error(
                    "Refusing diagnostic analysis on out-of-tree capture: %s",
                    capture_path,
                )
                return jsonify({
                    "error": "Capture stored at unexpected location",
                }), 500
            if not os.path.isfile(capture_path):
                return jsonify({
                    "error": "Capture file disappeared before analysis",
                }), 500

            # Load + immediately delete the file.  The analysis result is
            # self-contained JSON; the raw IQ is single-use.
            iq = None
            multiplex = None
            try:
                # The SDR service writes .npz with 'iq' (complex64) and
                # optionally 'multiplex' (float32 FM-demod output).  Fall
                # back to a plain .npy of complex64 IQ for legacy captures.
                if capture_path.endswith(".npz"):
                    with np.load(capture_path, allow_pickle=False) as archive:
                        if "iq" in archive.files:
                            iq = archive["iq"].astype(np.complex64)
                        if "multiplex" in archive.files:
                            multiplex = archive["multiplex"].astype(np.float32)
                else:
                    iq = np.load(capture_path, allow_pickle=False).astype(np.complex64)
            finally:
                try:
                    os.remove(capture_path)
                except OSError as cleanup_exc:
                    route_logger.debug(
                        "Failed to remove diagnostic capture %s: %s",
                        capture_path, cleanup_exc,
                    )

            if iq is None or iq.size == 0:
                return jsonify({
                    "error": "Capture contained no IQ samples",
                }), 500

            sample_rate = int(
                result.get("sample_rate") or effective_rate
            )

            diag = analyze_capture(iq, sample_rate, multiplex=multiplex)
            report = diagnostic_to_dict(diag)
            # Augment with the operator-facing receiver context so the
            # dashboard can show "which receiver / which frequency".
            report["receiver"] = {
                "id": receiver_record.id,
                "identifier": receiver_record.identifier,
                "frequency_hz": result.get("frequency_hz"),
            }

            deps._log_radio_event(
                "INFO",
                f"Diagnostic analysis run on {receiver_record.identifier}: "
                f"{report['summary_verdict']} verdict, "
                f"rbds_suppression_risk={report['rbds_suppression_risk']}",
                module_suffix="diagnostics",
                details={
                    "receiver_id": receiver_record.id,
                    "summary_verdict": report["summary_verdict"],
                    "rbds_suppression_risk": report["rbds_suppression_risk"],
                    "clipping_fraction": report["frontend"]["clipping_fraction"],
                },
            )

            return jsonify(report)

        except Exception as exc:
            route_logger.error(
                "Failed to run diagnostic analysis for receiver %s: %s",
                receiver_id, exc, exc_info=True,
            )
            return jsonify({
                "error": "Failed to run diagnostic analysis",
            }), 500

    @app.route(
        "/api/radio/diagnostics/auto_gain/<int:receiver_id>", methods=["POST"]
    )
    @require_permission('receivers.configure')
    def api_radio_diagnostics_auto_gain(receiver_id: int) -> Any:
        """Run runtime auto-gain calibration for a receiver.

        Sends an ``auto_gain`` command to sdr-service, which sweeps the
        device's gain range, measures IQ headroom for each step, and
        applies the highest setting that stays out of clipping.

        Request body (optional JSON):
            persist: bool, when true the chosen gain is also written
                back to the ``radio_receivers.gain`` column so it
                survives a service restart.
            target_rms_dbfs: float, target IQ RMS level (default -12).
            clipping_threshold: float, max acceptable clipping fraction
                (default 0.01 i.e. 1% of samples at |x| > 0.95).
        """
        ensure_radio_tables(route_logger)
        receiver_record = RadioReceiver.query.get_or_404(receiver_id)

        payload = request.get_json(silent=True) or {}
        persist = bool(payload.get("persist", False))
        try:
            target_rms_dbfs = float(payload.get("target_rms_dbfs", -12.0))
        except (TypeError, ValueError):
            target_rms_dbfs = -12.0
        try:
            clipping_threshold = float(payload.get("clipping_threshold", 0.01))
        except (TypeError, ValueError):
            clipping_threshold = 0.01
        # Keep the sweep bounded - 80 candidates * 0.3s each = ~24s worst case.
        try:
            settle_sec = float(payload.get("settle_sec", 0.2))
        except (TypeError, ValueError):
            settle_sec = 0.2
        try:
            measure_sec = float(payload.get("measure_sec", 0.1))
        except (TypeError, ValueError):
            measure_sec = 0.1

        try:
            command_id = str(uuid.uuid4())
            redis_client = deps.get_redis_client()

            command = {
                "action": "auto_gain",
                "receiver_id": receiver_record.identifier,
                "command_id": command_id,
                "target_rms_dbfs": target_rms_dbfs,
                "clipping_threshold": clipping_threshold,
                "settle_sec": settle_sec,
                "measure_sec": measure_sec,
            }

            route_logger.info(
                "Sending auto_gain to sdr-service for receiver %s "
                "(target=%.1f dBFS, clip<=%.3f, command_id=%s)",
                receiver_record.identifier, target_rms_dbfs,
                clipping_threshold, command_id,
            )
            redis_client.rpush("sdr:commands", json.dumps(command))

            # 80-candidate sweep * (settle + measure + overhead) bounds
            # the worst case at ~90 s; we wait that plus slack for slow
            # devices. Most sweeps complete in <10s.
            timeout = 90.0
            start_time = time.time()
            result = None
            while time.time() - start_time < timeout:
                result_json = redis_client.get(
                    f"sdr:command_result:{command_id}"
                )
                if result_json:
                    result = json.loads(result_json)
                    break
                time.sleep(0.2)

            if not result:
                return jsonify({
                    "error": "Timeout waiting for sdr-service auto-gain result",
                    "hint": (
                        "Check if sdr-service is running: "
                        "sudo systemctl status eas-station-sdr.service"
                    ),
                }), 504

            if not result.get("success"):
                return jsonify({
                    "error": "Auto-gain failed",
                    "hint": result.get("error", "Unknown error"),
                    "measurements": result.get("measurements", []),
                }), 503

            selected_gain = result.get("selected_gain_db")
            previous_gain = result.get("previous_gain_db")
            persisted = False
            if persist and selected_gain is not None:
                try:
                    receiver_record.gain = float(selected_gain)
                    db.session.commit()
                    persisted = True
                except Exception as exc:
                    db.session.rollback()
                    route_logger.error(
                        "Failed to persist auto-gain value %.1f for receiver %s: %s",
                        selected_gain, receiver_id, exc, exc_info=True,
                    )

            deps._log_radio_event(
                "INFO",
                (
                    f"Auto-gain set {receiver_record.identifier} to "
                    f"{selected_gain} dB "
                    f"(was {previous_gain}, decision={result.get('decision')}, "
                    f"persisted={persisted})"
                ),
                module_suffix="diagnostics",
                details={
                    "receiver_id": receiver_record.id,
                    "selected_gain_db": selected_gain,
                    "previous_gain_db": previous_gain,
                    "decision": result.get("decision"),
                    "persisted": persisted,
                },
            )

            return jsonify({
                "success": True,
                "selected_gain_db": selected_gain,
                "previous_gain_db": previous_gain,
                "applied": bool(result.get("applied")),
                "persisted": persisted,
                "decision": result.get("decision"),
                "target_rms_dbfs": result.get("target_rms_dbfs"),
                "clipping_threshold": result.get("clipping_threshold"),
                "selected_measurement": result.get("selected_measurement"),
                "measurements": result.get("measurements", []),
            })

        except Exception as exc:
            route_logger.error(
                "Failed to run auto-gain for receiver %s: %s",
                receiver_id, exc, exc_info=True,
            )
            return jsonify({"error": "Auto-gain request failed"}), 500


__all__ = ["register"]
