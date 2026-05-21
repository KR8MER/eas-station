"""Tests for the unified alert trail collector.

Verifies that ``collect_alert_trail`` finds and merges rows from every
log-shaped table that carries the correlation ID into one chronological
timeline, with the right category classification on each event.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# Skip whole module if the Flask app stack isn't importable.
pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")


@pytest.fixture
def app_with_db():
    """Build a minimal Flask app + in-memory SQLite tied to the project's
    declarative_base, so we can exercise the real ORM models without
    needing PostgreSQL/PostGIS."""
    from flask import Flask
    from app_core.extensions import db

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    # Importing models triggers the SQLAlchemy event listener registration,
    # which is what auto-stamps alert_identifier on insert.
    from app_core import models  # noqa: F401

    with app.app_context():
        # CAPAlert and a couple of other models carry PostGIS/JSONB columns
        # SQLite can't realize.  Limit the schema we create to the tables
        # the trail collector actually queries against the in-memory DB.
        # SystemLog is a clean text-only table — use it as the smoke target.
        from app_core.models import SystemLog
        SystemLog.__table__.create(db.engine)
        yield app, db


def test_collector_returns_empty_payload_for_unknown_identifier(app_with_db):
    app, db = app_with_db
    from app_core.alert_trail import collect_alert_trail

    with app.app_context():
        payload = collect_alert_trail("DOES-NOT-EXIST-2026")

    assert payload["identifier"] == "DOES-NOT-EXIST-2026"
    assert payload["alert"] is None
    assert payload["messages"] == []
    assert payload["events"] == []
    assert all(v == 0 for v in payload["counts"].values())


def test_collector_finds_system_log_rows_by_identifier(app_with_db):
    """SystemLog rows tagged with alert_identifier appear in the timeline
    under the ``system`` category."""
    app, db = app_with_db
    from app_core.alert_trail import collect_alert_trail
    from app_core.logging_context import bind_alert
    from app_core.models import SystemLog

    cid = "TEST-CORRELATION-001"
    t0 = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)

    with app.app_context():
        # Two rows under the bound alert; one row outside (must not be picked).
        with bind_alert(cid):
            db.session.add(SystemLog(
                level="INFO", message="alert flow started",
                module="cap_poller", timestamp=t0,
            ))
            db.session.add(SystemLog(
                level="WARNING", message="forwarding suppressed: reason X",
                module="auto_forward", timestamp=t0 + timedelta(seconds=2),
            ))
        # No bind — must NOT be associated with our identifier.
        db.session.add(SystemLog(
            level="INFO", message="unrelated background work",
            module="hardware", timestamp=t0 + timedelta(seconds=5),
        ))
        db.session.commit()

        payload = collect_alert_trail(cid)

    assert len(payload["events"]) == 2, payload["events"]
    assert payload["counts"]["system"] == 2
    # Chronological order
    assert payload["events"][0]["timestamp"] <= payload["events"][1]["timestamp"]
    assert "alert flow started" in payload["events"][0]["summary"]
    assert payload["events"][1]["level"] == "WARNING"


def test_event_helper_drops_rows_without_timestamp():
    """Defensive: rows that somehow lack a timestamp must be dropped by
    ``_event``, not rendered at epoch.  Verified at the helper level
    because SQLAlchemy default factories repopulate NULL timestamps on
    flush, making this hard to exercise via the ORM."""
    from app_core.alert_trail import _event

    # No timestamp → dropped.
    assert _event(
        timestamp=None, category="system", source="x", summary="y",
    ) is None

    # Non-datetime → dropped.
    assert _event(
        timestamp="2026-05-21T12:00:00", category="system", source="x", summary="y",
    ) is None

    # Real datetime → kept.
    kept = _event(
        timestamp=datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc),
        category="system", source="x", summary="y",
    )
    assert kept is not None
    assert kept["category"] == "system"


def test_category_labels_cover_every_event_category(app_with_db):
    """The category_labels mapping in the payload must contain a label for
    every category emitted by the collector — otherwise the template would
    render bare category keys ("ingest", "gpio") instead of human labels."""
    app, db = app_with_db
    from app_core.alert_trail import CATEGORIES, collect_alert_trail
    from app_core.logging_context import bind_alert
    from app_core.models import SystemLog

    cid = "TEST-CORRELATION-003"
    with app.app_context():
        with bind_alert(cid):
            db.session.add(SystemLog(
                level="INFO", message="x", module="x",
                timestamp=datetime(2026, 5, 21, tzinfo=timezone.utc),
            ))
        db.session.commit()
        payload = collect_alert_trail(cid)

    for event in payload["events"]:
        assert event["category"] in CATEGORIES, (
            f"Category {event['category']!r} has no label in CATEGORIES"
        )
    assert payload["category_labels"] is CATEGORIES
