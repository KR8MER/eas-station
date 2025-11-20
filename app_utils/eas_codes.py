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

"""Helper functions for mapping SAME event and originator codes to names."""

from __future__ import annotations

from typing import Optional

from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.eas import ORIGINATOR_DESCRIPTIONS


def _normalize_code(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = ''.join(ch for ch in value.upper() if ch.isalnum())
    if not cleaned:
        return None
    return cleaned[:3]


def get_event_name(code: Optional[str]) -> Optional[str]:
    """Return the descriptive name for a SAME event code."""

    normalized = _normalize_code(code)
    if not normalized:
        return None
    data = EVENT_CODE_REGISTRY.get(normalized)
    return data.get('name') if data else None


def get_originator_name(code: Optional[str]) -> Optional[str]:
    """Return the descriptive name for a SAME originator code."""

    normalized = _normalize_code(code)
    if not normalized:
        return None
    return ORIGINATOR_DESCRIPTIONS.get(normalized)


__all__ = ["get_event_name", "get_originator_name"]
