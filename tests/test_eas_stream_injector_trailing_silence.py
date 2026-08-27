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

"""Regression test: inject_eas_audio() must leave a silence gap before the
gate is released and live program audio can resume.

Before this fix, the gate was cleared in the same statement immediately
after the last EAS chunk was queued, so the capture loop's very next
iteration could publish live program audio -- listeners heard the EOM tone
cut directly into music/talk with no break at all.
"""

import struct
import wave
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest

from app_core.audio import eas_stream_injector

pytestmark = pytest.mark.unit


def _make_wav_bytes(duration_s: float, sample_rate: int = 22050) -> bytes:
    n_samples = int(duration_s * sample_rate)
    buf = BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        # A quiet tone, not literal silence -- distinguishes "real EAS audio"
        # chunks from the all-zero silence chunks the fix appends.
        samples = [int(8000 * ((i % 100) / 100.0 - 0.5)) for i in range(n_samples)]
        wf.writeframes(struct.pack('<%dh' % n_samples, *samples))
    return buf.getvalue()


class _NullLock:
    """A no-op context manager -- SimpleNamespace can't be `with`'d because
    dunder methods for protocols like this are looked up on the type, not
    the instance, so setting them as attributes doesn't work."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeBroadcastQueue:
    def __init__(self, events):
        self.published = []
        self._subscribers = {}
        self._events = events

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def _lock(self):
        return self

    def publish(self, chunk):
        self.published.append(np.array(chunk, copy=True))
        self._events.append('publish')


class _FakeGate:
    def __init__(self, events):
        self.set_calls = 0
        self.clear_calls = 0
        self._events = events

    def set(self):
        self.set_calls += 1
        self._events.append('set')

    def clear(self):
        self.clear_calls += 1
        self._events.append('clear')


@pytest.fixture(autouse=True)
def _register_fake_controller(monkeypatch):
    events = []
    queue = _FakeBroadcastQueue(events)
    gate = _FakeGate(events)
    adapter = SimpleNamespace(
        _source_broadcast=queue,
        config=SimpleNamespace(sample_rate=22050),
        _eas_inject_seq=0,
        _eas_injection_active=gate,
    )
    controller = SimpleNamespace(
        _lock=_NullLock(),
        _sources={'test-source': adapter},
    )
    eas_stream_injector.set_controller(controller)
    yield SimpleNamespace(queue=queue, gate=gate, adapter=adapter, events=events)
    eas_stream_injector.set_controller(None)


def test_trailing_silence_is_published_after_the_alert_audio(_register_fake_controller):
    fixture = _register_fake_controller
    wav_bytes = _make_wav_bytes(duration_s=0.5, sample_rate=22050)

    result = eas_stream_injector.inject_eas_audio(wav_bytes)

    assert result is True
    sample_rate = 22050
    chunk_size = int(sample_rate * 0.05)
    n_alert_samples = int(0.5 * sample_rate)
    n_silence_samples = int(eas_stream_injector.POST_EAS_SILENCE_SECONDS * sample_rate)
    # Mirror the production code's own chunking (a final partial chunk still
    # counts as one publish() call) rather than assuming exact divisibility.
    expected_alert_chunks = len(range(0, n_alert_samples, chunk_size))
    expected_silence_chunks = len(range(0, n_silence_samples, chunk_size))

    published = fixture.queue.published
    assert len(published) == expected_alert_chunks + expected_silence_chunks

    # The tail chunks must be genuine silence (all zeros), not a repeat of
    # the alert's audio.
    tail = published[expected_alert_chunks:]
    assert len(tail) == expected_silence_chunks
    for chunk in tail:
        assert np.all(chunk == 0)

    # And the head chunks must NOT be all zero (the synthetic tone), so this
    # test would actually fail if the split point were wrong.
    head = published[:expected_alert_chunks]
    assert any(np.any(chunk != 0) for chunk in head)


def test_gate_is_not_cleared_until_after_the_silence_is_queued(_register_fake_controller):
    fixture = _register_fake_controller
    wav_bytes = _make_wav_bytes(duration_s=0.2, sample_rate=22050)

    eas_stream_injector.inject_eas_audio(wav_bytes)

    assert fixture.gate.set_calls == 1
    assert fixture.gate.clear_calls == 1
    # 'clear' must be the very last event recorded, after every publish()
    # call -- including the trailing silence -- not immediately after the
    # last alert-audio chunk.
    assert fixture.events[0] == 'set'
    assert fixture.events[-1] == 'clear'
    assert fixture.events.count('publish') > 4  # alert audio + silence chunks
    assert fixture.events.count('clear') == 1
