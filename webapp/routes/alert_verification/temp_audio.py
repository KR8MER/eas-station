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

"""Decoding an uploaded file: detect segments, then persist."""

from typing import List, Optional, Tuple

from app_core.eas_storage import record_audio_decode_result
from app_utils.eas_decode import AudioDecodeError, SAMEAudioDecodeResult

from .eas_detection import _detect_comprehensive_eas_segments
from .progress import ProgressTracker


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
            store_results=store_results,
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
