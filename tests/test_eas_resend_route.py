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

"""Regression tests for the EAS message "Resend on Air" endpoint.

The resend used to run the GPIO activation, audio playout, and the full-length
hold *inline* in the gunicorn gevent worker.  That stalled the gevent hub for
the entire alert (driving ``lgpio`` from a gevent worker is unsafe) and let
gunicorn's 300 s ``--timeout`` kill the worker mid-broadcast, leaving the relay
keyed until a watchdog fired.  The endpoint now validates, guards against a
broadcast already on the air, and hands the playout to a detached subprocess —
returning ``202`` immediately.  These tests pin that contract down.
"""

import logging
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask, g

import app_utils.eas as eas_module
import webapp.eas.messages as messages_module


class _FakeQuery:
    def __init__(self, message):
        self._message = message

    def get_or_404(self, message_id):
        from werkzeug.exceptions import NotFound
        if self._message is None:
            raise NotFound()
        return self._message


@pytest.fixture
def resend_app(monkeypatch):
    app = Flask('eas-resend-test', root_path='/home/user/eas-station')

    @app.before_request
    def _set_user():
        g.current_user = SimpleNamespace(username='tester')

    blueprint = Blueprint('eas', __name__, url_prefix='/eas')
    register = messages_module.register_message_routes
    register(blueprint, logging.getLogger('test'))
    app.register_blueprint(blueprint)

    # Default: no broadcast currently on the air.
    monkeypatch.setattr(eas_module, 'get_broadcast_state', lambda: {'active': False})

    spawned = []

    def _fake_popen(command, **kwargs):
        spawned.append({'command': command, 'kwargs': kwargs})
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr('subprocess.Popen', _fake_popen)

    return SimpleNamespace(app=app, client=app.test_client(), spawned=spawned, monkeypatch=monkeypatch)


def _install_message(monkeypatch, *, audio_data=b'RIFFfake', metadata=None):
    message = SimpleNamespace(
        id=194,
        audio_data=audio_data,
        metadata_payload=metadata if metadata is not None else {'event_code': 'SVR'},
    )
    monkeypatch.setattr(messages_module, 'EASMessage', SimpleNamespace(query=_FakeQuery(message)))
    return message


def test_resend_returns_202_and_spawns_detached_worker(resend_app):
    _install_message(resend_app.monkeypatch)

    resp = resend_app.client.post('/eas/messages/194/resend')

    assert resp.status_code == 202
    body = resp.get_json()
    assert body['status'] == 'started'
    assert body['id'] == 194

    # Exactly one detached worker launched with the right script + arguments.
    assert len(resend_app.spawned) == 1
    spawn = resend_app.spawned[0]
    command = spawn['command']
    assert command[1].endswith('scripts/resend_eas_broadcast.py')
    assert '--message-id' in command and '194' in command
    assert '--operator' in command and 'tester' in command
    # Detached so it outlives the request worker.
    assert spawn['kwargs'].get('start_new_session') is True


def test_resend_blocked_when_broadcast_active(resend_app):
    _install_message(resend_app.monkeypatch)
    resend_app.monkeypatch.setattr(eas_module, 'get_broadcast_state', lambda: {'active': True})

    resp = resend_app.client.post('/eas/messages/194/resend')

    assert resp.status_code == 409
    assert 'already on the air' in resp.get_json()['error']
    # No worker should be launched while another broadcast is keyed.
    assert resend_app.spawned == []


def test_resend_requires_stored_audio(resend_app):
    _install_message(resend_app.monkeypatch, audio_data=None)

    resp = resend_app.client.post('/eas/messages/194/resend')

    assert resp.status_code == 422
    assert resend_app.spawned == []
