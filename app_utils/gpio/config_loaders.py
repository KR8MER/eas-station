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

from __future__ import annotations

"""Load GPIO, tower-light and NeoPixel configuration from the database."""

import json
from typing import Any, Dict, Iterable, List, Optional, Set

from app_utils.pi_pinout import ARGON_OLED_RESERVED_BCM, ARGON_OLED_RESERVED_PHYSICAL

from .pin_types import (
    MAX_FLASH_INTERVAL_MS,
    MIN_FLASH_INTERVAL_MS, GPIOBehavior, GPIOPinConfig,
)
from .neopixel import (
    NeopixelConfig,
)
from .tower_light import (
    TOWER_LIGHT_COLORS, TOWER_LIGHT_PROTOCOLS, TowerLightConfig,
)

# Import hardware settings helper
try:
    from app_core.hardware_settings import get_gpio_settings
    _GPIO_SETTINGS_AVAILABLE = True
except ImportError:
    _GPIO_SETTINGS_AVAILABLE = False

    def get_gpio_settings():
        """Fallback when settings module not available."""
        return {}

def load_gpio_pin_configs_from_db(logger=None, oled_enabled: bool = False) -> List[GPIOPinConfig]:
    """Load GPIO pin configurations from database.

    Hardware settings (GPIO, OLED, LED Sign, VFD) are configured via the web UI
    at /admin/hardware and stored in the database. Environment variables are
    NOT supported for hardware configuration.

    The pin map is stored as a JSON object mapping pin numbers to their configuration.

    Example pin_map format:
    {
      "17": {"name": "EAS Transmitter PTT", "active_high": true, "hold_seconds": 5.0, "watchdog_seconds": 300.0},
      "27": {"name": "Backup Relay", "active_high": true}
    }

    Args:
        logger: Optional logger used for diagnostic warnings.
        oled_enabled: Whether the OLED display is enabled. If True, pins 2, 3, 4, and 14
                      will be blocked as they are reserved for the OLED module.

    Returns:
        List of :class:`GPIOPinConfig` entries ready to be registered with a
        :class:`GPIOController` instance.
    """

    def _log(level: str, message: str) -> None:
        if logger is None:
            return
        log_method = getattr(logger, level, None)
        if callable(log_method):
            log_method(message)

    def _parse_bool(value: Any, default: bool = True) -> bool:
        """Parse a boolean value from JSON (true/false) or string (HIGH/LOW)."""
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        str_value = str(value).strip().upper()
        if str_value in {"TRUE", "1", "YES", "HIGH"}:
            return True
        if str_value in {"FALSE", "0", "NO", "LOW"}:
            return False
        return default

    def _parse_float(value: Any, default: float) -> float:
        """Parse a float value from JSON or string."""
        if value is None or value == "":
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _add_config(
        configs: List[GPIOPinConfig],
        seen: set,
        pin: int,
        name: str,
        active_high: bool,
        hold_seconds: float,
        watchdog_seconds: float,
        flash_enabled: bool = False,
        flash_interval_ms: int = 500,
        flash_partner_pin: Optional[int] = None,
    ) -> None:
        if pin in seen:
            _log("warning", f"Duplicate GPIO pin {pin} ignored")
            return

        # Only block OLED reserved pins if OLED is actually enabled
        if oled_enabled and pin in ARGON_OLED_RESERVED_BCM:
            reserved_physical = ", ".join(str(p) for p in sorted(ARGON_OLED_RESERVED_PHYSICAL))
            _log(
                "error",
                (
                    f"GPIO pin {pin} is reserved for the Argon OLED module (physical pins {reserved_physical}) "
                    "and cannot be configured while OLED is enabled"
                ),
            )
            return

        if pin < 2 or pin > 27:
            _log("error", f"GPIO pin {pin} is outside the supported BCM range (2-27)")
            return

        configs.append(
            GPIOPinConfig(
                pin=pin,
                name=name or f"GPIO Pin {pin}",
                active_high=active_high,
                hold_seconds=max(0.1, hold_seconds or 0.0),
                watchdog_seconds=max(1.0, watchdog_seconds or 0.0),
                enabled=True,
                flash_enabled=flash_enabled,
                flash_interval_ms=max(MIN_FLASH_INTERVAL_MS, min(MAX_FLASH_INTERVAL_MS, flash_interval_ms)),
                flash_partner_pin=flash_partner_pin,
            )
        )
        seen.add(pin)

    configs: List[GPIOPinConfig] = []
    seen_pins: set = set()

    # Load from database (hardware settings are only configured via /admin/hardware)
    gpio_pin_map = {}
    if _GPIO_SETTINGS_AVAILABLE:
        try:
            gpio_settings = get_gpio_settings()
            gpio_pin_map = gpio_settings.get('pin_map', {})
            if gpio_pin_map and logger:
                logger.debug("Loaded GPIO pin map from database")
        except Exception as exc:
            if logger:
                logger.warning("Failed to load GPIO settings from database: %s", exc)

    # No pins configured in database
    if not gpio_pin_map:
        _log("info", "No GPIO pins configured (configure in Admin > Hardware Settings)")
        return configs

    if not isinstance(gpio_pin_map, dict):
        _log("error", "GPIO pin_map must be a JSON object mapping pin numbers to configurations")
        return configs

    # Process each pin in the map
    for pin_key, pin_config in gpio_pin_map.items():
        try:
            pin_number = int(pin_key)
        except (TypeError, ValueError):
            _log("error", f"Invalid GPIO pin number '{pin_key}' in gpio_pin_map - must be an integer")
            continue

        if not isinstance(pin_config, dict):
            _log("error", f"Invalid configuration for GPIO pin {pin_number} - must be an object")
            continue

        # Extract configuration with defaults
        name = pin_config.get("name", f"GPIO Pin {pin_number}")
        active_high = _parse_bool(pin_config.get("active_high"), default=True)
        hold_seconds = _parse_float(pin_config.get("hold_seconds"), 5.0)
        watchdog_seconds = _parse_float(pin_config.get("watchdog_seconds"), 300.0)
        
        # Flash pattern configuration
        flash_enabled = _parse_bool(pin_config.get("flash_enabled"), default=False)
        flash_interval_ms = int(_parse_float(pin_config.get("flash_interval_ms"), 500.0))
        flash_partner_pin_value = pin_config.get("flash_partner_pin")
        flash_partner_pin = None
        if flash_partner_pin_value is not None and flash_partner_pin_value != "":
            try:
                flash_partner_pin = int(flash_partner_pin_value)
            except (TypeError, ValueError):
                _log("warning", f"Invalid flash_partner_pin '{flash_partner_pin_value}' for GPIO pin {pin_number}")

        _add_config(
            configs,
            seen_pins,
            pin_number,
            name,
            active_high,
            hold_seconds,
            watchdog_seconds,
            flash_enabled,
            flash_interval_ms,
            flash_partner_pin,
        )

    return configs


def _stringify_behavior_matrix(matrix: Dict[int, Iterable[GPIOBehavior]]) -> Dict[str, List[str]]:
    """Convert behavior matrix keys/values to JSON-serializable primitives."""

    result: Dict[str, List[str]] = {}
    for pin, behaviors in matrix.items():
        if not behaviors:
            continue
        if pin in ARGON_OLED_RESERVED_BCM:
            continue
        result[str(pin)] = sorted({behavior.value for behavior in behaviors})
    return result


def serialize_gpio_behavior_matrix(matrix: Dict[int, Iterable[GPIOBehavior]]) -> str:
    """Serialize a behavior matrix to a compact JSON string."""

    if not matrix:
        return ""

    serializable = _stringify_behavior_matrix(matrix)
    if not serializable:
        return ""
    return json.dumps(serializable, separators=(",", ":"), sort_keys=True)


def load_gpio_behavior_matrix_from_db(logger=None, oled_enabled: bool = False) -> Dict[int, Set[GPIOBehavior]]:
    """Load GPIO behavior assignments from database.

    Hardware settings (GPIO, OLED, LED Sign, VFD) are configured via the web UI
    at /admin/hardware and stored in the database. Environment variables are
    NOT supported for hardware configuration.

    Args:
        logger: Optional logger used for diagnostic warnings.
        oled_enabled: Whether the OLED display is enabled. If True, pins 2, 3, 4, and 14
                      will be blocked as they are reserved for the OLED module.

    Returns:
        Dictionary mapping pin numbers to sets of GPIO behaviors.
    """

    # Load from database (hardware settings are only configured via /admin/hardware)
    data = None
    if _GPIO_SETTINGS_AVAILABLE:
        try:
            gpio_settings = get_gpio_settings()
            data = gpio_settings.get('behavior_matrix', {})
            if data and logger:
                logger.debug("Loaded GPIO behavior matrix from database")
        except Exception as exc:
            if logger is not None:
                logger.warning("Failed to load GPIO behavior matrix from database: %s", exc)

    # No behavior matrix configured
    if not data:
        return {}

    matrix: Dict[int, Set[GPIOBehavior]] = {}
    for key, values in data.items():
        try:
            pin = int(key)
        except (TypeError, ValueError):
            if logger is not None:
                logger.warning("Ignoring invalid GPIO behavior pin key %r", key)
            continue

        # Only block OLED reserved pins if OLED is actually enabled
        if oled_enabled and pin in ARGON_OLED_RESERVED_BCM:
            if logger is not None:
                logger.warning(
                    "Ignoring GPIO behavior assignment for OLED-reserved pin %s (OLED is enabled)", pin
                )
            continue

        behaviors: Set[GPIOBehavior] = set()
        if isinstance(values, (list, tuple, set)):
            iterable: Iterable = values
        else:
            iterable = [values]

        for value in iterable:
            behavior = GPIOBehavior.from_value(value)
            if behavior is None:
                if logger is not None:
                    logger.warning(
                        "Ignoring unknown GPIO behavior %r for pin %s",
                        value,
                        pin,
                    )
                continue
            behaviors.add(behavior)

        if behaviors:
            matrix[pin] = behaviors

    return matrix

def load_tower_light_config_from_db(logger=None) -> Optional[TowerLightConfig]:
    """Load USB tower light configuration from the database.

    Returns a :class:`TowerLightConfig` when the feature is enabled, or
    ``None`` when it is disabled or the settings module is unavailable.
    """
    if not _GPIO_SETTINGS_AVAILABLE:
        return None

    try:
        from app_core.hardware_settings import get_tower_light_settings
        settings = get_tower_light_settings()
    except Exception as exc:
        if logger:
            logger.warning("Failed to load tower light settings from database: %s", exc)
        return None

    if not settings.get("enabled", False):
        return None

    protocol = str(settings.get("protocol", "adafruit") or "adafruit").strip().lower()
    if protocol not in TOWER_LIGHT_PROTOCOLS:
        protocol = "adafruit"

    def _color(key: str, default: str) -> str:
        value = str(settings.get(key, default) or default).strip().lower()
        return value if value in TOWER_LIGHT_COLORS else default

    def _hhmm(key: str, default: str) -> str:
        value = str(settings.get(key, default) or default).strip()
        parts = value.split(":")
        try:
            if len(parts) == 2 and 0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59:
                return value
        except ValueError:
            pass
        return default

    return TowerLightConfig(
        serial_port=str(settings.get("serial_port", "/dev/ttyUSB0")),
        baudrate=int(settings.get("baudrate", 9600)),
        protocol=protocol,
        alert_buzzer=bool(settings.get("alert_buzzer", False)),
        buzzer_disabled=bool(settings.get("buzzer_disabled", False)),
        incoming_uses_yellow=bool(settings.get("incoming_uses_yellow", True)),
        blink_on_alert=bool(settings.get("blink_on_alert", True)),
        standby_color=_color("standby_color", "green"),
        incoming_color=_color("incoming_color", "yellow"),
        alert_color=_color("alert_color", "red"),
        test_color=_color("test_color", "cyan"),
        fault_enabled=bool(settings.get("fault_enabled", True)),
        fault_color=_color("fault_color", "magenta"),
        severity_colors_enabled=bool(settings.get("severity_colors_enabled", False)),
        warning_color=_color("warning_color", "red"),
        watch_color=_color("watch_color", "yellow"),
        advisory_color=_color("advisory_color", "white"),
        quiet_enabled=bool(settings.get("quiet_enabled", False)),
        quiet_start=_hhmm("quiet_start", "22:00"),
        quiet_end=_hhmm("quiet_end", "07:00"),
    )


def load_neopixel_config_from_db(logger=None) -> Optional[NeopixelConfig]:
    """Load NeoPixel configuration from the database.

    Hardware settings are configured via the web UI at ``/admin/hardware``
    and stored in the database.  Environment variables are NOT supported for
    NeoPixel configuration.

    Returns:
        A :class:`NeopixelConfig` when the feature is enabled in the
        database, or ``None`` when it is disabled or no settings row exists.
    """
    if not _GPIO_SETTINGS_AVAILABLE:
        return None

    try:
        from app_core.hardware_settings import get_neopixel_settings
        settings = get_neopixel_settings()
    except Exception as exc:
        if logger:
            logger.warning("Failed to load NeoPixel settings from database: %s", exc)
        return None

    if not settings.get("enabled", False):
        return None

    gpio_pin = int(settings.get("gpio_pin", 18))
    if gpio_pin < 2 or gpio_pin > 27:
        if logger:
            logger.error(
                "NeoPixel GPIO pin %d is outside the supported BCM range (2-27)", gpio_pin
            )
        return None

    def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
        try:
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default

    def _rgb(raw: Any, default: tuple) -> tuple:
        if isinstance(raw, dict):
            try:
                return (
                    _clamp(raw.get("r", 0), 0, 255, 0),
                    _clamp(raw.get("g", 0), 0, 255, 0),
                    _clamp(raw.get("b", 0), 0, 255, 0),
                )
            except Exception:
                pass
        return default

    return NeopixelConfig(
        gpio_pin=gpio_pin,
        num_pixels=_clamp(settings.get("num_pixels", 1), 1, 1024, 1),
        brightness=_clamp(settings.get("brightness", 128), 0, 255, 128),
        led_order=str(settings.get("led_order", "GRB")).upper(),
        standby_color=_rgb(settings.get("standby_color"), (0, 10, 0)),
        alert_color=_rgb(settings.get("alert_color"), (255, 0, 0)),
        flash_on_alert=bool(settings.get("flash_on_alert", True)),
        flash_interval_ms=_clamp(settings.get("flash_interval_ms", 500), 50, 5000, 500),
    )
