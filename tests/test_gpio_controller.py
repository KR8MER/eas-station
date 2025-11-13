"""Tests for GPIO controller configuration behavior."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_utils.gpio import (
    GPIOController,
    GPIOPinConfig,
    GPIOState,
    load_gpio_pin_configs_from_env,
)


def test_add_pin_records_configuration_when_gpio_unavailable():
    """Configured pins should be visible even without GPIO hardware."""

    controller = GPIOController()
    controller.add_pin(GPIOPinConfig(pin=17, name="Test Pin"))

    states = controller.get_all_states()

    assert 17 in states
    assert states[17]["name"] == "Test Pin"
    assert states[17]["state"] == GPIOState.ERROR.value


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
