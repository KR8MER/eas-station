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

"""``/admin/alert-verification`` — the verification dashboard."""

import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

from flask import Flask, render_template, request
from werkzeug.utils import secure_filename

from app_core.auth.decorators import require_auth, require_role
from app_core.eas_storage import (
    build_alert_delivery_trends,
    collect_alert_delivery_records,
    load_recent_audio_decodes,
)
import base64
from app_utils import format_local_datetime, utc_now
from app_utils.eas_decode import SAMEAudioDecodeResult

from .decode_serialization import _deserialize_decode_result
from .helpers import _load_configured_fips, _resolve_window_days
from .progress import OperationResultStore, ProgressTracker
from .samples import DEFAULT_SAMPLE_FILES
from .temp_audio import _process_temp_audio_file


def register(app: Flask, logger):
    """Attach this module's routes, recreating register's closure.

    ``route_logger`` and ``repo_root`` are rebuilt here rather than passed in, so each
    handler closes over exactly what it closed over in the single-file
    module.
    """
    route_logger = logger.getChild('alert_verification')
    repo_root = Path(app.root_path).resolve()

    def _describe_bundled_samples() -> List[dict]:
        items: List[dict] = []
        for rel_path in DEFAULT_SAMPLE_FILES:
            absolute = (repo_root / rel_path).resolve()
            exists = absolute.exists()
            size_bytes = absolute.stat().st_size if exists else None
            items.append(
                {
                    "name": rel_path.name,
                    "relative_path": str(rel_path),
                    "exists": exists,
                    "size_bytes": size_bytes,
                }
            )
        return items

    def _handle_audio_decode(progress: Optional[ProgressTracker] = None):
        if "audio_file" not in request.files:
            return None, ["Please choose a WAV or MP3 file containing SAME bursts."], None

        upload = request.files["audio_file"]
        if not upload or not upload.filename:
            return None, ["Please choose a WAV or MP3 file containing SAME bursts."], None

        if progress:
            progress.update("upload", 1, 4, "Validating audio file...")

        filename = secure_filename(upload.filename)
        extension = os.path.splitext(filename.lower())[1]
        if extension not in {".wav", ".mp3"}:
            if progress:
                progress.error("Unsupported file type")
            return None, ["Unsupported file type. Upload a .wav or .mp3 file."], None

        store_results = request.form.get("store_results") == "on"

        if progress:
            progress.update("upload", 2, 4, "Uploading and preparing audio file...")

        decode_result: Optional[SAMEAudioDecodeResult] = None
        errors: List[str] = []
        stored_record = None

        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temp_file:
            upload.save(temp_file.name)
            temp_path = temp_file.name

        try:
            decode_result, errors, stored_record = _process_temp_audio_file(
                temp_path,
                filename,
                upload.mimetype or "application/octet-stream",
                store_results,
                route_logger,
                progress=progress,
            )
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except OSError as exc:
                route_logger.debug("Failed to clean up temp file %s: %s", temp_path, exc)

        return decode_result, errors, stored_record

    @app.route("/admin/alert-verification", methods=["GET", "POST"])
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def alert_verification():
        window_days = _resolve_window_days()
        decode_result = None
        decode_errors: List[str] = []
        stored_decode = None
        progress_id = None

        # Clean up old progress data (older than 1 hour)
        ProgressTracker.cleanup_old(max_age_seconds=3600)
        OperationResultStore.cleanup_old(max_age_seconds=3600)

        result_id = request.args.get("result_id")
        if result_id:
            stored_payload = OperationResultStore.load(result_id)
            if stored_payload:
                decode_errors = stored_payload.get("decode_errors") or []
                serialized_result = stored_payload.get("decode_result")
                if serialized_result:
                    decode_result = _deserialize_decode_result(serialized_result)
                stored_info = stored_payload.get("stored_decode")
                if stored_info:
                    stored_decode = SimpleNamespace(**stored_info)
                OperationResultStore.clear(result_id)
                ProgressTracker.clear(result_id)
                progress_id = result_id

        if request.method == "POST":
            # Generate a unique progress ID for this operation
            progress_id = request.form.get("progress_id") or str(uuid.uuid4())
            progress = ProgressTracker(progress_id)

            route_logger.info(f"Starting audio decode with progress_id: {progress_id}")

            # Initialize progress
            progress.update("init", 0, 100, "Starting audio processing...")

            # Handle audio decode with progress tracking
            decode_result, decode_errors, stored_decode = _handle_audio_decode(progress=progress)

        decode_segment_urls: Dict[str, str] = {}
        if decode_result and getattr(decode_result, "segments", None):
            for key, segment in decode_result.segments.items():
                wav_bytes = getattr(segment, "wav_bytes", None)
                if not wav_bytes:
                    continue
                try:
                    encoded = base64.b64encode(wav_bytes).decode("ascii")
                except (TypeError, ValueError):
                    continue
                normalized = str(key).lower()
                decode_segment_urls[normalized] = f"data:audio/wav;base64,{encoded}"

        # Track progress for data loading operations
        if request.method == "POST" and progress_id:
            progress = ProgressTracker(progress_id)
            progress.update("data", 1, 3, "Loading alert delivery records...")

        try:
            payload = collect_alert_delivery_records(window_days=window_days)

            if request.method == "POST" and progress_id:
                progress = ProgressTracker(progress_id)
                progress.update("data", 2, 3, "Calculating delivery trends...")

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

        if request.method == "POST" and progress_id:
            progress = ProgressTracker(progress_id)
            progress.update("data", 3, 3, "Loading recent decodes...")

        recent_decodes = load_recent_audio_decodes(limit=5)

        bundled_samples = _describe_bundled_samples()
        configured_fips = _load_configured_fips([])
        alert_self_test_context = {
            "configured_fips": configured_fips,
            "default_cooldown": 30.0,
            "default_samples": bundled_samples,
            "generated_at": utc_now().isoformat(),
        }

        # Mark progress as complete
        if request.method == "POST" and progress_id:
            progress = ProgressTracker(progress_id)
            progress.complete("Processing complete")
            route_logger.info(f"Completed audio decode with progress_id: {progress_id}")

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
            decode_segment_urls=decode_segment_urls,
            progress_id=progress_id,
            self_test_configured_fips=configured_fips,
            self_test_samples=bundled_samples,
            alert_self_test_context=alert_self_test_context,
        )
