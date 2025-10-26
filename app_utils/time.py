"""Time and timezone helpers used by the Flask application."""

from datetime import datetime
from typing import Optional

import pytz

# Timezone configuration for Putnam County, Ohio (Eastern Time)
PUTNAM_COUNTY_TZ = pytz.timezone("America/New_York")
UTC_TZ = pytz.UTC


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC_TZ)


def local_now() -> datetime:
    """Get the current Putnam County local time."""

    return utc_now().astimezone(PUTNAM_COUNTY_TZ)


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


def format_local_datetime(dt: Optional[datetime], include_utc: bool = True) -> str:
    """Format a datetime in Putnam County local time with optional UTC."""

    if not dt:
        return "Unknown"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)

    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)

    if include_utc:
        utc_str = dt.astimezone(UTC_TZ).strftime("%H:%M UTC")
        return f"{local_dt.strftime('%Y-%m-%d %H:%M %Z')} ({utc_str})"

    return local_dt.strftime("%Y-%m-%d %H:%M %Z")


def format_local_date(dt: Optional[datetime]) -> str:
    """Format a datetime to only display the local date."""

    if not dt:
        return "Unknown"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)

    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    return local_dt.strftime("%Y-%m-%d")


def format_local_time(dt: Optional[datetime]) -> str:
    """Format a datetime to only display the local time."""

    if not dt:
        return "Unknown"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)

    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    return local_dt.strftime("%I:%M %p %Z")


def is_alert_expired(expires_dt: Optional[datetime]) -> bool:
    """Determine if an alert is expired given its expiration datetime."""

    if not expires_dt:
        return False

    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=UTC_TZ)

    return expires_dt < utc_now()
