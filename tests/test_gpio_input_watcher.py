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

"""Tests for the GPIO input framework: pin reading, the cross-process event
channel, the web-app dispatch listener, config-loader parsing, and hardware
settings validation.
"""

from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_utils.gpio.input_watcher as input_watcher_module
from app_utils.gpio.input_watcher import GPIOInputWatcher
from app_utils.gpio.pin_types import GPIOInputAction, GPIOPinConfig


class _FakeButton:
    """Stand-in for gpiozero.Button that records construction args and lets
    the test fire the callback directly."""

    instances = []

    def __init__(self, pin, pull_up=True, bounce_time=None, hold_time=None):
        self.pin = pin
        self.pull_up = pull_up
        self.bounce_time = bounce_time
        self.hold_time = hold_time
        self.when_pressed = None
        self.when_held = None
        self.closed = False
        _FakeButton.instances.append(self)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_button():
    _FakeButton.instances = []
    yield
    _FakeButton.instances = []


@pytest.fixture
def patched_gpiozero(monkeypatch):
    """Make GPIOInputWatcher build _FakeButton instead of a real gpiozero.Button."""
    monkeypatch.setattr(input_watcher_module, "_Button", _FakeButton)
    monkeypatch.setattr(input_watcher_module, "_get_gpiozero_button", lambda: _FakeButton)
    monkeypatch.setattr(input_watcher_module, "ensure_gpiozero_pin_factory", lambda logger=None: True)
    return _FakeButton


# ---------------------------------------------------------------------------
# 1. Button construction, debounce pass-through, press -> queue
# ---------------------------------------------------------------------------


def test_press_enqueues_pin_and_action(patched_gpiozero):
    config = GPIOPinConfig(
        pin=17, name="RWT Button", direction="input",
        input_action=GPIOInputAction.RUN_RWT.value, input_bounce_ms=75.0,
    )
    watcher = GPIOInputWatcher([config], logger=None)
    watcher.start()

    assert watcher.active_pin_count == 1
    button = _FakeButton.instances[0]
    assert button.pin == 17
    assert button.bounce_time == pytest.approx(0.075)
    assert button.when_pressed is not None

    button.when_pressed()  # simulate a physical press

    pin, action = watcher._queue.get(timeout=1.0)
    assert pin == 17
    assert action == GPIOInputAction.RUN_RWT.value

    watcher.stop()
    assert button.closed is True


def test_dump_broadcast_uses_hold_not_press(patched_gpiozero):
    """DUMP_BROADCAST must arm via when_held with a real hold_time, never
    when_pressed -- a momentary bump or contact bounce must not be able to
    abort a live broadcast."""
    config = GPIOPinConfig(
        pin=22, name="Dump Button", direction="input",
        input_action=GPIOInputAction.DUMP_BROADCAST.value,
        input_hold_confirm_seconds=4.5,
    )
    watcher = GPIOInputWatcher([config], logger=None)
    watcher.start()

    button = _FakeButton.instances[0]
    assert button.when_pressed is None
    assert button.when_held is not None
    assert button.hold_time == 4.5


def test_none_action_pin_is_not_watched(patched_gpiozero):
    config = GPIOPinConfig(pin=23, name="Unused Input", direction="input", input_action=None)
    watcher = GPIOInputWatcher([config], logger=None)
    watcher.start()

    assert watcher.active_pin_count == 0
    assert _FakeButton.instances == []


def test_not_yet_implemented_action_is_skipped(patched_gpiozero, monkeypatch):
    """Every real GPIOInputAction is implemented as of this test, so there's
    no naturally-unimplemented action to exercise this with -- validate the
    GPIO_INPUT_ACTION_IMPLEMENTED filter mechanism itself instead, by
    temporarily excluding one, proving the watcher always respects whatever
    that set contains rather than hardcoding assumptions about which
    actions exist."""
    monkeypatch.setattr(
        input_watcher_module,
        "GPIO_INPUT_ACTION_IMPLEMENTED",
        frozenset({GPIOInputAction.NONE, GPIOInputAction.RUN_RWT}),
    )
    config = GPIOPinConfig(
        pin=24, name="Forward Button", direction="input",
        input_action=GPIOInputAction.FORWARD_LAST_ALERT.value,
    )
    watcher = GPIOInputWatcher([config], logger=None)
    watcher.start()

    assert watcher.active_pin_count == 0


# ---------------------------------------------------------------------------
# 2. Dispatch loop -> publish round trip
# ---------------------------------------------------------------------------


def test_dispatch_loop_publishes_queued_event(patched_gpiozero, monkeypatch):
    published = []

    def fake_publish(pin, action, timestamp=None):
        published.append((pin, action))
        return 1

    import app_core.gpio_commands as gpio_commands
    monkeypatch.setattr(gpio_commands, "publish_gpio_input_event", fake_publish)

    config = GPIOPinConfig(
        pin=17, name="RWT Button", direction="input",
        input_action=GPIOInputAction.RUN_RWT.value,
    )
    watcher = GPIOInputWatcher([config], logger=None)
    watcher.start()

    button = _FakeButton.instances[0]
    button.when_pressed()

    for _ in range(50):
        if published:
            break
        time.sleep(0.05)

    assert published == [(17, "run_rwt")]
    watcher.stop()


def test_publish_gpio_input_event_shape(monkeypatch):
    from app_core.gpio_commands import GPIO_INPUT_EVENT_CHANNEL, publish_gpio_input_event

    captured = {}

    class _FakeRedis:
        def publish(self, channel, payload):
            captured["channel"] = channel
            captured["payload"] = payload
            return 1

    import app_core.redis_client as redis_client_module
    monkeypatch.setattr(redis_client_module, "get_redis_client", lambda: _FakeRedis())

    receivers = publish_gpio_input_event(17, "run_rwt")

    assert receivers == 1
    assert captured["channel"] == GPIO_INPUT_EVENT_CHANNEL
    import json
    payload = json.loads(captured["payload"])
    assert payload["pin"] == 17
    assert payload["action"] == "run_rwt"
    assert "ts" in payload


# ---------------------------------------------------------------------------
# 3. Web-listener dispatch
# ---------------------------------------------------------------------------


def test_run_rwt_event_triggers_broadcast(monkeypatch):
    from app_core import gpio_input_listener

    calls = []

    class _FakeConfig:
        pass

    class _FakeQuery:
        def first(self):
            return _FakeConfig()

    import app_core.models as app_models
    monkeypatch.setattr(app_models, "RWTScheduleConfig", type("Q", (), {"query": _FakeQuery()}))
    monkeypatch.setattr(
        "app_utils.eas.get_broadcast_state", lambda: {"active": False}
    )
    monkeypatch.setattr(
        "app_core.rwt_scheduler.trigger_rwt_broadcast",
        lambda config, logger_instance=None: calls.append(config),
    )

    gpio_input_listener._dispatch_input_action({"pin": 17, "action": "run_rwt"})

    assert len(calls) == 1


def test_run_rwt_event_skipped_while_broadcast_active(monkeypatch):
    from app_core import gpio_input_listener

    calls = []

    class _FakeConfig:
        pass

    class _FakeQuery:
        def first(self):
            return _FakeConfig()

    import app_core.models as app_models
    monkeypatch.setattr(app_models, "RWTScheduleConfig", type("Q", (), {"query": _FakeQuery()}))
    monkeypatch.setattr(
        "app_utils.eas.get_broadcast_state", lambda: {"active": True}
    )
    monkeypatch.setattr(
        "app_core.rwt_scheduler.trigger_rwt_broadcast",
        lambda config, logger_instance=None: calls.append(config),
    )

    gpio_input_listener._dispatch_input_action({"pin": 17, "action": "run_rwt"})

    assert calls == []


def test_unknown_action_is_ignored_not_raised():
    from app_core import gpio_input_listener

    # Must not raise -- dispatch runs inside a listener loop that must stay alive.
    gpio_input_listener._dispatch_input_action({"pin": 17, "action": "not_a_real_action"})


# ---------------------------------------------------------------------------
# 4. Config loader: direction / input_action parsing
# ---------------------------------------------------------------------------


def test_config_loader_parses_input_direction_and_action(monkeypatch):
    import app_utils.gpio.config_loaders as config_loaders

    monkeypatch.setattr(config_loaders, "_GPIO_SETTINGS_AVAILABLE", True)
    monkeypatch.setattr(
        config_loaders, "get_gpio_settings",
        lambda: {
            "pin_map": {
                "17": {"name": "Relay", "active_high": True},
                "22": {
                    "name": "RWT Button", "direction": "input",
                    "input_action": "run_rwt", "input_bounce_ms": 80,
                },
            }
        },
    )

    configs = config_loaders.load_gpio_pin_configs_from_db(logger=None, oled_enabled=False)
    by_pin = {c.pin: c for c in configs}

    # Back-compat: a pin with no direction key defaults to output.
    assert by_pin[17].direction == "output"
    assert by_pin[17].input_action is None

    assert by_pin[22].direction == "input"
    assert by_pin[22].input_action == "run_rwt"
    assert by_pin[22].input_bounce_ms == 80.0


def test_config_loader_rejects_unknown_input_action(monkeypatch):
    import app_utils.gpio.config_loaders as config_loaders

    monkeypatch.setattr(config_loaders, "_GPIO_SETTINGS_AVAILABLE", True)
    monkeypatch.setattr(
        config_loaders, "get_gpio_settings",
        lambda: {
            "pin_map": {
                "22": {"name": "Button", "direction": "input", "input_action": "not_a_real_action"},
            }
        },
    )

    configs = config_loaders.load_gpio_pin_configs_from_db(logger=None, oled_enabled=False)
    assert configs[0].input_action is None


# ---------------------------------------------------------------------------
# 5. Hardware-settings save validation
# ---------------------------------------------------------------------------


def test_validate_rejects_input_pin_with_behavior():
    from webapp.admin.hardware import validate_gpio_input_pin_config

    pin_map = {"17": {"direction": "input"}}
    behavior_matrix = {"17": ["transmitter_ptt"]}

    error = validate_gpio_input_pin_config(pin_map, behavior_matrix)
    assert "17" in error
    assert "behavior" in error.lower()


def test_validate_rejects_duplicate_input_action():
    from webapp.admin.hardware import validate_gpio_input_pin_config

    pin_map = {
        "17": {"direction": "input", "input_action": "run_rwt"},
        "22": {"direction": "input", "input_action": "run_rwt"},
    }

    error = validate_gpio_input_pin_config(pin_map, {})
    assert "run_rwt" in error
    assert "17" in error and "22" in error


def test_validate_allows_clean_configuration():
    from webapp.admin.hardware import validate_gpio_input_pin_config

    pin_map = {
        "17": {"direction": "output"},
        "22": {"direction": "input", "input_action": "run_rwt"},
        "23": {"direction": "input", "input_action": "none"},
    }
    behavior_matrix = {"17": ["transmitter_ptt"]}

    error = validate_gpio_input_pin_config(pin_map, behavior_matrix)
    assert error == ""
