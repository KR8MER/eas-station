"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Organised registration helpers for legacy admin routes."""

from __future__ import annotations

from app_utils.eas import load_eas_config

from .audio import register_audio_routes
from .audio_ingest import register_audio_ingest_routes
from .api import register_api_routes
from .auth import register_auth_routes
from .boundaries import register_boundary_routes
from .coverage import calculate_coverage_percentages
from .dashboard import register_dashboard_routes
from .environment import register_environment_routes
from .intersections import register_intersection_routes
from .maintenance import register_maintenance_routes


def register(app, logger):
    """Register all admin-related routes on the Flask app."""

    eas_config = load_eas_config(app.root_path)

    register_audio_routes(app, logger, eas_config)
    register_audio_ingest_routes(app, logger)
    register_api_routes(app, logger)
    register_environment_routes(app, logger)
    register_maintenance_routes(app, logger)
    register_intersection_routes(app, logger)
    register_boundary_routes(app, logger)
    register_auth_routes(app, logger)
    register_dashboard_routes(app, logger, eas_config)

    # CRITICAL: Initialize audio controller on startup (not just when first API request comes in)
    # This ensures auto-start audio sources begin immediately
    with app.app_context():
        from .audio_ingest import _get_audio_controller
        logger.info("Initializing audio controller on startup...")
        _get_audio_controller()
        logger.info("Audio controller initialized")


__all__ = ['register', 'calculate_coverage_percentages']
