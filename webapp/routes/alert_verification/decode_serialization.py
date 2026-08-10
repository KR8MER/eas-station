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

"""A SAME decode result across the thread boundary.

The async worker returns its result through the on-disk store, so the decode
dataclasses have to survive a JSON round trip.
"""

from collections import OrderedDict
from types import SimpleNamespace
from typing import Dict, List, OrderedDict as TypingOrderedDict

import base64
from app_utils.eas_decode import (
    ENDEC_MODE_UNKNOWN,
    SAMEAudioDecodeResult,
    SAMEAudioSegment,
    SAMEHeaderDetails,
)


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

    mdc1200_packets = [
        SimpleNamespace(**pkt) for pkt in (data.get("mdc1200_packets") or [])
    ]

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
        endec_mode=str(data.get("endec_mode") or ENDEC_MODE_UNKNOWN),
        alert_tones=list(data.get("alert_tones") or []),
        dtmf_tones=list(data.get("dtmf_tones") or []),
        qc2_tones=list(data.get("qc2_tones") or []),
        mdc1200_packets=mdc1200_packets,
    )
