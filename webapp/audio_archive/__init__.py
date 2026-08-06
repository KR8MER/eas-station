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

"""Audio Archives admin page — routes plus its filesystem/config/metadata helpers."""

from .config import (
    DEFAULT_ARCHIVE_CONFIG,
    all_sources_with_archive_config,
    get_archive_config,
    normalize_archive_config,
    save_archive_config,
)
from .routes import register

__all__ = [
    "DEFAULT_ARCHIVE_CONFIG",
    "all_sources_with_archive_config",
    "get_archive_config",
    "normalize_archive_config",
    "register",
    "save_archive_config",
]
