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

"""Persisting and reloading SAME/EAS audio-decode results."""

from typing import Any, Dict, List, Optional

from app_core.extensions import db
from app_core.models import EASDecodedAudio
from app_utils.eas_decode import SAMEAudioDecodeResult, build_plain_language_summary


def _ensure_header_summary(header: Any) -> Any:
    """Ensure legacy SAME header payloads include a summary string."""

    if not isinstance(header, dict):
        return header

    if header.get("summary"):
        return header

    header_text = header.get("header")
    fields = header.get("fields")
    if isinstance(header_text, str) and isinstance(fields, dict):
        try:
            summary = build_plain_language_summary(header_text, fields)
        except Exception:  # pragma: no cover - defensive fallback
            summary = None
        if summary:
            enriched = dict(header)
            enriched["summary"] = summary
            return enriched

    return header

def record_audio_decode_result(
    *,
    filename: Optional[str],
    content_type: Optional[str],
    decode_payload: SAMEAudioDecodeResult,
):
    """Persist the results of decoding an uploaded SAME audio payload."""

    safe_filename = (filename or "").strip()[:255] or None
    safe_type = (content_type or "").strip()[:128] or None

    segments = decode_payload.segments
    segment_metadata = decode_payload.segment_metadata

    same_headers = []
    for header in decode_payload.headers:
        payload = header.to_dict()
        if not payload.get("summary"):
            payload = _ensure_header_summary(payload)
        same_headers.append(payload)

    record = EASDecodedAudio(
        original_filename=safe_filename,
        content_type=safe_type,
        raw_text=decode_payload.raw_text,
        same_headers=same_headers,
        quality_metrics={
            "bit_count": decode_payload.bit_count,
            "frame_count": decode_payload.frame_count,
            "frame_errors": decode_payload.frame_errors,
            "duration_seconds": decode_payload.duration_seconds,
            "sample_rate": decode_payload.sample_rate,
            "bit_confidence": decode_payload.bit_confidence,
            "min_bit_confidence": decode_payload.min_bit_confidence,
            "segment_count": len(segments),
            "endec_mode": decode_payload.endec_mode,
        },
        segment_metadata=segment_metadata,
        header_audio_data=(
            segments.get("header").wav_bytes if "header" in segments else None
        ),
        attention_tone_audio_data=(
            segments.get("attention_tone").wav_bytes if "attention_tone" in segments else None
        ),
        narration_audio_data=(
            segments.get("narration").wav_bytes if "narration" in segments else None
        ),
        eom_audio_data=(segments.get("eom").wav_bytes if "eom" in segments else None),
        buffer_audio_data=(
            segments.get("buffer").wav_bytes if "buffer" in segments else None
        ),
        composite_audio_data=(
            segments.get("composite").wav_bytes if "composite" in segments else None
        ),
        # Deprecated: keep for backward compatibility
        message_audio_data=(
            segments.get("message").wav_bytes if "message" in segments else None
        ),
    )

    try:
        db.session.add(record)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return record

def load_recent_audio_decodes(limit: int = 5) -> List[Dict[str, Any]]:
    """Return the most recent decoded audio payloads for display.

    Uses ``IS NOT NULL`` projections instead of selecting the BYTEA blob
    columns so that the listing view never pulls the full audio payloads
    (which can be megabytes per row) just to populate the ``has_*`` flags.
    """

    try:
        query = (
            db.session.query(
                EASDecodedAudio.id,
                EASDecodedAudio.created_at,
                EASDecodedAudio.original_filename,
                EASDecodedAudio.content_type,
                EASDecodedAudio.raw_text,
                EASDecodedAudio.same_headers,
                EASDecodedAudio.quality_metrics,
                EASDecodedAudio.segment_metadata,
                EASDecodedAudio.header_audio_data.isnot(None).label(
                    "has_header_audio"
                ),
                EASDecodedAudio.message_audio_data.isnot(None).label(
                    "has_message_audio"
                ),
                EASDecodedAudio.eom_audio_data.isnot(None).label("has_eom_audio"),
                EASDecodedAudio.buffer_audio_data.isnot(None).label(
                    "has_buffer_audio"
                ),
            )
            .order_by(EASDecodedAudio.created_at.desc())
        )
        if limit > 0:
            query = query.limit(limit)
        rows = query.all()
    except Exception:
        db.session.rollback()
        return []

    results: List[Dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "id": row.id,
                "created_at": row.created_at,
                "original_filename": row.original_filename,
                "content_type": row.content_type,
                "raw_text": row.raw_text,
                "same_headers": [
                    _ensure_header_summary(header)
                    for header in list(row.same_headers or [])
                ],
                "quality_metrics": dict(row.quality_metrics or {}),
                "segment_metadata": dict(row.segment_metadata or {}),
                "has_header_audio": bool(row.has_header_audio),
                "has_message_audio": bool(row.has_message_audio),
                "has_eom_audio": bool(row.has_eom_audio),
                "has_buffer_audio": bool(row.has_buffer_audio),
            }
        )

    return results
