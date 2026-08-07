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

from __future__ import annotations

"""No audio-ingest endpoint may return a stored credential.

Before this file existed, ``GET /api/audio/sources`` served the stored stream
password in cleartext on both of its non-adapter branches, and *every* endpoint
that emitted ``device_params`` served the stored ``Authorization`` header —
including the detail endpoint, whose redaction only ever covered
``auth_password``. Both bugs predate the package split; both are fixed by
routing ``device_params`` through a single redaction boundary.

The central test here is deliberately blunt: plant a known secret, hit every
endpoint, and assert the secret is nowhere in the response bytes. That catches
a new serializer that forgets to redact, which is the failure mode a
call-site-by-call-site approach keeps reproducing.
"""

import logging
import sys
from pathlib import Path

import pytest
from flask import Blueprint, Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.extensions import db
from app_core.models import AudioSourceConfigDB, AudioSourceMetrics
from webapp.admin import audio_ingest as audio_admin
from webapp.admin.audio_ingest import controller as controller_mod
from webapp.admin.audio_ingest import listing as listing_mod
from webapp.admin.audio_ingest import serialization as serialization_mod
from webapp.admin.audio_ingest import streaming as streaming_mod
from webapp.admin.audio_ingest.sanitize import (
    SECRET_DEVICE_PARAM_KEYS,
    _redact_device_params,
)

STREAM_PASSWORD = 'PW-SECRET-VALUE-must-not-leak'
AUTH_HEADER = 'Bearer HDR-SECRET-VALUE-must-not-leak'

SECRETS = {
    'auth_password': STREAM_PASSWORD,
    'auth_header': AUTH_HEADER,
}


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover - sqlalchemy hook
    return "TEXT"


class _StubController:
    def __init__(self):
        self._sources = {}

    def add_source(self, adapter):
        self._sources[adapter.config.name] = adapter

    def start_source(self, name):
        return True


@pytest.fixture(autouse=True)
def _quiet_audio_globals(monkeypatch):
    monkeypatch.setattr(controller_mod, "_initialization_started", True)
    monkeypatch.setattr(controller_mod, "_start_audio_sources_background", lambda app: None)
    monkeypatch.setattr(streaming_mod, "_auto_streaming_service", None)


@pytest.fixture
def secret_app(tmp_path: Path, monkeypatch):
    """An app holding one source whose device_params carry both secrets."""
    app = Flask("audio-credential-redaction-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'redaction.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        CACHE_TYPE="NullCache",
        # The permission decorator flashes a message when it bounces an
        # unauthenticated caller to login, and flashing needs a session.
        SECRET_KEY="audio-credential-redaction-test-key",
    )
    db.init_app(app)

    from app_core.cache import cache
    cache.init_app(app)

    with app.app_context():
        AudioSourceConfigDB.__table__.create(bind=db.engine)
        AudioSourceMetrics.__table__.create(bind=db.engine)
        audio_admin.register_audio_ingest_routes(app, logging.getLogger("redaction-test"))

        # The permission decorator bounces unauthenticated callers to
        # url_for('auth.login'); this bare app has no auth blueprint, so give it
        # just that endpoint rather than weakening the assertion.
        auth_bp = Blueprint('auth', __name__)
        auth_bp.add_url_rule('/login', 'login', lambda: 'login', methods=['GET'])
        app.register_blueprint(auth_bp)

        controller = _StubController()
        for module in (listing_mod, serialization_mod):
            monkeypatch.setattr(module, "_get_audio_controller", lambda c=controller: c)

        db.session.add(AudioSourceConfigDB(
            name='secret-src',
            source_type='stream',
            enabled=True,
            auto_start=False,
            priority=5,
            description='',
            config_params={'device_params': {
                'url': 'http://stream.invalid/mount',
                'auth_username': 'operator',
                'auth_password': STREAM_PASSWORD,
                'auth_header': AUTH_HEADER,
            }},
        ))
        db.session.commit()

        yield app

        db.session.remove()
        AudioSourceMetrics.__table__.drop(bind=db.engine)
        AudioSourceConfigDB.__table__.drop(bind=db.engine)


# The Redis snapshot shape that drives the "separated architecture" branch.
_REDIS_RUNNING = {'audio_controller': {'sources': {'secret-src': {'status': 'running'}}}}

ENDPOINTS = [
    ('/api/audio/sources', None),           # db-only branch
    ('/api/audio/sources', _REDIS_RUNNING),  # redis branch
    ('/api/audio/sources/secret-src', None),
    ('/api/audio/sources/secret-src', _REDIS_RUNNING),
    ('/api/audio/metrics', None),
    ('/api/audio/metrics/latest', None),
    ('/api/audio/health/dashboard', None),
]


@pytest.mark.unit
@pytest.mark.parametrize('path,redis_payload', ENDPOINTS)
def test_no_endpoint_returns_a_stored_credential(secret_app, monkeypatch, path, redis_payload):
    """The blunt instrument: the secret must not appear in the response bytes."""
    for module in (listing_mod, serialization_mod, controller_mod):
        monkeypatch.setattr(
            module, "_read_audio_metrics_from_redis", lambda r=redis_payload: r, raising=False
        )

    with secret_app.app_context():
        response = secret_app.test_client().get(path)
        body = response.get_data(as_text=True)

    leaked = [name for name, value in SECRETS.items() if value in body]
    assert not leaked, f'{path} leaked {leaked} (redis={redis_payload is not None})'


@pytest.mark.unit
def test_list_endpoint_reports_presence_without_the_value(secret_app, monkeypatch):
    """Redaction must not simply delete the field — the UI needs the flag."""
    for module in (listing_mod, serialization_mod, controller_mod):
        monkeypatch.setattr(
            module, "_read_audio_metrics_from_redis", lambda: None, raising=False
        )

    with secret_app.app_context():
        payload = secret_app.test_client().get('/api/audio/sources').get_json()

    device_params = payload['sources'][0]['config']['device_params']
    assert device_params['auth_password_set'] is True
    assert device_params['auth_header_set'] is True
    # A username is not a credential, and the edit form repopulates from it.
    assert device_params['auth_username'] == 'operator'
    assert device_params['url'] == 'http://stream.invalid/mount'


@pytest.mark.unit
@pytest.mark.parametrize('key', SECRET_DEVICE_PARAM_KEYS)
def test_every_declared_secret_is_actually_redacted(key):
    """Adding a name to SECRET_DEVICE_PARAM_KEYS must be enough to protect it."""
    redacted = _redact_device_params({'url': 'http://x/y', key: 'the-secret'})
    assert key not in redacted
    assert redacted[f'{key}_set'] is True
    assert redacted['url'] == 'http://x/y'


@pytest.mark.unit
def test_absent_secret_produces_no_flag():
    """No stored credential means no key at all, not ``*_set: False``."""
    redacted = _redact_device_params({'url': 'http://x/y'})
    for key in SECRET_DEVICE_PARAM_KEYS:
        assert key not in redacted
        assert f'{key}_set' not in redacted


@pytest.mark.unit
def test_empty_secret_reports_not_set():
    """A stored-but-empty credential is not a credential."""
    redacted = _redact_device_params({'auth_password': '', 'auth_header': ''})
    assert redacted['auth_password_set'] is False
    assert redacted['auth_header_set'] is False


@pytest.mark.unit
def test_restore_does_not_copy_secrets_into_adapter_metadata(secret_app, monkeypatch):
    """The metadata channel leaked even where device_params itself was redacted.

    ``_restore_audio_source_from_db_config`` folds every ``device_params`` key
    into ``adapter.metrics.metadata``, which the detail endpoint serializes. That
    is how ``auth_header`` reached the API on the adapter path.
    """
    from app_core.audio.ingest import AudioSourceConfig, AudioSourceType

    created = {}

    def _fake_create(runtime_config: AudioSourceConfig):
        from types import SimpleNamespace
        adapter = SimpleNamespace(
            config=runtime_config,
            status=SimpleNamespace(value='stopped'),
            error_message=None,
            metrics=SimpleNamespace(metadata={'pre': 'existing'}),
        )
        created['adapter'] = adapter
        return adapter

    monkeypatch.setattr(serialization_mod, 'create_audio_source', _fake_create)

    with secret_app.app_context():
        db_config = AudioSourceConfigDB.query.filter_by(name='secret-src').first()
        controller = _StubController()
        serialization_mod._restore_audio_source_from_db_config(controller, db_config)

    metadata = created['adapter'].metrics.metadata
    assert metadata['pre'] == 'existing'
    for name, value in SECRETS.items():
        assert value not in metadata.values(), f'{name} reached adapter metadata'
    assert metadata['auth_password_set'] is True
    assert metadata['auth_header_set'] is True
    # The adapter still receives the real credentials — it needs them to connect.
    assert created['adapter'].config.device_params['auth_password'] == STREAM_PASSWORD
    assert AudioSourceType  # imported for the config type used above


@pytest.mark.unit
def test_icecast_config_read_requires_permission(secret_app):
    """The GET writes nothing but exposes the same settings as the POST."""
    with secret_app.app_context():
        response = secret_app.test_client().get('/api/audio/icecast/config')

    # Unauthenticated callers are bounced to login rather than served the config.
    assert response.status_code in (301, 302, 401, 403), (
        f'Icecast config GET answered {response.status_code} without authentication'
    )


@pytest.mark.unit
def test_icecast_config_response_carries_no_cleartext_credentials():
    """The payload shape itself must not have a slot for the secrets."""
    source = Path('webapp/admin/audio_ingest/routes_icecast.py').read_text()

    # The request side legitimately reads data['password']; the response side
    # must only ever emit the boolean flags.
    assert "'password_set': bool(" in source
    assert "'admin_password_set': bool(" in source
    assert "'password': settings.source_password" not in source
    assert "'admin_password': settings.admin_password" not in source
    assert "'password': password," not in source
