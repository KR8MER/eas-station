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

"""Shared base for the split ``app_core.models`` package.

The original ``models.py`` was a single 2.3k-line module.  It is now split into
topical sibling modules (``_models_alerts``, ``_models_admin`` and friends) that
all import their SQLAlchemy / typing / Flask dependencies from here.  ``models``
itself remains the public surface and re-exports every name those submodules
expose, so call sites such as ``from app_core.models import CAPAlert`` keep
working unchanged.
"""

import hashlib
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from flask import current_app, has_app_context
from geoalchemy2 import Geometry
from werkzeug.security import (
    check_password_hash as werkzeug_check_password_hash,
    generate_password_hash as werkzeug_generate_password_hash,
)

from app_utils import ALERT_SOURCE_UNKNOWN, normalize_alert_source, utc_now
from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS

from .extensions import db
from sqlalchemy.engine.url import make_url
from sqlalchemy.dialects.postgresql import JSONB


def _spatial_backend_supports_geometry() -> bool:
    database_url = os.getenv("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL")
    if not database_url:
        return True

    try:
        backend = make_url(database_url).get_backend_name()
    except Exception:
        return True

    return backend == "postgresql"


_GEOMETRY_SUPPORTED = _spatial_backend_supports_geometry()


def _geometry_type(geometry_type: str):
    if _GEOMETRY_SUPPORTED:
        return Geometry(geometry_type, srid=4326)

    if has_app_context():  # pragma: no cover - logging requires app context
        current_app.logger.warning(
            "Spatial functions unavailable; storing %s geometry as plain text", geometry_type
        )
    return db.Text


def _log_warning(message: str) -> None:
    """Log a warning using the configured Flask application logger."""

    if has_app_context():
        current_app.logger.warning(message)


def _log_info(message: str) -> None:
    """Log an info message using the configured Flask application logger."""

    if has_app_context():
        current_app.logger.info(message)


__all__ = [
    "ALERT_SOURCE_UNKNOWN",
    "Any",
    "DEFAULT_LOCATION_SETTINGS",
    "Dict",
    "Geometry",
    "JSONB",
    "List",
    "Optional",
    "_GEOMETRY_SUPPORTED",
    "_geometry_type",
    "_log_info",
    "_log_warning",
    "_spatial_backend_supports_geometry",
    "current_app",
    "datetime",
    "db",
    "has_app_context",
    "hashlib",
    "make_url",
    "normalize_alert_source",
    "os",
    "utc_now",
    "werkzeug_check_password_hash",
    "werkzeug_generate_password_hash",
]
