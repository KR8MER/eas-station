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

"""Tests for the broadcast countdown overlay's two additions:

1. Phase breakpoints (``header_seconds`` / ``eom_seconds``) published by
   ``set_broadcast_active()`` so the overlay can show Sending Header /
   Narration / Sending EOM instead of a flat countdown.
2. The web "Hold to Abort Broadcast" route (``POST /api/broadcast/abort``,
   ``webapp/routes/broadcast_control.py``) -- the browser-side equivalent of
   holding a physical GPIO Dump/Abort Broadcast input for 3 seconds.
"""

import types
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_utils.eas as eas_module


class _FakeRedis:
    """Minimal in-memory stand-in for the Redis client get/set/delete API."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)

    def publish(self, *_args, **_kwargs):
        pass


@pytest.fixture
def fake_redis(monkeypatch):
    client = _FakeRedis()
    fake_module = types.ModuleType("app_core.redis_client")
    fake_module.get_redis_client = lambda: client
    monkeypatch.setitem(sys.modules, "app_core.redis_client", fake_module)
    return client


# ---------------------------------------------------------------------------
# set_broadcast_active() phase breakpoints
# ---------------------------------------------------------------------------


def test_set_broadcast_active_stores_phase_breakpoints(fake_redis):
    eas_module.set_broadcast_active(
        event_code='RWT', label='Required Weekly Test', duration_seconds=14.4,
        source='automated_rwt', identifier='RWT-1',
        header_seconds=7.2, eom_seconds=3.2,
    )
    state = eas_module.get_broadcast_state()
    assert state['header_seconds'] == 7.2
    assert state['eom_seconds'] == 3.2


def test_set_broadcast_active_defaults_phase_breakpoints_to_zero(fake_redis):
    """Callers that don't (yet) compute phase timing must not break --
    header_seconds/eom_seconds default to 0.0, which the overlay JS treats
    as 'no phase data available' rather than a real breakpoint at t=0."""
    eas_module.set_broadcast_active(
        event_code='SVR', label='Severe Thunderstorm Warning',
        duration_seconds=45.0, source='auto', identifier='urn:test',
    )
    state = eas_module.get_broadcast_state()
    assert state['header_seconds'] == 0.0
    assert state['eom_seconds'] == 0.0


def test_set_broadcast_active_rejects_none_phase_values(fake_redis):
    """A caller passing None (not omitting the kwarg) must not crash the
    float() coercion or corrupt the stored payload."""
    eas_module.set_broadcast_active(
        event_code='RWT', label='Test', duration_seconds=10.0,
        header_seconds=None, eom_seconds=None,
    )
    state = eas_module.get_broadcast_state()
    assert state['header_seconds'] == 0.0
    assert state['eom_seconds'] == 0.0


# ---------------------------------------------------------------------------
# POST /api/broadcast/abort
# ---------------------------------------------------------------------------


@pytest.fixture
def abort_app(monkeypatch):
    app = Flask('broadcast-abort-test', root_path=str(ROOT))
    app.secret_key = 'test-secret'

    import webapp.routes.broadcast_control as broadcast_control_module
    broadcast_control_module.register(app, app.logger)

    return SimpleNamespace(
        app=app, client=app.test_client(), monkeypatch=monkeypatch,
        module=broadcast_control_module,
    )


def test_abort_route_requires_permission(abort_app):
    """No authenticated_user fixture here on purpose -- confirms the route
    is actually gated, not just assumed to be. This minimal test app has no
    'auth.login' blueprint registered, so the real app's redirect-to-login
    surfaces as a 500 (BuildError) rather than a clean 302 here -- the
    assertion only needs to confirm the request was rejected, not the exact
    status code an unrelated URL-building detail produces in this harness."""
    resp = abort_app.client.post('/api/broadcast/abort')
    assert resp.status_code != 200


def test_abort_route_409_when_nothing_active(abort_app, authenticated_user):
    abort_app.monkeypatch.setattr(
        'app_utils.eas.get_broadcast_state', lambda: {'active': False},
    )
    resp = abort_app.client.post('/api/broadcast/abort')
    assert resp.status_code == 409
    body = resp.get_json()
    assert body['success'] is False


def test_abort_route_success_calls_abort_current_broadcast(abort_app, authenticated_user):
    abort_app.monkeypatch.setattr(
        'app_utils.eas.get_broadcast_state',
        lambda: {'active': True, 'label': 'Tornado Warning'},
    )
    pid_calls = iter([4321, None])  # before-call: real PID; after-call: cleared
    abort_app.monkeypatch.setattr(
        'app_utils.eas.get_broadcast_pid', lambda: next(pid_calls),
    )

    calls = []
    abort_app.monkeypatch.setattr(
        'app_core.audio.gpio_input_actions.abort_current_broadcast',
        lambda reason=None, operator=None: calls.append({'reason': reason, 'operator': operator}),
    )

    resp = abort_app.client.post('/api/broadcast/abort')

    assert resp.status_code == 200
    assert resp.get_json() == {'success': True}
    assert len(calls) == 1
    assert calls[0]['reason'] == 'Web UI Dump/Abort button'
    # authenticated_user's stub has no username attribute -- the route reads
    # session['username'], defaulting to 'anonymous' when unset, which is the
    # scenario this stub actually exercises (no session mutation performed).
    assert calls[0]['operator'] == 'anonymous'


def test_abort_route_409_when_no_trackable_pid(abort_app, authenticated_user):
    """The state marker says 'active' but no PID was ever published for it
    (a narrow timing window right at broadcast start) -- must not report
    success for something it couldn't actually touch."""
    abort_app.monkeypatch.setattr(
        'app_utils.eas.get_broadcast_state', lambda: {'active': True, 'label': 'x'},
    )
    abort_app.monkeypatch.setattr('app_utils.eas.get_broadcast_pid', lambda: None)
    abort_app.monkeypatch.setattr(
        'app_core.audio.gpio_input_actions.abort_current_broadcast',
        lambda reason=None, operator=None: None,
    )

    resp = abort_app.client.post('/api/broadcast/abort')

    assert resp.status_code == 409
    assert resp.get_json()['success'] is False


def test_abort_route_500_when_abort_raises(abort_app, authenticated_user):
    abort_app.monkeypatch.setattr(
        'app_utils.eas.get_broadcast_state', lambda: {'active': True, 'label': 'x'},
    )
    abort_app.monkeypatch.setattr('app_utils.eas.get_broadcast_pid', lambda: 999)

    def _raise(reason=None, operator=None):
        raise RuntimeError('boom')

    abort_app.monkeypatch.setattr(
        'app_core.audio.gpio_input_actions.abort_current_broadcast', _raise,
    )

    resp = abort_app.client.post('/api/broadcast/abort')

    assert resp.status_code == 500
    assert resp.get_json()['success'] is False


def test_abort_route_uses_session_username_as_operator(abort_app, authenticated_user):
    abort_app.monkeypatch.setattr(
        'app_utils.eas.get_broadcast_state', lambda: {'active': True, 'label': 'x'},
    )
    pid_calls = iter([111, None])
    abort_app.monkeypatch.setattr(
        'app_utils.eas.get_broadcast_pid', lambda: next(pid_calls),
    )
    calls = []
    abort_app.monkeypatch.setattr(
        'app_core.audio.gpio_input_actions.abort_current_broadcast',
        lambda reason=None, operator=None: calls.append(operator),
    )

    with abort_app.client.session_transaction() as sess:
        sess['username'] = 'kr8mer'

    resp = abort_app.client.post('/api/broadcast/abort')

    assert resp.status_code == 200
    assert calls == ['kr8mer']
