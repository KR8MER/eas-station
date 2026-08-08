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

"""Headline counts and the categorical breakdowns of the alert corpus."""

from typing import Any, Dict

from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.extensions import db
from app_core.models import Boundary, CAPAlert
from sqlalchemy import func

from .common import StatsSection

TOP_EVENT_LIMIT = 10


def collect_basic_counts(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """The four headline totals.

    They deliberately share one section: any of the four failing zeroes all
    four, which is the pre-existing behaviour and is pinned by
    ``test_the_four_basic_counts_fail_together``. Giving each its own fallback
    would be an improvement, but it is a behaviour change and belongs in its
    own commit.
    """
    return {
        "total_boundaries": Boundary.query.count(),
        "total_alerts": CAPAlert.query.count(),
        "active_alerts": get_active_alerts_query().count(),
        "expired_alerts": get_expired_alerts_query().count(),
    }


def fallback_basic_counts() -> Dict[str, Any]:
    return {
        "total_boundaries": 0,
        "total_alerts": 0,
        "active_alerts": 0,
        "expired_alerts": 0,
    }


def collect_boundary_stats(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """How many boundaries of each type are loaded."""
    boundary_stats = (
        db.session.query(Boundary.type, func.count(Boundary.id).label("count"))
        .group_by(Boundary.type)
        .all()
    )
    return {
        "boundary_stats": [
            {"type": boundary_type, "count": count}
            for boundary_type, count in boundary_stats
        ]
    }


def collect_alert_categories(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Alerts grouped by status, severity and event type."""
    alert_by_status = (
        db.session.query(CAPAlert.status, func.count(CAPAlert.id).label("count"))
        .group_by(CAPAlert.status)
        .all()
    )
    alert_by_severity = (
        db.session.query(CAPAlert.severity, func.count(CAPAlert.id).label("count"))
        .filter(CAPAlert.severity.isnot(None))
        .group_by(CAPAlert.severity)
        .all()
    )
    alert_by_event = (
        db.session.query(CAPAlert.event, func.count(CAPAlert.id).label("count"))
        .group_by(CAPAlert.event)
        .order_by(func.count(CAPAlert.id).desc())
        .limit(TOP_EVENT_LIMIT)
        .all()
    )
    return {
        "alert_by_status": [
            {"status": status, "count": count} for status, count in alert_by_status
        ],
        "alert_by_severity": [
            {"severity": severity, "count": count}
            for severity, count in alert_by_severity
        ],
        "alert_by_event": [
            {"event": event, "count": count} for event, count in alert_by_event
        ],
    }


def fallback_alert_categories() -> Dict[str, Any]:
    return {
        "alert_by_status": [],
        "alert_by_severity": [],
        "alert_by_event": [],
    }


def collect_urgency_certainty(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """CAP urgency and certainty distributions, skipping unset values."""
    alert_by_urgency = (
        db.session.query(CAPAlert.urgency, func.count(CAPAlert.id).label("count"))
        .filter(CAPAlert.urgency.isnot(None))
        .group_by(CAPAlert.urgency)
        .all()
    )
    alert_by_certainty = (
        db.session.query(CAPAlert.certainty, func.count(CAPAlert.id).label("count"))
        .filter(CAPAlert.certainty.isnot(None))
        .group_by(CAPAlert.certainty)
        .all()
    )
    return {
        "alert_by_urgency": [
            {"urgency": urgency, "count": count} for urgency, count in alert_by_urgency
        ],
        "alert_by_certainty": [
            {"certainty": certainty, "count": count}
            for certainty, count in alert_by_certainty
        ],
    }


def collect_message_types(stats_data: Dict[str, Any]) -> Dict[str, Any]:
    """Message-type mix, plus the cancellation and update rates it implies.

    ``AllClear`` counts as a cancellation alongside ``Cancel``; the comparison
    is case-folded because feeds are inconsistent about it.
    """
    alert_by_message_type = (
        db.session.query(CAPAlert.message_type, func.count(CAPAlert.id).label("count"))
        .filter(CAPAlert.message_type.isnot(None))
        .group_by(CAPAlert.message_type)
        .all()
    )
    total_for_mt = stats_data.get("total_alerts") or 0
    cancel_count = sum(
        c for mt, c in alert_by_message_type if mt and mt.lower() in ("cancel", "allclear")
    )
    update_count = sum(
        c for mt, c in alert_by_message_type if mt and mt.lower() == "update"
    )
    return {
        "alert_by_message_type": [
            {"message_type": mt, "count": count} for mt, count in alert_by_message_type
        ],
        "cancellation_rate": round(cancel_count / total_for_mt * 100, 1) if total_for_mt > 0 else 0,
        "update_rate": round(update_count / total_for_mt * 100, 1) if total_for_mt > 0 else 0,
    }


def fallback_message_types() -> Dict[str, Any]:
    return {
        "alert_by_message_type": [],
        "cancellation_rate": 0,
        "update_rate": 0,
    }


BASIC_COUNTS = StatsSection(
    collect_basic_counts, fallback_basic_counts,
    "Error getting basic counts: %s",
)
BOUNDARY_STATS = StatsSection(
    collect_boundary_stats, lambda: {"boundary_stats": []},
    "Error getting boundary stats: %s",
)
ALERT_CATEGORIES = StatsSection(
    collect_alert_categories, fallback_alert_categories,
    "Error getting alert category stats: %s",
)
URGENCY_CERTAINTY = StatsSection(
    collect_urgency_certainty,
    lambda: {"alert_by_urgency": [], "alert_by_certainty": []},
    "Error getting urgency/certainty stats: %s",
)
# Divides by ``total_alerts``, so it must run after BASIC_COUNTS.
MESSAGE_TYPES = StatsSection(
    collect_message_types, fallback_message_types,
    "Error getting message type stats: %s",
)

__all__ = [
    "ALERT_CATEGORIES",
    "BASIC_COUNTS",
    "BOUNDARY_STATS",
    "MESSAGE_TYPES",
    "URGENCY_CERTAINTY",
    "TOP_EVENT_LIMIT",
    "collect_alert_categories",
    "collect_basic_counts",
    "collect_boundary_stats",
    "collect_message_types",
    "collect_urgency_certainty",
]
