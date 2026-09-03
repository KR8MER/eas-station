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

"""Animated GIF alert export -- split out of routes_alert_export.py once
adding it pushed that module over the 400-line guidance (see AGENTS.md).

Shares _run_off_worker and _SOCIAL_IMAGE_RATIOS from routes_alert_export
rather than duplicating them.
"""

import json

from flask import flash, redirect, request, url_for, Response
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, Intersection

from ..coverage import calculate_coverage_percentages

from .blueprint import api_bp
from .display_data import _extract_alert_display_data
from .routes_alert_export import _run_off_worker, _SOCIAL_IMAGE_RATIOS


@api_bp.route('/alerts/<int:alert_id>/export-image.gif')
def alert_detail_gif(alert_id):
    """Generate an animated GIF share card for a weather alert.

    Reuses the same full-card composition as ``export-image.png``, once
    per cached radar-loop frame -- the header/info panels/footer stay
    fixed while the map inset animates through the radar and, on the
    frame matching the alert's own issuance time, the warning polygon
    appears. Frames before issuance never show the polygon (see
    app_utils.image_export.radar_loop's RADAR_LOOP_LEADIN_MINUTES).

    Accepts the same ``ratio`` and ``scale`` query arguments as
    ``export-image.png`` (``format`` doesn't apply -- output is always
    GIF). ``scale`` is capped at 2 here (see gif_export.GIF_MAX_SCALE).

    Returns:
        200 with the GIF bytes as an attachment.
        400 if the alert isn't a weather (category='Met') alert, has no
        stored geometry, or no radar frames could be rendered.
    """
    try:
        from app_utils.image_export import generate_alert_gif
        from app_core.location import get_location_settings

        alert = CAPAlert.query.get_or_404(alert_id)

        if alert.category != 'Met':
            flash('Animated GIF export is only available for weather alerts.', 'error')
            return redirect(url_for('api.alert_detail', alert_id=alert_id))

        geom_json = db.session.query(
            func.ST_AsGeoJSON(CAPAlert.geom)
        ).filter(CAPAlert.id == alert_id).scalar()
        if not geom_json:
            flash('This alert has no stored geometry to animate.', 'error')
            return redirect(url_for('api.alert_detail', alert_id=alert_id))
        geom = json.loads(geom_json)

        ratio = (request.args.get('ratio') or 'landscape').strip().lower()
        if ratio not in _SOCIAL_IMAGE_RATIOS:
            ratio = 'landscape'

        try:
            scale = float(request.args.get('scale', 1))
        except (TypeError, ValueError):
            scale = 1.0

        intersections = db.session.query(Intersection, Boundary).join(
            Boundary, Intersection.boundary_id == Boundary.id
        ).filter(Intersection.cap_alert_id == alert_id).all()

        coverage_data = calculate_coverage_percentages(alert_id, intersections)
        ipaws_data    = _extract_alert_display_data(alert)

        try:
            location_settings = get_location_settings()
        except Exception:
            location_settings = {}

        # Rendering up to ~15 full cards plus the GIF encode is well
        # beyond what's safe on the request greenlet -- see
        # _run_off_worker's docstring. Same fresh-session-per-thread
        # pattern as export-image.png.
        from sqlalchemy.orm import sessionmaker

        engine = db.engine
        Session = sessionmaker(bind=engine)

        def _render():
            render_session = Session()
            try:
                return generate_alert_gif(
                    alert, coverage_data, ipaws_data, location_settings, geom,
                    aspect_ratio=ratio, db_session=render_session, scale=scale,
                )
            finally:
                render_session.close()

        gif_bytes = _run_off_worker(_render)

        response = Response(gif_bytes, mimetype='image/gif')
        safe_event = (alert.event or 'alert').replace(' ', '_').lower()
        response.headers['Content-Disposition'] = (
            f'attachment; filename=alert_{alert_id}_{safe_event}_{ratio}.gif'
        )
        response.headers['Cache-Control'] = 'no-cache'
        return response

    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('api.alert_detail', alert_id=alert_id))
    except Exception as exc:
        api_bp.logger.error('Error generating alert GIF: %s', exc, exc_info=True)
        flash('Error generating animated GIF. Please try again.', 'error')
        return redirect(url_for('api.alert_detail', alert_id=alert_id))
