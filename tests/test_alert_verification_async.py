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


def test_progress_tracker_percent_is_monotonic_across_phases(tmp_path, monkeypatch):
    """The progress bar must never go backward when the pipeline moves
    from the upload phase (small total) to the decode phase (larger
    total).  This was the visible 50% → 16% regression users observed."""
    monkeypatch.setattr(alert_verification, "_progress_dir", str(tmp_path))
    monkeypatch.setattr(alert_verification, "_progress_lock", threading.Lock())

    tracker = alert_verification.ProgressTracker("op-monotonic")

    seq = [
        ("upload", 1, 4, "validate"),
        ("upload", 2, 4, "save"),
        ("decode", 1, 6, "demod-1"),  # would have been 16% in old scheme
        ("decode", 4, 6, "demod-4"),
        ("extract", 1, 4, "extract-1"),
        ("storage", 1, 1, "store"),
    ]

    last = -1
    for step, current, total, message in seq:
        tracker.update(step, current, total, message)
        snapshot = alert_verification.ProgressTracker.get("op-monotonic")
        assert snapshot is not None
        percent = int(snapshot.get("percent") or 0)
        assert percent >= last, (
            f"percent regressed at step {step}: {last} -> {percent}"
        )
        # Sub-progress must respect each phase's slice of the timeline.
        low, high = alert_verification.ProgressTracker.PHASE_RANGES[step]
        assert low <= percent <= high, (
            f"step {step} reported {percent}% outside [{low}, {high}]"
        )
        last = percent


def test_decode_same_audio_skips_sweep_when_auto_rate_disabled(monkeypatch):
    """``auto_rate_sweep=False`` must NOT call _try_multiple_sample_rates."""
    from app_utils import eas_decode

    calls = {"sweep": 0, "decode_at": 0, "callback": []}

    def fake_sweep(*args, **kwargs):
        calls["sweep"] += 1
        raise AssertionError("multi-rate sweep must not run on the fast path")

    def fake_decode(path, sample_rate):
        calls["decode_at"] += 1
        return SAMEAudioDecodeResult(
            raw_text="",
            headers=[],
            bit_count=0,
            frame_count=0,
            frame_errors=0,
            duration_seconds=0.0,
            sample_rate=sample_rate,
            bit_confidence=1.0,
            min_bit_confidence=1.0,
        )

    monkeypatch.setattr(eas_decode, "_try_multiple_sample_rates", fake_sweep)
    monkeypatch.setattr(eas_decode, "_decode_at_sample_rate", fake_decode)
    monkeypatch.setattr(eas_decode, "_detect_audio_sample_rate", lambda p: 22050)
    monkeypatch.setattr(eas_decode.os.path, "exists", lambda p: True)

    def cb(current, total, message):
        calls["callback"].append((current, total, message))

    eas_decode.decode_same_audio(
        "/tmp/fake.wav", auto_rate_sweep=False, progress_callback=cb
    )

    assert calls["sweep"] == 0
    assert calls["decode_at"] == 1
    # Fast path emits a single progress callback so the UI sees something.
    assert calls["callback"] == [(1, 1, "Demodulating SAME at 22050 Hz")]


def test_try_multiple_sample_rates_invokes_progress_callback(monkeypatch):
    """The multi-rate sweep must report progress per candidate rate so the
    progress UI advances during the slowest stage of the pipeline."""
    from app_utils import eas_decode

    fake_result = SAMEAudioDecodeResult(
        raw_text="",
        headers=[],
        bit_count=0,
        frame_count=0,
        frame_errors=0,
        duration_seconds=0.0,
        sample_rate=16000,
        bit_confidence=0.0,  # below early-exit threshold so all rates run
        min_bit_confidence=0.0,
    )

    monkeypatch.setattr(
        eas_decode, "_read_audio_samples", lambda p, r: ([0.0] * 16, b"\x00" * 32)
    )
    monkeypatch.setattr(
        eas_decode, "_decode_from_samples", lambda s, p, r: fake_result
    )
    monkeypatch.setattr(
        eas_decode,
        "_resample_with_scipy",
        lambda samples, src, dst: list(samples),
    )

    seen = []

    def cb(current, total, message):
        seen.append((current, total))

    eas_decode._try_multiple_sample_rates(
        "/tmp/fake.wav", 22050, progress_callback=cb
    )

    # At least the native rate plus several candidates fired callbacks,
    # all sharing the same total and current advancing monotonically.
    assert len(seen) >= 2
    totals = {total for _, total in seen}
    assert len(totals) == 1, f"inconsistent totals: {totals}"
    currents = [c for c, _ in seen]
    assert currents == sorted(currents)
    assert currents[0] == 1

