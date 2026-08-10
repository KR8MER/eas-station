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

"""``POST /admin/alert-verification/operations`` — start an async run."""

import os
import tempfile
import uuid
import threading
from typing import Dict, List, Optional

from flask import Flask, jsonify, request, url_for
from werkzeug.utils import secure_filename

from app_core.auth.decorators import require_auth, require_role
from app_utils.eas_decode import SAMEAudioDecodeResult

from .decode_serialization import _serialize_decode_result
from .helpers import _resolve_window_days
from .progress import OperationResultStore, ProgressTracker
from .temp_audio import _process_temp_audio_file


def register(app: Flask, logger):
    """Attach this module's routes, recreating register's closure.

    ``route_logger`` is rebuilt here rather than passed in, so each
    handler closes over exactly what it closed over in the single-file
    module.
    """
    route_logger = logger.getChild('alert_verification')

    def _async_decode_worker(
        progress_id: str,
        temp_path: str,
        filename: str,
        mimetype: str,
        store_results: bool,
    ) -> None:
        progress = ProgressTracker(progress_id)
        progress.update("init", 0, 100, "Starting audio processing...")

        with app.app_context():
            decode_result: Optional[SAMEAudioDecodeResult] = None
            errors: List[str] = []
            stored_record = None

            try:
                decode_result, errors, stored_record = _process_temp_audio_file(
                    temp_path,
                    filename,
                    mimetype,
                    store_results,
                    route_logger,
                    progress=progress,
                )
            except Exception as exc:  # pragma: no cover - defensive fallback
                route_logger.error("Async alert verification failed: %s", exc, exc_info=True)
                errors = ["Unable to decode audio payload. See logs for details."]
                progress.error(errors[0])
            else:
                if errors and not decode_result:
                    progress.error(errors[0])
                else:
                    progress.complete("Processing complete")

            result_payload: Dict[str, object] = {"decode_errors": errors}
            if decode_result:
                result_payload["decode_result"] = _serialize_decode_result(decode_result)
            if stored_record:
                result_payload["stored_decode"] = {
                    "id": getattr(stored_record, "id", None),
                    "original_filename": getattr(stored_record, "original_filename", None),
                }

            OperationResultStore.save(progress_id, result_payload)

        try:
            os.unlink(temp_path)
        except OSError as exc:  # pragma: no cover - defensive cleanup
            route_logger.debug("Failed to remove temp file %s: %s", temp_path, exc)

    @app.route("/admin/alert-verification/operations", methods=["POST"])
    @require_auth
    @require_role("Admin", "Operator")
    def start_alert_verification_operation():
        window_days = _resolve_window_days()

        # Periodic cleanup of old progress files
        try:
            ProgressTracker.cleanup_old(max_age_seconds=3600)
        except Exception:
            pass  # Don't fail operation if cleanup fails

        if "audio_file" not in request.files:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Please choose a WAV or MP3 file containing SAME bursts.",
                    }
                ),
                400,
            )

        upload = request.files["audio_file"]
        if not upload or not upload.filename:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Please choose a WAV or MP3 file containing SAME bursts.",
                    }
                ),
                400,
            )

        progress_id = request.form.get("progress_id") or str(uuid.uuid4())
        filename = secure_filename(upload.filename)
        extension = os.path.splitext(filename.lower())[1]
        if extension not in {".wav", ".mp3"}:
            ProgressTracker(progress_id).error("Unsupported file type")
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Unsupported file type. Upload a .wav or .mp3 file.",
                    }
                ),
                400,
            )

        store_results = request.form.get("store_results") == "on"
        mimetype = upload.mimetype or "application/octet-stream"

        progress = ProgressTracker(progress_id)
        progress.update("upload", 1, 4, "Validating audio file...")

        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temp_file:
            upload.save(temp_file.name)
            temp_path = temp_file.name

        progress.update("upload", 2, 4, "Uploading and preparing audio file...")

        thread = threading.Thread(
            target=_async_decode_worker,
            args=(progress_id, temp_path, filename, mimetype, store_results),
            daemon=True,
        )

        try:
            thread.start()
        except RuntimeError as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Failed to launch async alert verification: %s", exc)
            progress.error("Unable to start audio processing")
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Unable to start audio processing. Please try again.",
                    }
                ),
                500,
            )

        redirect_url = url_for(
            "alert_verification",
            days=window_days,
            result_id=progress_id,
        )

        return (
            jsonify(
                {
                    "status": "accepted",
                    "progress_id": progress_id,
                    "redirect_url": redirect_url,
                }
            ),
            202,
        )
