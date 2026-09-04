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

"""Alert share-card basemap tile provider settings management."""

import logging
from typing import Any, Dict

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import BadRequest

from app_core.auth.roles import require_permission
from app_core.auth.audit import AuditLogger
from app_core.extensions import db
from app_core.map_tile_settings import get_map_tile_settings, update_map_tile_settings
from app_core.models import MapTileSettings

logger = logging.getLogger(__name__)

map_tiles_bp = Blueprint('map_tiles', __name__)

_VALID_PROVIDERS = ('osm', 'carto_dark')


def _get_settings_row() -> MapTileSettings:
    """Flask-context row fetch for the admin page/API -- creates the
    default row on first visit, same convention as get_tts_settings()."""
    settings = MapTileSettings.query.get(1)
    if settings is None:
        settings = MapTileSettings(id=1)
        db.session.add(settings)
        db.session.commit()
    return settings


# Routes are relative to blueprint's url_prefix='/admin'.
@map_tiles_bp.route('/map-tiles')
@require_permission('system.configure')
def map_tiles_settings_page():
    """Display the basemap tile provider settings page."""
    try:
        settings = _get_settings_row()
        return render_template('admin/map_tiles.html', settings=settings)
    except Exception as exc:
        logger.error(f"Failed to load map tile settings: {exc}")
        flash(f"Error loading map tile settings: {exc}", "error")
        return redirect(url_for('dashboard.admin'))


@map_tiles_bp.route('/api/map-tiles/settings', methods=['GET'])
@require_permission('system.configure')
def get_settings():
    """Get current basemap tile provider settings.

    Returns:
        200 with {success, settings}.
    """
    try:
        settings = _get_settings_row()
        return jsonify({"success": True, "settings": settings.to_dict()})
    except Exception as exc:
        logger.error(f"Failed to get map tile settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


@map_tiles_bp.route('/api/map-tiles/settings', methods=['PUT'])
@require_permission('system.configure')
def update_settings():
    """Update the basemap tile provider settings.

    Body:
        provider (str, optional): 'osm' or 'carto_dark'.
        carto_api_key (str, optional): blank leaves the stored key unchanged.

    Returns:
        200 with {success, message, settings}.
        400 if provider isn't one of the recognized values.
    """
    try:
        data: Dict[str, Any] = request.get_json() if request.is_json else request.form.to_dict()

        if 'provider' in data and data['provider'] not in _VALID_PROVIDERS:
            raise BadRequest(f"Invalid provider. Must be one of: {', '.join(_VALID_PROVIDERS)}")

        settings = update_map_tile_settings(data)

        logger.info("Map tile settings updated successfully")

        # Audit: the API key itself is never recorded, only that it changed.
        _sensitive = ('key',)
        audit_details: Dict[str, Any] = {'changed_fields': sorted(data.keys())}
        for _k, _v in data.items():
            if not any(_s in _k.lower() for _s in _sensitive):
                audit_details[_k] = _v
        AuditLogger.log_config_change(
            resource_type='map_tile_settings',
            resource_id=str(settings.id) if getattr(settings, 'id', None) is not None else None,
            details=audit_details,
        )

        return jsonify({
            "success": True,
            "message": "Map tile settings updated successfully. Changes take effect on the next alert render.",
            "settings": settings.to_dict(),
        })

    except BadRequest as exc:
        logger.warning(f"Bad request updating map tile settings: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 400

    except Exception as exc:
        logger.error(f"Failed to update map tile settings: {exc}")
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500


@map_tiles_bp.route('/api/map-tiles/test', methods=['POST'])
@require_permission('system.configure')
def test_provider():
    """Fetch one real tile with the currently-saved CARTO settings to
    confirm the API key actually works, without needing to render a full
    alert card first.

    Returns:
        200 with {success, message} -- success is False (not an HTTP
        error) when the provider is 'osm' (nothing to test) or the tile
        fetch failed, so the frontend can show either as a plain result.
    """
    try:
        provider, api_key = get_map_tile_settings()
        if provider != 'carto_dark':
            return jsonify({
                "success": False,
                "error": "Provider is set to OpenStreetMap -- nothing to test. "
                         "Select CARTO Dark Matter and save a key first.",
            })
        if not api_key:
            return jsonify({"success": False, "error": "No CARTO API key is saved yet."})

        from app_utils.image_export.tiles import _fetch_tile
        tile = _fetch_tile(0, 0, 0, provider='carto_dark', api_key=api_key)
        if tile is None:
            return jsonify({
                "success": False,
                "error": "Could not fetch a tile from CARTO with this key -- check that it's "
                         "correct and hasn't been revoked at https://carto.com/basemaps/apikey.",
            })
        return jsonify({"success": True, "message": "CARTO API key is working."})

    except Exception as exc:
        logger.error(f"Map tile provider test failed: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500


def register_map_tile_routes(app, logger):
    """Register basemap tile provider admin routes with the Flask app.

    Routes are registered with url_prefix='/admin', so '/map-tiles' becomes
    '/admin/map-tiles' and '/api/map-tiles/settings' becomes
    '/admin/api/map-tiles/settings'.
    """
    app.register_blueprint(map_tiles_bp, url_prefix='/admin')
    logger.info("Map tile provider admin routes registered")


__all__ = ['map_tiles_bp', 'register_map_tile_routes']
