"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Received EAS alerts monitoring and display routes."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import render_template, request, url_for, jsonify
from sqlalchemy import or_, desc

from app_core.extensions import db
from app_core.models import ReceivedEASAlert, EASMessage


def register_received_alerts_routes(app, logger) -> None:
    """Register the received audio alerts monitoring route."""

    @app.route('/audio/received')
    def received_audio_alerts():
        """Display list of received EAS alerts from monitoring with forwarding status."""
        try:
            # Validate pagination parameters
            page = request.args.get('page', 1, type=int)
            page = max(1, page)  # Ensure page is at least 1
            per_page = request.args.get('per_page', 25, type=int)
            per_page = min(max(per_page, 10), 100)  # Clamp between 10 and 100

            # Filters
            search = request.args.get('search', '').strip()
            source_filter = request.args.get('source', '').strip()
            event_filter = request.args.get('event', '').strip()
            decision_filter = request.args.get('decision', '').strip()

            # Build query
            base_query = ReceivedEASAlert.query

            if search:
                search_term = f'%{search}%'
                base_query = base_query.filter(
                    or_(
                        ReceivedEASAlert.event_code.ilike(search_term),
                        ReceivedEASAlert.event_name.ilike(search_term),
                        ReceivedEASAlert.raw_same_header.ilike(search_term),
                        ReceivedEASAlert.originator_name.ilike(search_term),
                        ReceivedEASAlert.callsign.ilike(search_term),
                    )
                )

            if source_filter:
                base_query = base_query.filter(ReceivedEASAlert.source_name == source_filter)

            if event_filter:
                base_query = base_query.filter(ReceivedEASAlert.event_code == event_filter)

            if decision_filter:
                base_query = base_query.filter(ReceivedEASAlert.forwarding_decision == decision_filter)

            # Order by most recent first
            query = base_query.order_by(desc(ReceivedEASAlert.received_at))

            # Paginate
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            alerts = pagination.items

            # Get unique values for filters
            sources = db.session.query(ReceivedEASAlert.source_name).distinct().order_by(ReceivedEASAlert.source_name).all()
            sources = [s[0] for s in sources if s[0]]

            events = db.session.query(ReceivedEASAlert.event_code, ReceivedEASAlert.event_name).distinct().order_by(ReceivedEASAlert.event_code).all()
            events = [(e[0], e[1] or e[0]) for e in events if e[0]]

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
                search=search,
                source_filter=source_filter,
                event_filter=event_filter,
                decision_filter=decision_filter,
                sources=sources,
                events=events,
                decisions=decisions,
                stats=stats,
            )

        except Exception as e:
            logger.error(f"Error loading received alerts: {e}", exc_info=True)
            return render_template('error.html', error=str(e)), 500

    @app.route('/audio/received/<int:alert_id>')
    def received_audio_alert_detail(alert_id):
        """Display detailed view of a received EAS alert."""
        try:
            alert = ReceivedEASAlert.query.get_or_404(alert_id)

            return render_template(
                'audio_received_detail.html',
                alert=alert,
            )

        except Exception as e:
            logger.error(f"Error loading received alert detail: {e}", exc_info=True)
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
