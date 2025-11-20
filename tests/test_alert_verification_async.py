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

import io
import sys
import threading
import wave
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_utils.eas_decode import SAMEAudioDecodeResult, SAMEAudioSegment, SAMEHeaderDetails

import webapp.routes.alert_verification as alert_verification


def test_decode_result_serialization_round_trip():
    segment = SAMEAudioSegment(
        label="test",
        start_sample=0,
        end_sample=44100,
        sample_rate=44100,
        wav_bytes=b"\x00\x01\x02\x03",
    )

    decode_result = SAMEAudioDecodeResult(
        raw_text="ZCZC-TEST",
        headers=[
            SAMEHeaderDetails(
                header="ZCZC-TEST",
                fields={"event_code": "RWT"},
                confidence=0.95,
                summary="Required Weekly Test",
            )
        ],
        bit_count=100,
        frame_count=4,
        frame_errors=0,
        duration_seconds=10.0,
        sample_rate=44100,
        bit_confidence=0.98,
        min_bit_confidence=0.94,
        segments=OrderedDict([("attention_tone", segment)]),
    )

    payload = alert_verification._serialize_decode_result(decode_result)
    restored = alert_verification._deserialize_decode_result(payload)

    assert restored.raw_text == decode_result.raw_text
    assert restored.headers[0].header == decode_result.headers[0].header
    assert pytest.approx(restored.headers[0].confidence) == decode_result.headers[0].confidence
    assert restored.segments["attention_tone"].wav_bytes == segment.wav_bytes
    assert restored.segments["attention_tone"].sample_rate == segment.sample_rate


def test_operation_result_store(tmp_path, monkeypatch):
    # Redirect the result store to a temporary path for isolation
    monkeypatch.setattr(alert_verification, "_result_dir", str(tmp_path))
    monkeypatch.setattr(alert_verification, "_result_lock", threading.Lock())

    payload = {"decode_errors": ["example"], "decode_result": {"raw_text": ""}}
    alert_verification.OperationResultStore.save("test-op", payload)

    stored = alert_verification.OperationResultStore.load("test-op")
    assert stored == payload

    alert_verification.OperationResultStore.cleanup_old(max_age_seconds=0)
    alert_verification.OperationResultStore.clear("test-op")
    assert alert_verification.OperationResultStore.load("test-op") is None


def test_pcm_buffer_builds_segments():
    sample_rate = 22050
    # Generate one second of ramp samples
    pcm_samples = np.linspace(-0.5, 0.5, sample_rate, dtype=np.float32)
    pcm_int16 = np.clip(pcm_samples * 32767.0, -32768, 32767).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_out:
        wav_out.setnchannels(1)
        wav_out.setsampwidth(2)
        wav_out.setframerate(sample_rate)
        wav_out.writeframes(pcm_int16.tobytes())

    segment = SAMEAudioSegment(
        label="buffer",
        start_sample=0,
        end_sample=pcm_int16.size,
        sample_rate=sample_rate,
        wav_bytes=buffer.getvalue(),
    )

    cache = alert_verification._PCMBuffer.from_segment(segment)
    assert cache is not None

    sub_segment = cache.build_segment("slice", 100, 1000)
    assert sub_segment is not None
    assert sub_segment.start_sample == 100
    assert sub_segment.end_sample == 1000

    with wave.open(io.BytesIO(sub_segment.wav_bytes), "rb") as handle:
        assert handle.getframerate() == sample_rate
        assert handle.getnframes() == 900
