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

Tests for the SMS/Notifications page split (v3.0.0, site reorganization
Phase 0 -- see docs/roadmap/SITE_REORGANIZATION.md): SMS config, the
opt-in QR/link callout, Consent Records, and the SMS Message Log moved
from templates/admin/notifications.html to their own dedicated page,
templates/admin/sms_settings.html, at GET /admin/notifications/sms.

The important correctness property pinned down here is that
update_sms_settings() and update_notification_settings() are genuinely
separate routes touching disjoint fields -- posting one must never blank
out the other, which is exactly the bug that would have resulted from
sharing update_notification_settings()'s single form-with-defaults
handler across two pages that each submit only half its fields.
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
    """See tests/test_sms_optin_qr.py's identical helper docstring.

    Also pre-seeds the admin-session-heartbeat cookie keys
    (app_core.auth.session_tracking.SESSION_ROW_KEY/SESSION_SEEN_KEY) so
    before_request()'s heartbeat tracking short-circuits on "already
    recorded recently" instead of trying to query/write the real
    admin_sessions table -- the test app's sqlite fixture doesn't have
    that table, and an unrelated failure there was poisoning the SQLAlchemy
    session for this module's own POST routes.
    """
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


def _settings_namespace(**overrides):
    base = dict(
        email_enabled=False, smtp_host='', smtp_port=587, smtp_username='',
        smtp_password='', smtp_security='starttls', compliance_alert_emails=[],
        alert_emails=[], email_attach_audio=False, email_html=True,
        email_include_map=True, email_audio_link=True, email_compress_audio=False,
        public_base_url='', sms_enabled=False, sms_provider='twilio',
        sms_account_sid='', sms_auth_token='', sms_from_number='',
        sms_recipients=[], snmp_enabled=False, snmp_targets=[],
        snmp_community='public', updated_at=None,
    )
    base.update(overrides)
    ns = SimpleNamespace(**base)
    ns.to_dict = lambda: dict(base)
    return ns


class TestSmsSettingsPage:
    def test_unauthenticated_rejected(self, app):
        client = app.test_client()
        response = client.get("/admin/notifications/sms")
        assert response.status_code in (302, 401)

    def test_renders_sms_content_not_on_the_main_page(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        mock_settings_query = MagicMock()
        mock_settings_query.first.return_value = _settings_namespace()

        mock_optin_query = MagicMock()
        mock_optin_query.filter.return_value = mock_optin_query
        mock_optin_query.order_by.return_value = mock_optin_query
        mock_optin_query.limit.return_value = mock_optin_query
        mock_optin_query.all.return_value = []

        mock_sms_log_query = MagicMock()
        mock_sms_log_query.order_by.return_value = mock_sms_log_query
        mock_sms_log_query.limit.return_value = mock_sms_log_query
        mock_sms_log_query.all.return_value = []

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query), \
             patch("app_core.models.NotificationSettings.query", mock_settings_query), \
             patch("app_core.models.SmsOptInRequest.query", mock_optin_query), \
             patch("app_core.models.SmsMessageLog.query", mock_sms_log_query):
            sms_response = client.get("/admin/notifications/sms")
            main_response = client.get("/admin/notifications/")

        assert sms_response.status_code == 200
        assert b"SMS Notifications (Twilio)" in sms_response.data
        assert b"Consent Records" in sms_response.data
        assert b"SMS Message Log" in sms_response.data

        assert main_response.status_code == 200
        assert b"SMS Notifications (Twilio)" not in main_response.data
        assert b"Consent Records" not in main_response.data
        assert b"SMS Message Log" not in main_response.data
        # The main page still links out to the SMS page instead.
        assert b"/admin/notifications/sms" in main_response.data


class TestUpdateRoutesAreDisjoint:
    def test_update_sms_settings_does_not_touch_email_or_snmp_fields(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        existing = _settings_namespace(
            email_enabled=True, smtp_host="mail.example.com", snmp_enabled=True,
        )
        mock_settings_query = MagicMock()
        mock_settings_query.first.return_value = existing

        csrf_token = "test-csrf-token"
        with client.session_transaction() as sess:
            sess[app_module.CSRF_SESSION_KEY] = csrf_token

        # db.session itself is deliberately left real (not mocked): before_
        # request()'s own admin-session-tracking runs a real query against
        # the test app's sqlite DB on every authenticated request, and
        # mocking db.session wholesale breaks that unrelated code path.
        # `existing` is never added to the session (NotificationSettings.
        # query is mocked to return it directly), so the real commit()
        # below is a harmless no-op as far as this SimpleNamespace goes.
        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query), \
             patch("webapp.admin.notifications.NotificationSettings.query", mock_settings_query):
            response = client.post(
                "/admin/notifications/sms/update",
                data={
                    "csrf_token": csrf_token,
                    "sms_enabled": "true",
                    "sms_account_sid": "ACxxxx",
                    "sms_from_number": "+15555550100",
                    "sms_recipients": "+15555550101",
                },
            )

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        # The handler only ever assigned sms_* attributes -- email/snmp
        # fields on the fetched settings object were never touched.
        assert existing.email_enabled is True
        assert existing.smtp_host == "mail.example.com"
        assert existing.snmp_enabled is True
        assert existing.sms_enabled is True
        assert existing.sms_account_sid == "ACxxxx"

    def test_update_notification_settings_no_longer_accepts_sms_fields(self, app):
        import app as app_module

        client, mock_admin_query = _logged_in_client(app)

        existing = _settings_namespace(sms_enabled=True, sms_account_sid="ACoriginal")
        mock_settings_query = MagicMock()
        mock_settings_query.first.return_value = existing

        csrf_token = "test-csrf-token"
        with client.session_transaction() as sess:
            sess[app_module.CSRF_SESSION_KEY] = csrf_token

        with app.app_context(), \
             patch.object(app_module.AdminUser, "query", mock_admin_query), \
             patch("webapp.admin.notifications.NotificationSettings.query", mock_settings_query):
            response = client.post(
                "/admin/notifications/update",
                data={
                    "csrf_token": csrf_token,
                    "email_enabled": "true",
                    "smtp_host": "mail.example.com",
                },
            )

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        # sms_enabled/sms_account_sid were never reassigned by this route --
        # they retain whatever they already were on the fetched object.
        assert existing.sms_enabled is True
        assert existing.sms_account_sid == "ACoriginal"
        assert existing.email_enabled is True
