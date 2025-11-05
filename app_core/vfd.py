"""VFD display integration helpers used by the Flask application."""

from __future__ import annotations

import os
import threading
from enum import Enum
from types import ModuleType
from typing import Optional

from flask import current_app, has_app_context
from sqlalchemy.exc import OperationalError

from .extensions import db
from .models import VFDDisplay, VFDStatus

VFD_PORT = os.getenv("VFD_PORT", "/dev/ttyUSB0")
VFD_BAUDRATE = int(os.getenv("VFD_BAUDRATE", "38400"))

VFD_AVAILABLE = False
vfd_controller = None
vfd_module: Optional[ModuleType] = None

_vfd_tables_initialized = False
_vfd_tables_error: Optional[Exception] = None
_vfd_tables_lock = threading.Lock()


def _fallback_vfd_brightness():
    """Fallback brightness enum if VFD module not available."""
    class _VFDBrightness(Enum):
        LEVEL_0 = 0
        LEVEL_1 = 1
        LEVEL_2 = 2
        LEVEL_3 = 3
        LEVEL_4 = 4
        LEVEL_5 = 5
        LEVEL_6 = 6
        LEVEL_7 = 7
    return _VFDBrightness


def _fallback_vfd_font():
    """Fallback font enum if VFD module not available."""
    class _VFDFont(Enum):
        FONT_5x7 = 0x01
        FONT_7x10 = 0x02
        FONT_10x14 = 0x03
    return _VFDFont


try:  # pragma: no cover - optional dependency
    import vfd_controller as _vfd_module  # type: ignore
except ImportError as exc:  # pragma: no cover - optional dependency
    NoritakeVFDController = None  # type: ignore
    VFDBrightness = _fallback_vfd_brightness()  # type: ignore
    VFDFont = _fallback_vfd_font()  # type: ignore
    vfd_module = None

    def initialise_vfd_controller(logger, import_error=exc):
        logger.warning("VFD controller module not found: %s", import_error)
        return None
else:
    vfd_module = _vfd_module
    NoritakeVFDController = getattr(_vfd_module, "NoritakeVFDController", None)
    VFDBrightness = getattr(_vfd_module, "VFDBrightness", _fallback_vfd_brightness())
    VFDFont = getattr(_vfd_module, "VFDFont", _fallback_vfd_font())

    def initialise_vfd_controller(logger):
        global VFD_AVAILABLE, vfd_controller

        if NoritakeVFDController is None:
            return None

        try:
            vfd_controller = NoritakeVFDController(
                port=VFD_PORT,
                baudrate=VFD_BAUDRATE
            )

            # Try to connect
            if not vfd_controller.connect():
                logger.info(
                    "VFD controller is unavailable (no active connection on %s). "
                    "VFD integration will remain disabled until the display is connected.",
                    VFD_PORT
                )
                VFD_AVAILABLE = False
                vfd_controller = None
                return None

        except Exception as controller_error:  # pragma: no cover - defensive
            logger.error("Failed to initialize VFD controller: %s", controller_error)
            VFD_AVAILABLE = False
            vfd_controller = None
            return None

        VFD_AVAILABLE = True
        logger.info(
            "VFD controller initialized successfully on %s at %s baud",
            VFD_PORT,
            VFD_BAUDRATE,
        )
        return vfd_controller


def ensure_vfd_tables(force: bool = False):
    """Ensure VFD helper tables exist, creating them on first use."""

    global _vfd_tables_initialized, _vfd_tables_error

    if force:
        _vfd_tables_initialized = False
        _vfd_tables_error = None

    if _vfd_tables_initialized:
        return True

    if isinstance(_vfd_tables_error, OperationalError):
        if has_app_context():
            current_app.logger.debug(
                "Skipping VFD table initialization due to prior OperationalError"
            )
        return False

    if _vfd_tables_error is not None:
        raise _vfd_tables_error

    with _vfd_tables_lock:
        if _vfd_tables_initialized:
            return True

        if isinstance(_vfd_tables_error, OperationalError):
            if has_app_context():
                current_app.logger.debug(
                    "Skipping VFD table initialization due to prior OperationalError"
                )
            return False

        if _vfd_tables_error is not None:
            raise _vfd_tables_error

        return _ensure_vfd_tables_impl()


def _ensure_vfd_tables_impl():
    global _vfd_tables_initialized, _vfd_tables_error

    if _vfd_tables_initialized:
        return True

    if not has_app_context():  # pragma: no cover - convenience
        with current_app.app_context():  # type: ignore[attr-defined]
            return _ensure_vfd_tables_impl()

    try:
        VFDDisplay.__table__.create(db.engine, checkfirst=True)
        VFDStatus.__table__.create(db.engine, checkfirst=True)
    except OperationalError as vfd_error:  # pragma: no cover - defensive
        _vfd_tables_error = vfd_error
        current_app.logger.error("VFD table initialization failed: %s", vfd_error)
        return False
    except Exception as vfd_error:  # pragma: no cover - defensive
        _vfd_tables_error = vfd_error
        current_app.logger.error("VFD table initialization failed: %s", vfd_error)
        raise
    else:
        _vfd_tables_initialized = True
        _vfd_tables_error = None
        current_app.logger.info("VFD tables ensured")
        return True


__all__ = [
    "NoritakeVFDController",
    "VFD_AVAILABLE",
    "VFD_BAUDRATE",
    "VFD_PORT",
    "VFDBrightness",
    "VFDFont",
    "ensure_vfd_tables",
    "initialise_vfd_controller",
    "vfd_controller",
    "vfd_module",
]
