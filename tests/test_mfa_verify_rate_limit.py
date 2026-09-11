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

Tests for rate limiting on /mfa/verify (webapp/admin/auth.py::mfa_verify).

Before this, an attacker who already had valid credentials for an
MFA-enabled account (phished, leaked, stuffed -- /login's own rate limiting
only covers the password step) could guess TOTP/backup codes against this
endpoint with no limit at all. Fixed by reusing the same LoginRateLimiter
class /login already uses, keyed under a separate "mfa:"-prefixed bucket so
MFA guesses and password guesses don't share (or exhaust) each other's
attempt budget.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app_core.auth.rate_limiter import LoginRateLimiter

_CSRF_TOKEN = "test-csrf-token"


@pytest.fixture(autouse=True)
def _skip_real_db_init():
    """See tests/test_database_browser.py's identical fixture docstring:
    before_request()'s app.initialize_database() call trips over a real
    Postgres-only JSONB column against the app fixture's sqlite in-memory
    DB, unrelated to anything this module tests."""
    with patch("app.initialize_database", return_value=True):
        yield


def _post(client, code):
    return client.post("/mfa/verify", data={"code": code, "csrf_token": _CSRF_TOKEN})


@pytest.fixture
def mfa_pending_client(app):
    """A test client with a real session in the "password verified, MFA
    pending" state (see app_core.auth.mfa.MFASession) for a mocked,
    MFA-enabled user, a matching CSRF session token (app.py's before_request
    rejects any POST without one), and a fresh, test-local LoginRateLimiter
    instance (not the real module-level singleton, which is shared
    process-wide and would leak state between tests). Patches
    webapp.admin.auth.verify_user_mfa directly rather than exercising real
    TOTP math -- this module tests the rate-limit wrapper around it, not
    pyotp itself (see tests/test_mfa_totp_reuse_prevention.py for that).

    Yields (client, stub_user, fresh_rate_limiter, mock_verify).
    """
    stub_role = SimpleNamespace(name="admin", has_permission=lambda _permission_name: True)
    stub_user = SimpleNamespace(
        id=1,
        username="testadmin",
        is_active=True,
        mfa_enabled=True,
        role=stub_role,
        last_login_at=None,
    )

    import app as app_module
    import webapp.admin.auth as auth_module

    client = app.test_client()
    with client.session_transaction() as sess:
        auth_module.MFASession.set_pending(sess, stub_user.id)
        sess[app_module.CSRF_SESSION_KEY] = _CSRF_TOKEN

    mock_query = MagicMock()
    mock_query.get.return_value = stub_user
    fresh_rate_limiter = LoginRateLimiter()

    with app.app_context(), patch.object(app_module.AdminUser, "query", mock_query), patch(
        "webapp.admin.auth.get_rate_limiter", return_value=fresh_rate_limiter
    ), patch("webapp.admin.auth._create_admin_session"), patch(
        "webapp.admin.auth._check_password_expiry", return_value=(False, None)
    ), patch("webapp.admin.auth.AuditLogger"), patch(
        "webapp.admin.auth.db.session"
    ), patch(
        "webapp.admin.auth.verify_user_mfa"
    ) as mock_verify:
        yield client, stub_user, fresh_rate_limiter, mock_verify


class TestMfaVerifyRateLimit:
    def test_repeated_wrong_codes_eventually_lock_out(self, mfa_pending_client):
        client, _stub_user, _rate_limiter, mock_verify = mfa_pending_client
        mock_verify.return_value = False

        responses = [_post(client, "000000") for _ in range(LoginRateLimiter.MAX_ATTEMPTS + 1)]

        # Every attempt up to and including the one that trips the lockout
        # still reports "invalid code" (the same wording /login uses) --
        # only the *next* attempt sees the lockout message.
        for resp in responses[:-1]:
            assert b"Invalid verification code" in resp.data
        assert b"Too many failed verification attempts" in responses[-1].data

    def test_locked_out_rejects_even_a_correct_code(self, mfa_pending_client):
        """Once locked, the endpoint must not even bother checking the
        code -- otherwise the lockout is just cosmetic."""
        client, _stub_user, _rate_limiter, mock_verify = mfa_pending_client
        mock_verify.return_value = False
        for _ in range(LoginRateLimiter.MAX_ATTEMPTS):
            _post(client, "000000")

        mock_verify.return_value = True
        response = _post(client, "123456")
        assert b"Too many failed verification attempts" in response.data
        assert response.status_code == 200  # re-renders the form, not a redirect to the dashboard

    def test_successful_verification_clears_the_bucket(self, mfa_pending_client):
        client, _stub_user, rate_limiter, mock_verify = mfa_pending_client
        mock_verify.return_value = False
        for _ in range(LoginRateLimiter.MAX_ATTEMPTS - 1):
            _post(client, "000000")

        mock_verify.return_value = True
        response = _post(client, "654321")
        assert response.status_code == 302  # login completed, redirected onward

        # Bucket should be clear -- a fresh run of failures needs the full
        # MAX_ATTEMPTS again to lock out, not just one more.
        is_locked, _ = rate_limiter.is_locked_out("mfa:127.0.0.1")
        assert is_locked is False

    def test_separate_bucket_from_password_login_attempts(self, mfa_pending_client):
        """MFA failures must not consume the /login password-attempt
        budget (and vice versa) -- they're tracked under different keys
        even for the same client IP."""
        client, _stub_user, rate_limiter, mock_verify = mfa_pending_client
        mock_verify.return_value = False
        for _ in range(LoginRateLimiter.MAX_ATTEMPTS):
            _post(client, "000000")

        mfa_locked, _ = rate_limiter.is_locked_out("mfa:127.0.0.1")
        password_locked, _ = rate_limiter.is_locked_out("127.0.0.1")
        assert mfa_locked is True
        assert password_locked is False
