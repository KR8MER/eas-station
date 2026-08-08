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

"""FCC-shaped reports rendered inline on /logs.

This is the one category that returns ``report_meta``. Each row is also
mirrored into the generic ``rows`` list so the page's search/level/date filters
and the generic CSV exporter keep working — but the template renders the proper
columnar layout from ``report_meta`` instead of cramming every column into the
generic ``message`` cell (which was unreadable on mobile).

The rich PDF/CSV exports still go through
``/admin/compliance/report/<kind>.<fmt>``, which keeps the report-specific
column layout.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from .common import LogPage, LogQuery

REPORT_PREFIX = 'report_'
REPORT_WINDOW_DAYS = 30

REPORT_TITLES = {
    'received': 'Received Alerts (FCC report)',
    'forwarded': 'Forwarded Alerts (FCC report)',
    'ignored': 'Ignored Alerts (FCC report)',
    'initiated': 'Initiated Alerts (FCC report)',
    'weekly': 'Weekly Summary (FCC report)',
    'monthly': 'Monthly Summary (FCC report)',
}

def _empty_report() -> Dict[str, Any]:
    """What a failing builder degrades to, so the page renders empty not 500.

    A factory rather than a module constant: the caller reads ``rows`` and
    ``columns`` straight off it, and a shared mutable default would be one
    careless ``.append()`` away from leaking between requests.
    """
    return {
        "columns": [],
        "rows": [],
        "summary_lines": [],
        "window_start": None,
        "window_end": None,
    }


def _recover_timestamp(cells: List[str]) -> Optional[datetime]:
    """Best-effort display timestamp from a report row's first column.

    The report builders format timestamps as ``local / ISO UTC`` strings, so
    the ISO portion is recovered where possible and the row simply carries no
    timestamp where it is not.
    """
    if not cells:
        return None
    try:
        # The report builder formats timestamps as
        # local strings — try to recover ISO portion.
        first = cells[0]
        return datetime.fromisoformat(first.split(' / ')[-1].split(' UTC')[0])
    except Exception:
        return None


def load_report(query: LogQuery) -> LogPage:
    """Render ``report_<kind>`` inline, mirroring rows into the generic table."""
    from app_core.eas_storage import REPORT_BUILDERS, resolve_report_window

    report_kind = query.log_type[len(REPORT_PREFIX):]
    builder = REPORT_BUILDERS.get(report_kind)
    if builder is None:
        return LogPage("Unknown report", [], None)

    display_name = REPORT_TITLES.get(report_kind, f"Report: {report_kind}")
    try:
        window_start, window_end = resolve_report_window(days=REPORT_WINDOW_DAYS)
        report = builder(window_start=window_start, window_end=window_end)
    except Exception as exc:
        query.logger.error("report builder %s failed: %s", report_kind, exc)
        # If a query inside the builder raised, the SQLAlchemy
        # session/connection is left in an aborted-transaction
        # state.  Without a rollback every subsequent query on
        # this connection (including the per-request auth
        # permission check) hits InFailedSqlTransaction.
        try:
            from app_core.extensions import db as _db
            _db.session.rollback()
        except Exception:  # pragma: no cover - defensive
            query.logger.exception("rollback after report builder failure failed")
        report = _empty_report()

    column_labels = [c.get("label", "") for c in report.get("columns", [])]
    logs_data: List[Dict[str, Any]] = []
    for row in report.get("rows", [])[:query.limit]:
        cells = [str(c) if c is not None else "" for c in row]
        # Keep a readable fallback ``message`` for search matching
        # and the generic CSV export, but the template prefers
        # ``details`` (label→value) when ``report`` is set.
        pairs = " · ".join(
            f"{label}: {value}" for label, value in zip(column_labels, cells) if value
        )
        logs_data.append({
            'timestamp': _recover_timestamp(cells),
            'level': 'INFO',
            'module': f"report:{report_kind}",
            'message': pairs or " · ".join(cells),
            'alert_identifier': None,
            'details': dict(zip(column_labels, cells)),
        })

    report_meta = {
        'kind': report_kind,
        'title': report.get('title') or display_name,
        'subtitle': report.get('subtitle'),
        'columns': column_labels,
        'summary_lines': list(report.get('summary_lines') or []),
        'window_start': report.get('window_start'),
        'window_end': report.get('window_end'),
        'row_count': report.get('row_count', len(logs_data)),
    }

    return LogPage(display_name, logs_data, report_meta)


__all__ = ["REPORT_PREFIX", "REPORT_TITLES", "REPORT_WINDOW_DAYS", "load_report"]
