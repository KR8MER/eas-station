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

"""The /alerts PDF export — an archival, text-only rendering of the list.

⚠️ **This applies a strict subset of the page's filters.** Search, status,
severity, event, source and ``show_expired`` are honoured; the date range, the
VTEC event chain and the superseded rule are **not**. So a PDF exported from a
filtered page can contain rows the page itself was hiding.

That divergence is pre-existing and is pinned by
``test_pdf_export_ignores_filters_the_page_supports`` — recorded as current
behaviour, not endorsed. Unifying the two query builders is a behaviour change
and needs its own commit; doing it here would have silently altered what
operators get in a compliance export.
"""

from typing import Any, Dict, List

from app_core.eas_storage import format_local_datetime
from app_core.models import CAPAlert
from app_utils import utc_now
from sqlalchemy import or_

from .filters import TRUTHY
from .query import apply_search

# Hard cap: keeps memory bounded and the PDF a reasonable size (50–500KB).
MAX_EXPORT_ALERTS = 500

# Longer descriptions are truncated; the full text stays on the detail page.
MAX_DESCRIPTION_CHARS = 500


def build_export_query(args):
    """The export's filter set — deliberately narrower than the page's."""
    query = CAPAlert.query
    query = apply_search(query, args.get("search", "").strip())

    # Exact match filters: Apply each filter independently
    # Empty strings are treated as "no filter" (show all)
    for value, column in (
        (args.get("status", "").strip(), CAPAlert.status),
        (args.get("severity", "").strip(), CAPAlert.severity),
        (args.get("event", "").strip(), CAPAlert.event),
        (args.get("source", "").strip(), CAPAlert.source),
    ):
        if value:
            query = query.filter(column == value)

    # Expired alerts filter: By default, exclude expired alerts
    # This matches the default behavior of the /alerts page (see
    # apply_visibility() in query.py for why status.notin_ rather than
    # != "Expired" -- a Cancel/Update can set status='Cancelled' before
    # the original expires time, and that must be excluded here too).
    if str(args.get("show_expired", "")).lower() not in TRUTHY:
        query = query.filter(
            or_(CAPAlert.expires.is_(None), CAPAlert.expires > utc_now())
        ).filter(CAPAlert.status.notin_(("Expired", "Cancelled")))

    return query.order_by(CAPAlert.sent.desc())


def render_alert_blocks(alerts_list) -> List[str]:
    """Each alert as a labelled text block, blank-line separated."""
    lines: List[str] = []
    for alert in alerts_list:
        # Format timestamps with local time + UTC for compliance
        sent_str = format_local_datetime(alert.sent, include_utc=True) if alert.sent else 'Unknown'
        expires_str = (
            format_local_datetime(alert.expires, include_utc=True)
            if alert.expires else 'No expiration'
        )

        block = [
            f"Event: {alert.event}",
            f"Severity: {alert.severity or 'N/A'}",
            f"Status: {alert.status}",
            f"Source: {alert.source or 'Unknown'}",
            f"Sent: {sent_str}",
            f"Expires: {expires_str}",
        ]

        # Optional fields: only included when present.
        if alert.headline:
            block.append(f"Headline: {alert.headline}")
        if alert.area_desc:
            block.append(f"Area: {alert.area_desc}")
        if alert.description:
            description = alert.description
            if len(description) > MAX_DESCRIPTION_CHARS:
                description = description[:MAX_DESCRIPTION_CHARS] + '...'
            block.append(f"Description: {description}")

        lines.extend(block)
        lines.append("")  # Empty line between alerts for readability

    return lines


def build_filter_summary(args) -> str:
    """Human-readable description of the applied filters, for the subtitle."""
    parts = []
    for label, value in (
        ("Search", args.get("search", "").strip()),
        ("Status", args.get("status", "").strip()),
        ("Severity", args.get("severity", "").strip()),
        ("Event", args.get("event", "").strip()),
        ("Source", args.get("source", "").strip()),
    ):
        if value:
            parts.append(f"{label}: {value}")
    if str(args.get("show_expired", "")).lower() not in TRUTHY:
        parts.append("Active alerts only")

    return " | ".join(parts) if parts else "All alerts"


def build_export_sections(alerts_list) -> List[Dict[str, Any]]:
    """The single content section the PDF generator renders."""
    alert_lines = render_alert_blocks(alerts_list)
    return [{
        'heading': f'Alerts Export ({len(alerts_list)} alerts)',
        'content': alert_lines if alert_lines else ['No alerts found'],
    }]


__all__ = [
    "MAX_DESCRIPTION_CHARS",
    "MAX_EXPORT_ALERTS",
    "build_export_query",
    "build_export_sections",
    "build_filter_summary",
    "render_alert_blocks",
]
