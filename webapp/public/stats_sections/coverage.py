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

"""Geographic coverage and how long alerts stay live."""

from collections import defaultdict
from typing import Any, Dict, List

from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, Intersection
from sqlalchemy import func

from .common import StatsSection

TOP_BOUNDARY_LIMIT = 10
SECONDS_PER_HOUR = 3600


def collect_most_affected_boundaries(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """The boundaries intersecting the most alerts, busiest first."""
    most_affected = (
        db.session.query(
            Boundary.name,
            Boundary.type,
            func.count(Intersection.id).label("alert_count"),
        )
        .join(Intersection, Boundary.id == Intersection.boundary_id)
        .group_by(Boundary.id, Boundary.name, Boundary.type)
        .order_by(func.count(Intersection.id).desc())
        .limit(TOP_BOUNDARY_LIMIT)
        .all()
    )
    return {
        "most_affected_boundaries": [
            {"name": name, "type": b_type, "count": count}
            for name, b_type, count in most_affected
        ]
    }


def collect_duration_stats(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Per-event-type alert lifetimes, in hours.

    Non-positive durations are dropped: an alert whose ``expires`` precedes its
    ``sent`` is bad feed data, and averaging it in drags the mean negative.
    Events are ordered by total live time, so the busiest sit at the top.
    """
    durations = (
        db.session.query(
            CAPAlert.event,
            (
                func.extract("epoch", CAPAlert.expires)
                - func.extract("epoch", CAPAlert.sent)
            ).label("duration_seconds"),
        )
        .filter(
            CAPAlert.expires.isnot(None),
            CAPAlert.sent.isnot(None),
        )
        .all()
    )

    duration_by_event: Dict[str, List[float]] = defaultdict(list)
    for event, duration in durations:
        if duration and duration > 0:
            duration_by_event[event].append(duration / SECONDS_PER_HOUR)

    return {
        "duration_stats": [
            {
                "event": event,
                "count": len(values),
                "average": round(sum(values) / len(values), 2) if values else 0,
                "minimum": round(min(values), 2) if values else 0,
                "maximum": round(max(values), 2) if values else 0,
            }
            for event, values in sorted(
                duration_by_event.items(), key=lambda item: sum(item[1]), reverse=True
            )
        ]
    }


def collect_coverage_overlap(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """What share of alerts resolved to at least one boundary.

    Counts *distinct* alerts: an alert covering forty counties has forty
    intersection rows but is still one alert with coverage.
    """
    alerts_with_coverage = (
        db.session.query(func.count(func.distinct(Intersection.cap_alert_id))).scalar() or 0
    )
    total_for_cov = stats_data.get("total_alerts") or 0
    return {
        "coverage_overlap_rate": round(alerts_with_coverage / total_for_cov * 100, 1) if total_for_cov > 0 else 0,
        "alerts_with_coverage": alerts_with_coverage,
    }


MOST_AFFECTED_BOUNDARIES = StatsSection(
    collect_most_affected_boundaries,
    lambda: {"most_affected_boundaries": []},
    "Error getting affected boundaries: %s",
)
DURATION_STATS = StatsSection(
    collect_duration_stats, lambda: {"duration_stats": []},
    "Error calculating duration stats: %s",
)
# Divides by ``total_alerts``, so it must run after BASIC_COUNTS.
COVERAGE_OVERLAP = StatsSection(
    collect_coverage_overlap,
    lambda: {"coverage_overlap_rate": 0, "alerts_with_coverage": 0},
    "Error getting coverage overlap rate: %s",
)

__all__ = [
    "COVERAGE_OVERLAP",
    "DURATION_STATS",
    "MOST_AFFECTED_BOUNDARIES",
    "SECONDS_PER_HOUR",
    "TOP_BOUNDARY_LIMIT",
    "collect_coverage_overlap",
    "collect_duration_stats",
    "collect_most_affected_boundaries",
]
