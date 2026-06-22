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

"""Helper functions for Icecast settings management."""

import logging
from typing import Dict, Any
from flask import current_app

from .extensions import db
from .models import IcecastSettings

logger = logging.getLogger(__name__)


def get_icecast_settings() -> IcecastSettings:
    """Get Icecast settings from database.

    Returns the single IcecastSettings row (id=1), creating it with defaults if needed.
    """
    try:
        settings = IcecastSettings.query.get(1)
        if settings is None:
            settings = IcecastSettings(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings
    except Exception as e:
        # Table might not exist yet (migrations not run)
        # Create it and try again
        try:
            db.create_all()
            settings = IcecastSettings.query.get(1)
            if settings is None:
                settings = IcecastSettings(id=1)
                db.session.add(settings)
                db.session.commit()
            return settings
        except Exception as create_error:
            # Still failing - return default instance without persisting
            # This allows the app to start even if database is unavailable
            logger.error(f"Failed to get Icecast settings from database: {e}")
            logger.error(f"Failed to create table: {create_error}")
            # Return a non-persistent default instance
            return IcecastSettings(id=1)


def update_icecast_settings(data: Dict[str, Any]) -> IcecastSettings:
    """Update Icecast settings in database.

    Args:
        data: Dictionary of settings to update

    Returns:
        Updated IcecastSettings object
    """
    settings = get_icecast_settings()

    # Update fields if provided
    if 'enabled' in data:
        settings.enabled = bool(data['enabled'])
    if 'server' in data:
        settings.server = str(data['server'])
    if 'port' in data:
        settings.port = int(data['port'])
    if 'external_port' in data:
        settings.external_port = int(data['external_port']) if data['external_port'] else None
    if 'public_hostname' in data:
        settings.public_hostname = str(data['public_hostname']) if data['public_hostname'] else None
    if 'server_hostname' in data:
        settings.server_hostname = str(data['server_hostname']) if data['server_hostname'] else None
    if 'server_location' in data:
        settings.server_location = str(data['server_location']) if data['server_location'] else None
    if 'admin_contact' in data:
        settings.admin_contact = str(data['admin_contact']) if data['admin_contact'] else None
    if 'source_password' in data:
        settings.source_password = str(data['source_password'])
    if 'admin_user' in data:
        settings.admin_user = str(data['admin_user']) if data['admin_user'] else None
    if 'admin_password' in data:
        settings.admin_password = str(data['admin_password']) if data['admin_password'] else None
    if 'default_mount' in data:
        settings.default_mount = str(data['default_mount'])
    if 'stream_name' in data:
        settings.stream_name = str(data['stream_name'])
    if 'stream_description' in data:
        settings.stream_description = str(data['stream_description'])
    if 'stream_genre' in data:
        settings.stream_genre = str(data['stream_genre'])
    if 'stream_bitrate' in data:
        settings.stream_bitrate = int(data['stream_bitrate'])
    if 'stream_format' in data:
        settings.stream_format = str(data['stream_format'])
    if 'stream_public' in data:
        settings.stream_public = bool(data['stream_public'])
    if 'max_sources' in data:
        settings.max_sources = int(data['max_sources']) if data['max_sources'] not in (None, '', 'None') else None

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to commit Icecast settings: {e}")
        raise
    
    return settings


def get_icecast_config_dict() -> Dict[str, Any]:
    """Get Icecast settings as a dictionary.

    Returns:
        Dictionary of Icecast settings
    """
    settings = get_icecast_settings()
    return settings.to_dict()


def invalidate_icecast_settings_cache() -> None:
    """Invalidate any cached Icecast settings.

    Call this after updating Icecast settings to force services to reload.
    """
    # Icecast auto-config caches settings, reset it
    try:
        from .audio.icecast_auto_config import _auto_config
        if _auto_config is not None:
            # Reset the global instance to force reload
            import app_core.audio.icecast_auto_config as config_module
            config_module._auto_config = None
    except ImportError:
        pass


__all__ = [
    'get_icecast_settings',
    'update_icecast_settings',
    'get_icecast_config_dict',
    'invalidate_icecast_settings_cache',
]
