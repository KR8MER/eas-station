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

"""Regression tests for app_core.alerts.calculate_alert_intersections().

psycopg2 has no adapter registered for geoalchemy2.elements.WKBElement --
the type the ORM hands back for any already-persisted geometry column --
so passing alert.geom directly into a raw text() bind parameter always
raised "can't adapt type 'WKBElement'" in production, on every call. This
silently broke both admin "Fix Intersections" routes that delegate to this
function (fix_county_intersections, recalculate_intersections) and the
automatic recalculation triggered by a boundary upload
(webapp/admin/intersections.py::recalculate_active_alert_intersections).

Confirmed against a real PostGIS database: identical failure with the
pre-fix code (str() not applied), resolved by stringifying alert.geom
before it is used as a bind parameter. str(WKBElement) gives its EWKB hex
encoding (.desc), which PostGIS parses natively as raw SQL text.
"""

from types import SimpleNamespace
from unittest.mock import patch

import app_core.alerts as alerts_module


class _GeomLike:
    """Stand-in for geoalchemy2.elements.WKBElement: stringifies to its EWKB
    hex representation and nothing else."""

    def __init__(self, hex_str: str):
        self._hex = hex_str

    def __str__(self) -> str:
        return self._hex

    def __bool__(self) -> bool:
        return True


class _CapturingSession:
    """Records every execute() call's bind parameters."""

    def __init__(self):
        self.executed_params = []
        self.rollbacks = 0

    def execute(self, statement, params=None):
        self.executed_params.append(dict(params or {}))

        class _Result:
            def all(self_inner):
                return []  # no intersecting boundaries -- irrelevant to this test

        return _Result()

    def rollback(self):
        self.rollbacks += 1

    def query(self, model):
        class _Query:
            def filter_by(self_inner, **kw):
                return self_inner

            def delete(self_inner, synchronize_session=None):
                return 0

        return _Query()


def test_fetch_bulk_intersections_stringifies_geometry_before_binding():
    session = _CapturingSession()
    geom = _GeomLike("0103000020E6100000DEADBEEF")

    with patch.object(alerts_module, "db", SimpleNamespace(session=session)), \
         patch.object(alerts_module, "_log_invalid_boundary_geometries", lambda: None):
        alerts_module._fetch_bulk_intersections(str(geom))

    assert session.executed_params, "expected at least one execute() call"
    params = session.executed_params[0]
    assert isinstance(params["alert_geom"], str)
    assert params["alert_geom"] == str(geom)


def test_calculate_alert_intersections_passes_stringified_geometry():
    session = _CapturingSession()
    geom = _GeomLike("0103000020E6100000DEADBEEF")
    alert = SimpleNamespace(id=1, identifier="CAP-GEOM-1", geom=geom)

    with patch.object(alerts_module, "db", SimpleNamespace(session=session)), \
         patch.object(alerts_module, "_log_invalid_boundary_geometries", lambda: None):
        result = alerts_module.calculate_alert_intersections(alert)

    assert result == 0  # no intersecting boundaries in this fake session
    assert session.executed_params, "expected the bulk query to run"
    params = session.executed_params[0]
    assert isinstance(params["alert_geom"], str), (
        "calculate_alert_intersections must stringify alert.geom before "
        "passing it to a raw text() bind parameter -- psycopg2 cannot "
        f"adapt a raw WKBElement; got {type(params['alert_geom']).__name__}"
    )
    assert params["alert_geom"] == str(geom)


def test_calculate_alert_intersections_returns_zero_without_geometry():
    session = _CapturingSession()
    alert = SimpleNamespace(id=1, identifier="CAP-NO-GEOM", geom=None)

    with patch.object(alerts_module, "db", SimpleNamespace(session=session)):
        result = alerts_module.calculate_alert_intersections(alert)

    assert result == 0
    assert session.executed_params == []
