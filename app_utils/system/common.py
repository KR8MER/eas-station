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

"""Shared filesystem readers and value coercion helpers."""

import contextlib
from pathlib import Path
from typing import Any, Dict, Optional

SystemHealth = Dict[str, Any]


def _safe_read_text(path: Path) -> Optional[str]:
    with contextlib.suppress(OSError, FileNotFoundError, PermissionError):
        value = path.read_text(encoding="utf-8", errors="ignore").strip()
        if value:
            lower = value.lower()
            if lower not in {"none", "unknown", "not specified"}:
                return value
    return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort conversion of nested numeric representations to int."""

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            if cleaned.lower().startswith("0x"):
                return int(cleaned, 16)
            return int(float(cleaned))
        except ValueError:
            return None

    if isinstance(value, dict):
        for key in ("value", "raw", "raw_value", "raw_value_64", "count", "hex"):
            if key in value:
                coerced = _coerce_int(value.get(key))
                if coerced is not None:
                    return coerced

    return None


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        numeric = int(str(value).strip())
        return bool(numeric)
    except (TypeError, ValueError):
        lowered = str(value).strip().lower()
        if lowered in {"y", "yes", "true"}:
            return True
        if lowered in {"n", "no", "false"}:
            return False
    return None


def _is_valid_temperature(temp: float) -> bool:
    """Check if temperature value is within reasonable bounds for Celsius."""
    # Allow range from -50°C to 150°C (should cover all realistic hardware scenarios)
    return -50 <= temp <= 150
