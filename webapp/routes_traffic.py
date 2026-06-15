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

"""Web-traffic analytics routes (webalizer/awstats-style dashboard).

Exposes the Traffic Analytics page plus JSON endpoints that aggregate the
``web_request_logs`` table (and login activity from the audit log) into the
charts and tables the dashboard renders. Collection settings are read/written
here so the whole feature is configurable from the web UI.
"""

from typing import Any, Dict

from flask import Flask, jsonify, render_template, request, session

from app_core.analytics import traffic_stats
from app_core.analytics.web_traffic import TrafficAnalyticsSettings
from app_core.auth import require_permission
from app_core.extensions import db

# Bounds so a crafted ?days= can't ask for an unbounded scan.
_MIN_DAYS = 1
_MAX_DAYS = 365


def _clamp_days(default: int = 30) -> int:
    try:
        days = int(request.args.get("days", default))
    except (TypeError, ValueError):
        return default
    return max(_MIN_DAYS, min(days, _MAX_DAYS))


def register(app: Flask, logger) -> None:
    """Attach traffic-analytics routes to the Flask app."""

    route_logger = logger.getChild("routes_traffic")

    # ------------------------------------------------------------------ UI
    @app.route("/traffic")
    @require_permission("logs.view")
    def traffic_dashboard_page():
        """Render the Traffic Analytics dashboard."""
        return render_template("traffic_dashboard.html")

    # ------------------------------------------------------------------ data
    @app.route("/api/traffic/dashboard", methods=["GET"])
    @require_permission("logs.view")
    def traffic_dashboard_data():
        """Return the full dashboard payload for a given window (?days=)."""
        try:
            days = _clamp_days()
            data = traffic_stats.get_full_dashboard(days)
            return jsonify({"success": True, "days": days, **data})
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Failed to build traffic dashboard: %s", exc)
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/traffic/recent", methods=["GET"])
    @require_permission("logs.view")
    def traffic_recent_requests():
        """Return the most recent recorded requests."""
        try:
            try:
                limit = int(request.args.get("limit", 50))
            except (TypeError, ValueError):
                limit = 50
            limit = max(1, min(limit, 500))
            return jsonify(
                {"success": True, "requests": traffic_stats.get_recent_requests(limit)}
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Failed to load recent requests: %s", exc)
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    # ------------------------------------------------------------------ beacon
    @app.route("/api/traffic/client", methods=["GET"])
    def traffic_client_beacon():
        """Record client-only attributes (screen resolution) in the session.

        Screen resolution isn't available in HTTP headers, so a tiny script on
        every page reports it here once per browser session. The value is stashed
        in the session cookie and rides along on subsequent requests, where
        ``_record_traffic`` persists it. Public + GET so every visitor (even
        unauthenticated) contributes, and to avoid CSRF friction for a harmless,
        non-sensitive value.
        """
        try:
            width = request.args.get("w", type=int)
            height = request.args.get("h", type=int)
            if width and height and 0 < width <= 20000 and 0 < height <= 20000:
                session["client_screen"] = f"{width}x{height}"
            return jsonify({"success": True})
        except Exception:  # pragma: no cover - beacon must never error loudly
            return jsonify({"success": False}), 200

    # ------------------------------------------------------------------ settings
    @app.route("/api/traffic/settings", methods=["GET"])
    @require_permission("logs.view")
    def traffic_get_settings():
        """Return the current traffic-collection settings."""
        try:
            settings = TrafficAnalyticsSettings.get_settings()
            return jsonify({"success": True, "settings": settings.to_dict()})
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Failed to load traffic settings: %s", exc)
            db.session.rollback()
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/traffic/settings", methods=["POST"])
    @require_permission("system.configure")
    def traffic_update_settings():
        """Persist updated traffic-collection settings."""
        try:
            payload: Dict[str, Any] = request.get_json(silent=True) or {}
            settings = TrafficAnalyticsSettings.get_settings()

            if "enabled" in payload:
                settings.enabled = _to_bool(payload["enabled"])
            if "log_api_requests" in payload:
                settings.log_api_requests = _to_bool(payload["log_api_requests"])
            if "log_authenticated_only" in payload:
                settings.log_authenticated_only = _to_bool(payload["log_authenticated_only"])
            if "exclude_bots" in payload:
                settings.exclude_bots = _to_bool(payload["exclude_bots"])
            if "retention_days" in payload:
                try:
                    retention = int(payload["retention_days"])
                except (TypeError, ValueError):
                    return jsonify(
                        {"success": False, "error": "retention_days must be a number"}
                    ), 400
                settings.retention_days = max(1, min(retention, 3650))
            if "geoip_database_path" in payload:
                raw_path = payload.get("geoip_database_path")
                new_path = (raw_path or "").strip()[:512] or None
                if new_path != settings.geoip_database_path:
                    # Drop cached readers so the new database is picked up.
                    from app_core.analytics.geo import reset_readers

                    reset_readers()
                settings.geoip_database_path = new_path

            db.session.commit()
            route_logger.info("Traffic analytics settings updated")
            return jsonify({"success": True, "settings": settings.to_dict()})
        except Exception as exc:  # pragma: no cover - defensive
            db.session.rollback()
            route_logger.error("Failed to update traffic settings: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500


def _to_bool(value: Any) -> bool:
    """Coerce assorted truthy representations (JSON bool, "true", 1) to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False
