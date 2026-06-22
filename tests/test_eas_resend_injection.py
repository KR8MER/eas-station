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

"""Regression tests for re-injecting a resent EAS message into the air-chain.

A "Resend on Air" runs in a detached subprocess that has no
``AudioIngestController`` and therefore cannot reach the audio-service's
in-memory ``BroadcastQueue`` objects.  Before this fix it keyed GPIO and showed
the countdown overlay but never emitted audio out the air-chain, so Icecast
listeners heard silence.  The resend now asks the audio-service (over the Redis
command channel) to load the stored WAV from the database and inject it via
``eas_stream_injector.inject_eas_audio`` — exactly the path a live alert uses.

These tests pin the new ``inject_eas_audio`` Redis command: the publisher sends
the message id, and the subscriber loads the audio and injects it, reporting
whether any source queue received it.
"""

import sys
import types
from types import SimpleNamespace

import pytest

import app_core.audio.redis_commands as redis_commands


class _StubRedis:
    """Minimal Redis stand-in that records published commands."""

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
    pub = redis_commands.AudioCommandPublisher()
    return SimpleNamespace(pub=pub, redis=stub)


def test_publisher_sends_message_id_and_waits(publisher, monkeypatch):
    captured = {}

    def _fake_publish_command(command, params, wait_for_response=False, timeout=5.0):
        captured.update(
            command=command, params=params,
            wait_for_response=wait_for_response, timeout=timeout,
        )
        return {'success': True, 'message': 'ok', 'data': {'injected': True}}

    monkeypatch.setattr(publisher.pub, '_publish_command', _fake_publish_command)

    resp = publisher.pub.inject_eas_audio(194)

    assert resp['success'] is True
    assert captured['command'] == 'inject_eas_audio'
    assert captured['params'] == {'message_id': 194}
    # Must wait for the audio-service to confirm injection before the resend
    # process proceeds (so the alert is queued before it holds the air-chain).
    assert captured['wait_for_response'] is True


def _make_subscriber(monkeypatch, *, app=None):
    stub = _StubRedis()
    stub.pubsub = lambda: SimpleNamespace()
    monkeypatch.setattr(redis_commands, 'get_redis_client', lambda *a, **k: stub)
    # Avoid touching the real pubsub object during construction.
    monkeypatch.setattr(
        redis_commands.AudioCommandSubscriber, '_check_connection', lambda self: None
    )
    sub = redis_commands.AudioCommandSubscriber.__new__(redis_commands.AudioCommandSubscriber)
    sub.audio_controller = SimpleNamespace()
    sub.auto_streaming_service = None
    sub.eas_monitor = None
    sub.app = app
    sub.archiver_registry = {}
    sub.redis_client = stub
    return sub


class _AppContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeApp:
    def app_context(self):
        return _AppContext()


def _install_fake_eas_message(monkeypatch, message):
    """Make ``from app_core.models import EASMessage`` return a stub query."""
    fake_models = types.ModuleType('app_core.models')
    fake_models.EASMessage = SimpleNamespace(query=SimpleNamespace(get=lambda mid: message))
    monkeypatch.setitem(sys.modules, 'app_core.models', fake_models)


def _install_fake_injector(monkeypatch, *, result, calls):
    fake_injector = types.ModuleType('app_core.audio.eas_stream_injector')

    def _inject(wav_bytes):
        calls.append(wav_bytes)
        return result

    fake_injector.inject_eas_audio = _inject
    monkeypatch.setitem(sys.modules, 'app_core.audio.eas_stream_injector', fake_injector)


def test_inject_command_loads_audio_and_injects(monkeypatch):
    sub = _make_subscriber(monkeypatch, app=_FakeApp())
    _install_fake_eas_message(
        monkeypatch, SimpleNamespace(id=194, audio_data=b'RIFFfakewav')
    )
    calls = []
    _install_fake_injector(monkeypatch, result=True, calls=calls)

    result = sub._execute_command('inject_eas_audio', {'message_id': 194})

    assert result['success'] is True
    assert result['data']['injected'] is True
    assert calls == [b'RIFFfakewav']


def test_inject_command_reports_no_source_queues(monkeypatch):
    sub = _make_subscriber(monkeypatch, app=_FakeApp())
    _install_fake_eas_message(
        monkeypatch, SimpleNamespace(id=5, audio_data=b'RIFFfakewav')
    )
    _install_fake_injector(monkeypatch, result=False, calls=[])

    result = sub._execute_command('inject_eas_audio', {'message_id': 5})

    # No running source queues is non-fatal but must be reported so the resend
    # can log that Icecast listeners received nothing.
    assert result['success'] is False
    assert result['data']['injected'] is False


def test_inject_command_requires_message_id(monkeypatch):
    sub = _make_subscriber(monkeypatch, app=_FakeApp())

    result = sub._execute_command('inject_eas_audio', {})

    assert result['success'] is False
    assert 'message_id is required' in result['message']


def test_inject_command_handles_missing_audio(monkeypatch):
    sub = _make_subscriber(monkeypatch, app=_FakeApp())
    _install_fake_eas_message(monkeypatch, SimpleNamespace(id=7, audio_data=None))

    result = sub._execute_command('inject_eas_audio', {'message_id': 7})

    assert result['success'] is False
    assert 'no stored audio' in result['message']


def test_inject_command_without_app_is_graceful(monkeypatch):
    sub = _make_subscriber(monkeypatch, app=None)

    result = sub._execute_command('inject_eas_audio', {'message_id': 7})

    assert result['success'] is False
    assert result['data']['injected'] is False
