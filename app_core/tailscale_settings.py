"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""Helper functions for Tailscale settings management."""

import logging
from typing import Dict, Any

from .extensions import db
from .models import TailscaleSettings

logger = logging.getLogger(__name__)


def get_tailscale_settings() -> TailscaleSettings:
    """Get Tailscale settings from database.

    Returns the single TailscaleSettings row (id=1), creating it with defaults if needed.
    """
    try:
        settings = TailscaleSettings.query.get(1)
        if settings is None:
            settings = TailscaleSettings(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings
    except Exception as e:
        try:
            db.create_all()
            settings = TailscaleSettings.query.get(1)
            if settings is None:
                settings = TailscaleSettings(id=1)
                db.session.add(settings)
                db.session.commit()
            return settings
        except Exception as create_error:
            logger.error(f"Failed to get Tailscale settings from database: {e}")
            logger.error(f"Failed to create table: {create_error}")
            return TailscaleSettings(id=1)


def update_tailscale_settings(data: Dict[str, Any]) -> TailscaleSettings:
    """Update Tailscale settings in database.

    Args:
        data: Dictionary of settings to update

    Returns:
        Updated TailscaleSettings object
    """
    settings = get_tailscale_settings()

    if 'enabled' in data:
        settings.enabled = bool(data['enabled'])
    if data.get('clear_auth_key'):
        # Explicit "switch to browser-based login" action from the UI --
        # the only way to blank out an existing key, since a bare empty
        # submission below means "no change" instead.
        settings.auth_key = ''
    elif 'auth_key' in data:
        submitted_key = str(data['auth_key']).strip()
        # The form field is never pre-filled with the real secret, so a
        # blank or masked-placeholder submission means "no change", not
        # "clear the key" -- mirrors update_tts_settings() in tts_settings.py.
        if submitted_key and submitted_key != '••••••••':
            settings.auth_key = submitted_key
    if 'hostname' in data:
        settings.hostname = str(data['hostname']).strip()
    if 'advertise_exit_node' in data:
        settings.advertise_exit_node = bool(data['advertise_exit_node'])
    if 'accept_routes' in data:
        settings.accept_routes = bool(data['accept_routes'])
    if 'advertise_routes' in data:
        settings.advertise_routes = str(data['advertise_routes']).strip()
    if 'shields_up' in data:
        settings.shields_up = bool(data['shields_up'])
    if 'accept_dns' in data:
        settings.accept_dns = bool(data['accept_dns'])

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to commit Tailscale settings: {e}")
        raise

    return settings


def get_tailscale_config_dict() -> Dict[str, Any]:
    """Get Tailscale settings as a dictionary.

    Returns:
        Dictionary of Tailscale settings
    """
    settings = get_tailscale_settings()
    return settings.to_dict()


__all__ = [
    'get_tailscale_settings',
    'update_tailscale_settings',
    'get_tailscale_config_dict',
]
