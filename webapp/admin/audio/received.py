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

"""Received EAS alerts monitoring and display routes."""

import io

from flask import render_template, request, jsonify, send_file, abort
from sqlalchemy import desc, func
from sqlalchemy.orm import defer

from app_core.extensions import db
from app_core.models import ReceivedEASAlert
from webapp.admin.audio.received_filters import (
    DEFAULT_PER_PAGE,
    apply_filters,
    build_filter_chips,
    build_pager_qs,
    filter_params,
    parse_filters,
)


def register_received_alerts_routes(app, logger) -> None:
    """Register the received audio alerts monitoring route."""

    @app.route('/audio/received')
    def received_audio_alerts():
        """Display list of received EAS alerts from monitoring with forwarding status."""
        try:
            # Validate pagination parameters
            page = request.args.get('page', 1, type=int)
            page = max(1, page)  # Ensure page is at least 1
            per_page = request.args.get('per_page', DEFAULT_PER_PAGE, type=int)
            per_page = min(max(per_page, 10), 100)  # Clamp between 10 and 100

            # Parse and apply filters (multi-value source/event with
            # include/exclude modes; see received_filters.py).
            filters = parse_filters(request.args)
            # Defer the two heavy columns: raw_audio_data is the captured WAV
            # (~1 MB per alert) and full_alert_data is the complete decoded
            # JSONB. The list template (audio_received.html) renders neither
            # -- only the detail view does -- so a 100-row page was moving
            # ~100 MB of audio it would immediately discard.
            base_query = apply_filters(
                ReceivedEASAlert.query.options(
                    defer(ReceivedEASAlert.raw_audio_data),
                    defer(ReceivedEASAlert.full_alert_data),
                ),
                filters,
            )

            # Order by most recent first
            query = base_query.order_by(desc(ReceivedEASAlert.received_at))

            # Paginate
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            alerts = pagination.items

            # Get unique values for filters (with per-value alert counts so
            # the dropdowns show how much each choice matters)
            source_rows = db.session.query(
                ReceivedEASAlert.source_name, func.count(ReceivedEASAlert.id)
            ).group_by(ReceivedEASAlert.source_name).order_by(ReceivedEASAlert.source_name).all()
            sources = [(row[0], row[1]) for row in source_rows if row[0]]

            event_rows = db.session.query(
                ReceivedEASAlert.event_code,
                func.max(ReceivedEASAlert.event_name),
                func.count(ReceivedEASAlert.id),
            ).group_by(ReceivedEASAlert.event_code).order_by(ReceivedEASAlert.event_code).all()
            events = [(row[0], row[1] or row[0], row[2]) for row in event_rows if row[0]]

            originators = db.session.query(
                ReceivedEASAlert.originator_code, ReceivedEASAlert.originator_name
            ).distinct().order_by(ReceivedEASAlert.originator_code).all()
            originators = [(o[0], o[1] or o[0]) for o in originators if o[0]]

            decisions = ['forwarded', 'ignored', 'error']

            # Statistics
            stats = {
                'total': ReceivedEASAlert.query.count(),
                'forwarded': ReceivedEASAlert.query.filter_by(forwarding_decision='forwarded').count(),
                'ignored': ReceivedEASAlert.query.filter_by(forwarding_decision='ignored').count(),
                'error': ReceivedEASAlert.query.filter_by(forwarding_decision='error').count(),
            }

            return render_template(
                'audio_received.html',
                alerts=alerts,
                pagination=pagination,
                page=page,
                per_page=per_page,
                filters=filters,
                filter_chips=build_filter_chips(filters, per_page),
                has_filters=bool(filter_params(filters)),
                pager_qs=build_pager_qs(filters, per_page),
                sources=sources,
                events=events,
                originators=originators,
                decisions=decisions,
                stats=stats,
            )

        except Exception as e:
            logger.error(f"Error loading received alerts: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass
            return render_template('error.html', error=str(e)), 500

    @app.route('/audio/received/<int:alert_id>/audio')
    def received_alert_audio(alert_id):
        """Stream the raw WAV audio captured when this OTA alert was received."""
        try:
            alert = ReceivedEASAlert.query.get_or_404(alert_id)
            if not alert.raw_audio_data:
                abort(404)
            file_obj = io.BytesIO(alert.raw_audio_data)
            response = send_file(
                file_obj,
                mimetype='audio/wav',
                as_attachment=False,
                download_name=f'received_alert_{alert_id}.wav',
                max_age=0,
            )
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            return response
        except Exception as e:
            logger.error(f"Error serving received alert audio {alert_id}: {e}", exc_info=True)
            abort(500)

    @app.route('/audio/received/<int:alert_id>')
    def received_audio_alert_detail(alert_id):
        """Display detailed view of a received EAS alert."""
        try:
            alert = ReceivedEASAlert.query.get_or_404(alert_id)

            from app_utils.fips_codes import get_extended_same_lookup
            fips_lookup = get_extended_same_lookup()
            all_codes = list(alert.fips_codes or []) + [
                c for c in (alert.matched_fips_codes or [])
                if c not in (alert.fips_codes or [])
            ]
            fips_names = {code: fips_lookup.get(code, '') for code in all_codes}

            return render_template(
                'audio_received_detail.html',
                alert=alert,
                fips_names=fips_names,
            )

        except Exception as e:
            logger.error(f"Error loading received alert detail: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass
            return render_template('error.html', error=str(e)), 500

    @app.route('/api/audio/received/stats')
    def received_audio_alerts_stats():
        """API endpoint for statistics about received alerts."""
        try:
            stats = {
                'total': ReceivedEASAlert.query.count(),
                'forwarded': ReceivedEASAlert.query.filter_by(forwarding_decision='forwarded').count(),
                'ignored': ReceivedEASAlert.query.filter_by(forwarding_decision='ignored').count(),
                'error': ReceivedEASAlert.query.filter_by(forwarding_decision='error').count(),
            }

            # Recent alerts (last 24 hours)
            from datetime import timedelta
            from app_utils import utc_now
            last_24h = utc_now() - timedelta(days=1)
            stats['recent_24h'] = ReceivedEASAlert.query.filter(ReceivedEASAlert.received_at >= last_24h).count()

            return jsonify(stats)

        except Exception as e:
            logger.error(f"Error getting received alerts stats: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500
