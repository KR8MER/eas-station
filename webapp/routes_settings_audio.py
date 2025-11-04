from __future__ import annotations

from typing import Any

from flask import Flask, render_template

from app_core.location import get_location_settings


def register(app: Flask, logger) -> None:
    """Register audio settings routes"""
    route_logger = logger.getChild("routes_settings_audio")

    @app.route("/settings/audio")
    def audio_settings() -> Any:
        """Render the audio sources management page"""
        try:
            location_settings = get_location_settings()

            return render_template(
                "settings/audio.html",
                location_settings=location_settings,
            )
        except Exception as exc:
            route_logger.error("Error rendering audio settings page: %s", exc)
            return render_template(
                "settings/audio.html",
                location_settings=None,
            )


__all__ = ["register"]
