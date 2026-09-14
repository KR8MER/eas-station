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

"""Tests for sdr_hardware_service._run_bandscan_sweep -- the Bandscan
feature's background-thread sweep body.

The one genuinely important property here isn't the DSP (a single
_measure_iq_levels() call per channel, already covered by
test_sdr_capture_tap_and_auto_gain.py) -- it's that the receiver's
original frequency is ALWAYS restored no matter how the sweep ends
(normal completion, cancellation, or an exception mid-loop), since this
function calls receiver.set_frequency() directly and never touches the
database's assigned frequency. Called directly (not through the Redis
command queue) with settle_sec=0/measure_sec tiny, so these run fast.
"""

import json
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sdr_hardware_service as svc


class _FakeConfig:
    def __init__(self, frequency_hz):
        self.frequency_hz = frequency_hz
        self.sample_rate = 250_000


class _FakeBandscanReceiver:
    """Fake receiver whose set_frequency/get_samples are simple enough to
    assert against, with optional failure injection for the error-path
    test."""

    def __init__(self, start_freq_hz=93_900_000, fail_get_samples_at_call=None):
        self.config = _FakeConfig(start_freq_hz)
        self._effective_sample_rate = 250_000
        self.set_frequency_calls: list = []
        self._get_samples_call_count = 0
        self._fail_get_samples_at_call = fail_get_samples_at_call

    def set_frequency(self, freq_hz):
        self.set_frequency_calls.append(float(freq_hz))
        self.config.frequency_hz = float(freq_hz)
        return True

    def get_samples(self, num_samples=None):
        self._get_samples_call_count += 1
        if self._fail_get_samples_at_call is not None and (
            self._get_samples_call_count == self._fail_get_samples_at_call
        ):
            raise RuntimeError("simulated hardware read failure")
        n = num_samples or 4096
        return np.full(n, 0.1 + 0j, dtype=np.complex64)


class _FakeRedis:
    """Records every setex call so tests can inspect the final progress
    payload without a real Redis instance."""

    def __init__(self):
        self.writes: list = []

    def setex(self, key, ttl, value):
        self.writes.append((key, ttl, json.loads(value)))

    def last_payload(self):
        return self.writes[-1][2] if self.writes else None


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    # These tests only care about frequency/status bookkeeping, not real
    # timing -- skip the per-channel settle delay entirely.
    monkeypatch.setattr(svc.time, "sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def _clean_active_bandscans():
    svc._state.active_bandscans.clear()
    yield
    svc._state.active_bandscans.clear()


def _run(receiver, redis_client, cancel_event, **kwargs):
    svc._run_bandscan_sweep(
        receiver=receiver,
        receiver_id="rx-test",
        redis_client=redis_client,
        cancel_event=cancel_event,
        settle_sec=0.0,
        measure_sec=0.001,
        **kwargs,
    )


def test_channel_list_matches_expected_count_and_bounds():
    """A 100.0-100.3 MHz sweep at 100 kHz steps visits exactly the 4
    expected frequencies, in order."""
    receiver = _FakeBandscanReceiver(start_freq_hz=93_900_000)
    redis_client = _FakeRedis()

    _run(
        receiver, redis_client, threading.Event(),
        start_hz=100_000_000, end_hz=100_300_000, step_hz=100_000,
    )

    payload = redis_client.last_payload()
    assert payload["status"] == "done"
    freqs = [r["freq_hz"] for r in payload["results"]]
    assert freqs == [100_000_000, 100_100_000, 100_200_000, 100_300_000]
    # Every result has a real rms_dbfs -- the fake receiver always returns
    # usable samples.
    assert all(r["rms_dbfs"] is not None for r in payload["results"])


def test_original_frequency_restored_after_normal_completion():
    original = 93_900_000
    receiver = _FakeBandscanReceiver(start_freq_hz=original)
    redis_client = _FakeRedis()

    _run(
        receiver, redis_client, threading.Event(),
        start_hz=100_000_000, end_hz=100_200_000, step_hz=100_000,
    )

    assert receiver.config.frequency_hz == pytest.approx(original)
    # The very last set_frequency call must be the restore, not the last
    # scan channel.
    assert receiver.set_frequency_calls[-1] == pytest.approx(original)
    assert redis_client.last_payload()["status"] == "done"


def test_cancellation_mid_sweep_restores_frequency_and_marks_cancelled():
    original = 93_900_000
    receiver = _FakeBandscanReceiver(start_freq_hz=original)
    redis_client = _FakeRedis()
    cancel_event = threading.Event()

    # A wide range that would normally take many channels -- cancel after
    # the very first one by setting the event inside get_samples, so the
    # sweep loop's next iteration sees it set.
    real_get_samples = receiver.get_samples

    def _get_samples_then_cancel(num_samples=None):
        result = real_get_samples(num_samples)
        cancel_event.set()
        return result

    receiver.get_samples = _get_samples_then_cancel

    _run(
        receiver, redis_client, cancel_event,
        start_hz=100_000_000, end_hz=108_000_000, step_hz=100_000,
    )

    payload = redis_client.last_payload()
    assert payload["status"] == "cancelled"
    # Only the first channel (or very few) should have been measured
    # before the cancel took effect -- nowhere near the full 80-channel
    # range.
    assert 1 <= len(payload["results"]) < 5
    assert receiver.config.frequency_hz == pytest.approx(original)
    assert receiver.set_frequency_calls[-1] == pytest.approx(original)


def test_exception_mid_sweep_restores_frequency_and_marks_error():
    original = 93_900_000
    # get_samples is called twice per channel (one discarded drain read,
    # one real measurement inside _measure_iq_levels) -- fail on the 2nd
    # call so it escapes the drain read's own try/except and actually
    # propagates out of the sweep loop.
    receiver = _FakeBandscanReceiver(start_freq_hz=original, fail_get_samples_at_call=2)
    redis_client = _FakeRedis()

    _run(
        receiver, redis_client, threading.Event(),
        start_hz=100_000_000, end_hz=100_300_000, step_hz=100_000,
    )

    payload = redis_client.last_payload()
    assert payload["status"] == "error"
    assert receiver.config.frequency_hz == pytest.approx(original)
    assert receiver.set_frequency_calls[-1] == pytest.approx(original)


def test_active_bandscans_entry_is_cleared_on_completion():
    """The caller (bandscan_sweep command handler) registers the
    cancel Event in _state.active_bandscans before spawning the thread;
    this function must always remove it when done, or a receiver would
    be stuck forever reporting 'a scan is already running'."""
    receiver = _FakeBandscanReceiver()
    redis_client = _FakeRedis()
    cancel_event = threading.Event()
    svc._state.active_bandscans["rx-test"] = cancel_event

    _run(
        receiver, redis_client, cancel_event,
        start_hz=100_000_000, end_hz=100_100_000, step_hz=100_000,
    )

    assert "rx-test" not in svc._state.active_bandscans


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
