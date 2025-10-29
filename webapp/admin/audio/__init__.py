"""Audio archive and manual EAS route registration."""

from __future__ import annotations

from typing import Any

from flask import Flask


def register_audio_routes(app: Flask, logger: Any, eas_config: dict[str, Any]) -> None:
    """Register all audio-related routes on the Flask application."""
    from .history import register_history_routes
    from .detail import register_detail_routes
    from .files import register_file_routes
    from .messages import register_message_admin_routes
    from .manual import register_manual_routes

    register_history_routes(app, logger)
    register_detail_routes(app, logger)
    register_file_routes(app, logger)
    register_message_admin_routes(app, logger)
    register_manual_routes(app, logger, eas_config)


__all__ = ["register_audio_routes"]
