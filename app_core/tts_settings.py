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

"""Helper functions for TTS settings management."""

import logging
from typing import Dict, Any
from flask import current_app

from .extensions import db
from .models import TTSSettings

logger = logging.getLogger(__name__)


def get_tts_settings() -> TTSSettings:
    """Get TTS settings from database.

    Returns the single TTSSettings row (id=1), creating it with defaults if needed.
    
    NOTE: We refresh the settings object after loading to ensure we get fresh data 
    from the database, not a cached version. This is important because TTS settings 
    can be updated via /admin/tts while the app is running, and the Broadcast Builder 
    needs to see those changes immediately.
    """
    try:
        settings = TTSSettings.query.get(1)
        if settings is None:
            logger.info("TTS settings row not found, creating default")
            settings = TTSSettings(id=1)
            db.session.add(settings)
            db.session.commit()
        else:
            # Refresh to get latest data from database (not cached values)
            db.session.refresh(settings)
        return settings
    except Exception as e:
        # Table might not exist yet (migrations not run)
        # Create it and try again
        logger.warning(f"First attempt to get TTS settings failed: {e}")
        try:
            db.create_all()
            settings = TTSSettings.query.get(1)
            if settings is None:
                settings = TTSSettings(id=1)
                db.session.add(settings)
                db.session.commit()
            return settings
        except Exception as create_error:
            # Still failing - return default instance without persisting
            # This allows the app to start even if database is unavailable
            logger.error(f"Failed to get TTS settings from database: {e}")
            logger.error(f"Failed to create table: {create_error}")
            logger.error("Returning default TTS settings (enabled=False, provider='')")
            # Return a non-persistent default instance
            return TTSSettings(id=1)


def update_tts_settings(data: Dict[str, Any]) -> TTSSettings:
    """Update TTS settings in database.

    Args:
        data: Dictionary of settings to update

    Returns:
        Updated TTSSettings object
    """
    settings = get_tts_settings()

    # Update fields if provided
    if 'enabled' in data:
        settings.enabled = bool(data['enabled'])
    if 'provider' in data:
        settings.provider = str(data['provider']).strip()
    if 'azure_openai_endpoint' in data:
        settings.azure_openai_endpoint = str(data['azure_openai_endpoint']).strip() if data['azure_openai_endpoint'] else None
    if 'azure_openai_key' in data:
        submitted_key = str(data['azure_openai_key']).strip() if data['azure_openai_key'] else ''
        # The form field is intentionally left blank on page load (never
        # pre-filled with the real secret) so a blank or masked-placeholder
        # submission means "no change", not "clear the key". Only a real,
        # newly-typed value overwrites the stored key.
        if submitted_key and submitted_key != '••••••••':
            settings.azure_openai_key = submitted_key
    if 'azure_openai_model' in data:
        settings.azure_openai_model = str(data['azure_openai_model']).strip()
    if 'azure_openai_voice' in data:
        settings.azure_openai_voice = str(data['azure_openai_voice']).strip()
    if 'azure_openai_speed' in data:
        settings.azure_openai_speed = float(data['azure_openai_speed'])

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to commit TTS settings: {e}")
        raise
    
    return settings


def get_tts_config_dict() -> Dict[str, Any]:
    """Get TTS settings as a dictionary.

    Returns:
        Dictionary of TTS settings
    """
    settings = get_tts_settings()
    return settings.to_dict()


__all__ = [
    'get_tts_settings',
    'update_tts_settings',
    'get_tts_config_dict',
]
