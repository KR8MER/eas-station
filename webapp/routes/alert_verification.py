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

from __future__ import annotations

"""Routes powering the alert verification and analytics dashboard."""

import json
import os
import tempfile
import time
import uuid
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import (
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    OrderedDict as TypingOrderedDict,
)

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

from app_core.audio.self_test import (
    AlertSelfTestHarness,
    AlertSelfTestResult,
    AlertSelfTestStatus,
)
from app_core.eas_storage import (
    build_alert_delivery_trends,
    collect_alert_delivery_records,
    load_recent_audio_decodes,
    record_audio_decode_result,
)
from app_core.models import EASDecodedAudio
from app_core.location import get_location_settings
import base64
import io
import wave
import struct
import numpy as np
from app_utils import format_local_datetime, utc_now
from app_utils.export import generate_csv
from app_utils.eas_decode import (
    AudioDecodeError,
    SAMEAudioDecodeResult,
    SAMEAudioSegment,
    SAMEHeaderDetails,
    decode_same_audio,
)
from app_utils.eas_detection import detect_eas_from_file


DEFAULT_SAMPLE_FILES: Tuple[Path, ...] = (
    Path("samples/ZCZC-EAS-RWT-039137+0015-3042020-KR8MER.wav"),
    Path("samples/ZCZC-EAS-RWT-042001-042071-042133+0300-3040858-WJONTV.wav"),
)


class AlertSelfTestError(RuntimeError):
    """Raised when the self-test inputs are invalid."""


# Progress tracking infrastructure
# Persist to the filesystem so multiple workers can share state
_progress_lock = threading.Lock()
_progress_dir = os.path.join(tempfile.gettempdir(), "alert_verification_progress")
os.makedirs(_progress_dir, exist_ok=True)

_result_lock = threading.Lock()
_result_dir = os.path.join(_progress_dir, "results")
os.makedirs(_result_dir, exist_ok=True)


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


class OperationResultStore:
    """Persist alert verification results for asynchronous retrieval."""

    @staticmethod
    def _path(operation_id: str) -> str:
        safe_id = _sanitize_operation_id(operation_id)
        return os.path.join(_result_dir, f"{safe_id}.json")

    @classmethod
    def save(cls, operation_id: str, payload: Dict) -> None:
        data = dict(payload or {})
        target_path = cls._path(operation_id)
        temp_path = f"{target_path}.{uuid.uuid4().hex}.tmp"

        with _result_lock:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            os.replace(temp_path, target_path)

    @classmethod
    def load(cls, operation_id: str) -> Optional[Dict]:
        with _result_lock:
            try:
                with open(cls._path(operation_id), "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except FileNotFoundError:
                return None
            except (OSError, json.JSONDecodeError):  # pragma: no cover - defensive
                return None

    @classmethod
    def clear(cls, operation_id: str) -> None:
        with _result_lock:
            try:
                os.remove(cls._path(operation_id))
            except FileNotFoundError:
                return
            except OSError:  # pragma: no cover - defensive
                return

    @classmethod
    def cleanup_old(cls, max_age_seconds: int = 3600) -> None:
        current_time = time.time()
        with _result_lock:
            try:
                for filename in os.listdir(_result_dir):
                    if not filename.endswith(".json"):
                        continue
                    path = os.path.join(_result_dir, filename)
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


def _serialize_decode_result(decode_result: SAMEAudioDecodeResult) -> Dict[str, object]:
    payload = decode_result.to_dict()
    segment_audio: Dict[str, str] = {}

    for name, segment in decode_result.segments.items():
        wav_bytes = getattr(segment, "wav_bytes", None)
        if wav_bytes:
            segment_audio[name] = base64.b64encode(wav_bytes).decode("ascii")

    payload["segment_audio"] = segment_audio
    return payload


def _deserialize_decode_result(data: Dict[str, object]) -> SAMEAudioDecodeResult:
    headers: List[SAMEHeaderDetails] = []
    for header_data in data.get("headers", []):
        headers.append(
            SAMEHeaderDetails(
                header=header_data.get("header", ""),
                fields=dict(header_data.get("fields") or {}),
                confidence=float(header_data.get("confidence", 0.0)),
                summary=header_data.get("summary"),
            )
        )

    segments: TypingOrderedDict[str, SAMEAudioSegment] = OrderedDict()
    segment_meta = data.get("segments", {}) or {}
    segment_audio = data.get("segment_audio", {}) or {}

    for name, meta in segment_meta.items():
        audio_b64 = segment_audio.get(name)
        wav_bytes = base64.b64decode(audio_b64) if audio_b64 else b""
        segments[name] = SAMEAudioSegment(
            label=meta.get("label") or name,
            start_sample=int(meta.get("start_sample") or 0),
            end_sample=int(meta.get("end_sample") or 0),
            sample_rate=int(meta.get("sample_rate") or data.get("sample_rate") or 0),
            wav_bytes=wav_bytes,
        )

    return SAMEAudioDecodeResult(
        raw_text=data.get("raw_text", ""),
        headers=headers,
        bit_count=int(data.get("bit_count") or 0),
        frame_count=int(data.get("frame_count") or 0),
        frame_errors=int(data.get("frame_errors") or 0),
        duration_seconds=float(data.get("duration_seconds") or 0.0),
        sample_rate=int(data.get("sample_rate") or 0),
        bit_confidence=float(data.get("bit_confidence") or 0.0),
        min_bit_confidence=float(data.get("min_bit_confidence") or 0.0),
        segments=segments,
    )

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


class _PCMBuffer:
    """Helper for quickly rendering WAV segments from cached PCM samples."""

    def __init__(self, *, sample_rate: int, samples: np.ndarray, origin_start: int = 0):
        self.sample_rate = int(sample_rate)
        self.samples = samples.astype(np.int16, copy=True)
        self.origin_start = max(0, int(origin_start))

    @property
    def sample_count(self) -> int:
        return int(self.samples.size)

    @classmethod
    def from_segment(cls, segment: Optional[SAMEAudioSegment]) -> Optional["_PCMBuffer"]:
        if not segment or not getattr(segment, "wav_bytes", None):
            return None

        try:
            with wave.open(io.BytesIO(segment.wav_bytes), "rb") as handle:
                sample_rate = handle.getframerate()
                sample_width = handle.getsampwidth()
                frames = handle.readframes(handle.getnframes())
        except Exception:
            return None

        if not frames:
            return None

        if sample_width == 2:
            samples = np.frombuffer(frames, dtype=np.int16)
        else:
            dtype_map = {1: np.int8, 4: np.int32}
            dtype = dtype_map.get(sample_width)
            if dtype is None:
                return None
            raw = np.frombuffer(frames, dtype=dtype).astype(np.float32)
            scale = float(2 ** (sample_width * 8 - 1))
            if not scale:
                return None
            samples = np.clip(raw / scale, -1.0, 1.0)
            samples = (samples * 32767.0).astype(np.int16)

        if samples.size == 0:
            return None

        return cls(sample_rate=sample_rate, samples=samples, origin_start=segment.start_sample)

    def build_segment(self, label: str, start_sample: int, end_sample: int) -> Optional[SAMEAudioSegment]:
        if end_sample <= start_sample:
            return None

        relative_start = max(0, start_sample - self.origin_start)
        relative_end = max(relative_start, end_sample - self.origin_start)
        relative_end = min(relative_end, self.sample_count)
        relative_start = min(relative_start, relative_end)

        if relative_end <= relative_start:
            return None

        actual_start = self.origin_start + relative_start
        actual_end = actual_start + (relative_end - relative_start)
        pcm_slice = self.samples[relative_start:relative_end]
        if pcm_slice.size == 0:
            return None

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_out:
            wav_out.setnchannels(1)
            wav_out.setsampwidth(2)
            wav_out.setframerate(self.sample_rate)
            wav_out.writeframes(pcm_slice.tobytes())

        return SAMEAudioSegment(
            label=label,
            start_sample=actual_start,
            end_sample=actual_end,
            sample_rate=self.sample_rate,
            wav_bytes=buffer.getvalue(),
        )


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
        pcm_cache = _PCMBuffer.from_segment(same_result.segments.get('buffer'))
        if pcm_cache and pcm_cache.sample_rate != sample_rate:
            pcm_cache = None
        if not pcm_cache:
            pcm_cache = _PCMBuffer.from_segment(same_result.segments.get('message'))
            if pcm_cache and pcm_cache.sample_rate != sample_rate:
                pcm_cache = None

        # Add SAME header segment (from original decode)
        if 'header' in same_result.segments:
            segments['header'] = same_result.segments['header']

        # Add attention tone segment (EBS or NWS 1050Hz)
        if detection_result.alert_tones:
            # Take the first/longest tone as the attention tone
            tone = max(detection_result.alert_tones, key=lambda t: t.duration_seconds)

            tone_segment: Optional[SAMEAudioSegment] = None
            if pcm_cache:
                tone_segment = pcm_cache.build_segment(
                    'attention_tone',
                    tone.start_sample,
                    tone.end_sample,
                )

            if not tone_segment:
                tone_wav = _extract_audio_segment_wav(
                    audio_path,
                    tone.start_sample,
                    tone.end_sample,
                    sample_rate
                )

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
                narration_segment: Optional[SAMEAudioSegment] = None
                if pcm_cache:
                    narration_segment = pcm_cache.build_segment(
                        'narration',
                        narration.start_sample,
                        narration.end_sample,
                    )

                if not narration_segment:
                    narration_wav = _extract_audio_segment_wav(
                        audio_path,
                        narration.start_sample,
                        narration.end_sample,
                        sample_rate
                    )

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
        elif 'buffer' in same_result.segments and not detection_result.alert_tones:
            # Fallback: If no narration detected and no tones, extract narration from buffer
            # This helps when the audio doesn't have clear attention tones
            buffer_seg = same_result.segments['buffer']
            header_seg = same_result.segments.get('header')
            eom_seg = same_result.segments.get('eom')
            
            # Calculate narration bounds: after both header AND eom, to end of buffer
            # (since EOM often overlaps with or is before the end of header)
            narration_start = buffer_seg.start_sample
            if header_seg and eom_seg:
                # Start after whichever ends later
                narration_start = max(header_seg.end_sample, eom_seg.end_sample)
            elif header_seg:
                narration_start = header_seg.end_sample
            elif eom_seg:
                narration_start = eom_seg.end_sample
                
            narration_end = buffer_seg.end_sample
            
            # Only create narration if there's meaningful content
            narration_duration = (narration_end - narration_start) / sample_rate
            if narration_duration > 0.5:  # At least 0.5 seconds
                route_logger.info(f"No specific narration detected; extracting {narration_duration:.2f}s from buffer as narration fallback")
                
                narration_wav = _extract_audio_segment_wav(
                    audio_path,
                    narration_start,
                    narration_end,
                    sample_rate
                )
                
                segments['narration'] = SAMEAudioSegment(
                    label='narration',
                    start_sample=narration_start,
                    end_sample=narration_end,
                    sample_rate=sample_rate,
                    wav_bytes=narration_wav
                )

        # Add EOM segment (from original decode)
        if 'eom' in same_result.segments:
            segments['eom'] = same_result.segments['eom']

        # Add buffer segment (from original decode)
        if 'buffer' in same_result.segments:
            segments['buffer'] = same_result.segments['buffer']

        if progress:
            progress.update("decode", 5, 6, "Building composite audio segment...")

        # Build composite audio segment combining all individual segments
        composite = _build_composite_audio_segment(segments, sample_rate)
        if composite:
            route_logger.info(f"Created composite segment: {composite.duration_seconds:.2f}s")

        if progress:
            progress.update("decode", 6, 6, "Finalizing audio segments...")

        # Update the decode result with comprehensive segments in desired order
        # Composite first, then individual segments in chronological order
        same_result.segments.clear()
        ordered_segments = OrderedDict()
        
        # Add composite first if available
        if composite:
            ordered_segments['composite'] = composite
        
        # Then add individual segments in order
        for key in ['header', 'attention_tone', 'narration', 'eom', 'buffer']:
            if key in segments:
                ordered_segments[key] = segments[key]
        
        same_result.segments.update(ordered_segments)

        return same_result, detection_result

    except Exception as e:
        if progress:
            progress.error(f"Audio decode failed: {str(e)}")
        route_logger.error(f"Comprehensive detection failed: {e}", exc_info=True)
        # Fallback to basic decode
        return decode_same_audio(audio_path), None


def _build_composite_audio_segment(segments: Dict[str, SAMEAudioSegment], sample_rate: int, audio_path: Optional[str] = None) -> Optional[SAMEAudioSegment]:
    """
    Build a composite audio segment that represents the complete EAS alert.
    
    Strategy:
    1. If we have individual segments (header, tone, narration, eom), combine them
    2. Otherwise, use the buffer segment which contains the full audio
    
    Args:
        segments: Dictionary of detected segments
        sample_rate: Audio sample rate
        audio_path: Optional path to original audio file for fallback extraction
        
    Returns:
        Composite SAMEAudioSegment or None if no segments available
    """
    # Check if we have buffer segment - it contains the full alert audio
    if 'buffer' in segments:
        buffer_seg = segments['buffer']
        return SAMEAudioSegment(
            label='composite',
            start_sample=buffer_seg.start_sample,
            end_sample=buffer_seg.end_sample,
            sample_rate=buffer_seg.sample_rate,
            wav_bytes=buffer_seg.wav_bytes
        )
    
    # Fallback: combine individual segments
    # Define the order of segments for the composite
    segment_order = ['header', 'attention_tone', 'narration', 'eom']
    
    # Collect PCM buffers for each segment
    pcm_buffers = []
    start_sample = None
    end_sample = None
    
    for segment_name in segment_order:
        segment = segments.get(segment_name)
        if not segment or not segment.wav_bytes:
            continue
            
        # Extract PCM data from WAV bytes
        try:
            with wave.open(io.BytesIO(segment.wav_bytes), 'rb') as wf:
                seg_sample_rate = wf.getframerate()
                sample_width = wf.getsampwidth()
                frames = wf.readframes(wf.getnframes())
                
                # Convert to int16 PCM
                if sample_width == 2:
                    pcm_data = np.frombuffer(frames, dtype=np.int16)
                else:
                    # Convert other formats to int16
                    dtype_map = {1: np.int8, 4: np.int32}
                    dtype = dtype_map.get(sample_width)
                    if dtype is None:
                        continue
                    raw = np.frombuffer(frames, dtype=dtype).astype(np.float32)
                    scale = float(2 ** (sample_width * 8 - 1))
                    if not scale:
                        continue
                    normalized = np.clip(raw / scale, -1.0, 1.0)
                    pcm_data = (normalized * 32767.0).astype(np.int16)
                
                pcm_buffers.append(pcm_data)
                
                # Track overall start and end samples
                if start_sample is None:
                    start_sample = segment.start_sample
                end_sample = segment.end_sample
                
        except Exception as e:
            # Skip this segment if we can't process it
            continue
    
    if not pcm_buffers:
        return None
    
    # Concatenate all PCM buffers
    composite_pcm = np.concatenate(pcm_buffers)
    
    # Create WAV file
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(composite_pcm.tobytes())
    
    return SAMEAudioSegment(
        label='composite',
        start_sample=start_sample or 0,
        end_sample=end_sample or len(composite_pcm),
        sample_rate=sample_rate,
        wav_bytes=buffer.getvalue(),
    )


def _process_temp_audio_file(
    temp_path: str,
    filename: str,
    mimetype: str,
    store_results: bool,
    route_logger,
    progress: Optional[ProgressTracker] = None,
) -> Tuple[Optional[SAMEAudioDecodeResult], List[str], Optional[object]]:
    """Decode an uploaded audio file stored at temp_path."""

    errors: List[str] = []
    decode_result: Optional[SAMEAudioDecodeResult] = None
    stored_record = None

    try:
        decode_result, _ = _detect_comprehensive_eas_segments(
            temp_path,
            route_logger,
            progress=progress,
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

    if decode_result and store_results:
        if progress:
            progress.update("storage", 1, 1, "Storing decode results...")
        try:
            stored_record = record_audio_decode_result(
                filename=filename,
                content_type=mimetype,
                decode_payload=decode_result,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Failed to store decoded audio payload: %s", exc)
            errors.append("Decoded results were generated but could not be stored.")

    return decode_result, errors, stored_record


def register(app: Flask, logger) -> None:
    """Register alert verification routes on the Flask application."""

    route_logger = logger.getChild("alert_verification")
    repo_root = Path(app.root_path).resolve()

    # Clean up stale progress files on startup (files older than 1 hour)
    try:
        ProgressTracker.cleanup_old(max_age_seconds=3600)
        route_logger.info("Cleaned up stale alert verification progress files")
    except Exception as e:
        route_logger.warning(f"Failed to cleanup stale progress files: {e}")

    def _load_configured_fips(override: Iterable[str]) -> List[str]:
        override_list = [str(code).strip() for code in (override or []) if str(code).strip()]
        if override_list:
            return override_list

        settings = get_location_settings()
        return list(settings.get("fips_codes") or [])

    def _resolve_audio_paths(paths: Sequence[str], include_defaults: bool) -> List[Path]:
        resolved: List[Path] = []
        seen: set[Path] = set()

        def _add(candidate: Path) -> None:
            target = candidate.resolve()
            if target in seen:
                return
            if not target.exists():
                raise AlertSelfTestError(f"Audio sample not found: {target}")
            seen.add(target)
            resolved.append(target)

        for raw_value in paths or []:
            if not raw_value:
                continue
            candidate = Path(str(raw_value)).expanduser()
            if not candidate.is_absolute():
                candidate = repo_root / candidate
            _add(candidate)

        if include_defaults or not resolved:
            for rel_path in DEFAULT_SAMPLE_FILES:
                candidate = (repo_root / rel_path).resolve()
                if candidate.exists():
                    _add(candidate)

        if not resolved:
            raise AlertSelfTestError("No audio samples were provided or available.")

        return resolved

    def _result_to_dict(item: AlertSelfTestResult) -> dict:
        return {
            "audio_path": item.audio_path,
            "status": item.status.value,
            "reason": item.reason,
            "event_code": item.event_code,
            "originator": item.originator,
            "alert_fips_codes": item.alert_fips_codes,
            "matched_fips_codes": item.matched_fips_codes,
            "confidence": item.confidence,
            "duration_seconds": item.duration_seconds,
            "raw_text": item.raw_text,
            "duplicate": item.duplicate,
            "error": item.error,
            "timestamp": item.timestamp,
        }

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

    @app.route("/admin/alert-verification", methods=["GET", "POST"])
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

    @app.route("/api/alert-self-test/run", methods=["POST"])
    def run_alert_self_test():
        payload = request.get_json(force=True, silent=True) or {}

        user_audio_paths = payload.get("audio_paths") or []
        use_default_samples = bool(payload.get("use_default_samples", not user_audio_paths))
        cooldown = payload.get("duplicate_cooldown", 30.0)
        source_name = str(payload.get("source_name") or "self-test").strip() or "self-test"
        require_match = bool(payload.get("require_match", False))
        fips_override = payload.get("fips_codes") or []

        try:
            cooldown_value = max(0.0, float(cooldown))
        except (TypeError, ValueError):
            return (
                jsonify({"success": False, "error": "Duplicate cooldown must be numeric."}),
                400,
            )

        try:
            resolved_paths = _resolve_audio_paths(user_audio_paths, use_default_samples)
        except AlertSelfTestError as exc:
            route_logger.warning("Alert self-test rejected: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 400

        configured_fips = _load_configured_fips(fips_override)

        harness = AlertSelfTestHarness(
            configured_fips,
            duplicate_cooldown_seconds=cooldown_value,
            source_name=source_name,
        )

        route_logger.info(
            "Running alert self-test: audio=%s fips=%s cooldown=%s source=%s",
            ",".join(str(path) for path in resolved_paths),
            ",".join(harness.configured_fips_codes) or "<none>",
            cooldown_value,
            source_name,
        )

        results = harness.run_audio_files(resolved_paths)
        forwarded = sum(1 for item in results if item.status == AlertSelfTestStatus.FORWARDED)
        decode_errors = sum(1 for item in results if item.status == AlertSelfTestStatus.DECODE_ERROR)

        if require_match and forwarded == 0:
            success = False
            error = "No alerts matched the configured FIPS codes."
        else:
            success = True
            error = None

        response = {
            "success": success,
            "error": error,
            "configured_fips": harness.configured_fips_codes,
            "audio_samples": [
                {"path": str(path), "name": path.name}
                for path in resolved_paths
            ],
            "duplicate_cooldown": cooldown_value,
            "source_name": source_name,
            "results": [_result_to_dict(item) for item in results],
            "forwarded_count": forwarded,
            "decode_error_count": decode_errors,
            "default_samples_used": use_default_samples and not user_audio_paths,
            "timestamp": utc_now().isoformat(),
        }

        return jsonify(response)

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
            "composite": "composite_audio_data",
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
