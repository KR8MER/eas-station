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

"""Building the weekly/monthly summary report payloads."""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy import select

from app_core.extensions import db
from app_core.models import EASMessage, ManualEASActivation, ReceivedEASAlert
from app_utils.time import format_local_datetime

from .compliance_log import _event_matches_test
from .reports_common import _coerce_aware_utc


def _bucket_received(
    window_start: datetime, window_end: datetime
) -> List[Any]:
    """Return lightweight Row tuples (received_at, forwarding_decision,
    event_code, event_name) for ReceivedEASAlert in the window.

    The full ORM object carries ``full_alert_data`` (JSONB) and
    ``raw_audio_data`` (LargeBinary), both potentially multi-megabyte.
    Loading them just to read four small columns has OOM'd workers in the
    past, so we pull only what the report uses.
    """
    stmt = (
        select(
            ReceivedEASAlert.received_at,
            ReceivedEASAlert.forwarding_decision,
            ReceivedEASAlert.event_code,
            ReceivedEASAlert.event_name,
        )
        .where(
            ReceivedEASAlert.received_at >= window_start,
            ReceivedEASAlert.received_at < window_end,
        )
        .order_by(ReceivedEASAlert.received_at.asc())
        .execution_options(yield_per=500)
    )
    return list(db.session.execute(stmt))

def _bucket_initiated(window_start: datetime, window_end: datetime) -> List[Tuple[datetime, str]]:
    """Return ``(timestamp, source)`` pairs for every initiated EAS message
    in the window.

    EASMessage carries six LargeBinary audio columns; loading the full ORM
    row to read ``created_at`` is the difference between a few KB and a few
    GB of working set on a busy month.  We pull just the timestamps.
    """
    items: List[Tuple[datetime, str]] = []
    eas_stmt = (
        select(EASMessage.created_at)
        .where(
            EASMessage.created_at >= window_start,
            EASMessage.created_at < window_end,
        )
        .execution_options(yield_per=500)
    )
    for (created_at,) in db.session.execute(eas_stmt):
        items.append((created_at, "auto"))
    manual_stmt = (
        select(
            ManualEASActivation.sent_at,
            ManualEASActivation.created_at,
        )
        .where(
            ManualEASActivation.created_at >= window_start,
            ManualEASActivation.created_at < window_end,
        )
        .execution_options(yield_per=500)
    )
    for sent_at, created_at in db.session.execute(manual_stmt):
        items.append((sent_at or created_at, "manual"))
    return items

def _iso_week_start(dt: datetime) -> datetime:
    aware = _coerce_aware_utc(dt) or dt
    monday = aware - timedelta(days=aware.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)

def _month_start(dt: datetime) -> datetime:
    aware = _coerce_aware_utc(dt) or dt
    return aware.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def _bucket_summary_report(
    *,
    window_start: datetime,
    window_end: datetime,
    period: str,
) -> Dict[str, Any]:
    received_alerts = _bucket_received(window_start, window_end)
    initiated_items = _bucket_initiated(window_start, window_end)

    if period == "weekly":
        bucket_fn = _iso_week_start
        bucket_label = "Week starting"
        title = "Weekly Compliance Summary"
        slug = "weekly-summary"
    else:
        bucket_fn = _month_start
        bucket_label = "Month"
        title = "Monthly Compliance Summary"
        slug = "monthly-summary"

    buckets: Dict[datetime, Dict[str, int]] = defaultdict(
        lambda: {
            "received": 0,
            "forwarded": 0,
            "ignored": 0,
            "errors": 0,
            "tests": 0,
            "auto_initiated": 0,
            "manual_initiated": 0,
        }
    )

    for alert in received_alerts:
        ts = _coerce_aware_utc(alert.received_at)
        if ts is None:
            continue
        key = bucket_fn(ts)
        bucket = buckets[key]
        bucket["received"] += 1
        decision = (alert.forwarding_decision or "").lower()
        if decision == "forwarded":
            bucket["forwarded"] += 1
        elif decision == "ignored":
            bucket["ignored"] += 1
        elif decision == "error":
            bucket["errors"] += 1
        if (alert.event_code or "").upper() in {"RWT", "RMT"} or _event_matches_test(alert.event_name):
            bucket["tests"] += 1

    for ts, source in initiated_items:
        ts_aware = _coerce_aware_utc(ts)
        if ts_aware is None:
            continue
        key = bucket_fn(ts_aware)
        bucket = buckets[key]
        if source == "auto":
            bucket["auto_initiated"] += 1
        else:
            bucket["manual_initiated"] += 1

    sorted_keys = sorted(buckets.keys(), reverse=True)

    rows: List[List[Any]] = []
    totals = {
        "received": 0,
        "forwarded": 0,
        "ignored": 0,
        "errors": 0,
        "tests": 0,
        "auto_initiated": 0,
        "manual_initiated": 0,
    }
    for key in sorted_keys:
        b = buckets[key]
        for k, v in b.items():
            totals[k] += v
        if period == "weekly":
            label = format_local_datetime(key, include_utc=False)
        else:
            local = key
            label = local.strftime("%Y-%m")
        forward_rate = (b["forwarded"] / b["received"] * 100.0) if b["received"] else None
        rate_str = f"{forward_rate:.1f}%" if forward_rate is not None else "—"
        rows.append([
            label,
            b["received"],
            b["forwarded"],
            b["ignored"],
            b["errors"],
            b["tests"],
            b["auto_initiated"],
            b["manual_initiated"],
            rate_str,
        ])

    columns = [
        {"label": bucket_label, "weight": 2.0},
        {"label": "Received", "weight": 1.0},
        {"label": "Forwarded", "weight": 1.0},
        {"label": "Ignored", "weight": 1.0},
        {"label": "Errors", "weight": 0.9},
        {"label": "Tests (RWT/RMT)", "weight": 1.3},
        {"label": "Auto Initiated", "weight": 1.2},
        {"label": "Manual Initiated", "weight": 1.3},
        {"label": "Forward Rate", "weight": 1.1},
    ]

    subtitle = (
        f"Window: {format_local_datetime(window_start, include_utc=False)}"
        f" to {format_local_datetime(window_end, include_utc=False)}"
    )

    forward_rate = (
        (totals["forwarded"] / totals["received"] * 100.0) if totals["received"] else None
    )
    rate_str = f"{forward_rate:.1f}%" if forward_rate is not None else "N/A"
    summary_lines = [
        f"Buckets:           {len(sorted_keys)}",
        f"Received:          {totals['received']}",
        f"Forwarded:         {totals['forwarded']}",
        f"Ignored:           {totals['ignored']}",
        f"Errors:            {totals['errors']}",
        f"Tests (RWT/RMT):   {totals['tests']}",
        f"Auto initiated:    {totals['auto_initiated']}",
        f"Manual initiated:  {totals['manual_initiated']}",
        f"Overall forward rate: {rate_str}",
    ]

    return {
        "slug": slug,
        "title": title,
        "subtitle": subtitle,
        "columns": columns,
        "rows": rows,
        "summary_lines": summary_lines,
        "window_start": window_start,
        "window_end": window_end,
        "row_count": len(rows),
    }

def build_weekly_summary_report(
    *, window_start: datetime, window_end: datetime
) -> Dict[str, Any]:
    return _bucket_summary_report(
        window_start=window_start, window_end=window_end, period="weekly"
    )

def build_monthly_summary_report(
    *, window_start: datetime, window_end: datetime
) -> Dict[str, Any]:
    return _bucket_summary_report(
        window_start=window_start, window_end=window_end, period="monthly"
    )
