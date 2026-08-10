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

"""``/admin/alert-verification/export.csv`` — the CSV export."""

from flask import Flask, Response

from app_core.auth.decorators import require_auth, require_role
from app_core.eas_storage import collect_alert_delivery_records
from app_utils.export import generate_csv

from .helpers import _resolve_window_days, _serialize_csv_rows


def register(app: Flask, logger):
    """Attach this module's routes, recreating register's closure.

    ``route_logger`` is rebuilt here rather than passed in, so each
    handler closes over exactly what it closed over in the single-file
    module.
    """
    route_logger = logger.getChild('alert_verification')

    @app.route("/admin/alert-verification/export.csv")
    @require_auth
    @require_role("Admin", "Operator", "Analyst")
    def alert_verification_export():
        window_days = _resolve_window_days()

        try:
            payload = collect_alert_delivery_records(window_days=window_days)
        except Exception as exc:  # pragma: no cover - defensive fallback
            route_logger.error("Failed to generate alert verification export: %s", exc)
            return Response(
                "Unable to generate alert verification export. See logs for details.",
                status=500,
                mimetype="text/plain",
            )

        rows = list(_serialize_csv_rows(payload["records"]))
        csv_payload = generate_csv(
            rows,
            fieldnames=[
                "cap_identifier",
                "event",
                "sent_utc",
                "source",
                "delivery_status",
                "average_latency_seconds",
                "targets",
                "issues",
            ],
        )

        response = Response(csv_payload, mimetype="text/csv")
        response.headers["Content-Disposition"] = (
            f"attachment; filename=alert_verification_{window_days}d.csv"
        )
        return response
