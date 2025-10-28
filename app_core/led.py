"""LED sign integration helpers used by the Flask application."""

from __future__ import annotations

import os
import threading
from enum import Enum
from types import ModuleType
from typing import Optional

from flask import current_app, has_app_context
from sqlalchemy.exc import OperationalError

from .extensions import db
from .location import get_location_settings
from .models import LEDMessage, LEDSignStatus

LED_SIGN_IP = os.getenv("LED_SIGN_IP", "192.168.1.100")
LED_SIGN_PORT = int(os.getenv("LED_SIGN_PORT", "10001"))

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
    import led_sign_controller as _led_module  # type: ignore
except ImportError as exc:  # pragma: no cover - optional dependency
    LEDSignController = None  # type: ignore
    Color = DisplayMode = Effect = Font = FontSize = Speed = SpecialFunction = None  # type: ignore
    MessagePriority = _fallback_message_priority()  # type: ignore
    led_module = None

    def initialise_led_controller(logger):
        logger.warning("LED controller module not found: %s", exc)
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

        try:
            settings = get_location_settings()
            led_controller = LEDSignController(
                LED_SIGN_IP,
                LED_SIGN_PORT,
                location_settings=settings,
            )
        except Exception as controller_error:  # pragma: no cover - defensive
            logger.error("Failed to initialize LED controller: %s", controller_error)
            LED_AVAILABLE = False
            led_controller = None
            return None

        LED_AVAILABLE = True
        logger.info(
            "LED controller initialized successfully for %s:%s",
            LED_SIGN_IP,
            LED_SIGN_PORT,
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
    "LED_SIGN_IP",
    "LED_SIGN_PORT",
    "MessagePriority",
    "SpecialFunction",
    "Speed",
    "ensure_led_tables",
    "initialise_led_controller",
    "led_controller",
    "led_module",
]
