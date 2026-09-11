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

Tests for the data_management.html "Zone Catalog" tab removal (site
reorganization Phase 4 -- see docs/roadmap/SITE_REORGANIZATION.md). That
tab and the dedicated /admin/zones page both called the exact same
/admin/zones/* endpoints (webapp/admin/zones.py) -- a genuine duplicate,
not a different feature, despite an earlier extraction's docstring
claiming otherwise. Removed in favor of a link to /admin/zones.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _skip_real_db_init():
    """See tests/test_database_browser.py's identical fixture docstring."""
    with patch("app.initialize_database", return_value=True):
        yield


def _logged_in_client(app):
    """See tests/test_system_upgrade_page.py's identical helper docstring."""
    stub_role = SimpleNamespace(name="admin", has_permission=lambda _permission_name: True)
    stub_user = SimpleNamespace(id=1, is_active=True, role=stub_role)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = stub_user.id
        sess["admin_session_id"] = 1
        sess["admin_session_seen"] = int(time.time())

    mock_query = MagicMock()
    mock_query.get.return_value = stub_user
    return client, mock_query


class TestDataManagementPageNoLongerEmbedsZoneCatalog:
    def test_unauthenticated_rejected(self, app):
        client = app.test_client()
        response = client.get("/admin/data-management")
        assert response.status_code in (302, 401)

    def test_zone_catalog_tab_removed_and_links_to_dedicated_page(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query):
            response = client.get("/admin/data-management")

        assert response.status_code == 200
        body = response.data
        assert b"zone-catalog" not in body
        assert b"zones-subtab" not in body
        assert b"NOAA Zone Catalog Management" not in body
        assert b"js/admin/zone-catalog.js" not in body
        # Links out to the pre-existing dedicated page instead.
        assert b"/admin/zones" in body

        # The Boundaries and Manage tabs (genuinely related -- upload, then
        # browse/delete the same data) are untouched.
        assert b"boundaries-subtab" in body
        assert b"manage-subtab" in body
