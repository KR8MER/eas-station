"""Tests for the GPS holdover anchor surviving a manager restart.

Regression coverage for the dashboard's holdover card going blank: the
"last 3D fix" anchor that holdover is measured from used to live only in
memory, so a GPS-service restart *during* a holdover period reset it to
None and the dashboard rendered "—" / "unknown" even though the receiver
was still coasting. The anchor is now persisted to Redis and restored on
construction.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app_core.gps.gps_manager import GPSManager, REDIS_LAST_3D_KEY


class FakeRedis:
    """Minimal Redis stand-in covering the get/set the manager uses."""

    def __init__(self):
        self.store = {}

    def set(self, key, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)


def _manager(redis):
    # Empty config → all defaults; __init__ does not open the serial port or
    # start any threads, so this is safe to construct in a unit test.
    return GPSManager(config={}, redis_client=redis)


def test_anchor_persists_to_redis_on_3d_fix():
    redis = FakeRedis()
    mgr = _manager(redis)
    assert mgr._last_3d_fix_at is None

    mgr._mark_3d_fix()

    assert REDIS_LAST_3D_KEY in redis.store
    assert mgr._last_3d_fix_at is not None


def test_anchor_restored_after_restart_mid_holdover():
    redis = FakeRedis()
    # A previous process recorded a 3D fix 42 s ago, then the service
    # restarted while the receiver is still without a fix.
    redis.store[REDIS_LAST_3D_KEY] = (
        datetime.now(timezone.utc) - timedelta(seconds=42)
    ).isoformat()

    mgr = _manager(redis)

    assert mgr._last_3d_fix_at is not None, "anchor must restore from Redis"
    # Holdover is measured from the restored anchor, so it is a real
    # duration rather than the old blank/None.
    elapsed = (datetime.now(timezone.utc) - mgr._last_3d_fix_at).total_seconds()
    assert 41.0 <= elapsed <= 120.0


def test_malformed_persisted_anchor_is_ignored():
    redis = FakeRedis()
    redis.store[REDIS_LAST_3D_KEY] = "not-a-timestamp"

    mgr = _manager(redis)

    assert mgr._last_3d_fix_at is None


def test_no_redis_is_tolerated():
    mgr = _manager(None)
    assert mgr._last_3d_fix_at is None
    # Must not raise even though there is nowhere to persist.
    mgr._mark_3d_fix()
    assert mgr._last_3d_fix_at is not None
