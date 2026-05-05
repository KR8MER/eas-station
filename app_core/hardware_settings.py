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

    # Check if cached object is still valid (attached to session)
    if _settings_cache is not None and not _cache_dirty:
        try:
            # Check if instance is detached from session
            insp = inspect(_settings_cache)
            if not insp.detached:
                return _settings_cache
        except Exception:
            pass
        # Cache is stale/detached, need to re-query
        _cache_dirty = True

    # Query database
    settings = HardwareSettings.query.get(1)

    if settings is None:
        # Create default settings if none exist
        settings = HardwareSettings(id=1)
        db.session.add(settings)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            # Try to get again in case another process created it
            settings = HardwareSettings.query.get(1)
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

    settings = get_hardware_settings()

    # Update fields
    for key, value in updates.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    # Commit changes
    db.session.add(settings)
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
        'alert_buzzer': settings.tower_light_alert_buzzer,
        'incoming_uses_yellow': settings.tower_light_incoming_uses_yellow,
        'blink_on_alert': settings.tower_light_blink_on_alert,
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
