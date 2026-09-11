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

Tests for the public double opt-in SMS flow (webapp/public/sms_optin.py):
/sms-opt-in, /sms-opt-in/start, /sms-opt-in/confirm.

This replaces the old "administrator adds a number and attests consent was
obtained elsewhere" design, which gave a carrier/Twilio campaign reviewer
nothing verifiable to point at. These tests pin down the actual security-
relevant behavior: a wrong/expired/over-attempted code is rejected, a
correct one adds the number to the live recipient list exactly once, and
the endpoint is rate-limited per IP and per phone number so it can't be
used to spam arbitrary numbers with SMS at the operator's expense.
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


def _client_with_csrf(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        import app as app_module
        sess[app_module.CSRF_SESSION_KEY] = _CSRF_TOKEN
    return client


def _post(client, url, **fields):
    fields.setdefault("csrf_token", _CSRF_TOKEN)
    return client.post(url, data=fields)


def _settings(**overrides):
    defaults = dict(
        sms_account_sid="ACxxxx",
        sms_auth_token="tokxxxx",
        sms_from_number="+15555550100",
        sms_recipients=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def optin_env(app):
    """Patches the ORM boundary (NotificationSettings.query,
    SmsOptInRequest.query/constructor side effects via db.session, and the
    Twilio send call) with a fresh, test-local rate limiter -- not the
    real module-level singleton, which is shared process-wide and would
    leak lockouts between tests.

    Yields a namespace with: client, settings (mutable stub the test can
    adjust), rate_limiter, mock_send (Twilio send mock), and helpers to
    stub SmsOptInRequest.query for the confirm-step tests.
    """
    import webapp.public.sms_optin as optin_module

    client = _client_with_csrf(app)
    settings = _settings()
    rate_limiter = LoginRateLimiter()

    mock_notification_query = MagicMock()
    mock_notification_query.get.return_value = settings

    mock_optin_query = MagicMock()
    # No recent-pending row by default (the resend-cooldown check).
    mock_optin_query.filter.return_value.first.return_value = None

    with app.app_context(), patch.object(
        optin_module.NotificationSettings, "query", mock_notification_query
    ), patch.object(
        optin_module.SmsOptInRequest, "query", mock_optin_query
    ), patch(
        "webapp.public.sms_optin.get_rate_limiter", return_value=rate_limiter
    ), patch(
        "webapp.public.sms_optin.db.session"
    ), patch(
        "webapp.public.sms_optin.send_verification_sms"
    ) as mock_send:
        mock_send.return_value = (True, "sent")
        yield SimpleNamespace(
            client=client,
            settings=settings,
            rate_limiter=rate_limiter,
            mock_send=mock_send,
            mock_optin_query=mock_optin_query,
        )


class TestSmsOptInPage:
    def test_get_page_renders_without_auth(self, app):
        client = app.test_client()
        response = client.get("/sms-opt-in")
        assert response.status_code == 200
        assert b"sms-opt-in" in response.data or b"Verification Code" in response.data


class TestSmsOptInStart:
    def test_rejects_missing_consent(self, optin_env):
        response = _post(optin_env.client, "/sms-opt-in/start", phone_number="+15555550111")
        assert response.status_code == 400
        assert b"agree" in response.data.lower()
        optin_env.mock_send.assert_not_called()

    def test_rejects_invalid_phone_number(self, optin_env):
        response = _post(
            optin_env.client, "/sms-opt-in/start",
            phone_number="not-a-number", consent="on",
        )
        assert response.status_code == 400
        optin_env.mock_send.assert_not_called()

    def test_rejects_when_sms_not_configured(self, optin_env):
        optin_env.settings.sms_account_sid = ""
        response = _post(
            optin_env.client, "/sms-opt-in/start",
            phone_number="+15555550111", consent="on",
        )
        assert response.status_code == 503
        optin_env.mock_send.assert_not_called()

    def test_already_subscribed_short_circuits(self, optin_env):
        optin_env.settings.sms_recipients = ["+15555550111"]
        response = _post(
            optin_env.client, "/sms-opt-in/start",
            phone_number="+15555550111", consent="on",
        )
        assert response.status_code == 200
        assert response.get_json()["already_subscribed"] is True
        optin_env.mock_send.assert_not_called()

    def test_valid_request_sends_code(self, optin_env):
        response = _post(
            optin_env.client, "/sms-opt-in/start",
            phone_number="+15555550111", consent="on", name="Test Person",
        )
        assert response.status_code == 200
        assert response.get_json()["success"] is True
        optin_env.mock_send.assert_called_once()
        # The code passed to Twilio must be a 6-digit string.
        sent_code = optin_env.mock_send.call_args[0][4]
        assert len(sent_code) == 6 and sent_code.isdigit()

    def test_send_failure_does_not_report_success(self, optin_env):
        optin_env.mock_send.return_value = (False, "boom")
        response = _post(
            optin_env.client, "/sms-opt-in/start",
            phone_number="+15555550111", consent="on",
        )
        assert response.status_code == 502

    def test_ip_rate_limit_locks_out_after_max_attempts(self, optin_env):
        for _ in range(LoginRateLimiter.MAX_ATTEMPTS):
            _post(
                optin_env.client, "/sms-opt-in/start",
                phone_number="+15555550111", consent="on",
            )
        response = _post(
            optin_env.client, "/sms-opt-in/start",
            phone_number="+15555559999", consent="on",
        )
        assert response.status_code == 429

    def test_resend_cooldown_blocks_duplicate_pending_request(self, optin_env):
        # Simulate an existing unexpired pending request for this number.
        optin_env.mock_optin_query.filter.return_value.first.return_value = SimpleNamespace(id=1)
        response = _post(
            optin_env.client, "/sms-opt-in/start",
            phone_number="+15555550111", consent="on",
        )
        assert response.status_code == 429
        optin_env.mock_send.assert_not_called()


class TestSmsOptInConfirm:
    def _pending(self, **overrides):
        from datetime import timedelta

        from app_utils import utc_now
        from werkzeug.security import generate_password_hash

        from app_core.crypto import pepper_password

        defaults = dict(
            id=1,
            phone_number="+15555550111",
            verified_at=None,
            code_hash=generate_password_hash(pepper_password("123456")),
            code_expires_at=utc_now() + timedelta(minutes=10),
            code_attempts=0,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_no_pending_session_rejected(self, optin_env):
        response = _post(optin_env.client, "/sms-opt-in/confirm", code="123456")
        assert response.status_code == 400

    def test_correct_code_adds_recipient(self, optin_env, app):
        import webapp.public.sms_optin as optin_module

        pending = self._pending()
        with optin_env.client.session_transaction() as sess:
            sess[optin_module._SESSION_KEY] = pending.id

        with patch.object(optin_module.SmsOptInRequest, "query") as mock_q:
            mock_q.get.return_value = pending
            response = _post(optin_env.client, "/sms-opt-in/confirm", code="123456")

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        assert pending.verified_at is not None
        assert pending.phone_number in optin_env.settings.sms_recipients

    def test_wrong_code_increments_attempts_and_fails(self, optin_env):
        import webapp.public.sms_optin as optin_module

        pending = self._pending()
        with optin_env.client.session_transaction() as sess:
            sess[optin_module._SESSION_KEY] = pending.id

        with patch.object(optin_module.SmsOptInRequest, "query") as mock_q:
            mock_q.get.return_value = pending
            response = _post(optin_env.client, "/sms-opt-in/confirm", code="000000")

        assert response.status_code == 400
        assert pending.code_attempts == 1
        assert pending.verified_at is None
        assert optin_env.settings.sms_recipients == []

    def test_too_many_attempts_locks_out(self, optin_env):
        import webapp.public.sms_optin as optin_module

        pending = self._pending(code_attempts=optin_module._MAX_CODE_ATTEMPTS)
        with optin_env.client.session_transaction() as sess:
            sess[optin_module._SESSION_KEY] = pending.id

        with patch.object(optin_module.SmsOptInRequest, "query") as mock_q:
            mock_q.get.return_value = pending
            response = _post(optin_env.client, "/sms-opt-in/confirm", code="123456")

        assert response.status_code == 429

    def test_expired_code_rejected(self, optin_env):
        from datetime import timedelta

        from app_utils import utc_now

        import webapp.public.sms_optin as optin_module

        pending = self._pending(code_expires_at=utc_now() - timedelta(minutes=1))
        with optin_env.client.session_transaction() as sess:
            sess[optin_module._SESSION_KEY] = pending.id

        with patch.object(optin_module.SmsOptInRequest, "query") as mock_q:
            mock_q.get.return_value = pending
            response = _post(optin_env.client, "/sms-opt-in/confirm", code="123456")

        assert response.status_code == 400
        assert pending.verified_at is None
