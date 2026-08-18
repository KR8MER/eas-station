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

Tests for app_core/radio/diagnostics_report.py (the "Run Full Diagnostics"
checklist) and the /api/radio/diagnostics/run-check route that serves it.
"""

from __future__ import annotations

import json
import logging
import sys
import time
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
from app_core.models import RadioReceiver
from app_core.radio.diagnostics_report import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_WARN,
    overall_status,
    run_sdr_diagnostics_checks,
)
import webapp.routes_settings_radio as radio_routes
import webapp.radio_settings.deps as radio_deps


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):  # pragma: no cover
    return "TEXT"


def _receiver(identifier="WXTEST", enabled=True, frequency_hz=98_500_000, sample_rate=2_400_000):
    return SimpleNamespace(
        identifier=identifier,
        display_name=f"Test {identifier}",
        enabled=enabled,
        frequency_hz=frequency_hz,
        sample_rate=sample_rate,
    )


class FakeRedis:
    def __init__(self, kv=None, hashes=None):
        self.kv = kv or {}
        self.hashes = hashes or {}

    def get(self, key):
        return self.kv.get(key)

    def hgetall(self, key):
        return self.hashes.get(key, {})


def test_no_receivers_configured_is_a_fail():
    checks = run_sdr_diagnostics_checks([], FakeRedis())
    assert len(checks) == 1
    assert checks[0]["status"] == STATUS_FAIL
    assert overall_status(checks) == STATUS_FAIL


def test_invalid_config_is_flagged():
    bad = _receiver(frequency_hz=0)
    checks = run_sdr_diagnostics_checks([bad], FakeRedis())
    config_check = next(c for c in checks if c["id"] == "config_sanity")
    assert config_check["status"] == STATUS_FAIL


def test_missing_heartbeat_is_a_fail():
    r = _receiver()
    checks = run_sdr_diagnostics_checks([r], FakeRedis())
    heartbeat_check = next(c for c in checks if c["id"] == "sdr_heartbeat")
    assert heartbeat_check["status"] == STATUS_FAIL


def test_fresh_heartbeat_passes():
    r = _receiver()
    redis_client = FakeRedis(kv={
        "sdr:heartbeat": json.dumps({"timestamp": time.time(), "receiver_count": 1}),
    })
    checks = run_sdr_diagnostics_checks([r], redis_client)
    heartbeat_check = next(c for c in checks if c["id"] == "sdr_heartbeat")
    assert heartbeat_check["status"] == STATUS_PASS


def test_stale_heartbeat_warns():
    r = _receiver()
    redis_client = FakeRedis(kv={
        "sdr:heartbeat": json.dumps({"timestamp": time.time() - 60, "receiver_count": 1}),
    })
    checks = run_sdr_diagnostics_checks([r], redis_client)
    heartbeat_check = next(c for c in checks if c["id"] == "sdr_heartbeat")
    assert heartbeat_check["status"] == STATUS_WARN


def test_no_enabled_receivers_short_circuits_after_heartbeat():
    r = _receiver(enabled=False)
    redis_client = FakeRedis(kv={
        "sdr:heartbeat": json.dumps({"timestamp": time.time(), "receiver_count": 0}),
    })
    checks = run_sdr_diagnostics_checks([r], redis_client)
    ids = [c["id"] for c in checks]
    assert "receiver_health" in ids
    assert "receiver_reporting" not in ids


def test_full_healthy_pipeline_all_pass():
    r = _receiver()
    now = time.time()
    redis_client = FakeRedis(
        kv={
            "sdr:heartbeat": json.dumps({"timestamp": now, "receiver_count": 1}),
            "sdr:metrics": json.dumps({
                "receivers": {
                    "WXTEST": {
                        "running": True,
                        "locked": True,
                        "samples_available": True,
                    },
                },
            }),
            "eas:spectrum:WXTEST": json.dumps({"timestamp": now}),
        },
        hashes={
            "sdr:ring_buffer:WXTEST": {"overflow_count": "0", "underflow_count": "0"},
        },
    )
    checks = run_sdr_diagnostics_checks([r], redis_client)
    assert overall_status(checks) == STATUS_PASS
    by_id = {c["id"]: c for c in checks}
    assert by_id["receiver_running"]["status"] == STATUS_PASS
    assert by_id["receiver_locked"]["status"] == STATUS_PASS
    assert by_id["receiver_samples"]["status"] == STATUS_PASS
    assert by_id["ring_buffer_health"]["status"] == STATUS_PASS
    assert by_id["spectrum_cache"]["status"] == STATUS_PASS


def test_ring_buffer_overflow_warns():
    r = _receiver()
    now = time.time()
    redis_client = FakeRedis(
        kv={
            "sdr:heartbeat": json.dumps({"timestamp": now, "receiver_count": 1}),
            "sdr:metrics": json.dumps({
                "receivers": {"WXTEST": {"running": True, "locked": True, "samples_available": True}},
            }),
        },
        hashes={
            "sdr:ring_buffer:WXTEST": {"overflow_count": "42", "underflow_count": "0"},
        },
    )
    checks = run_sdr_diagnostics_checks([r], redis_client)
    ring_check = next(c for c in checks if c["id"] == "ring_buffer_health")
    assert ring_check["status"] == STATUS_WARN
    assert "42" in ring_check["message"]


def test_missing_spectrum_cache_warns():
    r = _receiver()
    now = time.time()
    redis_client = FakeRedis(kv={
        "sdr:heartbeat": json.dumps({"timestamp": now, "receiver_count": 1}),
        "sdr:metrics": json.dumps({
            "receivers": {"WXTEST": {"running": True, "locked": True, "samples_available": True}},
        }),
        # No eas:spectrum:WXTEST key.
    })
    checks = run_sdr_diagnostics_checks([r], redis_client)
    spectrum_check = next(c for c in checks if c["id"] == "spectrum_cache")
    assert spectrum_check["status"] == STATUS_WARN


def test_receiver_not_reporting_is_warn_not_fail():
    """A receiver the SDR service hasn't started yet is a warn, not a hard
    fail -- it may just be mid-startup."""
    r = _receiver()
    redis_client = FakeRedis(kv={
        "sdr:heartbeat": json.dumps({"timestamp": time.time(), "receiver_count": 0}),
        "sdr:metrics": json.dumps({"receivers": {}}),
    })
    checks = run_sdr_diagnostics_checks([r], redis_client)
    reporting_check = next(c for c in checks if c["id"] == "receiver_reporting")
    assert reporting_check["status"] == STATUS_WARN


def test_overall_status_precedence():
    assert overall_status([{"status": STATUS_PASS}, {"status": STATUS_WARN}]) == STATUS_WARN
    assert overall_status([{"status": STATUS_PASS}, {"status": STATUS_FAIL}, {"status": STATUS_WARN}]) == STATUS_FAIL
    assert overall_status([{"status": STATUS_PASS}]) == STATUS_PASS
    assert overall_status([]) == "info"


# ---------------------------------------------------------------------------
# /api/radio/diagnostics/run-check route tests
# ---------------------------------------------------------------------------

@pytest.fixture
def diag_app(tmp_path, monkeypatch):
    database_path = tmp_path / "diag_report.db"
    app = Flask("radio-diag-report-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{database_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    monkeypatch.setattr(radio_deps, "_log_radio_event", lambda *args, **kwargs: None)

    with app.app_context():
        engine = db.engine
        RadioReceiver.__table__.create(bind=engine)
        radio_routes.register(app, logging.getLogger("radio-diag-report-test"))
        yield app
        db.session.remove()
        RadioReceiver.__table__.drop(bind=engine, checkfirst=True)


def _add_db_receiver():
    receiver = RadioReceiver(
        identifier="WXTEST",
        display_name="Report Test",
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
        squelch_enabled=False,
        squelch_threshold_db=-60.0,
        squelch_open_ms=100,
        squelch_close_ms=400,
        squelch_alarm=False,
    )
    db.session.add(receiver)
    db.session.commit()
    return receiver


def test_run_check_route_returns_checklist(diag_app, monkeypatch, authenticated_user):
    app = diag_app
    with app.app_context():
        _add_db_receiver()
        fake_redis = FakeRedis(kv={
            "sdr:heartbeat": json.dumps({"timestamp": time.time(), "receiver_count": 1}),
        })
        monkeypatch.setattr(radio_deps, "get_redis_client", lambda: fake_redis)

        client = app.test_client()
        resp = client.post("/api/radio/diagnostics/run-check")
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert "overall_status" in body
        assert isinstance(body["checks"], list)
        assert len(body["checks"]) > 0


def test_run_check_route_handles_redis_down(diag_app, monkeypatch, authenticated_user):
    app = diag_app
    with app.app_context():
        _add_db_receiver()

        def _boom():
            raise ConnectionError("redis down")
        monkeypatch.setattr(radio_deps, "get_redis_client", _boom)

        client = app.test_client()
        resp = client.post("/api/radio/diagnostics/run-check")
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["overall_status"] == STATUS_FAIL
