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
severe-weather episode can need dozens of WMS fetches, too slow for one
request) and reports how many are still pending. The frontend is expected
to poll this until ``pending`` reaches 0. See
app_utils.image_export.radar_loop for why this needs no background job.
"""

import json

from flask import jsonify
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import CAPAlert
from app_utils.image_export.radar_loop import build_radar_loop

from .blueprint import api_bp


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
    alert = CAPAlert.query.get(alert_id)
    if not alert:
        return jsonify({'error': 'Alert not found'}), 404
    if alert.category != 'Met':
        return jsonify({'error': 'Radar loop is only available for weather alerts'}), 400

    geom_json = db.session.query(
        func.ST_AsGeoJSON(CAPAlert.geom)
    ).filter(CAPAlert.id == alert_id).scalar()
    if not geom_json:
        return jsonify({'error': 'Alert has no geometry to map'}), 400

    result = build_radar_loop(alert, json.loads(geom_json))
    return jsonify(result)
