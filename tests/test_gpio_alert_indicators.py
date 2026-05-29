"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.gpio.alert_indicators as indicators
from services.gpio.alert_indicators import AlertIndicatorMonitor


class _FakeTower:
    def __init__(self, available=True):
        self.is_available = available
        self.events = []

    def start_alert(self):
        self.events.append("start_alert")

    def start_incoming_alert(self):
        self.events.append("start_incoming")

    def end_alert(self):
        self.events.append("end_alert")


class _FakeNeo:
    def __init__(self):
        self.events = []

    def start_alert(self):
        self.events.append("start_alert")

    def end_alert(self):
        self.events.append("end_alert")


def _patch_state(monkeypatch, *, broadcast, incoming):
    """Patch the Redis-backed state readers used by update_alert_indicators."""
    import app_utils.eas as eas

    monkeypatch.setattr(eas, "get_broadcast_state", lambda: {"active": broadcast})
    monkeypatch.setattr(eas, "get_incoming_alert_state", lambda: {"incoming": incoming})


def test_monitor_idle_to_incoming_to_broadcast_to_idle(monkeypatch):
    """Monitor walks the full lifecycle and fires each transition exactly once."""

    tower = _FakeTower()
    neo = _FakeNeo()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower, neopixel_controller=neo)

    # idle → incoming (yellow on tower; NeoPixel unaffected until broadcast)
    _patch_state(monkeypatch, broadcast=False, incoming=True)
    monitor.refresh()
    assert tower.events == ["start_incoming"]
    assert neo.events == []

    # incoming → active broadcast (red + NeoPixel alert)
    _patch_state(monkeypatch, broadcast=True, incoming=False)
    monitor.refresh()
    assert tower.events[-1] == "start_alert"
    assert neo.events == ["start_alert"]

    # active → idle (back to standby)
    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.events[-1] == "end_alert"
    assert neo.events[-1] == "end_alert"


def test_monitor_is_idempotent_across_repeated_refreshes(monkeypatch):
    """Re-reading the same active state must not re-fire start_alert."""

    tower = _FakeTower()
    neo = _FakeNeo()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower, neopixel_controller=neo)

    _patch_state(monkeypatch, broadcast=True, incoming=False)
    monitor.refresh()
    monitor.refresh()
    monitor.refresh()

    assert tower.events.count("start_alert") == 1
    assert neo.events.count("start_alert") == 1


def test_monitor_incoming_expires_without_broadcast(monkeypatch):
    """An incoming alert that expires without a broadcast returns the tower to standby."""

    tower = _FakeTower()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower)

    _patch_state(monkeypatch, broadcast=False, incoming=True)
    monitor.refresh()
    assert tower.events == ["start_incoming"]

    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert tower.events[-1] == "end_alert"


def test_monitor_survives_state_read_errors(monkeypatch):
    """If the Redis state read raises, the monitor leaves indicators untouched."""

    import app_utils.eas as eas

    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(eas, "get_broadcast_state", boom)
    monkeypatch.setattr(eas, "get_incoming_alert_state", lambda: {"incoming": False})

    tower = _FakeTower()
    monitor = AlertIndicatorMonitor(tower_light_controller=tower)
    # Should not raise, and should not drive the tower.
    monitor.refresh()
    assert tower.events == []
