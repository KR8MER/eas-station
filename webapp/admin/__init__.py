"""Organised registration helpers for legacy admin routes."""

from __future__ import annotations

from app_utils.eas import load_eas_config

from .audio import register_audio_routes
from .api import register_api_routes
from .auth import register_auth_routes
from .boundaries import register_boundary_routes
from .coverage import calculate_coverage_percentages
from .dashboard import register_dashboard_routes
from .intersections import register_intersection_routes
from .maintenance import register_maintenance_routes


def register(app, logger):
    """Register all admin-related routes on the Flask app."""

    eas_config = load_eas_config(app.root_path)

    register_audio_routes(app, logger, eas_config)
    register_api_routes(app, logger)
    register_maintenance_routes(app, logger)
    register_intersection_routes(app, logger)
    register_boundary_routes(app, logger)
    register_auth_routes(app, logger)
    register_dashboard_routes(app, logger, eas_config)


__all__ = ['register', 'calculate_coverage_percentages']
