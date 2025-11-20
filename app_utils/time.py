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

"""Timezone and datetime helpers for the NOAA alerts system."""

import logging
import os
from datetime import datetime
from typing import Optional

import pytz

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


def parse_nws_datetime(dt_string: Optional[str], logger=None) -> Optional[datetime]:
    """Parse the wide variety of datetime formats used by the NWS feeds."""

    if not dt_string:
        return None

    dt_string = str(dt_string).strip()

    if dt_string.endswith("Z"):
        try:
            dt = datetime.fromisoformat(dt_string.replace("Z", "+00:00"))
            return dt.astimezone(UTC_TZ)
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(dt_string)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(UTC_TZ)
    except ValueError:
        pass

    if "EDT" in dt_string:
        try:
            dt_clean = dt_string.replace(" EDT", "").replace("EDT", "")
            dt = datetime.fromisoformat(dt_clean)
            eastern_tz = pytz.timezone("US/Eastern")
            dt = eastern_tz.localize(dt, is_dst=True)
            return dt.astimezone(UTC_TZ)
        except ValueError:
            pass

    if "EST" in dt_string:
        try:
            dt_clean = dt_string.replace(" EST", "").replace("EST", "")
            dt = datetime.fromisoformat(dt_clean)
            est_tz = pytz.timezone("US/Eastern")
            dt = est_tz.localize(dt)
            return dt.astimezone(UTC_TZ)
        except ValueError:
            pass

    if logger is not None:
        logger.warning("Could not parse datetime: %s", dt_string)
    return None


def _ensure_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC_TZ)
    return dt


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

