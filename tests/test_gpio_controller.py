"""Tests for GPIO controller configuration behavior."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app_utils.gpio as gpio

from app_utils.gpio import (
    GPIOBehavior,
    GPIOBehaviorManager,
    GPIOController,
    GPIOPinConfig,
    GPIOState,
    load_gpio_behavior_matrix_from_env,
    load_gpio_pin_configs_from_env,
    serialize_gpio_behavior_matrix,
)


def test_add_pin_records_configuration_when_gpio_unavailable():
    """Configured pins should be visible even without GPIO hardware."""

    controller = GPIOController()
    controller.add_pin(GPIOPinConfig(pin=17, name="Test Pin"))

    states = controller.get_all_states()

    assert 17 in states
    assert states[17]["name"] == "Test Pin"
    assert states[17]["state"] == GPIOState.INACTIVE.value


def test_add_pin_uses_null_backend_when_hardware_unavailable(monkeypatch):
    """Null GPIO backend should be treated as a simulated but healthy pin."""

    controller = GPIOController()
    controller._gpiozero_available = False

    monkeypatch.setattr(
        gpio,
        "_create_gpio_backend",
        lambda exclude=None: gpio._NullGPIOBackend(),
    )

    controller.add_pin(GPIOPinConfig(pin=18, name="Simulated Pin"))

    assert controller.get_state(18) == GPIOState.INACTIVE


def test_load_gpio_pin_configs_from_env(monkeypatch):
    """Environment parsing should produce structured GPIO configurations."""

    monkeypatch.setenv("EAS_GPIO_PIN", "12")
    monkeypatch.setenv("EAS_GPIO_ACTIVE_STATE", "LOW")
    monkeypatch.setenv("EAS_GPIO_HOLD_SECONDS", "2.5")
    monkeypatch.setenv("EAS_GPIO_WATCHDOG_SECONDS", "90")
    monkeypatch.setenv("GPIO_ADDITIONAL_PINS", "22:Aux Relay:HIGH:1.5:45\n24")
    monkeypatch.setenv("GPIO_PIN_25", "LOW:3:180:Backup Relay")

    configs = load_gpio_pin_configs_from_env()

    assert {cfg.pin for cfg in configs} == {12, 22, 24, 25}

    primary = next(cfg for cfg in configs if cfg.pin == 12)
    assert primary.name == "EAS Transmitter PTT"
    assert primary.active_high is False
    assert primary.hold_seconds == 2.5
    assert primary.watchdog_seconds == 90

    aux = next(cfg for cfg in configs if cfg.pin == 22)
    assert aux.name == "Aux Relay"
    assert aux.active_high is True
    assert aux.watchdog_seconds == 45

    fallback = next(cfg for cfg in configs if cfg.pin == 24)
    assert fallback.name == "GPIO Pin 24"
    assert fallback.active_high is True

    override = next(cfg for cfg in configs if cfg.pin == 25)
    assert override.name == "Backup Relay"
    assert override.active_high is False


def test_load_gpio_behavior_matrix_from_env(monkeypatch):
    """GPIO_PIN_BEHAVIOR_MATRIX should deserialize to enums per pin."""

    matrix_json = '{"18": ["duration_of_alert", "incoming_alert"], "22": "flash", "bad": ["unknown"]}'
    monkeypatch.setenv("GPIO_PIN_BEHAVIOR_MATRIX", matrix_json)

    matrix = load_gpio_behavior_matrix_from_env()

    assert 18 in matrix
    assert matrix[18] == {GPIOBehavior.DURATION_OF_ALERT, GPIOBehavior.INCOMING_ALERT}
    assert 22 in matrix
    assert matrix[22] == {GPIOBehavior.FLASH}
    assert "bad" not in matrix


def test_serialize_gpio_behavior_matrix_round_trip():
    """Behavior matrix serialization should produce stable JSON."""

    matrix = {
        18: {GPIOBehavior.DURATION_OF_ALERT, GPIOBehavior.PLAYOUT},
        22: {GPIOBehavior.FLASH},
    }

    json_value = serialize_gpio_behavior_matrix(matrix)
    assert json_value

    restored = json.loads(json_value)
    assert restored == {
        "18": ["duration_of_alert", "playout"],
        "22": ["flash"],
    }


class _FakeController:
    def __init__(self):
        self.activations = []
        self.deactivations = []

    def activate(self, pin, activation_type=None, alert_id=None, reason=None):
        self.activations.append((pin, activation_type, alert_id, reason))
        return True

    def deactivate(self, pin, force=False):
        self.deactivations.append((pin, force))
        return True


def test_behavior_manager_hold_lifecycle(monkeypatch):
    """Behavior manager should activate and release pins for alert duration."""

    monkeypatch.setenv("GPIO_PIN_BEHAVIOR_MATRIX", "")
    controller = _FakeController()
    configs = [GPIOPinConfig(pin=18, name="Alert Relay")]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={18: {GPIOBehavior.DURATION_OF_ALERT}},
    )

    handled = manager.start_alert(alert_id="test", event_code="TOR")
    assert handled is True
    assert controller.activations

    manager.end_alert(alert_id="test", event_code="TOR")
    assert controller.deactivations


def test_behavior_manager_pulse_only(monkeypatch):
    """Pulse-only behaviors should prevent fallback activation."""

    controller = _FakeController()
    configs = [GPIOPinConfig(pin=18, name="Beacon")] 
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={18: {GPIOBehavior.FIVE_SECONDS}},
    )

    calls = []

    def fake_pulse(**kwargs):  # pragma: no cover - simple test hook
        controller.activate(kwargs["pin"])
        controller.deactivate(kwargs["pin"], force=True)
        calls.append(kwargs["pin"])

    monkeypatch.setattr(manager, "_pulse_pin", fake_pulse)

    handled = manager.start_alert(alert_id="pulse", event_code="RWT")
    assert handled is True
    assert calls == [18]
