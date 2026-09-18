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

"""Rendering report payloads to CSV/PDF, and the report-kind dispatch table."""

import csv
import io
from typing import Any, Dict

from .reports_received_initiated import build_initiated_alerts_report, build_received_alerts_report
from .reports_summary import build_monthly_summary_report, build_weekly_summary_report


REPORT_BUILDERS = {
    "received": lambda **kw: build_received_alerts_report(decision="received", **kw),
    "forwarded": lambda **kw: build_received_alerts_report(decision="forwarded", **kw),
    "ignored": lambda **kw: build_received_alerts_report(decision="ignored", **kw),
    "initiated": build_initiated_alerts_report,
    "weekly": build_weekly_summary_report,
    "monthly": build_monthly_summary_report,
}

def generate_report_csv(report: Dict[str, Any]) -> str:
    """Render a report payload as CSV (header row + data + summary block)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([col.get("label", "") for col in report.get("columns", [])])
    for row in report.get("rows", []):
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    summary_lines = report.get("summary_lines") or []
    if summary_lines:
        writer.writerow([])
        writer.writerow(["Summary"])
        for line in summary_lines:
            writer.writerow([line])
    return output.getvalue()

def generate_report_pdf(report: Dict[str, Any]) -> bytes:
    """Render a report payload as a paginated landscape PDF."""
    from app_utils.pdf_generator import generate_table_pdf

    return generate_table_pdf(
        report.get("title", "Compliance Report"),
        report.get("columns", []),
        report.get("rows", []),
        subtitle=report.get("subtitle"),
        summary_lines=report.get("summary_lines"),
        landscape=True,
    )
