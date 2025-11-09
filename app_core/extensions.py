"""Flask extension singletons used across the NOAA alerts application."""

from flask import current_app
from flask_sqlalchemy import SQLAlchemy

# SQLAlchemy is initialised via the application factory in ``app.py``.
db = SQLAlchemy()

# Global RadioManager instance for SDR receivers
# This is initialized in the application factory
radio_manager = None

def get_radio_manager():
    """Get the global RadioManager instance."""
    global radio_manager
    if radio_manager is None:
        from app_core.radio import RadioManager
        radio_manager = RadioManager()
        radio_manager.register_builtin_drivers()
    try:
        app = current_app._get_current_object()
    except Exception:  # pragma: no cover - current_app may be unavailable
        app = None
    if app is not None:
        radio_manager.attach_app(app)
    return radio_manager

__all__ = ["db", "get_radio_manager"]
