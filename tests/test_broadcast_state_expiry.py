"""Regression tests for broadcast-state self-expiry.

The on-air overlay and tower light read the broadcast marker through
``get_broadcast_state``.  The send worker clears the marker the instant
playout finishes, but if that thread is delayed or blocked the indicators
must still stop reporting an active broadcast once the broadcast's own
``start_ts + duration_seconds`` (plus a short grace) has elapsed — otherwise
the popup and tower light linger past end-of-message.
"""

import json
import time
import types
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_utils.eas as eas


class _FakeRedis:
    """Minimal in-memory stand-in for the Redis client get/set/delete API."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)

    def publish(self, *_args, **_kwargs):
        pass


def _install(monkeypatch):
    """Make ``get_broadcast_state``'s ``from app_core.redis_client import
    get_redis_client`` resolve to a fake client, without importing the real
    redis-backed module (and its heavy package side effects)."""
    client = _FakeRedis()
    fake_module = types.ModuleType("app_core.redis_client")
    fake_module.get_redis_client = lambda: client
    monkeypatch.setitem(sys.modules, "app_core.redis_client", fake_module)
    return client


def test_broadcast_active_during_playout(monkeypatch):
    client = _install(monkeypatch)
    client.store[eas._BROADCAST_STATE_KEY] = json.dumps({
        "active": True,
        "start_ts": time.time(),          # just started
        "duration_seconds": 14.0,
        "event_code": "RWT",
    })
    assert eas.get_broadcast_state().get("active") is True


def test_broadcast_self_expires_after_end_of_message(monkeypatch):
    client = _install(monkeypatch)
    # Started long enough ago that start_ts + duration + grace is in the past,
    # but the worker never cleared the marker (key still present).
    client.store[eas._BROADCAST_STATE_KEY] = json.dumps({
        "active": True,
        "start_ts": time.time() - 100.0,
        "duration_seconds": 14.0,
        "event_code": "RWT",
    })
    assert eas.get_broadcast_state().get("active") is False
    # Marker is lazily dropped so repeated reads / WS pushes don't resurrect it.
    assert client.store.get(eas._BROADCAST_STATE_KEY) is None


def test_broadcast_active_within_grace_window(monkeypatch):
    client = _install(monkeypatch)
    # End-of-message reached, but still inside the grace window — the overlay
    # should keep showing the "END OF MESSAGE" confirmation.
    client.store[eas._BROADCAST_STATE_KEY] = json.dumps({
        "active": True,
        "start_ts": time.time() - 15.0,   # 1s past a 14s broadcast
        "duration_seconds": 14.0,
        "event_code": "RWT",
    })
    assert eas.get_broadcast_state().get("active") is True


def test_broadcast_missing_duration_is_left_untouched(monkeypatch):
    client = _install(monkeypatch)
    # Defensive: a marker without timing fields must not be force-expired.
    client.store[eas._BROADCAST_STATE_KEY] = json.dumps({"active": True})
    assert eas.get_broadcast_state().get("active") is True
