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

"""Tests for GPIO controller configuration behavior."""

import json
import logging
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
    load_gpio_behavior_matrix_from_db,
    load_gpio_pin_configs_from_db,
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


def test_load_gpio_pin_configs_from_database(monkeypatch):
    """Database pin map should produce structured GPIO configurations."""

    # Mock the database settings to return a pin map
    pin_map = {
        "12": {"name": "EAS Transmitter PTT", "active_high": False, "hold_seconds": 2.5, "watchdog_seconds": 90},
        "22": {"name": "Aux Relay", "active_high": True, "hold_seconds": 1.5, "watchdog_seconds": 45},
        "24": {},
        "25": {"name": "Backup Relay", "active_high": False, "hold_seconds": 3, "watchdog_seconds": 180},
    }

    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)
    monkeypatch.setattr(gpio, "get_gpio_settings", lambda: {"pin_map": pin_map, "behavior_matrix": {}})

    configs = load_gpio_pin_configs_from_db()

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


def test_reserved_oled_pins_rejected(monkeypatch, caplog):
    """Pins reserved for the OLED module should not be configurable when OLED is enabled."""

    # Mock database returning OLED-reserved pins (BCM 2, 4, 14)
    pin_map = {
        "4": {"name": "Button Override"},
        "2": {"name": "Aux", "active_high": True, "hold_seconds": 1, "watchdog_seconds": 60},
        "14": {"name": "Serial", "active_high": True, "hold_seconds": 1, "watchdog_seconds": 60},
    }

    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)
    monkeypatch.setattr(gpio, "get_gpio_settings", lambda: {"pin_map": pin_map, "behavior_matrix": {}})

    test_logger = logging.getLogger("gpio-test")
    with caplog.at_level(logging.ERROR, logger="gpio-test"):
        configs = load_gpio_pin_configs_from_db(logger=test_logger, oled_enabled=True)

    assert configs == []
    assert any("reserved" in record.message for record in caplog.records)


def test_load_gpio_behavior_matrix_from_database(monkeypatch):
    """Database behavior matrix should deserialize to enums per pin."""

    behavior_matrix = {
        "18": ["duration_of_alert", "incoming_alert"],
        "22": "flash",
        "bad": ["unknown"],
    }

    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)
    monkeypatch.setattr(gpio, "get_gpio_settings", lambda: {"pin_map": {}, "behavior_matrix": behavior_matrix})

    matrix = load_gpio_behavior_matrix_from_db()

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




def test_gpio_state_includes_output_verification(monkeypatch):
    """GPIO status should expose output verification details for UI/diagnostics."""

    controller = GPIOController()
    controller._gpiozero_available = False
    monkeypatch.setattr(
        gpio,
        "_create_gpio_backend",
        lambda exclude=None: gpio._NullGPIOBackend(),
    )

    controller.add_pin(GPIOPinConfig(pin=17, name="Verified Pin"))

    assert controller.activate(17) is True
    states = controller.get_all_states()
    verification = states[17].get("verification")

    assert verification is not None
    assert verification["verified"] is True
    assert verification["observed"] == "active"


def test_behavior_manager_flash_alternates_partner_pin():
    """Flash behavior should alternate phase across partner pins when configured."""

    controller = _FakeController()
    configs = [
        GPIOPinConfig(pin=18, name="Red", flash_enabled=True, flash_interval_ms=50, flash_partner_pin=23),
        GPIOPinConfig(pin=23, name="Amber", flash_enabled=True, flash_interval_ms=50, flash_partner_pin=18),
    ]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={18: {GPIOBehavior.FLASH}, 23: {GPIOBehavior.FLASH}},
    )

    handled = manager.start_alert(alert_id="flash", event_code="RWT")
    assert handled is True

    import time
    time.sleep(0.18)
    manager.end_alert(alert_id="flash", event_code="RWT")

    activated_pins = [call[0] for call in controller.activations]
    assert 18 in activated_pins
    assert 23 in activated_pins

def test_behavior_manager_hold_lifecycle(monkeypatch):
    """Behavior manager should activate and release pins for alert duration."""

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
