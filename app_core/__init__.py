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

"""Core application modules for the NOAA alerts system."""

# The package exposes commonly used symbols so callers can import from
# ``app_core`` without having to know the concrete module layout.
#
# Flask/SQLAlchemy extensions are only available when the full production
# dependency stack is installed.  Sub-modules that contain pure-Python DSP
# or utility logic (e.g. app_core.radio.demodulation) must remain importable
# in a minimal test environment that only has numpy/scipy installed.

try:
    from .extensions import db  # noqa: F401
    from . import models  # noqa: F401
    _FLASK_AVAILABLE = True
except ImportError:  # pragma: no cover
    db = None  # type: ignore[assignment]
    models = None  # type: ignore[assignment]
    _FLASK_AVAILABLE = False

__all__ = [
    "db",
    "models",
]
