"""Routes powering the alert verification and analytics dashboard."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Dict, List, Optional

from flask import Flask, Response, abort, render_template, request, send_file, session, jsonify
from werkzeug.utils import secure_filename
import time
import uuid
import threading

from app_core.eas_storage import (
    build_alert_delivery_trends,
    collect_alert_delivery_records,
    load_recent_audio_decodes,
    record_audio_decode_result,
)
from app_core.models import EASDecodedAudio
import base64
import io
import wave
import struct
import numpy as np
from app_utils import format_local_datetime
from app_utils.export import generate_csv
from app_utils.eas_decode import AudioDecodeError, SAMEAudioDecodeResult, decode_same_audio
from app_utils.eas_detection import detect_eas_from_file


# Progress tracking infrastructure
# Persist to the filesystem so multiple workers can share state
_progress_lock = threading.Lock()
_progress_dir = os.path.join(tempfile.gettempdir(), "alert_verification_progress")
os.makedirs(_progress_dir, exist_ok=True)


def _sanitize_operation_id(operation_id: str) -> str:
    """Return a filesystem-safe operation identifier."""

    return "".join(ch for ch in operation_id if ch.isalnum() or ch in {"-", "_"})


def _progress_path(operation_id: str) -> str:
    """Resolve the storage path for a progress payload."""

    safe_id = _sanitize_operation_id(operation_id)
    return os.path.join(_progress_dir, f"{safe_id}.json")

class ProgressTracker:
    """Track progress of long-running operations using a shared file store."""

    def __init__(self, operation_id: str):
        self.operation_id = operation_id

    def _write_payload(self, payload: Dict) -> None:
        """Persist a progress payload to disk atomically."""

        payload = dict(payload)
        payload["timestamp"] = time.time()
        target_path = _progress_path(self.operation_id)
        temp_path = f"{target_path}.{uuid.uuid4().hex}.tmp"

        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temp_path, target_path)

    def update(self, step: str, current: int, total: int, message: str = ""):
        """Update progress for the current operation."""
        progress_data = {
            "step": step,
            "current": current,
            "total": total,
            "message": message,
            "percent": int((current / total * 100)) if total > 0 else 0,
        }
        with _progress_lock:
            self._write_payload(progress_data)

    def complete(self, message: str = "Complete"):
        """Mark operation as complete."""
        with _progress_lock:
            self._write_payload({
                "step": "complete",
                "current": 100,
                "total": 100,
                "message": message,
                "percent": 100,
            })

    def error(self, message: str):
        """Mark operation as failed."""
        with _progress_lock:
            self._write_payload({
                "step": "error",
                "current": 0,
                "total": 100,
                "message": message,
                "percent": 0,
            })

    @staticmethod
    def get(operation_id: str) -> Optional[Dict]:
        """Get progress data for an operation."""
        with _progress_lock:
            path = _progress_path(operation_id)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except FileNotFoundError:
                return None
            except (OSError, json.JSONDecodeError):  # pragma: no cover - defensive
                return None

    @staticmethod
    def clear(operation_id: str):
        """Clear progress data for an operation."""
        with _progress_lock:
            path = _progress_path(operation_id)
            try:
                os.remove(path)
            except FileNotFoundError:
                return
            except OSError:  # pragma: no cover - defensive
                return

    @staticmethod
    def cleanup_old(max_age_seconds: int = 3600):
        """Clean up progress data older than max_age_seconds."""
        current_time = time.time()
        with _progress_lock:
            try:
                for filename in os.listdir(_progress_dir):
                    if not filename.endswith(".json"):
                        continue
                    path = os.path.join(_progress_dir, filename)
                    try:
                        modified = os.path.getmtime(path)
                    except OSError:
                        continue
                    if current_time - modified > max_age_seconds:
                        try:
                            os.remove(path)
                        except OSError:
                            continue
            except OSError:  # pragma: no cover - defensive
                return


def _extract_audio_segment_wav(audio_path: str, start_sample: int, end_sample: int, sample_rate: int) -> bytes:
    """Extract a segment of audio and return as WAV bytes.

    Supports both WAV and MP3 files.
    """
    file_ext = os.path.splitext(audio_path)[1].lower()

    if file_ext == '.mp3':
        # Handle MP3 files using pydub
        try:
            from pydub import AudioSegment

            # Load MP3 file
            audio = AudioSegment.from_mp3(audio_path)

            # Convert to mono if needed
            if audio.channels > 1:
                audio = audio.set_channels(1)

            # Ensure correct sample rate
            if audio.frame_rate != sample_rate:
                audio = audio.set_frame_rate(sample_rate)

            # Calculate time positions in milliseconds
            start_ms = int((start_sample / sample_rate) * 1000)
            end_ms = int((end_sample / sample_rate) * 1000)

            # Extract segment
            segment = audio[start_ms:end_ms]

            # Export as WAV bytes
            buffer = io.BytesIO()
            segment.export(buffer, format="wav")
            return buffer.getvalue()

        except ImportError:
            raise AudioDecodeError(
                "pydub is required for MP3 file support. Install with: pip install pydub"
            )
    else:
        # Handle WAV files directly
        with wave.open(audio_path, 'rb') as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()

            # Read the specific segment
            wf.setpos(start_sample)
            frames = wf.readframes(end_sample - start_sample)

            # Create WAV file in memory
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wav_out:
                wav_out.setnchannels(n_channels)
                wav_out.setsampwidth(sampwidth)
                wav_out.setframerate(sample_rate)
                wav_out.writeframes(frames)

            return buffer.getvalue()


def _detect_comprehensive_eas_segments(audio_path: str, route_logger, progress: Optional[ProgressTracker] = None):
    """
    Perform comprehensive EAS detection and return properly separated segments.

    Returns a dict compatible with SAMEAudioDecodeResult format but with additional segments:
    - header: SAME header bursts
    - attention_tone: EBS two-tone or NWS 1050 Hz
    - narration: Voice narration
    - eom: End-of-Message marker
    - buffer: Lead-in/lead-out audio
    """
    try:
        # Step 1: Run comprehensive detection
        if progress:
            progress.update("decode", 1, 6, "Detecting SAME headers and audio segments...")

        detection_result = detect_eas_from_file(
            audio_path,
            detect_tones=True,
            detect_narration=True
        )

        route_logger.info(f"Comprehensive detection: SAME={detection_result.same_detected}, "
                         f"EBS={detection_result.has_ebs_tone}, NWS={detection_result.has_nws_tone}, "
                         f"Narration={detection_result.has_narration}")

        if progress:
            progress.update("decode", 2, 6, "Processing SAME headers...")

        # Get the basic SAME decode result
        same_result = detection_result.raw_same_result
        if not same_result:
            # Fallback to basic decode if comprehensive failed
            same_result = decode_same_audio(audio_path)

        if progress:
            progress.update("decode", 3, 6, "Extracting audio segments...")

        # Step 2: Build segment dictionary with comprehensive segments
        segments = {}
        sample_rate = detection_result.sample_rate or same_result.sample_rate

        # Add SAME header segment (from original decode)
        if 'header' in same_result.segments:
            segments['header'] = same_result.segments['header']

        # Add attention tone segment (EBS or NWS 1050Hz)
        if detection_result.alert_tones:
            # Take the first/longest tone as the attention tone
            tone = max(detection_result.alert_tones, key=lambda t: t.duration_seconds)

            tone_wav = _extract_audio_segment_wav(
                audio_path,
                tone.start_sample,
                tone.end_sample,
                sample_rate
            )

            # Create a segment object similar to SAMEAudioSegment
            from app_utils.eas_decode import SAMEAudioSegment
            tone_segment = SAMEAudioSegment(
                label='attention_tone',
                start_sample=tone.start_sample,
                end_sample=tone.end_sample,
                sample_rate=sample_rate,
                wav_bytes=tone_wav
            )
            segments['attention_tone'] = tone_segment

            route_logger.info(f"Extracted {tone.tone_type.upper()} tone: "
                            f"{tone.duration_seconds:.2f}s at {tone.start_sample / sample_rate:.2f}s")

        # Add narration segment
        if detection_result.narration_segments:
            # Take the first narration segment with speech
            narration = next((seg for seg in detection_result.narration_segments if seg.contains_speech),
                           detection_result.narration_segments[0] if detection_result.narration_segments else None)

            if narration:
                narration_wav = _extract_audio_segment_wav(
                    audio_path,
                    narration.start_sample,
                    narration.end_sample,
                    sample_rate
                )

                from app_utils.eas_decode import SAMEAudioSegment
                narration_segment = SAMEAudioSegment(
                    label='narration',
                    start_sample=narration.start_sample,
                    end_sample=narration.end_sample,
                    sample_rate=sample_rate,
                    wav_bytes=narration_wav
                )
                segments['narration'] = narration_segment

                route_logger.info(f"Extracted narration: {narration.duration_seconds:.2f}s "
                                f"at {narration.start_sample / sample_rate:.2f}s, "
                                f"speech={narration.contains_speech}")

        # Add EOM segment (from original decode)
        if 'eom' in same_result.segments:
            segments['eom'] = same_result.segments['eom']

        # Add buffer segment (from original decode)
        if 'buffer' in same_result.segments:
            segments['buffer'] = same_result.segments['buffer']

        if progress:
            progress.update("decode", 6, 6, "Finalizing audio segments...")

        # Update the decode result with comprehensive segments
        same_result.segments.clear()
        same_result.segments.update(segments)

        return same_result, detection_result

    except Exception as e:
        if progress:
            progress.error(f"Audio decode failed: {str(e)}")
        route_logger.error(f"Comprehensive detection failed: {e}", exc_info=True)
        # Fallback to basic decode
        return decode_same_audio(audio_path), None


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

        errors: List[str] = []
        decode_result: Optional[SAMEAudioDecodeResult] = None
        stored_record = None

        if progress:
            progress.update("upload", 2, 4, "Uploading and preparing audio file...")

        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temp_file:
            upload.save(temp_file.name)
            temp_path = temp_file.name

        try:
            # Use comprehensive detection to properly separate all EAS elements
            decode_result, detection_result = _detect_comprehensive_eas_segments(
                temp_path,
                route_logger,
                progress=progress
            )
        except AudioDecodeError as exc:
            if progress:
                progress.error(f"Audio decode error: {str(exc)}")
            errors.append(str(exc))
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Unexpected failure decoding SAME audio: %s", exc)
            if progress:
                progress.error("Unable to decode audio payload")
            errors.append("Unable to decode audio payload. See logs for details.")
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except OSError as exc:
                route_logger.debug("Failed to clean up temp file %s: %s", temp_path, exc)

            if decode_result and request.form.get("store_results") == "on":
                if progress:
                    progress.update("storage", 1, 1, "Storing decode results...")
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
        progress_id = None

        # Clean up old progress data (older than 1 hour)
        ProgressTracker.cleanup_old(max_age_seconds=3600)

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
        )

    @app.route("/admin/alert-verification/progress/<operation_id>")
    def alert_verification_progress(operation_id: str):
        """Get progress status for a long-running operation."""
        progress_data = ProgressTracker.get(operation_id)

        if not progress_data:
            route_logger.debug(f"Progress not found for operation_id: {operation_id}")
            return jsonify({
                "status": "not_found",
                "message": "No progress data found for this operation"
            }), 404

        route_logger.debug(f"Progress for {operation_id}: {progress_data.get('percent')}% - {progress_data.get('message')}")
        return jsonify({
            "status": "ok",
            "progress": progress_data
        })

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

    @app.route("/admin/alert-verification/decodes/<int:decode_id>/audio/<string:segment>")
    def alert_verification_decode_audio(decode_id: int, segment: str):
        segment_key = (segment or "").strip().lower()
        column_map = {
            "header": "header_audio_data",
            "attention_tone": "attention_tone_audio_data",
            "tone": "attention_tone_audio_data",  # Alias
            "narration": "narration_audio_data",
            "eom": "eom_audio_data",
            "buffer": "buffer_audio_data",
            "message": "message_audio_data",  # Deprecated, for backward compatibility
        }

        if segment_key not in column_map:
            abort(400, description="Unsupported audio segment.")

        record = EASDecodedAudio.query.get_or_404(decode_id)
        payload = getattr(record, column_map[segment_key])
        if not payload:
            abort(404, description="Audio segment not available.")

        download = (request.args.get("download") or "").strip().lower()
        as_attachment = download in {"1", "true", "yes", "download"}

        filename = f"decoded_{decode_id}_{segment_key}.wav"
        file_obj = io.BytesIO(payload)
        file_obj.seek(0)

        response = send_file(
            file_obj,
            mimetype="audio/wav",
            as_attachment=as_attachment,
            download_name=filename,
            max_age=0,
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


__all__ = ["register"]
