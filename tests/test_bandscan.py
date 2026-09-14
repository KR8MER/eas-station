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
    """Records every setex/delete call so tests can inspect the final
    progress payload and the bandscan-active mute flag without a real
    Redis instance."""

    def __init__(self):
        self.writes: list = []
        self.store: dict = {}
        self.deleted_keys: list = []

    def setex(self, key, ttl, value):
        self.writes.append((key, ttl, json.loads(value)))
        self.store[key] = value

    def delete(self, key):
        self.deleted_keys.append(key)
        self.store.pop(key, None)

    def exists(self, key):
        return 1 if key in self.store else 0

    def last_payload(self):
        # The progress payload is always the last setex call each time
        # _write_progress() runs -- see its own comment on why the
        # active-flag write happens first.
        for key, _ttl, value in reversed(self.writes):
            if isinstance(value, dict):
                return value
        return None


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


def test_active_flag_present_during_sweep_and_cleared_after_completion():
    """The demod worker/audio service check RedisChannels.BANDSCAN_ACTIVE_PREFIX
    to mute audio and suppress dead-air alarms for the sweep's duration --
    this must be set while the sweep runs and explicitly cleared (not just
    left to expire on its own TTL) once it finishes."""
    receiver = _FakeBandscanReceiver(start_freq_hz=93_900_000)
    redis_client = _FakeRedis()
    active_key = f"{svc.RedisChannels.BANDSCAN_ACTIVE_PREFIX}rx-test"

    _run(
        receiver, redis_client, threading.Event(),
        start_hz=100_000_000, end_hz=100_300_000, step_hz=100_000,
    )

    # Was set at least once while the sweep ran...
    assert any(key == active_key for key, _ttl, _value in redis_client.writes)
    # ...and explicitly cleared (not just left for the TTL) once done.
    assert active_key in redis_client.deleted_keys
    assert active_key not in redis_client.store


def test_active_flag_cleared_after_cancellation():
    receiver = _FakeBandscanReceiver(start_freq_hz=93_900_000)
    redis_client = _FakeRedis()
    cancel_event = threading.Event()
    active_key = f"{svc.RedisChannels.BANDSCAN_ACTIVE_PREFIX}rx-test"

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

    assert active_key not in redis_client.store


def test_active_flag_cleared_after_error():
    receiver = _FakeBandscanReceiver(start_freq_hz=93_900_000, fail_get_samples_at_call=2)
    redis_client = _FakeRedis()
    active_key = f"{svc.RedisChannels.BANDSCAN_ACTIVE_PREFIX}rx-test"

    _run(
        receiver, redis_client, threading.Event(),
        start_hz=100_000_000, end_hz=100_300_000, step_hz=100_000,
    )

    assert active_key not in redis_client.store


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


# ---------------------------------------------------------------------------
# "Identify Stations": _run_bandscan_identify -- a second, explicit pass that
# retunes to each of a sweep's already-detected peaks and dwells long enough
# to attempt an RDS PS (station name) decode via a purpose-built
# FMDemodulator instance (see that function's own docstring for why this
# can't be folded into the sweep itself).
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402


class _FakeIdentifyDemodulator:
    """Stand-in for app_core.radio.demod.fm.FMDemodulator.

    Returns a canned RBDSData.ps_name (or None) from every demodulate()
    call instead of actually decoding anything, so these tests exercise
    _run_bandscan_identify's control flow (early-stop on decode, full-dwell
    on no decode, per-frequency isolation) without needing synthetic
    RDS-modulated IQ or real DSP -- that's app_core/radio/demod's own test
    coverage (tests/test_rbds_demodulation.py), not this function's job.
    """

    #: Queue of ps_name values (str or None), one per FMDemodulator
    #: constructed, consumed in construction order -- _run_bandscan_identify
    #: builds a fresh demodulator per target frequency, in the same order
    #: as target_freqs_hz, so this queue's order lines up with that list.
    #: None means "this frequency never decodes"; tests reset this before
    #: use via the _fake_identify_demodulator fixture.
    ps_name_queue: list = []
    demodulate_call_count = 0

    def __init__(self, config):
        self.config = config
        self._ps_name = type(self).ps_name_queue.pop(0) if type(self).ps_name_queue else None

    def demodulate(self, iq_samples):
        type(self).demodulate_call_count += 1
        status = SimpleNamespace(rbds_data=SimpleNamespace(ps_name=self._ps_name))
        return np.zeros(4, dtype=np.float32), status


@pytest.fixture
def _fake_identify_demodulator(monkeypatch):
    import app_core.radio.demod.fm as fm_module

    _FakeIdentifyDemodulator.ps_name_queue = []
    _FakeIdentifyDemodulator.demodulate_call_count = 0
    monkeypatch.setattr(fm_module, "FMDemodulator", _FakeIdentifyDemodulator)
    return _FakeIdentifyDemodulator


def _run_identify(receiver, redis_client, cancel_event, target_freqs_hz, **kwargs):
    kwargs.setdefault("dwell_sec", 0.05)
    kwargs.setdefault("settle_sec", 0.0)
    svc._run_bandscan_identify(
        receiver=receiver,
        receiver_id="rx-test",
        redis_client=redis_client,
        cancel_event=cancel_event,
        target_freqs_hz=target_freqs_hz,
        **kwargs,
    )


def test_identify_records_decoded_ps_name_and_stops_early(_fake_identify_demodulator):
    receiver = _FakeBandscanReceiver(start_freq_hz=93_900_000)
    redis_client = _FakeRedis()
    _fake_identify_demodulator.ps_name_queue = ["KISSFM"]

    # A generous dwell budget -- if the loop were burning the whole thing
    # instead of stopping the moment a name decodes, this test would be
    # slow instead of just wrong.
    _run_identify(receiver, redis_client, threading.Event(), [93_900_000.0], dwell_sec=2.5)

    payload = redis_client.last_payload()
    assert payload["status"] == "done"
    assert payload["target_freqs_hz"] == [93_900_000.0]
    assert len(payload["results"]) == 1
    result = payload["results"][0]
    assert result["freq_hz"] == 93_900_000.0
    assert result["ps_name"] == "KISSFM"
    assert result["rms_dbfs"] is not None
    # Stopped after the first successful decode, not the full dwell.
    assert _fake_identify_demodulator.demodulate_call_count == 1


def test_identify_records_none_and_uses_full_dwell_when_nothing_decodes(_fake_identify_demodulator):
    receiver = _FakeBandscanReceiver(start_freq_hz=93_900_000)
    redis_client = _FakeRedis()
    _fake_identify_demodulator.ps_name_queue = [None]

    _run_identify(receiver, redis_client, threading.Event(), [93_900_000.0], dwell_sec=0.05)

    payload = redis_client.last_payload()
    result = payload["results"][0]
    assert result["ps_name"] is None
    assert result["freq_hz"] == 93_900_000.0
    # A weak/marginal peak that never locks is not an error -- and the loop
    # should have kept trying across more than one chunk, not given up
    # after a single read.
    assert _fake_identify_demodulator.demodulate_call_count > 1


def test_identify_isolates_demodulator_state_per_frequency(_fake_identify_demodulator):
    """A stale Costas/PLL lock from one peak must never leak into the
    next -- verified here by two peaks getting two different, correctly
    ordered results from one pass."""
    receiver = _FakeBandscanReceiver(start_freq_hz=93_900_000)
    redis_client = _FakeRedis()
    _fake_identify_demodulator.ps_name_queue = ["FIRST", None]

    _run_identify(
        receiver, redis_client, threading.Event(),
        [99_500_000.0, 101_300_000.0], dwell_sec=0.05,
    )

    payload = redis_client.last_payload()
    results = payload["results"]
    assert [r["freq_hz"] for r in results] == [99_500_000.0, 101_300_000.0]
    assert results[0]["ps_name"] == "FIRST"
    assert results[1]["ps_name"] is None


def test_identify_restores_original_frequency_after_completion(_fake_identify_demodulator):
    original = 93_900_000
    receiver = _FakeBandscanReceiver(start_freq_hz=original)
    redis_client = _FakeRedis()
    _fake_identify_demodulator.ps_name_queue = ["ABC", "DEF"]

    _run_identify(
        receiver, redis_client, threading.Event(),
        [99_500_000.0, 101_300_000.0],
    )

    assert receiver.config.frequency_hz == pytest.approx(original)
    assert receiver.set_frequency_calls[-1] == pytest.approx(original)
    assert redis_client.last_payload()["status"] == "done"


def test_identify_cancellation_restores_frequency_and_marks_cancelled(_fake_identify_demodulator):
    original = 93_900_000
    receiver = _FakeBandscanReceiver(start_freq_hz=original)
    redis_client = _FakeRedis()
    cancel_event = threading.Event()
    _fake_identify_demodulator.ps_name_queue = [None, None]

    real_get_samples = receiver.get_samples

    def _get_samples_then_cancel(num_samples=None):
        result = real_get_samples(num_samples)
        cancel_event.set()
        return result

    receiver.get_samples = _get_samples_then_cancel

    _run_identify(
        receiver, redis_client, cancel_event,
        [99_500_000.0, 101_300_000.0], dwell_sec=5.0,
    )

    payload = redis_client.last_payload()
    assert payload["status"] == "cancelled"
    # Cancelled during (or right after) the first frequency -- nowhere near
    # both target frequencies getting a full result.
    assert 1 <= len(payload["results"]) < 2 + 1
    assert receiver.config.frequency_hz == pytest.approx(original)
    assert receiver.set_frequency_calls[-1] == pytest.approx(original)


def test_identify_active_flag_present_during_pass_and_cleared_after(_fake_identify_demodulator):
    """Shares RedisChannels.BANDSCAN_ACTIVE_PREFIX with the sweep (see that
    key's own docstring) -- the demod worker and audio service mute/
    suppress-dead-air off this exact flag regardless of which kind of scan
    set it."""
    receiver = _FakeBandscanReceiver()
    redis_client = _FakeRedis()
    active_key = f"{svc.RedisChannels.BANDSCAN_ACTIVE_PREFIX}rx-test"
    _fake_identify_demodulator.ps_name_queue = ["WABC"]

    _run_identify(receiver, redis_client, threading.Event(), [99_500_000.0])

    assert any(key == active_key for key, _ttl, _value in redis_client.writes)
    assert active_key in redis_client.deleted_keys
    assert active_key not in redis_client.store


def test_identify_writes_its_own_progress_key_not_the_sweeps(_fake_identify_demodulator):
    receiver = _FakeBandscanReceiver()
    redis_client = _FakeRedis()
    _fake_identify_demodulator.ps_name_queue = ["WABC"]

    _run_identify(receiver, redis_client, threading.Event(), [99_500_000.0])

    identify_key = f"{svc.RedisChannels.BANDSCAN_IDENTIFY_PROGRESS_PREFIX}rx-test"
    sweep_key = f"{svc.RedisChannels.BANDSCAN_PROGRESS_PREFIX}rx-test"
    assert identify_key in redis_client.store
    assert sweep_key not in redis_client.store


def test_identify_active_bandscans_entry_is_cleared_on_completion(_fake_identify_demodulator):
    """Shares _state.active_bandscans with the sweep (registered the same
    way, by the bandscan_identify command handler) -- either kind of scan
    already running for a receiver must block starting the other, and this
    entry must always be removed when done or a receiver would be stuck
    forever reporting 'a scan is already running'."""
    receiver = _FakeBandscanReceiver()
    redis_client = _FakeRedis()
    cancel_event = threading.Event()
    svc._state.active_bandscans["rx-test"] = cancel_event
    _fake_identify_demodulator.ps_name_queue = ["WABC"]

    _run_identify(receiver, redis_client, cancel_event, [99_500_000.0])

    assert "rx-test" not in svc._state.active_bandscans


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
