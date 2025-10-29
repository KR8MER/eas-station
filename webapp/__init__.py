"""Route scaffolding helpers for the NOAA alerts Flask application."""

from __future__ import annotations

from flask import Flask

from . import routes_admin


def register_routes(app: Flask, logger) -> None:
    """Register all route groups with the provided Flask application."""

    routes_admin.register(app, logger)


__all__ = ["register_routes"]
