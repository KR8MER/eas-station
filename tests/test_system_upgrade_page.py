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

Tests for the System Upgrade page split (v3.0.0+, site reorganization
Phase 2 -- see docs/roadmap/SITE_REORGANIZATION.md): System Upgrade moved
out of templates/admin/operations.html to its own page at
GET /admin/system-upgrade, since it's a much bigger, riskier operation
(its own live progress/log-streaming UI) than the routine maintenance
chores it used to share a page with. Alert Boundary Coverage was removed
from operations.html entirely (not split -- it was a pure duplicate of
functionality already on the existing /admin/intersections page).
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
    """See tests/test_sms_settings_page.py's identical helper docstring
    (pre-seeds the admin-session-heartbeat cookie keys so before_request()'s
    heartbeat tracking doesn't try to touch the real admin_sessions table)."""
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


class TestSystemUpgradePage:
    def test_unauthenticated_rejected(self, app):
        client = app.test_client()
        response = client.get("/admin/system-upgrade")
        assert response.status_code in (302, 401)

    def test_renders_for_authenticated_admin(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query):
            response = client.get("/admin/system-upgrade")

        assert response.status_code == 200
        assert b"System Upgrade" in response.data
        assert b"upgrade-checkout-select" in response.data
        assert b"startUpgrade" in response.data

    def test_operations_page_no_longer_has_upgrade_or_boundary_panels(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query):
            response = client.get("/admin/operations")

        assert response.status_code == 200
        assert b"upgrade-checkout-select" not in response.data
        assert b"recalc-all-btn" not in response.data
        # It links out to the new/existing pages instead of embedding them.
        assert b"/admin/system-upgrade" in response.data
        assert b"/admin/intersections" in response.data
