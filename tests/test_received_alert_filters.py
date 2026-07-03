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

"""Tests for the received-alerts filter helpers (multi-select + exclusion).

Covers webapp/admin/audio/received_filters.py: parameter parsing,
include/exclude query behaviour, and chip/pagination query-string
generation.
"""

from datetime import datetime, timezone

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from werkzeug.datastructures import MultiDict

from app_core._models_alerts import ReceivedEASAlert
from app_core.extensions import db
from webapp.admin.audio.received_filters import (
    apply_filters,
    build_filter_chips,
    build_pager_qs,
    filter_params,
    parse_filters,
)


# SQLite cannot render the PostgreSQL JSONB columns some models declare;
# map them to plain JSON for the in-memory test database.
@compiles(JSONB, "sqlite")
def _render_jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def app():
    """Minimal Flask app bound to an in-memory SQLite database."""
    flask_app = Flask(__name__)
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["TESTING"] = True
    db.init_app(flask_app)

    with flask_app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[ReceivedEASAlert.__table__])
        yield flask_app
        db.session.remove()


def _parse(query_string_pairs):
    return parse_filters(MultiDict(query_string_pairs))


def _seed(app):
    """Seed alerts across several sources plus one with no event code."""
    when = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = [
        ReceivedEASAlert(received_at=when, source_name="ERN-LUC", event_code="RWT",
                         forwarding_decision="ignored"),
        ReceivedEASAlert(received_at=when, source_name="ERN-LUC", event_code="TOR",
                         forwarding_decision="forwarded"),
        ReceivedEASAlert(received_at=when, source_name="WXL51", event_code="RWT",
                         forwarding_decision="ignored"),
        ReceivedEASAlert(received_at=when, source_name="KEC63", event_code="SVR",
                         forwarding_decision="forwarded"),
        ReceivedEASAlert(received_at=when, source_name="NOAA-1", event_code=None,
                         forwarding_decision="ignored"),
    ]
    db.session.add_all(rows)
    db.session.commit()
    return rows


# ---------------------------------------------------------------------------
# parse_filters
# ---------------------------------------------------------------------------

def test_parse_multi_values_and_modes():
    filters = _parse([
        ("source", "ERN-LUC"), ("source", "WXL51"), ("source", " ERN-LUC "),
        ("source_mode", "EXCLUDE"),
        ("event", "RWT"),
        ("event_mode", "bogus"),
    ])
    # Duplicates collapse, whitespace stripped, order preserved
    assert filters["sources"] == ["ERN-LUC", "WXL51"]
    assert filters["source_mode"] == "exclude"
    assert filters["events"] == ["RWT"]
    # Invalid mode degrades to include
    assert filters["event_mode"] == "include"


def test_parse_ignores_invalid_dates_and_confidence():
    filters = _parse([
        ("date_from", "not-a-date"),
        ("date_to", "2026-07-02"),
        ("min_confidence", "5.0"),
    ])
    assert filters["date_from"] == ""
    assert filters["date_to"] == "2026-07-02"
    assert filters["min_confidence"] is None


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------

def test_include_multiple_sources(app):
    _seed(app)
    filters = _parse([("source", "ERN-LUC"), ("source", "WXL51")])
    rows = apply_filters(ReceivedEASAlert.query, filters).all()
    assert len(rows) == 3
    assert {r.source_name for r in rows} == {"ERN-LUC", "WXL51"}


def test_exclude_source_filters_it_out(app):
    _seed(app)
    filters = _parse([("source", "ERN-LUC"), ("source_mode", "exclude")])
    rows = apply_filters(ReceivedEASAlert.query, filters).all()
    names = {r.source_name for r in rows}
    assert "ERN-LUC" not in names
    assert names == {"WXL51", "KEC63", "NOAA-1"}


def test_exclude_events_hides_weekly_tests(app):
    _seed(app)
    filters = _parse([("event", "RWT"), ("event", "RMT"), ("event_mode", "exclude")])
    rows = apply_filters(ReceivedEASAlert.query, filters).all()
    # Rows without an event code must survive an exclusion filter
    assert {r.event_code for r in rows} == {"TOR", "SVR", None}


def test_include_events_combined_with_source_exclusion(app):
    _seed(app)
    filters = _parse([
        ("event", "RWT"),
        ("source", "WXL51"), ("source_mode", "exclude"),
    ])
    rows = apply_filters(ReceivedEASAlert.query, filters).all()
    assert len(rows) == 1
    assert rows[0].source_name == "ERN-LUC"
    assert rows[0].event_code == "RWT"


def test_no_filters_returns_everything(app):
    _seed(app)
    filters = _parse([])
    assert apply_filters(ReceivedEASAlert.query, filters).count() == 5


# ---------------------------------------------------------------------------
# filter_params / chips / pager
# ---------------------------------------------------------------------------

def test_filter_params_only_emit_meaningful_modes():
    # Mode without any values must not leak into the query string
    filters = _parse([("source_mode", "exclude"), ("event_mode", "exclude")])
    assert filter_params(filters) == []

    filters = _parse([("source", "A"), ("source_mode", "exclude")])
    assert filter_params(filters) == [("source", "A"), ("source_mode", "exclude")]

    # Include mode is the default and stays implicit
    filters = _parse([("source", "A")])
    assert filter_params(filters) == [("source", "A")]


def test_chip_removal_drops_orphaned_mode_marker():
    filters = _parse([("source", "A"), ("source_mode", "exclude")])
    chips = build_filter_chips(filters, per_page=25)
    assert len(chips) == 1
    assert chips[0]["label"] == "Not source"
    # Removing the only excluded source also removes source_mode
    assert "source_mode" not in chips[0]["remove_qs"]


def test_chip_removal_keeps_mode_for_remaining_values():
    filters = _parse([("source", "A"), ("source", "B"), ("source_mode", "exclude")])
    chips = build_filter_chips(filters, per_page=25)
    assert len(chips) == 2
    # Removing A keeps B and the exclude marker
    assert "source=B" in chips[0]["remove_qs"]
    assert "source_mode=exclude" in chips[0]["remove_qs"]


def test_chip_values_are_url_encoded():
    filters = _parse([("search", "tornado & flood"), ("source", "A")])
    chips = build_filter_chips(filters, per_page=25)
    source_chip = next(c for c in chips if c["label"] == "Source")
    assert "search=tornado+%26+flood" in source_chip["remove_qs"]


def test_pager_qs_carries_filters_and_per_page():
    filters = _parse([("source", "A"), ("source", "B"), ("decision", "ignored")])
    qs = build_pager_qs(filters, per_page=50)
    assert "source=A" in qs and "source=B" in qs
    assert "decision=ignored" in qs
    assert "per_page=50" in qs
