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

"""Rendering FCC compliance-log entries to CSV and PDF."""

import csv
import io
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app_utils.optimized_parsing import json_dumps
from app_utils.time import format_local_datetime


_FCC_LOG_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("Timestamp (local)", "_timestamp"),
    ("Category", "category"),
    ("Originator", "_originator"),
    ("Event Code", "event_code"),
    ("Event", "event_label"),
    ("FIPS Codes", "_fips"),
    ("Issue Time", "_issue"),
    ("Purge / Expires", "_purge"),
    ("Station ID", "station"),
    ("Identifier", "identifier"),
    ("Status", "status"),
    ("Action Taken", "action_taken"),
    ("Action Reason", "action_reason"),
    ("Details", "_details_json"),
)

def _format_compliance_originator(entry: Dict[str, Any]) -> str:
    """Render the originator code (and name when known) for a log entry."""
    code = (entry.get("originator_code") or "").strip().upper() or None
    name = (entry.get("originator_name") or "").strip() or None
    if code and name and name.lower() != code.lower():
        return f"{code} ({name})"
    if code:
        return code
    if name:
        return name
    return ""

def _format_compliance_fips(entry: Dict[str, Any], *, limit: int = 12) -> str:
    """Render FIPS codes as comma-separated PSSCCC values with an overflow tag.

    The renderer wraps to multiple lines, so we can list far more codes than
    a single-line cell would allow; ``limit`` only kicks in on pathological
    statewide alerts.
    """
    codes = entry.get("fips_codes") or []
    if not codes:
        return ""
    formatted = list(codes)[:limit]
    suffix = "" if len(codes) <= limit else f", +{len(codes) - limit} more"
    return ", ".join(formatted) + suffix

def _format_compliance_issue(entry: Dict[str, Any]) -> str:
    """Render the SAME issue time (datetime or JJJHHMM string) for the log."""
    value = entry.get("issue_time")
    if isinstance(value, datetime):
        return format_local_datetime(value, include_utc=True)
    return str(value or "")

def _format_compliance_purge(entry: Dict[str, Any]) -> str:
    """Render the SAME purge time (datetime, duration string, or empty)."""
    value = entry.get("purge_time")
    if isinstance(value, datetime):
        return format_local_datetime(value, include_utc=True)
    return str(value or "")

def generate_compliance_log_csv(entries: Sequence[Dict[str, Any]]) -> str:
    """Generate a CSV export for compliance log entries.

    The column layout mirrors the FCC Part 11 logging requirements
    (§§ 11.35(a), 11.54(a)(3)): originator, event code, location codes,
    issue/purge times, station identifier, and the action taken plus reason.
    """

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([label for label, _ in _FCC_LOG_COLUMNS])

    for entry in entries:
        details = entry.get("details") or {}
        details_json = json_dumps(details, ensure_ascii=False, sort_keys=True)
        derived = {
            "_timestamp": format_local_datetime(
                entry.get("timestamp"), include_utc=True
            ),
            "_originator": _format_compliance_originator(entry),
            "_fips": ", ".join(entry.get("fips_codes") or []),
            "_issue": _format_compliance_issue(entry),
            "_purge": _format_compliance_purge(entry),
            "_details_json": details_json,
        }
        writer.writerow(
            [
                derived.get(key, entry.get(key) if key != "_timestamp" else "")
                if key.startswith("_")
                else (entry.get(key) or "")
                for _, key in _FCC_LOG_COLUMNS
            ]
        )

    return output.getvalue()

_COMPLIANCE_CATEGORY_LABELS: Dict[str, str] = {
    "manual": "Manual",
    "received": "Received",
    "relayed": "Relayed",
    "off-air": "Off-Air",
}

def _format_compliance_details(entry: Dict[str, Any]) -> str:
    """Render the per-entry FCC fields + supplementary details for the PDF.

    The Part 11-required identity fields (originator/event/FIPS/etc.) get
    their own table columns; this string fills the remaining "Details"
    column with the Part 11 fields that didn't get a dedicated column
    (Station ID, Issue Time, Purge Time) plus category-specific extras.
    """
    parts: List[str] = []

    # Station ID has its own table column; do not duplicate it here.
    issue = _format_compliance_issue(entry)
    if issue:
        parts.append(f"Issued: {issue}")
    purge = _format_compliance_purge(entry)
    if purge:
        parts.append(f"Purge: {purge}")
    reason = (entry.get("action_reason") or "").strip()
    if reason:
        parts.append(f"Reason: {reason}")

    details = entry.get("details") or {}
    if isinstance(details, dict):
        cat = (entry.get("category") or "").lower()
        if cat == "received":
            for key in ("severity", "urgency", "certainty"):
                value = details.get(key)
                if value:
                    parts.append(f"{key.title()}: {value}")
        elif cat == "relayed":
            media: List[str] = []
            if details.get("has_audio"):
                media.append("audio")
            if details.get("has_text"):
                media.append("text")
            if media:
                parts.append("Media: " + ", ".join(media))
        elif cat == "off-air":
            src = details.get("source_name") or details.get("alert_source")
            if src:
                parts.append(f"Monitored: {src}")
            confidence = details.get("decode_confidence")
            if isinstance(confidence, (int, float)):
                parts.append(f"Decode: {confidence:.0%}")

    return "; ".join(parts)

def generate_compliance_log_pdf(
    entries: Sequence[Dict[str, Any]],
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> bytes:
    """Generate a paginated PDF summary for compliance log entries."""
    from app_utils.pdf_generator import generate_table_pdf

    if window_start and window_end:
        subtitle = (
            f"Window: {format_local_datetime(window_start, include_utc=False)} "
            f"to {format_local_datetime(window_end, include_utc=False)}"
        )
    else:
        subtitle = None

    # Column layout follows the FCC Part 11 log fields: timestamp, originator
    # (ORG), event code (EEE), location codes (PSSCCC), station identifier
    # (LLLLLLLL — exactly 8 chars per § 11.31), action taken plus the event
    # description and supplemental Details.  Cells wrap to multiple lines
    # (see pdf_generator._wrap_to_width), so weights set the wrap width.
    columns = [
        {"label": "Timestamp (local / UTC)", "weight": 1.3},
        {"label": "Category", "weight": 0.6},
        {"label": "Originator (ORG)", "weight": 1.1},
        {"label": "Event Code", "weight": 0.55},
        {"label": "Event", "weight": 1.5},
        {"label": "FIPS (PSSCCC)", "weight": 1.3},
        {"label": "Station ID (LLLLLLLL)", "weight": 0.9},
        {"label": "Action", "weight": 0.8},
        {"label": "Identifier", "weight": 1.9},
        {"label": "Details", "weight": 2.3},
    ]

    rows: List[List[str]] = []
    category_counts: Dict[str, int] = {}
    originator_counts: Dict[str, int] = {}
    action_counts: Dict[str, int] = {}

    for entry in entries:
        category_raw = (entry.get("category") or "").lower()
        category_label = _COMPLIANCE_CATEGORY_LABELS.get(
            category_raw, category_raw.title() if category_raw else ""
        )
        originator_cell = _format_compliance_originator(entry)
        event_code = (entry.get("event_code") or "").upper()
        action_label = (entry.get("action_taken") or "").strip()
        station_cell = (entry.get("station") or "").strip()

        rows.append([
            format_local_datetime(entry.get("timestamp"), include_utc=True),
            category_label,
            originator_cell,
            event_code,
            str(entry.get("event_label") or ""),
            _format_compliance_fips(entry),
            station_cell,
            action_label,
            str(entry.get("identifier") or ""),
            _format_compliance_details(entry),
        ])

        if category_label:
            category_counts[category_label] = category_counts.get(category_label, 0) + 1
        org_key = (entry.get("originator_code") or "—").upper()
        originator_counts[org_key] = originator_counts.get(org_key, 0) + 1
        if action_label:
            action_counts[action_label] = action_counts.get(action_label, 0) + 1

    summary_lines: List[str] = [f"Total entries: {len(rows)}"]
    if category_counts:
        summary_lines.append(
            "By category: "
            + ", ".join(
                f"{label} ({count})"
                for label, count in sorted(category_counts.items())
            )
        )
    if originator_counts:
        summary_lines.append(
            "By originator (ORG): "
            + ", ".join(
                f"{label} ({count})"
                for label, count in sorted(originator_counts.items())
            )
        )
    if action_counts:
        summary_lines.append(
            "By action: "
            + ", ".join(
                f"{label} ({count})"
                for label, count in sorted(action_counts.items())
            )
        )
    summary_lines.append(
        "Per 47 CFR §§ 11.35(a) and 11.54(a)(3): each entry records the "
        "originator (ORG), event code (EEE), location codes (PSSCCC), "
        "station identifier (LLLLLLLL), issue and purge times, and the "
        "action taken."
    )

    return generate_table_pdf(
        "EAS Part 11 Compliance Log",
        columns,
        rows,
        subtitle=subtitle,
        summary_lines=summary_lines,
        footer_text="EAS Station™ — FCC Part 11 Compliance Log",
        landscape=True,
        empty_message="No compliance activity recorded during this window.",
    )
