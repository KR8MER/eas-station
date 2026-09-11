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

Tests for the Bad Actor Blocklist page split (v3.0.0+, site reorganization
Phase 1 -- see docs/roadmap/SITE_REORGANIZATION.md): the panel moved out of
templates/admin/application_settings.html to its own page at
GET /admin/security/bad-actors/, since it's a fully independent subsystem
(own nginx config files, own systemd refresh timer, own JSON API) that only
shared a page with logging/storage/branding settings for lack of a better
home.
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


class TestBadActorBlocklistPage:
    def test_unauthenticated_rejected(self, app):
        client = app.test_client()
        response = client.get("/admin/security/bad-actors/")
        assert response.status_code in (302, 401)

    def test_renders_for_authenticated_admin(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query):
            response = client.get("/admin/security/bad-actors/")

        assert response.status_code == 200
        assert b"Bad Actor Blocklist" in response.data
        assert b"badActorsAllowList" in response.data

    def test_application_settings_no_longer_has_the_panel(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        mock_settings_query = MagicMock()
        mock_settings_query.first.return_value = SimpleNamespace(
            log_level="INFO", log_file="logs/eas_station.log",
            upload_folder="/opt/eas-station/uploads",
            backup_dir="/var/backups/eas-station",
            dashboard_headline="", dashboard_subtitle="",
            password_min_length=15, password_require_uppercase=False,
            password_require_lowercase=False, password_require_digits=False,
            password_require_special=False, password_expiration_days=0,
            httpbl_enabled=False, httpbl_api_key_set=False,
        )

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query), \
             patch("webapp.admin.application_settings.ApplicationSettings.query", mock_settings_query):
            response = client.get("/admin/application/")

        assert response.status_code == 200
        assert b"badActorsAllowList" not in response.data
        assert b"badActorsBase" not in response.data
        # It links out to the new page instead of embedding the panel.
        assert b"/admin/security/bad-actors/" in response.data
