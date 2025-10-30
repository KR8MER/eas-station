"""Public monitoring and utility endpoints for the Flask app."""

from __future__ import annotations

from flask import Flask, jsonify
from sqlalchemy import text

from app_core.extensions import db
from app_core.models import RadioReceiver
from app_core.radio import ensure_radio_tables
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

            try:
                ensure_radio_tables(route_logger)
                receiver_total = RadioReceiver.query.count()
            except Exception as radio_exc:  # pragma: no cover - defensive
                route_logger.debug("Radio table check failed: %s", radio_exc)
                receiver_total = None

            return jsonify(
                {
                    "status": "healthy",
                    "timestamp": utc_now().isoformat(),
                    "local_timestamp": local_now().isoformat(),
                    "version": _system_version(),
                    "database": "connected",
                    "led_available": LED_AVAILABLE,
                    "radio_receivers": receiver_total,
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

    @app.route("/api/monitoring/radio")
    def monitoring_radio():
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("Radio table validation failed: %s", exc)

        receivers = (
            RadioReceiver.query.order_by(RadioReceiver.display_name, RadioReceiver.identifier).all()
        )

        payload = []
        for receiver in receivers:
            latest = receiver.latest_status()
            payload.append(
                {
                    "id": receiver.id,
                    "identifier": receiver.identifier,
                    "display_name": receiver.display_name,
                    "driver": receiver.driver,
                    "frequency_hz": receiver.frequency_hz,
                    "sample_rate": receiver.sample_rate,
                    "gain": receiver.gain,
                    "channel": receiver.channel,
                    "auto_start": receiver.auto_start,
                    "enabled": receiver.enabled,
                    "notes": receiver.notes,
                    "latest_status": (
                        {
                            "reported_at": latest.reported_at.isoformat() if latest and latest.reported_at else None,
                            "locked": bool(latest.locked) if latest else None,
                            "signal_strength": latest.signal_strength if latest else None,
                            "last_error": latest.last_error if latest else None,
                            "capture_mode": latest.capture_mode if latest else None,
                            "capture_path": latest.capture_path if latest else None,
                        }
                        if latest
                        else None
                    ),
                }
            )

        return jsonify({"receivers": payload, "count": len(payload)})


__all__ = ["register"]
