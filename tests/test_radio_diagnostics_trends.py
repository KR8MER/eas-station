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

Tests for app_core/radio/trends.py (the bucket/rollup archive) and the
/api/radio/diagnostics/trends/<id> route that reads it.
"""

from __future__ import annotations

import json
import logging
import sys
import time
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
from app_core.radio import trends as sdr_trends
import webapp.routes_settings_radio as radio_routes
import webapp.radio_settings.deps as radio_deps


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover
    return "TEXT"


class FakeRedis:
    """In-memory Redis stand-in covering list ops (lpush/ltrim/lrange)."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        if key in self.lists:
            self.lists[key] = self.lists[key][start:end + 1]
        return True

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if end == -1:
            return items[start:]
        return items[start:end + 1]

    def pipeline(self):
        return self

    def execute(self):
        return True


class FakeStatus:
    def __init__(self, locked=True, signal_strength=-40.0):
        self.locked = locked
        self.signal_strength = signal_strength


# ---------------------------------------------------------------------------
# app_core/radio/trends.py unit tests
# ---------------------------------------------------------------------------

def test_publish_sample_appends_raw_row():
    redis_client = FakeRedis()
    prev_counters: dict = {}
    last_bucket_ids = sdr_trends.new_last_bucket_ids()

    sdr_trends.publish_sample(
        redis_client, "WXTEST", FakeStatus(), {"overflow_count": 3, "underflow_count": 1},
        250_000, 250_000, prev_counters, last_bucket_ids,
    )

    key = sdr_trends.redis_key_for_tier("WXTEST", "raw")
    assert len(redis_client.lists[key]) == 1
    row = json.loads(redis_client.lists[key][0])
    assert row["signal_strength"] == -40.0
    assert row["locked"] == 1.0
    assert row["sample_rate_ratio"] == 1.0
    # First sample: no prior counters, so delta is 0, not the raw 3/1.
    assert row["overflow_count"] == 0.0
    assert row["underflow_count"] == 0.0


def test_publish_sample_computes_counter_deltas():
    """overflow/underflow are stored as deltas since the previous sample,
    not the raw monotonic totals -- verifies the delta math directly."""
    redis_client = FakeRedis()
    prev_counters: dict = {}
    last_bucket_ids = sdr_trends.new_last_bucket_ids()

    sdr_trends.publish_sample(
        redis_client, "WXTEST", FakeStatus(), {"overflow_count": 5, "underflow_count": 0},
        250_000, 250_000, prev_counters, last_bucket_ids,
    )
    sdr_trends.publish_sample(
        redis_client, "WXTEST", FakeStatus(), {"overflow_count": 9, "underflow_count": 2},
        250_000, 250_000, prev_counters, last_bucket_ids,
    )

    key = sdr_trends.redis_key_for_tier("WXTEST", "raw")
    rows = [json.loads(r) for r in redis_client.lists[key]]
    # Newest-first: rows[0] is the second sample (delta 9-5=4, 2-0=2).
    assert rows[0]["overflow_count"] == 4.0
    assert rows[0]["underflow_count"] == 2.0
    assert rows[1]["overflow_count"] == 0.0


def test_publish_sample_noop_when_status_missing():
    redis_client = FakeRedis()
    prev_counters: dict = {}
    last_bucket_ids = sdr_trends.new_last_bucket_ids()

    sdr_trends.publish_sample(
        redis_client, "WXTEST", None, None, 250_000, 250_000, prev_counters, last_bucket_ids,
    )
    assert redis_client.lists == {}


def test_emit_rollups_produces_5m_bucket_after_boundary_crossing():
    redis_client = FakeRedis()
    prev_counters: dict = {}
    last_bucket_ids = sdr_trends.new_last_bucket_ids()

    for i in range(3):
        sdr_trends.publish_sample(
            redis_client, "WXTEST", FakeStatus(signal_strength=-30.0 - i),
            {"overflow_count": i, "underflow_count": 0},
            250_000, 250_000, prev_counters, last_bucket_ids,
        )

    now_ms = int(time.time() * 1000)
    # Force a 5-minute boundary crossing.
    sdr_trends.emit_rollups(redis_client, "WXTEST", last_bucket_ids, now_ms + 6 * 60 * 1000)

    rollup_key = sdr_trends.redis_key_for_tier("WXTEST", "5m")
    assert rollup_key in redis_client.lists
    rollup = json.loads(redis_client.lists[rollup_key][0])
    assert rollup["tier"] == "5m"
    assert rollup["sample_count"] == 3
    assert rollup["locked_pct"] == 100.0
    # overflow deltas across the 3 samples: 0, then 1-0=1, then 2-1=1 -> sum 2
    assert rollup["overflow_count"] == 2.0


def test_read_window_falls_back_to_default_for_unknown_window():
    redis_client = FakeRedis()
    result = sdr_trends.read_window(redis_client, "WXTEST", "not-a-real-window")
    assert result["window"] == sdr_trends.SDR_TRENDS_DEFAULT_WINDOW
    assert result["tier"] == "raw"
    assert result["samples"] == []


def test_read_window_returns_chronological_order():
    redis_client = FakeRedis()
    prev_counters: dict = {}
    last_bucket_ids = sdr_trends.new_last_bucket_ids()

    for i in range(3):
        sdr_trends.publish_sample(
            redis_client, "WXTEST", FakeStatus(signal_strength=float(i)),
            {"overflow_count": 0, "underflow_count": 0},
            250_000, 250_000, prev_counters, last_bucket_ids,
        )

    result = sdr_trends.read_window(redis_client, "WXTEST", "1h")
    values = [s["signal_strength"] for s in result["samples"]]
    assert values == [0.0, 1.0, 2.0]  # oldest first


def test_read_window_handles_no_redis_client():
    result = sdr_trends.read_window(None, "WXTEST", "1h")
    assert result["samples"] == []


# ---------------------------------------------------------------------------
# /api/radio/diagnostics/trends/<id> route tests
# ---------------------------------------------------------------------------

@pytest.fixture
def trends_app(tmp_path, monkeypatch):
    """A minimal Flask app with just the radio routes registered."""
    database_path = tmp_path / "trends.db"
    app = Flask("radio-trends-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)

    monkeypatch.setattr(
        radio_deps, "_log_radio_event", lambda *args, **kwargs: None
    )

    with app.app_context():
        engine = db.engine
        RadioReceiver.__table__.create(bind=engine)
        radio_routes.register(app, logging.getLogger("radio-trends-test"))
        yield app
        db.session.remove()
        RadioReceiver.__table__.drop(bind=engine, checkfirst=True)


def _add_receiver():
    receiver = RadioReceiver(
        identifier="WXTEST",
        display_name="Trends Test",
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


def test_trends_route_returns_samples(trends_app, monkeypatch, authenticated_user):
    app = trends_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        fake_redis = FakeRedis()
        prev_counters: dict = {}
        last_bucket_ids = sdr_trends.new_last_bucket_ids()
        sdr_trends.publish_sample(
            fake_redis, "WXTEST", FakeStatus(), {"overflow_count": 0, "underflow_count": 0},
            2_400_000, 2_400_000, prev_counters, last_bucket_ids,
        )
        monkeypatch.setattr(radio_deps, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.get(f"/api/radio/diagnostics/trends/{receiver_id}")
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["identifier"] == "WXTEST"
        assert body["window"] == "1h"
        assert body["tier"] == "raw"
        assert body["sample_count"] == 1
        assert body["samples"][0]["locked"] == 1.0
        assert set(sdr_trends.SDR_TRENDS_WINDOW_TO_TIER) <= set(body["available_windows"])


def test_trends_route_honours_window_param(trends_app, monkeypatch, authenticated_user):
    app = trends_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id
        fake_redis = FakeRedis()
        monkeypatch.setattr(radio_deps, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.get(f"/api/radio/diagnostics/trends/{receiver_id}?window=7d")
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["window"] == "7d"
        assert body["tier"] == "5m"
        assert body["samples"] == []


def test_trends_route_404_for_unknown_receiver(trends_app, monkeypatch, authenticated_user):
    app = trends_app
    with app.app_context():
        fake_redis = FakeRedis()
        monkeypatch.setattr(radio_deps, "get_redis_client", lambda: fake_redis)
        client = app.test_client()
        resp = client.get("/api/radio/diagnostics/trends/999999")
        assert resp.status_code == 404


def test_trends_route_survives_redis_unavailable(trends_app, monkeypatch, authenticated_user):
    """If Redis is down, the route still returns 200 with an empty archive
    rather than a 500 -- historical trends being unavailable shouldn't take
    down the rest of the diagnostics page."""
    app = trends_app
    with app.app_context():
        receiver = _add_receiver()
        receiver_id = receiver.id

        def _boom():
            raise ConnectionError("redis is down")
        monkeypatch.setattr(radio_deps, "get_redis_client", _boom)

        client = app.test_client()
        resp = client.get(f"/api/radio/diagnostics/trends/{receiver_id}")
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["samples"] == []
