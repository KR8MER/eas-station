"""Every alert must be either active or expired — never neither, never both.

``get_active_alerts_query()`` and ``get_expired_alerts_query()`` were written
independently, and the expired one only checked ``expires < now``. Active
additionally excluded ``status='Expired'``, ``status='Cancelled'`` and
superseded alerts, so an alert in one of those states with a *future* expiry
matched neither query and disappeared from the dashboard, the counts and the
archive at the same time. A cancelled-but-not-yet-expired alert vanishing
entirely is an operational problem: nothing in the UI shows it was cancelled.

These tests assert the two queries partition the table.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.extensions import db
from app_core.models import CAPAlert
from app_utils import utc_now

# CAPAlert carries a PostGIS geometry column, so these cannot run against the
# in-memory SQLite database the default `app` fixture builds. They exercise the
# real query SQL, which is the point — skip unless a PostgreSQL DATABASE_URL is
# configured (CI provides one; see .github/workflows/tests.yml).
_DB_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _DB_URL.startswith(("postgresql", "postgres://")),
    reason="needs a PostgreSQL DATABASE_URL (CAPAlert uses a PostGIS geometry column)",
)


@pytest.fixture(scope="module")
def app():
    """The real application object, bound to the configured PostgreSQL URL.

    Deliberately shadows the session-wide `app` fixture from conftest.py, which
    forces sqlite:///:memory: and therefore has no cap_alerts table.
    """
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app

# (label, status, expires offset from now or None, superseded)
CASES = [
    ("active", "Actual", timedelta(hours=1), False),
    ("already-expired", "Actual", timedelta(hours=-1), False),
    ("no-expiry", "Actual", None, False),
    ("status-expired-future-expiry", "Expired", timedelta(hours=1), False),
    ("status-cancelled-future-expiry", "Cancelled", timedelta(hours=1), False),
    ("superseded-future-expiry", "Actual", timedelta(hours=1), True),
]

EXPECTED_ACTIVE = {"active", "no-expiry"}


@pytest.fixture
def alert_partition_rows(app):
    """Insert one CAPAlert per interesting state, then clean up."""
    with app.app_context():
        now = utc_now()
        db.session.query(CAPAlert).filter(
            CAPAlert.identifier.like("partition-%")
        ).delete(synchronize_session=False)
        db.session.commit()

        created = []
        for label, status, offset, _superseded in CASES:
            alert = CAPAlert(
                identifier=f"partition-{label}",
                status=status,
                expires=(now + offset) if offset is not None else None,
                sent=now,
                event="Partition Test",
                headline=label,
                message_type="Alert",
                scope="Public",
                category="Met",
                source="TEST",
            )
            db.session.add(alert)
            created.append(alert)
        db.session.flush()

        anchor = created[0].id
        for alert, (_label, _status, _offset, superseded) in zip(created, CASES):
            if superseded:
                alert.superseded_by_id = anchor
        db.session.commit()

        yield {label: alert.id for alert, (label, *_rest) in zip(created, CASES)}

        db.session.query(CAPAlert).filter(
            CAPAlert.identifier.like("partition-%")
        ).delete(synchronize_session=False)
        db.session.commit()


def test_every_alert_is_active_or_expired_never_neither(app, alert_partition_rows):
    with app.app_context():
        active = {a.id for a in get_active_alerts_query().all()}
        expired = {a.id for a in get_expired_alerts_query().all()}

        invisible = [
            label
            for label, alert_id in alert_partition_rows.items()
            if alert_id not in active and alert_id not in expired
        ]
        assert not invisible, (
            "These alert states match neither get_active_alerts_query() nor "
            "get_expired_alerts_query(), so they vanish from every view in the "
            f"UI: {invisible}"
        )


def test_no_alert_is_both_active_and_expired(app, alert_partition_rows):
    with app.app_context():
        active = {a.id for a in get_active_alerts_query().all()}
        expired = {a.id for a in get_expired_alerts_query().all()}

        both = [
            label
            for label, alert_id in alert_partition_rows.items()
            if alert_id in active and alert_id in expired
        ]
        assert not both, f"Alert states counted twice in dashboard totals: {both}"


def test_active_set_is_exactly_the_expected_states(app, alert_partition_rows):
    with app.app_context():
        active = {a.id for a in get_active_alerts_query().all()}
        got = {
            label
            for label, alert_id in alert_partition_rows.items()
            if alert_id in active
        }
        assert got == EXPECTED_ACTIVE, (
            "An alert is active only when it has not passed its expiry, is not "
            "marked Expired/Cancelled, and has not been superseded."
        )


def test_expiry_boundary_is_not_a_gap(app):
    """expires == now must fall on one side, not slip between `<` and `>`."""
    with app.app_context():
        now = utc_now()
        alert = CAPAlert(
            identifier="partition-boundary",
            status="Actual",
            expires=now,
            sent=now,
            event="Partition Test",
            headline="boundary",
            message_type="Alert",
            scope="Public",
            category="Met",
            source="TEST",
        )
        db.session.add(alert)
        db.session.commit()
        try:
            active = {a.id for a in get_active_alerts_query().all()}
            expired = {a.id for a in get_expired_alerts_query().all()}
            assert (alert.id in active) or (alert.id in expired), (
                "An alert whose expires timestamp equals now matched neither "
                "query: active used `> now` and expired used `< now`."
            )
        finally:
            db.session.delete(alert)
            db.session.commit()
