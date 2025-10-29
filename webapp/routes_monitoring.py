"""Public monitoring and utility endpoints for the Flask app."""

from __future__ import annotations

from flask import Flask, jsonify
from sqlalchemy import text

from app_core.extensions import db
from app_core.led import LED_AVAILABLE
from app_core.location import get_location_settings
from app_utils import get_location_timezone_name, local_now, utc_now


def register(app: Flask, logger) -> None:
    """Attach monitoring and utility routes to the Flask app."""

    route_logger = logger.getChild("routes_monitoring")

    def _system_version() -> str:
        return str(app.config.get("SYSTEM_VERSION", "unknown"))

    @app.route("/health")
    def health_check():
        """Simple health check endpoint."""

        try:
            db.session.execute(text("SELECT 1")).fetchone()

            return jsonify(
                {
                    "status": "healthy",
                    "timestamp": utc_now().isoformat(),
                    "local_timestamp": local_now().isoformat(),
                    "version": _system_version(),
                    "database": "connected",
                    "led_available": LED_AVAILABLE,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Health check failed: %s", exc)
            return (
                jsonify(
                    {
                        "status": "unhealthy",
                        "error": str(exc),
                        "timestamp": utc_now().isoformat(),
                        "local_timestamp": local_now().isoformat(),
                    }
                ),
                500,
            )

    @app.route("/ping")
    def ping():
        """Simple ping endpoint."""

        return jsonify(
            {
                "pong": True,
                "timestamp": utc_now().isoformat(),
                "local_timestamp": local_now().isoformat(),
            }
        )

    @app.route("/version")
    def version():
        """Version information endpoint."""

        location = get_location_settings()
        return jsonify(
            {
                "version": _system_version(),
                "name": "NOAA CAP Alerts System",
                "author": "KR8MER Amateur Radio Emergency Communications",
                "description": (
                    f"Emergency alert system for {location['county_name']}, "
                    f"{location['state_code']}"
                ),
                "timezone": get_location_timezone_name(),
                "led_available": LED_AVAILABLE,
                "timestamp": utc_now().isoformat(),
                "local_timestamp": local_now().isoformat(),
            }
        )

    @app.route("/favicon.ico")
    def favicon():
        """Serve favicon."""

        return "", 204

    @app.route("/robots.txt")
    def robots():
        """Robots.txt for web crawlers."""

        return (
            """User-agent: *
Disallow: /admin/
Disallow: /api/
Disallow: /debug/
Allow: /
""",
            200,
            {"Content-Type": "text/plain"},
        )


__all__ = ["register"]
