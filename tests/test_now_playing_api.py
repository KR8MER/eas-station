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

"""Tests for the public GET /api/audio/now-playing API.

Uses the same lightweight standalone-Flask-app pattern as
test_audio_source_listing.py rather than booting the full app.py -- this
route only needs the DB and the two helpers it calls (Redis source data,
the public Icecast URL), both monkeypatched directly.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.extensions import db
from app_core.models import AudioSourceConfigDB, AudioSourceMetrics
import webapp.routes_now_playing as now_playing_mod
from webapp.admin.audio_ingest import serialization as serialization_mod
from webapp.admin.audio_ingest import streaming as streaming_mod


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover - sqlalchemy hook
    return "TEXT"


@pytest.fixture
def np_app(tmp_path: Path):
    from flask import Flask

    app = Flask("now-playing-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'now_playing.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)

    with app.app_context():
        AudioSourceConfigDB.__table__.create(bind=db.engine)
        AudioSourceMetrics.__table__.create(bind=db.engine)
        now_playing_mod.register(app, logging.getLogger("now-playing-test"))
        yield app
        db.session.remove()
        AudioSourceMetrics.__table__.drop(bind=db.engine)
        AudioSourceConfigDB.__table__.drop(bind=db.engine)


@pytest.fixture
def client(np_app):
    return np_app.test_client()


def _add_source(name, *, enabled=True, priority=5, description=""):
    row = AudioSourceConfigDB(
        name=name, source_type="stream", enabled=enabled,
        priority=priority, description=description, config_params={},
    )
    db.session.add(row)
    db.session.commit()
    return row


def _stub_redis_and_icecast(monkeypatch, *, redis_data=None, icecast_urls=None):
    """redis_data: {source_name: metadata_dict or None}
    icecast_urls: {source_name: url or None} -- absence means None (no public stream)."""
    redis_data = redis_data or {}
    icecast_urls = icecast_urls or {}

    def _read_redis(source_name):
        data = redis_data.get(source_name)
        return {"metadata": data} if data is not None else None

    def _icecast_url(source_name):
        return icecast_urls.get(source_name)

    monkeypatch.setattr(serialization_mod, "_read_redis_source_data", _read_redis)
    monkeypatch.setattr(streaming_mod, "_get_icecast_stream_url", _icecast_url)


def test_no_public_stream_returns_404(np_app, client, monkeypatch):
    with np_app.app_context():
        _add_source("internal_only")
    _stub_redis_and_icecast(monkeypatch)  # no icecast url for anything

    resp = client.get("/api/audio/now-playing")
    assert resp.status_code == 404


def test_default_source_returns_artwork_and_title(np_app, client, monkeypatch):
    with np_app.app_context():
        _add_source("wxyz_relay", description="WXYZ 101.1")
    _stub_redis_and_icecast(
        monkeypatch,
        redis_data={"wxyz_relay": {
            "title": "Some Great Song",
            "artist": "A Cool Artist",
            "artwork_url": "https://cdn.example.com/art.jpg",
            "album": "The Album",
        }},
        icecast_urls={"wxyz_relay": "http://station.example.com:8000/wxyz.mp3"},
    )

    resp = client.get("/api/audio/now-playing")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "source": "wxyz_relay",
        "stream_name": "WXYZ 101.1",
        "icecast_url": "http://station.example.com:8000/wxyz.mp3",
        "title": "Some Great Song",
        "artist": "A Cool Artist",
        "album": "The Album",
        "artwork_url": "https://cdn.example.com/art.jpg",
        "length": None,
    }
    # Never leaks machine-describing fields (mount/server/port/bitrate/etc.)
    assert set(body.keys()) == {
        "source", "stream_name", "icecast_url",
        "title", "artist", "album", "artwork_url", "length",
    }


def test_source_query_param_selects_named_stream(np_app, client, monkeypatch):
    with np_app.app_context():
        _add_source("stream_a", description="Stream A")
        _add_source("stream_b", description="Stream B")
    _stub_redis_and_icecast(
        monkeypatch,
        redis_data={
            "stream_a": {"title": "Song A"},
            "stream_b": {"title": "Song B"},
        },
        icecast_urls={
            "stream_a": "http://host:8000/a.mp3",
            "stream_b": "http://host:8000/b.mp3",
        },
    )

    resp = client.get("/api/audio/now-playing?source=stream_b")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "stream_b"
    assert body["title"] == "Song B"


def test_unknown_source_query_param_returns_404(np_app, client, monkeypatch):
    _stub_redis_and_icecast(monkeypatch)
    resp = client.get("/api/audio/now-playing?source=does_not_exist")
    assert resp.status_code == 404


def test_disabled_source_is_not_selectable_by_name(np_app, client, monkeypatch):
    with np_app.app_context():
        _add_source("disabled_stream", enabled=False)
    _stub_redis_and_icecast(
        monkeypatch, icecast_urls={"disabled_stream": "http://host:8000/x.mp3"}
    )

    resp = client.get("/api/audio/now-playing?source=disabled_stream")
    assert resp.status_code == 404


def test_no_metadata_yet_returns_null_fields_not_error(np_app, client, monkeypatch):
    """A stream with no now-playing metadata (e.g. just started) is a valid
    200 with null fields, not an error -- clients should bind to a stable
    shape rather than branch on presence/absence."""
    with np_app.app_context():
        _add_source("quiet_stream")
    _stub_redis_and_icecast(
        monkeypatch, icecast_urls={"quiet_stream": "http://host:8000/q.mp3"}
    )

    resp = client.get("/api/audio/now-playing")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "quiet_stream"
    assert body["title"] is None
    assert body["artwork_url"] is None


def test_falls_back_to_db_metric_when_redis_has_nothing_fresh(np_app, client, monkeypatch):
    """Right after a restart the audio service may not have published a
    fresh Redis snapshot yet -- the last-known DB row should still surface
    title/artwork rather than the endpoint going blank."""
    with np_app.app_context():
        _add_source("db_fallback_stream")
        db.session.add(AudioSourceMetrics(
            source_name="db_fallback_stream", source_type="stream",
            timestamp=datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc),
            peak_level_db=-6.0, rms_level_db=-18.0,
            peak_level_linear=0.5, rms_level_linear=0.12,
            sample_rate=48000, channels=2, frames_captured=1,
            source_metadata={"title": "Last Known Song", "artwork_url": "https://x/y.jpg"},
        ))
        db.session.commit()
    _stub_redis_and_icecast(
        monkeypatch, icecast_urls={"db_fallback_stream": "http://host:8000/d.mp3"}
    )  # no redis_data entry -> _read_redis_source_data returns None

    resp = client.get("/api/audio/now-playing")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["title"] == "Last Known Song"
    assert body["artwork_url"] == "https://x/y.jpg"


def test_path_is_registered_as_publicly_readable():
    """Regression guard: the whole point of this endpoint is that an
    external player/widget can read it without a session. If this path
    ever drops out of PUBLIC_API_GET_PATHS it silently 401s for anyone
    not logged in."""
    import app as app_module
    assert '/api/audio/now-playing' in app_module.PUBLIC_API_GET_PATHS
