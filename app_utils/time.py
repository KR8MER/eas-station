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

"""Timezone and datetime helpers for the NOAA alerts system."""

import logging
import os
from datetime import datetime
from typing import Optional

import pytz

# Try to import python-dateutil for robust datetime parsing
try:
    from dateutil import parser as dateutil_parser
    _HAS_DATEUTIL = True
except ImportError:
    _HAS_DATEUTIL = False

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE_NAME = os.getenv("DEFAULT_TIMEZONE", "America/New_York")
UTC_TZ = pytz.UTC
_location_timezone = pytz.timezone(DEFAULT_TIMEZONE_NAME)


def get_location_timezone():
    """Return the configured location timezone object."""

    return _location_timezone


def get_location_timezone_name() -> str:
    """Return the configured location timezone name."""

    tz = get_location_timezone()
    return getattr(tz, "zone", DEFAULT_TIMEZONE_NAME)


def set_location_timezone(tz_name: Optional[str]) -> None:
    """Update the location timezone used by helper utilities."""

    global _location_timezone

    if not tz_name:
        return

    try:
        _location_timezone = pytz.timezone(tz_name)
        logger.info("Updated location timezone to %s", tz_name)
    except Exception as exc:  # pragma: no cover - safety fallback
        logger.warning(
            "Invalid timezone '%s', keeping %s: %s",
            tz_name,
            get_location_timezone_name(),
            exc,
        )


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC_TZ)


def local_now() -> datetime:
    """Get the current configured local time."""

    return utc_now().astimezone(get_location_timezone())


def _parse_datetime_with_tz_abbreviation(dt_string: str, tz_abbrev: str, is_dst: bool) -> Optional[datetime]:
    """Helper to parse datetime strings with timezone abbreviations like EDT/EST.
    
    Args:
        dt_string: Datetime string with timezone abbreviation
        tz_abbrev: Timezone abbreviation to remove (e.g., 'EDT', 'EST')
        is_dst: Whether this is daylight saving time
        
    Returns:
        Parsed datetime in UTC, or None if parsing fails
    """
    clean_string = dt_string.replace(f" {tz_abbrev}", "").replace(tz_abbrev, "")
    try:
        if _HAS_DATEUTIL:
            dt = dateutil_parser.parse(clean_string)
        else:
            dt = datetime.fromisoformat(clean_string)
        
        if dt.tzinfo is None:
            eastern_tz = pytz.timezone("US/Eastern")
            dt = eastern_tz.localize(dt, is_dst=is_dst)
        return dt.astimezone(UTC_TZ)
    except (ValueError, TypeError):
        return None


def parse_nws_datetime(dt_string: Optional[str], logger=None) -> Optional[datetime]:
    """Parse the wide variety of datetime formats used by the NWS feeds.
    
    Uses python-dateutil for robust parsing when available, with fallback to
    standard library datetime parsing for compatibility.
    """
    if not dt_string:
        return None

    dt_string = str(dt_string).strip()

    # Handle 'Z' suffix (UTC indicator) - convert to timezone offset for better compatibility
    if dt_string.endswith("Z"):
        dt_string = dt_string[:-1] + "+00:00"
    
    # Handle common timezone abbreviations (EDT/EST)
    # These are parsed specially because they're not standard ISO 8601
    if "EDT" in dt_string:
        result = _parse_datetime_with_tz_abbreviation(dt_string, "EDT", is_dst=True)
        if result is not None:
            return result
    
    if "EST" in dt_string:
        result = _parse_datetime_with_tz_abbreviation(dt_string, "EST", is_dst=False)
        if result is not None:
            return result
    
    # Try parsing with dateutil (handles most ISO 8601 and common formats)
    # Or fall back to standard library parsing if dateutil is not available
    try:
        if _HAS_DATEUTIL:
            dt = dateutil_parser.parse(dt_string)
        else:
            dt = datetime.fromisoformat(dt_string)
            
        if dt.tzinfo is None:
            # If no timezone, assume UTC for safety
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(UTC_TZ)
    except (ValueError, TypeError):
        pass

    if logger is not None:
        logger.warning("Could not parse datetime: %s", dt_string)
    return None


def _ensure_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC_TZ)
    return dt


def to_location_time(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert *dt* into the configured location timezone.

    Timestamps are persisted in UTC throughout the system; some columns are
    timezone-aware (``db.DateTime(timezone=True)``) and some are naive
    ``datetime.utcnow()`` values. Naive values are treated as UTC so both
    styles render identically.

    Args:
        dt (datetime | None): Timestamp to convert.

    Returns:
        datetime | None: ``dt`` expressed in the location timezone, or ``None``
        when ``dt`` is falsy.

    Example:
        >>> to_location_time(datetime(2026, 8, 11, 10, 6, 43)).hour  # America/New_York
        6
    """
    dt = _ensure_datetime(dt)
    if not dt:
        return None
    return dt.astimezone(get_location_timezone())


def format_local(
    dt: Optional[datetime],
    fmt: str = "%Y-%m-%d %H:%M:%S %Z",
    default: str = "N/A",
) -> str:
    """Format *dt* in the configured location timezone.

    This is the general-purpose replacement for calling ``.strftime()`` directly
    on a stored timestamp in a template, which silently renders UTC and makes
    on-air logs look hours off from the operator's wall clock.

    Args:
        dt (datetime | None): Timestamp to format (UTC, aware or naive).
        fmt (str): ``strftime`` pattern. Include ``%Z`` so the rendered time
            states which zone it is in.
        default (str): Text returned when ``dt`` is missing.

    Returns:
        str: The formatted local timestamp, or *default*.

    Example:
        >>> format_local(utc_now(), '%Y-%m-%d %H:%M:%S %Z')
        '2026-08-11 06:06:43 EDT'
    """
    local_dt = to_location_time(dt)
    if not local_dt:
        return default
    return local_dt.strftime(fmt)


def format_local_datetime(dt: Optional[datetime], include_utc: bool = True) -> str:
    """Format a datetime in the configured local time with optional UTC."""

    if not dt:
        return "Unknown"

    dt = _ensure_datetime(dt)
    if not dt:
        return "Unknown"

    local_dt = dt.astimezone(get_location_timezone())

    if include_utc:
        utc_str = dt.astimezone(UTC_TZ).strftime("%H:%M UTC")
        return f"{local_dt.strftime('%Y-%m-%d %H:%M %Z')} ({utc_str})"

    return local_dt.strftime("%Y-%m-%d %H:%M %Z")


def format_local_date(dt: Optional[datetime]) -> str:
    """Format a datetime to only display the local date."""

    if not dt:
        return "Unknown"

    dt = _ensure_datetime(dt)
    if not dt:
        return "Unknown"

    local_dt = dt.astimezone(get_location_timezone())
    return local_dt.strftime("%Y-%m-%d")


def format_local_time(dt: Optional[datetime]) -> str:
    """Format a datetime to only display the local time."""

    if not dt:
        return "Unknown"

    dt = _ensure_datetime(dt)
    if not dt:
        return "Unknown"

    local_dt = dt.astimezone(get_location_timezone())
    return local_dt.strftime("%I:%M %p %Z")


def is_alert_expired(expires_dt: Optional[datetime]) -> bool:
    """Determine if an alert is expired given its expiration datetime."""

    if not expires_dt:
        return False

    checked_dt = _ensure_datetime(expires_dt)
    if not checked_dt:
        return False

    return checked_dt < utc_now()


# Backwards compatibility exports -----------------------------------------------------
# Older code imported PUTNAM_COUNTY_TZ directly. Provide a proxy that keeps backwards
# compatibility while using the dynamic timezone implementation above.


class _TimezoneProxy:
    def __getattr__(self, item):  # pragma: no cover - simple delegation
        return getattr(get_location_timezone(), item)

    def __str__(self) -> str:  # pragma: no cover - simple delegation
        return str(get_location_timezone())

    def __repr__(self) -> str:  # pragma: no cover - simple delegation
        return repr(get_location_timezone())


PUTNAM_COUNTY_TZ = _TimezoneProxy()

