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

Tests for /admin/notifications/sms-optin-qr.png (webapp/admin/notifications.py).

The whole point of generating this QR code server-side per request (rather
than a static asset) is that it must always encode *this* instance's own
address -- an operator running more than one EAS Station deployment must
get a different, correct QR code from each one. These tests pin down the
permission gate and that the URL handed to the QR encoder tracks the
request's actual host rather than anything hardcoded.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _skip_real_db_init():
    """See tests/test_database_browser.py's identical fixture docstring."""
    with patch("app.initialize_database", return_value=True):
        yield


def _logged_in_client(app, host=None):
    """Like tests/test_database_browser.py's `logged_in_client` fixture,
    plus an optional Host override for testing that the QR endpoint
    reflects the *request's* host, not a fixed one.

    Werkzeug's test client cookie jar is host-scoped: the session cookie
    set by session_transaction() is only resent on a later request to the
    *same* host, so a Host override has to be applied to both calls or
    the "authenticated" request silently looks anonymous again (a real
    30 minutes were lost here chasing an unrelated-looking 302 before
    finding that root cause -- if this stops working, check that first).
    """
    stub_role = SimpleNamespace(name="admin", has_permission=lambda _permission_name: True)
    stub_user = SimpleNamespace(id=1, is_active=True, role=stub_role)

    import app as app_module

    client = app.test_client()
    environ_overrides = {"HTTP_HOST": host, "wsgi.url_scheme": "https"} if host else {}
    with client.session_transaction(environ_overrides=environ_overrides) as sess:
        sess["user_id"] = stub_user.id

    mock_query = MagicMock()
    mock_query.get.return_value = stub_user
    return client, mock_query, environ_overrides


class TestSmsOptinQr:
    def test_unauthenticated_rejected(self, app):
        client = app.test_client()
        response = client.get("/admin/notifications/sms-optin-qr.png")
        assert response.status_code in (302, 401)

    def test_authenticated_returns_png_for_this_hosts_url(self, app):
        import app as app_module

        client, mock_query, environ_overrides = _logged_in_client(app, host="station-a.example.com")
        fake_png = b"\x89PNG\r\n\x1a\nfake"
        with app.app_context(), patch.object(app_module.AdminUser, "query", mock_query):
            with patch("app_core.auth.mfa.MFAManager.generate_qr_code", return_value=fake_png) as mock_gen:
                response = client.get(
                    "/admin/notifications/sms-optin-qr.png", environ_overrides=environ_overrides
                )

        assert response.status_code == 200
        assert response.mimetype == "image/png"
        assert response.data == fake_png

        # The URL handed to the QR encoder must reflect *this* request's
        # own host, not a different instance's or a hardcoded value.
        mock_gen.assert_called_once()
        encoded_url = mock_gen.call_args[0][0]
        assert encoded_url == "https://station-a.example.com/sms-opt-in"

    def test_different_instance_gets_its_own_url(self, app):
        import app as app_module

        client, mock_query, environ_overrides = _logged_in_client(app, host="station-b.example.org")
        with app.app_context(), patch.object(app_module.AdminUser, "query", mock_query):
            with patch("app_core.auth.mfa.MFAManager.generate_qr_code", return_value=b"png") as mock_gen:
                client.get("/admin/notifications/sms-optin-qr.png", environ_overrides=environ_overrides)

        mock_gen.assert_called_once()
        encoded_url = mock_gen.call_args[0][0]
        assert encoded_url == "https://station-b.example.org/sms-opt-in"
