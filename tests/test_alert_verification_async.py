import sys
import threading
from collections import OrderedDict
from pathlib import Path

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
