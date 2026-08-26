#!/usr/bin/env python3
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

"""Tests for eas_monitoring_service._reconcile_broadcast_metadata().

A user asked whether every broadcast path (manual Send, RWT, resend, live
auto-forward) updates the Icecast stream's "now playing" title with the
alert text. It turned out only the live auto-forward path did -- it called
app_core.audio.alert_metadata directly, which only works because
auto_forward.py happens to run in the same process as the Icecast
streamers; RWT (web process), manual Send (web process), and resend (a
standalone script process) would silently no-op if they tried the same
direct call, since alert_metadata's target is a module-level singleton
that only exists inside eas_monitoring_service.py's own process.

_reconcile_broadcast_metadata() closes that gap by polling the same
Redis broadcast-state marker every broadcast path already writes via
set_broadcast_active()/clear_broadcast_active() (to key the GPIO relay
and drive the countdown overlay) -- so every path gets stream-metadata
override "for free" with no per-caller wiring, from the one process that
actually owns the live IcecastStreamer objects.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import eas_monitoring_service as svc  # noqa: E402


def _reset_applied_label():
    svc._applied_broadcast_metadata_label = None


def test_sets_metadata_on_transition_to_active():
    _reset_applied_label()
    with patch("app_utils.eas.get_broadcast_state", return_value={
        "active": True, "label": "Tornado Warning — Logan County",
    }), \
         patch("app_core.audio.alert_metadata.set_alert_metadata") as mock_set, \
         patch("app_core.audio.alert_metadata.clear_alert_metadata") as mock_clear:
        svc._reconcile_broadcast_metadata()

    mock_set.assert_called_once_with("Tornado Warning — Logan County")
    mock_clear.assert_not_called()
    assert svc._applied_broadcast_metadata_label == "Tornado Warning — Logan County"


def test_does_not_reset_metadata_while_label_unchanged():
    """Repeated ticks with the same active label must not re-push the
    override every ~0.25s -- only an actual transition should call
    set_alert_metadata()."""
    _reset_applied_label()
    state = {"active": True, "label": "Severe Thunderstorm Warning"}
    with patch("app_utils.eas.get_broadcast_state", return_value=state), \
         patch("app_core.audio.alert_metadata.set_alert_metadata") as mock_set, \
         patch("app_core.audio.alert_metadata.clear_alert_metadata"):
        svc._reconcile_broadcast_metadata()
        svc._reconcile_broadcast_metadata()
        svc._reconcile_broadcast_metadata()

    mock_set.assert_called_once_with("Severe Thunderstorm Warning")


def test_updates_metadata_when_label_changes_mid_broadcast():
    _reset_applied_label()
    with patch("app_utils.eas.get_broadcast_state") as mock_state, \
         patch("app_core.audio.alert_metadata.set_alert_metadata") as mock_set, \
         patch("app_core.audio.alert_metadata.clear_alert_metadata"):
        mock_state.return_value = {"active": True, "label": "Flood Watch"}
        svc._reconcile_broadcast_metadata()
        mock_state.return_value = {"active": True, "label": "Flood Warning"}
        svc._reconcile_broadcast_metadata()

    assert mock_set.call_args_list == [
        (("Flood Watch",), {}), (("Flood Warning",), {}),
    ]


def test_clears_metadata_on_transition_to_inactive():
    _reset_applied_label()
    svc._applied_broadcast_metadata_label = "Flash Flood Warning"
    with patch("app_utils.eas.get_broadcast_state", return_value={"active": False}), \
         patch("app_core.audio.alert_metadata.set_alert_metadata") as mock_set, \
         patch("app_core.audio.alert_metadata.clear_alert_metadata") as mock_clear:
        svc._reconcile_broadcast_metadata()

    mock_clear.assert_called_once()
    mock_set.assert_not_called()
    assert svc._applied_broadcast_metadata_label is None


def test_noop_while_already_idle():
    _reset_applied_label()
    with patch("app_utils.eas.get_broadcast_state", return_value={"active": False}), \
         patch("app_core.audio.alert_metadata.set_alert_metadata") as mock_set, \
         patch("app_core.audio.alert_metadata.clear_alert_metadata") as mock_clear:
        svc._reconcile_broadcast_metadata()
        svc._reconcile_broadcast_metadata()

    mock_set.assert_not_called()
    mock_clear.assert_not_called()


def test_falls_back_to_event_code_when_label_missing():
    _reset_applied_label()
    with patch("app_utils.eas.get_broadcast_state", return_value={
        "active": True, "label": "", "event_code": "TOR",
    }), \
         patch("app_core.audio.alert_metadata.set_alert_metadata") as mock_set, \
         patch("app_core.audio.alert_metadata.clear_alert_metadata"):
        svc._reconcile_broadcast_metadata()

    mock_set.assert_called_once_with("TOR")


def test_exception_is_swallowed_not_raised():
    """A Redis/import failure inside the reconcile must never propagate
    into the audio service's main loop -- it's a display nicety, not
    something that may ever interrupt metrics publishing or airchain
    control."""
    _reset_applied_label()
    with patch("app_utils.eas.get_broadcast_state", side_effect=RuntimeError("boom")):
        svc._reconcile_broadcast_metadata()  # must not raise
