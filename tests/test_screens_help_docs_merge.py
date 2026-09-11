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

Tests for the screens.html -> help.html documentation merge (site
reorganization Phase 3 -- see docs/roadmap/SITE_REORGANIZATION.md). The
"Documentation" tab on /screens (template variables, data sources, LED/VFD
examples) duplicated reference material for a different audience than the
operational screen-management UI it was bolted to, and pointed at
/static/docs/guides/CUSTOM_DISPLAY_SCREENS.md -- a file that does not exist
anywhere in the repo. The content moved into help.html's existing "Custom
Display Screens" accordion section instead of staying as a dead link.
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


class TestScreensPageNoLongerEmbedsDocs:
    def test_screens_page_has_no_documentation_tab(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query):
            response = client.get("/screens")

        assert response.status_code == 200
        assert b"docs-pane" not in response.data
        assert b"docs-tab" not in response.data
        # No longer points at the guide file that doesn't exist in the repo.
        assert b"CUSTOM_DISPLAY_SCREENS.md" not in response.data
        # Links out to the full documentation instead.
        assert b'href="/help"' in response.data


class TestHelpPageHasScreenDocumentation:
    def test_help_page_has_template_variables_and_examples(self, app):
        with patch("app.initialize_database", return_value=True):
            client = app.test_client()
            response = client.get("/help")

        assert response.status_code == 200
        body = response.data
        assert b"Template Variables" in body
        assert b"Available Data Sources" in body
        assert b"LED Screen Example" in body
        assert b"VFD Screen Example" in body
        assert b"{status.active_alerts_count}" in body
        # The dead external guide link is gone from here too.
        assert b"CUSTOM_DISPLAY_SCREENS.md" not in body
