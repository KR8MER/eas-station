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

"""Regression test for POST /eas/manual/generate running tone synthesis
off the request greenlet.

``EASAudioGenerator.build_manual_components()`` synthesizes the SAME header
tone via pure-Python, sample-by-sample list operations -- CPU-bound work
with no I/O yield points. Under this app's gevent worker model that used to
block the entire worker process for the full synthesis duration, the same
bug already found and fixed for alert image export (see
``_run_off_worker`` in ``webapp/admin/api/routes_alert_export.py`` and
``tests/test_alert_export_off_worker.py``). This test pins down that the
manual-generate route now runs that call through the same helper.
"""

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask, g

REPO_ROOT = Path(__file__).resolve().parents[1]

import webapp.eas.workflow as workflow_module


class _FakeQueryCount:
    def count(self):
        return 1  # Skip the "creating first user" bootstrap branch.


class _FakeActivationQuery:
    def filter(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return 0


def _fake_manual_eas_activation(**kwargs):
    record = SimpleNamespace(**kwargs)
    record.id = 4242
    record.created_at = datetime.now(timezone.utc)
    return record


_fake_manual_eas_activation.query = _FakeActivationQuery()
_fake_manual_eas_activation.archived_at = SimpleNamespace(is_=lambda value: True)


class _FakeSession:
    def add(self, *args, **kwargs):
        pass

    def flush(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeGenerator:
    """Stands in for EASAudioGenerator, recording which thread synthesized
    audio instead of doing real (slow) FSK/tone work."""

    calls = []

    def __init__(self, config, logger=None, db_session=None):
        self.config = config
        self.db_session = db_session

    def build_manual_components(self, alert, header, **kwargs):
        _FakeGenerator.calls.append({
            'thread_ident': threading.current_thread().ident,
            'header': header,
            'kwargs': kwargs,
        })
        return {
            'same_samples': [1, 2, 3],
            'attention_samples': [],
            'pre_alert_samples': [],
            'tts_samples': [],
            'post_alert_samples': [],
            'eom_samples': [4, 5, 6],
            'composite_samples': [1, 2, 3, 4, 5, 6],
            'pre_chime_samples': [],
            'post_chime_samples': [],
            'eom_header': 'NNNN',
            'tone_profile': kwargs.get('tone_profile'),
            'tone_seconds': kwargs.get('tone_duration'),
            'message_text': 'Test message.',
            'tts_warning': None,
            'tts_provider': None,
            'tts_enabled': kwargs.get('include_tts', False),
            'sample_rate': 16000,
            'signaling': {},
        }


@pytest.fixture
def manual_generate_app(monkeypatch, tmp_path):
    app = Flask('eas-manual-generate-test', root_path=str(REPO_ROOT))
    app.config['EAS_OUTPUT_DIR'] = str(tmp_path)
    app.config['EAS_OUTPUT_WEB_SUBDIR'] = 'eas_messages'

    @app.before_request
    def _set_user():
        g.current_user = SimpleNamespace(username='tester')

    # manual_eas_generate() builds a stream_url via url_for('manual_eas_audio', ...),
    # a route registered elsewhere in the real app (not this blueprint) -- stub it
    # so url_for can resolve it without pulling in the rest of the application.
    @app.route('/eas/manual/audio/<int:event_id>/<component>', endpoint='manual_eas_audio')
    def _stub_audio(event_id, component):
        return ''

    blueprint = Blueprint('eas', __name__, url_prefix='/eas')
    workflow_module.register_workflow_routes(blueprint, logging.getLogger('test'), {})
    app.register_blueprint(blueprint)

    monkeypatch.setattr(workflow_module, 'AdminUser', SimpleNamespace(query=_FakeQueryCount()))
    monkeypatch.setattr(workflow_module, 'ManualEASActivation', _fake_manual_eas_activation)
    monkeypatch.setattr(workflow_module, 'db', SimpleNamespace(session=_FakeSession(), engine=None))
    monkeypatch.setattr(workflow_module, 'EASAudioGenerator', _FakeGenerator)

    _FakeGenerator.calls = []

    return SimpleNamespace(app=app, client=app.test_client())


def test_manual_generate_runs_synthesis_off_request_thread(manual_generate_app, authenticated_user):
    calling_thread_ident = threading.current_thread().ident

    resp = manual_generate_app.client.post(
        '/eas/manual/generate',
        json={
            'identifier': 'TEST-MANUAL-001',
            'event_code': 'SVR',
            'same_codes': ['039049'],
            'duration_minutes': 15,
            'tone_profile': 'attention',
            'include_tts': False,
        },
    )

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body['identifier'] == 'TEST-MANUAL-001'
    assert body['event_code'] == 'SVR'

    # The fix: build_manual_components() ran on a real OS thread from
    # gevent's threadpool, not inline on the request greenlet/thread --
    # so a slow synthesis can no longer block the whole worker process.
    assert len(_FakeGenerator.calls) == 1
    assert _FakeGenerator.calls[0]['thread_ident'] != calling_thread_ident


def test_manual_generate_still_reports_failures(manual_generate_app, authenticated_user, monkeypatch):
    def _boom(self, alert, header, **kwargs):
        raise RuntimeError('synthesis exploded')

    monkeypatch.setattr(_FakeGenerator, 'build_manual_components', _boom)

    resp = manual_generate_app.client.post(
        '/eas/manual/generate',
        json={
            'identifier': 'TEST-MANUAL-002',
            'event_code': 'SVR',
            'same_codes': ['039049'],
            'duration_minutes': 15,
            'tone_profile': 'attention',
            'include_tts': False,
        },
    )

    assert resp.status_code == 500
    assert 'error' in resp.get_json()
