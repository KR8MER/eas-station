"""Authenticated EAS workflow blueprint."""

from __future__ import annotations

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
