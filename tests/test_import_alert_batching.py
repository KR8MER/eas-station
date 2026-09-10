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

"""Tests for import_specific_alert()'s batched existence check.

A DB audit replaced this route's per-feature ``CAPAlert.query.filter_by(
identifier=...).first()`` (one query per row in the NOAA response) with a
single batched ``.filter(CAPAlert.identifier.in_(...))`` lookup done once
before the loop. The original per-iteration query saw same-batch inserts via
db.session.flush() -- a duplicate identifier appearing twice in one NOAA
response correctly became an insert-then-update. The batched version must
preserve that by tracking newly-inserted rows in the same lookup dict as it
goes, or a duplicate identifier in one batch would try to INSERT twice and
crash on the unique constraint.

Uses test_request_context + calling the view function directly (same
pattern as test_upgrade_progress.py) rather than app_client.post(), since a
real dispatched request also runs Flask's before_request DB-health gate,
which this suite's in-memory SQLite can't satisfy.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from app_core.extensions import db
from app_core.models import CAPAlert, SystemLog
from webapp.admin.maintenance.routes_import import import_specific_alert


def _feature(identifier: str) -> dict:
    """A NOAA CAP feature payload; content is irrelevant since
    parse_noaa_cap_alert is mocked to interpret it as just an identifier."""
    return {"properties": {"id": identifier}}


def _parsed(identifier: str) -> tuple:
    parsed = {
        "identifier": identifier,
        "sent": datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        "status": "Actual",
        "message_type": "Alert",
        "scope": "Public",
        "event": "Test Event",
    }
    return parsed, None  # geometry=None -- keeps assign_alert_geometry/
    # calculate_alert_intersections out of scope for this test


def _post(app, payload: dict):
    with app.test_request_context(
        "/admin/import_alert", method="POST", json=payload
    ):
        return import_specific_alert()


class TestImportSpecificAlertBatching:
    def test_inserts_and_updates_split_correctly(self, app, authenticated_user):
        """One pre-existing identifier (update) + one new one (insert)."""
        with app.app_context():
            db.metadata.create_all(bind=db.engine, tables=[CAPAlert.__table__, SystemLog.__table__])
            db.session.add(CAPAlert(**_parsed("EXISTING-1")[0]))
            db.session.commit()

        def fake_parse(feature):
            return _parsed(feature["properties"]["id"])

        with patch(
            "webapp.admin.maintenance.routes_import.retrieve_noaa_alerts",
            return_value=([_feature("EXISTING-1"), _feature("NEW-1")], "url", {}),
        ), patch(
            "webapp.admin.maintenance.routes_import.parse_noaa_cap_alert",
            side_effect=fake_parse,
        ), patch(
            "webapp.admin.maintenance.routes_import.assign_alert_geometry"
        ), patch(
            "webapp.admin.maintenance.routes_import.calculate_alert_intersections"
        ):
            response = _post(app, {"start": "2026-09-10T00:00:00Z", "end": "2026-09-10T23:59:59Z", "area": "OH"})

        assert response.status_code == 200
        data = response.get_json()
        assert data["inserted"] == 1
        assert data["updated"] == 1
        assert data["skipped"] == 0
        with app.app_context():
            assert CAPAlert.query.filter_by(identifier="NEW-1").count() == 1
            assert CAPAlert.query.filter_by(identifier="EXISTING-1").count() == 1

    def test_duplicate_identifier_within_one_batch_updates_not_double_inserts(
        self, app, authenticated_user
    ):
        """The exact regression this fix must not introduce: the same
        identifier appearing twice in one NOAA response (e.g. across two
        result pages) must become one insert + one update, never two
        inserts (which would crash on CAPAlert.identifier's unique
        constraint)."""
        with app.app_context():
            db.metadata.create_all(bind=db.engine, tables=[CAPAlert.__table__, SystemLog.__table__])

        def fake_parse(feature):
            return _parsed(feature["properties"]["id"])

        with patch(
            "webapp.admin.maintenance.routes_import.retrieve_noaa_alerts",
            return_value=(
                [_feature("DUP-1"), _feature("DUP-1")],
                "url",
                {},
            ),
        ), patch(
            "webapp.admin.maintenance.routes_import.parse_noaa_cap_alert",
            side_effect=fake_parse,
        ), patch(
            "webapp.admin.maintenance.routes_import.assign_alert_geometry"
        ), patch(
            "webapp.admin.maintenance.routes_import.calculate_alert_intersections"
        ):
            response = _post(app, {"start": "2026-09-10T00:00:00Z", "end": "2026-09-10T23:59:59Z", "area": "OH"})

        assert response.status_code == 200
        data = response.get_json()
        assert data["inserted"] == 1
        assert data["updated"] == 1
        with app.app_context():
            assert CAPAlert.query.filter_by(identifier="DUP-1").count() == 1
