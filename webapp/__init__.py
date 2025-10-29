"""Route scaffolding helpers for the NOAA alerts Flask application."""

from __future__ import annotations

from flask import Flask

from . import routes_admin, routes_exports, routes_led, routes_public, template_helpers


def register_routes(app: Flask, logger) -> None:
    """Register all route groups with the provided Flask application."""

    template_helpers.register(app)
    routes_public.register(app, logger)
    routes_exports.register(app, logger)
    routes_led.register(app, logger)
    routes_admin.register(app, logger)


__all__ = ["register_routes"]
