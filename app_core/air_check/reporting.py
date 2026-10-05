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

"""Air-check summaries for the Air-Check page and the health-alert worker."""

import logging
from datetime import timedelta
from typing import Any, Dict, List

from app_utils import utc_now

from .roles import _default_session, _rollback, air_check_receivers
from .service import sweep_overdue

logger = logging.getLogger(__name__)


def summarize(hours: int = 24, session=None) -> Dict[str, Any]:
    """Counts by status for the window, plus unacknowledged problem count."""
    session = session or _default_session()
    from app_core.models import AirCheckRecord
    from app_core._models_air_check import (
        AIR_CHECK_STATUSES,
        AIR_CHECK_STATUS_MISMATCH,
        AIR_CHECK_STATUS_MISSED,
        AIR_CHECK_STATUS_UNEXPECTED,
    )

    since = utc_now() - timedelta(hours=hours)
    counts = {status: 0 for status in AIR_CHECK_STATUSES}
    open_counts = {status: 0 for status in AIR_CHECK_STATUSES}
    rows = (
        session.query(AirCheckRecord.status, AirCheckRecord.acknowledged_at)
        .filter(AirCheckRecord.created_at >= since)
        .all()
    )
    problems = (AIR_CHECK_STATUS_MISSED, AIR_CHECK_STATUS_MISMATCH, AIR_CHECK_STATUS_UNEXPECTED)
    for status, acknowledged_at in rows:
        counts[status] = counts.get(status, 0) + 1
        if status in problems and acknowledged_at is None:
            open_counts[status] = open_counts.get(status, 0) + 1
    return {
        "hours": hours,
        "counts": counts,
        "open_counts": open_counts,
        "open_problems": sum(open_counts.values()),
        "receivers": [
            {"identifier": r.identifier, "display_name": r.display_name}
            for r in air_check_receivers(session)
        ],
    }


def collect_air_check_issues(session=None) -> List[str]:
    """Unacknowledged air-check problems, phrased for the health-alert email."""
    session = session or _default_session()
    try:
        sweep_overdue(session)
        summary = summarize(24, session)
    except Exception as exc:
        logger.debug("Air-check issue collection failed: %s", exc)
        _rollback(session)
        return []
    counts = summary["open_counts"]
    if not summary["open_problems"]:
        return []
    issues = []
    if counts.get("missed"):
        issues.append(
            f"Air-check: {counts['missed']} transmission(s) in the last 24h were NOT heard "
            "on the air-check receiver"
        )
    if counts.get("mismatch"):
        issues.append(
            f"Air-check: {counts['mismatch']} transmission(s) in the last 24h were heard "
            "on air with a header different from the one sent"
        )
    if counts.get("unexpected"):
        issues.append(
            f"Air-check: {counts['unexpected']} header(s) heard on this station's transmitter "
            "in the last 24h that this station did not send"
        )
    return issues


__all__ = [
    "collect_air_check_issues",
    "summarize",
]
