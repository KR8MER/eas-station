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

Tests for the /api/radio/bandscan/<id>/identify/* routes.

There is no existing route-level test file for the other bandscan
endpoints (start/progress/cancel) either -- this is new coverage, not a
gap being filled. The actual sweep/decode logic these routes dispatch to
(_run_bandscan_identify) has its own thorough coverage in
tests/test_bandscan.py; these tests only exercise the web layer: body
validation, permission gating, and the Redis command-queue handoff.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.extensions import db
from app_core.models import RadioReceiver
from app_core.config.redis_config import RedisChannels
import webapp.radio_settings.deps as radio_deps
import webapp.radio_settings.routes_bandscan as routes_bandscan


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover
    return "TEXT"


class FakeRedis:
    """Minimal in-memory Redis stand-in -- just enough for the
    rpush-then-poll-for-a-result pattern every bandscan route uses."""

    def __init__(self, command_result=None):
        self.kv: dict = {}
        self.lists: dict = {}
        self.command_result = command_result

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def get(self, key):
        if key.startswith("sdr:command_result:") and self.command_result is not None:
            return json.dumps(self.command_result)
        return self.kv.get(key)

    def setex(self, key, ttl, value):
        self.kv[key] = value
        return True

    def delete(self, key):
        return self.kv.pop(key, None) is not None


@pytest.fixture
def bandscan_app(tmp_path, monkeypatch):
    """Minimal Flask app with only the bandscan routes registered."""
    database_path = tmp_path / "bandscan.db"
    app = Flask("bandscan-route-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    monkeypatch.setattr(radio_deps, "_log_radio_event", lambda *args, **kwargs: None)

    with app.app_context():
        engine = db.engine
        RadioReceiver.__table__.create(bind=engine)
        routes_bandscan.register(app, logging.getLogger("bandscan-route-test"))
        yield app
        db.session.remove()
        RadioReceiver.__table__.drop(bind=engine, checkfirst=True)


def _add_receiver():
    receiver = RadioReceiver(
        identifier="WXTEST",
        display_name="Bandscan Route Test",
        driver="rtlsdr",
        frequency_hz=98_500_000,
        sample_rate=2_400_000,
        modulation_type="WFM",
        audio_output=True,
        stereo_enabled=False,
        deemphasis_us=75.0,
        enable_rbds=True,
        enabled=True,
        auto_start=False,
    )
    db.session.add(receiver)
    db.session.commit()
    return receiver


def test_identify_start_requires_frequencies(bandscan_app, authenticated_user):
    app = bandscan_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id
        client = app.test_client()

        resp = client.post(f"/api/radio/bandscan/{receiver_id}/identify/start", json={})
        assert resp.status_code == 400
        assert "frequencies_hz" in resp.get_json()["error"]


def test_identify_start_rejects_empty_list(bandscan_app, authenticated_user):
    app = bandscan_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id
        client = app.test_client()

        resp = client.post(
            f"/api/radio/bandscan/{receiver_id}/identify/start",
            json={"frequencies_hz": []},
        )
        assert resp.status_code == 400


def test_identify_start_rejects_out_of_band_frequency(bandscan_app, authenticated_user):
    app = bandscan_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id
        client = app.test_client()

        # 87.4 MHz is just below the 87.5-108.0 MHz Bandscan band.
        resp = client.post(
            f"/api/radio/bandscan/{receiver_id}/identify/start",
            json={"frequencies_hz": [87_400_000]},
        )
        assert resp.status_code == 400
        assert "MHz" in resp.get_json()["error"]


def test_identify_start_happy_path_dispatches_correct_command(bandscan_app, monkeypatch, authenticated_user):
    app = bandscan_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        fake_redis = FakeRedis(command_result={"success": True, "started": True})
        monkeypatch.setattr(radio_deps, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.post(
            f"/api/radio/bandscan/{receiver_id}/identify/start",
            json={"frequencies_hz": [93_900_000, 101_300_000]},
        )
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json() == {"started": True}

        assert len(fake_redis.lists["sdr:commands"]) == 1
        command = json.loads(fake_redis.lists["sdr:commands"][0])
        assert command["action"] == "bandscan_identify"
        assert command["receiver_id"] == "WXTEST"
        assert command["target_freqs_hz"] == [93_900_000, 101_300_000]


def test_identify_start_propagates_already_running_as_409(bandscan_app, monkeypatch, authenticated_user):
    app = bandscan_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        fake_redis = FakeRedis(command_result={
            "success": False,
            "error": "A bandscan is already running for this receiver",
        })
        monkeypatch.setattr(radio_deps, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.post(
            f"/api/radio/bandscan/{receiver_id}/identify/start",
            json={"frequencies_hz": [93_900_000]},
        )
        assert resp.status_code == 409


def test_identify_start_requires_authentication(bandscan_app):
    """No authenticated_user fixture applied -- the deny-by-default auth
    gate must reject this before it ever reaches the route body."""
    app = bandscan_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id
        client = app.test_client()

        resp = client.post(
            f"/api/radio/bandscan/{receiver_id}/identify/start",
            json={"frequencies_hz": [93_900_000]},
        )
        assert resp.status_code == 401


def test_identify_progress_unavailable_when_no_scan_has_run(bandscan_app, monkeypatch, authenticated_user):
    app = bandscan_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        fake_redis = FakeRedis()
        monkeypatch.setattr(radio_deps, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.get(f"/api/radio/bandscan/{receiver_id}/identify/progress")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "unavailable"}


def test_identify_progress_returns_stored_payload(bandscan_app, monkeypatch, authenticated_user):
    app = bandscan_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        fake_redis = FakeRedis()
        stored = {
            "status": "done",
            "target_freqs_hz": [93_900_000],
            "results": [{"freq_hz": 93_900_000, "ps_name": "KISSFM", "rms_dbfs": -20.0}],
            "started_at": 0,
            "updated_at": 0,
        }
        fake_redis.kv[f"{RedisChannels.BANDSCAN_IDENTIFY_PROGRESS_PREFIX}WXTEST"] = json.dumps(stored)
        monkeypatch.setattr(radio_deps, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.get(f"/api/radio/bandscan/{receiver_id}/identify/progress")
        assert resp.status_code == 200
        assert resp.get_json() == stored


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
