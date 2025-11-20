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

from __future__ import annotations

"""Location settings defaults and helpers for the NOAA alerts system."""

import os
from typing import Iterable, List, Sequence, Tuple

from app_utils.fips_codes import ALL_US_FIPS_CODES, STATEWIDE_SAME_CODES
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "America/New_York")
DEFAULT_COUNTY_NAME = os.getenv("DEFAULT_COUNTY_NAME", "Putnam County")
DEFAULT_STATE_CODE = os.getenv("DEFAULT_STATE_CODE", "OH")
DEFAULT_ZONE_CODES = os.getenv("DEFAULT_ZONE_CODES", "OHZ016,OHC137")
DEFAULT_FIPS_CODES = os.getenv("DEFAULT_FIPS_CODES", "039137")
DEFAULT_MAP_CENTER_LAT = float(os.getenv("DEFAULT_MAP_CENTER_LAT", "41.0195"))
DEFAULT_MAP_CENTER_LNG = float(os.getenv("DEFAULT_MAP_CENTER_LNG", "-84.1190"))
DEFAULT_MAP_ZOOM = int(os.getenv("DEFAULT_MAP_ZOOM", "9"))
DEFAULT_LED_LINES = os.getenv(
    "DEFAULT_LED_LINES",
    "PUTNAM COUNTY,EMERGENCY MGMT,NO ALERTS,SYSTEM READY",
)


VALID_SAME_CODES = ALL_US_FIPS_CODES | STATEWIDE_SAME_CODES


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def ensure_list(value: Iterable[str] | Sequence[str] | str | None) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_csv(value)
    return [str(item).strip() for item in value if str(item).strip()]


def sanitize_fips_codes(values: Iterable[str] | Sequence[str] | str | None) -> Tuple[List[str], List[str]]:
    """Return valid SAME/FIPS codes and the entries that were rejected."""

    raw_values = ensure_list(values)
    valid: List[str] = []
    invalid: List[str] = []
    seen = set()

    for item in raw_values:
        digits = "".join(ch for ch in str(item) if ch.isdigit())
        if not digits:
            if item:
                invalid.append(str(item))
            continue
        code = digits.zfill(6)[:6]
        if code in VALID_SAME_CODES:
            if code not in seen:
                valid.append(code)
                seen.add(code)
        else:
            invalid.append(str(item))

    return valid, invalid


def normalise_fips_codes(values: Iterable[str] | Sequence[str] | str | None) -> List[str]:
    """Return the valid SAME/FIPS codes in canonical order."""

    valid, _ = sanitize_fips_codes(values)
    return valid


_default_fips_codes = normalise_fips_codes(DEFAULT_FIPS_CODES)
if not _default_fips_codes:
    _default_fips_codes = ["039137"]


DEFAULT_LOCATION_SETTINGS = {
    "county_name": DEFAULT_COUNTY_NAME,
    "state_code": DEFAULT_STATE_CODE,
    "timezone": DEFAULT_TIMEZONE,
    "zone_codes": ensure_list(DEFAULT_ZONE_CODES),
    "fips_codes": list(_default_fips_codes),
    # Area-term matching has been retired from the CAP poller but the field is
    # retained for backwards compatibility with stored settings/exports.
    "area_terms": [],
    "map_center_lat": DEFAULT_MAP_CENTER_LAT,
    "map_center_lng": DEFAULT_MAP_CENTER_LNG,
    "map_default_zoom": DEFAULT_MAP_ZOOM,
    "led_default_lines": ensure_list(DEFAULT_LED_LINES),
}


def normalise_upper(values: Iterable[str]) -> List[str]:
    return [value.upper() for value in ensure_list(values)]


def as_title(value: str) -> str:
    return value.strip() if value else value

