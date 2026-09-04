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

"""API Dashboard routes: live request volume, latency and error rate for
every /api/* route, built from the same WebRequestLog rows the Traffic
Analytics dashboard records (see app_core/analytics/api_stats.py)."""

from typing import Any, Dict

from flask import Flask, current_app, jsonify, render_template, request

from app_core.analytics import api_stats
from app_core.analytics.traffic_filters import TrafficFilters
from app_core.auth import require_permission
from app_core.extensions import db
from app_utils.api_reference import compute_api_reference

_GENERIC_ERROR = "An internal error occurred. Check the server logs for details."

# Bounds so a crafted ?days= can't ask for an unbounded scan.
_MIN_DAYS = 1
_MAX_DAYS = 365


def _clamp_days(default: int = 7) -> int:
    try:
        days = int(request.args.get("days", default))
    except (TypeError, ValueError):
        return default
    return max(_MIN_DAYS, min(days, _MAX_DAYS))


def register(app: Flask, logger) -> None:
    """Attach API Dashboard routes to the Flask app."""

    route_logger = logger.getChild("routes_api_dashboard")

    @app.route("/api-dashboard")
    @require_permission("logs.view")
    def api_dashboard_page():
        """Display the live API Dashboard page."""
        return render_template("api_dashboard.html")

    @app.route("/api/dashboard/api-stats", methods=["GET"])
    @require_permission("logs.view")
    def api_dashboard_data():
        """Return the full API Dashboard payload.

        Query:
            days (int, optional): trailing-window size in days. Default 7,
                clamped to [1, 365].

        Returns:
            200 with {success, days, summary, by_route, timeseries, slowest,
            top_errors, generated_at}.
        """
        try:
            days = _clamp_days()
            flt = TrafficFilters(days=days)

            catalog = compute_api_reference(current_app)
            routes_by_endpoint: Dict[str, Any] = {
                entry["endpoint"]: entry
                for group_entries in catalog["groups"].values()
                for entry in group_entries
            }

            by_route = api_stats.get_api_by_route(filters=flt)
            for row in by_route:
                meta = routes_by_endpoint.get(row["endpoint"])
                if meta:
                    row["path"] = meta["path"]
                    row["methods"] = meta["methods"]
                    row["group"] = meta["group"]
                    row["summary"] = meta["summary"]
                    row["auth"] = meta["auth"]
                else:
                    row["path"] = None
                    row["methods"] = []
                    row["group"] = "Unmapped"
                    row["summary"] = ""
                    row["auth"] = None

            return jsonify({
                "success": True,
                "days": days,
                "summary": api_stats.get_api_summary(filters=flt),
                "by_route": by_route,
                "timeseries": api_stats.get_api_timeseries(filters=flt),
                "slowest": api_stats.get_api_slowest_routes(filters=flt),
                "top_errors": api_stats.get_api_top_errors(filters=flt),
                "generated_at": catalog["generated_at"],
            })
        except Exception as exc:
            route_logger.error(f"Failed to build API dashboard: {exc}")
            db.session.rollback()
            return jsonify({"success": False, "error": _GENERIC_ERROR}), 500
