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

"""Animated video alert export -- split out of routes_alert_export.py once
adding it pushed that module over the 400-line guidance (see AGENTS.md).

Replaces an earlier GIF export (see git history / video_export.py's
docstring for why) -- same route shape, MP4 instead of GIF.

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


@api_bp.route('/alerts/<int:alert_id>/export-image.mp4')
def alert_detail_video(alert_id):
    """Generate an animated MP4 share card for a weather alert.

    Reuses the same full-card composition as ``export-image.png``, once
    per cached radar-loop frame -- the header/info panels/footer stay
    fixed while the map inset animates through the radar and, on the
    frame matching the alert's own issuance time, the warning polygon
    appears. Frames before issuance never show the polygon (see
    app_utils.image_export.radar_loop's RADAR_LOOP_LEADIN_MINUTES).

    Accepts the same ``ratio`` and ``scale`` query arguments as
    ``export-image.png`` (``format`` doesn't apply -- output is always
    MP4/H.264). ``scale`` is capped at 2 here (see
    video_export.VIDEO_MAX_SCALE).

    Returns:
        200 with the MP4 bytes as an attachment.
        400 if the alert isn't a weather (category='Met') alert, has no
        stored geometry, no radar frames could be rendered, or ffmpeg
        isn't installed.
    """
    try:
        from app_core.location import get_location_settings

        alert = CAPAlert.query.get_or_404(alert_id)

        if alert.category != 'Met':
            flash('Animated video export is only available for weather alerts.', 'error')
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

        # Rendering up to ~15 full cards is well beyond what's safe on the
        # request greenlet -- see _run_off_worker's docstring. Same
        # fresh-session-per-thread pattern as export-image.png.
        from sqlalchemy.orm import sessionmaker
        from app_utils.image_export.video_export import (
            encode_frames_to_mp4, render_alert_video_frames,
        )

        engine = db.engine
        Session = sessionmaker(bind=engine)

        def _render():
            render_session = Session()
            try:
                return render_alert_video_frames(
                    alert, coverage_data, ipaws_data, location_settings, geom,
                    aspect_ratio=ratio, db_session=render_session, scale=scale,
                )
            finally:
                render_session.close()

        frame_sequence = _run_off_worker(_render)
        # The ffmpeg encode itself must run back on this request greenlet,
        # not the threadpool _render() above just ran on -- see
        # encode_frames_to_mp4's docstring for why gevent's cooperative
        # subprocess handling only works there.
        video_bytes = encode_frames_to_mp4(frame_sequence)

        response = Response(video_bytes, mimetype='video/mp4')
        safe_event = (alert.event or 'alert').replace(' ', '_').lower()
        response.headers['Content-Disposition'] = (
            f'attachment; filename=alert_{alert_id}_{safe_event}_{ratio}.mp4'
        )
        response.headers['Cache-Control'] = 'no-cache'
        return response

    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('api.alert_detail', alert_id=alert_id))
    except Exception as exc:
        api_bp.logger.error('Error generating alert video: %s', exc, exc_info=True)
        flash('Error generating animated video. Please try again.', 'error')
        return redirect(url_for('api.alert_detail', alert_id=alert_id))
