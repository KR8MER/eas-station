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

"""Shared window-resolution and formatting helpers for the reports package."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from app_utils.time import utc_now


# ---------------------------------------------------------------------------
# FCC compliance report builders (received / forwarded / ignored / initiated /
# weekly / monthly).  Each builder returns a uniform ``ReportPayload`` dict
# that the PDF and CSV exporters consume.
# ---------------------------------------------------------------------------


REPORT_DECISION_FILTERS: Dict[str, Tuple[str, ...]] = {
    "received": (),  # all decisions
    "forwarded": ("forwarded",),
    "ignored": ("ignored",),
}

_DECISION_TITLES: Dict[str, str] = {
    "received": "Received Alerts Report",
    "forwarded": "Forwarded Alerts Report",
    "ignored": "Ignored Alerts Report",
}

# Hard ceiling on the number of rows any single report will materialise.
# The export routes accept arbitrary start/end bounds, so a multi-year
# window could otherwise build a list large enough to exhaust the worker.
# Reports that hit the cap say so in their summary block.
REPORT_MAX_ROWS = 25000

def _normalize_window_days(window_days: int) -> int:
    try:
        days = int(window_days)
    except (TypeError, ValueError):
        return 30
    return max(1, min(days, 365))

def _coerce_aware_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def resolve_report_window(
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    days: Optional[int] = None,
) -> Tuple[datetime, datetime]:
    """Resolve a report window from explicit bounds or a relative day count."""
    end_dt = _coerce_aware_utc(end) or utc_now()
    if start is not None:
        start_dt = _coerce_aware_utc(start) or end_dt - timedelta(days=30)
    else:
        window_days = _normalize_window_days(days if days is not None else 30)
        start_dt = end_dt - timedelta(days=window_days)
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    return start_dt, end_dt
