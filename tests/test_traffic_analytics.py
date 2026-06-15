"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Tests for the web-traffic analytics feature (webalizer/awstats-style).

Covers the User-Agent classifier, the IP/network geo classification, and the
aggregation helpers that back the Traffic Analytics dashboard.
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


# ---------------------------------------------------------------------------
# User-Agent classification
# ---------------------------------------------------------------------------

def test_classify_user_agent_chrome_on_windows():
    from app_core.analytics.web_traffic import classify_user_agent

    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    result = classify_user_agent(ua)
    assert result["browser"] == "Chrome"
    assert result["os"] == "Windows 10/11"
    assert result["is_bot"] is False


def test_classify_user_agent_detects_bot():
    from app_core.analytics.web_traffic import classify_user_agent

    result = classify_user_agent("Googlebot/2.1 (+http://www.google.com/bot.html)")
    assert result["is_bot"] is True


def test_classify_user_agent_edge_before_chrome():
    from app_core.analytics.web_traffic import classify_user_agent

    ua = "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0 Safari/537.36 Edg/120.0"
    assert classify_user_agent(ua)["browser"] == "Edge"


def test_is_excluded_path():
    from app_core.analytics.web_traffic import is_excluded_path

    assert is_excluded_path("/static/css/app.css") is True
    assert is_excluded_path("/socket.io/") is True
    assert is_excluded_path("/health") is True
    assert is_excluded_path("/api/traffic/dashboard") is True
    assert is_excluded_path("/dashboard") is False
    assert is_excluded_path("/api/alerts") is False


# ---------------------------------------------------------------------------
# Geo / network classification
# ---------------------------------------------------------------------------

def test_classify_ip_local_and_public():
    from app_core.analytics.geo import classify_ip

    assert classify_ip("127.0.0.1") == "Local (loopback)"
    assert classify_ip("192.168.1.50") == "Local Network"
    assert classify_ip("10.0.0.4") == "Local Network"
    assert classify_ip("169.254.1.1") == "Local (link-local)"
    # No GeoIP DB configured -> generic public label, never raises.
    assert classify_ip("8.8.8.8") == "Internet (Public)"
    assert classify_ip(None) == "Unknown"
    assert classify_ip("not-an-ip") == "Unknown"


def test_classify_location_returns_label_and_code():
    from app_core.analytics.geo import classify_location

    # Local addresses: label set, no country code (no flag).
    assert classify_location("192.168.1.50") == {
        "label": "Local Network",
        "country_code": None,
    }
    assert classify_location("127.0.0.1")["country_code"] is None
    # Public address with no GeoIP DB -> generic label, still no code.
    public = classify_location("8.8.8.8")
    assert public["label"] == "Internet (Public)"
    assert public["country_code"] is None
    # Invalid / missing.
    assert classify_location(None)["label"] == "Unknown"


def test_resolve_hostname_caches_and_handles_failure(monkeypatch):
    import socket as socket_mod

    from app_core.analytics import geo

    # Start from a clean cache so prior tests don't interfere.
    geo._hostname_cache.clear()

    calls = {"n": 0}

    def fake_gethostbyaddr(ip):
        calls["n"] += 1
        if ip == "8.8.8.8":
            return ("dns.google", [], [ip])
        raise socket_mod.herror("no PTR")

    monkeypatch.setattr(geo.socket, "gethostbyaddr", fake_gethostbyaddr)

    assert geo.resolve_hostname("8.8.8.8") == "dns.google"
    # Second call is served from cache (no extra lookup).
    assert geo.resolve_hostname("8.8.8.8") == "dns.google"
    assert calls["n"] == 1

    # A failed lookup is negatively cached as None.
    assert geo.resolve_hostname("1.2.3.4") is None
    assert geo.resolve_hostname("1.2.3.4") is None
    assert calls["n"] == 2

    # Bad input never calls the resolver.
    assert geo.resolve_hostname(None) is None
    assert geo.resolve_hostname("not-an-ip") is None
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

def test_settings_defaults_created(app_with_db):
    app, db = app_with_db
    from app_core.analytics.web_traffic import TrafficAnalyticsSettings

    with app.app_context():
        settings = TrafficAnalyticsSettings.get_settings()
        assert settings.enabled is True
        assert settings.retention_days == 90
        cfg = settings.as_config()
        assert cfg["log_api_requests"] is True
        assert cfg["geoip_database_path"] is None
        # Reverse DNS is opt-in (network calls), so it defaults to off.
        assert cfg["resolve_hostnames"] is False


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

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
        screen_resolution=overrides.pop("screen_resolution", "1920x1080"),
        country=overrides.pop("country", "Local Network"),
        language=overrides.pop("language", "en-US"),
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    db.session.add(row)
    db.session.commit()
    return row


def test_summary_and_breakdowns(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, path="/dashboard", ip_address="192.168.1.10")
        _add_request(db, path="/dashboard", ip_address="192.168.1.11")
        _add_request(db, path="/alerts", ip_address="192.168.1.10")
        _add_request(db, path="/api/alerts", is_api=True, ip_address="192.168.1.10")
        _add_request(db, path="/crawl", is_bot=True, ip_address="66.249.0.1", browser=None)
        _add_request(db, path="/missing", status_code=404, ip_address="192.168.1.12")

        summary = traffic_stats.get_summary(days=30)
        assert summary["total_hits"] == 6
        # Page views exclude API + bot hits.
        assert summary["page_views"] == 4
        assert summary["api_hits"] == 1
        assert summary["bot_hits"] == 1
        assert summary["error_hits"] == 1
        assert summary["unique_visitors"] == 4  # .10 .11 .12 + bot .1

        top_pages = traffic_stats.get_top_pages(days=30)
        assert top_pages[0]["path"] == "/dashboard"
        assert top_pages[0]["hits"] == 2

        status = traffic_stats.get_status_breakdown(days=30)
        families = {row["family"]: row["count"] for row in status}
        assert families["2xx Success"] == 5
        assert families["4xx Client Error"] == 1

        res = traffic_stats.get_resolution_breakdown(days=30)
        assert any(r["resolution"] == "1920x1080" for r in res)

        countries = traffic_stats.get_country_breakdown(days=30)
        assert any(c["country"] == "Local Network" for c in countries)
        # Each country row exposes a (possibly null) ISO code for the flag.
        assert all("country_code" in c for c in countries)

        full = traffic_stats.get_full_dashboard(days=30)
        for key in (
            "summary", "timeseries", "top_pages", "top_visitors",
            "status_breakdown", "browser_breakdown", "os_breakdown",
            "referer_breakdown", "resolution_breakdown", "country_breakdown",
            "language_breakdown", "login_summary", "login_timeseries",
            "top_login_ips", "recent_logins",
        ):
            assert key in full


def test_window_excludes_old_rows(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats
    from app_utils import utc_now

    with app.app_context():
        _add_request(db, timestamp=utc_now())
        _add_request(db, timestamp=utc_now() - timedelta(days=40))

        # 30-day window should only see the recent row.
        assert traffic_stats.get_summary(days=30)["total_hits"] == 1
        # 60-day window sees both.
        assert traffic_stats.get_summary(days=60)["total_hits"] == 2


def test_routes_registered(app_with_db):
    app, db = app_with_db
    import logging
    from webapp import routes_traffic

    routes_traffic.register(app, logging.getLogger("test"))
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/traffic" in rules
    assert "/api/traffic/dashboard" in rules
    assert "/api/traffic/settings" in rules
    assert "/api/traffic/client" in rules


def test_recorder_buffers_and_flushes(app_with_db):
    app, db = app_with_db
    from app_core.analytics.traffic_recorder import TrafficRecorder
    from app_core.analytics.web_traffic import WebRequestLog
    from app_utils import utc_now

    with app.app_context():
        recorder = TrafficRecorder(app)
        # enabled by default in cached config
        recorder.record({
            "timestamp": utc_now(),
            "method": "GET",
            "path": "/dashboard",
            "status_code": 200,
            "ip_address": "192.168.1.20",
            "is_authenticated": False,
            "is_api": False,
            "is_bot": False,
        })
        assert WebRequestLog.query.count() == 0  # not flushed yet
        recorder._flush()
        assert WebRequestLog.query.count() == 1

        # Disabled recorder drops records.
        recorder._config["enabled"] = False
        recorder.record({"timestamp": utc_now(), "method": "GET", "path": "/x",
                         "status_code": 200, "is_authenticated": False,
                         "is_api": False, "is_bot": False})
        recorder._flush()
        assert WebRequestLog.query.count() == 1


def test_top_visitors_include_hostname_and_country(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(
            db,
            ip_address="8.8.8.8",
            hostname="dns.google",
            country="United States",
            country_code="US",
        )
        _add_request(db, ip_address="8.8.8.8", hostname="dns.google")

        visitors = traffic_stats.get_top_visitors(days=30)
        top = next(v for v in visitors if v["ip_address"] == "8.8.8.8")
        assert top["hits"] == 2
        assert top["hostname"] == "dns.google"
        assert top["country_code"] == "US"


def test_recorder_resolves_hostnames_when_enabled(app_with_db, monkeypatch):
    app, db = app_with_db
    from app_core.analytics import geo
    from app_core.analytics.traffic_recorder import TrafficRecorder
    from app_core.analytics.web_traffic import WebRequestLog
    from app_utils import utc_now

    geo._hostname_cache.clear()
    monkeypatch.setattr(geo, "resolve_hostname", lambda ip, *a, **k: f"host-for-{ip}")

    with app.app_context():
        recorder = TrafficRecorder(app)
        recorder._config["resolve_hostnames"] = True
        recorder.record({
            "timestamp": utc_now(), "method": "GET", "path": "/x",
            "status_code": 200, "ip_address": "8.8.4.4",
            "is_authenticated": False, "is_api": False, "is_bot": False,
        })
        recorder._flush()
        row = WebRequestLog.query.filter_by(ip_address="8.8.4.4").first()
        assert row is not None
        assert row.hostname == "host-for-8.8.4.4"


def test_recorder_skips_hostnames_when_disabled(app_with_db, monkeypatch):
    app, db = app_with_db
    from app_core.analytics import geo
    from app_core.analytics.traffic_recorder import TrafficRecorder
    from app_core.analytics.web_traffic import WebRequestLog
    from app_utils import utc_now

    called = {"n": 0}

    def boom(ip, *a, **k):
        called["n"] += 1
        return "should-not-be-used"

    monkeypatch.setattr(geo, "resolve_hostname", boom)

    with app.app_context():
        recorder = TrafficRecorder(app)
        recorder._config["resolve_hostnames"] = False
        recorder.record({
            "timestamp": utc_now(), "method": "GET", "path": "/y",
            "status_code": 200, "ip_address": "8.8.4.4",
            "is_authenticated": False, "is_api": False, "is_bot": False,
        })
        recorder._flush()
        row = WebRequestLog.query.filter_by(ip_address="8.8.4.4").first()
        assert row.hostname is None
        assert called["n"] == 0


def test_login_summary_from_audit(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats
    from app_core.auth.audit import AuditAction, AuditLog
    from app_utils import utc_now

    with app.app_context():
        db.session.add(AuditLog(
            timestamp=utc_now(), username="alice", ip_address="192.168.1.5",
            action=AuditAction.LOGIN_SUCCESS.value, success=True,
        ))
        db.session.add(AuditLog(
            timestamp=utc_now(), username="bob", ip_address="10.0.0.9",
            action=AuditAction.LOGIN_FAILURE.value, success=False,
        ))
        db.session.commit()

        login = traffic_stats.get_login_summary(days=30)
        assert login["successful_logins"] == 1
        assert login["failed_logins"] == 1

        ips = traffic_stats.get_top_login_ips(days=30)
        assert {r["ip_address"] for r in ips} == {"192.168.1.5", "10.0.0.9"}
