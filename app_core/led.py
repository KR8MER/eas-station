"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""LED sign integration helpers used by the Flask application."""

import os
import threading
from enum import Enum
from types import ModuleType
from typing import Optional, Tuple

from flask import current_app, has_app_context
from sqlalchemy.exc import OperationalError

from .extensions import db
from .location import get_location_settings
from .models import LEDMessage, LEDSignStatus

# Import hardware settings helper
try:
    from app_core.hardware_settings import get_led_settings
    _LED_SETTINGS_AVAILABLE = True
except ImportError:
    _LED_SETTINGS_AVAILABLE = False

    def get_led_settings():
        """Fallback when settings module not available."""
        return {}

LED_AVAILABLE = False
led_controller = None
led_module: Optional[ModuleType] = None

_led_tables_initialized = False
_led_tables_error: Optional[Exception] = None
_led_tables_lock = threading.Lock()


def _fallback_message_priority():
    class _MessagePriority(Enum):
        EMERGENCY = 0
        URGENT = 1
        NORMAL = 2
        LOW = 3

    return _MessagePriority


try:  # pragma: no cover - optional dependency
    import scripts.led_sign_controller as _led_module  # type: ignore
except ImportError as exc:  # pragma: no cover - optional dependency
    LEDSignController = None  # type: ignore
    Color = DisplayMode = Effect = Font = FontSize = Speed = SpecialFunction = None  # type: ignore
    MessagePriority = _fallback_message_priority()  # type: ignore
    led_module = None

    def initialise_led_controller(logger, import_error=exc):
        logger.warning("LED controller module not found: %s", import_error)
        return None
else:
    led_module = _led_module
    LEDSignController = getattr(_led_module, "LEDSignController", None)
    Color = getattr(_led_module, "Color", None)
    DisplayMode = getattr(_led_module, "DisplayMode", getattr(_led_module, "Effect", None))
    Effect = getattr(_led_module, "Effect", None)
    Font = getattr(_led_module, "Font", getattr(_led_module, "FontSize", None))
    FontSize = getattr(_led_module, "FontSize", None)
    Speed = getattr(_led_module, "Speed", None)
    SpecialFunction = getattr(_led_module, "SpecialFunction", None)
    MessagePriority = getattr(
        _led_module,
        "MessagePriority",
        _fallback_message_priority(),
    )

    def initialise_led_controller(logger):
        global LED_AVAILABLE, led_controller

        if LEDSignController is None:
            return None

        # Get settings from database
        led_settings = {}
        if _LED_SETTINGS_AVAILABLE:
            try:
                led_settings = get_led_settings()
            except Exception as exc:
                logger.warning("Failed to load LED settings from database: %s; using defaults", exc)

        # Check if LED is enabled in settings
        if not led_settings.get('enabled', False):
            logger.warning("⚠️  LED sign DISABLED - Enable in Admin > Hardware Settings > LED Sign tab")
            logger.info("📍 To enable LED: Open web UI → Admin → Hardware Settings → LED Sign tab → Check 'Enable LED Sign'")
            LED_AVAILABLE = False
            led_controller = None
            return None

        # Get connection settings from database
        connection_type = led_settings.get('connection_type', 'network')
        
        if connection_type == 'network':
            ip_address = led_settings.get('ip_address', '192.168.1.100')
            port = led_settings.get('port', 10001)
        else:
            # Serial connection - not yet fully implemented in LEDSignController
            logger.warning("LED serial connection not yet fully supported, using network mode")
            ip_address = led_settings.get('ip_address', '192.168.1.100')
            port = led_settings.get('port', 10001)

        try:
            settings = get_location_settings()

            led_controller = LEDSignController(
                ip_address,
                port,
                location_settings=settings,
            )
        except Exception as controller_error:  # pragma: no cover - defensive
            logger.error("❌ Failed to initialize LED controller: %s", controller_error)
            logger.error("   Check LED sign connection and network settings:")
            logger.error(f"   - IP Address: {ip_address}")
            logger.error(f"   - Port: {port}")
            logger.error("   - Verify LED sign is powered on and connected to network")
            logger.error("   - Check firewall rules allow connection to LED sign")
            LED_AVAILABLE = False
            led_controller = None
            return None

        if not getattr(led_controller, "connected", False):
            logger.warning("⚠️  LED sign not connected (may be offline or unreachable)")
            logger.info(f"   - Configured address: {ip_address}:{port}")
            logger.info("   - LED will automatically reconnect when sign becomes available")
            logger.info("   - Check Admin > Hardware Settings > LED Sign to verify configuration")
            # Don't fail completely - allow LED to reconnect later
            LED_AVAILABLE = True  # Keep available for retry
            logger.info("✅ LED controller initialized (waiting for connection)")
            return led_controller

        LED_AVAILABLE = True
        logger.info(
            "LED controller initialized successfully for %s:%s",
            ip_address,
            port,
        )
        return led_controller


def ensure_led_tables(force: bool = False):
    """Ensure LED helper tables exist, creating them on first use."""

    global _led_tables_initialized, _led_tables_error

    if force:
        _led_tables_initialized = False
        _led_tables_error = None

    if _led_tables_initialized:
        return True

    if isinstance(_led_tables_error, OperationalError):
        if has_app_context():
            current_app.logger.debug(
                "Skipping LED table initialization due to prior OperationalError"
            )
        return False

    if _led_tables_error is not None:
        raise _led_tables_error

    with _led_tables_lock:
        if _led_tables_initialized:
            return True

        if isinstance(_led_tables_error, OperationalError):
            if has_app_context():
                current_app.logger.debug(
                    "Skipping LED table initialization due to prior OperationalError"
                )
            return False

        if _led_tables_error is not None:
            raise _led_tables_error

        return _ensure_led_tables_impl()


def _ensure_led_tables_impl():
    global _led_tables_initialized, _led_tables_error

    if _led_tables_initialized:
        return True

    if not has_app_context():  # pragma: no cover - convenience
        with current_app.app_context():  # type: ignore[attr-defined]
            return _ensure_led_tables_impl()

    try:
        LEDMessage.__table__.create(db.engine, checkfirst=True)
        LEDSignStatus.__table__.create(db.engine, checkfirst=True)
    except OperationalError as led_error:  # pragma: no cover - defensive
        _led_tables_error = led_error
        current_app.logger.error("LED table initialization failed: %s", led_error)
        return False
    except Exception as led_error:  # pragma: no cover - defensive
        _led_tables_error = led_error
        current_app.logger.error("LED table initialization failed: %s", led_error)
        raise
    else:
        _led_tables_initialized = True
        _led_tables_error = None
        current_app.logger.info("LED tables ensured")
        return True


__all__ = [
    "Color",
    "DisplayMode",
    "Effect",
    "Font",
    "FontSize",
    "LED_AVAILABLE",
    "MessagePriority",
    "SpecialFunction",
    "Speed",
    "ensure_led_tables",
    "initialise_led_controller",
    "led_controller",
    "led_module",
]
