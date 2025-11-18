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
