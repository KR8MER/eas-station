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

Tests for the pgweb access gate: /api/internal/pgweb-auth-check (the nginx
auth_request target -- see the `listen 8081` server block in
config/nginx-eas-station.conf) and the /admin/database-browser/ status page.

pgweb has no authentication of its own, so this endpoint is the only thing
standing between "gated by login + system.configure" and "unauthenticated
full SQL access to the production database" for any deployment that has set
pgweb up (see docs/guides/DATABASE_BROWSER.md). Every status this endpoint
can return matters: nginx's auth_request module treats 2xx as allow, 401/403
as deny, and anything else as an upstream error (a bare 500 for the real
client) -- so these tests pin the exact status codes down, not just
"succeeds or fails".
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _skip_real_db_init():
    """before_request() calls app.initialize_database() (creates tables)
    on every non-setup-mode request. That trips over a real Postgres-only
    JSONB column against the app fixture's sqlite:///:memory: -- unrelated
    to anything this module tests, so short-circuit it the same way the
    app fixture's SKIP_DB_INIT env var wants to but before_request doesn't
    actually check."""
    with patch("app.initialize_database", return_value=True):
        yield


@pytest.fixture
def logged_in_client(app):
    """A test client with a real session cookie AND AdminUser.query.get()
    patched to resolve it, satisfying BOTH of this app's two independent
    "am I logged in" checks against the same fake user.

    tests/conftest.py's `authenticated_user` fixture only patches
    app_core.auth.roles.get_current_user() (what require_permission/
    has_permission call) -- it does nothing for app.py's before_request,
    which does its own separate session['user_id'] -> AdminUser.query.get()
    lookup to populate g.current_user and 401s/redirects before any view
    (or its decorators) ever runs. Both call sites resolve the same
    imported AdminUser class, so patching its query.get here satisfies
    both at once. Returns (client, stub_user) so a test can flip
    stub_user.role.has_permission per case.
    """
    stub_role = SimpleNamespace(name="admin", has_permission=lambda _permission_name: True)
    stub_user = SimpleNamespace(id=1, is_active=True, role=stub_role)

    import app as app_module

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = stub_user.id
    # Replace the whole `query` class attribute (a MagicMock standing in
    # for the QueryProperty descriptor result), not just its `get` method.
    # `patch.object` itself does a plain getattr() to save the "original"
    # value before replacing it, and even that getattr evaluates the real
    # QueryProperty descriptor -- which needs an active app context, not
    # yet pushed at fixture-setup time otherwise (a real request pushes its
    # own, but that's too late for patch.object's own bookkeeping).
    mock_query = MagicMock()
    mock_query.get.return_value = stub_user
    with app.app_context(), patch.object(app_module.AdminUser, "query", mock_query):
        yield client, stub_user


class TestPgwebAuthCheck:
    def test_unauthenticated_request_returns_401(self, app):
        """before_request's own deny-by-default gate must handle this --
        the view function never even runs for an unauthenticated caller."""
        client = app.test_client()
        response = client.get("/api/internal/pgweb-auth-check")
        assert response.status_code == 401

    def test_authenticated_without_permission_returns_403(self, logged_in_client):
        client, stub_user = logged_in_client
        stub_user.role.has_permission = lambda _permission_name: False
        response = client.get("/api/internal/pgweb-auth-check")
        assert response.status_code == 403
        # nginx auth_request discards the body regardless, but this must
        # never be a redirect -- see the module docstring on why.
        assert response.location is None

    def test_authenticated_with_permission_returns_200(self, logged_in_client):
        client, _stub_user = logged_in_client
        response = client.get("/api/internal/pgweb-auth-check")
        assert response.status_code == 200
        assert response.location is None


class TestDatabaseBrowserPage:
    def test_unauthenticated_redirects_to_login(self, app):
        client = app.test_client()
        response = client.get("/admin/database-browser/")
        assert response.status_code in (302, 401)

    def test_status_reports_not_installed_when_unit_file_absent(self, logged_in_client):
        client, _stub_user = logged_in_client
        with patch(
            "webapp.admin.database_browser._service_active", return_value=False
        ), patch("webapp.admin.database_browser.subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            response = client.get("/admin/database-browser/")
        assert response.status_code == 200
        assert b"Not Installed" in response.data

    def test_status_reports_running_when_service_active(self, logged_in_client):
        client, _stub_user = logged_in_client
        with patch(
            "webapp.admin.database_browser._service_active", return_value=True
        ), patch("webapp.admin.database_browser.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "eas-station-pgweb.service enabled enabled\n"
            response = client.get("/admin/database-browser/")
        assert response.status_code == 200
        assert b"Running" in response.data
        assert b":8081/" in response.data
