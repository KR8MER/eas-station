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

"""Integration test for calculate_coverage_percentages()'s per-type county scoping.

The alert detail page showed per-service-type coverage percentages (e.g.
"Villages: 27.3%") that had no defined relationship to either the
county-level coverage percentage shown right next to them, or to the
"22 of 126 affected" counts elsewhere on the same page -- because the
denominator was scoped to only the boundaries this alert happened to touch,
not to the same "whole county" scope the county-level percentage uses.

Fixed to scope the denominator to every boundary of that type within the
*configured* county's polygon -- not every boundary of that type this
deployment has ever uploaded, which (per TestCoverageFallbackLogic in
tests/test_coverage_and_signature.py) can include a neighbouring county's
districts and would reintroduce the misleadingly-low-percentage bug that
test class guards against. This test constructs boundaries in two distinct,
non-overlapping "counties" to confirm the neighbouring county's boundaries
of the same type are excluded from the denominator.
"""

import os

import pytest

from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, Intersection
from app_utils import utc_now

_DB_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _DB_URL.startswith(("postgresql", "postgres://")),
    reason="needs a PostgreSQL DATABASE_URL (Boundary/CAPAlert use PostGIS geometry columns)",
)


@pytest.fixture(scope="module")
def app():
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


# Two well-separated "counties," each with its own fire boundaries. Putnam is
# the configured county; Allen is the neighbour whose fire districts must be
# excluded from Putnam's per-type denominator.
_PUTNAM_COUNTY = (
    '{"type":"Polygon","coordinates":[[[-84.6,41.3],[-83.9,41.3],'
    '[-83.9,40.7],[-84.6,40.7],[-84.6,41.3]]]}'
)
_ALLEN_COUNTY = (
    '{"type":"Polygon","coordinates":[[[-83.0,40.9],[-82.3,40.9],'
    '[-82.3,40.3],[-83.0,40.3],[-83.0,40.9]]]}'
)
# Two equal-area, non-overlapping squares inside Putnam County.
_FIRE_PUTNAM_1 = (
    '{"type":"Polygon","coordinates":[[[-84.3,41.1],[-84.2,41.1],'
    '[-84.2,41.0],[-84.3,41.0],[-84.3,41.1]]]}'
)
_FIRE_PUTNAM_2 = (
    '{"type":"Polygon","coordinates":[[[-84.1,41.1],[-84.0,41.1],'
    '[-84.0,41.0],[-84.1,41.0],[-84.1,41.1]]]}'
)
# A fire boundary inside neighbouring Allen County -- must not count toward
# Putnam's "fire" denominator even though it shares the type.
_FIRE_ALLEN_1 = (
    '{"type":"Polygon","coordinates":[[[-82.8,40.7],[-82.7,40.7],'
    '[-82.7,40.6],[-82.8,40.6],[-82.8,40.7]]]}'
)
# The alert exactly matches fire_putnam_1 -- 100% of it, 0% of fire_putnam_2.
_ALERT_GEOM = _FIRE_PUTNAM_1


@pytest.fixture
def county_scoped_fixture(app):
    with app.app_context():
        from app_core.location import update_location_settings

        names = [
            "Zzztestputnam County", "Zzztestallen County",
            "Zzztestputnam Fire 1", "Zzztestputnam Fire 2", "Zzztestallen Fire 1",
        ]
        db.session.query(Intersection).delete(synchronize_session=False)
        db.session.query(Boundary).filter(Boundary.name.in_(names)).delete(
            synchronize_session=False
        )
        db.session.query(CAPAlert).filter(
            CAPAlert.identifier == "coverage-county-scoping-test"
        ).delete(synchronize_session=False)
        db.session.commit()

        update_location_settings({
            "county_name": "Zzztestputnam County",
            "state_code": "OH",
            "timezone": "America/New_York",
            "fips_codes": [],
            "zone_codes": [],
            "area_terms": [],
        })

        putnam = Boundary(name="Zzztestputnam County", type="county")
        allen = Boundary(name="Zzztestallen County", type="county")
        fire_putnam_1 = Boundary(name="Zzztestputnam Fire 1", type="fire")
        fire_putnam_2 = Boundary(name="Zzztestputnam Fire 2", type="fire")
        fire_allen_1 = Boundary(name="Zzztestallen Fire 1", type="fire")
        db.session.add_all([putnam, allen, fire_putnam_1, fire_putnam_2, fire_allen_1])
        db.session.commit()

        for boundary, geojson in (
            (putnam, _PUTNAM_COUNTY),
            (allen, _ALLEN_COUNTY),
            (fire_putnam_1, _FIRE_PUTNAM_1),
            (fire_putnam_2, _FIRE_PUTNAM_2),
            (fire_allen_1, _FIRE_ALLEN_1),
        ):
            db.session.execute(
                db.text("UPDATE boundaries SET geom = ST_GeomFromGeoJSON(:geom) WHERE id = :id"),
                {"geom": geojson, "id": boundary.id},
            )
        db.session.commit()

        alert = CAPAlert(
            identifier="coverage-county-scoping-test",
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
        db.session.commit()
        db.session.execute(
            db.text("UPDATE cap_alerts SET geom = ST_GeomFromGeoJSON(:geom) WHERE id = :id"),
            {"geom": _ALERT_GEOM, "id": alert.id},
        )
        db.session.add(Intersection(cap_alert_id=alert.id, boundary_id=fire_putnam_1.id))
        db.session.commit()

        yield {"alert_id": alert.id, "fire_putnam_1_id": fire_putnam_1.id}

        db.session.query(Intersection).filter_by(cap_alert_id=alert.id).delete(
            synchronize_session=False
        )
        db.session.query(Boundary).filter(Boundary.name.in_(names)).delete(
            synchronize_session=False
        )
        db.session.query(CAPAlert).filter_by(id=alert.id).delete(synchronize_session=False)
        db.session.commit()


def test_per_type_denominator_excludes_neighbouring_county(app, county_scoped_fixture):
    with app.app_context():
        from app_core.models import Intersection as IntersectionModel
        from webapp.admin.coverage import calculate_coverage_percentages

        intersections = db.session.query(IntersectionModel, Boundary).join(
            Boundary, IntersectionModel.boundary_id == Boundary.id
        ).filter(IntersectionModel.cap_alert_id == county_scoped_fixture["alert_id"]).all()

        coverage_data = calculate_coverage_percentages(
            county_scoped_fixture["alert_id"], intersections
        )

        fire_data = coverage_data["fire"]
        # 2 Putnam fire districts, NOT 3 (excluding Allen's).
        assert fire_data["total_boundaries"] == 2
        assert fire_data["affected_boundaries"] == 1
        # Alert exactly covers fire_putnam_1 (equal area to fire_putnam_2,
        # which it doesn't touch at all) -> exactly half of Putnam's total
        # fire-district area is covered. This is the core assertion: it was
        # previously impossible for this figure to differ from 100% (the
        # narrower, pre-fix denominator only ever counted the already-
        # affected boundary itself), and it is now directly comparable to
        # the county-level percentage's own "fraction of the whole scope
        # covered" meaning.
        assert fire_data["coverage_percentage"] == pytest.approx(50.0, abs=1.0)
