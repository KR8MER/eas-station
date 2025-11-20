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

"""Utility helpers for the NOAA alerts Flask application."""

from .time import (
    PUTNAM_COUNTY_TZ,
    UTC_TZ,
    format_local_date,
    format_local_datetime,
    format_local_time,
    get_location_timezone,
    get_location_timezone_name,
    is_alert_expired,
    local_now,
    parse_nws_datetime,
    set_location_timezone,
    utc_now,
)
from .formatting import format_bytes, format_uptime
from .export import generate_csv
from .system import build_system_health_snapshot
from .alert_sources import (
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_MANUAL,
    ALERT_SOURCE_NOAA,
    ALERT_SOURCE_UNKNOWN,
    expand_source_summary,
    normalize_alert_source,
    summarise_sources,
)

__all__ = [
    "PUTNAM_COUNTY_TZ",
    "UTC_TZ",
    "utc_now",
    "local_now",
    "parse_nws_datetime",
    "format_local_datetime",
    "format_local_date",
    "format_local_time",
    "is_alert_expired",
    "format_bytes",
    "format_uptime",
    "generate_csv",
    "build_system_health_snapshot",
    "get_location_timezone",
    "get_location_timezone_name",
    "set_location_timezone",
    "ALERT_SOURCE_NOAA",
    "ALERT_SOURCE_IPAWS",
    "ALERT_SOURCE_MANUAL",
    "ALERT_SOURCE_UNKNOWN",
    "normalize_alert_source",
    "summarise_sources",
    "expand_source_summary",
]
