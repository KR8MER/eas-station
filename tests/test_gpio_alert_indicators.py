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

"""Tests for the tower-light / NeoPixel alert-indicator state machine."""

from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.gpio.alert_indicators as indicators
from services.gpio.alert_indicators import (
    AlertIndicatorMonitor,
    in_quiet_hours,
    resolve_tower_state,
)
from app_utils.gpio import TowerLightConfig


class _FakeTower:
    """Records show_state() calls; carries a real TowerLightConfig."""

    def __init__(self, available=True, **config_overrides):
        self.config = TowerLightConfig(**config_overrides)
        self.is_available = available
        self.states = []  # list of (color, flash, buzzer) tuples

    def show_state(self, color, flash=False, buzzer=False, fallback="off"):
        self.states.append((color, flash, buzzer))


class _FakeNeo:
    def __init__(self):
        self.events = []

    def start_alert(self):
        self.events.append("start_alert")

    def end_alert(self):
        self.events.append("end_alert")


def _patch_state(
    monkeypatch, *, broadcast, incoming, event_code="", redis_ok=True, dead_air_active=False
):
    """Patch the Redis-backed state readers used by update_alert_indicators.

    ``dead_air_active`` defaults to False so every test that doesn't care
    about the dead-air fault light gets a clean, deterministic "no fault"
    reading -- without this the tests read this station's *live*
    ``eas:dead_air`` Redis key, and pass or fail based on whether a real
    source happened to be alarming at the moment the suite ran.
    """
    import app_utils.eas as eas

    broadcast_payload = (
        {"active": True, "event_code": event_code} if broadcast else {"active": False}
    )
    monkeypatch.setattr(eas, "get_broadcast_state", lambda: dict(broadcast_payload))
    monkeypatch.setattr(eas, "get_incoming_alert_state", lambda: {"incoming": incoming})
    monkeypatch.setattr(indicators, "_redis_ok", lambda: redis_ok)
    monkeypatch.setattr(
        indicators,
        "read_dead_air_state",
        lambda: {
            "active": dead_air_active,
            "sources": {"TEST-SRC": {}} if dead_air_active else {},
            "acknowledged": False,
        },
    )


# ---------------------------------------------------------------------------
# Monitor lifecycle (applied states)
# ---------------------------------------------------------------------------


def test_monitor_idle_to_incoming_to_broadcast_to_idle(monkeypatch):
    """Monitor walks the full lifecycle and applies each state exactly once."""
    tower = _FakeTower()
    neo = _FakeNeo()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower, neopixel_controller=neo)

    # init → standby (green steady)
    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.states == [("green", False, False)]
    assert neo.events == []

    # standby → incoming (yellow flashing; NeoPixel unaffected until broadcast)
    _patch_state(monkeypatch, broadcast=False, incoming=True)
    monitor.refresh()
    assert tower.states[-1] == ("yellow", True, False)
    assert neo.events == []

    # incoming → active broadcast (red + NeoPixel alert)
    _patch_state(monkeypatch, broadcast=True, incoming=False, event_code="TOR")
    monitor.refresh()
    assert tower.states[-1] == ("red", True, False)
    assert neo.events == ["start_alert"]

    # active → idle (back to standby)
    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.states[-1] == ("green", False, False)
    assert neo.events[-1] == "end_alert"


def test_monitor_is_idempotent_across_repeated_refreshes(monkeypatch):
    """Re-reading the same active state must not re-write the hardware."""
    tower = _FakeTower()
    neo = _FakeNeo()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower, neopixel_controller=neo)

    _patch_state(monkeypatch, broadcast=True, incoming=False, event_code="TOR")
    monitor.refresh()
    monitor.refresh()
    monitor.refresh()

    assert len(tower.states) == 1
    assert neo.events.count("start_alert") == 1


def test_monitor_incoming_expires_without_broadcast(monkeypatch):
    """An incoming alert that expires without a broadcast returns to standby."""
    tower = _FakeTower()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower)

    _patch_state(monkeypatch, broadcast=False, incoming=True)
    monitor.refresh()
    assert tower.states[-1] == ("yellow", True, False)

    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.states[-1] == ("green", False, False)


def test_monitor_gate_pending_lights_blue_and_yields_to_alert(monkeypatch):
    """AlertIndicatorMonitor threads pending_gate_count_fn into the tower colour,
    not just the GATE_PENDING relay -- and a live alert still takes priority."""
    tower = _FakeTower()
    pending_count = {"n": 2}
    monitor = AlertIndicatorMonitor(
        tower_light_controller=tower,
        pending_gate_count_fn=lambda: pending_count["n"],
    )

    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.states[-1] == ("blue", True, False)

    # A live broadcast still wins over a non-empty Pending Alerts queue.
    _patch_state(monkeypatch, broadcast=True, incoming=False, event_code="TOR")
    monitor.refresh()
    assert tower.states[-1] == ("red", True, False)

    # Broadcast ends, queue is now empty -> standby, not blue.
    pending_count["n"] = 0
    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.states[-1] == ("green", False, False)


def test_monitor_shows_fault_when_redis_down(monkeypatch):
    """Redis loss drives the fault state instead of silently sitting stale."""
    tower = _FakeTower()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower)

    _patch_state(monkeypatch, broadcast=False, incoming=False, redis_ok=False)
    monitor.refresh()
    assert tower.states[-1] == ("magenta", True, False)

    # Recovery returns to standby.
    _patch_state(monkeypatch, broadcast=False, incoming=False, redis_ok=True)
    monitor.refresh()
    assert tower.states[-1] == ("green", False, False)


def test_monitor_state_read_error_resolves_to_fault(monkeypatch):
    """If the state readers raise, the tower indicates a fault (NeoPixel untouched)."""
    import app_utils.eas as eas

    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(eas, "get_broadcast_state", boom)
    monkeypatch.setattr(eas, "get_incoming_alert_state", lambda: {"incoming": False})
    monkeypatch.setattr(indicators, "_redis_ok", lambda: True)

    tower = _FakeTower()
    neo = _FakeNeo()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower, neopixel_controller=neo)
    monitor.refresh()

    assert tower.states[-1] == ("magenta", True, False)
    assert neo.events == []


# ---------------------------------------------------------------------------
# resolve_tower_state (pure resolver)
# ---------------------------------------------------------------------------


def test_resolver_test_broadcast_uses_test_color_and_no_buzzer():
    cfg = TowerLightConfig(alert_buzzer=True)
    state = resolve_tower_state(cfg, {"active": True, "event_code": "RWT"}, False, True)
    assert state.name == "test"
    assert state.color == "cyan"
    assert state.buzzer is False


def test_resolver_severity_colors():
    cfg = TowerLightConfig(severity_colors_enabled=True, alert_buzzer=True)
    warning = resolve_tower_state(cfg, {"active": True, "event_code": "TOR"}, False, True)
    watch = resolve_tower_state(cfg, {"active": True, "event_code": "SVA"}, False, True)
    advisory = resolve_tower_state(cfg, {"active": True, "event_code": "ADR"}, False, True)

    assert (warning.name, warning.color, warning.buzzer) == ("alert_warning", "red", True)
    assert (watch.name, watch.color) == ("alert_watch", "yellow")
    assert (advisory.name, advisory.color) == ("alert_advisory", "white")


def test_resolver_severity_disabled_uses_single_alert_color():
    cfg = TowerLightConfig(alert_color="blue")
    state = resolve_tower_state(cfg, {"active": True, "event_code": "TOR"}, False, True)
    assert (state.name, state.color) == ("alert", "blue")


def test_resolver_fault_beats_everything_unless_disabled():
    cfg = TowerLightConfig()
    state = resolve_tower_state(cfg, {"active": True, "event_code": "TOR"}, True, False)
    assert state.name == "fault"

    cfg_no_fault = TowerLightConfig(fault_enabled=False)
    state = resolve_tower_state(cfg_no_fault, {"active": True, "event_code": "TOR"}, True, False)
    assert state.name == "alert"


def test_resolver_quiet_hours_dark_standby_but_alerts_override():
    cfg = TowerLightConfig(quiet_enabled=True, quiet_start="22:00", quiet_end="07:00")
    night = datetime(2026, 6, 12, 23, 30)

    standby = resolve_tower_state(cfg, {"active": False}, False, True, now=night)
    assert (standby.name, standby.color) == ("quiet", "off")

    alert = resolve_tower_state(
        cfg, {"active": True, "event_code": "TOR"}, False, True, now=night
    )
    assert alert.name == "alert"

    incoming = resolve_tower_state(cfg, {"active": False}, True, True, now=night)
    assert incoming.name == "incoming"

    day = datetime(2026, 6, 12, 12, 0)
    standby_day = resolve_tower_state(cfg, {"active": False}, False, True, now=day)
    assert standby_day.name == "standby"


def test_resolver_incoming_disabled_falls_through_to_standby():
    cfg = TowerLightConfig(incoming_uses_yellow=False)
    state = resolve_tower_state(cfg, {"active": False}, True, True)
    assert state.name == "standby"


def test_resolver_active_alert_holds_yellow_after_broadcast():
    """An unexpired alert keeps the light lit (yellow) after playout ends.

    Regression for the light dropping to green standby while an alert is
    still active — it must match the website stack light.
    """
    cfg = TowerLightConfig()
    state = resolve_tower_state(
        cfg, {"active": False}, False, True, active_alert_count=2
    )
    assert (state.name, state.color, state.flash) == ("active", "yellow", True)


def test_resolver_active_alert_respects_incoming_disabled():
    """When incoming yellow is disabled, active alerts still fall to standby."""
    cfg = TowerLightConfig(incoming_uses_yellow=False)
    state = resolve_tower_state(
        cfg, {"active": False}, False, True, active_alert_count=3
    )
    assert state.name == "standby"


def test_resolver_active_broadcast_beats_active_alert_count():
    """A live broadcast still wins over a non-zero active alert count."""
    cfg = TowerLightConfig()
    state = resolve_tower_state(
        cfg, {"active": True, "event_code": "TOR"}, False, True, active_alert_count=5
    )
    assert (state.name, state.color) == ("alert", "red")


def test_resolver_active_alert_overrides_quiet_hours():
    cfg = TowerLightConfig(quiet_enabled=True, quiet_start="22:00", quiet_end="07:00")
    night = datetime(2026, 6, 12, 23, 30)
    state = resolve_tower_state(
        cfg, {"active": False}, False, True, now=night, active_alert_count=1
    )
    assert (state.name, state.color) == ("active", "yellow")


def test_resolver_gate_pending_shows_blue_when_queue_nonempty():
    """A non-empty Pending Alerts queue shows blue, flashing, no buzzer."""
    cfg = TowerLightConfig()
    state = resolve_tower_state(
        cfg, {"active": False}, False, True, pending_gate_count=3
    )
    assert (state.name, state.color, state.flash, state.buzzer) == (
        "gate_pending", "blue", True, False,
    )


def test_resolver_gate_pending_disabled_falls_through_to_standby():
    cfg = TowerLightConfig(gate_pending_enabled=False)
    state = resolve_tower_state(
        cfg, {"active": False}, False, True, pending_gate_count=3
    )
    assert state.name == "standby"


def test_resolver_active_alert_beats_gate_pending():
    """An active/incoming alert must never be buried by a pending-review indication."""
    cfg = TowerLightConfig()
    state = resolve_tower_state(
        cfg, {"active": False}, True, True, pending_gate_count=5
    )
    assert state.name == "incoming"

    state_active_count = resolve_tower_state(
        cfg, {"active": False}, False, True, active_alert_count=1, pending_gate_count=5
    )
    assert state_active_count.name == "active"


def test_resolver_broadcast_beats_gate_pending():
    cfg = TowerLightConfig()
    state = resolve_tower_state(
        cfg, {"active": True, "event_code": "TOR"}, False, True, pending_gate_count=5
    )
    assert (state.name, state.color) == ("alert", "red")


def test_resolver_gate_pending_overrides_quiet_hours():
    """Pending Alerts must never be silenced by a dark quiet-hours schedule."""
    cfg = TowerLightConfig(quiet_enabled=True, quiet_start="22:00", quiet_end="07:00")
    night = datetime(2026, 6, 12, 23, 30)
    state = resolve_tower_state(
        cfg, {"active": False}, False, True, now=night, pending_gate_count=2
    )
    assert (state.name, state.color) == ("gate_pending", "blue")


def test_monitor_holds_yellow_after_broadcast_with_active_alert(monkeypatch):
    """Full lifecycle: broadcast ends but an alert is still active → yellow, not green."""
    tower = _FakeTower()
    neo = _FakeNeo()
    monitor = AlertIndicatorMonitor(
        tower_light_controller=tower,
        neopixel_controller=neo,
        active_alert_count_fn=lambda: 1,
    )

    # active broadcast → red + NeoPixel alert
    _patch_state(monkeypatch, broadcast=True, incoming=False, event_code="TOR")
    monitor.refresh()
    assert tower.states[-1] == ("red", True, False)
    assert neo.events == ["start_alert"]

    # broadcast ends but the alert is still active → stay yellow (NOT green).
    # NeoPixel still returns to standby (its two-state edge behaviour is unchanged).
    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.states[-1] == ("yellow", True, False)
    assert neo.events[-1] == "end_alert"


def test_monitor_returns_green_once_alert_expires(monkeypatch):
    """When the active alert count drops to zero the light returns to green."""
    tower = _FakeTower()
    counts = [1]
    monitor = AlertIndicatorMonitor(
        tower_light_controller=tower,
        active_alert_count_fn=lambda: counts[0],
    )

    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.states[-1] == ("yellow", True, False)

    counts[0] = 0
    monitor.refresh()
    assert tower.states[-1] == ("green", False, False)


def test_monitor_active_alert_count_failure_is_non_fatal(monkeypatch):
    """A raising count function is swallowed (treated as zero), not crashing the loop."""
    tower = _FakeTower()

    def boom():
        raise RuntimeError("db down")

    monitor = AlertIndicatorMonitor(
        tower_light_controller=tower,
        active_alert_count_fn=boom,
    )

    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.states[-1] == ("green", False, False)


# ---------------------------------------------------------------------------
# in_quiet_hours
# ---------------------------------------------------------------------------


def test_quiet_hours_overnight_wrap():
    assert in_quiet_hours("22:00", "07:00", datetime(2026, 1, 1, 23, 0)) is True
    assert in_quiet_hours("22:00", "07:00", datetime(2026, 1, 1, 3, 0)) is True
    assert in_quiet_hours("22:00", "07:00", datetime(2026, 1, 1, 12, 0)) is False


def test_quiet_hours_same_day_window():
    assert in_quiet_hours("09:00", "17:00", datetime(2026, 1, 1, 12, 0)) is True
    assert in_quiet_hours("09:00", "17:00", datetime(2026, 1, 1, 8, 59)) is False
    assert in_quiet_hours("09:00", "17:00", datetime(2026, 1, 1, 17, 0)) is False


def test_quiet_hours_invalid_or_equal_disables():
    assert in_quiet_hours("nonsense", "07:00", datetime(2026, 1, 1, 23, 0)) is False
    assert in_quiet_hours(None, None, datetime(2026, 1, 1, 23, 0)) is False
    assert in_quiet_hours("08:00", "08:00", datetime(2026, 1, 1, 8, 0)) is False
