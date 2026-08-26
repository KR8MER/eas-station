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

"""Regression tests for injecting a manually-sent EAS activation into the air-chain.

A user manually sent a Required Weekly Test via webapp/eas/workflow.py's
"Send" button and reported hearing nothing on any Icecast stream.
Investigation found manual Send (unlike live auto-forward and resend) never
called into the Icecast injection path at all -- it only played audio
locally via the configured ``audio_player_cmd`` (e.g. ``aplay``) and keyed
GPIO. Unlike resend (which replays a stored ``EASMessage`` row referenced
by id), manual Send persists a ``ManualEASActivation`` with no ``EASMessage``
row to reference, so it can't reuse ``inject_eas_audio(message_id=...)`` --
it has the composite WAV bytes in hand instead. ``inject_raw_eas_audio`` is
the sibling command that takes those bytes directly (base64-in-JSON, same
pattern ``abort_injected_audio`` already uses for its EOM burst).

These tests mirror tests/test_eas_resend_injection.py's structure for the
message-id-based inject_eas_audio command.
"""

import base64
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


def test_publisher_base64_encodes_audio_and_waits(publisher, monkeypatch):
    captured = {}

    def _fake_publish_command(command, params, wait_for_response=False, timeout=5.0):
        captured.update(
            command=command, params=params,
            wait_for_response=wait_for_response, timeout=timeout,
        )
        return {'success': True, 'message': 'ok', 'data': {'injected': True}}

    monkeypatch.setattr(publisher.pub, '_publish_command', _fake_publish_command)

    resp = publisher.pub.inject_raw_eas_audio(b'RIFFfakewav')

    assert resp['success'] is True
    assert captured['command'] == 'inject_raw_eas_audio'
    assert captured['params'] == {
        'audio_b64': base64.b64encode(b'RIFFfakewav').decode('ascii')
    }
    # Must wait so the caller (manual Send) knows whether Icecast listeners
    # actually received the audio before reporting success to the operator.
    assert captured['wait_for_response'] is True


def _make_subscriber(monkeypatch, *, app=None):
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
    sub.app = app
    sub.archiver_registry = {}
    sub.redis_client = stub
    return sub


def _install_fake_injector(monkeypatch, *, result, calls):
    import sys
    import types

    fake_injector = types.ModuleType('app_core.audio.eas_stream_injector')

    def _inject(wav_bytes):
        calls.append(wav_bytes)
        return result

    fake_injector.inject_eas_audio = _inject
    monkeypatch.setitem(sys.modules, 'app_core.audio.eas_stream_injector', fake_injector)


def test_inject_raw_command_decodes_and_injects(monkeypatch):
    sub = _make_subscriber(monkeypatch)
    calls = []
    _install_fake_injector(monkeypatch, result=True, calls=calls)

    payload = base64.b64encode(b'RIFFfakewav').decode('ascii')
    result = sub._execute_command('inject_raw_eas_audio', {'audio_b64': payload})

    assert result['success'] is True
    assert result['data']['injected'] is True
    assert calls == [b'RIFFfakewav']


def test_inject_raw_command_reports_no_source_queues(monkeypatch):
    sub = _make_subscriber(monkeypatch)
    _install_fake_injector(monkeypatch, result=False, calls=[])

    payload = base64.b64encode(b'RIFFfakewav').decode('ascii')
    result = sub._execute_command('inject_raw_eas_audio', {'audio_b64': payload})

    assert result['success'] is False
    assert result['data']['injected'] is False


def test_inject_raw_command_requires_audio_b64(monkeypatch):
    sub = _make_subscriber(monkeypatch)

    result = sub._execute_command('inject_raw_eas_audio', {})

    assert result['success'] is False
    assert 'audio_b64 is required' in result['message']


def test_inject_raw_command_rejects_invalid_base64(monkeypatch):
    sub = _make_subscriber(monkeypatch)

    result = sub._execute_command('inject_raw_eas_audio', {'audio_b64': 'not-valid-base64!!!'})

    assert result['success'] is False
    assert 'Invalid audio_b64' in result['message']


def test_inject_raw_command_rejects_empty_decoded_audio(monkeypatch):
    sub = _make_subscriber(monkeypatch)

    # Valid base64 that decodes to zero bytes.
    result = sub._execute_command('inject_raw_eas_audio', {'audio_b64': ''})

    assert result['success'] is False
    assert 'audio_b64 is required' in result['message']
