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

"""When alerts happen: hour/day/month/year buckets and the recent-alert feed."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

from app_core.extensions import db
from app_core.models import CAPAlert
from sqlalchemy import func

from .common import StatsSection, empty_dow_hour_matrix

# Rows older than this many years are treated as corrupt rather than historic —
# an alert stamped 1970 is a Unix-epoch default, not a real 1970 alert.
MAX_YEAR_LOOKBACK = 5

# How many recent alerts feed the client-side charts and filter dropdowns.
RECENT_ALERT_LIMIT = 2500

# How many days of daily totals the "recent" strip shows.
RECENT_DAY_WINDOW = 30


def collect_time_buckets(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Alert counts bucketed by hour, weekday, month and year."""
    alert_by_hour = (
        db.session.query(
            func.extract("hour", CAPAlert.sent).label("hour"),
            func.count(CAPAlert.id).label("count"),
        )
        .group_by(func.extract("hour", CAPAlert.sent))
        .all()
    )
    hourly_data = [0] * 24
    for hour, count in alert_by_hour:
        if hour is not None:
            hourly_data[int(hour)] = count

    alert_by_dow = (
        db.session.query(
            func.extract("dow", CAPAlert.sent).label("dow"),
            func.count(CAPAlert.id).label("count"),
        )
        .group_by(func.extract("dow", CAPAlert.sent))
        .all()
    )
    # Postgres `extract(dow)` is already 0=Sunday, which is the index the
    # template's labels use, so no shift is applied here. (The matrix below
    # builds its index from Python's weekday() and *does* need one.)
    dow_data = [0] * 7
    for dow, count in alert_by_dow:
        if dow is not None:
            dow_data[int(dow)] = count

    alert_by_month = (
        db.session.query(
            func.extract("month", CAPAlert.sent).label("month"),
            func.count(CAPAlert.id).label("count"),
        )
        .group_by(func.extract("month", CAPAlert.sent))
        .all()
    )
    monthly_data = [0] * 12
    for month, count in alert_by_month:
        if month is not None:
            monthly_data[int(month) - 1] = count

    # Filter to only include years from the last 5 years to exclude
    # potentially corrupted data (e.g., 1970 from Unix epoch defaults)
    min_year = datetime.now().year - MAX_YEAR_LOOKBACK
    alert_by_year = (
        db.session.query(
            func.extract("year", CAPAlert.sent).label("year"),
            func.count(CAPAlert.id).label("count"),
        )
        .filter(func.extract("year", CAPAlert.sent) >= min_year)
        .group_by(func.extract("year", CAPAlert.sent))
        .order_by(func.extract("year", CAPAlert.sent))
        .all()
    )

    return {
        "alert_by_hour": hourly_data,
        "alert_by_dow": dow_data,
        "alert_by_month": monthly_data,
        "alert_by_year": [
            {"year": int(year), "count": count}
            for year, count in alert_by_year
            if year
        ],
    }


def fallback_time_buckets() -> Dict[str, Any]:
    return {
        "alert_by_hour": [0] * 24,
        "alert_by_dow": [0] * 7,
        "alert_by_month": [0] * 12,
        "alert_by_year": [],
    }


def collect_alert_events(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """The recent-alert feed, and everything derived from one pass over it.

    One query serves four outputs — the client-side alert list, the filter
    dropdown options, the daily totals strip and the weekday×hour heat matrix —
    because re-querying for each would be four scans of the same rows.
    """
    recent_alerts = (
        db.session.query(
            CAPAlert.id,
            CAPAlert.identifier,
            CAPAlert.sent,
            CAPAlert.expires,
            CAPAlert.severity,
            CAPAlert.status,
            CAPAlert.event,
            CAPAlert.source,
        )
        .order_by(CAPAlert.sent.desc())
        .limit(RECENT_ALERT_LIMIT)
        .all()
    )

    severities: set[str] = set()
    statuses: set[str] = set()
    events: set[str] = set()
    daily_totals: Dict[str, int] = defaultdict(int)
    hourly_matrix = empty_dow_hour_matrix()
    alert_events: List[Dict[str, Any]] = []

    for (
        alert_id,
        identifier,
        sent,
        expires,
        severity,
        status,
        event,
        source,
    ) in recent_alerts:
        if severity:
            severities.add(severity)
        if status:
            statuses.add(status)
        if event:
            events.add(event)

        if sent:
            day_key = sent.date().isoformat()
            daily_totals[day_key] += 1
            # Python's weekday() is 0=Monday; the matrix rows are 0=Sunday to
            # match the template's labels, hence the shift.
            dow_index = ((sent.weekday() + 1) % 7)
            hour = sent.hour
            hourly_matrix[dow_index][hour] += 1

        alert_events.append(
            {
                "id": alert_id,
                "identifier": identifier,
                "sent": sent.isoformat() if sent else None,
                "expires": expires.isoformat() if expires else None,
                "severity": severity or "Unknown",
                "status": status or "Unknown",
                "event": event or "Unknown",
                "source": source or "Unknown",
            }
        )

    daily_alerts = [
        {"date": day, "count": count} for day, count in sorted(daily_totals.items())
    ]

    return {
        "alert_events": alert_events,
        "filter_options": {
            "severities": sorted(severities),
            "statuses": sorted(statuses),
            "events": sorted(events),
        },
        "daily_alerts": daily_alerts,
        "recent_by_day": daily_alerts[-RECENT_DAY_WINDOW:],
        "dow_hour_matrix": hourly_matrix,
    }


def fallback_alert_events() -> Dict[str, Any]:
    return {
        "alert_events": [],
        "filter_options": {"severities": [], "statuses": [], "events": []},
        "daily_alerts": [],
        "recent_by_day": [],
        "dow_hour_matrix": empty_dow_hour_matrix(),
    }


TIME_BUCKETS = StatsSection(
    collect_time_buckets, fallback_time_buckets,
    "Error getting time-based stats: %s",
)
ALERT_EVENTS = StatsSection(
    collect_alert_events, fallback_alert_events,
    "Error preparing alert events for stats: %s",
)

__all__ = [
    "ALERT_EVENTS",
    "MAX_YEAR_LOOKBACK",
    "RECENT_ALERT_LIMIT",
    "RECENT_DAY_WINDOW",
    "TIME_BUCKETS",
    "collect_alert_events",
    "collect_time_buckets",
]
