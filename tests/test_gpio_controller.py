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
    NeopixelConfig,
    NeopixelController,
    TowerLightConfig,
    TowerLightController,
    _NullNeopixelStrip,
    _make_neo_color,
    _TOWER_CMD_GRN_ON,
    _TOWER_CMD_GRN_OFF,
    _TOWER_CMD_RED_ON,
    _TOWER_CMD_RED_OFF,
    _TOWER_CMD_RED_BLINK,
    _TOWER_CMD_YEL_OFF,
    _TOWER_CMD_YEL_BLINK,
    _TOWER_CMD_BUZ_OFF,
    _TOWER_CMD_BUZ_ON,
    load_gpio_behavior_matrix_from_db,
    load_gpio_pin_configs_from_db,
    load_neopixel_config_from_db,
    load_tower_light_config_from_db,
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


def _null_controller(monkeypatch):
    """Build a controller backed by the simulated null GPIO backend."""
    controller = GPIOController()
    controller._gpiozero_available = False
    monkeypatch.setattr(
        gpio,
        "_create_gpio_backend",
        lambda exclude=None: gpio._NullGPIOBackend(),
    )
    return controller


def test_activate_flash_true_forces_flash_without_flash_enabled(monkeypatch):
    """activate(flash=True) starts the flash engine even when flash_enabled is unset."""

    controller = _null_controller(monkeypatch)
    controller.add_pin(GPIOPinConfig(pin=18, name="Beacon", flash_enabled=False))

    try:
        assert controller.activate(18, flash=True) is True
        assert 18 in controller._flash_threads  # controller is the flash engine
    finally:
        controller.deactivate(18, force=True)
        assert 18 not in controller._flash_threads


def test_activate_flash_false_suppresses_configured_flash(monkeypatch):
    """activate(flash=False) keeps a flash_enabled pin solid (no flash thread)."""

    controller = _null_controller(monkeypatch)
    controller.add_pin(GPIOPinConfig(pin=18, name="Relay", flash_enabled=True))

    try:
        assert controller.activate(18, flash=False) is True
        assert 18 not in controller._flash_threads
    finally:
        controller.deactivate(18, force=True)


def test_cleanup_invokes_behavior_manager_shutdown(monkeypatch):
    """Controller.cleanup() should shut the attached behavior manager down."""

    controller = _null_controller(monkeypatch)
    controller.add_pin(GPIOPinConfig(pin=26, name="TX Key"))

    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=[GPIOPinConfig(pin=26, name="TX Key")],
        behavior_matrix={26: {GPIOBehavior.TRANSMITTER_PTT}},
    )
    controller.behavior_manager = manager

    calls = []
    monkeypatch.setattr(manager, "shutdown", lambda: calls.append(True))

    controller.cleanup()
    assert calls == [True]


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

    # Mock database returning OLED-reserved pins.  The Argon OLED module reserves
    # the I2C lines BCM 2 (SDA) and BCM 3 (SCL) plus BCM 14 (TXD); none of these
    # may be used for relays while OLED is enabled.
    pin_map = {
        "3": {"name": "SCL", "active_high": True, "hold_seconds": 1, "watchdog_seconds": 60},
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
        # Records the ``flash`` override the behavior manager passed for each
        # activation so tests can assert flash vs. solid-hold intent.
        self.flash_calls = []

    def activate(self, pin, activation_type=None, alert_id=None, reason=None, flash=None):
        self.activations.append((pin, activation_type, alert_id, reason))
        self.flash_calls.append((pin, flash))
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


def test_behavior_manager_flash_delegates_to_controller_engine():
    """FLASH should delegate to the controller flash engine (flash=True), once per pair.

    After consolidating the two flash code paths, the controller is the single
    flash authority: for a partner pair the manager starts exactly one pin with
    ``flash=True`` and the controller drives the partner in opposite phase.
    """

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

    # Exactly one pin of the partner pair is activated, and with flash forced on.
    flash_activations = [c for c in controller.flash_calls if c[1] is True]
    assert len(flash_activations) == 1
    assert flash_activations[0][0] in (18, 23)

    manager.end_alert(alert_id="flash", event_code="RWT")
    # The flashed pin is released (controller stops its flash thread on deactivate).
    assert controller.deactivations
    assert flash_activations[0][0] in [d[0] for d in controller.deactivations]


def test_behavior_manager_holds_are_solid_not_flashing():
    """Held relays (PTT, duration) must activate with flash=False even if flash_enabled."""

    controller = _FakeController()
    # Pin has flash_enabled in its config, but is assigned a *hold* behavior.
    configs = [GPIOPinConfig(pin=17, name="TX", flash_enabled=True)]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={17: {GPIOBehavior.TRANSMITTER_PTT}},
    )

    assert manager.start_alert(alert_id="a", event_code="TOR") is True
    # The hold must be solid: flash explicitly suppressed for the held pin.
    assert (17, False) in controller.flash_calls
    assert all(flash is not True for pin, flash in controller.flash_calls if pin == 17)


def test_behavior_manager_flash_precedence_over_hold():
    """A pin with both FLASH and a hold behavior flashes (FLASH wins, no conflict)."""

    controller = _FakeController()
    configs = [GPIOPinConfig(pin=19, name="Beacon")]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={19: {GPIOBehavior.FLASH, GPIOBehavior.DURATION_OF_ALERT}},
    )

    assert manager.start_alert(alert_id="a", event_code="TOR") is True
    # The pin is driven exactly once, as a flash — never also as a solid hold.
    calls_for_pin = [flash for pin, flash in controller.flash_calls if pin == 19]
    assert calls_for_pin == [True]


def test_behavior_manager_transmitter_and_audio_mute_hold_for_alert():
    """TRANSMITTER_PTT and AUDIO_MUTE hold for the alert and release on end_alert."""

    controller = _FakeController()
    configs = [
        GPIOPinConfig(pin=26, name="TX Key"),
        GPIOPinConfig(pin=20, name="Program Mute"),
    ]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={
            26: {GPIOBehavior.TRANSMITTER_PTT},
            20: {GPIOBehavior.AUDIO_MUTE},
        },
    )

    assert manager.start_alert(alert_id="a", event_code="TOR") is True
    activated = {c[0] for c in controller.activations}
    assert {26, 20} <= activated

    manager.end_alert(alert_id="a", event_code="TOR")
    released = {d[0] for d in controller.deactivations}
    assert {26, 20} <= released


def test_validate_configuration_warns_without_transmit_behavior():
    """validate_configuration flags a matrix that never keys the transmitter."""

    controller = _FakeController()
    configs = [GPIOPinConfig(pin=22, name="Beacon")]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={22: {GPIOBehavior.FLASH}},
    )

    warnings = manager.validate_configuration()
    assert any("transmit-capable" in w for w in warnings)

    # Assigning a transmit-capable behavior clears the warning.
    manager.update_behavior_matrix({22: {GPIOBehavior.TRANSMITTER_PTT}})
    assert not any("transmit-capable" in w for w in manager.validate_configuration())


def test_validate_configuration_warns_on_unconfigured_pin_and_partner():
    """validate_configuration flags behaviors on non-active pins and lone flash partners."""

    controller = _FakeController()
    configs = [GPIOPinConfig(pin=17, name="Red", flash_partner_pin=27)]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={
            17: {GPIOBehavior.FLASH, GPIOBehavior.TRANSMITTER_PTT},
            99: {GPIOBehavior.PLAYOUT},  # pin 99 not in pin_configs
        },
    )

    warnings = manager.validate_configuration()
    assert any("pin 99" in w for w in warnings)
    # Pin 17 flashes with partner 27, but 27 has no FLASH behavior assigned.
    assert any("partner pin 27" in w for w in warnings)


def test_behavior_manager_shutdown_releases_holds_and_flash():
    """shutdown() releases every held/flashing pin so nothing waits on the watchdog."""

    controller = _FakeController()
    configs = [
        GPIOPinConfig(pin=26, name="TX Key"),
        GPIOPinConfig(pin=13, name="Beacon"),
    ]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={
            26: {GPIOBehavior.TRANSMITTER_PTT},
            13: {GPIOBehavior.FLASH},
        },
    )

    assert manager.start_alert(alert_id="a", event_code="TOR") is True
    manager.shutdown()

    released = {d[0] for d in controller.deactivations}
    assert {26, 13} <= released

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


def test_end_alert_force_releases_held_pins():
    """end_alert() must force-release holds so the min-hold can't keep them on.

    Regression: a held air-chain pin with a large ``hold_seconds`` (anti-chatter
    value) used to release without ``force``, so deactivate() slept out the
    remaining min-hold with the relay still asserted — holding the transmitter
    keyed and the on-air overlay up for minutes after end-of-message.
    """

    controller = _FakeController()
    configs = [GPIOPinConfig(pin=26, name="TX Key", hold_seconds=300.0)]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={26: {GPIOBehavior.TRANSMITTER_PTT}},
    )

    assert manager.start_alert(alert_id="a", event_code="RWT") is True
    manager.end_alert(alert_id="a", event_code="RWT")

    assert (26, True) in controller.deactivations, (
        "end_alert must force-release held pins (force=True)"
    )


def test_end_alert_release_ignores_long_min_hold(monkeypatch):
    """A real controller must drop the air chain at end-of-message, not after hold_seconds."""

    import time

    controller = _null_controller(monkeypatch)
    # A 5-minute min-hold mimics an operator who set hold_seconds too high.
    controller.add_pin(GPIOPinConfig(pin=26, name="TX Key", hold_seconds=300.0))
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=[GPIOPinConfig(pin=26, name="TX Key", hold_seconds=300.0)],
        behavior_matrix={26: {GPIOBehavior.TRANSMITTER_PTT}},
    )

    assert manager.start_alert(alert_id="a", event_code="RWT") is True
    assert controller.get_state(26) == GPIOState.ACTIVE

    start = time.monotonic()
    manager.end_alert(alert_id="a", event_code="RWT")
    elapsed = time.monotonic() - start

    assert controller.get_state(26) == GPIOState.INACTIVE
    assert elapsed < 5.0, (
        f"end_alert blocked {elapsed:.1f}s waiting out the min-hold; "
        "the air chain should release immediately at end-of-message"
    )


def test_behavior_manager_pulse_only_does_not_claim_the_broadcast(monkeypatch):
    """A pulse-only matrix pulses, but must NOT suppress fallback activation.

    ``start_alert`` reporting True is what tells the GPIO subprocess "the matrix
    has taken this broadcast" and skips keying every configured pin.  A
    five-second beacon pulse cannot carry a broadcast that runs for minutes, so
    counting it as handled left the transmitter unkeyed for the whole alert —
    the failure operators saw on automated RWTs when their relay was assigned
    Forwarding Alert (held only for forwarded alerts) alongside a beacon pulse.
    """

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
    assert handled is False, "a beacon pulse must not stand in for keying the air chain"
    assert calls == [18], "the pulse itself should still fire"


def test_forwarding_only_matrix_falls_back_on_an_rwt(monkeypatch):
    """The automated-RWT case: a Forwarding Alert relay holds nothing for an RWT.

    An RWT is originated locally, not forwarded, so FORWARDING_ALERT pins are
    correctly left alone — which means nothing holds the air chain and the
    subprocess must fall back to keying every configured pin.
    """

    controller = _FakeController()
    configs = [
        GPIOPinConfig(pin=17, name="Transmit relay"),
        GPIOPinConfig(pin=18, name="Beacon"),
    ]
    manager = GPIOBehaviorManager(
        controller=controller,
        pin_configs=configs,
        behavior_matrix={
            17: {GPIOBehavior.FORWARDING_ALERT},
            18: {GPIOBehavior.FIVE_SECONDS},
        },
    )
    monkeypatch.setattr(manager, "_pulse_pin", lambda **kwargs: None)

    # Automated RWT (forwarded=False): nothing is held -> fallback required.
    assert manager.start_alert(alert_id="RWT-AUTO-1", event_code="RWT") is False

    # A forwarded alert on the same matrix does hold the relay.
    assert manager.start_alert(alert_id="urn:cap:1", event_code="TOR", forwarded=True) is True


# ---------------------------------------------------------------------------
# NeoPixel tests
# ---------------------------------------------------------------------------


def test_null_neopixel_strip_tracks_pixel_values():
    """_NullNeopixelStrip should store and return pixel colour values."""
    strip = _NullNeopixelStrip(4)
    assert strip.numPixels() == 4

    strip.setPixelColor(0, 0xFF0000)
    strip.setPixelColor(3, 0x00FF00)
    strip.show()  # no-op; must not raise

    assert strip.pixels[0] == 0xFF0000
    assert strip.pixels[1] == 0
    assert strip.pixels[3] == 0x00FF00


def test_make_neo_color_without_rpi_ws281x(monkeypatch):
    """_make_neo_color should pack RGB correctly even without the real library."""
    monkeypatch.setattr(gpio, "NeopixelColor", None)
    packed = _make_neo_color(255, 128, 0)
    assert packed == (255 << 16) | (128 << 8) | 0


def test_neopixel_controller_starts_in_null_mode(monkeypatch):
    """NeopixelController should start cleanly when rpi_ws281x is unavailable."""
    monkeypatch.setattr(gpio, "_NEOPIXEL_LIB_AVAILABLE", False)

    config = NeopixelConfig(gpio_pin=18, num_pixels=3, brightness=64)
    ctrl = NeopixelController(config)
    available = ctrl.start()

    assert available is False
    assert ctrl.is_available is False


def test_neopixel_controller_set_color(monkeypatch):
    """set_color should push the colour to every pixel."""
    monkeypatch.setattr(gpio, "_NEOPIXEL_LIB_AVAILABLE", False)

    config = NeopixelConfig(gpio_pin=18, num_pixels=4, brightness=128)
    ctrl = NeopixelController(config)
    ctrl.start()

    ctrl.set_color(10, 20, 30)
    expected = _make_neo_color(10, 20, 30)
    assert all(p == expected for p in ctrl._strip.pixels)


def test_neopixel_controller_standby_and_off(monkeypatch):
    """set_standby and off should use the configured standby colour and black."""
    monkeypatch.setattr(gpio, "_NEOPIXEL_LIB_AVAILABLE", False)

    config = NeopixelConfig(
        gpio_pin=18, num_pixels=2, brightness=128, standby_color=(0, 5, 0)
    )
    ctrl = NeopixelController(config)
    ctrl.start()

    ctrl.set_standby()
    standby_val = _make_neo_color(0, 5, 0)
    assert all(p == standby_val for p in ctrl._strip.pixels)

    ctrl.off()
    assert all(p == 0 for p in ctrl._strip.pixels)


def test_neopixel_controller_start_and_end_alert(monkeypatch):
    """start_alert should show the alert colour; end_alert restores standby."""
    monkeypatch.setattr(gpio, "_NEOPIXEL_LIB_AVAILABLE", False)

    config = NeopixelConfig(
        gpio_pin=18,
        num_pixels=2,
        brightness=128,
        standby_color=(0, 5, 0),
        alert_color=(200, 0, 0),
        flash_on_alert=False,
    )
    ctrl = NeopixelController(config)
    ctrl.start()

    ctrl.start_alert()
    alert_val = _make_neo_color(200, 0, 0)
    assert all(p == alert_val for p in ctrl._strip.pixels)

    ctrl.end_alert()
    standby_val = _make_neo_color(0, 5, 0)
    assert all(p == standby_val for p in ctrl._strip.pixels)


def test_neopixel_controller_flash_and_stop(monkeypatch):
    """Flash pattern should toggle the strip; stop_flash cleans up the thread."""
    import time

    monkeypatch.setattr(gpio, "_NEOPIXEL_LIB_AVAILABLE", False)

    config = NeopixelConfig(
        gpio_pin=18,
        num_pixels=1,
        brightness=128,
        standby_color=(0, 5, 0),
        alert_color=(200, 0, 0),
        flash_on_alert=True,
        flash_interval_ms=50,
    )
    ctrl = NeopixelController(config)
    ctrl.start()

    ctrl.start_flash(200, 0, 0)
    assert ctrl._flash_thread is not None and ctrl._flash_thread.is_alive()

    # Let at least two toggles happen
    time.sleep(0.15)

    ctrl.stop_flash()
    assert ctrl._flash_thread is None


def test_neopixel_controller_cleanup(monkeypatch):
    """cleanup should stop flash and turn the strip off."""
    monkeypatch.setattr(gpio, "_NEOPIXEL_LIB_AVAILABLE", False)

    config = NeopixelConfig(gpio_pin=18, num_pixels=2, brightness=128)
    ctrl = NeopixelController(config)
    ctrl.start()

    ctrl.start_flash(255, 0, 0)
    ctrl.cleanup()

    # Strip reference should be cleared after cleanup
    assert ctrl._strip is None
    assert ctrl._flash_thread is None


def test_neopixel_controller_get_status(monkeypatch):
    """get_status should return a dict with all expected keys."""
    monkeypatch.setattr(gpio, "_NEOPIXEL_LIB_AVAILABLE", False)

    config = NeopixelConfig(
        gpio_pin=18,
        num_pixels=5,
        brightness=100,
        led_order="RGB",
        flash_interval_ms=250,
    )
    ctrl = NeopixelController(config)
    ctrl.start()

    status = ctrl.get_status()
    assert status["gpio_pin"] == 18
    assert status["num_pixels"] == 5
    assert status["brightness"] == 100
    assert status["led_order"] == "RGB"
    assert status["flash_interval_ms"] == 250
    assert status["available"] is False
    assert status["flashing"] is False


def test_load_neopixel_config_disabled(monkeypatch):
    """load_neopixel_config_from_db should return None when disabled."""
    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)

    fake_settings = {
        "enabled": False,
        "gpio_pin": 18,
        "num_pixels": 1,
        "brightness": 128,
        "led_order": "GRB",
        "standby_color": {"r": 0, "g": 10, "b": 0},
        "alert_color": {"r": 255, "g": 0, "b": 0},
        "flash_on_alert": True,
        "flash_interval_ms": 500,
    }

    # Patch the hardware_settings import inside gpio.py
    import types
    fake_module = types.ModuleType("app_core.hardware_settings")
    fake_module.get_neopixel_settings = lambda: fake_settings
    monkeypatch.setitem(
        __import__("sys").modules, "app_core.hardware_settings", fake_module
    )

    result = load_neopixel_config_from_db()
    assert result is None


def test_load_neopixel_config_enabled(monkeypatch):
    """load_neopixel_config_from_db should return NeopixelConfig when enabled."""
    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)

    fake_settings = {
        "enabled": True,
        "gpio_pin": 18,
        "num_pixels": 8,
        "brightness": 200,
        "led_order": "GRB",
        "standby_color": {"r": 0, "g": 20, "b": 0},
        "alert_color": {"r": 255, "g": 50, "b": 0},
        "flash_on_alert": True,
        "flash_interval_ms": 300,
    }

    import types
    fake_module = types.ModuleType("app_core.hardware_settings")
    fake_module.get_neopixel_settings = lambda: fake_settings
    monkeypatch.setitem(
        __import__("sys").modules, "app_core.hardware_settings", fake_module
    )

    result = load_neopixel_config_from_db()
    assert result is not None
    assert result.gpio_pin == 18
    assert result.num_pixels == 8
    assert result.brightness == 200
    assert result.led_order == "GRB"
    assert result.standby_color == (0, 20, 0)
    assert result.alert_color == (255, 50, 0)
    assert result.flash_on_alert is True
    assert result.flash_interval_ms == 300


# ---------------------------------------------------------------------------
# USB Tower Light tests (Adafruit #5125 / CH34x serial)
# ---------------------------------------------------------------------------


class _FakeSerial:
    """Minimal pyserial stub that records written bytes."""

    def __init__(self):
        self.written: list[int] = []

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    def close(self) -> None:
        pass


def _make_tower_ctrl(config: TowerLightConfig | None = None) -> tuple:
    """Return a TowerLightController with a fake serial port injected."""
    if config is None:
        config = TowerLightConfig(serial_port="/dev/null")
    ctrl = TowerLightController(config)
    fake_ser = _FakeSerial()
    ctrl._serial = fake_ser
    ctrl._available = True
    return ctrl, fake_ser


def test_tower_light_standby_sends_correct_commands():
    """set_standby should turn green on and everything else off."""
    ctrl, ser = _make_tower_ctrl()
    ser.written.clear()

    ctrl.set_standby()

    assert _TOWER_CMD_RED_OFF in ser.written
    assert _TOWER_CMD_YEL_OFF in ser.written
    assert _TOWER_CMD_BUZ_OFF in ser.written
    assert _TOWER_CMD_GRN_ON in ser.written


def test_tower_light_all_off_sends_correct_commands():
    """all_off should turn all four segments off."""
    ctrl, ser = _make_tower_ctrl()
    ser.written.clear()

    ctrl.all_off()

    from app_utils.gpio import _TOWER_CMD_RED_OFF, _TOWER_CMD_YEL_OFF, _TOWER_CMD_GRN_OFF, _TOWER_CMD_BUZ_OFF
    for cmd in (_TOWER_CMD_RED_OFF, _TOWER_CMD_YEL_OFF, _TOWER_CMD_GRN_OFF, _TOWER_CMD_BUZ_OFF):
        assert cmd in ser.written


def test_tower_light_start_alert_solid():
    """start_alert with blink_on_alert=False should send red on, not blink."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(serial_port="/dev/null", blink_on_alert=False, alert_buzzer=False)
    )
    ser.written.clear()

    ctrl.start_alert()

    assert _TOWER_CMD_RED_ON in ser.written
    assert _TOWER_CMD_RED_BLINK not in ser.written
    assert _TOWER_CMD_BUZ_ON not in ser.written


def test_tower_light_start_alert_blink():
    """start_alert with blink_on_alert=True should use the blink command."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(serial_port="/dev/null", blink_on_alert=True, alert_buzzer=False)
    )
    ser.written.clear()

    ctrl.start_alert()

    assert _TOWER_CMD_RED_BLINK in ser.written
    assert _TOWER_CMD_RED_ON not in ser.written


def test_tower_light_start_alert_with_buzzer():
    """start_alert with alert_buzzer=True should also send the buzzer on command."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(serial_port="/dev/null", blink_on_alert=False, alert_buzzer=True)
    )
    ser.written.clear()

    ctrl.start_alert()

    assert _TOWER_CMD_BUZ_ON in ser.written


def test_tower_light_start_incoming_alert_blink():
    """start_incoming_alert should blink yellow when blink_on_alert=True."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(serial_port="/dev/null", blink_on_alert=True)
    )
    ser.written.clear()

    ctrl.start_incoming_alert()

    assert _TOWER_CMD_YEL_BLINK in ser.written
    assert _TOWER_CMD_GRN_OFF in ser.written
    assert _TOWER_CMD_RED_OFF in ser.written


def test_tower_light_start_incoming_alert_disabled_sends_nothing():
    """start_incoming_alert should send no commands when incoming_uses_yellow=False."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(serial_port="/dev/null", blink_on_alert=True, incoming_uses_yellow=False)
    )
    ser.written.clear()

    ctrl.start_incoming_alert()

    assert len(ser.written) == 0


def test_tower_light_end_alert_returns_to_standby():
    """end_alert should restore the standby (green on) state."""
    ctrl, ser = _make_tower_ctrl()
    ctrl.start_alert()
    ser.written.clear()

    ctrl.end_alert()

    assert _TOWER_CMD_GRN_ON in ser.written
    assert _TOWER_CMD_RED_OFF in ser.written


def test_tower_light_get_status():
    """get_status should return a dict with expected keys."""
    ctrl, _ = _make_tower_ctrl(
        TowerLightConfig(
            serial_port="/dev/ttyUSB1",
            baudrate=9600,
            alert_buzzer=True,
            blink_on_alert=False,
        )
    )

    status = ctrl.get_status()
    assert status["available"] is True
    assert status["serial_port"] == "/dev/ttyUSB1"
    assert status["baudrate"] == 9600
    assert status["alert_buzzer"] is True
    assert status["blink_on_alert"] is False


def test_tower_light_cleanup_closes_serial():
    """cleanup should close the serial port and clear state."""
    ctrl, ser = _make_tower_ctrl()
    ctrl.cleanup()

    assert ctrl._serial is None
    assert ctrl._available is False


def test_load_tower_light_config_disabled(monkeypatch):
    """load_tower_light_config_from_db should return None when disabled."""
    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)

    fake_settings = {
        "enabled": False,
        "serial_port": "/dev/ttyUSB0",
        "baudrate": 9600,
        "alert_buzzer": False,
        "incoming_uses_yellow": True,
        "blink_on_alert": True,
    }

    import types
    fake_module = types.ModuleType("app_core.hardware_settings")
    fake_module.get_tower_light_settings = lambda: fake_settings
    monkeypatch.setitem(
        __import__("sys").modules, "app_core.hardware_settings", fake_module
    )

    result = load_tower_light_config_from_db()
    assert result is None


def test_load_tower_light_config_enabled(monkeypatch):
    """load_tower_light_config_from_db should return TowerLightConfig when enabled."""
    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)

    fake_settings = {
        "enabled": True,
        "serial_port": "/dev/ttyUSB1",
        "baudrate": 9600,
        "alert_buzzer": True,
        "incoming_uses_yellow": True,
        "blink_on_alert": False,
    }

    import types
    fake_module = types.ModuleType("app_core.hardware_settings")
    fake_module.get_tower_light_settings = lambda: fake_settings
    monkeypatch.setitem(
        __import__("sys").modules, "app_core.hardware_settings", fake_module
    )

    result = load_tower_light_config_from_db()
    assert result is not None
    assert result.serial_port == "/dev/ttyUSB1"
    assert result.baudrate == 9600
    assert result.alert_buzzer is True
    assert result.blink_on_alert is False


# ---------------------------------------------------------------------------
# ANDONT 7-colour USB stack light protocol
# ---------------------------------------------------------------------------


def _andont_frame(color_code: int, buzzer_on: bool, flash: bool) -> list[int]:
    # Buzzer byte: 0x02 = on, 0x01 = off. The vendor table claims the
    # opposite, but this is what real hardware does.
    return [0xFF, color_code, 0x02 if buzzer_on else 0x01, 0x02 if flash else 0x01, 0xAA]


def test_andont_standby_sends_green_frame():
    """set_standby on the ANDONT protocol writes one FF..AA frame (green)."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(serial_port="/dev/null", protocol="andont")
    )
    ser.written.clear()

    ctrl.set_standby()

    assert ser.written == _andont_frame(0x02, buzzer_on=False, flash=False)


def test_andont_alert_blue_with_buzzer_and_flash():
    """Active alert renders the configured colour (blue) with buzzer + flash."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(
            serial_port="/dev/null",
            protocol="andont",
            alert_color="blue",
            alert_buzzer=True,
            blink_on_alert=True,
        )
    )
    ser.written.clear()

    ctrl.start_alert()

    assert ser.written == _andont_frame(0x03, buzzer_on=True, flash=True)


def test_andont_incoming_uses_configured_color():
    """Incoming state renders the configured colour without the buzzer."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(
            serial_port="/dev/null",
            protocol="andont",
            incoming_color="cyan",
            blink_on_alert=False,
        )
    )
    ser.written.clear()

    ctrl.start_incoming_alert()

    assert ser.written == _andont_frame(0x05, buzzer_on=False, flash=False)


def test_andont_all_off_sends_off_frame():
    """all_off on the ANDONT protocol writes the 'light off' frame."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(serial_port="/dev/null", protocol="andont")
    )
    ser.written.clear()

    ctrl.all_off()

    assert ser.written == _andont_frame(0x01, buzzer_on=False, flash=False)


def test_adafruit_clamps_unsupported_alert_color():
    """Blue is not a #5125 segment; the alert state must fall back to red."""
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(
            serial_port="/dev/null",
            protocol="adafruit",
            alert_color="blue",
            blink_on_alert=True,
            alert_buzzer=False,
        )
    )
    ser.written.clear()

    ctrl.start_alert()

    assert _TOWER_CMD_RED_BLINK in ser.written


def test_adafruit_custom_standby_segment():
    """A red/yellow/green standby choice is honoured on the Adafruit protocol."""
    from app_utils.gpio import _TOWER_CMD_YEL_ON, _TOWER_CMD_GRN_OFF

    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(serial_port="/dev/null", standby_color="yellow")
    )
    ser.written.clear()

    ctrl.set_standby()

    assert _TOWER_CMD_YEL_ON in ser.written
    assert _TOWER_CMD_GRN_OFF in ser.written
    assert _TOWER_CMD_RED_OFF in ser.written


def test_load_tower_light_config_andont_colors(monkeypatch):
    """Protocol and state colours load from settings with invalid values clamped."""
    monkeypatch.setattr(gpio, "_GPIO_SETTINGS_AVAILABLE", True)

    fake_settings = {
        "enabled": True,
        "serial_port": "/dev/ttyUSB0",
        "baudrate": 9600,
        "protocol": "andont",
        "alert_buzzer": False,
        "incoming_uses_yellow": True,
        "blink_on_alert": True,
        "standby_color": "green",
        "incoming_color": "yellow",
        "alert_color": "BLUE",          # case-insensitive
    }

    import types
    fake_module = types.ModuleType("app_core.hardware_settings")
    fake_module.get_tower_light_settings = lambda: fake_settings
    monkeypatch.setitem(
        __import__("sys").modules, "app_core.hardware_settings", fake_module
    )

    result = load_tower_light_config_from_db()
    assert result is not None
    assert result.protocol == "andont"
    assert result.alert_color == "blue"

    fake_settings["protocol"] = "nonsense"
    fake_settings["alert_color"] = "ultraviolet"
    result = load_tower_light_config_from_db()
    assert result.protocol == "adafruit"
    assert result.alert_color == "red"


def test_buzzer_master_kill_switch_overrides_alert_buzzer():
    """buzzer_disabled must silence the buzzer in every state on both protocols."""
    # ANDONT: alert with buzzer requested -> frame still carries buzzer-off (0x01)
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(
            serial_port="/dev/null", protocol="andont",
            alert_buzzer=True, buzzer_disabled=True, blink_on_alert=False,
        )
    )
    ser.written.clear()
    ctrl.start_alert()
    assert ser.written == _andont_frame(0x04, buzzer_on=False, flash=False)

    # Adafruit: BUZ_ON must never be sent
    ctrl, ser = _make_tower_ctrl(
        TowerLightConfig(
            serial_port="/dev/null", alert_buzzer=True, buzzer_disabled=True,
        )
    )
    ser.written.clear()
    ctrl.start_alert()
    assert _TOWER_CMD_BUZ_ON not in ser.written


def test_show_state_clamps_to_fallback_on_adafruit():
    """show_state falls back when the protocol can't render the colour."""
    from app_utils.gpio import _TOWER_CMD_YEL_ON

    ctrl, ser = _make_tower_ctrl(TowerLightConfig(serial_port="/dev/null"))
    ser.written.clear()
    ctrl.show_state("cyan", flash=False, buzzer=False, fallback="yellow")
    assert _TOWER_CMD_YEL_ON in ser.written

    # 'off' (or unknown fallback) turns all segments off
    ser.written.clear()
    ctrl.show_state("off")
    from app_utils.gpio import _TOWER_CMD_GRN_OFF
    for cmd in (_TOWER_CMD_RED_OFF, _TOWER_CMD_YEL_OFF, _TOWER_CMD_GRN_OFF):
        assert cmd in ser.written
