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

Tests for the outbound SMS message log (app_core/_models_sms_log.py,
recorded from app_core/notifications/sms.py) and its search UI in
Settings -> Notifications (webapp/admin/notifications.py).

The whole point of this log is "can an admin find every SMS ever sent to
a given number" -- these tests pin down that (a) every send path (alert
broadcast, opt-in verification code, test message) actually writes a row,
success or failure, and (b) the admin page's search box filters by phone
number rather than just showing everything.
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


def _logged_in_client(app):
    """See tests/test_sms_optin_qr.py's identical helper docstring."""
    stub_role = SimpleNamespace(name="admin", has_permission=lambda _permission_name: True)
    stub_user = SimpleNamespace(id=1, is_active=True, role=stub_role)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = stub_user.id

    mock_query = MagicMock()
    mock_query.get.return_value = stub_user
    return client, mock_query


class TestRecordSmsMessage:
    def test_writes_a_row_via_the_given_session(self):
        from app_core._models_sms_log import record_sms_message

        session = MagicMock()
        record_sms_message(
            "+15555551234", "alert", True,
            event_code="TOR", twilio_sid="SM123", db_session=session,
        )

        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert added.phone_number == "+15555551234"
        assert added.message_type == "alert"
        assert added.success is True
        assert added.event_code == "TOR"
        assert added.twilio_sid == "SM123"
        session.commit.assert_called_once()

    def test_a_commit_failure_is_swallowed_not_raised(self):
        from app_core._models_sms_log import record_sms_message

        session = MagicMock()
        session.commit.side_effect = Exception("db is down")

        # Must not raise -- a logging failure is never allowed to look like
        # (or cause) an SMS send failure to the caller.
        record_sms_message("+15555551234", "test", True, db_session=session)
        session.rollback.assert_called_once()


class TestSmsSendPathsLogEveryAttempt:
    def test_alert_sms_logs_success_and_failure_per_recipient(self):
        from app_core.notifications.sms import send_eas_alert_sms

        fake_client = MagicMock()
        fake_client.messages.create.side_effect = [
            SimpleNamespace(sid="SM_OK"),
            Exception("carrier rejected"),
        ]

        with patch("twilio.rest.Client", return_value=fake_client), \
             patch("app_core.notifications.sms._log_sms") as mock_log:
            send_eas_alert_sms(
                alert_info={"event_code": "TOR", "headline": "Tornado Warning"},
                recipients=["+15555550001", "+15555550002"],
                account_sid="SID",
                auth_token="TOKEN",
                from_number="+15555559999",
                db_session="the-session",
            )

        assert mock_log.call_count == 2
        ok_call = mock_log.call_args_list[0]
        assert ok_call.args == ("+15555550001", "alert", True)
        assert ok_call.kwargs["event_code"] == "TOR"
        assert ok_call.kwargs["twilio_sid"] == "SM_OK"
        assert ok_call.kwargs["db_session"] == "the-session"

        fail_call = mock_log.call_args_list[1]
        assert fail_call.args == ("+15555550002", "alert", False)
        assert "carrier rejected" in fail_call.kwargs["error_message"]

    def test_verification_sms_logs_type_verification(self):
        from app_core.notifications.sms import send_verification_sms

        fake_client = MagicMock()
        fake_client.messages.create.return_value = SimpleNamespace(sid="SM_VERIFY")

        with patch("twilio.rest.Client", return_value=fake_client), \
             patch("app_core.notifications.sms._log_sms") as mock_log:
            ok, _msg = send_verification_sms(
                "SID", "TOKEN", "+15555559999", "+15555550001", "123456",
            )

        assert ok is True
        mock_log.assert_called_once_with(
            "+15555550001", "verification", True, twilio_sid="SM_VERIFY",
        )

    def test_test_sms_logs_type_test(self):
        from app_core.notifications.sms import test_sms

        fake_client = MagicMock()
        fake_client.messages.create.return_value = SimpleNamespace(sid="SM_TEST")

        with patch("twilio.rest.Client", return_value=fake_client), \
             patch("app_core.notifications.sms._log_sms") as mock_log:
            ok, _msg = test_sms("SID", "TOKEN", "+15555559999", "+15555550001")

        assert ok is True
        mock_log.assert_called_once_with(
            "+15555550001", "test", True, twilio_sid="SM_TEST",
        )


class TestSmsMessageLogAdminSearch:
    def test_unauthenticated_rejected(self, app):
        client = app.test_client()
        response = client.get("/admin/notifications/")
        assert response.status_code in (302, 401)

    def test_search_filters_by_phone_number(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        matching_entry = SimpleNamespace(
            phone_number="+15555550001",
            message_type="alert",
            event_code="TOR",
            success=True,
            error_message=None,
            created_at=None,
        )

        mock_sms_log_query = MagicMock()
        mock_sms_log_query.filter.return_value = mock_sms_log_query
        mock_sms_log_query.order_by.return_value = mock_sms_log_query
        mock_sms_log_query.limit.return_value = mock_sms_log_query
        mock_sms_log_query.all.return_value = [matching_entry]

        mock_settings_query = MagicMock()
        mock_settings_query.first.return_value = SimpleNamespace(
            email_enabled=False, smtp_host='', smtp_port=587, smtp_username='',
            smtp_password='', smtp_security='starttls', compliance_alert_emails=[],
            alert_emails=[], email_attach_audio=False, email_html=True,
            email_include_map=True, email_audio_link=True, email_compress_audio=False,
            public_base_url='', sms_enabled=False, sms_provider='twilio',
            sms_account_sid='', sms_auth_token='', sms_from_number='',
            sms_recipients=[], snmp_enabled=False, snmp_targets=[],
            snmp_community='public',
        )

        mock_optin_query = MagicMock()
        mock_optin_query.filter.return_value = mock_optin_query
        mock_optin_query.order_by.return_value = mock_optin_query
        mock_optin_query.limit.return_value = mock_optin_query
        mock_optin_query.all.return_value = []

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query), \
             patch("app_core.models.SmsMessageLog.query", mock_sms_log_query), \
             patch("app_core.models.NotificationSettings.query", mock_settings_query), \
             patch("app_core.models.SmsOptInRequest.query", mock_optin_query):
            response = client.get("/admin/notifications/sms?sms_log_search=5550001")

        assert response.status_code == 200
        mock_sms_log_query.filter.assert_called_once()
        mock_sms_log_query.all.assert_called_once()
