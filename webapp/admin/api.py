"""REST-style API routes used by the admin interface."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import psutil
from flask import flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import desc, func

from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, EASMessage, Intersection, PollHistory
from app_core.system_health import get_system_health
from app_utils import UTC_TZ, get_location_timezone, get_location_timezone_name, local_now, utc_now
from app_core.eas_storage import get_eas_static_prefix
from app_core.boundaries import (
    get_boundary_color,
    get_boundary_display_label,
    get_boundary_group,
    normalize_boundary_type,
)
from app_core.alerts import get_active_alerts_query, get_expired_alerts_query
from app_utils import is_alert_expired

from .coverage import calculate_coverage_percentages

_CPU_SAMPLE_INTERVAL_SECONDS = 1.0
_last_cpu_sample_timestamp: Optional[datetime] = None
_last_cpu_sample_value: float = 0.0


def _get_cpu_usage_percent() -> float:
    """Return a recently sampled CPU percentage without blocking the request."""

    global _last_cpu_sample_timestamp, _last_cpu_sample_value

    now = datetime.utcnow()
    if (
        _last_cpu_sample_timestamp is None
        or (now - _last_cpu_sample_timestamp).total_seconds() >= _CPU_SAMPLE_INTERVAL_SECONDS
    ):
        _last_cpu_sample_value = psutil.cpu_percent(interval=None)
        _last_cpu_sample_timestamp = now
    return _last_cpu_sample_value


def register_api_routes(app, logger):
    """Attach JSON API endpoints used by the admin UI."""

    @app.route('/api/alerts/<int:alert_id>/geometry')
    def get_alert_geometry(alert_id):
        """Get specific alert geometry and intersecting boundaries as GeoJSON"""
        try:
            alert = db.session.query(
                CAPAlert.id,
                CAPAlert.identifier,
                CAPAlert.event,
                CAPAlert.severity,
                CAPAlert.urgency,
                CAPAlert.headline,
                CAPAlert.description,
                CAPAlert.expires,
                CAPAlert.sent,
                CAPAlert.area_desc,
                CAPAlert.status,
                func.ST_AsGeoJSON(CAPAlert.geom).label('geometry'),
            ).filter(CAPAlert.id == alert_id).first()

            if not alert:
                return jsonify({'error': 'Alert not found'}), 404

            county_boundary = None
            try:
                county_geom = db.session.query(
                    func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                ).filter(Boundary.type == 'county').first()

                if county_geom and county_geom.geometry:
                    county_boundary = json.loads(county_geom.geometry)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Could not get county boundary: %s", exc)

            geometry = None
            is_county_wide = False

            if alert.geometry:
                geometry = json.loads(alert.geometry)
            elif alert.area_desc:
                area_lower = alert.area_desc.lower()
                if any(county_term in area_lower for county_term in ['county', 'putnam', 'ohio']):
                    if county_boundary:
                        geometry = county_boundary
                        is_county_wide = True

            intersecting_boundaries = []
            if geometry:
                # Fix N+1 query: fetch geometry in a single query with proper join
                intersections = db.session.query(
                    Intersection,
                    Boundary,
                    func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                ).join(
                    Boundary, Intersection.boundary_id == Boundary.id
                ).filter(Intersection.cap_alert_id == alert_id).all()

                for intersection, boundary, boundary_geom_json in intersections:
                    if boundary_geom_json:
                        intersecting_boundaries.append(
                            {
                                'type': 'Feature',
                                'properties': {
                                    'id': boundary.id,
                                    'name': boundary.name,
                                    'type': boundary.type,
                                    'description': boundary.description,
                                    'intersection_area': intersection.intersection_area,
                                },
                                'geometry': json.loads(boundary_geom_json),
                            }
                        )

            expires_iso = None
            if alert.expires:
                expires_dt = alert.expires.replace(tzinfo=UTC_TZ) if alert.expires.tzinfo is None else alert.expires.astimezone(UTC_TZ)
                expires_iso = expires_dt.isoformat()

            sent_iso = None
            if alert.sent:
                sent_dt = alert.sent.replace(tzinfo=UTC_TZ) if alert.sent.tzinfo is None else alert.sent.astimezone(UTC_TZ)
                sent_iso = sent_dt.isoformat()

            response_data = {
                'alert': {
                    'type': 'Feature',
                    'properties': {
                        'id': alert.id,
                        'identifier': alert.identifier,
                        'event': alert.event,
                        'severity': alert.severity,
                        'urgency': alert.urgency,
                        'headline': alert.headline,
                        'description': alert.description,
                        'sent': sent_iso,
                        'expires': expires_iso,
                        'area_desc': alert.area_desc,
                        'status': alert.status,
                        'is_county_wide': is_county_wide,
                    },
                    'geometry': geometry,
                }
                if geometry
                else None,
                'intersecting_boundaries': {
                    'type': 'FeatureCollection',
                    'features': intersecting_boundaries,
                },
            }

            return jsonify(response_data)

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error getting alert geometry: %s", exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/alerts/<int:alert_id>')
    def alert_detail(alert_id):
        """Show detailed information about a specific alert with accurate coverage calculation"""
        try:
            alert = CAPAlert.query.get_or_404(alert_id)

            intersections = db.session.query(Intersection, Boundary).join(
                Boundary, Intersection.boundary_id == Boundary.id
            ).filter(Intersection.cap_alert_id == alert_id).all()

            is_county_wide = False
            if alert.area_desc:
                area_lower = alert.area_desc.lower()
                is_county_wide = (
                    'putnam county' in area_lower
                    or 'entire county' in area_lower
                    or ('county' in area_lower and 'ohio' in area_lower)
                    or (
                        'putnam' in area_lower
                        and (area_lower.count(';') >= 2 or area_lower.count(',') >= 2)
                    )
                )

            coverage_data = calculate_coverage_percentages(alert_id, intersections)

            county_coverage = coverage_data.get('county', {}).get('coverage_percentage', 0)
            is_actually_county_wide = county_coverage >= 95.0

            if not coverage_data and is_county_wide:
                boundary_totals = db.session.query(
                    Boundary.type,
                    func.count(Boundary.id),
                ).group_by(Boundary.type).all()

                if boundary_totals:
                    coverage_data = {}
                    for boundary_type, boundary_count in boundary_totals:
                        entry = {
                            'total_boundaries': boundary_count,
                            'affected_boundaries': boundary_count,
                            'coverage_percentage': 100.0,
                            'total_area_sqm': None,
                            'intersected_area_sqm': None,
                            'is_estimated': True,
                        }

                        if boundary_type == 'county':
                            coverage_data['county'] = entry
                        else:
                            coverage_data[boundary_type] = entry

                    if 'county' not in coverage_data:
                        coverage_data['county'] = {
                            'total_boundaries': 1,
                            'affected_boundaries': 1,
                            'coverage_percentage': 100.0,
                            'total_area_sqm': None,
                            'intersected_area_sqm': None,
                            'is_estimated': True,
                        }

                    county_coverage = coverage_data['county']['coverage_percentage']
                    is_actually_county_wide = True

            suppress_boundary_details = is_actually_county_wide

            boundary_summary: List[Dict[str, Any]] = []
            for boundary_type, data in coverage_data.items() if coverage_data else []:
                if boundary_type == 'county':
                    continue

                total_boundaries = data.get('total_boundaries')
                affected_boundaries = data.get('affected_boundaries')
                coverage_percentage = data.get('coverage_percentage', 0.0)

                is_full_coverage = False
                if total_boundaries is not None and affected_boundaries is not None:
                    is_full_coverage = affected_boundaries >= total_boundaries > 0
                else:
                    is_full_coverage = coverage_percentage >= 95.0

                boundary_summary.append(
                    {
                        'type': boundary_type,
                        'total_boundaries': total_boundaries,
                        'affected_boundaries': affected_boundaries,
                        'coverage_percentage': coverage_percentage,
                        'is_full_coverage': is_full_coverage,
                        'is_estimated': data.get('is_estimated', False),
                    }
                )

            boundary_summary.sort(key=lambda item: item['type'])

            audio_entries: List[Dict[str, Any]] = []
            static_prefix = get_eas_static_prefix()

            def _static_path(filename: Optional[str]) -> Optional[str]:
                if not filename:
                    return None
                parts = [static_prefix, filename] if static_prefix else [filename]
                return '/'.join(part for part in parts if part)

            try:
                messages = (
                    EASMessage.query
                    .filter(EASMessage.cap_alert_id == alert_id)
                    .order_by(EASMessage.created_at.desc())
                    .all()
                )

                for message in messages:
                    metadata = dict(message.metadata_payload or {})
                    eom_filename = metadata.get('eom_filename')
                    has_eom = bool(message.eom_audio_data) or bool(eom_filename)

                    audio_url = url_for('eas_message_audio', message_id=message.id)
                    if message.text_payload:
                        text_url = url_for('eas_message_summary', message_id=message.id)
                    else:
                        text_path = _static_path(message.text_filename)
                        text_url = url_for('static', filename=text_path) if text_path else None

                    if has_eom:
                        eom_url = url_for('eas_message_audio', message_id=message.id, variant='eom')
                    else:
                        eom_path = _static_path(eom_filename) if eom_filename else None
                        eom_url = url_for('static', filename=eom_path) if eom_path else None

                    audio_entries.append(
                        {
                            'id': message.id,
                            'created_at': message.created_at,
                            'same_header': message.same_header,
                            'audio_url': audio_url,
                            'text_url': text_url,
                            'detail_url': url_for('audio_detail', message_id=message.id),
                            'metadata': metadata,
                            'eom_url': eom_url,
                        }
                    )
            except Exception as audio_error:  # pragma: no cover - defensive logging
                logger.warning(
                    'Unable to load audio archive for alert %s: %s',
                    alert.identifier,
                    audio_error,
                )

            primary_audio_entry: Optional[Dict[str, Any]] = audio_entries[0] if audio_entries else None
            additional_audio_entries: List[Dict[str, Any]] = (
                audio_entries[1:] if len(audio_entries) > 1 else []
            )

            return render_template(
                'alert_detail.html',
                alert=alert,
                intersections=intersections,
                is_county_wide=is_county_wide,
                is_actually_county_wide=is_actually_county_wide,
                coverage_data=coverage_data,
                audio_entries=audio_entries,
                primary_audio_entry=primary_audio_entry,
                additional_audio_entries=additional_audio_entries,
                boundary_summary=boundary_summary,
                suppress_boundary_details=suppress_boundary_details,
            )

        except Exception as exc:
            logger.error('Error in alert_detail route: %s', exc)
            flash(f'Error loading alert details: {exc}', 'error')
            return redirect(url_for('index'))

    @app.route('/api/alerts')
    def get_alerts():
        """Get CAP alerts as GeoJSON with optional inclusion of expired alerts"""
        try:
            include_expired = request.args.get('include_expired', 'false').lower() == 'true'

            if include_expired:
                alerts_query = CAPAlert.query
                logger.info("Including expired alerts in API response")
            else:
                alerts_query = get_active_alerts_query()
                logger.info("Including only active alerts in API response")

            alerts = db.session.query(
                CAPAlert.id,
                CAPAlert.identifier,
                CAPAlert.event,
                CAPAlert.severity,
                CAPAlert.urgency,
                CAPAlert.headline,
                CAPAlert.description,
                CAPAlert.expires,
                CAPAlert.area_desc,
                func.ST_AsGeoJSON(CAPAlert.geom).label('geometry'),
            ).filter(
                CAPAlert.id.in_(alerts_query.with_entities(CAPAlert.id).subquery())
            ).all()

            county_boundary = None
            try:
                county_geom = db.session.query(
                    func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                ).filter(Boundary.type == 'county').first()

                if county_geom and county_geom.geometry:
                    county_boundary = json.loads(county_geom.geometry)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Could not get county boundary: %s", exc)

            features = []
            for alert in alerts:
                geometry = None
                is_county_wide = False

                if alert.geometry:
                    geometry = json.loads(alert.geometry)
                elif alert.area_desc and any(
                    county_term in alert.area_desc.lower()
                    for county_term in ['county', 'putnam', 'ohio']
                ):
                    if county_boundary:
                        geometry = county_boundary
                        is_county_wide = True

                if not is_county_wide and alert.area_desc:
                    area_lower = alert.area_desc.lower()

                    if 'putnam' in area_lower:
                        separator_count = max(area_lower.count(';'), area_lower.count(','))
                        if separator_count >= 2:
                            is_county_wide = True

                    county_keywords = ['county', 'putnam county', 'entire county']
                    if any(keyword in area_lower for keyword in county_keywords):
                        is_county_wide = True

                if geometry:
                    expires_iso = None
                    if alert.expires:
                        expires_dt = alert.expires.replace(tzinfo=UTC_TZ) if alert.expires.tzinfo is None else alert.expires.astimezone(UTC_TZ)
                        expires_iso = expires_dt.isoformat()

                    features.append(
                        {
                            'type': 'Feature',
                            'properties': {
                                'id': alert.id,
                                'identifier': alert.identifier,
                                'event': alert.event,
                                'severity': alert.severity,
                                'urgency': alert.urgency,
                                'headline': alert.headline,
                                'description': (
                                    alert.description[:500] + '...'
                                    if len(alert.description) > 500
                                    else alert.description
                                ),
                                'area_desc': alert.area_desc,
                                'expires_iso': expires_iso,
                                'is_county_wide': is_county_wide,
                                'is_expired': is_alert_expired(alert.expires),
                            },
                            'geometry': geometry,
                        }
                    )

            logger.info('Returning %s alerts (include_expired=%s)', len(features), include_expired)

            return jsonify(
                {
                    'type': 'FeatureCollection',
                    'features': features,
                    'metadata': {
                        'total_features': len(features),
                        'include_expired': include_expired,
                        'generated_at': utc_now().isoformat(),
                    },
                }
            )

        except Exception as exc:
            logger.error('Error getting alerts: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/alerts/historical')
    def get_historical_alerts():
        """Get historical alerts as GeoJSON with date filtering"""
        try:
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            include_active = request.args.get('include_active', 'false').lower() == 'true'

            if include_active:
                query = CAPAlert.query
            else:
                query = get_expired_alerts_query()

            if start_date:
                start_dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC_TZ)
                query = query.filter(CAPAlert.sent >= start_dt)

            if end_date:
                end_dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC_TZ)
                query = query.filter(CAPAlert.sent <= end_dt)

            alerts = db.session.query(
                CAPAlert.id,
                CAPAlert.identifier,
                CAPAlert.event,
                CAPAlert.severity,
                CAPAlert.urgency,
                CAPAlert.headline,
                CAPAlert.description,
                CAPAlert.expires,
                CAPAlert.sent,
                CAPAlert.area_desc,
                func.ST_AsGeoJSON(CAPAlert.geom).label('geometry'),
            ).filter(
                CAPAlert.id.in_(query.with_entities(CAPAlert.id).subquery())
            ).all()

            county_boundary = None
            try:
                county_geom = db.session.query(
                    func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                ).filter(Boundary.type == 'county').first()

                if county_geom and county_geom.geometry:
                    county_boundary = json.loads(county_geom.geometry)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Could not get county boundary: %s", exc)

            features = []
            for alert in alerts:
                geometry = None
                is_county_wide = False

                if alert.geometry:
                    geometry = json.loads(alert.geometry)
                elif alert.area_desc and any(
                    county_term in alert.area_desc.lower()
                    for county_term in ['county', 'putnam', 'ohio']
                ):
                    if county_boundary:
                        geometry = county_boundary
                        is_county_wide = True

                if geometry:
                    expires_iso = None
                    if alert.expires:
                        expires_dt = alert.expires.replace(tzinfo=UTC_TZ) if alert.expires.tzinfo is None else alert.expires.astimezone(UTC_TZ)
                        expires_iso = expires_dt.isoformat()

                    sent_iso = None
                    if alert.sent:
                        sent_dt = alert.sent.replace(tzinfo=UTC_TZ) if alert.sent.tzinfo is None else alert.sent.astimezone(UTC_TZ)
                        sent_iso = sent_dt.isoformat()

                    features.append(
                        {
                            'type': 'Feature',
                            'properties': {
                                'id': alert.id,
                                'identifier': alert.identifier,
                                'event': alert.event,
                                'severity': alert.severity,
                                'urgency': alert.urgency,
                                'headline': alert.headline,
                                'description': (
                                    alert.description[:500] + '...'
                                    if len(alert.description) > 500
                                    else alert.description
                                ),
                                'sent': sent_iso,
                                'expires': expires_iso,
                                'area_desc': alert.area_desc,
                                'is_historical': True,
                                'is_county_wide': is_county_wide,
                            },
                            'geometry': geometry,
                        }
                    )

            return jsonify({'type': 'FeatureCollection', 'features': features})

        except Exception as exc:
            logger.error('Error getting historical alerts: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/boundaries')
    def get_boundaries():
        """Get all boundaries as GeoJSON"""
        try:
            # Validate pagination parameters
            page = request.args.get('page', 1, type=int)
            page = max(1, page)  # Ensure page is at least 1
            per_page = request.args.get('per_page', 1000, type=int)
            per_page = min(max(per_page, 1), 5000)  # Clamp between 1 and 5000
            boundary_type = request.args.get('type')
            search = request.args.get('search')

            query = db.session.query(
                Boundary.id,
                Boundary.name,
                Boundary.type,
                Boundary.description,
                func.ST_AsGeoJSON(Boundary.geom).label('geometry'),
            )

            if boundary_type:
                normalized_type = normalize_boundary_type(boundary_type)
                query = query.filter(func.lower(Boundary.type) == normalized_type)

            if search:
                query = query.filter(Boundary.name.ilike(f'%{search}%'))

            boundaries = query.paginate(page=page, per_page=per_page, error_out=False).items

            features = []
            for boundary in boundaries:
                if boundary.geometry:
                    normalized_type = normalize_boundary_type(boundary.type)
                    features.append(
                        {
                            'type': 'Feature',
                            'properties': {
                                'id': boundary.id,
                                'name': boundary.name,
                                'type': normalized_type,
                                'raw_type': boundary.type,
                                'display_type': get_boundary_display_label(boundary.type),
                                'group': get_boundary_group(boundary.type),
                                'color': get_boundary_color(boundary.type),
                                'description': boundary.description,
                            },
                            'geometry': json.loads(boundary.geometry),
                        }
                    )

            return jsonify({'type': 'FeatureCollection', 'features': features})
        except Exception as exc:
            logger.error('Error fetching boundaries: %s', exc)
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/system_status')
    def api_system_status():
        """Get system status information using new helper functions with timezone support"""
        try:
            total_boundaries = Boundary.query.count()
            active_alerts = get_active_alerts_query().count()

            last_poll = PollHistory.query.order_by(desc(PollHistory.timestamp)).first()

            cpu = _get_cpu_usage_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            current_utc = utc_now()
            current_local = local_now()

            status = 'healthy'
            status_reasons = []

            def _record_status(level: str, message: str) -> None:
                nonlocal status
                status_reasons.append({'level': level, 'message': message})
                if level == 'critical':
                    status = 'critical'
                elif level == 'warning' and status != 'critical':
                    status = 'warning'

            if cpu >= 90:
                _record_status(
                    'critical',
                    f'CPU usage is {cpu:.1f}%, exceeding the 90% critical threshold.',
                )
            elif cpu >= 75:
                _record_status(
                    'warning',
                    f'CPU usage is {cpu:.1f}%, above the 75% warning threshold.',
                )

            if memory.percent >= 92:
                _record_status(
                    'critical',
                    (
                        'Memory usage is '
                        f'{memory.percent:.1f}%, exceeding the 92% critical threshold.'
                    ),
                )
            elif memory.percent >= 80:
                _record_status(
                    'warning',
                    (
                        'Memory usage is '
                        f'{memory.percent:.1f}%, above the 80% warning threshold.'
                    ),
                )

            if disk.percent >= 95:
                _record_status(
                    'critical',
                    (
                        'Disk usage is '
                        f'{disk.percent:.1f}% on the root volume with '
                        f"{disk.free // (1024 * 1024 * 1024)} GB free, exceeding the "
                        '95% critical threshold.'
                    ),
                )
            elif disk.percent >= 85:
                _record_status(
                    'warning',
                    (
                        'Disk usage is '
                        f'{disk.percent:.1f}% on the root volume with '
                        f"{disk.free // (1024 * 1024 * 1024)} GB free, above the "
                        '85% warning threshold.'
                    ),
                )

            poll_snapshot = None
            location_tz = get_location_timezone()
            if last_poll:
                poll_timestamp = last_poll.timestamp
                if poll_timestamp.tzinfo is None:
                    poll_timestamp = poll_timestamp.replace(tzinfo=UTC_TZ)
                poll_age_minutes = (current_utc - poll_timestamp).total_seconds() / 60.0
                poll_local_time = poll_timestamp.astimezone(location_tz)
                poll_time_display = poll_local_time.strftime('%Y-%m-%d %H:%M %Z')
                if poll_age_minutes >= 60:
                    _record_status(
                        'critical',
                        (
                            'Last poll ran '
                            f'{poll_age_minutes:.0f} minutes ago '
                            f'(local time {poll_time_display}).'
                        ),
                    )
                elif poll_age_minutes >= 15:
                    _record_status(
                        'warning',
                        (
                            'Last poll ran '
                            f'{poll_age_minutes:.0f} minutes ago '
                            f'(local time {poll_time_display}).'
                        ),
                    )

                poll_status = (last_poll.status or '').strip().lower()
                if poll_status and poll_status not in {'success', 'ok', 'completed'}:
                    level = 'critical' if poll_status in {'failed', 'error'} else 'warning'
                    error_detail = (last_poll.error_message or '').strip()
                    detail_suffix = f" Details: {error_detail}" if error_detail else ''
                    _record_status(
                        level,
                        f"Last poll reported status '{last_poll.status}'.{detail_suffix}",
                    )

                poll_snapshot = {
                    'timestamp': poll_timestamp.isoformat(),
                    'local_timestamp': poll_timestamp.astimezone(location_tz).isoformat(),
                    'status': last_poll.status,
                    'alerts_fetched': last_poll.alerts_fetched or 0,
                    'alerts_new': last_poll.alerts_new or 0,
                    'error_message': (last_poll.error_message or '').strip() or None,
                    'data_source': last_poll.data_source,
                }
            else:
                _record_status(
                    'warning',
                    'No poll activity has been recorded yet; verify the poller service is '
                    'running and configured.',
                )

            status_summary = 'All systems operational.'
            if status_reasons:
                summary_source = next(
                    (reason for reason in status_reasons if reason['level'] == status),
                    status_reasons[0],
                )
                status_summary = summary_source['message']

            return jsonify(
                {
                    'status': status,
                    'status_summary': status_summary,
                    'status_reasons': status_reasons,
                    'timestamp': current_utc.isoformat(),
                    'local_timestamp': current_local.isoformat(),
                    'timezone': get_location_timezone_name(),
                    'boundaries_count': total_boundaries,
                    'active_alerts_count': active_alerts,
                    'database_status': 'connected',
                    'last_poll': poll_snapshot,
                    'system_resources': {
                        'cpu_usage_percent': cpu,
                        'memory_usage_percent': memory.percent,
                        'disk_usage_percent': disk.percent,
                        'disk_free_gb': disk.free // (1024 * 1024 * 1024),
                    },
                }
            )
        except Exception as exc:
            logger.error('Error getting system status: %s', exc)
            return jsonify({'error': f'Failed to get system status: {exc}'}), 500

    @app.route('/api/system_health')
    def api_system_health():
        """Get comprehensive system health information via API"""
        try:
            health_data = get_system_health()
            return jsonify(health_data)
        except Exception as exc:
            logger.error('Error getting system health via API: %s', exc)
            return jsonify({'error': str(exc)}), 500


__all__ = ['register_api_routes']
