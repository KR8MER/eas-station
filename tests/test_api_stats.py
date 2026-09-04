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

"""Tests for the API Dashboard's aggregation helpers (app_core/analytics/api_stats.py).

Mirrors tests/test_traffic_analytics.py's fixture (in-memory SQLite with the
traffic tables created) since api_stats.py reads the same WebRequestLog table.
"""

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
        from app_core.analytics.web_traffic import WebRequestLog

        WebRequestLog.__table__.create(db.engine)
        yield app, db


def _add_api_request(db, **overrides):
    from app_core.analytics.web_traffic import WebRequestLog
    from app_utils import utc_now

    row = WebRequestLog(
        timestamp=overrides.pop("timestamp", utc_now()),
        method=overrides.pop("method", "GET"),
        path=overrides.pop("path", "/api/alerts/1"),
        endpoint=overrides.pop("endpoint", "webapp.routes_alerts.api_get_alert"),
        status_code=overrides.pop("status_code", 200),
        response_time_ms=overrides.pop("response_time_ms", 50),
        is_api=overrides.pop("is_api", True),
        is_bot=overrides.pop("is_bot", False),
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    db.session.add(row)
    db.session.commit()
    return row


def test_get_api_summary_counts_and_error_rate(app_with_db):
    app, db = app_with_db
    with app.app_context():
        from app_core.analytics import api_stats

        for status in (200, 200, 200, 500):
            _add_api_request(db, status_code=status)
        # Non-API traffic must be excluded entirely.
        _add_api_request(db, is_api=False, path="/dashboard", endpoint="webapp.dashboard.index")

        summary = api_stats.get_api_summary(days=7)
        assert summary["total_requests"] == 4
        assert summary["error_count"] == 1
        assert summary["error_rate_pct"] == 25.0


def test_get_api_summary_percentiles(app_with_db):
    app, db = app_with_db
    with app.app_context():
        from app_core.analytics import api_stats

        # 10 requests, response times 10..100ms in steps of 10.
        for ms in range(10, 101, 10):
            _add_api_request(db, response_time_ms=ms)

        summary = api_stats.get_api_summary(days=7)
        # Nearest-rank percentile over the sorted [10,20,...,100] list
        # (round(pct/100 * (n-1)) as the index -- Python's banker's rounding
        # makes round(4.5) == 4, landing p50 on index 4 -> value 50).
        assert summary["p50_ms"] == 50
        assert summary["p95_ms"] == 100
        assert summary["p99_ms"] == 100


def test_get_api_by_route_groups_by_endpoint_not_raw_path(app_with_db):
    app, db = app_with_db
    with app.app_context():
        from app_core.analytics import api_stats

        # Two different raw paths (parameterized IDs) but the same endpoint
        # must collapse into a single route bucket.
        _add_api_request(db, path="/api/alerts/1", endpoint="webapp.routes_alerts.api_get_alert")
        _add_api_request(db, path="/api/alerts/2", endpoint="webapp.routes_alerts.api_get_alert")
        _add_api_request(db, path="/api/status", endpoint="webapp.routes_status.api_status", status_code=503)

        by_route = api_stats.get_api_by_route(days=7)
        by_endpoint = {r["endpoint"]: r for r in by_route}

        assert by_endpoint["webapp.routes_alerts.api_get_alert"]["hits"] == 2
        assert by_endpoint["webapp.routes_status.api_status"]["hits"] == 1
        assert by_endpoint["webapp.routes_status.api_status"]["error_rate_pct"] == 100.0
        # Sorted by hits descending.
        assert by_route[0]["endpoint"] == "webapp.routes_alerts.api_get_alert"


def test_get_api_by_route_excludes_rows_with_no_endpoint(app_with_db):
    app, db = app_with_db
    with app.app_context():
        from app_core.analytics import api_stats

        _add_api_request(db, endpoint=None)
        _add_api_request(db, endpoint="webapp.routes_alerts.api_get_alert")

        by_route = api_stats.get_api_by_route(days=7)
        assert len(by_route) == 1
        assert by_route[0]["endpoint"] == "webapp.routes_alerts.api_get_alert"


def test_get_api_timeseries_buckets_by_day_for_wide_window(app_with_db):
    from datetime import timedelta

    app, db = app_with_db
    with app.app_context():
        from app_core.analytics import api_stats
        from app_utils import utc_now

        now = utc_now()
        _add_api_request(db, timestamp=now)
        _add_api_request(db, timestamp=now - timedelta(days=1), status_code=500)

        series = api_stats.get_api_timeseries(days=7)
        assert series["granularity"] == "day"
        assert sum(series["hits"]) == 2
        assert sum(series["errors"]) == 1


def test_get_api_slowest_routes_respects_min_hits(app_with_db):
    app, db = app_with_db
    with app.app_context():
        from app_core.analytics import api_stats

        # Only 2 hits on a slow route -- below the default min_hits=3.
        _add_api_request(db, endpoint="webapp.routes_slow.api_slow", response_time_ms=5000)
        _add_api_request(db, endpoint="webapp.routes_slow.api_slow", response_time_ms=5000)
        for _ in range(3):
            _add_api_request(db, endpoint="webapp.routes_fast.api_fast", response_time_ms=10)

        slowest = api_stats.get_api_slowest_routes(days=7)
        endpoints = [r["endpoint"] for r in slowest]
        assert "webapp.routes_slow.api_slow" not in endpoints
        assert "webapp.routes_fast.api_fast" in endpoints


def test_get_api_top_errors_only_counts_4xx_5xx(app_with_db):
    app, db = app_with_db
    with app.app_context():
        from app_core.analytics import api_stats

        _add_api_request(db, endpoint="webapp.routes_alerts.api_get_alert", status_code=200)
        _add_api_request(db, endpoint="webapp.routes_alerts.api_get_alert", status_code=404)
        _add_api_request(db, endpoint="webapp.routes_alerts.api_get_alert", status_code=404)

        top_errors = api_stats.get_api_top_errors(days=7)
        assert len(top_errors) == 1
        assert top_errors[0]["status_code"] == 404
        assert top_errors[0]["hits"] == 2
