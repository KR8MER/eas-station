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

"""GET /api/boundaries?alert_id=... scoping.

The alert detail page's map drew every boundary of a selected type
county-wide (e.g. all 126 villages) under an "Affected Boundaries" legend
label, while the sidebar right next to it correctly listed only the ones
the alert actually intersects (e.g. "22 of 126 affected") -- because the
map's fetch had no idea which alert it was looking at. Fixed by adding an
optional alert_id parameter that joins Intersection, the same table the
sidebar counts already come from. These tests pin: the filter actually
restricts results, boundaries outside the alert's intersections are
excluded, and every other caller of this endpoint (dashboard map, admin
boundary management) is unaffected by making alert_id optional.
"""

import os

import pytest

from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, Intersection
from app_utils import utc_now

_DB_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _DB_URL.startswith(("postgresql", "postgres://")),
    reason="needs a PostgreSQL DATABASE_URL (Boundary uses a PostGIS geometry column)",
)


@pytest.fixture(scope="module")
def app():
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


_SQUARE_A = '{"type":"Polygon","coordinates":[[[-84.3,41.1],[-84.2,41.1],[-84.2,41.0],[-84.3,41.0],[-84.3,41.1]]]}'
_SQUARE_B = '{"type":"Polygon","coordinates":[[[-83.3,40.1],[-83.2,40.1],[-83.2,40.0],[-83.3,40.0],[-83.3,40.1]]]}'


@pytest.fixture
def scoped_alert(app):
    """One CAPAlert, two 'village' Boundary rows, one Intersection linking
    the alert to only the first boundary -- mirrors a real alert that
    intersects some but not all boundaries of a type."""
    with app.app_context():
        db.session.query(Intersection).delete(synchronize_session=False)
        db.session.query(Boundary).filter(Boundary.name.like("Test Village%")).delete(
            synchronize_session=False
        )
        db.session.query(CAPAlert).filter(
            CAPAlert.identifier == "boundary-scoping-route-test"
        ).delete(synchronize_session=False)
        db.session.commit()

        alert = CAPAlert(
            identifier="boundary-scoping-route-test",
            sent=utc_now(),
            status="Actual",
            event="Test Event",
            headline="Test",
            message_type="Alert",
            scope="Public",
            category="Met",
            source="TEST",
        )
        db.session.add(alert)

        # "villages" (plural) is the canonical BOUNDARY_TYPE_CONFIG key --
        # normalize_boundary_type() maps the singular "village" alias to it
        # at query time, but a stored row must use the canonical form.
        affected = Boundary(name="Test Village Affected", type="villages")
        unaffected = Boundary(name="Test Village Unaffected", type="villages")
        db.session.add_all([affected, unaffected])
        db.session.commit()

        db.session.execute(
            db.text("UPDATE boundaries SET geom = ST_GeomFromGeoJSON(:geom) WHERE id = :id"),
            {"geom": _SQUARE_A, "id": affected.id},
        )
        db.session.execute(
            db.text("UPDATE boundaries SET geom = ST_GeomFromGeoJSON(:geom) WHERE id = :id"),
            {"geom": _SQUARE_B, "id": unaffected.id},
        )
        db.session.add(Intersection(cap_alert_id=alert.id, boundary_id=affected.id))
        db.session.commit()

        yield {"alert_id": alert.id, "affected_id": affected.id, "unaffected_id": unaffected.id}

        db.session.query(Intersection).filter_by(cap_alert_id=alert.id).delete(
            synchronize_session=False
        )
        db.session.query(Boundary).filter(
            Boundary.id.in_([affected.id, unaffected.id])
        ).delete(synchronize_session=False)
        db.session.query(CAPAlert).filter_by(id=alert.id).delete(synchronize_session=False)
        db.session.commit()


def _feature_ids(payload):
    return {f["properties"]["id"] for f in payload["features"]}


def test_alert_id_restricts_to_intersected_boundaries(client, scoped_alert):
    resp = client.get(f"/api/boundaries?type=village&alert_id={scoped_alert['alert_id']}")
    assert resp.status_code == 200
    ids = _feature_ids(resp.get_json())
    assert scoped_alert["affected_id"] in ids
    assert scoped_alert["unaffected_id"] not in ids


def test_omitting_alert_id_returns_every_boundary_of_the_type(client, scoped_alert):
    """Regression guard: the dashboard map, admin boundary management, and
    any other caller that never passes alert_id must see unchanged
    (unscoped) behavior."""
    resp = client.get("/api/boundaries?type=village")
    assert resp.status_code == 200
    ids = _feature_ids(resp.get_json())
    assert scoped_alert["affected_id"] in ids
    assert scoped_alert["unaffected_id"] in ids


def test_unrelated_alert_id_returns_no_boundaries_of_the_type(client, scoped_alert):
    """An alert_id with no Intersection rows at all for this boundary type
    must come back empty, not silently fall back to the unscoped list."""
    resp = client.get("/api/boundaries?type=village&alert_id=999999999")
    assert resp.status_code == 200
    assert resp.get_json()["features"] == []
