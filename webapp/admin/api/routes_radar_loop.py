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

"""``/api/alerts/<id>/radar-loop`` — lazily-rendered, disk-cached radar frames.

Renders a bounded number of not-yet-cached frames per call (a long
severe-weather episode can need dozens of frames, too slow for one
request) and reports how many are still pending. The frontend is expected
to poll this until ``pending`` reaches 0. See
app_utils.image_export.radar_loop for why this needs no background job.

Also backs ``/api/alerts/<id>/radar-loop-hires``, the separate, explicitly
"High-Resolution" Level II loop (app_utils.image_export.radar_loop_hires)
-- see that module's docstring for why it's a distinct feature rather than
a silent Level II upgrade to this endpoint.
"""

import json

from flask import jsonify, request
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import CAPAlert
from app_utils.image_export.radar_loop import build_radar_loop
from app_utils.image_export.radar_loop_hires import VALID_FIELDS, build_hires_radar_loop

from .blueprint import api_bp


def _load_alert_and_geom(alert_id):
    """Shared lookup for both loop endpoints below.

    Returns (alert, geom_dict, None) on success, or
    (None, None, (error_response, status)) on failure.
    """
    alert = CAPAlert.query.get(alert_id)
    if not alert:
        return None, None, (jsonify({'error': 'Alert not found'}), 404)
    if alert.category != 'Met':
        return None, None, (jsonify({'error': 'Radar loop is only available for weather alerts'}), 400)

    geom_json = db.session.query(
        func.ST_AsGeoJSON(CAPAlert.geom)
    ).filter(CAPAlert.id == alert_id).scalar()
    if not geom_json:
        return None, None, (jsonify({'error': 'Alert has no geometry to map'}), 400)

    return alert, json.loads(geom_json), None


@api_bp.route('/api/alerts/<int:alert_id>/radar-loop')
def get_alert_radar_loop(alert_id):
    """Lazily render (and permanently disk-cache) a weather alert's radar loop.

    Renders up to a few not-yet-cached frames per call; poll until
    ``pending`` is 0. Frames span the alert's ``sent`` time through
    whichever of ``cancelled_at``/``expires``/now comes first, at 5-minute
    cadence, capped at ``RADAR_LOOP_MAX_FRAMES``.

    Returns:
        200 with {frames: [{time, url}], pending, total}.
        404 if the alert doesn't exist.
        400 if the alert isn't a weather (category='Met') alert, or has no
        stored geometry.
    """
    alert, geom, error = _load_alert_and_geom(alert_id)
    if error:
        return error

    result = build_radar_loop(alert, geom)
    return jsonify(result)


@api_bp.route('/api/alerts/<int:alert_id>/radar-loop-hires')
def get_alert_radar_loop_hires(alert_id):
    """Lazily render (and permanently disk-cache) a weather alert's
    High-Resolution (Level II) radar loop -- a real per-site NEXRAD volume
    scan decode, much sharper than the standard loop above but only
    available within ~230km of a WSR-88D site.

    Query:
        field (str, optional): 'reflectivity' (default) or 'velocity'.

    Renders up to one not-yet-cached frame per call (a real volume
    download + decode, slower than the standard loop's WMS tile fetch);
    poll until ``pending`` is 0. Same 5-minute cadence and duration window
    as the standard loop.

    Returns:
        200 with {frames: [{time, url}], pending, total}. ``total`` and
        ``frames`` can both be 0 for a genuine Level II coverage gap --
        check the ``error`` key for the human-readable reason, which is
        still a 200 (a coverage gap isn't a request error).
        404 if the alert doesn't exist.
        400 if the alert isn't a weather (category='Met') alert, has no
        stored geometry, or ``field`` isn't recognized.
    """
    field = (request.args.get('field') or 'reflectivity').strip().lower()
    if field not in VALID_FIELDS:
        return jsonify({'error': f"field must be one of {VALID_FIELDS}"}), 400

    alert, geom, error = _load_alert_and_geom(alert_id)
    if error:
        return error

    result = build_hires_radar_loop(alert, geom, field=field)
    return jsonify(result)
