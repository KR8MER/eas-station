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

"""Helper functions for accessing hardware settings from database."""

from typing import Any, Dict, Optional

from flask import current_app, has_app_context

from .extensions import db
from .models import HardwareSettings


_settings_cache: Optional[HardwareSettings] = None
_cache_dirty = False


def get_hardware_settings() -> HardwareSettings:
    """Get or create the singleton hardware settings record.

    Returns:
        HardwareSettings instance (id=1)
    """
    global _settings_cache, _cache_dirty
    from sqlalchemy import inspect

    # Check if cached object is still valid. The instance is only safe to
    # reuse while it is attached to the *current* scoped session — under
    # gunicorn/gevent each request gets its own session, and handing out an
    # instance owned by another request's session makes any subsequent
    # db.session.add()/flush raise "Object is already attached to session".
    if _settings_cache is not None and not _cache_dirty:
        try:
            insp = inspect(_settings_cache)
            if insp.persistent and insp.session is db.session():
                return _settings_cache
        except Exception:
            pass
        # Cache belongs to another (or no) session, need to re-query
        _cache_dirty = True

    # Query database (attaches a fresh instance to the current session)
    settings = db.session.get(HardwareSettings, 1)

    if settings is None:
        # Create default settings if none exist
        settings = HardwareSettings(id=1)
        db.session.add(settings)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            # Try to get again in case another process created it
            settings = db.session.get(HardwareSettings, 1)
            if settings is None:
                raise

    # Update cache
    _settings_cache = settings
    _cache_dirty = False

    return settings


def update_hardware_settings(updates: Dict[str, Any]) -> HardwareSettings:
    """Update hardware settings with the provided values.

    Args:
        updates: Dictionary of field names and values to update

    Returns:
        Updated HardwareSettings instance
    """
    global _settings_cache, _cache_dirty

    # get_hardware_settings() guarantees the instance is attached to the
    # current session, so no add()/merge() is needed before committing.
    settings = get_hardware_settings()

    # Update fields
    for key, value in updates.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    # Commit changes
    db.session.commit()

    # Mark cache as dirty to force reload
    _cache_dirty = True

    return settings


def invalidate_hardware_settings_cache() -> None:
    """Invalidate the settings cache to force reload from database."""
    global _cache_dirty
    _cache_dirty = True


def get_gpio_settings() -> Dict[str, Any]:
    """Get GPIO-specific settings.

    Returns:
        Dictionary with GPIO configuration
    """
    settings = get_hardware_settings()
    return {
        'enabled': settings.gpio_enabled,
        'pin_map': settings.gpio_pin_map or {},
        'behavior_matrix': settings.gpio_behavior_matrix or {},
    }


def get_oled_settings() -> Dict[str, Any]:
    """Get OLED-specific settings.

    Returns:
        Dictionary with OLED configuration
    """
    settings = get_hardware_settings()
    return {
        'enabled': settings.oled_enabled,
        'i2c_bus': settings.oled_i2c_bus,
        'i2c_address': settings.oled_i2c_address,
        'width': settings.oled_width,
        'height': settings.oled_height,
        'rotate': settings.oled_rotate,
        'contrast': settings.oled_contrast,
        'font_path': settings.oled_font_path,
        'default_invert': settings.oled_default_invert,
        'button_gpio': settings.oled_button_gpio,
        'button_hold_seconds': settings.oled_button_hold_seconds,
        'button_active_high': settings.oled_button_active_high,
        'scroll_effect': settings.oled_scroll_effect,
        'scroll_speed': settings.oled_scroll_speed,
        'scroll_fps': settings.oled_scroll_fps,
        'screens_auto_start': settings.screens_auto_start,
    }


def get_led_settings() -> Dict[str, Any]:
    """Get LED sign-specific settings.

    Returns:
        Dictionary with LED configuration
    """
    settings = get_hardware_settings()
    return {
        'enabled': settings.led_enabled,
        'connection_type': settings.led_connection_type,
        'ip_address': settings.led_ip_address,
        'port': settings.led_port,
        'serial_port': settings.led_serial_port,
        'baudrate': settings.led_baudrate,
        'serial_mode': settings.led_serial_mode,
        'default_text': settings.led_default_text,
    }


def get_vfd_settings() -> Dict[str, Any]:
    """Get VFD display-specific settings.

    Returns:
        Dictionary with VFD configuration
    """
    settings = get_hardware_settings()
    return {
        'enabled': settings.vfd_enabled,
        'port': settings.vfd_port,
        'baudrate': settings.vfd_baudrate,
    }


def get_zigbee_settings() -> Dict[str, Any]:
    """Get Zigbee coordinator-specific settings.

    Returns:
        Dictionary with Zigbee configuration
    """
    settings = get_hardware_settings()
    return {
        'enabled': settings.zigbee_enabled,
        'port': settings.zigbee_port,
        'baudrate': settings.zigbee_baudrate,
        'channel': settings.zigbee_channel,
        'pan_id': settings.zigbee_pan_id,
    }


def get_tower_light_settings() -> Dict[str, Any]:
    """Get USB tower light settings.

    Returns:
        Dictionary with tower light configuration
    """
    settings = get_hardware_settings()
    return {
        'enabled': settings.tower_light_enabled,
        'serial_port': settings.tower_light_serial_port,
        'baudrate': settings.tower_light_baudrate,
        'protocol': getattr(settings, 'tower_light_protocol', 'adafruit') or 'adafruit',
        'alert_buzzer': settings.tower_light_alert_buzzer,
        'incoming_uses_yellow': settings.tower_light_incoming_uses_yellow,
        'blink_on_alert': settings.tower_light_blink_on_alert,
        'standby_color': getattr(settings, 'tower_light_standby_color', 'green') or 'green',
        'incoming_color': getattr(settings, 'tower_light_incoming_color', 'yellow') or 'yellow',
        'alert_color': getattr(settings, 'tower_light_alert_color', 'red') or 'red',
        'buzzer_disabled': bool(getattr(settings, 'tower_light_buzzer_disabled', False)),
        'test_color': getattr(settings, 'tower_light_test_color', 'cyan') or 'cyan',
        'fault_enabled': bool(getattr(settings, 'tower_light_fault_enabled', True)),
        'fault_color': getattr(settings, 'tower_light_fault_color', 'magenta') or 'magenta',
        'gate_pending_enabled': bool(getattr(settings, 'tower_light_gate_pending_enabled', True)),
        'gate_pending_color': getattr(settings, 'tower_light_gate_pending_color', 'blue') or 'blue',
        'severity_colors_enabled': bool(getattr(settings, 'tower_light_severity_colors', False)),
        'warning_color': getattr(settings, 'tower_light_warning_color', 'red') or 'red',
        'watch_color': getattr(settings, 'tower_light_watch_color', 'yellow') or 'yellow',
        'advisory_color': getattr(settings, 'tower_light_advisory_color', 'white') or 'white',
        'quiet_enabled': bool(getattr(settings, 'tower_light_quiet_enabled', False)),
        'quiet_start': getattr(settings, 'tower_light_quiet_start', '22:00') or '22:00',
        'quiet_end': getattr(settings, 'tower_light_quiet_end', '07:00') or '07:00',
        'silence_enabled': bool(getattr(settings, 'tower_light_silence_enabled', True)),
        'silence_color': getattr(settings, 'tower_light_silence_color', 'magenta') or 'magenta',
        'silence_buzzer': bool(getattr(settings, 'tower_light_silence_buzzer', False)),
    }


def get_dead_air_settings() -> Dict[str, Any]:
    """Get dead-air (silence) monitoring settings.

    Feeds both the audio ingest monitors (thresholds) and the GPIO
    indicator service (rack buzzer pin).

    Returns:
        Dictionary with dead-air configuration. ``buzzer_gpio_pin`` is
        ``None`` when the rack buzzer is disabled or unconfigured, which
        the GPIO side reads as "never touch a pin".
    """
    settings = get_hardware_settings()
    buzzer_enabled = bool(getattr(settings, 'dead_air_buzzer_enabled', False))
    pin = getattr(settings, 'dead_air_buzzer_gpio_pin', None)
    return {
        'enabled': bool(getattr(settings, 'dead_air_enabled', False)),
        'level_threshold_db': float(
            getattr(settings, 'dead_air_level_threshold_db', -65) or -65
        ),
        'detect_open_carrier': bool(
            getattr(settings, 'dead_air_detect_open_carrier', True)
        ),
        # Stored as whole percent in the UI; the monitor wants a 0-1 ratio.
        'flatness_threshold': float(
            getattr(settings, 'dead_air_flatness_threshold_pct', 25) or 25
        ) / 100.0,
        'duration_seconds': float(
            getattr(settings, 'dead_air_duration_seconds', 20) or 20
        ),
        'buzzer_enabled': buzzer_enabled,
        'buzzer_gpio_pin': int(pin) if (buzzer_enabled and pin) else None,
    }


def get_neopixel_settings() -> Dict[str, Any]:
    """Get NeoPixel / WS2812B LED strip settings.

    Returns:
        Dictionary with NeoPixel configuration
    """
    settings = get_hardware_settings()
    return {
        'enabled': settings.neopixel_enabled,
        'gpio_pin': settings.neopixel_gpio_pin,
        'num_pixels': settings.neopixel_num_pixels,
        'brightness': settings.neopixel_brightness,
        'led_order': settings.neopixel_led_order,
        'standby_color': settings.neopixel_standby_color or {"r": 0, "g": 10, "b": 0},
        'alert_color': settings.neopixel_alert_color or {"r": 255, "g": 0, "b": 0},
        'flash_on_alert': settings.neopixel_flash_on_alert,
        'flash_interval_ms': settings.neopixel_flash_interval_ms,
    }


def get_gps_settings() -> Dict[str, Any]:
    """Get GPS HAT / receiver settings.

    Defaults target the Uputronics Raspberry Pi GPS/RTC Expansion Board
    (u-blox MAX-M8Q, PPS on BCM 18, DS3231 RTC). The Adafruit Ultimate
    GPS HAT (#2324, PPS on BCM 4) is also supported by changing the PPS
    GPIO pin in Admin → Hardware Settings.

    Returns:
        Dictionary with GPS configuration
    """
    settings = get_hardware_settings()
    return {
        'enabled': settings.gps_enabled,
        'serial_port': settings.gps_serial_port,
        'baudrate': settings.gps_baudrate,
        'pps_gpio_pin': settings.gps_pps_gpio_pin,
        'use_for_location': settings.gps_use_for_location,
        'use_for_time': settings.gps_use_for_time,
        'min_satellites': settings.gps_min_satellites,
        # Tier 3 fields. ``source`` is a string enum (auto/serial/gpsd);
        # the gpsd host/port are only consulted when source is "gpsd"
        # or "auto".
        'gps_source': getattr(settings, 'gps_source', 'auto') or 'auto',
        'gpsd_host': getattr(settings, 'gps_gpsd_host', '127.0.0.1') or '127.0.0.1',
        'gpsd_port': int(getattr(settings, 'gps_gpsd_port', 2947) or 2947),
    }


__all__ = [
    'get_hardware_settings',
    'update_hardware_settings',
    'invalidate_hardware_settings_cache',
    'get_gpio_settings',
    'get_oled_settings',
    'get_led_settings',
    'get_vfd_settings',
    'get_zigbee_settings',
    'get_tower_light_settings',
    'get_neopixel_settings',
    'get_gps_settings',
]
