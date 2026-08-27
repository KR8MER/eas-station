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

"""Tests for GET /api/alerts/<id>/radar-loop.

The route itself is a thin wrapper -- app_utils.image_export.radar_loop's
own test suite (test_image_export_radar_loop.py) covers the actual frame
logic in depth. This just pins the three ways the route can reject a
request before ever calling build_radar_loop(), plus one real end-to-end
call (mocking the WMS fetch so it stays offline) to catch a wiring mistake
between the route and build_radar_loop's return shape.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app_core.extensions import db
from app_core.models import AdminUser, CAPAlert
from app_utils import utc_now

_DB_URL = None
import os
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
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_admin(app, client):
    """Log the test client in against the *real* auth gate.

    Both routes under test (``alert_detail`` and ``get_alert_radar_loop``)
    carry no ``@require_auth``/``@require_role`` decorator -- they rely
    entirely on the deny-by-default check in ``app.py``'s global
    ``before_request``, which populates ``g.current_user`` by loading a
    real ``AdminUser`` row for ``session['user_id']`` directly from the
    database. That check never calls ``get_current_user()``, so the
    ``authenticated_user`` fixture (which only monkeypatches that function)
    does not satisfy it -- every request here would 401 or redirect to
    /login regardless. A real row plus a real session value is the only
    thing that works.
    """
    with app.app_context():
        db.session.query(AdminUser).filter_by(username="radar-loop-route-test-admin").delete(
            synchronize_session=False
        )
        db.session.commit()

        user = AdminUser(username="radar-loop-route-test-admin", is_active=True)
        user.set_password("not-a-real-password")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    yield user_id

    with app.app_context():
        db.session.query(AdminUser).filter_by(id=user_id).delete(synchronize_session=False)
        db.session.commit()


@pytest.fixture
def met_alert_with_geom(app):
    with app.app_context():
        db.session.query(CAPAlert).filter(
            CAPAlert.identifier == "radar-loop-route-test-met"
        ).delete(synchronize_session=False)
        db.session.commit()

        now = utc_now()
        alert = CAPAlert(
            identifier="radar-loop-route-test-met",
            status="Actual",
            # Both already over -- build_radar_loop clips the window at
            # expires (not "now") once expires has passed, so the window is
            # sent..expires = 50 minutes, not sent..now = 60.
            expires=now - timedelta(minutes=10),
            sent=now - timedelta(hours=1),
            event="Severe Thunderstorm Warning",
            headline="Test", message_type="Alert", scope="Public",
            category="Met", source="TEST",
        )
        db.session.add(alert)
        db.session.commit()
        db.session.execute(
            db.text(
                "UPDATE cap_alerts SET geom = ST_GeomFromGeoJSON(:geom) WHERE id = :id"
            ),
            {
                "geom": '{"type":"Polygon","coordinates":[[[-84.3,41.1],[-83.85,40.86],'
                        '[-83.9,40.72],[-84.22,40.61],[-84.3,41.1]]]}',
                "id": alert.id,
            },
        )
        db.session.commit()
        alert_id = alert.id

        yield alert_id

        db.session.query(CAPAlert).filter_by(id=alert_id).delete()
        db.session.commit()


@pytest.fixture
def non_met_alert(app):
    with app.app_context():
        db.session.query(CAPAlert).filter(
            CAPAlert.identifier == "radar-loop-route-test-nonmet"
        ).delete(synchronize_session=False)
        db.session.commit()

        now = utc_now()
        alert = CAPAlert(
            identifier="radar-loop-route-test-nonmet",
            status="Actual", expires=now + timedelta(hours=1), sent=now,
            event="Local Area Emergency", headline="Test", message_type="Alert",
            scope="Public", category="Transport", source="TEST",
        )
        db.session.add(alert)
        db.session.commit()
        alert_id = alert.id

        yield alert_id

        db.session.query(CAPAlert).filter_by(id=alert_id).delete()
        db.session.commit()


def test_missing_alert_returns_404(client, logged_in_admin):
    resp = client.get("/api/alerts/999999999/radar-loop")
    assert resp.status_code == 404


def test_non_met_alert_returns_400(client, non_met_alert, logged_in_admin):
    resp = client.get(f"/api/alerts/{non_met_alert}/radar-loop")
    assert resp.status_code == 400
    assert "weather" in resp.get_json()["error"].lower()


def test_met_alert_without_geometry_returns_400(client, app, logged_in_admin):
    with app.app_context():
        now = utc_now()
        alert = CAPAlert(
            identifier="radar-loop-route-test-no-geom",
            status="Actual", expires=now + timedelta(hours=1), sent=now,
            event="Special Weather Statement", headline="Test", message_type="Alert",
            scope="Public", category="Met", source="TEST",
        )
        db.session.add(alert)
        db.session.commit()
        alert_id = alert.id

    try:
        resp = client.get(f"/api/alerts/{alert_id}/radar-loop")
        assert resp.status_code == 400
        assert "geometry" in resp.get_json()["error"].lower()
    finally:
        with app.app_context():
            db.session.query(CAPAlert).filter_by(id=alert_id).delete()
            db.session.commit()


def test_met_alert_with_geometry_builds_frames(client, met_alert_with_geom, logged_in_admin):
    from PIL import Image

    with patch(
        "app_utils.image_export.radar_loop._render_map",
        return_value=Image.new("RGB", (4, 4), (0, 128, 0)),
    ):
        resp = client.get(f"/api/alerts/{met_alert_with_geom}/radar-loop")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 11  # sent to expires, 5-min cadence, 50 min = 11 frames
    assert len(data["frames"]) > 0
    assert data["frames"][0]["url"].startswith(f"/static/radar_loops/{met_alert_with_geom}/")
