"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

import logging
from pathlib import Path
from types import SimpleNamespace

import logging
from pathlib import Path

import pytest
from flask import Flask

import webapp.routes.alert_verification as alert_verification
from app_core.audio.self_test import AlertSelfTestResult, AlertSelfTestStatus


@pytest.fixture
def alert_self_test_setup(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    app = Flask(
        'alert-self-test',
        root_path=str(repo_root),
        template_folder=str(repo_root / 'templates'),
        static_folder=str(repo_root / 'static'),
    )
    app.jinja_env.filters.setdefault('shields_escape', lambda value: value)
    app.jinja_env.globals.setdefault('csrf_token', 'test-token')
    app.jinja_env.globals.setdefault('has_permission', lambda *_, **__: True)
    app.jinja_env.globals.setdefault('current_user', SimpleNamespace(is_authenticated=True))

    fake_settings = {'fips_codes': ['039137', '039051']}
    monkeypatch.setattr(alert_verification, 'get_location_settings', lambda: fake_settings)

    class DummyHarness:
        def __init__(self, configured_fips, duplicate_cooldown_seconds, source_name):
            self.configured_fips_codes = list(configured_fips)
            self.cooldown = duplicate_cooldown_seconds
            self.source_name = source_name

        def run_audio_files(self, paths):
            resolved = [Path(path) for path in paths]
            return [
                AlertSelfTestResult(
                    audio_path=str(resolved[0]),
                    status=AlertSelfTestStatus.FORWARDED,
                    reason='Matched configured FIPS: 039137',
                    event_code='RWT',
                    originator='WXR',
                    alert_fips_codes=['039137'],
                    matched_fips_codes=['039137'],
                    confidence=0.98,
                    duration_seconds=8.5,
                    raw_text='ZCZC-EAS-RWT...',
                )
            ]

    monkeypatch.setattr(alert_verification, 'AlertSelfTestHarness', DummyHarness)

    alert_verification.register(app, logging.getLogger('alert-self-test'))

    sample = tmp_path / 'lab.wav'
    sample.write_text('fake audio payload')

    with app.test_client() as client:
        yield {'client': client, 'sample_path': sample}


def test_alert_self_test_run_endpoint_returns_results(alert_self_test_setup):
    client = alert_self_test_setup['client']
    sample_path = alert_self_test_setup['sample_path']

    response = client.post(
        '/api/alert-self-test/run',
        json={
            'audio_paths': [str(sample_path)],
            'use_default_samples': False,
            'duplicate_cooldown': 15,
            'source_name': 'ui-demo',
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['forwarded_count'] == 1
    assert payload['configured_fips'] == ['039137', '039051']
    assert payload['audio_samples'][0]['path'].endswith('lab.wav')
    assert payload['source_name'] == 'ui-demo'


def test_alert_self_test_rejects_missing_audio(alert_self_test_setup):
    client = alert_self_test_setup['client']

    response = client.post(
        '/api/alert-self-test/run',
        json={'audio_paths': ['/does/not/exist.wav'], 'use_default_samples': False},
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload['success'] is False
    assert 'Audio sample not found' in payload['error']
