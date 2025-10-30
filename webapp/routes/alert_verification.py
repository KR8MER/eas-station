"""Routes powering the alert verification and analytics dashboard."""

from __future__ import annotations

import os
import tempfile
from typing import List, Optional

from flask import Flask, Response, render_template, request
from werkzeug.utils import secure_filename

from app_core.eas_storage import (
    build_alert_delivery_trends,
    collect_alert_delivery_records,
    load_recent_audio_decodes,
    record_audio_decode_result,
)
from app_utils import format_local_datetime
from app_utils.export import generate_csv
from app_utils.eas_decode import AudioDecodeError, SAMEAudioDecodeResult, decode_same_audio


def register(app: Flask, logger) -> None:
    """Register alert verification routes on the Flask application."""

    route_logger = logger.getChild("alert_verification")

    def _resolve_window_days() -> int:
        value = request.values.get("days", type=int)
        if value is None:
            return 30
        return max(1, min(int(value), 365))

    def _serialize_csv_rows(records):
        for record in records:
            targets = ", ".join(
                f"{target['target']} ({target['status']})"
                for target in record.get("target_details", [])
            )
            issues = "; ".join(record.get("issues") or [])
            yield {
                "cap_identifier": record.get("identifier") or "",
                "event": record.get("event") or "",
                "sent_utc": (record.get("sent").isoformat() if record.get("sent") else ""),
                "source": record.get("source") or "",
                "delivery_status": record.get("delivery_status") or "unknown",
                "average_latency_seconds": (
                    round(record["average_latency_seconds"], 2)
                    if isinstance(record.get("average_latency_seconds"), (int, float))
                    else ""
                ),
                "targets": targets,
                "issues": issues,
            }

    def _handle_audio_decode():
        if "audio_file" not in request.files:
            return None, ["Please choose a WAV or MP3 file containing SAME bursts."], None

        upload = request.files["audio_file"]
        if not upload or not upload.filename:
            return None, ["Please choose a WAV or MP3 file containing SAME bursts."], None

        filename = secure_filename(upload.filename)
        extension = os.path.splitext(filename.lower())[1]
        if extension not in {".wav", ".mp3"}:
            return None, ["Unsupported file type. Upload a .wav or .mp3 file."], None

        errors: List[str] = []
        decode_result: Optional[SAMEAudioDecodeResult] = None
        stored_record = None

        with tempfile.NamedTemporaryFile(suffix=extension) as temp_file:
            upload.save(temp_file.name)
            try:
                decode_result = decode_same_audio(temp_file.name)
            except AudioDecodeError as exc:
                errors.append(str(exc))
            except Exception as exc:  # pragma: no cover - defensive fallback
                route_logger.error("Unexpected failure decoding SAME audio: %s", exc)
                errors.append("Unable to decode audio payload. See logs for details.")

            if decode_result and request.form.get("store_results") == "on":
                try:
                    stored_record = record_audio_decode_result(
                        filename=filename,
                        content_type=upload.mimetype,
                        decode_payload=decode_result,
                    )
                except Exception as exc:  # pragma: no cover - defensive fallback
                    route_logger.error("Failed to store decoded audio payload: %s", exc)
                    errors.append("Decoded results were generated but could not be stored.")

        return decode_result, errors, stored_record

    @app.route("/admin/alert-verification", methods=["GET", "POST"])
    def alert_verification():
        window_days = _resolve_window_days()
        decode_result = None
        decode_errors: List[str] = []
        stored_decode = None

        if request.method == "POST":
            decode_result, decode_errors, stored_decode = _handle_audio_decode()

        try:
            payload = collect_alert_delivery_records(window_days=window_days)
            trends = build_alert_delivery_trends(
                payload["records"],
                window_start=payload["window_start"],
                window_end=payload["window_end"],
                delay_threshold=payload["delay_threshold_seconds"],
                logger=route_logger,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Failed to assemble alert verification data: %s", exc)
            try:
                fallback_threshold = int(
                    app.config.get("ALERT_VERIFICATION_DELAY_THRESHOLD_SECONDS", 120)
                )
            except (TypeError, ValueError):
                fallback_threshold = 120

            payload = {
                "window_start": None,
                "window_end": None,
                "generated_at": None,
                "delay_threshold_seconds": fallback_threshold,
                "summary": {
                    "total": 0,
                    "delivered": 0,
                    "partial": 0,
                    "pending": 0,
                    "missing": 0,
                    "awaiting_playout": 0,
                    "average_latency_seconds": None,
                },
                "records": [],
                "orphans": [],
            }
            trends = {
                "generated_at": None,
                "delay_threshold_seconds": payload["delay_threshold_seconds"],
                "originators": [],
                "stations": [],
            }

        recent_decodes = load_recent_audio_decodes(limit=5)

        return render_template(
            "eas/alert_verification.html",
            window_days=window_days,
            payload=payload,
            trends=trends,
            format_local_datetime=format_local_datetime,
            decode_result=decode_result,
            decode_errors=decode_errors,
            stored_decode=stored_decode,
            recent_decodes=recent_decodes,
        )

    @app.route("/admin/alert-verification/export.csv")
    def alert_verification_export():
        window_days = _resolve_window_days()

        try:
            payload = collect_alert_delivery_records(window_days=window_days)
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Failed to generate alert verification export: %s", exc)
            return Response(
                "Unable to generate alert verification export. See logs for details.",
                status=500,
                mimetype="text/plain",
            )

        rows = list(_serialize_csv_rows(payload["records"]))
        csv_payload = generate_csv(
            rows,
            fieldnames=[
                "cap_identifier",
                "event",
                "sent_utc",
                "source",
                "delivery_status",
                "average_latency_seconds",
                "targets",
                "issues",
            ],
        )

        response = Response(csv_payload, mimetype="text/csv")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=alert_verification_{window_days}d.csv"
        )
        return response


__all__ = ["register"]
