"""Authenticated EAS workflow blueprint."""

from __future__ import annotations

from flask import Blueprint

from app_utils.eas import load_eas_config

from . import messages, workflow


def create_blueprint(app, logger):
    """Create the EAS workflow blueprint with all routes registered."""

    eas_config = load_eas_config(app.root_path)
    blueprint = Blueprint('eas', __name__, url_prefix='/eas')

    workflow.register_manual_routes(blueprint, logger, eas_config)
    messages.register_message_routes(blueprint, logger)
    workflow.register_page_routes(blueprint, logger, eas_config)

    return blueprint


def register(app, logger):
    """Register the EAS workflow blueprint with the Flask app."""

    blueprint = create_blueprint(app, logger)
    app.register_blueprint(blueprint)


__all__ = ['create_blueprint', 'register']
