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

from __future__ import annotations

"""Helper functions for basemap tile provider settings management."""

import logging
from typing import Any, Dict, Optional, Tuple

from .extensions import db
from .models import MapTileSettings

logger = logging.getLogger(__name__)


def get_map_tile_settings(db_session: Any = None) -> Tuple[str, Optional[str]]:
    """Return (provider, carto_api_key) for the alert share-card map inset.

    Args:
        db_session: Optional raw SQLAlchemy session. app_utils.image_export
            .maps._render_map() is called both from the web app (Flask
            context) and from the standalone CAP poller via
            app_core.notifications.alert_image (no Flask context) --
            pass the poller's own session there so carto_api_key decrypts
            correctly. See app_core.crypto's _root_secret() for why this
            works without a Flask app context: it falls back to the
            SECRET_KEY environment variable, which every service (poller
            included) already has via systemd's EnvironmentFile.

    Never raises -- any failure (missing table, closed session, no row
    yet) degrades to ('osm', None), the zero-config default, since a
    settings read must never break map rendering.
    """
    try:
        row = (
            db_session.get(MapTileSettings, 1)
            if db_session is not None
            else MapTileSettings.query.get(1)
        )
        if row is None:
            return 'osm', None
        return (row.provider or 'osm'), row.carto_api_key
    except Exception as exc:
        logger.warning("Could not load map tile settings, defaulting to OSM: %s", exc)
        return 'osm', None


def update_map_tile_settings(data: Dict[str, Any]) -> MapTileSettings:
    """Update map tile settings in the database (Flask-context callers only
    -- the admin settings page).

    Args:
        data: Dict that may contain 'provider' and/or 'carto_api_key'. An
            empty/missing 'carto_api_key' leaves the stored key untouched
            (the admin form's "leave blank to keep the current key"
            convention, same as TTSSettings.azure_openai_key).

    Returns:
        The updated MapTileSettings row.
    """
    settings = MapTileSettings.query.get(1)
    if settings is None:
        settings = MapTileSettings(id=1)
        db.session.add(settings)

    if 'provider' in data:
        provider = str(data['provider']).strip()
        if provider in ('osm', 'carto_dark'):
            settings.provider = provider

    new_key = (data.get('carto_api_key') or '').strip()
    if new_key:
        settings.carto_api_key = new_key

    db.session.commit()
    return settings
