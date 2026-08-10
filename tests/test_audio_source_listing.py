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

"""Characterization tests for GET /api/audio/sources.

This file was written *before* ``api_get_audio_sources`` (327 lines in one
handler) was decomposed into ``webapp/admin/audio_ingest/listing.py``, and it is
the safety net that made the decomposition checkable. AST comparison is useless
for a restructure, so instead the handler is driven over a set of scenarios that
exercise every branch and the full response body is asserted.

The three serialization paths a source can take, all reachable here:

* **adapter** — an adapter is present in the local controller (integrated mode)
* **redis**   — the audio service publishes the source's state to Redis
                (separated mode, the production deployment)
* **db-only** — neither, so the row is reported from its database config alone

plus the two envelope counters and the ``audio_service_dead`` rule that turns a
db-only auto-start source from "stopped" into "error".
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.extensions import db
from app_core.models import AudioSourceConfigDB, AudioSourceMetrics
from webapp.admin import audio_ingest as audio_admin
from webapp.admin.audio_ingest import controller as audio_controller_mod
from webapp.admin.audio_ingest import streaming as audio_streaming_mod


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover - sqlalchemy hook
    return "TEXT"


@pytest.fixture(autouse=True)
def _quiet_audio_globals(monkeypatch):
    monkeypatch.setattr(audio_controller_mod, "_initialization_started", True)
    monkeypatch.setattr(audio_controller_mod, "_start_audio_sources_background", lambda app: None)
    monkeypatch.setattr(audio_streaming_mod, "_auto_streaming_service", None)


@pytest.fixture
def listing_app(tmp_path: Path):
    """A Flask app with the audio-ingest routes and an empty source table.

    ``CACHE_TYPE=NullCache`` matters: the endpoint carries
    ``@cache.cached(timeout=30, key_prefix='audio_source_list')``, and a real
    cache would serve scenario 1's body for every later scenario.
    """
    app = Flask("audio-source-listing-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'listing.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        CACHE_TYPE="NullCache",
    )
    db.init_app(app)

    from app_core.cache import cache
    cache.init_app(app)

    with app.app_context():
        AudioSourceConfigDB.__table__.create(bind=db.engine)
        AudioSourceMetrics.__table__.create(bind=db.engine)
        audio_admin.register_audio_ingest_routes(app, logging.getLogger("audio-source-listing"))
        yield app
        db.session.remove()
        AudioSourceMetrics.__table__.drop(bind=db.engine)
        AudioSourceConfigDB.__table__.drop(bind=db.engine)


def _add_source(name, *, source_type="stream", enabled=True, auto_start=False,
                priority=5, description="", config_params=None):
    row = AudioSourceConfigDB(
        name=name,
        source_type=source_type,
        enabled=enabled,
        auto_start=auto_start,
        priority=priority,
        description=description,
        config_params=config_params if config_params is not None else {},
    )
    db.session.add(row)
    db.session.commit()
    return row


def _add_metric(name, **kwargs):
    defaults = dict(
        source_name=name,
        source_type='stream',
        timestamp=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
        peak_level_db=-6.0,
        rms_level_db=-18.0,
        peak_level_linear=0.5,
        rms_level_linear=0.12,
        sample_rate=48000,
        channels=2,
        frames_captured=1234,
        silence_detected=False,
        buffer_utilization=0.25,
        source_metadata={"station": "WXYZ"},
    )
    defaults.update(kwargs)
    row = AudioSourceMetrics(**defaults)
    db.session.add(row)
    db.session.commit()
    return row


class _StubController:
    def __init__(self, sources=None):
        self._sources = sources or {}


def _stub_adapter(name, *, status="running", sample_rate=44100, channels=1):
    from app_core.audio.ingest import AudioSourceStatus, AudioSourceType

    return SimpleNamespace(
        config=SimpleNamespace(
            name=name,
            source_type=AudioSourceType.STREAM,
            enabled=True,
            priority=5,
            sample_rate=sample_rate,
            channels=channels,
            buffer_size=4096,
            silence_threshold_db=-60.0,
            silence_duration_seconds=5.0,
            device_params={"url": "http://example.invalid/stream", "auth_password": "hunter2"},
        ),
        status=AudioSourceStatus(status),
        error_message=None,
        metrics=SimpleNamespace(
            timestamp=1754481600.0,
            peak_level_db=-3.0,
            rms_level_db=-15.0,
            sample_rate=sample_rate,
            channels=channels,
            frames_captured=999,
            silence_detected=False,
            buffer_utilization=0.5,
            metadata={"live": True},
        ),
    )


def _get(listing_app):
    return listing_app.test_client().get("/api/audio/sources").get_json()


# ---------------------------------------------------------------------------
# The scenarios
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_sources_returns_empty_envelope(listing_app):
    with listing_app.app_context():
        payload = _get(listing_app)

    assert payload == {'sources': [], 'total': 0, 'active_count': 0, 'db_only_count': 0}


@pytest.mark.unit
def test_db_only_source_reports_stopped(listing_app, monkeypatch):
    """No Redis metrics, no adapter: the row is described from its config."""
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: {'audio_controller': {'sources': {}}},
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController(),
    )

    with listing_app.app_context():
        _add_source('quiet-one', config_params={'sample_rate': 22050, 'channels': 2})
        payload = _get(listing_app)

    assert payload['total'] == 1
    assert payload['active_count'] == 0
    assert payload['db_only_count'] == 1

    source = payload['sources'][0]
    assert source['id'] == 'quiet-one'
    assert source['status'] == 'stopped'
    assert source['error_message'] == 'Not started'
    assert source['in_memory'] is False
    assert source['config']['sample_rate'] == 22050
    assert source['config']['channels'] == 2
    # Untouched keys fall back to the documented defaults.
    assert source['config']['buffer_size'] == 4096
    assert source['config']['silence_threshold_db'] == -60.0


@pytest.mark.unit
def test_dead_audio_service_turns_autostart_sources_into_errors(listing_app, monkeypatch):
    """The rule that distinguishes "deliberately stopped" from "failed"."""
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: None,
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController(),
    )

    with listing_app.app_context():
        _add_source('should-be-running', auto_start=True)
        _add_source('deliberately-off', auto_start=False)
        payload = _get(listing_app)

    by_name = {s['name']: s for s in payload['sources']}
    assert by_name['should-be-running']['status'] == 'error'
    assert 'not running' in by_name['should-be-running']['error_message'].lower()
    assert by_name['deliberately-off']['status'] == 'stopped'
    assert by_name['deliberately-off']['error_message'] == 'Not started'


@pytest.mark.unit
def test_db_only_source_carries_its_latest_metric_row(listing_app, monkeypatch):
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: None,
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController(),
    )

    with listing_app.app_context():
        _add_source('has-history')
        _add_metric('has-history', timestamp=datetime(2026, 8, 6, 11, 0, 0, tzinfo=timezone.utc))
        # A second, newer row: the endpoint must pick the latest per source.
        _add_metric(
            'has-history',
            timestamp=datetime(2026, 8, 6, 12, 30, 0, tzinfo=timezone.utc),
            peak_level_db=-1.5,
        )
        payload = _get(listing_app)

    metrics = payload['sources'][0]['metrics']
    assert metrics['peak_level_db'] == -1.5
    assert metrics['sample_rate'] == 48000
    assert metrics['channels'] == 2
    assert metrics['frames_captured'] == 1234
    assert metrics['silence_detected'] is False
    assert metrics['buffer_utilization'] == 0.25
    assert metrics['metadata']['station'] == 'WXYZ'


@pytest.mark.unit
def test_redis_source_data_wins_over_the_database_metric(listing_app, monkeypatch):
    """Separated mode: live values come from Redis, history only fills gaps."""
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: {
            'audio_controller': {
                'sources': {
                    'live-source': {
                        'status': 'running',
                        'peak_level_db': -2.0,
                        'rms_level_db': -12.0,
                        'sample_rate': 32000,
                        'silence_detected': False,
                        'timestamp': 1754481600.0,
                        'metadata': {'from': 'redis'},
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController(),
    )

    with listing_app.app_context():
        _add_source('live-source')
        _add_metric('live-source')
        payload = _get(listing_app)

    source = payload['sources'][0]
    assert source['status'] == 'running'
    assert source['redis_mode'] is True
    assert source['in_memory'] is True
    assert payload['active_count'] == 1
    assert payload['db_only_count'] == 0

    metrics = source['metrics']
    assert metrics['peak_level_db'] == -2.0        # Redis
    assert metrics['rms_level_db'] == -12.0        # Redis
    assert metrics['sample_rate'] == 32000         # Redis
    assert metrics['channels'] == 2                # fell through to the DB row
    assert metrics['frames_captured'] == 1234      # fell through to the DB row
    assert metrics['metadata']['from'] == 'redis'
    assert metrics['metadata']['station'] == 'WXYZ'


@pytest.mark.unit
def test_redis_source_data_that_is_not_a_dict_is_ignored(listing_app, monkeypatch):
    """A malformed payload must not take the source down with it."""
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: {'audio_controller': {'sources': {'broken': 'not-a-dict'}}},
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController(),
    )

    with listing_app.app_context():
        _add_source('broken')
        payload = _get(listing_app)

    source = payload['sources'][0]
    # redis_source_data became {} -> falsy -> the db-only branch runs.
    assert source['status'] == 'stopped'
    assert source['in_memory'] is False


@pytest.mark.unit
def test_json_encoded_controller_blob_is_decoded(listing_app, monkeypatch):
    """The audio service may publish the controller dict as a JSON string."""
    import json

    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: {
            'audio_controller': json.dumps({
                'sources': {'encoded': {'status': 'running'}},
                'streaming': json.dumps({
                    'active_streams': {
                        'encoded': {
                            'mount': 'encoded.mp3',
                            'server': 'icecast.invalid',
                            'port': 8000,
                            'format': 'mp3',
                            'bitrate_kbps': 128,
                            'running': True,
                        }
                    }
                }),
            })
        },
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController(),
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_icecast_stream_url',
        lambda name: None,
    )

    with listing_app.app_context():
        _add_source('encoded')
        payload = _get(listing_app)

    source = payload['sources'][0]
    assert source['status'] == 'running'
    # No configured Icecast URL, so it is reconstructed from the stream stats.
    assert source['icecast_url'] == 'http://icecast.invalid:8000/encoded.mp3'
    assert source['streaming']['icecast']['mount'] == 'encoded.mp3'
    assert source['streaming']['icecast']['bitrate_kbps'] == 128.0
    assert source['streaming']['icecast']['running'] is True


@pytest.mark.unit
def test_local_adapter_is_serialized_when_present(listing_app, monkeypatch):
    """Integrated mode: an adapter in the controller takes priority."""
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: None,
    )
    adapter = _stub_adapter('local-one')
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController({'local-one': adapter}),
    )

    with listing_app.app_context():
        _add_source('local-one')
        payload = _get(listing_app)

    source = payload['sources'][0]
    assert source['status'] == 'running'
    assert payload['active_count'] == 1
    # in_memory is absent on the adapter payload, and db_only_count treats a
    # missing key as in-memory.
    assert payload['db_only_count'] == 0
    assert source['metrics']['peak_level_db'] == -3.0
    # The stored credential never reaches the API; only the fact one exists.
    assert 'auth_password' not in source['config']['device_params']
    assert source['config']['device_params']['auth_password_set'] is True


@pytest.mark.unit
def test_mixed_deployment_counts_are_correct(listing_app, monkeypatch):
    """One of each path in a single response — the envelope has to add up."""
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: {
            'audio_controller': {
                'sources': {'from-redis': {'status': 'running'}},
            }
        },
    )
    adapter = _stub_adapter('from-adapter')
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController({'from-adapter': adapter}),
    )

    with listing_app.app_context():
        _add_source('from-redis')
        _add_source('from-adapter')
        _add_source('from-db-only')
        payload = _get(listing_app)

    by_name = {s['name']: s for s in payload['sources']}
    assert payload['total'] == 3
    assert payload['active_count'] == 2
    assert payload['db_only_count'] == 1
    assert by_name['from-redis'].get('redis_mode') is True
    assert by_name['from-adapter'].get('redis_mode') is None
    assert by_name['from-db-only']['in_memory'] is False


@pytest.mark.unit
def test_icecast_status_from_the_local_service_wins_over_redis(listing_app, monkeypatch):
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: {
            'audio_controller': {
                'sources': {'streamed': {'status': 'running'}},
                'streaming': {'active_streams': {'streamed': {'mount': 'from-redis.mp3'}}},
            }
        },
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController(),
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_auto_streaming_service',
        lambda: SimpleNamespace(get_status=lambda: {
            'active_streams': {'streamed': {'mount': 'from-service.mp3', 'running': True}}
        }),
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_icecast_stream_url',
        lambda name: f'http://icecast.invalid:8000/{name}',
    )

    with listing_app.app_context():
        _add_source('streamed')
        payload = _get(listing_app)

    assert payload['sources'][0]['streaming']['icecast']['mount'] == 'from-service.mp3'


@pytest.mark.unit
def test_a_failing_streaming_service_does_not_fail_the_request(listing_app, monkeypatch):
    def _explode():
        raise RuntimeError('icecast is on fire')

    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: None,
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController(),
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_auto_streaming_service',
        lambda: SimpleNamespace(get_status=_explode),
    )

    with listing_app.app_context():
        _add_source('resilient')
        payload = _get(listing_app)

    assert payload['total'] == 1
    assert payload['sources'][0]['streaming'] is None


@pytest.mark.unit
def test_an_unexpected_failure_becomes_a_500(listing_app, monkeypatch):
    def _explode():
        raise RuntimeError('controller unavailable')

    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: None,
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        _explode,
    )

    with listing_app.app_context():
        _add_source('doomed')
        response = listing_app.test_client().get('/api/audio/sources')

    assert response.status_code == 500
    assert 'controller unavailable' in response.get_json()['error']


# ---------------------------------------------------------------------------
# The placeholder-adapter masking regression
#
# In the separated deployment the web process builds an adapter for every
# database row but never starts one, so every adapter permanently reports
# STOPPED.  Preferring those over the ``service_dead`` signal made a dead audio
# service render as three deliberately-stopped sources, and made
# ``_serialize_db_only``'s "failed to start" branch unreachable in production —
# the tests above only reach it because they stub the controller empty.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dead_service_ignores_never_started_placeholder_adapters(listing_app, monkeypatch):
    """A stopped local adapter must not mask a dead audio service."""
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: None,
    )
    # The production shape: the controller holds a placeholder adapter for
    # every configured source, all of them STOPPED because the web process
    # deliberately never starts them.
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController({
            'should-be-running': _stub_adapter('should-be-running', status='stopped'),
            'deliberately-off': _stub_adapter('deliberately-off', status='stopped'),
        }),
    )

    with listing_app.app_context():
        _add_source('should-be-running', auto_start=True)
        _add_source('deliberately-off', auto_start=False)
        payload = _get(listing_app)

    by_name = {s['name']: s for s in payload['sources']}

    # The auto-start source is a failure, not a choice, and must say so.
    assert by_name['should-be-running']['status'] == 'error'
    assert 'not running' in by_name['should-be-running']['error_message'].lower()
    assert by_name['should-be-running']['in_memory'] is False

    # A source that was never meant to run still reads as stopped.
    assert by_name['deliberately-off']['status'] == 'stopped'
    assert by_name['deliberately-off']['error_message'] == 'Not started'

    assert payload['db_only_count'] == 2


@pytest.mark.unit
def test_running_local_adapter_still_wins_when_redis_is_silent(listing_app, monkeypatch):
    """Integrated mode is untouched: a genuinely running adapter is authoritative."""
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._read_audio_metrics_from_redis',
        lambda: None,
    )
    monkeypatch.setattr(
        'webapp.admin.audio_ingest.listing._get_audio_controller',
        lambda: _StubController({'live-one': _stub_adapter('live-one', status='running')}),
    )

    with listing_app.app_context():
        _add_source('live-one', auto_start=True)
        payload = _get(listing_app)

    source = payload['sources'][0]
    assert source['status'] == 'running'
    assert payload['active_count'] == 1
    # The adapter path carries no 'in_memory' key — proof it was taken.
    assert 'in_memory' not in source
