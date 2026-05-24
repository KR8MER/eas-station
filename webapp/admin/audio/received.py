"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import render_template, request, url_for, jsonify, send_file, abort
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
            alert_source_filter = request.args.get('alert_source', '').strip()
            event_filter = request.args.get('event', '').strip()
            decision_filter = request.args.get('decision', '').strip()
            originator_filter = request.args.get('originator', '').strip()
            date_from = request.args.get('date_from', '').strip()
            date_to = request.args.get('date_to', '').strip()
            min_confidence_raw = request.args.get('min_confidence', '').strip()

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

            if alert_source_filter:
                base_query = base_query.filter(ReceivedEASAlert.alert_source == alert_source_filter)

            if event_filter:
                base_query = base_query.filter(ReceivedEASAlert.event_code == event_filter)

            if decision_filter:
                base_query = base_query.filter(ReceivedEASAlert.forwarding_decision == decision_filter)

            if originator_filter:
                base_query = base_query.filter(ReceivedEASAlert.originator_code == originator_filter)

            # Date range: inputs are YYYY-MM-DD local dates. Treat as inclusive day.
            if date_from:
                try:
                    df = datetime.strptime(date_from, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    base_query = base_query.filter(ReceivedEASAlert.received_at >= df)
                except ValueError:
                    date_from = ''
            if date_to:
                try:
                    dt = datetime.strptime(date_to, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    # Include the entire selected end day
                    dt_end = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                    base_query = base_query.filter(ReceivedEASAlert.received_at <= dt_end)
                except ValueError:
                    date_to = ''

            min_confidence = None
            if min_confidence_raw:
                try:
                    min_confidence = float(min_confidence_raw)
                    if 0.0 <= min_confidence <= 1.0:
                        base_query = base_query.filter(ReceivedEASAlert.decode_confidence >= min_confidence)
                    else:
                        min_confidence = None
                except ValueError:
                    min_confidence = None

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
                search=search,
                source_filter=source_filter,
                alert_source_filter=alert_source_filter,
                event_filter=event_filter,
                decision_filter=decision_filter,
                originator_filter=originator_filter,
                date_from=date_from,
                date_to=date_to,
                min_confidence=min_confidence,
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
