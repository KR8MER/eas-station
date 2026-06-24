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

"""Tests for centralized GPIO relay keying in the eas-station-gpio subprocess.

The subprocess is the single owner of the physical relay lines.  It keys them
off the Redis broadcast-state / incoming-alert markers every producer publishes
(rather than each producer building its own contending controller), and it
executes operator-initiated manual control commands from the web UI over a
Redis command channel.  These tests cover both flows with fakes so no Redis or
GPIO hardware is required.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.gpio.alert_indicators as indicators
from services.gpio.alert_indicators import AlertIndicatorMonitor
from app_core.gpio_commands import dispatch_gpio_command


class _FakeBehaviorManager:
    """Records the behavior-manager calls the monitor makes."""

    def __init__(self):
        self.starts = []
        self.ends = []
        self.incoming = []

    def start_alert(self, *, alert_id=None, event_code=None, reason=None, forwarded=False):
        self.starts.append(
            {"alert_id": alert_id, "event_code": event_code, "forwarded": forwarded}
        )
        return True

    def end_alert(self, *, alert_id=None, event_code=None, forwarded=False):
        self.ends.append(
            {"alert_id": alert_id, "event_code": event_code, "forwarded": forwarded}
        )

    def trigger_incoming_alert(self, *, alert_id=None, event_code=None):
        self.incoming.append({"alert_id": alert_id, "event_code": event_code})


class _FakeController:
    """Minimal controller exposing the surface the keying/dispatch code uses."""

    def __init__(self, behavior_manager=None):
        self.behavior_manager = behavior_manager
        self.activated = []
        self.deactivated = []
        self.activate_all_calls = []
        self.deactivate_all_calls = []

    def activate(self, *, pin, activation_type=None, operator=None, alert_id=None, reason=None):
        self.activated.append({"pin": pin, "operator": operator, "reason": reason})
        return True

    def deactivate(self, *, pin, force=False):
        self.deactivated.append({"pin": pin, "force": force})
        return True

    def activate_all(self, *, activation_type=None, operator=None, alert_id=None, reason=None):
        self.activate_all_calls.append({"alert_id": alert_id, "reason": reason})
        return {1: True}

    def deactivate_all(self, *, force=False):
        self.deactivate_all_calls.append({"force": force})
        return {1: True}


def _patch_state(monkeypatch, *, broadcast, incoming, event_code="", source="auto",
                 identifier="", redis_ok=True):
    """Patch the Redis-backed state readers used by update_alert_indicators."""
    import app_utils.eas as eas

    if broadcast:
        broadcast_payload = {
            "active": True,
            "event_code": event_code,
            "source": source,
            "identifier": identifier,
        }
    else:
        broadcast_payload = {"active": False}

    incoming_payload = (
        {"incoming": True, "event_code": event_code} if incoming else {"incoming": False}
    )
    monkeypatch.setattr(eas, "get_broadcast_state", lambda: dict(broadcast_payload))
    monkeypatch.setattr(eas, "get_incoming_alert_state", lambda: dict(incoming_payload))
    monkeypatch.setattr(indicators, "_redis_ok", lambda: redis_ok)


# ---------------------------------------------------------------------------
# Relay keying off broadcast / incoming edges
# ---------------------------------------------------------------------------


def test_relay_keyed_and_released_on_broadcast_edges(monkeypatch):
    """Rising edge holds the relay; falling edge releases it (once each)."""
    bm = _FakeBehaviorManager()
    controller = _FakeController(behavior_manager=bm)
    monitor = AlertIndicatorMonitor(gpio_controller=controller)

    # Idle -> nothing.
    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert bm.starts == [] and bm.ends == []

    # Broadcast starts -> start_alert once with the alert identity.
    _patch_state(
        monkeypatch, broadcast=True, incoming=False,
        event_code="RWT", source="automated_rwt", identifier="RWT-AUTO-1",
    )
    monitor.refresh()
    assert len(bm.starts) == 1
    assert bm.starts[0]["alert_id"] == "RWT-AUTO-1"
    assert bm.starts[0]["event_code"] == "RWT"
    assert bm.starts[0]["forwarded"] is False

    # Still active -> no duplicate start.
    monitor.refresh()
    assert len(bm.starts) == 1

    # Broadcast ends -> end_alert once.  The falling edge reads {active: False}
    # (no source/code), so the release uses forwarded=True as a safe superset.
    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert len(bm.ends) == 1
    assert bm.ends[0]["forwarded"] is True


def test_forwarded_source_holds_forwarding_pins(monkeypatch):
    """A 'forwarded' broadcast source keys start_alert(forwarded=True)."""
    bm = _FakeBehaviorManager()
    controller = _FakeController(behavior_manager=bm)
    monitor = AlertIndicatorMonitor(gpio_controller=controller)

    _patch_state(
        monkeypatch, broadcast=True, incoming=False,
        event_code="TOR", source="forwarded", identifier="urn:cap:1",
    )
    monitor.refresh()
    assert bm.starts[0]["forwarded"] is True


def test_incoming_alert_pulses_relay(monkeypatch):
    """The incoming-alert rising edge pulses INCOMING_ALERT pins once."""
    bm = _FakeBehaviorManager()
    controller = _FakeController(behavior_manager=bm)
    monitor = AlertIndicatorMonitor(gpio_controller=controller)

    _patch_state(monkeypatch, broadcast=False, incoming=True, event_code="TOR")
    monitor.refresh()
    assert len(bm.incoming) == 1
    assert bm.incoming[0]["event_code"] == "TOR"

    # Still incoming -> no duplicate pulse.
    monitor.refresh()
    assert len(bm.incoming) == 1


def test_relay_fallback_without_behavior_manager(monkeypatch):
    """With no behavior matrix the subprocess keys every pin via activate_all."""
    controller = _FakeController(behavior_manager=None)
    monitor = AlertIndicatorMonitor(gpio_controller=controller)

    _patch_state(monkeypatch, broadcast=True, incoming=False, event_code="RMT")
    monitor.refresh()
    assert len(controller.activate_all_calls) == 1

    _patch_state(monkeypatch, broadcast=False, incoming=False)
    monitor.refresh()
    assert controller.deactivate_all_calls == [{"force": True}]


# ---------------------------------------------------------------------------
# Manual command dispatch
# ---------------------------------------------------------------------------


def test_dispatch_activate_command():
    controller = _FakeController()
    ok = dispatch_gpio_command(
        controller,
        {"action": "activate", "pin": 17, "operator": "admin", "reason": "test"},
    )
    assert ok is True
    assert controller.activated == [{"pin": 17, "operator": "admin", "reason": "test"}]


def test_dispatch_deactivate_force_command():
    controller = _FakeController()
    ok = dispatch_gpio_command(
        controller, {"action": "deactivate", "pin": 17, "force": True}
    )
    assert ok is True
    assert controller.deactivated == [{"pin": 17, "force": True}]


def test_dispatch_unknown_action_is_noop():
    controller = _FakeController()
    assert dispatch_gpio_command(controller, {"action": "explode", "pin": 1}) is False
    assert controller.activated == []


def test_dispatch_without_controller_is_safe():
    assert dispatch_gpio_command(None, {"action": "activate", "pin": 1}) is False


# ---------------------------------------------------------------------------
# Broadcast-marker lifecycle (identifier + return value + guarded clear)
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Tiny in-memory stand-in for the Redis client used by the marker helpers."""

    def __init__(self):
        self.store = {}

    def set(self, key, value, ex=None):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)

    def publish(self, channel, message):
        return 0


def _patch_redis(monkeypatch, client):
    import app_core.redis_client as rc
    monkeypatch.setattr(rc, "get_redis_client", lambda *a, **k: client)


def test_set_broadcast_active_returns_true_when_written(monkeypatch):
    import app_utils.eas as eas

    client = _FakeRedis()
    _patch_redis(monkeypatch, client)
    ok = eas.set_broadcast_active("RWT", "Test", 30.0, source="automated_rwt", identifier="RWT-1")
    assert ok is True
    import json
    stored = json.loads(client.store[eas._BROADCAST_STATE_KEY])
    assert stored["identifier"] == "RWT-1"


def test_set_broadcast_active_returns_false_without_redis(monkeypatch):
    import app_utils.eas as eas

    _patch_redis(monkeypatch, None)
    assert eas.set_broadcast_active("RWT", "Test", 30.0) is False


def test_clear_broadcast_active_guarded_by_identifier(monkeypatch):
    import app_utils.eas as eas

    client = _FakeRedis()
    _patch_redis(monkeypatch, client)

    # A newer broadcast (idB) owns the marker.
    eas.set_broadcast_active("TOR", "Tornado", 60.0, identifier="idB")

    # An older broadcast (idA) finishing must NOT erase idB's marker.
    eas.clear_broadcast_active(identifier="idA")
    assert eas._BROADCAST_STATE_KEY in client.store

    # The owning broadcast clears its own marker.
    eas.clear_broadcast_active(identifier="idB")
    assert eas._BROADCAST_STATE_KEY not in client.store


def test_set_incoming_alert_carries_identifier(monkeypatch):
    import json
    import app_utils.eas as eas

    client = _FakeRedis()
    _patch_redis(monkeypatch, client)
    eas.set_incoming_alert(event_code="TOR", identifier="urn:cap:42")
    stored = json.loads(client.store[eas._INCOMING_STATE_KEY])
    assert stored["identifier"] == "urn:cap:42"
    assert stored["event_code"] == "TOR"
