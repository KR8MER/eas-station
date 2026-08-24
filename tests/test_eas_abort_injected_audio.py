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

"""Regression tests for aborting audio already injected into the live
Icecast air-chain.

"Hold to Abort Broadcast" (the web button and the physical GPIO Dump/Abort
input) used to only know how to SIGTERM/SIGKILL a local playback subprocess.
inject_eas_audio() pushes a broadcast's audio chunks into each source's
BroadcastQueue up front -- a completely separate pipeline the local kill
never touched -- so on a station with no local player configured at all
(Icecast-only, a real supported deployment mode) there was never a PID to
find, and the abort button was a no-op: the alert kept streaming to
listeners regardless of how long the button was held.

These tests pin down abort_injected_audio() (the BroadcastQueue-purge
itself) and the new 'abort_injected_audio' Redis command that lets
abort_current_broadcast() reach it from the web/GPIO process.
"""

import sys
import threading
import types
from types import SimpleNamespace

import numpy as np
import pytest

from app_core.audio import eas_stream_injector
from app_core.audio.broadcast_queue import BroadcastQueue
import app_core.audio.redis_commands as redis_commands


@pytest.fixture(autouse=True)
def _reset_controller():
    eas_stream_injector.set_controller(None)
    yield
    eas_stream_injector.set_controller(None)


def _adapter(broadcast_queue=None):
    return SimpleNamespace(
        _source_broadcast=broadcast_queue or BroadcastQueue(max_queue_size=10),
        config=SimpleNamespace(sample_rate=8000),
        _eas_inject_seq=0,
        _eas_injection_active=threading.Event(),
    )


def _controller(sources):
    return SimpleNamespace(_lock=threading.Lock(), _sources=sources)


# ---------------------------------------------------------------------------
# eas_stream_injector.abort_injected_audio()
# ---------------------------------------------------------------------------

def test_abort_injected_audio_returns_zero_without_a_controller():
    assert eas_stream_injector.abort_injected_audio() == 0


def test_abort_injected_audio_clears_every_subscriber_queue():
    bq = BroadcastQueue(max_queue_size=10)
    icecast_q = bq.subscribe('icecast')
    monitor_q = bq.subscribe('eas_monitor')
    for _ in range(5):
        bq.publish(np.zeros(10, dtype=np.float32))
    assert icecast_q.qsize() == 5
    assert monitor_q.qsize() == 5

    eas_stream_injector.set_controller(_controller({'source1': _adapter(bq)}))

    cleared = eas_stream_injector.abort_injected_audio()

    assert cleared == 10  # 5 chunks x 2 subscribers
    assert icecast_q.qsize() == 0
    assert monitor_q.qsize() == 0


def test_abort_injected_audio_releases_the_injection_gate():
    bq = BroadcastQueue(max_queue_size=10)
    bq.subscribe('icecast')
    adapter = _adapter(bq)
    adapter._eas_injection_active.set()
    eas_stream_injector.set_controller(_controller({'source1': adapter}))

    eas_stream_injector.abort_injected_audio()

    assert not adapter._eas_injection_active.is_set()


def test_abort_injected_audio_injects_the_replacement_wav(monkeypatch):
    bq = BroadcastQueue(max_queue_size=10)
    bq.subscribe('icecast')
    eas_stream_injector.set_controller(_controller({'source1': _adapter(bq)}))

    injected = []
    monkeypatch.setattr(
        eas_stream_injector, 'inject_eas_audio',
        lambda wav: injected.append(wav) or True,
    )

    eas_stream_injector.abort_injected_audio(replacement_wav=b'EOMBYTES')

    assert injected == [b'EOMBYTES']


def test_abort_injected_audio_skips_injection_without_a_replacement(monkeypatch):
    bq = BroadcastQueue(max_queue_size=10)
    bq.subscribe('icecast')
    eas_stream_injector.set_controller(_controller({'source1': _adapter(bq)}))

    injected = []
    monkeypatch.setattr(
        eas_stream_injector, 'inject_eas_audio',
        lambda wav: injected.append(wav) or True,
    )

    eas_stream_injector.abort_injected_audio()

    assert injected == []


# ---------------------------------------------------------------------------
# AudioCommandPublisher.abort_injected_audio()
# ---------------------------------------------------------------------------

class _StubRedis:
    def __init__(self):
        self.published = []

    def ping(self):
        return True

    def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1


@pytest.fixture
def publisher(monkeypatch):
    stub = _StubRedis()
    monkeypatch.setattr(redis_commands, 'get_redis_client', lambda *a, **k: stub)
    return SimpleNamespace(pub=redis_commands.AudioCommandPublisher(), redis=stub)


def test_publisher_sends_no_params_when_no_eom_given(publisher, monkeypatch):
    captured = {}

    def _fake_publish_command(command, params, wait_for_response=False, timeout=5.0):
        captured.update(command=command, params=params)
        return {'success': True, 'message': 'ok', 'data': {'cleared': 0}}

    monkeypatch.setattr(publisher.pub, '_publish_command', _fake_publish_command)

    resp = publisher.pub.abort_injected_audio()

    assert resp['success'] is True
    assert captured['command'] == 'abort_injected_audio'
    assert captured['params'] == {}


def test_publisher_base64_encodes_eom_wav(publisher, monkeypatch):
    import base64

    captured = {}
    monkeypatch.setattr(
        publisher.pub, '_publish_command',
        lambda command, params, wait_for_response=False, timeout=5.0: captured.update(params=params) or {'success': True},
    )

    publisher.pub.abort_injected_audio(eom_wav=b'EOMBYTES')

    assert captured['params']['eom_wav_b64'] == base64.b64encode(b'EOMBYTES').decode('ascii')


# ---------------------------------------------------------------------------
# AudioCommandSubscriber._execute_command('abort_injected_audio', ...)
# ---------------------------------------------------------------------------

def _make_subscriber(monkeypatch):
    stub = _StubRedis()
    stub.pubsub = lambda: SimpleNamespace()
    monkeypatch.setattr(redis_commands, 'get_redis_client', lambda *a, **k: stub)
    monkeypatch.setattr(
        redis_commands.AudioCommandSubscriber, '_check_connection', lambda self: None
    )
    sub = redis_commands.AudioCommandSubscriber.__new__(redis_commands.AudioCommandSubscriber)
    sub.audio_controller = SimpleNamespace()
    sub.auto_streaming_service = None
    sub.eas_monitor = None
    sub.app = None
    sub.archiver_registry = {}
    sub.redis_client = stub
    return sub


def test_dispatch_calls_abort_injected_audio_with_no_eom(monkeypatch):
    sub = _make_subscriber(monkeypatch)

    calls = []
    fake_injector = types.ModuleType('app_core.audio.eas_stream_injector')
    fake_injector.abort_injected_audio = lambda replacement_wav=None: calls.append(replacement_wav) or 7
    monkeypatch.setitem(sys.modules, 'app_core.audio.eas_stream_injector', fake_injector)

    result = sub._execute_command('abort_injected_audio', {})

    assert result['success'] is True
    assert result['data']['cleared'] == 7
    assert calls == [None]


def test_dispatch_decodes_base64_eom_and_passes_it_through(monkeypatch):
    import base64

    sub = _make_subscriber(monkeypatch)

    calls = []
    fake_injector = types.ModuleType('app_core.audio.eas_stream_injector')
    fake_injector.abort_injected_audio = lambda replacement_wav=None: calls.append(replacement_wav) or 0
    monkeypatch.setitem(sys.modules, 'app_core.audio.eas_stream_injector', fake_injector)

    result = sub._execute_command(
        'abort_injected_audio',
        {'eom_wav_b64': base64.b64encode(b'EOMBYTES').decode('ascii')},
    )

    assert result['success'] is True
    assert calls == [b'EOMBYTES']
