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

"""Audio archive and manual EAS route registration."""

from __future__ import annotations

from typing import Any

from flask import Flask


def register_audio_routes(app: Flask, logger: Any, eas_config: dict[str, Any]) -> None:
    """Register all audio-related routes on the Flask application."""
    from .history import register_history_routes
    from .detail import register_detail_routes
    from .files import register_file_routes
    from .received import register_received_alerts_routes

    register_history_routes(app, logger)
    register_detail_routes(app, logger)
    register_file_routes(app, logger)
    register_received_alerts_routes(app, logger)


__all__ = ["register_audio_routes"]
