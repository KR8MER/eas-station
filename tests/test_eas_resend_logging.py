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

"""Regression tests for scripts/resend_eas_broadcast.py's audit/log coverage.

A resend replays an *existing* EASMessage row rather than inserting a new
one, so the SQLAlchemy after_insert listener that normally fires the
EAS_BROADCAST audit-ledger entry for a fresh transmission (see
app_core/auth/audit_listeners.py) never runs for a resend. Before this fix
the only record of a resend was a plain SystemLog row written at the very
end of _run() -- and even that vanished with zero trace if anything raised
earlier, since this detached process's stdout/stderr are redirected to
DEVNULL by the Flask route that launches it (webapp/eas/messages.py).

Separately, the script resolved its local audio player command through an
'AUDIO_PLAYER_CMD' app.config/env key that nothing else in the codebase
ever sets -- every other broadcast path (manual Send, RWT, live/forwarded)
reads 'audio_player_cmd' from load_eas_config() (EAS_AUDIO_PLAYER env var or
the EASSettings.audio_player DB column). That mismatch silently meant a
resend never actually played locally and never published a PID for the
"Hold to Abort Broadcast" button to find.

These tests pin down both fixes.
"""

import logging
import sys
import types
from types import SimpleNamespace

import pytest

import app_utils.eas as eas_module
import scripts.resend_eas_broadcast as resend_module


class _AppContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeApp:
    root_path = '/tmp'
    logger = logging.getLogger('test_eas_resend_logging')

    def app_context(self):
        return _AppContext()


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeSystemLog:
    """Records its constructor kwargs instead of touching a real table."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _install_stub_modules(monkeypatch, *, message):
    fake_app_module = types.ModuleType('app')
    fake_app_module.app = _FakeApp()
    fake_app_module.db = SimpleNamespace(session=_FakeSession())
    fake_app_module.EASMessage = SimpleNamespace(query=SimpleNamespace(get=lambda mid: message))
    monkeypatch.setitem(sys.modules, 'app', fake_app_module)

    fake_models = types.ModuleType('app_core.models')
    fake_models.SystemLog = _FakeSystemLog
    monkeypatch.setitem(sys.modules, 'app_core.models', fake_models)

    audit_calls = []

    class _FakeAuditAction:
        EAS_BROADCAST = 'eas.broadcast'

    class _FakeAuditLogger:
        @staticmethod
        def log(**kwargs):
            audit_calls.append(kwargs)

    fake_audit = types.ModuleType('app_core.auth.audit')
    fake_audit.AuditAction = _FakeAuditAction
    fake_audit.AuditLogger = _FakeAuditLogger
    monkeypatch.setitem(sys.modules, 'app_core.auth.audit', fake_audit)

    fake_redis_commands = types.ModuleType('app_core.audio.redis_commands')
    fake_redis_commands.get_audio_command_publisher = lambda: SimpleNamespace(
        inject_eas_audio=lambda message_id, timeout=10.0: {
            'success': False, 'message': 'no active sources',
        },
    )
    monkeypatch.setitem(sys.modules, 'app_core.audio.redis_commands', fake_redis_commands)

    return SimpleNamespace(db=fake_app_module.db, audit_calls=audit_calls)


@pytest.fixture
def message():
    return SimpleNamespace(
        id=194,
        audio_data=b'RIFFfakewavdata',
        eom_audio_data=None,
        same_audio_data=None,
        metadata_payload={'event_code': 'RWT', 'playback_duration_seconds': 0.01},
    )


def test_resend_resolves_audio_player_cmd_via_load_eas_config(monkeypatch, message):
    """The dead 'AUDIO_PLAYER_CMD' lookup must be gone -- this must call the
    same load_eas_config() every other broadcast path uses."""
    stubs = _install_stub_modules(monkeypatch, message=message)
    monkeypatch.setattr(eas_module, 'set_broadcast_active', lambda **kw: True)
    monkeypatch.setattr(eas_module, 'clear_broadcast_active', lambda **kw: None)

    load_calls = []

    def _fake_load_eas_config(base_path):
        load_calls.append(base_path)
        return {'audio_player_cmd': ['aplay']}

    monkeypatch.setattr(eas_module, 'load_eas_config', _fake_load_eas_config)

    played = []
    monkeypatch.setattr(
        eas_module, 'play_broadcast_audio',
        lambda command, **kw: played.append(command),
    )

    rc = resend_module._run(194, 'kr8mer')

    assert rc == 0
    assert load_calls == ['/tmp']
    assert played, 'expected play_broadcast_audio() to be called with the configured player'
    assert played[0][0] == 'aplay'
    assert played[0][-1].endswith('.wav')


def test_resend_writes_audit_log_entry_on_success(monkeypatch, message):
    stubs = _install_stub_modules(monkeypatch, message=message)
    monkeypatch.setattr(eas_module, 'set_broadcast_active', lambda **kw: True)
    monkeypatch.setattr(eas_module, 'clear_broadcast_active', lambda **kw: None)
    monkeypatch.setattr(eas_module, 'load_eas_config', lambda base_path: {'audio_player_cmd': None})

    rc = resend_module._run(194, 'kr8mer')

    assert rc == 0
    assert len(stubs.audit_calls) == 1
    call = stubs.audit_calls[0]
    assert call['action'] == 'eas.broadcast'
    assert call['success'] is True
    assert call['username'] == 'kr8mer'
    assert call['resource_type'] == 'eas_message'
    assert call['resource_id'] == '194'
    assert call['details']['resend'] is True

    # The plain operational SystemLog row must still be written too.
    assert len(stubs.db.session.added) == 1
    assert stubs.db.session.added[0].kwargs['level'] == 'INFO'


def test_resend_writes_failure_audit_entry_when_playout_raises(monkeypatch, message):
    """An exception during playout must not vanish silently -- both the
    SystemLog row and the audit entry must record the failure, and _run()
    must return a non-zero code rather than looking like a success."""
    stubs = _install_stub_modules(monkeypatch, message=message)

    def _raise(**kw):
        raise RuntimeError('redis unavailable')

    monkeypatch.setattr(eas_module, 'set_broadcast_active', _raise)
    monkeypatch.setattr(eas_module, 'clear_broadcast_active', lambda **kw: None)
    monkeypatch.setattr(eas_module, 'load_eas_config', lambda base_path: {'audio_player_cmd': None})

    rc = resend_module._run(194, 'kr8mer')

    assert rc == 1
    assert len(stubs.audit_calls) == 1
    call = stubs.audit_calls[0]
    assert call['success'] is False
    assert 'redis unavailable' in call['details']['error']

    assert len(stubs.db.session.added) == 1
    system_log = stubs.db.session.added[0]
    assert system_log.kwargs['level'] == 'ERROR'
    assert 'redis unavailable' in system_log.kwargs['details']['error']
