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

# Import get_redis_client for backward compatibility
from app_core.redis_client import get_redis_client

__all__ = ["db", "get_radio_manager", "get_redis_client"]
