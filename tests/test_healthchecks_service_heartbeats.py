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

Tests for the per-critical-service healthchecks.io heartbeat feature: one
outbound check per app_core.config.get_eas_services() entry, each pinged
only while that specific service is active, so a missed ping on
healthchecks.io's side identifies exactly which subsystem failed. Mirrors
tests/test_tickstem_service_heartbeats.py -- same gating logic (shared
heartbeat_worker.HeartbeatWorker._ping_one_service_heartbeat()), same
route-level bulk-create shape, different account API surface (X-Api-Key
header, /checks/ endpoints, HTTP 403 for quota exhaustion instead of
Tickstem's 402).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app_core import healthchecks_client
from app_core.heartbeat_worker import HeartbeatWorker


def _resp(status_code=200, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.json.return_value = json_body if json_body is not None else {}
    return r


class TestPingHealthchecksServiceHeartbeatsOnce:
    """The gating logic that makes this feature worth having: only ping a
    row when it's due AND its own service is currently active. One row
    being down/disabled/not-due must never affect another row. Identical
    shape to TestPingServiceHeartbeatsOnce in
    test_tickstem_service_heartbeats.py, since both providers share
    heartbeat_worker's _ping_one_service_heartbeat() helper.
    """

    def _row(self, service_name, enabled=True, last_ping_at=None, interval_secs=300):
        row = MagicMock()
        row.service_name = service_name
        row.enabled = enabled
        row.last_ping_at = last_ping_at
        row.interval_secs = interval_secs
        row.ping_url = f"https://hc-ping.com/tok-{service_name}"
        return row

    def test_pings_only_the_active_and_due_service(self):
        worker = HeartbeatWorker(app=MagicMock())
        row_up = self._row("eas-station-web.service")
        row_down = self._row("eas-station-poller.service")

        with patch("app_core.models.HealthchecksServiceHeartbeat") as MockModel, \
             patch("app_core.heartbeat_worker._current_service_status",
                   return_value={"eas-station-web.service": True, "eas-station-poller.service": False}), \
             patch("app_core.heartbeat_worker.send_heartbeat_ping", return_value=(True, None)) as mock_send, \
             patch("app_core.extensions.db"):
            MockModel.query.filter_by.return_value.all.return_value = [row_up, row_down]
            worker._ping_healthchecks_service_heartbeats_once()

        mock_send.assert_called_once_with(row_up.ping_url)

    def test_skips_rows_not_yet_due(self):
        from datetime import datetime, timezone

        worker = HeartbeatWorker(app=MagicMock())
        row_not_due = self._row("eas-station-web.service", last_ping_at=datetime.now(timezone.utc))

        with patch("app_core.models.HealthchecksServiceHeartbeat") as MockModel, \
             patch("app_core.heartbeat_worker._current_service_status",
                   return_value={"eas-station-web.service": True}), \
             patch("app_core.heartbeat_worker.send_heartbeat_ping") as mock_send:
            MockModel.query.filter_by.return_value.all.return_value = [row_not_due]
            worker._ping_healthchecks_service_heartbeats_once()

        mock_send.assert_not_called()

    def test_no_rows_is_a_noop(self):
        worker = HeartbeatWorker(app=MagicMock())
        with patch("app_core.models.HealthchecksServiceHeartbeat") as MockModel, \
             patch("app_core.heartbeat_worker.send_heartbeat_ping") as mock_send:
            MockModel.query.filter_by.return_value.all.return_value = []
            worker._ping_healthchecks_service_heartbeats_once()
        mock_send.assert_not_called()

    def test_health_check_failure_pings_nothing_rather_than_raise(self):
        worker = HeartbeatWorker(app=MagicMock())
        row = self._row("eas-station-web.service")
        with patch("app_core.models.HealthchecksServiceHeartbeat") as MockModel, \
             patch("app_core.heartbeat_worker._current_service_status", side_effect=RuntimeError("boom")), \
             patch("app_core.heartbeat_worker.send_heartbeat_ping") as mock_send:
            MockModel.query.filter_by.return_value.all.return_value = [row]
            worker._ping_healthchecks_service_heartbeats_once()  # must not raise
        mock_send.assert_not_called()


class TestHealthchecksClient:
    def test_create_check_posts_expected_payload(self):
        with patch("app_core.healthchecks_client.requests.post",
                    return_value=_resp(201, {"uuid": "chk-1", "ping_url": "https://hc-ping.com/chk-1", "status": "new"})) as mock_post:
            result = healthchecks_client.create_check(
                "key123", "EAS Station -- web", timeout_secs=300, grace_secs=300, tags="eas-station")
        assert result["uuid"] == "chk-1"
        assert result["ping_url"] == "https://hc-ping.com/chk-1"
        _, kwargs = mock_post.call_args
        assert kwargs["json"] == {
            "name": "EAS Station -- web", "timeout": 300, "grace": 300, "tags": "eas-station",
        }
        assert kwargs["headers"]["X-Api-Key"] == "key123"

    def test_create_check_raises_on_error_status(self):
        with patch("app_core.healthchecks_client.requests.post",
                    return_value=_resp(403, {"error": "check limit reached"})):
            with pytest.raises(healthchecks_client.HealthchecksAPIError, match="limit reached"):
                healthchecks_client.create_check("key123", "EAS Station -- web")

    def test_error_carries_status_code_for_quota_detection(self):
        with patch("app_core.healthchecks_client.requests.post",
                    return_value=_resp(403, {"error": "check limit reached for your plan"})):
            with pytest.raises(healthchecks_client.HealthchecksAPIError) as exc_info:
                healthchecks_client.create_check("key123", "EAS Station -- web")
        assert exc_info.value.status_code == 403

    def test_non_quota_error_has_different_status_code(self):
        with patch("app_core.healthchecks_client.requests.post",
                    return_value=_resp(401, {"error": "wrong api key"})):
            with pytest.raises(healthchecks_client.HealthchecksAPIError) as exc_info:
                healthchecks_client.create_check("key123", "EAS Station -- web")
        assert exc_info.value.status_code == 401

    def test_pause_check_calls_expected_url(self):
        with patch("app_core.healthchecks_client.requests.post",
                    return_value=_resp(200, {"status": "paused"})) as mock_post:
            healthchecks_client.pause_check("key123", "chk-1")
        args, _ = mock_post.call_args
        assert args[0] == "https://healthchecks.io/api/v3/checks/chk-1/pause"

    def test_resume_check_calls_expected_url(self):
        with patch("app_core.healthchecks_client.requests.post",
                    return_value=_resp(200, {"status": "new"})) as mock_post:
            healthchecks_client.resume_check("key123", "chk-1")
        args, _ = mock_post.call_args
        assert args[0] == "https://healthchecks.io/api/v3/checks/chk-1/resume"

    def test_delete_check_calls_expected_url(self):
        with patch("app_core.healthchecks_client.requests.delete", return_value=_resp(200)) as mock_delete:
            healthchecks_client.delete_check("key123", "chk-1")
        args, _ = mock_delete.call_args
        assert args[0] == "https://healthchecks.io/api/v3/checks/chk-1"

    def test_get_pings_returns_list(self):
        with patch("app_core.healthchecks_client.requests.get",
                    return_value=_resp(200, {"pings": [{"type": "success"}, {"type": "success"}]})):
            pings = healthchecks_client.get_pings("key123", "chk-1", limit=1)
        assert pings == [{"type": "success"}]


class TestCreateAllServiceHeartbeatsRoute:
    """Route-level coverage for the quota-aware bulk-create endpoint: it
    must respect an explicit service_names subset (rather than always
    attempting every critical service) and stop immediately on a 403
    rather than retrying the same failure for everything left in the list.
    """

    URL = "/admin/healthchecks/service-heartbeats/create-all"

    def _post(self, app, payload):
        with app.test_request_context(self.URL, method="POST", json=payload):
            from webapp.admin.healthchecks import create_all_service_heartbeats
            return create_all_service_heartbeats()

    def _settings(self, api_key="real-key-123"):
        settings = MagicMock()
        settings.api_key = api_key
        settings.id = 1
        return settings

    def test_only_attempts_the_requested_services(self, app, authenticated_user):
        settings = self._settings()
        created_names = []

        def fake_create_check(api_key, name, timeout_secs, grace_secs, tags):
            created_names.append(name)
            return {"uuid": "chk-x", "ping_url": "https://hc-ping.com/chk-x", "status": "new", "timeout": timeout_secs}

        with patch("webapp.admin.healthchecks.get_or_create_settings", return_value=settings), \
             patch("app_core.config.get_eas_services", return_value=[
                 "eas-station-web.service", "eas-station-poller.service", "eas-station-audio.service",
             ]), \
             patch("app_core.models.HealthchecksServiceHeartbeat") as MockModel, \
             patch("webapp.admin.healthchecks.healthchecks_client.create_check", side_effect=fake_create_check), \
             patch("webapp.admin.healthchecks.db"):
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

        def fake_create_check(api_key, name, timeout_secs, grace_secs, tags):
            attempts.append(name)
            raise healthchecks_client.HealthchecksAPIError(
                "HTTP 403: check limit reached for your plan", status_code=403)

        with patch("webapp.admin.healthchecks.get_or_create_settings", return_value=settings), \
             patch("app_core.config.get_eas_services", return_value=[
                 "eas-station-web.service", "eas-station-poller.service", "eas-station-audio.service",
             ]), \
             patch("app_core.models.HealthchecksServiceHeartbeat") as MockModel, \
             patch("webapp.admin.healthchecks.healthchecks_client.create_check", side_effect=fake_create_check), \
             patch("webapp.admin.healthchecks.db"):
            MockModel.query.all.return_value = []
            MockModel.query.order_by.return_value.all.return_value = []
            response = self._post(app, {"service_names": [
                "eas-station-web.service", "eas-station-poller.service", "eas-station-audio.service",
            ]})

        data = response.get_json()
        assert data["quota_reached"] is True
        assert len(attempts) == 1  # stopped after the first 403, never tried the other two
        assert data["created"] == []

    def test_missing_api_key_is_rejected(self, app, authenticated_user):
        settings = self._settings(api_key=None)
        with patch("webapp.admin.healthchecks.get_or_create_settings", return_value=settings):
            response = self._post(app, {"service_names": ["eas-station-web.service"]})
        response, status = response
        assert status == 400
        assert "API key" in response.get_json()["error"]
