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

"""Tests for the Traffic Analytics enhancements:

* custom date ranges + drill-down dimension filtering (``TrafficFilters``),
* anomaly detection (``traffic_anomalies``),
* privacy / GDPR tools (``traffic_privacy``),
* the new collection settings fields.
"""

from datetime import timedelta

import pytest

pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")


@pytest.fixture
def app_with_db():
    """Minimal Flask app + in-memory SQLite with the traffic tables created."""
    from flask import Flask
    from app_core.extensions import db

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    from app_core import models  # noqa: F401  (registers mappers)

    with app.app_context():
        from app_core.analytics.web_traffic import (
            TrafficAnalyticsSettings,
            WebRequestLog,
        )
        from app_core.auth.audit import AuditLog
        from app_core.models import AdminSession

        WebRequestLog.__table__.create(db.engine)
        TrafficAnalyticsSettings.__table__.create(db.engine)
        AuditLog.__table__.create(db.engine)
        AdminSession.__table__.create(db.engine)
        yield app, db


def _add_request(db, **overrides):
    from app_core.analytics.web_traffic import WebRequestLog
    from app_utils import utc_now

    row = WebRequestLog(
        timestamp=overrides.pop("timestamp", utc_now()),
        method=overrides.pop("method", "GET"),
        path=overrides.pop("path", "/dashboard"),
        status_code=overrides.pop("status_code", 200),
        ip_address=overrides.pop("ip_address", "192.168.1.10"),
        is_api=overrides.pop("is_api", False),
        is_bot=overrides.pop("is_bot", False),
        browser=overrides.pop("browser", "Chrome"),
        os=overrides.pop("os", "Linux"),
        country=overrides.pop("country", "Local Network"),
        language=overrides.pop("language", "en-US"),
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    db.session.add(row)
    db.session.commit()
    return row


def _add_login_failure(db, ip_address, count=1):
    from app_core.auth.audit import AuditAction, AuditLog
    from app_utils import utc_now

    for _ in range(count):
        db.session.add(
            AuditLog(
                timestamp=utc_now(),
                action=AuditAction.LOGIN_FAILURE.value,
                username="attacker",
                ip_address=ip_address,
                success=False,
            )
        )
    db.session.commit()


# ---------------------------------------------------------------------------
# TrafficFilters — windows + parsing
# ---------------------------------------------------------------------------

def test_filters_default_window_is_trailing_days():
    from app_core.analytics.traffic_filters import TrafficFilters
    from app_utils import utc_now

    flt = TrafficFilters(days=7)
    start, end = flt.window()
    assert (end - start) == timedelta(days=7)
    # No explicit end -> the upper bound is open (so "now" rows still count).
    assert flt.end is None
    assert flt.days == 7


def test_filters_days_are_clamped():
    from app_core.analytics.traffic_filters import TrafficFilters

    assert TrafficFilters(days=99999).days == 365
    assert TrafficFilters(days=0).days == 1
    assert TrafficFilters(days="garbage").days == 30


def test_filters_from_request_parses_custom_range_and_dimensions():
    from app_core.analytics.traffic_filters import TrafficFilters

    args = {
        "start": "2026-01-01",
        "end": "2026-01-31",
        "path": "/alerts",
        "status_family": "4xx",
        "country_code": "us",
        "method": "post",
    }
    flt = TrafficFilters.from_request(args)
    start, end = flt.window()
    assert start.strftime("%Y-%m-%d") == "2026-01-01"
    assert end.strftime("%Y-%m-%d") == "2026-01-31"
    assert flt.path == "/alerts"
    assert flt.status_family == 4
    assert flt.country_code == "US"  # uppercased
    assert flt.method == "POST"
    chips = {c["key"]: c["value"] for c in flt.describe()}
    assert chips["path"] == "/alerts"
    assert chips["status_family"] == "4xx"


def test_filters_previous_window_is_immediately_before():
    from datetime import datetime

    from app_core.analytics.traffic_filters import TrafficFilters

    # Use an explicit range so the windows are deterministic (an open-ended
    # filter resolves "now" afresh on every call).
    flt = TrafficFilters(start=datetime(2026, 1, 11), end=datetime(2026, 1, 21))
    prev = flt.previous()
    cur_start, cur_end = flt.window()
    prev_start, prev_end = prev.window()
    assert prev_end == cur_start
    assert (prev_end - prev_start) == (cur_end - cur_start)
    assert prev_start == datetime(2026, 1, 1)


# ---------------------------------------------------------------------------
# Custom date range + dimension drill-down through the stats layer
# ---------------------------------------------------------------------------

def test_custom_date_range_excludes_rows_outside_window(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats
    from app_core.analytics.traffic_filters import TrafficFilters
    from app_utils import utc_now

    with app.app_context():
        now = utc_now()
        _add_request(db, path="/recent", timestamp=now - timedelta(days=1))
        _add_request(db, path="/old", timestamp=now - timedelta(days=20))

        # Explicit range covering only the last 5 days.
        flt = TrafficFilters(start=now - timedelta(days=5), end=now + timedelta(minutes=1))
        assert traffic_stats.get_summary(filters=flt)["total_hits"] == 1
        paths = {p["path"] for p in traffic_stats.get_top_pages(filters=flt)}
        assert paths == {"/recent"}


def test_dimension_filter_narrows_every_section(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats
    from app_core.analytics.traffic_filters import TrafficFilters

    with app.app_context():
        _add_request(db, path="/alerts", ip_address="203.0.113.1", browser="Chrome")
        _add_request(db, path="/alerts", ip_address="203.0.113.2", browser="Firefox")
        _add_request(db, path="/map", ip_address="203.0.113.3", browser="Chrome")

        flt = TrafficFilters(days=30, path="/alerts")
        assert traffic_stats.get_summary(filters=flt)["total_hits"] == 2

        # Browser drill-down composes with nothing else.
        bf = TrafficFilters(days=30, browser="Chrome")
        assert traffic_stats.get_summary(filters=bf)["total_hits"] == 2
        browsers = {b["browser"]: b["count"] for b in traffic_stats.get_browser_breakdown(filters=bf)}
        assert browsers == {"Chrome": 2}


def test_status_family_filter(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats
    from app_core.analytics.traffic_filters import TrafficFilters

    with app.app_context():
        _add_request(db, status_code=200)
        _add_request(db, status_code=404)
        _add_request(db, status_code=500)

        flt = TrafficFilters(days=30, status_family=4)
        assert traffic_stats.get_summary(filters=flt)["total_hits"] == 1
        flt5 = TrafficFilters(days=30, status_family=5)
        assert traffic_stats.get_summary(filters=flt5)["total_hits"] == 1


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def test_anomaly_high_error_rate(app_with_db):
    app, db = app_with_db
    from app_core.analytics.traffic_anomalies import detect_anomalies

    with app.app_context():
        for _ in range(15):
            _add_request(db, status_code=200)
        for _ in range(15):
            _add_request(db, status_code=500, ip_address="198.51.100.9")

        anomalies = detect_anomalies()
        kinds = {a["type"] for a in anomalies}
        assert "error_rate" in kinds
        # 50% error rate should be flagged.
        rate = next(a for a in anomalies if a["type"] == "error_rate")
        assert rate["value"] >= 25


def test_anomaly_scanner_detection(app_with_db):
    app, db = app_with_db
    from app_core.analytics.traffic_anomalies import detect_anomalies

    with app.app_context():
        for _ in range(60):
            _add_request(db, status_code=404, ip_address="198.51.100.50", path="/wp-login.php")
        anomalies = detect_anomalies()
        scanner = [a for a in anomalies if a["type"] == "scanner"]
        assert scanner and scanner[0]["ip_address"] == "198.51.100.50"


def test_anomaly_login_bruteforce(app_with_db):
    app, db = app_with_db
    from app_core.analytics.traffic_anomalies import detect_anomalies

    with app.app_context():
        _add_login_failure(db, "203.0.113.99", count=12)
        anomalies = detect_anomalies()
        brute = [a for a in anomalies if a["type"] == "brute_force"]
        assert brute and brute[0]["ip_address"] == "203.0.113.99"


def test_anomaly_detection_can_be_disabled(app_with_db):
    app, db = app_with_db
    from app_core.analytics.traffic_anomalies import detect_anomalies
    from app_core.analytics.web_traffic import TrafficAnalyticsSettings

    with app.app_context():
        settings = TrafficAnalyticsSettings.get_settings()
        settings.anomaly_detection_enabled = False
        db.session.commit()
        for _ in range(40):
            _add_request(db, status_code=500)
        assert detect_anomalies() == []


def test_anomaly_quiet_when_healthy(app_with_db):
    app, db = app_with_db
    from app_core.analytics.traffic_anomalies import detect_anomalies

    with app.app_context():
        for _ in range(30):
            _add_request(db, status_code=200)
        # Only an occasional error — below thresholds.
        _add_request(db, status_code=404)
        kinds = {a["type"] for a in detect_anomalies()}
        assert "error_rate" not in kinds
        assert "scanner" not in kinds


# ---------------------------------------------------------------------------
# Privacy / GDPR tools
# ---------------------------------------------------------------------------

def test_anonymize_value_masks_public_but_not_local():
    from app_core.analytics.traffic_privacy import anonymize_value

    assert anonymize_value("203.0.113.45") == "203.0.113.0"
    assert anonymize_value("127.0.0.1") == "127.0.0.1"  # loopback untouched
    # IPv6 truncated to /48.
    assert anonymize_value("2001:db8:abcd:1234::1") == "2001:db8:abcd::"


def test_purge_ip_deletes_rows(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_privacy, traffic_stats

    with app.app_context():
        _add_request(db, ip_address="203.0.113.7")
        _add_request(db, ip_address="203.0.113.7")
        _add_request(db, ip_address="203.0.113.8")

        result = traffic_privacy.purge_ip("203.0.113.7")
        assert result["deleted"] == 2
        assert traffic_stats.get_summary(days=30)["total_hits"] == 1


def test_anonymize_ip_masks_rows_but_keeps_them(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_privacy, traffic_stats
    from app_core.analytics.web_traffic import WebRequestLog

    with app.app_context():
        _add_request(db, ip_address="203.0.113.7", hostname="host.example.com")
        _add_request(db, ip_address="203.0.113.7")

        result = traffic_privacy.anonymize_ip("203.0.113.7")
        assert result["updated"] == 2
        assert result["masked"] == "203.0.113.0"
        # Rows retained (counts intact) but the address is masked.
        assert traffic_stats.get_summary(days=30)["total_hits"] == 2
        remaining = {r.ip_address for r in WebRequestLog.query.all()}
        assert remaining == {"203.0.113.0"}
        assert all(r.hostname is None for r in WebRequestLog.query.all())


# ---------------------------------------------------------------------------
# Settings model — new fields
# ---------------------------------------------------------------------------

def test_settings_new_fields_default_and_persist(app_with_db):
    app, db = app_with_db
    from app_core.analytics.web_traffic import TrafficAnalyticsSettings

    with app.app_context():
        settings = TrafficAnalyticsSettings.get_settings()
        cfg = settings.as_config()
        assert cfg["anonymize_ip"] is False
        assert cfg["anomaly_detection_enabled"] is True
        assert cfg["anomaly_error_rate_pct"] == 25
        assert cfg["anomaly_scanner_threshold"] == 50

        settings.anonymize_ip = True
        settings.anomaly_error_rate_pct = 40
        db.session.commit()

        reloaded = TrafficAnalyticsSettings.get_settings().as_config()
        assert reloaded["anonymize_ip"] is True
        assert reloaded["anomaly_error_rate_pct"] == 40
