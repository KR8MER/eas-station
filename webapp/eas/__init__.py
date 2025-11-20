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

from __future__ import annotations

"""Authenticated EAS workflow blueprint."""

from flask import Blueprint

from app_utils.eas import load_eas_config

from .messages import register_message_routes
from .workflow import register_workflow_routes


def register(app, logger):
    """Register the EAS workflow blueprint with the Flask app."""

    eas_config = load_eas_config(app.root_path)
    blueprint = Blueprint('eas', __name__, url_prefix='/eas')

    register_workflow_routes(blueprint, logger, eas_config)
    register_message_routes(blueprint, logger)

    app.register_blueprint(blueprint)


__all__ = ['register']
