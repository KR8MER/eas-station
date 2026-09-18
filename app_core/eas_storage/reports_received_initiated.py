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

"""Building the received-alerts and initiated-alerts report payloads."""

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select

from app_core.extensions import db
from app_core.models import CAPAlert, EASMessage, ManualEASActivation, ReceivedEASAlert
from app_utils.time import format_local_datetime

from .reports_common import REPORT_DECISION_FILTERS, REPORT_MAX_ROWS, _DECISION_TITLES


def _format_fips(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, (list, tuple, set)):
        return ", ".join(str(v) for v in values)
    return str(values)

def _short(text: Any, limit: int = 80) -> str:
    if text is None:
        return ""
    s = str(text)
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"

def build_received_alerts_report(
    *,
    window_start: datetime,
    window_end: datetime,
    decision: str = "received",
) -> Dict[str, Any]:
    """Build a per-category report covering received_eas_alerts rows.

    ``decision`` selects ``received`` (all), ``forwarded`` or ``ignored``.
    """
    decision_key = decision if decision in REPORT_DECISION_FILTERS else "received"
    filters = REPORT_DECISION_FILTERS[decision_key]

    # Select only the columns the report prints.  Loading whole
    # ``ReceivedEASAlert`` ORM rows drags along ``raw_audio_data``
    # (LargeBinary WAV capture, ~1 MB per alert) and ``full_alert_data``
    # (JSONB) — none of which appear in the output.  On a month of traffic
    # that was hundreds of megabytes of working set per request, enough to
    # get the gunicorn worker OOM-killed, which surfaces to the user as a
    # 502 gateway error on /logs?type=report_received.
    stmt = (
        select(
            ReceivedEASAlert.received_at,
            ReceivedEASAlert.event_code,
            ReceivedEASAlert.event_name,
            ReceivedEASAlert.originator_code,
            ReceivedEASAlert.callsign,
            ReceivedEASAlert.source_name,
            ReceivedEASAlert.matched_fips_codes,
            ReceivedEASAlert.fips_codes,
            ReceivedEASAlert.forwarding_decision,
            ReceivedEASAlert.forwarding_reason,
        )
        .where(
            ReceivedEASAlert.received_at >= window_start,
            ReceivedEASAlert.received_at < window_end,
        )
        .order_by(ReceivedEASAlert.received_at.desc())
        .limit(REPORT_MAX_ROWS)
        .execution_options(yield_per=500)
    )
    if filters:
        stmt = stmt.where(ReceivedEASAlert.forwarding_decision.in_(filters))

    rows: List[List[Any]] = []
    forwarded_count = 0
    ignored_count = 0
    error_count = 0
    for alert in db.session.execute(stmt):
        decision_value = (alert.forwarding_decision or "").lower()
        if decision_value == "forwarded":
            forwarded_count += 1
        elif decision_value == "ignored":
            ignored_count += 1
        elif decision_value == "error":
            error_count += 1
        rows.append([
            format_local_datetime(alert.received_at, include_utc=True),
            alert.event_code or "",
            _short(alert.event_name, 40),
            alert.originator_code or "",
            alert.callsign or alert.source_name or "",
            _format_fips(alert.matched_fips_codes or alert.fips_codes),
            (alert.forwarding_decision or "").upper(),
            _short(alert.forwarding_reason, 60),
        ])

    columns = [
        {"label": "Received (local / UTC)", "weight": 2.4},
        {"label": "Event", "weight": 0.7},
        {"label": "Description", "weight": 2.0},
        {"label": "Originator", "weight": 0.8},
        {"label": "Callsign / Source", "weight": 1.4},
        {"label": "FIPS", "weight": 1.5},
        {"label": "Decision", "weight": 1.0},
        {"label": "Reason", "weight": 2.4},
    ]

    title = _DECISION_TITLES[decision_key]
    subtitle = (
        f"Window: {format_local_datetime(window_start, include_utc=False)}"
        f" to {format_local_datetime(window_end, include_utc=False)}"
    )

    summary_lines = [
        f"Total entries:    {len(rows)}",
        f"Forwarded:        {forwarded_count}",
        f"Ignored:          {ignored_count}",
        f"Errors:           {error_count}",
    ]
    if len(rows) >= REPORT_MAX_ROWS:
        summary_lines.append(
            f"Note: truncated to the newest {REPORT_MAX_ROWS} entries — "
            "narrow the reporting window to see the rest."
        )

    slug = f"{decision_key}-alerts"
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

def build_initiated_alerts_report(
    *,
    window_start: datetime,
    window_end: datetime,
) -> Dict[str, Any]:
    """Alerts initiated by this station: auto-relays plus manual activations."""

    # Column-level selects, not whole ORM rows: ``EASMessage`` carries six
    # LargeBinary audio columns and ``CAPAlert`` carries ``raw_json`` plus a
    # PostGIS ``geom``.  A joined eager load of both to print two strings is
    # what pushed this report past the worker's memory ceiling and turned
    # /logs?type=report_initiated into a 502 gateway error.
    auto_stmt = (
        select(
            EASMessage.created_at,
            EASMessage.same_header,
            CAPAlert.event,
            CAPAlert.identifier,
        )
        .select_from(EASMessage)
        .outerjoin(CAPAlert, EASMessage.cap_alert_id == CAPAlert.id)
        .where(
            EASMessage.created_at >= window_start,
            EASMessage.created_at < window_end,
        )
        .order_by(EASMessage.created_at.desc())
        .limit(REPORT_MAX_ROWS)
        .execution_options(yield_per=500)
    )
    manual_stmt = (
        select(
            ManualEASActivation.sent_at,
            ManualEASActivation.created_at,
            ManualEASActivation.event_name,
            ManualEASActivation.event_code,
            ManualEASActivation.same_header,
            ManualEASActivation.status,
            ManualEASActivation.identifier,
        )
        .where(
            ManualEASActivation.created_at >= window_start,
            ManualEASActivation.created_at < window_end,
        )
        .order_by(ManualEASActivation.created_at.desc())
        .limit(REPORT_MAX_ROWS)
        .execution_options(yield_per=500)
    )

    rows: List[List[Any]] = []
    auto_count = 0
    manual_count = 0

    for message in db.session.execute(auto_stmt):
        auto_count += 1
        rows.append([
            format_local_datetime(message.created_at, include_utc=True),
            "AUTO",
            message.event or "",
            "",
            _short(message.same_header, 50),
            "relayed",
            _short(message.identifier or "", 40),
        ])

    for activation in db.session.execute(manual_stmt):
        manual_count += 1
        ts = activation.sent_at or activation.created_at
        rows.append([
            format_local_datetime(ts, include_utc=True),
            "MANUAL",
            activation.event_name or activation.event_code or "",
            activation.event_code or "",
            _short(activation.same_header, 50),
            activation.status or "",
            _short(activation.identifier, 40),
        ])

    rows.sort(key=lambda r: r[0], reverse=True)
    truncated = auto_count >= REPORT_MAX_ROWS or manual_count >= REPORT_MAX_ROWS

    columns = [
        {"label": "Initiated (local / UTC)", "weight": 2.4},
        {"label": "Source", "weight": 0.7},
        {"label": "Event", "weight": 1.6},
        {"label": "Code", "weight": 0.6},
        {"label": "SAME Header", "weight": 3.0},
        {"label": "Status", "weight": 1.0},
        {"label": "Identifier", "weight": 1.8},
    ]

    subtitle = (
        f"Window: {format_local_datetime(window_start, include_utc=False)}"
        f" to {format_local_datetime(window_end, include_utc=False)}"
    )
    summary_lines = [
        f"Total initiated:  {auto_count + manual_count}",
        f"Automated relay:  {auto_count}",
        f"Manual activation:{manual_count}",
    ]
    if truncated:
        summary_lines.append(
            f"Note: truncated to the newest {REPORT_MAX_ROWS} entries per source — "
            "narrow the reporting window to see the rest."
        )

    return {
        "slug": "initiated-alerts",
        "title": "Initiated Alerts Report",
        "subtitle": subtitle,
        "columns": columns,
        "rows": rows,
        "summary_lines": summary_lines,
        "window_start": window_start,
        "window_end": window_end,
        "row_count": len(rows),
    }
