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
"""

from __future__ import annotations

"""Regression test: EASBroadcaster.handle_alert() must not silently drop
Icecast injection when running in a process that never registered an
app_core.audio.eas_stream_injector controller.

Background
----------
eas_stream_injector.inject_eas_audio() is a no-op unless a controller was
registered in *this process* via set_controller() -- which only happens in
eas_monitoring_service.py, the entry point of eas-station-audio.service.
Prior to this fix, EASBroadcaster.handle_alert() (app_utils/eas.py) called
that function directly and unconditionally. Every CAP/IPAWS auto-forward
(poller/cap_poller.py -- the main ingest path, the gated-alert auto-release
timer, and the forwarding catch-up sweep, all running as
eas-station-poller.service) and every operator "Approve" on a held/gated
alert (webapp/admin/pending_alerts.py, running as eas-station-web.service)
therefore recorded a broadcast in the database and logged "Auto-forwarded
... to air chain" while no audio ever reached Icecast or local playback.

Confirmed live on 2026-09-17: a Flash Flood Warning auto-forwarded via
IPAWS -- and again via the forwarding catch-up sweep after a poller
restart -- produced two "Auto-forwarded" log lines and an Icecast metadata
title change, but a listener monitoring the stream live heard nothing
either time. tests/test_broadcast_reaches_icecast_audit.py's structural
audit did not catch this because it only checks that a broadcast-trigger
function calls something named inject_eas_audio() somewhere in its body --
it has no way to know that call is a silent no-op in the calling process.

handle_alert() now checks eas_stream_injector.has_controller() and, when
False, falls back to the cross-process Redis command
(AudioCommandPublisher.inject_raw_eas_audio) that Manual Send and RWT
already use for exactly this reason.
"""

import tempfile
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app_utils.eas import EASBroadcaster, load_eas_config


def _build_minimal_alert():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=None,
        identifier="TEST-FFW-1",
        event="Flash Flood Warning",
        headline="Flash Flood Warning",
        description="",
        instruction=None,
        sent=now,
        expires=now + timedelta(hours=1),
        status="Actual",
        message_type="Alert",
        severity="Severe",
        urgency="Expected",
        certainty="Observed",
        raw_json=None,
    )


def _build_payload(fips_codes):
    return {
        "identifier": "TEST-FFW-1",
        "event": "Flash Flood Warning",
        "status": "Actual",
        "message_type": "Alert",
        "raw_json": {
            "properties": {
                "event": "Flash Flood Warning",
                "areaDesc": "Test County",
                "geocode": {"SAME": fips_codes},
                "parameters": {"EAS-ORG": "WXR"},
            }
        },
        "forwarding_decision": "forwarded",
        "forwarded": True,
    }


def _build_broadcaster():
    """Returns (broadcaster, records) -- records collects every EASMessage
    stand-in handle_alert() constructs, so a test can inspect the final
    metadata_payload written to it (e.g. after the injection-outcome
    update, which happens via attribute assignment after construction)."""
    cfg = load_eas_config()
    cfg["enabled"] = True
    cfg["output_dir"] = tempfile.mkdtemp()
    cfg["sample_rate"] = 16000
    cfg["attention_tone_seconds"] = 1
    cfg["tts_provider"] = ""
    cfg["max_activation_seconds"] = 1

    db_session = MagicMock()
    db_session.add = MagicMock()
    db_session.commit = MagicMock()

    records = []

    def capture_model(**kwargs):
        m = MagicMock()
        m.id = 1
        # A real EASMessage.metadata_payload starts as the dict passed to
        # the constructor; a bare MagicMock isn't dict-like and would break
        # the post-injection `dict(record.metadata_payload or {})` merge.
        m.metadata_payload = dict(kwargs.get('metadata_payload') or {})
        records.append(m)
        return m

    broadcaster = EASBroadcaster(
        db_session=db_session,
        model_cls=capture_model,
        config=cfg,
        logger=MagicMock(),
    )
    return broadcaster, records


class TestInjectionFallsBackToRedisWithoutController:
    """Simulates the three real broken call sites: cap_poller.py's main
    ingest path, its gate-release/catch-up sweeps, and
    pending_alerts.py's operator-approve action -- none of which ever
    register an eas_stream_injector controller in their own process."""

    def test_falls_back_to_redis_when_no_controller_registered(self):
        broadcaster, records = _build_broadcaster()
        alert = _build_minimal_alert()
        payload = _build_payload(["039161"])

        fake_publisher = MagicMock()
        fake_publisher.inject_raw_eas_audio.return_value = {"success": True}

        with patch(
            "app_core.audio.eas_stream_injector.has_controller",
            return_value=False,
        ), patch(
            "app_core.audio.eas_stream_injector.inject_eas_audio",
        ) as direct_inject, patch(
            "app_core.audio.redis_commands.get_audio_command_publisher",
            return_value=fake_publisher,
        ):
            result = broadcaster.handle_alert(alert, payload)

        assert result.get("same_triggered") is True
        direct_inject.assert_not_called()
        fake_publisher.inject_raw_eas_audio.assert_called_once()
        assert records[-1].metadata_payload["icecast_injected"] is True

    def test_uses_direct_injection_when_controller_registered(self):
        """Inside eas-station-audio.service itself (e.g. a live OTA relay),
        a controller IS registered -- keep the fast in-process path and
        never round-trip through Redis to talk to itself."""
        broadcaster, records = _build_broadcaster()
        alert = _build_minimal_alert()
        payload = _build_payload(["039161"])

        fake_publisher = MagicMock()

        with patch(
            "app_core.audio.eas_stream_injector.has_controller",
            return_value=True,
        ), patch(
            "app_core.audio.eas_stream_injector.inject_eas_audio",
            return_value=True,
        ) as direct_inject, patch(
            "app_core.audio.redis_commands.get_audio_command_publisher",
            return_value=fake_publisher,
        ):
            result = broadcaster.handle_alert(alert, payload)

        assert result.get("same_triggered") is True
        direct_inject.assert_called_once()
        fake_publisher.inject_raw_eas_audio.assert_not_called()
        assert records[-1].metadata_payload["icecast_injected"] is True

    def test_logs_error_when_redis_fallback_also_fails(self):
        """If the audio service isn't running either, the failure must be
        loud (an ERROR-level log naming the problem), not silently
        swallowed the way the original bug was."""
        broadcaster, records = _build_broadcaster()
        alert = _build_minimal_alert()
        payload = _build_payload(["039161"])

        fake_publisher = MagicMock()
        fake_publisher.inject_raw_eas_audio.return_value = {
            "success": False,
            "message": "The audio service is not running",
        }

        with patch(
            "app_core.audio.eas_stream_injector.has_controller",
            return_value=False,
        ), patch(
            "app_core.audio.redis_commands.get_audio_command_publisher",
            return_value=fake_publisher,
        ):
            result = broadcaster.handle_alert(alert, payload)

        assert result.get("same_triggered") is True
        assert broadcaster.logger.error.called, (
            "A failed Redis injection fallback must be logged at ERROR "
            "level -- this is the exact silence that let a live Flash "
            "Flood Warning go out with no audio on 2026-09-17."
        )
        messages = " ".join(
            str(call.args[0]) for call in broadcaster.logger.error.call_args_list
        )
        assert "injection" in messages.lower()
        # The failure must be recorded on the row so cap_poller.py's
        # retry_failed_icecast_injections() sweep can find and re-send it.
        assert records[-1].metadata_payload["icecast_injected"] is False
