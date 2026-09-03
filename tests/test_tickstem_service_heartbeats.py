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

Tests for the per-critical-service Tickstem heartbeat feature: one outbound
heartbeat per app_core.config.get_eas_services() entry, each pinged only
while that specific service is active, so a missed ping on Tickstem's side
identifies exactly which subsystem failed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app_core import tickstem_client
from app_core.heartbeat_worker import HeartbeatWorker, _current_service_status, _is_due


def _resp(status_code=200, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.json.return_value = json_body if json_body is not None else {}
    return r


class TestIsDue:
    def test_never_pinged_is_due(self):
        assert _is_due(None, 300) is True

    def test_within_interval_not_due(self):
        assert _is_due(datetime.now(timezone.utc) - timedelta(seconds=10), 300) is False

    def test_past_interval_is_due(self):
        assert _is_due(datetime.now(timezone.utc) - timedelta(seconds=301), 300) is True

    def test_naive_and_aware_dont_crash(self):
        aware = datetime.now(timezone.utc) - timedelta(seconds=301)
        assert _is_due(aware, 300) is True


class TestCurrentServiceStatus:
    def test_maps_name_to_is_running(self):
        fake_health = {
            "systemd": {
                "services": [
                    {"name": "eas-station-web.service", "is_running": True},
                    {"name": "eas-station-poller.service", "is_running": False},
                ]
            }
        }
        with patch("app_core.system_health.get_system_health", return_value=fake_health):
            status = _current_service_status()
        assert status == {
            "eas-station-web.service": True,
            "eas-station-poller.service": False,
        }

    def test_missing_systemd_key_returns_empty(self):
        with patch("app_core.system_health.get_system_health", return_value={}):
            assert _current_service_status() == {}


class TestPingServiceHeartbeatsOnce:
    """The gating logic that makes this feature worth having: only ping a
    row when it's due AND its own service is currently active. One row
    being down/disabled/not-due must never affect another row.
    """

    def _row(self, service_name, enabled=True, last_ping_at=None, interval_secs=300):
        row = MagicMock()
        row.service_name = service_name
        row.enabled = enabled
        row.last_ping_at = last_ping_at
        row.interval_secs = interval_secs
        row.ping_url = f"https://api.tickstem.dev/v1/heartbeats/tok-{service_name}/ping"
        return row

    def test_pings_only_the_active_and_due_service(self):
        worker = HeartbeatWorker(app=MagicMock())
        row_up = self._row("eas-station-web.service")
        row_down = self._row("eas-station-poller.service")

        with patch("app_core.models.TickstemServiceHeartbeat") as MockModel, \
             patch("app_core.heartbeat_worker._current_service_status",
                   return_value={"eas-station-web.service": True, "eas-station-poller.service": False}), \
             patch("app_core.heartbeat_worker.send_heartbeat_ping", return_value=(True, None)) as mock_send, \
             patch("app_core.extensions.db"):
            MockModel.query.filter_by.return_value.all.return_value = [row_up, row_down]
            worker._ping_service_heartbeats_once()

        mock_send.assert_called_once_with(row_up.ping_url)

    def test_skips_rows_not_yet_due(self):
        worker = HeartbeatWorker(app=MagicMock())
        row_not_due = self._row("eas-station-web.service", last_ping_at=datetime.now(timezone.utc))

        with patch("app_core.models.TickstemServiceHeartbeat") as MockModel, \
             patch("app_core.heartbeat_worker._current_service_status",
                   return_value={"eas-station-web.service": True}), \
             patch("app_core.heartbeat_worker.send_heartbeat_ping") as mock_send:
            MockModel.query.filter_by.return_value.all.return_value = [row_not_due]
            worker._ping_service_heartbeats_once()

        mock_send.assert_not_called()

    def test_no_rows_is_a_noop(self):
        worker = HeartbeatWorker(app=MagicMock())
        with patch("app_core.models.TickstemServiceHeartbeat") as MockModel, \
             patch("app_core.heartbeat_worker.send_heartbeat_ping") as mock_send:
            MockModel.query.filter_by.return_value.all.return_value = []
            worker._ping_service_heartbeats_once()
        mock_send.assert_not_called()

    def test_health_check_failure_pings_nothing_rather_than_raise(self):
        worker = HeartbeatWorker(app=MagicMock())
        row = self._row("eas-station-web.service")
        with patch("app_core.models.TickstemServiceHeartbeat") as MockModel, \
             patch("app_core.heartbeat_worker._current_service_status", side_effect=RuntimeError("boom")), \
             patch("app_core.heartbeat_worker.send_heartbeat_ping") as mock_send:
            MockModel.query.filter_by.return_value.all.return_value = [row]
            worker._ping_service_heartbeats_once()  # must not raise
        mock_send.assert_not_called()


class TestTickstemClientHeartbeats:
    def test_create_heartbeat_posts_expected_payload(self):
        with patch("app_core.tickstem_client.requests.post",
                    return_value=_resp(201, {"id": "hb-1", "token": "abc123", "status": "active"})) as mock_post:
            result = tickstem_client.create_heartbeat("key123", "EAS Station -- web", interval_secs=300, grace_secs=300)
        assert result["id"] == "hb-1"
        assert result["token"] == "abc123"
        _, kwargs = mock_post.call_args
        assert kwargs["json"] == {"name": "EAS Station -- web", "interval_secs": 300, "grace_secs": 300}
        assert kwargs["headers"]["Authorization"] == "Bearer key123"

    def test_create_heartbeat_raises_on_error_status(self):
        with patch("app_core.tickstem_client.requests.post",
                    return_value=_resp(402, {"error": "Heartbeat quota reached"})):
            with pytest.raises(tickstem_client.TickstemAPIError, match="quota reached"):
                tickstem_client.create_heartbeat("key123", "EAS Station -- web")

    def test_error_carries_status_code_for_quota_detection(self):
        with patch("app_core.tickstem_client.requests.post",
                    return_value=_resp(402, {"error": "Heartbeat quota reached for your plan"})):
            with pytest.raises(tickstem_client.TickstemAPIError) as exc_info:
                tickstem_client.create_heartbeat("key123", "EAS Station -- web")
        assert exc_info.value.status_code == 402

    def test_non_quota_error_has_different_status_code(self):
        with patch("app_core.tickstem_client.requests.post",
                    return_value=_resp(401, {"error": "invalid api key"})):
            with pytest.raises(tickstem_client.TickstemAPIError) as exc_info:
                tickstem_client.create_heartbeat("key123", "EAS Station -- web")
        assert exc_info.value.status_code == 401

    def test_set_heartbeat_status_patches_status_field(self):
        with patch("app_core.tickstem_client.requests.patch",
                    return_value=_resp(200, {"status": "paused"})) as mock_patch:
            tickstem_client.set_heartbeat_status("key123", "hb-1", "paused")
        _, kwargs = mock_patch.call_args
        assert kwargs["json"] == {"status": "paused"}

    def test_delete_heartbeat_calls_expected_url(self):
        with patch("app_core.tickstem_client.requests.delete", return_value=_resp(204)) as mock_delete:
            tickstem_client.delete_heartbeat("key123", "hb-1")
        args, _ = mock_delete.call_args
        assert args[0] == "https://api.tickstem.dev/v1/heartbeats/hb-1"


class TestCreateAllServiceHeartbeatsRoute:
    """Route-level coverage for the quota-aware bulk-create endpoint: it
    must respect an explicit service_names subset (rather than always
    attempting every critical service) and stop immediately on a 402
    rather than retrying the same failure for everything left in the list.
    """

    URL = "/admin/tickstem/service-heartbeats/create-all"

    def _post(self, app, payload):
        with app.test_request_context(self.URL, method="POST", json=payload):
            from webapp.admin.tickstem import create_all_service_heartbeats
            return create_all_service_heartbeats()

    def _settings(self, api_key="real-key-123"):
        settings = MagicMock()
        settings.api_key = api_key
        settings.id = 1
        return settings

    def test_only_attempts_the_requested_services(self, app, authenticated_user):
        settings = self._settings()
        created_names = []

        def fake_create_heartbeat(api_key, name, interval_secs, grace_secs):
            created_names.append(name)
            return {"id": "hb-x", "token": "tok-x", "status": "active", "interval_secs": interval_secs}

        with patch("webapp.admin.tickstem._get_or_create_settings", return_value=settings), \
             patch("app_core.config.get_eas_services", return_value=[
                 "eas-station-web.service", "eas-station-poller.service", "eas-station-audio.service",
             ]), \
             patch("app_core.models.TickstemServiceHeartbeat") as MockModel, \
             patch("webapp.admin.tickstem.tickstem_client.create_heartbeat", side_effect=fake_create_heartbeat), \
             patch("webapp.admin.tickstem.db"):
            MockModel.query.all.return_value = []
            MockModel.query.order_by.return_value.all.return_value = []
            response = self._post(app, {"service_names": ["eas-station-poller.service"]})

        data = response.get_json()
        assert data["created"] == ["eas-station-poller.service"]
        assert any("poller" in n for n in created_names)
        assert not any("web" in n or "audio" in n for n in created_names)

    def test_stops_on_quota_reached_without_retrying_remaining_services(self, app, authenticated_user):
        settings = self._settings()
        attempts = []

        def fake_create_heartbeat(api_key, name, interval_secs, grace_secs):
            attempts.append(name)
            raise tickstem_client.TickstemAPIError("HTTP 402: Heartbeat quota reached for your plan", status_code=402)

        with patch("webapp.admin.tickstem._get_or_create_settings", return_value=settings), \
             patch("app_core.config.get_eas_services", return_value=[
                 "eas-station-web.service", "eas-station-poller.service", "eas-station-audio.service",
             ]), \
             patch("app_core.models.TickstemServiceHeartbeat") as MockModel, \
             patch("webapp.admin.tickstem.tickstem_client.create_heartbeat", side_effect=fake_create_heartbeat), \
             patch("webapp.admin.tickstem.db"):
            MockModel.query.all.return_value = []
            MockModel.query.order_by.return_value.all.return_value = []
            response = self._post(app, {"service_names": [
                "eas-station-web.service", "eas-station-poller.service", "eas-station-audio.service",
            ]})

        data = response.get_json()
        assert data["quota_reached"] is True
        assert len(attempts) == 1  # stopped after the first 402, never tried the other two
        assert data["created"] == []

    def test_missing_api_key_is_rejected(self, app, authenticated_user):
        settings = self._settings(api_key=None)
        with patch("webapp.admin.tickstem._get_or_create_settings", return_value=settings):
            response = self._post(app, {"service_names": ["eas-station-web.service"]})
        response, status = response
        assert status == 400
        assert "API key" in response.get_json()["error"]
