"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Routes powering the EAS compliance dashboard and exports."""

from __future__ import annotations

from datetime import timedelta

from flask import Flask, Response, current_app, render_template, request

from app_core.eas_storage import (
    collect_compliance_dashboard_data,
    collect_compliance_log_entries,
    generate_compliance_log_csv,
    generate_compliance_log_pdf,
)
from app_core.system_health import (
    collect_audio_path_status,
    collect_receiver_health_snapshot,
)
from app_utils.time import format_local_datetime, get_location_timezone_name, utc_now


def register(app: Flask, logger) -> None:
    """Register compliance dashboard routes on the Flask application."""

    route_logger = logger.getChild("eas_compliance")

    def _resolve_window_days() -> int:
        value = request.args.get("days", type=int)
        if value is None:
            return 30
        return max(1, min(int(value), 365))

    @app.route("/admin/compliance")
    def compliance_dashboard():
        window_days = _resolve_window_days()

        try:
            dashboard = collect_compliance_dashboard_data(window_days=window_days)
            receiver_snapshot = collect_receiver_health_snapshot(route_logger)
            audio_status = collect_audio_path_status(route_logger)
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Failed to assemble compliance dashboard: %s", exc)
            now = utc_now()
            dashboard = {
                "window_days": window_days,
                "window_start": now - timedelta(days=window_days),
                "window_end": now,
                "generated_at": now,
                "received_vs_relayed": {
                    "received": 0,
                    "relayed": 0,
                    "auto_relayed": 0,
                    "manual_relayed": 0,
                    "relay_rate": None,
                },
                "weekly_tests": {
                    "rows": [],
                    "received_total": 0,
                    "relayed_total": 0,
                    "relay_rate": None,
                },
                "recent_activity": [],
                "entries": [],
            }
            receiver_snapshot = {
                "items": [],
                "total": 0,
                "issues": 0,
                "issue_items": [],
                "threshold_minutes": current_app.config.get(
                    "RECEIVER_OFFLINE_THRESHOLD_MINUTES", 10
                ),
            }
            audio_status = {
                "enabled": False,
                "status": "unknown",
                "output_dir": None,
                "heartbeat_minutes": current_app.config.get(
                    "AUDIO_PATH_ALERT_THRESHOLD_MINUTES", 60
                ),
                "last_activity": None,
                "issues": [
                    "Compliance metrics are temporarily unavailable. Check logs for details.",
                ],
            }

        timezone_name = get_location_timezone_name()

        return render_template(
            "eas/compliance.html",
            dashboard=dashboard,
            receiver_snapshot=receiver_snapshot,
            audio_status=audio_status,
            timezone_name=timezone_name,
            window_days=window_days,
            format_local_datetime=format_local_datetime,
        )

    @app.route("/admin/compliance/export.csv")
    def compliance_export_csv():
        window_days = _resolve_window_days()

        try:
            entries, _, _ = collect_compliance_log_entries(window_days=window_days)
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
    def compliance_export_pdf():
        window_days = _resolve_window_days()

        try:
            entries, window_start, window_end = collect_compliance_log_entries(
                window_days=window_days
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


__all__ = ["register"]
