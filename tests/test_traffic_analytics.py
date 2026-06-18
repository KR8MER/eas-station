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
    assert result["browser_version"] == "120.0"
    assert result["os"] == "Windows 10/11"
    assert result["is_bot"] is False


def test_classify_user_agent_safari_version_from_version_token():
    from app_core.analytics.web_traffic import classify_user_agent

    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/16.1 Safari/605.1.15"
    )
    result = classify_user_agent(ua)
    assert result["browser"] == "Safari"
    # Safari's user-facing version comes from the Version/ token, not Safari/.
    assert result["browser_version"] == "16.1"
    assert result["os"] == "macOS"


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


def test_resolve_asn_skips_local_and_unconfigured():
    from app_core.analytics.geo import resolve_asn

    # No ASN database configured -> None, never raises.
    assert resolve_asn("8.8.8.8", None) is None
    # Local/private addresses are never looked up.
    assert resolve_asn("192.168.1.5", "/nonexistent.mmdb") is None
    assert resolve_asn("127.0.0.1", "/nonexistent.mmdb") is None
    assert resolve_asn(None, "/nonexistent.mmdb") is None


def test_city_and_asn_breakdowns(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, ip_address="8.8.8.8", city="Mountain View", asn_org="Google LLC")
        _add_request(db, ip_address="8.8.4.4", city="Mountain View", asn_org="Google LLC")
        _add_request(db, ip_address="1.1.1.1", city="Sydney", asn_org="Cloudflare")

        cities = {c["city"]: c["count"] for c in traffic_stats.get_city_breakdown(days=30)}
        assert cities.get("Mountain View") == 2
        assert cities.get("Sydney") == 1

        orgs = {o["asn_org"]: o["count"] for o in traffic_stats.get_asn_breakdown(days=30)}
        assert orgs.get("Google LLC") == 2
        assert orgs.get("Cloudflare") == 1


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


def test_resolve_hostname_resolves_ipv6(monkeypatch):
    """IPv6 PTR lookups go through the same path as IPv4 (regression)."""
    import socket as socket_mod

    from app_core.analytics import geo

    geo._hostname_cache.clear()

    def fake_gethostbyaddr(ip):
        if ip == "2001:4860:4860::8888":
            return ("dns.google", [], [ip])
        raise socket_mod.herror("no PTR")

    monkeypatch.setattr(geo.socket, "gethostbyaddr", fake_gethostbyaddr)

    assert geo.resolve_hostname("2001:4860:4860::8888") == "dns.google"
    # Authoritative "no PTR" for a v6 address is negatively cached.
    assert geo.resolve_hostname("2001:db8::1") is None
    name, status = geo.resolve_hostname("2001:db8::1", return_status=True)
    assert name is None and status == "no_record"


def test_resolve_hostname_transient_failure_not_cached(monkeypatch):
    """A timeout/temporary failure is retryable: not cached, status 'error'."""
    import socket as socket_mod

    from app_core.analytics import geo

    geo._hostname_cache.clear()
    calls = {"n": 0}

    def flaky_gethostbyaddr(ip):
        calls["n"] += 1
        if calls["n"] == 1:
            raise socket_mod.timeout("timed out")
        return ("late.example.net", [], [ip])

    monkeypatch.setattr(geo.socket, "gethostbyaddr", flaky_gethostbyaddr)

    # First lookup times out -> None, status 'error', and NOT cached.
    name, status = geo.resolve_hostname("2001:4860:4860::8888", return_status=True)
    assert name is None and status == "error"
    assert "2001:4860:4860::8888" not in geo._hostname_cache
    # A later pass retries (because it wasn't cached) and now succeeds.
    assert geo.resolve_hostname("2001:4860:4860::8888") == "late.example.net"
    assert calls["n"] == 2


def test_ip_version_breakdown(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        # Two distinct IPv4 addresses, one with a resolved hostname.
        _add_request(db, ip_address="8.8.8.8", hostname="dns.google")
        _add_request(db, ip_address="8.8.8.8", hostname="dns.google")
        _add_request(db, ip_address="1.1.1.1")
        # Two IPv6 addresses inside the same /64 (one visitor), no PTR records.
        _add_request(db, ip_address="2001:db8:abcd:1::1")
        _add_request(db, ip_address="2001:db8:abcd:1::2")

        rows = {r["label"]: r for r in traffic_stats.get_ip_version_breakdown(days=30)}
        assert rows["IPv4"]["count"] == 3
        assert rows["IPv4"]["ips"] == 2
        assert rows["IPv4"]["visitors"] == 2
        assert rows["IPv4"]["resolved"] == 1  # only 8.8.8.8 has a hostname

        assert rows["IPv6"]["count"] == 2
        assert rows["IPv6"]["ips"] == 2
        # Both v6 addresses collapse to a single /64 visitor.
        assert rows["IPv6"]["visitors"] == 1
        assert rows["IPv6"]["resolved"] == 0


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
        # Internal (loopback) traffic is excluded from visitor analytics by default.
        assert cfg["exclude_loopback"] is True
        assert cfg["excluded_paths"] is None
        # ASN database is a separate, optional slot.
        assert cfg["geoip_asn_database_path"] is None


def test_excluded_paths_parsing_and_matching():
    from app_core.analytics.web_traffic import is_excluded_path, parse_excluded_paths

    extra = parse_excluded_paths("/api/audio/, /metrics\n/debug")
    assert extra == ("/api/audio/", "/metrics", "/debug")
    # Built-in plumbing is always excluded.
    assert is_excluded_path("/static/app.css") is True
    # Operator skip-list adds to it.
    assert is_excluded_path("/api/audio/metrics", extra) is True
    assert is_excluded_path("/metrics", extra) is True
    # A normal page is still recorded.
    assert is_excluded_path("/dashboard", extra) is False


def test_referer_breakdown_groups_by_domain_and_excludes_self(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, referer="https://news.example.com/article?id=1")
        _add_request(db, referer="https://news.example.com/other")
        _add_request(db, referer="https://t.co/abc")
        _add_request(db, referer="https://easstation.com/dashboard")  # self-referral

        refs = traffic_stats.get_referer_breakdown(days=30, self_hosts={"easstation.com"})
        by_host = {r["referer"]: r["count"] for r in refs}
        # Grouped by domain; the two example.com URLs collapse to one row.
        assert by_host.get("news.example.com") == 2
        assert by_host.get("t.co") == 1
        # The self-referral is excluded.
        assert "easstation.com" not in by_host


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
            "language_breakdown", "error_pages", "error_sources",
            "hourly_distribution", "weekday_distribution", "recent_requests",
            "login_summary", "login_timeseries", "top_login_ips", "recent_logins",
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
    # Purge-all (full reset) endpoint is registered.
    assert "/api/traffic/purge-all" in rules


def test_purge_all_deletes_every_row(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats
    from app_core.analytics.traffic_privacy import purge_all
    from app_core.analytics.web_traffic import WebRequestLog

    with app.app_context():
        _add_request(db, ip_address="192.168.1.10")
        _add_request(db, ip_address="203.0.113.7")
        _add_request(db, ip_address="198.51.100.4")
        assert WebRequestLog.query.count() == 3

        result = purge_all()
        assert result["deleted"] == 3
        assert WebRequestLog.query.count() == 0
        # A fresh dashboard reflects the empty dataset.
        assert traffic_stats.get_summary(days=30)["total_hits"] == 0


def test_dashboard_cache_returns_fresh_when_disabled(app_with_db):
    """use_cache=False (default) must always reflect the current rows."""
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        traffic_stats.invalidate_dashboard_cache()
        _add_request(db, path="/dashboard")
        first = traffic_stats.get_full_dashboard(days=30)
        assert first["summary"]["total_hits"] == 1

        _add_request(db, path="/alerts")
        # Without caching, the second call sees the new row immediately.
        second = traffic_stats.get_full_dashboard(days=30)
        assert second["summary"]["total_hits"] == 2


def test_dashboard_cache_serves_then_invalidates(app_with_db):
    """use_cache=True serves a cached payload until it's invalidated."""
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        traffic_stats.invalidate_dashboard_cache()
        _add_request(db, path="/dashboard")
        first = traffic_stats.get_full_dashboard(days=30, use_cache=True)
        assert first["summary"]["total_hits"] == 1

        # A new row is hidden by the still-warm cache (same preset key).
        _add_request(db, path="/alerts")
        cached = traffic_stats.get_full_dashboard(days=30, use_cache=True)
        assert cached["summary"]["total_hits"] == 1

        # Invalidation (as a purge/anonymize would trigger) forces a recompute.
        traffic_stats.invalidate_dashboard_cache()
        fresh = traffic_stats.get_full_dashboard(days=30, use_cache=True)
        assert fresh["summary"]["total_hits"] == 2
        traffic_stats.invalidate_dashboard_cache()


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


def test_summary_includes_bandwidth(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, content_length=1000)
        _add_request(db, content_length=3000)
        _add_request(db, content_length=None)  # nulls ignored in averages

        summary = traffic_stats.get_summary(days=30)
        assert summary["total_bytes"] == 4000
        assert summary["avg_bytes"] == 2000


def test_error_reports(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, path="/wp-login.php", status_code=404, ip_address="66.249.0.1")
        _add_request(db, path="/wp-login.php", status_code=404, ip_address="66.249.0.1")
        _add_request(db, path="/.env", status_code=404, ip_address="66.249.0.1")
        _add_request(db, path="/ok", status_code=200, ip_address="192.168.1.10")

        pages = traffic_stats.get_error_pages(days=30)
        top = pages[0]
        assert top["path"] == "/wp-login.php"
        assert top["status_code"] == 404
        assert top["hits"] == 2

        sources = traffic_stats.get_error_sources(days=30)
        assert sources[0]["ip_address"] == "66.249.0.1"
        assert sources[0]["errors"] == 3
        # Each source is annotated with the path it errors on most + that status.
        assert sources[0]["top_path"] == "/wp-login.php"
        assert sources[0]["top_status"] == 404
        assert sources[0]["top_path_hits"] == 2


def test_visits_entry_exit_and_duration(app_with_db):
    app, db = app_with_db
    from datetime import timedelta

    from app_core.analytics import traffic_stats
    from app_utils import utc_now

    base = utc_now() - timedelta(hours=2)
    with app.app_context():
        # One visit by .10: /landing -> /alerts, 5 minutes apart.
        _add_request(db, ip_address="203.0.113.10", path="/landing", timestamp=base)
        _add_request(db, ip_address="203.0.113.10", path="/alerts",
                     timestamp=base + timedelta(minutes=5))
        # A second, separate visit by .10 an hour later (> 30 min gap).
        _add_request(db, ip_address="203.0.113.10", path="/dashboard",
                     timestamp=base + timedelta(minutes=90))
        # A bot hit must not count as a visit.
        _add_request(db, ip_address="66.249.0.1", path="/x", is_bot=True,
                     timestamp=base)

        v = traffic_stats.get_visits(days=30)
        assert v["visits"] == 2  # two human sessions, bot excluded
        entries = {e["path"]: e["count"] for e in v["entry_pages"]}
        exits = {e["path"]: e["count"] for e in v["exit_pages"]}
        assert entries.get("/landing") == 1
        assert exits.get("/alerts") == 1
        assert v["avg_duration_seconds"] >= 0


def test_filetype_breakdown(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, path="/dashboard")          # page (no ext)
        _add_request(db, path="/robots.txt")          # txt
        _add_request(db, path="/data/report.json")    # json

        types = {r["filetype"]: r["count"] for r in traffic_stats.get_filetype_breakdown(days=30)}
        assert types.get("(page)") == 1
        assert types.get("txt") == 1
        assert types.get("json") == 1


def test_search_terms_from_referrer(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, referer="https://www.google.com/search?q=emergency+alerts")
        _add_request(db, referer="https://duckduckgo.com/?q=eas+station")
        _add_request(db, referer="https://news.example.com/article")  # not a search engine

        terms = {t["term"]: t["count"] for t in traffic_stats.get_search_terms(days=30)}
        assert terms.get("emergency alerts") == 1
        assert terms.get("eas station") == 1


def test_bot_breakdown(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, is_bot=True, user_agent="Mozilla/5.0 (compatible; Googlebot/2.1)")
        _add_request(db, is_bot=True, user_agent="Mozilla/5.0 (compatible; Googlebot/2.1)")
        _add_request(db, is_bot=True, user_agent="Mozilla/5.0 (compatible; bingbot/2.0)")

        bots = {b["bot"]: b["hits"] for b in traffic_stats.get_bot_breakdown(days=30)}
        assert bots.get("Googlebot") == 2
        assert bots.get("Bingbot") == 1


def test_classify_bot():
    from app_core.analytics.web_traffic import classify_bot

    assert classify_bot("Mozilla/5.0 (compatible; Googlebot/2.1)") == "Googlebot"
    assert classify_bot("AhrefsBot/7.0") == "AhrefsBot"
    assert classify_bot("Mozilla/5.0 Firefox/120") == "Other bot"
    assert classify_bot(None) == "Unknown bot"


def test_time_distributions(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db)
        hourly = traffic_stats.get_hourly_distribution(days=30)
        assert len(hourly["labels"]) == 24
        assert len(hourly["hits"]) == 24
        assert sum(hourly["hits"]) == 1

        weekday = traffic_stats.get_weekday_distribution(days=30)
        assert len(weekday["labels"]) == 7
        assert sum(weekday["hits"]) == 1


def test_geoip_upload_route_registered(app_with_db):
    app, db = app_with_db
    import logging
    from webapp import routes_traffic

    routes_traffic.register(app, logging.getLogger("test"))
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/api/traffic/geoip/upload" in rules


def test_maxmind_magic_detection():
    from webapp.routes_traffic import _has_maxmind_magic

    # The metadata marker near the end identifies a real .mmdb even without the
    # maxminddb reader installed.
    valid = b"\x00" * 5000 + b"\xab\xcd\xefMaxMind.com" + b"metadata-bytes"
    assert _has_maxmind_magic(valid) is True
    # Arbitrary content (e.g. a PNG or text file) is rejected.
    assert _has_maxmind_magic(b"not a database, just some bytes") is False
    assert _has_maxmind_magic(b"") is False


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


# ---------------------------------------------------------------------------
# New dashboard reports: devices, methods, auth, search engines, slowest,
# bounce rate, and previous-window deltas.
# ---------------------------------------------------------------------------

def test_device_breakdown_classifies_platforms(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, os="Windows 10/11", user_agent="Mozilla/5.0 (Windows NT 10.0)")
        _add_request(db, os="macOS", user_agent="Mozilla/5.0 (Macintosh)")
        _add_request(db, os="iOS", user_agent="Mozilla/5.0 (iPhone) Mobile/15E148")
        _add_request(db, os="Android", user_agent="Mozilla/5.0 (Linux; Android 13) Mobile")
        _add_request(db, os="iPadOS", user_agent="Mozilla/5.0 (iPad)")
        # Bot rows must be excluded from the human device split.
        _add_request(db, os="Linux", is_bot=True, user_agent="Googlebot/2.1")

        devices = {r["device"]: r["count"] for r in traffic_stats.get_device_breakdown(days=30)}
        assert devices.get("Desktop") == 2   # Windows + macOS
        assert devices.get("Mobile") == 2     # iOS + Android phone
        assert devices.get("Tablet") == 1     # iPadOS


def test_method_breakdown_counts_verbs(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, method="GET")
        _add_request(db, method="GET")
        _add_request(db, method="POST")

        methods = {r["method"]: r["count"] for r in traffic_stats.get_method_breakdown(days=30)}
        assert methods.get("GET") == 2
        assert methods.get("POST") == 1


def test_auth_breakdown_splits_authenticated(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, is_authenticated=True)
        _add_request(db, is_authenticated=False)
        _add_request(db, is_authenticated=False)
        _add_request(db, is_authenticated=True, is_bot=True)  # bot excluded

        auth = {r["label"]: r["count"] for r in traffic_stats.get_auth_breakdown(days=30)}
        assert auth.get("Authenticated") == 1
        assert auth.get("Anonymous") == 2


def test_search_engine_breakdown_from_referrer(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, referer="https://www.google.com/search?q=eas")
        _add_request(db, referer="https://www.bing.com/search?q=eas")
        _add_request(db, referer="https://duckduckgo.com/?q=eas")
        _add_request(db, referer="https://example.com/page")  # not a search engine

        engines = {r["engine"]: r["count"] for r in traffic_stats.get_search_engine_breakdown(days=30)}
        assert engines.get("Google") == 1
        assert engines.get("Bing") == 1
        assert engines.get("DuckDuckGo") == 1
        assert "example.com" not in engines


def test_slowest_pages_ranks_by_avg_response(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        # /slow needs >= min_hits timed requests to qualify.
        for _ in range(3):
            _add_request(db, path="/slow", response_time_ms=900)
        for _ in range(3):
            _add_request(db, path="/fast", response_time_ms=10)
        # Below the min-hits threshold -> excluded even though it's slow.
        _add_request(db, path="/rare", response_time_ms=5000)

        slow = traffic_stats.get_slowest_pages(days=30, min_hits=3)
        paths = [r["path"] for r in slow]
        assert paths[0] == "/slow"
        assert "/rare" not in paths
        assert slow[0]["avg_response_ms"] == 900


def test_visits_report_bounce_rate(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats
    from app_utils import utc_now

    base = utc_now()
    with app.app_context():
        # Visitor A: single page view -> a bounce.
        _add_request(db, ip_address="203.0.113.1", path="/landing", timestamp=base)
        # Visitor B: two page views in one visit -> not a bounce.
        _add_request(db, ip_address="203.0.113.2", path="/a",
                     timestamp=base + timedelta(seconds=1))
        _add_request(db, ip_address="203.0.113.2", path="/b",
                     timestamp=base + timedelta(seconds=30))

        visits = traffic_stats.get_visits(days=30)
        assert visits["visits"] == 2
        assert visits["single_page_visits"] == 1
        assert visits["bounce_rate"] == 50.0


def test_summary_previous_window(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats
    from app_utils import utc_now

    now = utc_now()
    with app.app_context():
        # Current window (within the last `days`).
        _add_request(db, timestamp=now - timedelta(days=1))
        # Previous window (between `days` and `2*days` ago).
        _add_request(db, timestamp=now - timedelta(days=10))
        _add_request(db, timestamp=now - timedelta(days=12))

        prev = traffic_stats.get_summary_previous(days=7)
        # Only the two rows in the preceding 7-day window are counted.
        assert prev["total_hits"] == 2


# ---------------------------------------------------------------------------
# IPv6 visitor grouping + state/region surfacing
# ---------------------------------------------------------------------------

def test_network_key_groups_ipv6_by_prefix():
    from app_core.analytics.geo import network_key

    # IPv4 addresses are their own key.
    assert network_key("203.0.113.7") == "203.0.113.7"
    # Two IPv6 privacy addresses in the same /64 collapse to one key.
    a = network_key("2001:db8:abcd:1234::1")
    b = network_key("2001:db8:abcd:1234:ffff:ffff:ffff:ffff")
    assert a == b == "2001:db8:abcd:1234::/64"
    # A different /64 is a different key.
    assert network_key("2001:db8:abcd:9999::1") != a
    # Junk / missing never raises.
    assert network_key("not-an-ip") == "not-an-ip"
    assert network_key(None) is None


def test_unique_visitors_collapse_ipv6_prefix(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        # Same household /64, three rotating privacy addresses -> 1 visitor.
        _add_request(db, ip_address="2001:db8:1:2::a")
        _add_request(db, ip_address="2001:db8:1:2::b")
        _add_request(db, ip_address="2001:db8:1:2:dead:beef::c")
        # A distinct IPv4 visitor.
        _add_request(db, ip_address="198.51.100.5")

        summary = traffic_stats.get_summary(days=30)
        assert summary["total_hits"] == 4
        # 1 IPv6 /64 + 1 IPv4 = 2 unique visitors (not 4).
        assert summary["unique_visitors"] == 2


def test_city_breakdown_includes_region_label(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, ip_address="8.8.8.8", city="Springfield",
                     region="Illinois", region_code="IL")
        _add_request(db, ip_address="8.8.4.4", city="Springfield",
                     region="Missouri", region_code="MO")

        rows = {r["region_code"]: r for r in traffic_stats.get_city_breakdown(days=30)}
        # Same city name, two different states -> two distinguishable rows.
        assert "Springfield, IL" in {r["label"] for r in rows.values()}
        assert "Springfield, MO" in {r["label"] for r in rows.values()}


def test_region_breakdown_groups_states_for_map(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        # Two hits from Ohio, one from California, one from a non-US country.
        _add_request(db, ip_address="8.8.8.8", country="United States",
                     country_code="US", region="Ohio", region_code="OH")
        _add_request(db, ip_address="8.8.8.9", country="United States",
                     country_code="US", region="Ohio", region_code="OH")
        _add_request(db, ip_address="8.8.4.4", country="United States",
                     country_code="US", region="California", region_code="CA")
        _add_request(db, ip_address="1.1.1.1", country="Australia",
                     country_code="AU", region="New South Wales", region_code="NSW")
        # No region at all -> must be excluded from the breakdown.
        _add_request(db, ip_address="9.9.9.9", country="United States",
                     country_code="US")

        rows = traffic_stats.get_region_breakdown(days=30)
        by_code = {(r["country_code"], r["region_code"]): r["count"] for r in rows}

        assert by_code[("US", "OH")] == 2
        assert by_code[("US", "CA")] == 1
        assert by_code[("AU", "NSW")] == 1
        # Rows without a region_code are not included.
        assert all(r["region_code"] is not None for r in rows)


def test_region_breakdown_in_dashboard_payload(app_with_db):
    app, db = app_with_db
    from app_core.analytics import traffic_stats

    with app.app_context():
        _add_request(db, ip_address="8.8.8.8", country="United States",
                     country_code="US", region="Texas", region_code="TX")
        payload = traffic_stats.get_full_dashboard()
        assert "region_breakdown" in payload
        assert any(r["region_code"] == "TX" for r in payload["region_breakdown"])


def test_classify_location_surfaces_region_keys():
    from app_core.analytics.geo import classify_location

    # Even without a GeoIP DB, the public-address fallback now carries the
    # region keys (as None) so the recorder can store them uniformly.
    public = classify_location("8.8.8.8")
    assert "region" in public and "region_code" in public
    assert public["region"] is None


# ---------------------------------------------------------------------------
# Reverse-DNS hostname backfill (fills NULL hostnames over time)
# ---------------------------------------------------------------------------

def test_recorder_backfills_missing_hostnames(app_with_db, monkeypatch):
    app, db = app_with_db
    from app_core.analytics import geo
    from app_core.analytics.traffic_recorder import TrafficRecorder
    from app_core.analytics.web_traffic import WebRequestLog
    from app_utils import utc_now

    geo._hostname_cache.clear()

    def fake_resolve(ip, *a, return_status=False, **k):
        # Only 1.1.1.1 has a PTR record; 9.9.9.9 has none (authoritative miss).
        if ip == "1.1.1.1":
            return ("one.one.one.one", "resolved") if return_status else "one.one.one.one"
        return (None, "no_record") if return_status else None

    monkeypatch.setattr(geo, "resolve_hostname", fake_resolve)

    with app.app_context():
        # Rows captured with NULL hostname (e.g. before "Resolve hostnames" was on).
        for ip in ("1.1.1.1", "1.1.1.1", "9.9.9.9"):
            db.session.add(WebRequestLog(
                timestamp=utc_now(), method="GET", path="/x", status_code=200,
                ip_address=ip, is_authenticated=False, is_api=False, is_bot=False,
            ))
        db.session.commit()

        recorder = TrafficRecorder(app)
        recorder._config["resolve_hostnames"] = True
        recorder._last_hostname_backfill_at = -1e9  # force the interval gate open
        recorder._maybe_backfill_hostnames()

        # Resolvable IP: every NULL row for it is filled in.
        resolved = WebRequestLog.query.filter_by(ip_address="1.1.1.1").all()
        assert resolved and all(r.hostname == "one.one.one.one" for r in resolved)
        # No-PTR IP stays NULL but is remembered so it isn't re-queried each pass.
        unresolved = WebRequestLog.query.filter_by(ip_address="9.9.9.9").first()
        assert unresolved.hostname is None
        assert "9.9.9.9" in recorder._hostname_tried


def test_recorder_backfill_retries_transient_failure(app_with_db, monkeypatch):
    """A transient ('error') backfill miss is not blacklisted, so it retries.

    Regression for IPv6: a slow ip6.arpa lookup that times out must not be
    remembered as a permanent miss the way an authoritative no-PTR result is.
    """
    app, db = app_with_db
    from app_core.analytics import geo
    from app_core.analytics.traffic_recorder import TrafficRecorder
    from app_core.analytics.web_traffic import WebRequestLog
    from app_utils import utc_now

    geo._hostname_cache.clear()
    attempts = {"n": 0}

    def fake_resolve(ip, *a, return_status=False, **k):
        attempts["n"] += 1
        # First attempt times out (transient); a later attempt succeeds.
        if attempts["n"] == 1:
            return (None, "error") if return_status else None
        return ("late.example.net", "resolved") if return_status else "late.example.net"

    monkeypatch.setattr(geo, "resolve_hostname", fake_resolve)

    with app.app_context():
        db.session.add(WebRequestLog(
            timestamp=utc_now(), method="GET", path="/x", status_code=200,
            ip_address="2001:4860:4860::8888", is_authenticated=False,
            is_api=False, is_bot=False,
        ))
        db.session.commit()

        recorder = TrafficRecorder(app)
        recorder._config["resolve_hostnames"] = True

        # First pass: transient failure -> NULL, and NOT remembered.
        recorder._last_hostname_backfill_at = -1e9
        recorder._maybe_backfill_hostnames()
        assert "2001:4860:4860::8888" not in recorder._hostname_tried
        assert WebRequestLog.query.first().hostname is None

        # Second pass: retried (because it wasn't blacklisted) and now resolves.
        recorder._last_hostname_backfill_at = -1e9
        recorder._maybe_backfill_hostnames()
        assert WebRequestLog.query.first().hostname == "late.example.net"


def test_recorder_backfill_noop_when_disabled(app_with_db, monkeypatch):
    app, db = app_with_db
    from app_core.analytics import geo
    from app_core.analytics.traffic_recorder import TrafficRecorder
    from app_core.analytics.web_traffic import WebRequestLog
    from app_utils import utc_now

    monkeypatch.setattr(geo, "resolve_hostname", lambda ip, *a, **k: "should-not-be-used")

    with app.app_context():
        db.session.add(WebRequestLog(
            timestamp=utc_now(), method="GET", path="/x", status_code=200,
            ip_address="1.1.1.1", is_authenticated=False, is_api=False, is_bot=False,
        ))
        db.session.commit()

        recorder = TrafficRecorder(app)
        recorder._config["resolve_hostnames"] = False
        recorder._last_hostname_backfill_at = -1e9
        recorder._maybe_backfill_hostnames()

        row = WebRequestLog.query.filter_by(ip_address="1.1.1.1").first()
        assert row.hostname is None
