"""Unit tests for the SDR-service capture tap and auto-gain helpers.

These exercise the two pure-Python helpers in ``sdr_hardware_service`` that
implement (a) the publisher-thread tap that assembles an N-second IQ
capture in real time and (b) the runtime gain calibration sweep.

We deliberately avoid spinning up the full Redis-driven service loop;
both helpers are designed to be testable in isolation given a fake
receiver / device.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sdr_hardware_service as svc


# ---------------------------------------------------------------------------
# Capture tap
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_active_captures():
    """Ensure the module-level registry is empty between tests."""
    svc._active_captures.clear()
    yield
    svc._active_captures.clear()


def test_capture_tap_accumulates_exact_target_count():
    """The tap should collect exactly ``target_samples``, no more, no less."""
    import threading

    target = 5000
    event = threading.Event()
    entry = {
        "target_samples": target,
        "collected": 0,
        "chunks": [],
        "done": False,
        "event": event,
        "started_at": 0.0,
        "error": None,
        "command_id": "test",
    }
    svc._active_captures["rcv0"] = entry

    # Feed the tap five 1024-sample chunks (5120 total) — should be
    # trimmed to exactly 5000 and signal completion.
    chunk = np.arange(1024, dtype=np.complex64) + 1j
    for _ in range(5):
        svc._capture_tap_append("rcv0", chunk)

    assert entry["collected"] == target
    assert entry["done"] is True
    assert event.is_set()
    total = sum(len(c) for c in entry["chunks"])
    assert total == target


def test_capture_tap_no_op_when_no_active_capture():
    """With no active capture, the tap silently drops samples."""
    chunk = np.zeros(2048, dtype=np.complex64)
    # Should not raise and should not create any entry.
    svc._capture_tap_append("nobody", chunk)
    assert "nobody" not in svc._active_captures


def test_capture_tap_does_not_exceed_target_on_oversized_chunk():
    """If a single chunk would overflow, only the needed prefix is kept."""
    import threading

    entry = {
        "target_samples": 500,
        "collected": 0,
        "chunks": [],
        "done": False,
        "event": threading.Event(),
        "started_at": 0.0,
        "error": None,
        "command_id": "test",
    }
    svc._active_captures["rcv1"] = entry

    big_chunk = np.ones(8192, dtype=np.complex64)
    svc._capture_tap_append("rcv1", big_chunk)

    assert entry["collected"] == 500
    assert len(entry["chunks"]) == 1
    assert len(entry["chunks"][0]) == 500
    assert entry["done"] is True


def test_capture_tap_copies_samples():
    """The tap must copy samples so it survives producer buffer reuse."""
    import threading

    entry = {
        "target_samples": 4,
        "collected": 0,
        "chunks": [],
        "done": False,
        "event": threading.Event(),
        "started_at": 0.0,
        "error": None,
        "command_id": "test",
    }
    svc._active_captures["rcv2"] = entry

    chunk = np.array([1 + 1j, 2 + 2j, 3 + 3j, 4 + 4j], dtype=np.complex64)
    svc._capture_tap_append("rcv2", chunk)
    # Mutate the producer-owned chunk; the stored capture must NOT change.
    chunk[:] = 0
    stored = entry["chunks"][0]
    assert np.all(stored == np.array([1 + 1j, 2 + 2j, 3 + 3j, 4 + 4j], dtype=np.complex64))


# ---------------------------------------------------------------------------
# IQ level measurement
# ---------------------------------------------------------------------------

class _FakeReceiver:
    def __init__(self, samples):
        self._samples = samples

    def get_samples(self, num_samples=None):
        if self._samples is None:
            return None
        n = num_samples or len(self._samples)
        return self._samples[:n]


def test_measure_iq_levels_basic():
    """RMS and peak come back as dBFS relative to |x|=1.0."""
    # Constant complex tone at amplitude 0.5 → RMS = 0.5, peak = 0.5
    samples = np.full(4096, 0.5 + 0j, dtype=np.complex64)
    stats = svc._measure_iq_levels(_FakeReceiver(samples))
    assert stats is not None
    assert stats["samples"] == 4096
    # 20*log10(0.5) = -6.02 dBFS
    assert abs(stats["rms_dbfs"] - (-6.0)) < 0.1
    assert abs(stats["peak_dbfs"] - (-6.0)) < 0.1
    assert stats["clipping_fraction"] == 0.0


def test_measure_iq_levels_detects_clipping():
    """Samples at full scale show up in ``clipping_fraction``."""
    samples = np.concatenate([
        np.full(900, 0.1 + 0j, dtype=np.complex64),
        np.full(100, 1.0 + 0j, dtype=np.complex64),  # at full scale
    ])
    stats = svc._measure_iq_levels(_FakeReceiver(samples))
    assert stats is not None
    # 10% of samples have |x| > 0.95
    assert abs(stats["clipping_fraction"] - 0.1) < 0.001


def test_measure_iq_levels_returns_none_when_no_samples():
    assert svc._measure_iq_levels(_FakeReceiver(None)) is None
    assert svc._measure_iq_levels(_FakeReceiver(np.array([], dtype=np.complex64))) is None


# ---------------------------------------------------------------------------
# Auto-gain calibration
# ---------------------------------------------------------------------------

class _FakeSoapyModule:
    SOAPY_SDR_RX = 1


class _FakeGainRange:
    def __init__(self, lo, hi):
        self._lo, self._hi = lo, hi

    def minimum(self):
        return self._lo

    def maximum(self):
        return self._hi


class _FakeSoapyDevice:
    """Synthesises IQ samples as a function of the currently-set gain.

    Models a roughly linear gain-to-amplitude relationship so the auto-gain
    sweep has a real signal to optimise: amplitude(gain) = gain/30, clipped
    at 1.0 (drives clipping above ~30 dB).
    """

    def __init__(self):
        self.gain_db = 0.0
        self.agc = True
        self.gain_history = []
        self._range = _FakeGainRange(0.0, 40.0)

    def getGainRange(self, *_args, **_kwargs):
        return self._range

    def hasGainMode(self, *_args, **_kwargs):
        return True

    def setGainMode(self, _rx, _ch, mode):
        self.agc = bool(mode)

    def setGain(self, _rx, _ch, gain):
        self.gain_db = float(gain)
        self.gain_history.append(self.gain_db)

    def getGain(self, _rx, _ch):
        return self.gain_db


class _FakeHandle:
    def __init__(self):
        self.device = _FakeSoapyDevice()
        self.sdr = _FakeSoapyModule()


class _FakeConfig:
    sample_rate = 250_000
    channel = 0


class _FakeFmReceiver:
    """Fake receiver that emits samples whose amplitude tracks the gain."""

    def __init__(self):
        self._handle = _FakeHandle()
        self.config = _FakeConfig()
        self._effective_sample_rate = 250_000

    def get_samples(self, num_samples=None):
        n = num_samples or 8192
        amplitude = min(1.0, self._handle.device.gain_db / 30.0)
        # Tiny phase variation so |x| varies a bit, otherwise clipping ratio
        # snaps from 0 to 1 in one step which makes the test brittle.
        rng = np.linspace(0, 2 * np.pi, n, endpoint=False)
        return (amplitude * np.exp(1j * rng)).astype(np.complex64)


def test_auto_gain_picks_a_non_clipping_gain(monkeypatch):
    """Auto-gain returns a gain below the clipping knee with measurements."""
    # Skip the per-step settle/drain to keep the test fast.
    monkeypatch.setattr(svc.time, "sleep", lambda _s: None)

    receiver = _FakeFmReceiver()
    result = svc._auto_gain_calibrate(
        receiver=receiver,
        receiver_id="fakefm",
        command_id="cmd",
        settle_sec=0.0,
        measure_sec=0.01,
        target_rms_dbfs=-12.0,
        clipping_threshold=0.01,
    )
    assert result["success"] is True
    assert result["applied"] is True
    gain = result["selected_gain_db"]
    # amplitude = gain/30. Clipping starts at gain ≈ 28.5 (|x| > 0.95).
    # With clipping_threshold = 1%, the highest non-clipping gain in the
    # 1 dB sweep should be ~28 dB. We accept anything strictly below the
    # clipping knee and above 0 dB.
    assert 0 < gain < 29
    # The sweep should have visited at least the discrete gain range.
    assert len(result["measurements"]) > 5
    # AGC must be off after calibration.
    assert receiver._handle.device.agc is False
    # The final gain on the device matches the selected one.
    assert receiver._handle.device.gain_db == pytest.approx(gain)


def test_auto_gain_rejects_when_no_device_handle(monkeypatch):
    """Receivers without a SoapySDR handle fail fast with a clear error."""

    class _NoHandleReceiver:
        config = _FakeConfig()

    monkeypatch.setattr(svc.time, "sleep", lambda _s: None)
    result = svc._auto_gain_calibrate(
        receiver=_NoHandleReceiver(),
        receiver_id="x",
        command_id="cmd",
        settle_sec=0.0,
        measure_sec=0.01,
    )
    assert result["success"] is False
    assert "SoapySDR" in result["error"]
