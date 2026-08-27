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

"""Regression test: the public /alerts page and its PDF export must hide
cancelled-but-not-yet-expired alerts by default, same as expired ones.

This was one of at least five independent, ad-hoc `expires > now` checks
scattered across the codebase (navbar stack light, physical tower light,
OLED/LED display, two live WebSocket pushes, and this public page) that all
predated app_core.alerts.get_active_alerts_query() and never adopted its
status.notin_(("Expired", "Cancelled")) exclusion. A CAP Cancel/Update can
set status='Cancelled' well before the original `expires` timestamp lapses
(see tests/test_cap_references_cancellation.py), so every one of those
independent checks kept showing a cancelled alert as current/active
indefinitely -- reported live 2026-08-27: an alert confirmed cancelled on
PBS WARN still showed active on the dashboard, the navbar stack light, and
the physical tower light.
"""

import os
from datetime import timedelta

import pytest

from app_core.extensions import db
from app_core.models import CAPAlert
from app_utils import utc_now
from webapp.public.alerts_page.filters import AlertFilters
from webapp.public.alerts_page.query import apply_visibility

# CAPAlert carries a PostGIS geometry column, so this cannot run against the
# in-memory SQLite database the default `app` fixture builds -- see
# tests/test_alert_active_expired_partition.py for the same pattern.
_DB_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _DB_URL.startswith(("postgresql", "postgres://")),
    reason="needs a PostgreSQL DATABASE_URL (CAPAlert uses a PostGIS geometry column)",
)


@pytest.fixture(scope="module")
def app():
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def cancelled_future_expiry_alert(app):
    """A CAP Cancel arrived early: status='Cancelled' but expires is still
    in the future, exactly like a real OHDOT Local Area Emergency alert
    observed in production."""
    with app.app_context():
        now = utc_now()
        db.session.query(CAPAlert).filter(
            CAPAlert.identifier == "public-page-cancelled-future"
        ).delete(synchronize_session=False)
        db.session.commit()

        alert = CAPAlert(
            identifier="public-page-cancelled-future",
            status="Cancelled",
            cancelled_at=now,
            expires=now + timedelta(hours=6),
            sent=now,
            event="Local Area Emergency",
            headline="Test cancellation",
            message_type="Alert",
            scope="Public",
            category="Met",
            source="TEST",
        )
        db.session.add(alert)
        db.session.commit()
        alert_id = alert.id

        yield alert_id

        db.session.query(CAPAlert).filter_by(id=alert_id).delete()
        db.session.commit()


def test_default_view_hides_a_cancelled_alert_even_with_future_expiry(app, cancelled_future_expiry_alert):
    with app.app_context():
        query = apply_visibility(CAPAlert.query, AlertFilters())
        ids = {a.id for a in query.all()}
        assert cancelled_future_expiry_alert not in ids


def test_show_expired_flag_still_reveals_it(app, cancelled_future_expiry_alert):
    """show_expired=True is the operator's explicit "show me everything"
    toggle -- it must still surface a cancelled alert, same as a genuinely
    expired one, or there'd be no way to review it at all."""
    with app.app_context():
        query = apply_visibility(CAPAlert.query, AlertFilters(show_expired=True))
        ids = {a.id for a in query.all()}
        assert cancelled_future_expiry_alert in ids
