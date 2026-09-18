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

"""Collecting FCC compliance-log entries and the compliance dashboard summary."""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import defer

from app_core.extensions import db
from app_core.models import CAPAlert, EASMessage, ManualEASActivation, ReceivedEASAlert
from app_utils.eas_codes import get_event_name, get_originator_name
from app_utils.time import utc_now

from .compliance_parsing import (
    _cap_fips_codes,
    _cap_originator_from_source,
    _format_purge_minutes,
    _parse_same_header_fields,
)
from .reports_common import _coerce_aware_utc, _normalize_window_days


TEST_EVENT_KEYWORDS = (
    "Required Weekly Test",
    "Required Monthly Test",
    "RWT",
    "RMT",
)

def _event_matches_test(label: Optional[str]) -> bool:
    if not label:
        return False
    normalized = str(label).lower()
    return any(keyword.lower() in normalized for keyword in TEST_EVENT_KEYWORDS)

def collect_compliance_log_entries(
    window_days: int = 30,
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], datetime, datetime]:
    """Return compliance activity entries for the requested window.

    When ``window_start`` and ``window_end`` are both provided they take
    precedence over ``window_days``; otherwise the window ends at "now" and
    extends ``window_days`` into the past.
    """

    if window_start is not None and window_end is not None:
        window_start = _coerce_aware_utc(window_start) or window_start
        window_end = _coerce_aware_utc(window_end) or window_end
        if window_start > window_end:
            window_start, window_end = window_end, window_start
    else:
        days = _normalize_window_days(window_days)
        window_end = utc_now()
        window_start = window_end - timedelta(days=days)

    entries: List[Dict[str, Any]] = []

    # Define a reasonable limit for compliance log entries to prevent memory exhaustion
    MAX_ENTRIES_PER_CATEGORY = 10000

    # SQLAlchemy fetches every column on the ORM model by default — including
    # several multi-megabyte LargeBinary columns on EASMessage and a JSONB
    # payload on ReceivedEASAlert.  Naively iterating a 30-day window can
    # balloon a gunicorn worker to multiple GB.  We defer the heavy columns,
    # strip the joined CAPAlert down to only what we read, and stream rows
    # with yield_per() so the working set stays small.
    STREAM_BATCH = 500

    try:
        alert_query = (
            CAPAlert.query.filter(CAPAlert.sent >= window_start)
            .order_by(CAPAlert.sent.desc())
            .limit(MAX_ENTRIES_PER_CATEGORY)
            .yield_per(STREAM_BATCH)
        )

        for alert in alert_query:
            originator_code = _cap_originator_from_source(alert.source)
            originator_name = (
                get_originator_name(originator_code) if originator_code else None
            )
            forwarding_reason = (alert.eas_forwarding_reason or "").strip() or None
            if alert.eas_forwarded:
                action_taken = "Relayed"
            elif forwarding_reason:
                action_taken = "Not relayed"
            else:
                action_taken = "Received"
            entries.append(
                {
                    "timestamp": alert.sent,
                    "category": "received",
                    "event_label": alert.event,
                    "event_code": None,  # CAP feeds carry no SAME code directly
                    "originator_code": originator_code,
                    "originator_name": originator_name,
                    "fips_codes": _cap_fips_codes(alert.raw_json),
                    "issue_time": alert.sent,
                    "purge_time": alert.expires,
                    "station": None,
                    "identifier": alert.identifier,
                    "status": alert.status,
                    "action_taken": action_taken,
                    "action_reason": forwarding_reason,
                    "details": {
                        "message_type": alert.message_type,
                        "scope": alert.scope,
                        "urgency": alert.urgency,
                        "severity": alert.severity,
                        "certainty": alert.certainty,
                        "source": alert.source,
                    },
                }
            )

        # Pull only the columns we actually read from EASMessage + the joined
        # CAPAlert.  audio_data presence is computed at the SQL level so we
        # never transfer the megabyte-scale WAV bytes to Python just to ask
        # "is it non-null?".
        eas_select = (
            select(
                EASMessage.id,
                EASMessage.created_at,
                EASMessage.same_header,
                EASMessage.audio_filename,
                EASMessage.text_filename,
                EASMessage.cap_alert_id,
                EASMessage.audio_data.isnot(None).label("has_audio_blob"),
                EASMessage.text_payload.isnot(None).label("has_text_blob"),
                CAPAlert.event.label("cap_event"),
            )
            .select_from(EASMessage)
            .outerjoin(CAPAlert, EASMessage.cap_alert_id == CAPAlert.id)
            .where(EASMessage.created_at >= window_start)
            .order_by(EASMessage.created_at.desc())
            .execution_options(yield_per=STREAM_BATCH)
        )

        for row in db.session.execute(eas_select):
            same_fields = _parse_same_header_fields(row.same_header)
            originator_code = same_fields.get("originator")
            entries.append(
                {
                    "timestamp": row.created_at,
                    "category": "relayed",
                    "event_label": row.cap_event or (
                        get_event_name(same_fields.get("event_code"))
                        if same_fields.get("event_code")
                        else None
                    ),
                    "event_code": same_fields.get("event_code"),
                    "originator_code": originator_code,
                    "originator_name": get_originator_name(originator_code),
                    "fips_codes": same_fields.get("fips") or [],
                    "issue_time": same_fields.get("issue_time"),
                    "purge_time": _format_purge_minutes(same_fields.get("purge_minutes")),
                    "station": same_fields.get("station"),
                    "identifier": row.same_header,
                    "status": "relayed",
                    "action_taken": "Relayed",
                    "action_reason": None,
                    "details": {
                        "has_audio": bool(row.has_audio_blob or row.audio_filename),
                        "has_text": bool(row.has_text_blob or row.text_filename),
                        "cap_alert_id": row.cap_alert_id,
                    },
                }
            )

        manual_query = (
            ManualEASActivation.query.filter(ManualEASActivation.created_at >= window_start)
            .order_by(ManualEASActivation.created_at.desc())
            .yield_per(STREAM_BATCH)
        )

        for activation in manual_query:
            timestamp = activation.sent_at or activation.created_at
            same_fields = _parse_same_header_fields(activation.same_header)
            originator_code = same_fields.get("originator")
            entries.append(
                {
                    "timestamp": timestamp,
                    "category": "manual",
                    "event_label": activation.event_name,
                    "event_code": activation.event_code or same_fields.get("event_code"),
                    "originator_code": originator_code,
                    "originator_name": get_originator_name(originator_code),
                    "fips_codes": same_fields.get("fips") or [],
                    "issue_time": same_fields.get("issue_time"),
                    "purge_time": _format_purge_minutes(same_fields.get("purge_minutes")),
                    "station": same_fields.get("station"),
                    "identifier": activation.identifier,
                    "status": activation.status,
                    "action_taken": "Initiated",
                    "action_reason": None,
                    "details": {
                        "event_code": activation.event_code,
                        "message_type": activation.message_type,
                        "same_header": activation.same_header,
                    },
                }
            )

        # full_alert_data (JSONB) and raw_audio_data (LargeBinary) are not
        # rendered in the log; deferring them keeps the per-row cost down to
        # the SAME header + a handful of small columns.
        received_query = (
            ReceivedEASAlert.query.options(
                defer(ReceivedEASAlert.full_alert_data),
                defer(ReceivedEASAlert.raw_audio_data),
            )
            .filter(ReceivedEASAlert.received_at >= window_start)
            .order_by(ReceivedEASAlert.received_at.desc())
            .limit(MAX_ENTRIES_PER_CATEGORY)
            .yield_per(STREAM_BATCH)
        )

        for received in received_query:
            same_fields = _parse_same_header_fields(received.raw_same_header)
            originator_code = (
                received.originator_code or same_fields.get("originator")
            )
            originator_name = (
                received.originator_name
                or get_originator_name(originator_code)
            )
            decision = (received.forwarding_decision or "").strip().lower()
            if decision == "forwarded":
                action_taken = "Relayed"
            elif decision == "ignored":
                action_taken = "Not relayed"
            elif decision == "error":
                action_taken = "Decode error"
            else:
                action_taken = "Received"
            entries.append(
                {
                    "timestamp": received.received_at,
                    "category": "off-air",
                    "event_label": received.event_name
                    or get_event_name(received.event_code),
                    "event_code": received.event_code or same_fields.get("event_code"),
                    "originator_code": originator_code,
                    "originator_name": originator_name,
                    "fips_codes": list(received.fips_codes or [])
                    or same_fields.get("fips") or [],
                    "issue_time": received.issue_datetime or same_fields.get("issue_time"),
                    "purge_time": received.purge_datetime
                    or _format_purge_minutes(same_fields.get("purge_minutes")),
                    "station": received.callsign or same_fields.get("station"),
                    "identifier": received.raw_same_header
                    or f"received-eas-{received.id}",
                    "status": received.forwarding_decision or "received",
                    "action_taken": action_taken,
                    "action_reason": (received.forwarding_reason or "").strip() or None,
                    "details": {
                        "source_name": received.source_name,
                        "alert_source": received.alert_source,
                        "decode_confidence": received.decode_confidence,
                        "matched_fips": list(received.matched_fips_codes or []),
                    },
                }
            )
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.error("Failed to collect compliance entries: %s", exc)
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive fallback
            pass

    entries.sort(key=lambda item: item.get("timestamp") or datetime.min, reverse=True)
    return entries, window_start, window_end

def collect_compliance_dashboard_data(
    window_days: int = 30,
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate compliance metrics for dashboard presentation.

    Either supply ``window_days`` for a relative window, or pin the window by
    providing both ``window_start`` and ``window_end`` (explicit bounds win).
    """

    entries, window_start, window_end = collect_compliance_log_entries(
        window_days,
        window_start=window_start,
        window_end=window_end,
    )

    received_total = sum(1 for entry in entries if entry["category"] == "received")
    auto_relay_total = sum(1 for entry in entries if entry["category"] == "relayed")
    manual_relay_total = sum(1 for entry in entries if entry["category"] == "manual")
    relayed_total = auto_relay_total + manual_relay_total

    relay_rate = None
    if received_total:
        relay_rate = (relayed_total / received_total) * 100

    weekly_counts: Dict[datetime, Dict[str, int]] = defaultdict(lambda: {"received": 0, "relayed": 0})

    for entry in entries:
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, datetime):
            continue

        is_test_event = _event_matches_test(entry.get("event_label"))
        details = entry.get("details") or {}
        event_code = str(
            entry.get("event_code") or details.get("event_code") or ""
        ).upper()
        if not is_test_event and event_code not in {"RWT", "RMT"}:
            continue

        week_start = timestamp - timedelta(days=timestamp.weekday())
        week_key = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        category = entry["category"]
        if category == "received":
            weekly_counts[week_key]["received"] += 1
        elif category == "off-air":
            # Off-air ReceivedEASAlert entries can be either received-and-
            # relayed or received-and-ignored; treat them as received unless
            # we actually forwarded them.
            if (entry.get("action_taken") or "").lower() == "relayed":
                weekly_counts[week_key]["relayed"] += 1
            else:
                weekly_counts[week_key]["received"] += 1
        else:
            weekly_counts[week_key]["relayed"] += 1

    weekly_rows = [
        {
            "week_start": key,
            "received": values["received"],
            "relayed": values["relayed"],
            "compliance": (
                (values["relayed"] / values["received"]) * 100
                if values["received"]
                else None
            ),
        }
        for key, values in weekly_counts.items()
    ]
    weekly_rows.sort(key=lambda item: item["week_start"], reverse=True)

    weekly_received_total = sum(row["received"] for row in weekly_rows)
    weekly_relayed_total = sum(row["relayed"] for row in weekly_rows)
    weekly_rate = None
    if weekly_received_total:
        weekly_rate = (weekly_relayed_total / weekly_received_total) * 100

    recent_activity = entries[:25]

    span_seconds = max((window_end - window_start).total_seconds(), 0)
    effective_window_days = max(1, int(round(span_seconds / 86400))) or 1

    return {
        "window_days": effective_window_days,
        "window_start": window_start,
        "window_end": window_end,
        "generated_at": utc_now(),
        "received_vs_relayed": {
            "received": received_total,
            "relayed": relayed_total,
            "auto_relayed": auto_relay_total,
            "manual_relayed": manual_relay_total,
            "relay_rate": relay_rate,
        },
        "weekly_tests": {
            "rows": weekly_rows,
            "received_total": weekly_received_total,
            "relayed_total": weekly_relayed_total,
            "relay_rate": weekly_rate,
        },
        "recent_activity": recent_activity,
        "entries": entries,
    }
