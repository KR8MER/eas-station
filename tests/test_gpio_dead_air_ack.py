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

"""Tests for the GPIO-triggered "Acknowledge Dead Air" input action and the
shared acknowledge_dead_air() core function it reuses from the web route.
"""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeRedis:
    def __init__(self, kv=None):
        self.kv = dict(kv or {})
        self.deleted = []

    def get(self, key):
        return self.kv.get(key)

    def setex(self, key, ttl, value):
        self.kv[key] = value

    def delete(self, key):
        self.deleted.append(key)
        self.kv.pop(key, None)


@pytest.fixture
def redis_client_factory(monkeypatch):
    """Patch app_core.redis_client.get_redis_client for dead_air_alarm's use."""
    def _install(client):
        import app_core.redis_client as redis_client_module
        monkeypatch.setattr(redis_client_module, "get_redis_client", lambda: client)
    return _install


# ---------------------------------------------------------------------------
# Core acknowledge_dead_air() -- the shared logic
# ---------------------------------------------------------------------------


def test_acknowledge_requires_active_alarm(redis_client_factory):
    from app_core.audio.dead_air_alarm import acknowledge_dead_air

    redis_client_factory(_FakeRedis())  # no eas:dead_air key at all

    result = acknowledge_dead_air(acknowledged=True)

    assert result["ok"] is False
    assert result["status"] == 409
    assert "No dead-air alarm" in result["error"]


def test_acknowledge_succeeds_against_active_episode(redis_client_factory):
    from app_core.audio.dead_air_alarm import acknowledge_dead_air
    from app_core.config.redis_config import RedisChannels

    client = _FakeRedis({
        RedisChannels.DEAD_AIR_KEY: json.dumps({"active": True, "episode": "abc123"}),
    })
    redis_client_factory(client)

    result = acknowledge_dead_air(acknowledged=True)

    assert result["ok"] is True
    assert result["episode"] == "abc123"
    assert client.kv[RedisChannels.DEAD_AIR_ACK_KEY] == "abc123"


def test_acknowledge_rejects_stale_episode(redis_client_factory):
    from app_core.audio.dead_air_alarm import acknowledge_dead_air
    from app_core.config.redis_config import RedisChannels

    client = _FakeRedis({
        RedisChannels.DEAD_AIR_KEY: json.dumps({"active": True, "episode": "new-episode"}),
    })
    redis_client_factory(client)

    result = acknowledge_dead_air(acknowledged=True, requested_episode="old-episode")

    assert result["ok"] is False
    assert result["status"] == 409
    assert RedisChannels.DEAD_AIR_ACK_KEY not in client.kv


def test_unacknowledge_clears_the_ack_key(redis_client_factory):
    from app_core.audio.dead_air_alarm import acknowledge_dead_air
    from app_core.config.redis_config import RedisChannels

    client = _FakeRedis({RedisChannels.DEAD_AIR_ACK_KEY: "abc123"})
    redis_client_factory(client)

    result = acknowledge_dead_air(acknowledged=False)

    assert result == {"ok": True, "acknowledged": False}
    assert RedisChannels.DEAD_AIR_ACK_KEY in client.deleted


def test_no_redis_client_is_unavailable(redis_client_factory):
    from app_core.audio.dead_air_alarm import acknowledge_dead_air

    redis_client_factory(None)

    result = acknowledge_dead_air(acknowledged=True)

    assert result["ok"] is False
    assert result["status"] == 503


# ---------------------------------------------------------------------------
# GPIO wrapper + dispatch wiring
# ---------------------------------------------------------------------------


def test_gpio_wrapper_logs_success_on_ok(monkeypatch):
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr(
        "app_core.audio.dead_air_alarm.acknowledge_dead_air",
        lambda acknowledged=True: {"ok": True, "acknowledged": True, "episode": "xyz"},
    )

    # Must not raise regardless of outcome.
    gpio_input_actions.acknowledge_dead_air_alarm()


def test_gpio_wrapper_does_not_raise_on_failure(monkeypatch):
    from app_core.audio import gpio_input_actions

    monkeypatch.setattr(
        "app_core.audio.dead_air_alarm.acknowledge_dead_air",
        lambda acknowledged=True: {"ok": False, "error": "No dead-air alarm is currently active"},
    )

    gpio_input_actions.acknowledge_dead_air_alarm()


def test_dispatch_wiring_calls_ack_action(monkeypatch):
    from app_core import gpio_input_listener

    calls = []
    monkeypatch.setattr(
        "app_core.audio.gpio_input_actions.acknowledge_dead_air_alarm",
        lambda: calls.append(True),
    )

    gpio_input_listener._dispatch_input_action({"pin": 25, "action": "dead_air_ack"})

    assert calls == [True]


# ---------------------------------------------------------------------------
# Route delegation (source-level check, mirrors test_dead_air_monitoring.py's
# existing style for this file)
# ---------------------------------------------------------------------------


def test_route_still_uses_shared_function():
    routes = (ROOT / "webapp" / "admin" / "audio_ingest"
              / "routes_dead_air.py").read_text(encoding="utf-8")
    assert "from app_core.audio.dead_air_alarm import acknowledge_dead_air" in routes
