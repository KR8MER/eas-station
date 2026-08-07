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

"""The /logs hub routes and its CSV/PDF exports."""

from app_core.config import get_all_log_services
from app_core.eas_storage import format_local_datetime
from app_core.extensions import db
from app_utils.pdf_generator import generate_pdf_document
from flask import render_template, request, Response
from typing import List


def register(app, route_logger, _load_logs_data) -> None:
    """Attach the logs routes to the Flask app."""
    @app.route("/logs")
    def logs():
        """Comprehensive log viewer with filtering by log type."""
        try:
            log_type = request.args.get('type', 'all')  # Default to 'all' to show everything
            limit = min(int(request.args.get('limit', 100)), 500)  # Max 500 records

            # Get filter parameters
            search_query = request.args.get('search', '').strip()
            log_level_filter = request.args.get('level', '').strip().upper()
            date_from = request.args.get('date_from', '').strip()
            date_to = request.args.get('date_to', '').strip()
            service_filter = request.args.get('service', '').strip()
            alert_filter = request.args.get('alert', '').strip()
            action_filter = request.args.get('action', '').strip()

            log_type_name, logs_data, report_meta = _load_logs_data(
                log_type, limit, service_filter, action_filter
            )

            # Apply filters
            if search_query:
                logs_data = [
                    log for log in logs_data
                    if (search_query.lower() in log.get('message', '').lower() or
                        search_query.lower() in log.get('module', '').lower() or
                        search_query.lower() in str(log.get('details', '')).lower())
                ]

            if alert_filter:
                # Exact match on the correlation ID; clicking a chip in the UI
                # passes the full identifier so substring matching would be
                # surprising (different alerts can share a prefix).
                logs_data = [
                    log for log in logs_data
                    if (log.get('alert_identifier') or '') == alert_filter
                ]

            if log_level_filter:
                logs_data = [
                    log for log in logs_data
                    if log.get('level', '').upper() == log_level_filter
                ]

            if date_from:
                try:
                    from datetime import datetime
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')

                    def check_date_from(log):
                        ts = log.get('timestamp')
                        if not ts:
                            return False
                        # Strip timezone for comparison
                        if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                            ts = ts.replace(tzinfo=None)
                        return ts >= date_from_obj

                    logs_data = [log for log in logs_data if check_date_from(log)]
                except ValueError:
                    pass

            if date_to:
                try:
                    from datetime import datetime, timedelta
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)

                    def check_date_to(log):
                        ts = log.get('timestamp')
                        if not ts:
                            return False
                        # Strip timezone for comparison
                        if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                            ts = ts.replace(tzinfo=None)
                        return ts < date_to_obj

                    logs_data = [log for log in logs_data if check_date_to(log)]
                except ValueError:
                    pass

            # Compliance tab shows a summary banner with the cards that used
            # to live on /admin/compliance (Relay Performance, Weekly Test
            # Coverage).  Compute on demand only — keeps the page fast for
            # every other tab.
            compliance_summary = None
            if log_type == 'compliance':
                try:
                    from app_core.eas_storage import collect_compliance_dashboard_data
                    compliance_summary = collect_compliance_dashboard_data(window_days=30)
                except Exception as exc:
                    route_logger.warning("compliance summary unavailable: %s", exc)
                    compliance_summary = None

            return render_template(
                "logs.html",
                logs=logs_data,
                log_type=log_type,
                limit=limit,
                log_type_name=log_type_name,
                search_query=search_query,
                log_level_filter=log_level_filter,
                date_from=date_from,
                date_to=date_to,
                service_filter=service_filter,
                alert_filter=alert_filter,
                action_filter=action_filter,
                available_services=get_all_log_services(),
                compliance_summary=compliance_summary,
                report=report_meta,
            )

        except Exception as exc:  # pragma: no cover - fallback content
            db.session.rollback()
            route_logger.error("Error loading logs: %s", exc)
            return (
                "<h1>Error loading logs</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/logs/export.csv")
    def logs_export_csv():
        """Export logs as CSV file."""
        try:
            import csv
            import io
            from datetime import datetime

            log_type = request.args.get('type', 'system')
            limit = min(int(request.args.get('limit', 100)), 500)
            action_filter = request.args.get('action', '').strip()

            log_type_name, logs_data, _report_meta = _load_logs_data(
                log_type, limit, action_filter=action_filter
            )

            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow(['Timestamp', 'Level', 'Module', 'Message', 'Details'])

            # Write data
            for log_entry in logs_data:
                timestamp_str = format_local_datetime(
                    log_entry.get('timestamp'), include_utc=True
                ) if log_entry.get('timestamp') else 'N/A'
                level = log_entry.get('level', 'INFO')
                module = log_entry.get('module', 'System')
                message = log_entry.get('message', '')
                details = str(log_entry.get('details', ''))

                writer.writerow([timestamp_str, level, module, message, details])

            # Create response
            csv_data = output.getvalue()
            output.close()

            response = Response(csv_data, mimetype="text/csv")
            response.headers["Content-Disposition"] = (
                f"attachment; filename=logs_{log_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            return response

        except Exception as exc:
            db.session.rollback()
            route_logger.error('Error generating logs CSV: %s', exc)
            return (
                "<h1>Error generating CSV</h1>"
                f"<p>{exc}</p><p><a href='/logs'>← Back to Logs</a></p>"
            )

    @app.route("/logs/export.pdf")
    def logs_export_pdf():
        """Export system logs as PDF - server-side from database."""
        try:
            log_type = request.args.get('type', 'system')
            limit = min(int(request.args.get('limit', 100)), 500)
            action_filter = request.args.get('action', '').strip()

            from datetime import datetime

            log_type_name, logs_data, _report_meta = _load_logs_data(
                log_type, limit, action_filter=action_filter
            )

            sections = []

            log_lines: List[str] = []
            for log_entry in logs_data:
                timestamp_str = format_local_datetime(
                    log_entry.get('timestamp'), include_utc=True
                )
                level = log_entry.get('level', 'INFO')
                module = log_entry.get('module', 'System')
                message = log_entry.get('message', '')
                log_lines.append(f"[{timestamp_str}] [{level}] {module}: {message}")

            if not log_lines:
                log_lines.append('No log entries found')

            heading_name = log_type_name or 'Logs'
            sections.append(
                {
                    'heading': f"{heading_name} (Last {len(logs_data)} entries)",
                    'content': log_lines,
                }
            )

            pdf_bytes = generate_pdf_document(
                title=f"{heading_name} Export",
                sections=sections,
                subtitle=f"Showing last {limit} entries",
                footer_text="Generated by EAS Station™ — Emergency Alert System Platform",
            )

            response = Response(pdf_bytes, mimetype="application/pdf")
            response.headers["Content-Disposition"] = (
                f"inline; filename=logs_{log_type}_{datetime.now().strftime('%Y%m%d')}.pdf"
            )
            return response

        except Exception as exc:
            db.session.rollback()
            route_logger.error('Error generating logs PDF: %s', exc)
            return (
                "<h1>Error generating PDF</h1>"
                f"<p>{exc}</p><p><a href='/logs'>← Back to Logs</a></p>"
            )


__all__ = ["register"]
