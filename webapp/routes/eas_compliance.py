"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Routes powering the FCC compliance exports.

The visible /admin/compliance dashboard is sunset — its content lives at
/logs?type=compliance now.  What this module still owns is the export
endpoints that page links to (CSV/PDF compliance log and per-report
CSV/PDF for received / forwarded / ignored / initiated / weekly /
monthly).
"""

from datetime import datetime, timezone

from flask import Flask, Response, request

from app_core.auth.decorators import require_auth, require_role
from app_core.eas_storage import (
    REPORT_BUILDERS,
    collect_compliance_log_entries,
    generate_compliance_log_csv,
    generate_compliance_log_pdf,
    generate_report_csv,
    generate_report_pdf,
    resolve_report_window,
)


def register(app: Flask, logger) -> None:
    """Register compliance dashboard routes on the Flask application."""

    route_logger = logger.getChild("eas_compliance")

    def _resolve_window_days() -> int:
        value = request.args.get("days", type=int)
        if value is None:
            return 30
        return max(1, min(int(value), 365))

    def _parse_query_date(value: str) -> "datetime | None":
        if not value:
            return None
        try:
            if len(value) == 10:
                parsed = datetime.strptime(value, "%Y-%m-%d")
            else:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _resolve_dashboard_window():
        """Return ``(start, end, days)``. Explicit start+end wins over days."""
        start = _parse_query_date(request.args.get("start", type=str) or "")
        end = _parse_query_date(request.args.get("end", type=str) or "")
        if start and end:
            window_start, window_end = resolve_report_window(start=start, end=end)
            span = max((window_end - window_start).total_seconds(), 0)
            days = max(1, int(round(span / 86400))) or 1
            return window_start, window_end, days
        days = _resolve_window_days()
        window_start, window_end = resolve_report_window(days=days)
        return window_start, window_end, days

    @app.route("/admin/compliance")
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def compliance_dashboard():
        # The FCC compliance dashboard has been folded into the unified
        # Logs & Reports hub at /logs?type=compliance, which now shows the
        # relay-performance / weekly-test summary cards above the
        # activity table.  Redirect (302) so existing bookmarks land
        # there.  Export endpoints below (/admin/compliance/export.* and
        # /admin/compliance/report/<kind>.<fmt>) are still served — the
        # Reports tabs on /logs link to them for the rich column-aware
        # exports.
        from flask import redirect
        return redirect("/logs?type=compliance", code=302)

    @app.route("/admin/compliance/export.csv")
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def compliance_export_csv():
        window_start, window_end, window_days = _resolve_dashboard_window()

        try:
            entries, _, _ = collect_compliance_log_entries(
                window_days=window_days,
                window_start=window_start,
                window_end=window_end,
            )
            csv_payload = generate_compliance_log_csv(entries)
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Failed to generate compliance CSV export: %s", exc)
            return Response(
                "Unable to generate compliance export. See logs for details.",
                status=500,
                mimetype="text/plain",
            )

        response = Response(csv_payload, mimetype="text/csv")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=eas_compliance_{window_days}d.csv"
        )
        return response

    @app.route("/admin/compliance/export.pdf")
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def compliance_export_pdf():
        window_start, window_end, window_days = _resolve_dashboard_window()

        try:
            entries, window_start, window_end = collect_compliance_log_entries(
                window_days=window_days,
                window_start=window_start,
                window_end=window_end,
            )
            pdf_payload = generate_compliance_log_pdf(
                entries,
                window_start=window_start,
                window_end=window_end,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Failed to generate compliance PDF export: %s", exc)
            return Response(
                "Unable to generate compliance export. See logs for details.",
                status=500,
                mimetype="text/plain",
            )

        response = Response(pdf_payload, mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=eas_compliance_{window_days}d.pdf"
        )
        return response


    def _resolve_report_window():
        """Pick the report window from start/end query args, or fall back to days."""
        window_start, window_end, _ = _resolve_dashboard_window()
        return window_start, window_end

    def _make_response(report, fmt: str):
        slug = report.get("slug", "report")
        if fmt == "csv":
            payload = generate_report_csv(report)
            response = Response(payload, mimetype="text/csv")
            filename = f"eas_{slug}.csv"
        else:
            payload = generate_report_pdf(report)
            response = Response(payload, mimetype="application/pdf")
            filename = f"eas_{slug}.pdf"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @app.route("/admin/compliance/report/<report_kind>.<fmt>")
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def compliance_report_export(report_kind: str, fmt: str):
        if fmt not in {"pdf", "csv"}:
            return Response("Unsupported format.", status=404, mimetype="text/plain")
        builder = REPORT_BUILDERS.get(report_kind)
        if builder is None:
            return Response("Unknown report.", status=404, mimetype="text/plain")
        try:
            window_start, window_end = _resolve_report_window()
            report = builder(window_start=window_start, window_end=window_end)
            return _make_response(report, fmt)
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error(
                "Failed to generate %s report (%s): %s", report_kind, fmt, exc
            )
            return Response(
                "Unable to generate report. See logs for details.",
                status=500,
                mimetype="text/plain",
            )


__all__ = ["register"]
