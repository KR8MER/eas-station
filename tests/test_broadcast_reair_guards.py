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

"""Regression tests for the 2026-09-24 Flood Warning re-air loop.

A 165 s CAP broadcast outlasted the poller's 180 s WatchdogSec; systemd
killed the poller mid-playout before eas_forwarded was written, and each
restart's catch-up sweep aired the alert again (19 times in an hour).  Three
guards failed or were missing:

* nothing fed the watchdog during the blocking broadcast
  (``watchdog_keepalive`` around ``EASBroadcaster.handle_alert``);
* the full-FIPS dedup compared the alert's *full* SAME set against the
  broadcast's coverage-filtered locations, so it never matched
  (``filter_same_codes_to_coverage``);
* the display's per-second active-alert query pulled every stored broadcast's
  audio blobs (``load_alert_plain_text_map``).

The catch-up sweep's own guard is pinned in test_forwarding_pipeline_guard.py.
"""

import inspect
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app_utils.eas.same_header_build import filter_same_codes_to_coverage
from app_utils.system import sd_notify

pytestmark = pytest.mark.unit


# -- coverage filter --------------------------------------------------------

def test_filter_keeps_only_configured_counties():
    settings = {"fips_codes": ["039161", "039137"]}
    assert filter_same_codes_to_coverage(
        ["018001", "018003", "039161"], settings
    ) == ["039161"]


def test_filter_preserves_statewide_and_nationwide_wildcards():
    settings = {"fips_codes": ["039161"]}
    assert filter_same_codes_to_coverage(
        ["000000", "039000", "018001"], settings
    ) == ["000000", "039000"]


def test_filter_is_passthrough_without_configured_coverage():
    assert filter_same_codes_to_coverage(["018001"], {}) == ["018001"]
    assert filter_same_codes_to_coverage(["018001"], None) == ["018001"]


def test_cap_dedup_compares_coverage_filtered_fips():
    """auto_forward_cap_alert must hand is_duplicate_broadcast the same
    coverage-filtered FIPS set the broadcast records as its locations, while
    the advisory-lock key stays on the unfiltered set (shared with OTA)."""
    from tests.test_alert_gating import _cap_alert, _load_auto_forward_module

    mod = _load_auto_forward_module()
    cap_alert = _cap_alert(severity="Extreme", event="Flood Warning")
    with patch.object(mod, "_update_cap_forwarding_status"), \
         patch.object(mod, "_publish_endec_feed"), \
         patch.object(mod, "_resolve_event_code", return_value="FLS"), \
         patch.object(mod, "_acquire_dedupe_lock"), \
         patch.object(mod, "_alert_dedupe_lock_key", return_value=None) as lock_key, \
         patch.object(mod, "is_duplicate_broadcast", return_value=True) as is_dup:
        result = mod.auto_forward_cap_alert(
            cap_alert,
            {"raw_json": {"properties": {"geocode": {
                "SAME": ["018001", "018003", "039161"],
            }}}},
            db_session=MagicMock(),
            eas_message_cls=MagicMock(),
            eas_config={"enabled": True, "forwarded_event_codes": []},
            location_settings={"fips_codes": ["039161"]},
        )

    assert "duplicate" in (result.get("reason") or "").lower()
    assert is_dup.call_args.args[1] == ["039161"]
    assert lock_key.call_args.args[1] == ["018001", "018003", "039161"]


# -- watchdog keepalive -----------------------------------------------------

def test_keepalive_is_noop_outside_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    before = threading.active_count()
    with sd_notify.watchdog_keepalive(10):
        assert threading.active_count() == before


def test_keepalive_pings_while_blocked_and_stops_after(monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", "/nonexistent")
    pings = []
    pinged = threading.Event()

    def _notify(state):
        pings.append(state)
        pinged.set()
        return True

    monkeypatch.setattr(sd_notify, "notify", _notify)
    with sd_notify.watchdog_keepalive(10, interval=0.01):
        assert pinged.wait(2), "keepalive never fed the watchdog"
    count = len(pings)
    threading.Event().wait(0.05)
    assert set(pings) == {"WATCHDOG=1"}
    assert len(pings) == count, "keepalive kept pinging after the block exited"


def test_keepalive_is_bounded(monkeypatch):
    """A call that hangs past its budget must stop being covered, so the
    systemd watchdog can still catch a genuine hang."""
    monkeypatch.setenv("NOTIFY_SOCKET", "/nonexistent")
    pings = []
    monkeypatch.setattr(sd_notify, "notify", lambda state: pings.append(state) or True)
    with sd_notify.watchdog_keepalive(0.05, interval=0.01):
        threading.Event().wait(0.3)
    assert 0 < len(pings) < 15


def test_broadcaster_wraps_handle_alert_in_keepalive(monkeypatch):
    from app_utils.eas import broadcaster as bmod

    entered = []

    class _Keepalive:
        def __init__(self, budget):
            entered.append(budget)

        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(bmod, "watchdog_keepalive", _Keepalive)
    b = object.__new__(bmod.EASBroadcaster)
    b.config = {"max_activation_seconds": 300}
    monkeypatch.setattr(b, "_handle_alert", lambda alert, payload: {"ok": True}, raising=False)

    assert b.handle_alert(SimpleNamespace(), {}) == {"ok": True}
    # Budget covers generation + the longest permitted playout.
    assert entered and entered[0] >= 300 + bmod.GENERATION_BUDGET_SECONDS


# -- display text lookup ----------------------------------------------------

def test_plain_text_map_does_not_load_audio_blobs():
    """The OLED screen manager calls this every second; loading full
    EASMessage rows serialized every stored broadcast's audio each time."""
    from app_core import alerts

    source = inspect.getsource(alerts.load_alert_plain_text_map)
    assert "load_only(" in source
    for blob in ("audio_data", "eom_audio_data", "same_audio_data",
                 "attention_audio_data", "tts_audio_data", "buffer_audio_data"):
        assert f"EASMessage.{blob}" not in source
