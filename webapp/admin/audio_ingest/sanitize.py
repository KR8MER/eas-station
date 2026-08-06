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

"""JSON-safety helpers for values that reach the API surface."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


def _sanitize_float(value: float) -> float:
    """Sanitize float values to be JSON-safe (no inf/nan, convert numpy types)."""
    import math
    import numpy as np

    # Handle None values
    if value is None:
        return -120.0
    
    # Convert numpy types to regular Python float first
    if isinstance(value, (np.floating, np.integer)):
        value = float(value)
    
    # Handle non-numeric types
    try:
        value = float(value)
    except (TypeError, ValueError):
        return -120.0

    if math.isinf(value):
        return -120.0 if value < 0 else 120.0
    if math.isnan(value):
        return -120.0
    return value


def _sanitize_bool(value) -> bool:
    """Sanitize boolean values to be JSON-safe (convert numpy bool_ types)."""
    import numpy as np

    # Handle None values
    if value is None:
        return False
    
    # Convert numpy bool_ to Python bool
    if isinstance(value, np.bool_):
        return bool(value)

    return bool(value)


def _sanitize_metadata_value(value: Any) -> Any:
    """Sanitize a metadata value to ensure JSON serialization safety."""
    if value is None:
        return None

    # Treat the literal string "None" as missing.  AudioSourceMetrics rows
    # written before the Redis scalar round-trip fix (commit 44162d8) stored
    # Python None as the JSON string "None" in the source_metadata JSONB
    # column, and that value still leaks through _merge_metadata as a truthy
    # string — rendering "Station Name (PS): None", "PI: None" etc. in the
    # audio monitor instead of hiding those rows.
    if isinstance(value, str) and value == "None":
        return None

    if isinstance(value, (str, int)):
        return value

    if isinstance(value, float):
        return _sanitize_float(value)

    if isinstance(value, bool):
        return _sanitize_bool(value)

    if isinstance(value, (list, tuple)):
        return [
            _sanitize_metadata_value(item)
            for item in value
        ]

    if isinstance(value, dict):
        return {
            str(key): _sanitize_metadata_value(item)
            for key, item in value.items()
        }

    if isinstance(value, datetime):
        return value.isoformat()

    try:
        import numpy as np  # type: ignore

        if isinstance(value, (np.floating, np.integer)):
            return _sanitize_float(float(value))

        if isinstance(value, np.bool_):
            return _sanitize_bool(bool(value))
    except Exception:
        # numpy may not be installed in some environments
        pass

    return str(value)


def _merge_metadata(*metadata_sources: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Merge multiple metadata dictionaries into a sanitized structure."""
    merged: Dict[str, Any] = {}

    for metadata in metadata_sources:
        if not metadata:
            continue

        for key, value in metadata.items():
            sanitized_value = _sanitize_metadata_value(value)
            if sanitized_value is None:
                continue

            key_str = str(key)
            if key_str in merged and merged[key_str] is not None:
                continue

            merged[key_str] = sanitized_value

    return merged or None


def _redact_device_params(device_params: Any) -> Any:
    """Return a copy of device_params with the stored stream password redacted.

    The browser never needs the actual credential; it only needs to know one is
    stored (so the edit form can show "leave blank to keep current"). We expose a
    boolean ``auth_password_set`` instead of the secret.
    """
    if not isinstance(device_params, dict):
        return device_params
    redacted = dict(device_params)
    if 'auth_password' in redacted:
        redacted['auth_password_set'] = bool(redacted.get('auth_password'))
        redacted.pop('auth_password', None)
    return redacted


def _db_to_linear(db_value: float) -> float:
    """Convert dB value to linear (0.0 to 1.0 range)."""
    if db_value <= -120.0:
        return 0.0
    if db_value >= 0.0:
        return 1.0
    # dB to linear: 10^(dB/20), normalized to 0-1 range assuming -60dB floor
    import math
    linear = math.pow(10, db_value / 20.0)
    return min(1.0, max(0.0, linear))
