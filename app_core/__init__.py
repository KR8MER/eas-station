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

"""Core application modules for the NOAA alerts system."""

# The package exposes commonly used symbols so callers can import from
# ``app_core`` without having to know the concrete module layout.

from .extensions import db  # noqa: F401
from . import models  # noqa: F401

__all__ = [
    "db",
    "models",
]
