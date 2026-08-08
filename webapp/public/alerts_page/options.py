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

"""Dropdown options and headline counts for the /alerts filter bar."""

from typing import Any, Dict

from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_core.extensions import db
from app_core.models import CAPAlert
from sqlalchemy.exc import OperationalError

# What the page falls back to when the lookups fail. The filter bar renders
# empty rather than the page 500ing — the alert listing itself is a separate
# query and may well still succeed.
EMPTY_OPTIONS: Dict[str, Any] = {
    "statuses": [],
    "severities": [],
    "events": [],
    "sources": [],
    "active_alerts": 0,
    "expired_alerts": 0,
    "total_alerts": 0,
    "superseded_count": 0,
}


def _distinct(column):
    return [
        row[0]
        for row in db.session.query(column)
        .filter(column.isnot(None))
        .distinct()
        .order_by(column)
        .all()
    ]


def load_filter_options(route_logger) -> Dict[str, Any]:
    """Distinct filter values plus the four headline counts.

    Every lookup shares one try block, so any of them failing yields the whole
    :data:`EMPTY_OPTIONS` set — matching the pre-refactor behaviour.
    """
    try:
        return {
            "statuses": _distinct(CAPAlert.status),
            "severities": _distinct(CAPAlert.severity),
            "events": _distinct(CAPAlert.event),
            "sources": _distinct(CAPAlert.source),
            "active_alerts": get_active_alerts_query().count(),
            "expired_alerts": get_expired_alerts_query().count(),
            "total_alerts": CAPAlert.query.count(),
            "superseded_count": (
                CAPAlert.query.filter(CAPAlert.superseded_by_id.isnot(None)).count()
            ),
        }
    except OperationalError as exc:
        # Database connection or operational error - rollback and use defaults
        db.session.rollback()
        route_logger.warning("Database operational error fetching filter options: %s", exc)
    except Exception as exc:
        # Unexpected error - rollback and log
        db.session.rollback()
        route_logger.warning("Error fetching filter options for alerts page: %s", exc)

    return dict(EMPTY_OPTIONS)


__all__ = ["EMPTY_OPTIONS", "load_filter_options"]
