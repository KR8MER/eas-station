"""Route for the unified per-alert trail view.

Provides ``/alerts/<identifier>/trail`` — a single page that merges every
event keyed to one alert's correlation ID (CAP ingestion, OTA decode,
forwarding decisions, SAME message generation, GPIO activations, audio
broadcast, system log lines, manual activations) into a chronological
timeline.  This is the page the per-row ``Trail`` button on
``/alerts`` and the alert chip on ``/logs`` link to.
"""
from __future__ import annotations

from flask import Flask, abort, render_template, url_for

from app_core.alert_trail import collect_alert_trail
from app_core.auth.decorators import require_auth
from app_utils.time import format_local_datetime, get_location_timezone_name


def register(app: Flask, logger) -> None:
    """Register the trail route on the Flask application."""

    route_logger = logger.getChild("alert_trail")

    # ``<path:identifier>`` allows colons and slashes that appear inside CAP
    # identifiers (e.g. ``urn:oid:...``) without requiring callers to encode
    # them.  The trailing ``/trail`` segment disambiguates from the existing
    # integer-id alert detail route at ``/alerts/<int:alert_id>``.
    @app.route("/alerts/<path:identifier>/trail")
    @require_auth
    def alert_trail(identifier: str):
        if not identifier or len(identifier) > 255:
            abort(404)

        try:
            payload = collect_alert_trail(identifier)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error(
                "Failed to assemble alert trail for %s: %s", identifier, exc,
                exc_info=True,
            )
            abort(500)

        # If nothing at all referenced this identifier, render a friendly
        # not-found state rather than 404'ing — the user followed a link in
        # good faith and "no events recorded yet" is more useful than a
        # generic error page.
        has_any_signal = bool(
            payload["alert"]
            or payload["messages"]
            or payload["manual"]
            or payload["received"]
            or payload["events"]
        )

        return render_template(
            "alerts/trail.html",
            payload=payload,
            identifier=identifier,
            has_any_signal=has_any_signal,
            timezone_name=get_location_timezone_name(),
            format_local_datetime=format_local_datetime,
        )


__all__ = ["register"]
