from __future__ import annotations

import io
import json
import math
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import psutil
from flask import (
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import desc, func, or_

from urllib.parse import urljoin, urlparse

from app_utils import (
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_MANUAL,
    ALERT_SOURCE_NOAA,
    ALERT_SOURCE_UNKNOWN,
    UTC_TZ,
    build_system_health_snapshot,
    format_bytes,
    format_local_date,
    format_local_datetime,
    format_local_time,
    format_uptime,
    get_location_timezone,
    get_location_timezone_name,
    is_alert_expired,
    local_now,
    normalize_alert_source,
    parse_nws_datetime as _parse_nws_datetime,
    set_location_timezone,
    summarise_sources,
    expand_source_summary,
    utc_now,
)
from app_utils.eas import (
    P_DIGIT_MEANINGS,
    EASAudioGenerator,
    ORIGINATOR_DESCRIPTIONS,
    PRIMARY_ORIGINATORS,
    SAME_HEADER_FIELD_DESCRIPTIONS,
    build_same_header,
    describe_same_header,
    load_eas_config,
    manual_default_same_codes,
    samples_to_wav_bytes,
)
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree
from app_core.alerts import (
    assign_alert_geometry,
    calculate_alert_intersections,
    ensure_multipolygon,
    get_active_alerts_query,
    get_expired_alerts_query,
    parse_noaa_cap_alert,
)
from app_core.boundaries import (
    BOUNDARY_GROUP_LABELS,
    BOUNDARY_TYPE_CONFIG,
    calculate_geometry_length_miles,
    describe_mtfcc,
    extract_name_and_description,
    get_boundary_color,
    get_boundary_display_label,
    get_boundary_group,
    get_field_mappings,
    normalize_boundary_type,
)
from app_core.extensions import db
from app_core.eas_storage import (
    get_eas_static_prefix,
    load_or_cache_audio_data,
    load_or_cache_summary_payload,
    remove_eas_files,
    resolve_eas_disk_path,
)
from app_core.location import get_location_settings, update_location_settings
from app_core.system_health import get_system_health
from app_core.models import (
    AdminUser,
    Boundary,
    CAPAlert,
    EASMessage,
    ManualEASActivation,
    Intersection,
    LEDMessage,
    LEDSignStatus,
    LocationSettings,
    PollHistory,
    SystemLog,
)
from app_core.led import (
    Color,
    Effect,
    DisplayMode,
    Font,
    FontSize,
    LED_AVAILABLE,
    LED_SIGN_IP,
    LED_SIGN_PORT,
    MessagePriority,
    SpecialFunction,
    Speed,
    ensure_led_tables,
    initialise_led_controller,
    led_controller,
    led_module,
)




def calculate_coverage_percentages(alert_id, intersections):
    """Calculate coverage metrics for each boundary type and the overall county."""

    coverage_data: Dict[str, Dict[str, Any]] = {}

    try:
        logger = current_app.logger
        alert = CAPAlert.query.get(alert_id)
        if not alert or not alert.geom:
            return coverage_data

        boundary_types: Dict[str, List[Tuple[Intersection, Boundary]]] = {}
        for intersection, boundary in intersections:
            boundary_types.setdefault(boundary.type, []).append((intersection, boundary))

        for boundary_type, boundaries in boundary_types.items():
            all_boundaries_of_type = Boundary.query.filter_by(type=boundary_type).all()
            if not all_boundaries_of_type:
                continue

            total_area_query = db.session.query(
                func.sum(func.ST_Area(Boundary.geom)).label('total_area')
            ).filter(Boundary.type == boundary_type).first()

            total_area = total_area_query.total_area if total_area_query and total_area_query.total_area else 0

            intersected_area = sum(
                intersection.intersection_area or 0 for intersection, _ in boundaries
            )

            coverage_percentage = 0.0
            if total_area > 0:
                coverage_percentage = (intersected_area / total_area) * 100
                coverage_percentage = min(100.0, max(0.0, coverage_percentage))

            coverage_data[boundary_type] = {
                'total_boundaries': len(all_boundaries_of_type),
                'affected_boundaries': len(boundaries),
                'coverage_percentage': round(coverage_percentage, 1),
                'total_area_sqm': total_area,
                'intersected_area_sqm': intersected_area,
            }

        county_boundary = Boundary.query.filter_by(type='county').first()
        if county_boundary and county_boundary.geom:
            county_intersection_query = db.session.query(
                func.ST_Area(
                    func.ST_Intersection(alert.geom, county_boundary.geom)
                ).label('intersection_area'),
                func.ST_Area(county_boundary.geom).label('total_county_area'),
            ).first()

            if county_intersection_query:
                county_coverage = 0.0
                if county_intersection_query.total_county_area:
                    county_coverage = (
                        county_intersection_query.intersection_area
                        / county_intersection_query.total_county_area
                    ) * 100
                    county_coverage = min(100.0, max(0.0, county_coverage))

                coverage_data['county'] = {
                    'coverage_percentage': round(county_coverage, 1),
                    'total_area_sqm': county_intersection_query.total_county_area,
                    'intersected_area_sqm': county_intersection_query.intersection_area,
                }

    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.error('Error calculating coverage percentages: %s', exc)

    return coverage_data


def register(app, logger):
    """Register legacy administrative and audio routes on the Flask app."""
    @app.route('/audio')
    def audio_history():
        try:
            eas_enabled = app.config.get('EAS_BROADCAST_ENABLED', False)
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 25, type=int)
            per_page = min(max(per_page, 10), 100)

            search = request.args.get('search', '').strip()
            event_filter = request.args.get('event', '').strip()
            severity_filter = request.args.get('severity', '').strip()
            status_filter = request.args.get('status', '').strip()

            base_query = db.session.query(EASMessage, CAPAlert).outerjoin(
                CAPAlert, EASMessage.cap_alert_id == CAPAlert.id
            )

            if search:
                search_term = f'%{search}%'
                base_query = base_query.filter(
                    or_(
                        CAPAlert.event.ilike(search_term),
                        CAPAlert.headline.ilike(search_term),
                        CAPAlert.identifier.ilike(search_term),
                        EASMessage.same_header.ilike(search_term),
                    )
                )

            if event_filter:
                base_query = base_query.filter(CAPAlert.event == event_filter)
            if severity_filter:
                base_query = base_query.filter(CAPAlert.severity == severity_filter)
            if status_filter:
                base_query = base_query.filter(CAPAlert.status == status_filter)

            query = base_query.order_by(EASMessage.created_at.desc())

            manual_query = ManualEASActivation.query
            include_manual = True

            if search:
                search_term = f'%{search}%'
                manual_query = manual_query.filter(
                    or_(
                        ManualEASActivation.event_name.ilike(search_term),
                        ManualEASActivation.event_code.ilike(search_term),
                        ManualEASActivation.identifier.ilike(search_term),
                        ManualEASActivation.same_header.ilike(search_term),
                    )
                )
            if event_filter:
                manual_query = manual_query.filter(
                    or_(
                        ManualEASActivation.event_name == event_filter,
                        ManualEASActivation.event_code == event_filter,
                    )
                )
            if status_filter:
                manual_query = manual_query.filter(ManualEASActivation.status == status_filter)
            if severity_filter:
                include_manual = False

            if include_manual:
                manual_query = manual_query.order_by(ManualEASActivation.created_at.desc())

            automated_total = query.order_by(None).count()
            manual_total = manual_query.order_by(None).count() if include_manual else 0
            total_count = automated_total + manual_total

            total_pages = max(1, math.ceil(total_count / per_page)) if per_page else 1
            page = max(1, min(page, total_pages))
            offset = (page - 1) * per_page
            fetch_limit = offset + per_page

            automated_records = query.limit(fetch_limit).all() if fetch_limit else []
            manual_records: List[ManualEASActivation] = []
            if include_manual and fetch_limit:
                manual_records = manual_query.limit(fetch_limit).all()

            web_prefix = get_eas_static_prefix()

            def _static_path(filename: Optional[str]) -> Optional[str]:
                if not filename:
                    return None
                parts = [web_prefix, filename] if web_prefix else [filename]
                return '/'.join(part for part in parts if part)

            def _manual_web_path(subpath: Optional[str], *, fallback_prefix: Optional[str] = None) -> Optional[str]:
                if not subpath:
                    return None
                effective_prefix = fallback_prefix if fallback_prefix is not None else web_prefix
                parts = [effective_prefix, subpath] if effective_prefix else [subpath]
                return '/'.join(part for part in parts if part)

            def _sort_key(value: Optional[datetime]) -> datetime:
                if value is None:
                    return datetime.min.replace(tzinfo=timezone.utc)
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

            messages: List[Dict[str, Any]] = []
            for message, alert in automated_records:
                metadata = dict(message.metadata_payload or {})
                event_name = (alert.event if alert and alert.event else metadata.get('event')) or 'Unknown Event'
                severity = alert.severity if alert and alert.severity else metadata.get('severity')
                status = alert.status if alert and alert.status else metadata.get('status')
                eom_filename = metadata.get('eom_filename')
                has_eom_data = bool(message.eom_audio_data) or bool(eom_filename)

                audio_url = url_for('eas_message_audio', message_id=message.id) if message.id else None
                if message.text_payload:
                    text_url = url_for('eas_message_summary', message_id=message.id)
                else:
                    text_path = _static_path(message.text_filename)
                    text_url = url_for('static', filename=text_path) if text_path else None

                if has_eom_data:
                    eom_url = url_for('eas_message_audio', message_id=message.id, variant='eom')
                else:
                    eom_path = _static_path(eom_filename) if eom_filename else None
                    eom_url = url_for('static', filename=eom_path) if eom_path else None

                messages.append({
                    'id': message.id,
                    'event': event_name,
                    'severity': severity,
                    'status': status,
                    'created_at': message.created_at,
                    'same_header': message.same_header,
                    'audio_url': audio_url,
                    'text_url': text_url,
                    'detail_url': url_for('audio_detail', message_id=message.id),
                    'alert_url': url_for('alert_detail', alert_id=alert.id) if alert else None,
                    'alert_identifier': alert.identifier if alert else None,
                    'eom_url': eom_url,
                    'source': 'automated',
                    'alert_label': 'View Alert',
                })

            if include_manual and manual_records:
                for event in manual_records:
                    metadata = dict(event.metadata_payload or {})
                    components_payload = event.components_payload or {}
                    manual_prefix = metadata.get('web_prefix', web_prefix)

                    composite_component = components_payload.get('composite')
                    audio_component = (
                        composite_component
                        or components_payload.get('tts')
                        or components_payload.get('attention')
                        or components_payload.get('same')
                    )
                    eom_component = components_payload.get('eom')

                    audio_subpath = audio_component.get('storage_subpath') if audio_component else None
                    audio_url = (
                        url_for(
                            'static',
                            filename=_manual_web_path(
                                audio_subpath,
                                fallback_prefix=manual_prefix,
                            ),
                        )
                        if audio_subpath
                        else None
                    )

                    summary_subpath = metadata.get('summary_subpath') or (
                        '/'.join(part for part in [event.storage_path, event.summary_filename] if part)
                        if event.summary_filename
                        else None
                    )
                    summary_url = (
                        url_for(
                            'static',
                            filename=_manual_web_path(
                                summary_subpath,
                                fallback_prefix=manual_prefix,
                            ),
                        )
                        if summary_subpath
                        else None
                    )

                    eom_subpath = eom_component.get('storage_subpath') if eom_component else None
                    eom_url = (
                        url_for(
                            'static',
                            filename=_manual_web_path(
                                eom_subpath,
                                fallback_prefix=manual_prefix,
                            ),
                        )
                        if eom_subpath
                        else None
                    )

                    messages.append({
                        'id': event.id,
                        'event': event.event_name or event.event_code or 'Manual Activation',
                        'severity': metadata.get('severity'),
                        'status': event.status,
                        'created_at': event.created_at,
                        'same_header': event.same_header,
                        'audio_url': audio_url,
                        'text_url': summary_url,
                        'detail_url': url_for('manual_eas_print', event_id=event.id),
                        'alert_url': url_for('manual_eas_print', event_id=event.id),
                        'alert_identifier': event.identifier,
                        'eom_url': eom_url,
                        'source': 'manual',
                        'alert_label': 'View Activation',
                    })

            messages.sort(key=lambda item: _sort_key(item.get('created_at')), reverse=True)
            page_start = offset
            page_end = offset + per_page
            messages = messages[page_start:page_end]

            class CombinedPagination:
                def __init__(self, page_number: int, page_size: int, total_items: int):
                    self.page = page_number
                    self.per_page = page_size
                    self.total = total_items
                    self.pages = max(1, math.ceil(total_items / page_size)) if page_size else 1
                    self.has_prev = self.page > 1
                    self.has_next = self.page < self.pages
                    self.prev_num = self.page - 1 if self.has_prev else None
                    self.next_num = self.page + 1 if self.has_next else None

                def iter_pages(self, left_edge: int = 2, left_current: int = 2, right_current: int = 3, right_edge: int = 2):
                    last = self.pages
                    for num in range(1, last + 1):
                        if num <= left_edge or (
                            self.page - left_current - 1 < num < self.page + right_current
                        ) or num > last - right_edge:
                            yield num
                        elif num == left_edge + 1 or num == self.page + right_current:
                            yield None

            pagination = CombinedPagination(page, per_page, total_count)

            try:
                cap_events = [
                    row[0]
                    for row in db.session.query(CAPAlert.event)
                    .join(EASMessage, EASMessage.cap_alert_id == CAPAlert.id)
                    .filter(CAPAlert.event.isnot(None))
                    .distinct()
                    .order_by(CAPAlert.event)
                    .all()
                ]

                cap_severities = [
                    row[0]
                    for row in db.session.query(CAPAlert.severity)
                    .join(EASMessage, EASMessage.cap_alert_id == CAPAlert.id)
                    .filter(CAPAlert.severity.isnot(None))
                    .distinct()
                    .order_by(CAPAlert.severity)
                    .all()
                ]

                cap_statuses = [
                    row[0]
                    for row in db.session.query(CAPAlert.status)
                    .join(EASMessage, EASMessage.cap_alert_id == CAPAlert.id)
                    .filter(CAPAlert.status.isnot(None))
                    .distinct()
                    .order_by(CAPAlert.status)
                    .all()
                ]

                manual_event_names = [
                    row[0]
                    for row in db.session.query(ManualEASActivation.event_name)
                    .filter(ManualEASActivation.event_name.isnot(None))
                    .distinct()
                    .order_by(ManualEASActivation.event_name)
                    .all()
                ]

                manual_statuses = [
                    row[0]
                    for row in db.session.query(ManualEASActivation.status)
                    .filter(ManualEASActivation.status.isnot(None))
                    .distinct()
                    .order_by(ManualEASActivation.status)
                    .all()
                ]

                events = sorted({value for value in cap_events + manual_event_names if value})
                severities = sorted({value for value in cap_severities if value})
                statuses = sorted({value for value in cap_statuses + manual_statuses if value})
            except Exception as filter_error:
                logger.warning('Unable to load audio filter metadata: %s', filter_error)
                events = []
                severities = []
                statuses = []

            current_filters = {
                'search': search,
                'event': event_filter,
                'severity': severity_filter,
                'status': status_filter,
                'per_page': per_page,
            }

            total_messages = EASMessage.query.count() + ManualEASActivation.query.count()

            return render_template(
                'audio_history.html',
                messages=messages,
                pagination=pagination,
                events=events,
                severities=severities,
                statuses=statuses,
                current_filters=current_filters,
                total_messages=total_messages,
                eas_enabled=eas_enabled,
            )

        except Exception as exc:
            logger.error('Error loading audio archive: %s', exc)
            return render_template_string(
                """
                <h1>Error Loading Audio Archive</h1>
                <div class=\"alert alert-danger\">{{ error }}</div>
                <p><a href='/' class='btn btn-primary'>← Back to Main</a></p>
                """,
                error=str(exc),
            )


    @app.route('/audio/<int:message_id>')
    def audio_detail(message_id: int):
        try:
            message = EASMessage.query.get_or_404(message_id)
            alert = CAPAlert.query.get(message.cap_alert_id) if message.cap_alert_id else None
            metadata = dict(message.metadata_payload or {})
            event_name = (alert.event if alert and alert.event else metadata.get('event')) or 'Unknown Event'
            severity = alert.severity if alert and alert.severity else metadata.get('severity')
            status = alert.status if alert and alert.status else metadata.get('status')
            same_locations = metadata.get('locations')
            if isinstance(same_locations, list):
                locations = same_locations
            elif same_locations is None:
                locations = []
            else:
                locations = [str(same_locations)]

            eom_filename = metadata.get('eom_filename')
            has_eom_data = bool(message.eom_audio_data) or bool(eom_filename)

            audio_url = url_for('eas_message_audio', message_id=message.id)
            if message.text_payload:
                text_url = url_for('eas_message_summary', message_id=message.id)
            else:
                static_prefix = get_eas_static_prefix()
                text_url = None
                if message.text_filename:
                    static_path = '/'.join(part for part in [static_prefix, message.text_filename] if part)
                    text_url = url_for('static', filename=static_path) if static_path else None

            if has_eom_data:
                eom_url = url_for('eas_message_audio', message_id=message.id, variant='eom')
            elif eom_filename:
                eom_path = '/'.join(part for part in [get_eas_static_prefix(), eom_filename] if part)
                eom_url = url_for('static', filename=eom_path) if eom_path else None
            else:
                eom_url = None

            summary_data = load_or_cache_summary_payload(message)

            return render_template(
                'audio_detail.html',
                message=message,
                alert=alert,
                metadata=metadata,
                summary_data=summary_data,
                audio_url=audio_url,
                text_url=text_url,
                eom_url=eom_url,
                event_name=event_name,
                severity=severity,
                status=status,
                locations=locations,
            )

        except Exception as exc:
            logger.error('Error loading audio detail %s: %s', message_id, exc)
            flash('Unable to load audio detail at this time.', 'error')
            return redirect(url_for('audio_history'))


    @app.route('/api/alerts/<int:alert_id>/geometry')
    def get_alert_geometry(alert_id):
        """Get specific alert geometry and intersecting boundaries as GeoJSON"""
        try:
            # Get the alert with geometry
            alert = db.session.query(
                CAPAlert.id, CAPAlert.identifier, CAPAlert.event, CAPAlert.severity,
                CAPAlert.urgency, CAPAlert.headline, CAPAlert.description, CAPAlert.expires,
                CAPAlert.sent, CAPAlert.area_desc, CAPAlert.status,
                func.ST_AsGeoJSON(CAPAlert.geom).label('geometry')
            ).filter(CAPAlert.id == alert_id).first()

            if not alert:
                return jsonify({'error': 'Alert not found'}), 404

            # Get county boundary for fallback
            county_boundary = None
            try:
                county_geom = db.session.query(
                    func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                ).filter(Boundary.type == 'county').first()

                if county_geom and county_geom.geometry:
                    county_boundary = json.loads(county_geom.geometry)
            except Exception as e:
                logger.warning(f"Could not get county boundary: {str(e)}")

            # Determine geometry and county-wide status
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

            # Get intersecting boundaries
            intersecting_boundaries = []
            if geometry:
                intersections = db.session.query(Intersection, Boundary).join(
                    Boundary, Intersection.boundary_id == Boundary.id
                ).filter(Intersection.cap_alert_id == alert_id).all()

                # Convert intersecting boundaries to GeoJSON features
                for intersection, boundary in intersections:
                    boundary_geom = db.session.query(
                        func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                    ).filter(Boundary.id == boundary.id).first()

                    if boundary_geom and boundary_geom.geometry:
                        intersecting_boundaries.append({
                            'type': 'Feature',
                            'properties': {
                                'id': boundary.id,
                                'name': boundary.name,
                                'type': boundary.type,
                                'description': boundary.description,
                                'intersection_area': intersection.intersection_area
                            },
                            'geometry': json.loads(boundary_geom.geometry)
                        })

            # Format dates
            expires_iso = None
            if alert.expires:
                if alert.expires.tzinfo is None:
                    expires_dt = alert.expires.replace(tzinfo=UTC_TZ)
                else:
                    expires_dt = alert.expires.astimezone(UTC_TZ)
                expires_iso = expires_dt.isoformat()

            sent_iso = None
            if alert.sent:
                if alert.sent.tzinfo is None:
                    sent_dt = alert.sent.replace(tzinfo=UTC_TZ)
                else:
                    sent_dt = alert.sent.astimezone(UTC_TZ)
                sent_iso = sent_dt.isoformat()

            # Build response
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
                        'is_county_wide': is_county_wide
                    },
                    'geometry': geometry
                } if geometry else None,
                'intersecting_boundaries': {
                    'type': 'FeatureCollection',
                    'features': intersecting_boundaries
                }
            }

            return jsonify(response_data)

        except Exception as e:
            logger.error(f"Error getting alert geometry: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/alerts/<int:alert_id>')
    def alert_detail(alert_id):
        """Show detailed information about a specific alert with accurate coverage calculation"""
        try:
            alert = CAPAlert.query.get_or_404(alert_id)

            # Get intersections
            intersections = db.session.query(Intersection, Boundary).join(
                Boundary, Intersection.boundary_id == Boundary.id
            ).filter(Intersection.cap_alert_id == alert_id).all()

            # Determine if this should be considered county-wide based on area description
            is_county_wide = False
            if alert.area_desc:
                area_lower = alert.area_desc.lower()
                is_county_wide = (
                    'putnam county' in area_lower or
                    'entire county' in area_lower or
                    ('county' in area_lower and 'ohio' in area_lower) or
                    ('putnam' in area_lower and (area_lower.count(';') >= 2 or area_lower.count(',') >= 2))
                )

            # Calculate actual coverage percentages
            coverage_data = calculate_coverage_percentages(alert_id, intersections)

            # Determine actual coverage status
            county_coverage = coverage_data.get('county', {}).get('coverage_percentage', 0)
            is_actually_county_wide = county_coverage >= 95.0  # Consider 95%+ as county-wide

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

                    audio_entries.append({
                        'id': message.id,
                        'created_at': message.created_at,
                        'same_header': message.same_header,
                        'audio_url': audio_url,
                        'text_url': text_url,
                        'detail_url': url_for('audio_detail', message_id=message.id),
                        'metadata': metadata,
                        'eom_url': eom_url,
                    })
            except Exception as audio_error:
                logger.warning('Unable to load audio archive for alert %s: %s', alert.identifier, audio_error)

            return render_template('alert_detail.html',
                                 alert=alert,
                                 intersections=intersections,
                                 is_county_wide=is_county_wide,
                                 is_actually_county_wide=is_actually_county_wide,
                                 coverage_data=coverage_data,
                                 audio_entries=audio_entries)

        except Exception as e:
            logger.error(f"Error in alert_detail route: {str(e)}")
            flash(f'Error loading alert details: {str(e)}', 'error')
            return redirect(url_for('index'))


    # =============================================================================
    # API ROUTES
    # =============================================================================

    @app.route('/api/alerts')
    def get_alerts():
        """Get CAP alerts as GeoJSON with optional inclusion of expired alerts"""
        try:
            # Check if we should include expired alerts
            include_expired = request.args.get('include_expired', 'false').lower() == 'true'

            # Use different query based on whether expired alerts are requested
            if include_expired:
                # Get ALL alerts (active and expired)
                alerts_query = CAPAlert.query
                logger.info("Including expired alerts in API response")
            else:
                # Get only active alerts (existing behavior)
                alerts_query = get_active_alerts_query()
                logger.info("Including only active alerts in API response")

            alerts = db.session.query(
                CAPAlert.id, CAPAlert.identifier, CAPAlert.event, CAPAlert.severity,
                CAPAlert.urgency, CAPAlert.headline, CAPAlert.description, CAPAlert.expires,
                CAPAlert.area_desc, func.ST_AsGeoJSON(CAPAlert.geom).label('geometry')
            ).filter(
                CAPAlert.id.in_(alerts_query.with_entities(CAPAlert.id).subquery())
            ).all()

            # Get the actual county boundary geometry for fallback
            county_boundary = None
            try:
                county_geom = db.session.query(
                    func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                ).filter(
                    Boundary.type == 'county'
                ).first()

                if county_geom and county_geom.geometry:
                    county_boundary = json.loads(county_geom.geometry)
            except Exception as e:
                logger.warning(f"Could not get county boundary: {str(e)}")

            features = []
            for alert in alerts:
                # Use existing geometry or fall back to county boundary
                geometry = None
                is_county_wide = False

                if alert.geometry:
                    geometry = json.loads(alert.geometry)
                elif alert.area_desc and any(county_term in alert.area_desc.lower()
                                             for county_term in ['county', 'putnam', 'ohio']):
                    # Use actual county boundary if available
                    if county_boundary:
                        geometry = county_boundary
                        is_county_wide = True

                # Check if this should be marked as county-wide based on area description
                if not is_county_wide and alert.area_desc:
                    area_lower = alert.area_desc.lower()

                    # Multi-county alerts that include the configured county should be treated as county-wide
                    if 'putnam' in area_lower:
                        # Count counties (semicolons or commas usually separate them)
                        separator_count = max(area_lower.count(';'), area_lower.count(','))
                        if separator_count >= 2:  # 3+ counties = treat as county-wide
                            is_county_wide = True

                    # Direct county-wide keywords
                    county_keywords = ['county', 'putnam county', 'entire county']
                    if any(keyword in area_lower for keyword in county_keywords):
                        is_county_wide = True

                if geometry:
                    # Convert expires to ISO format for JavaScript (will be in UTC)
                    expires_iso = None
                    if alert.expires:
                        if alert.expires.tzinfo is None:
                            expires_dt = alert.expires.replace(tzinfo=UTC_TZ)
                        else:
                            expires_dt = alert.expires.astimezone(UTC_TZ)
                        expires_iso = expires_dt.isoformat()

                    features.append({
                        'type': 'Feature',
                        'properties': {
                            'id': alert.id,
                            'identifier': alert.identifier,
                            'event': alert.event,
                            'severity': alert.severity,
                            'urgency': alert.urgency,
                            'headline': alert.headline,
                            'description': alert.description[:500] + '...' if len(
                                alert.description) > 500 else alert.description,
                            'area_desc': alert.area_desc,
                            'expires_iso': expires_iso,
                            'is_county_wide': is_county_wide,
                            'is_expired': is_alert_expired(alert.expires)  # Add expiration status
                        },
                        'geometry': geometry
                    })

            logger.info(f"Returning {len(features)} alerts (include_expired={include_expired})")

            return jsonify({
                'type': 'FeatureCollection',
                'features': features,
                'metadata': {
                    'total_features': len(features),
                    'include_expired': include_expired,
                    'generated_at': utc_now().isoformat()
                }
            })

        except Exception as e:
            logger.error(f"Error getting alerts: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/alerts/historical')
    def get_historical_alerts():
        """Get historical alerts as GeoJSON with date filtering"""
        try:
            # Get query parameters
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            include_active = request.args.get('include_active', 'false').lower() == 'true'

            # Base query - all alerts or just expired
            if include_active:
                query = CAPAlert.query
            else:
                query = get_expired_alerts_query()

            # Apply date filters
            if start_date:
                start_dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC_TZ)
                query = query.filter(CAPAlert.sent >= start_dt)

            if end_date:
                end_dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC_TZ)
                query = query.filter(CAPAlert.sent <= end_dt)

            # Get alerts with geometry
            alerts = db.session.query(
                CAPAlert.id, CAPAlert.identifier, CAPAlert.event, CAPAlert.severity,
                CAPAlert.urgency, CAPAlert.headline, CAPAlert.description, CAPAlert.expires,
                CAPAlert.sent, CAPAlert.area_desc, func.ST_AsGeoJSON(CAPAlert.geom).label('geometry')
            ).filter(
                CAPAlert.id.in_(query.with_entities(CAPAlert.id).subquery())
            ).all()

            # Get county boundary for fallback
            county_boundary = None
            try:
                county_geom = db.session.query(
                    func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                ).filter(Boundary.type == 'county').first()

                if county_geom and county_geom.geometry:
                    county_boundary = json.loads(county_geom.geometry)
            except Exception as e:
                logger.warning(f"Could not get county boundary: {str(e)}")

            # Build GeoJSON features
            features = []
            for alert in alerts:
                geometry = None
                is_county_wide = False

                if alert.geometry:
                    geometry = json.loads(alert.geometry)
                elif alert.area_desc and any(county_term in alert.area_desc.lower()
                                             for county_term in ['county', 'putnam', 'ohio']):
                    if county_boundary:
                        geometry = county_boundary
                        is_county_wide = True

                if geometry:
                    expires_iso = None
                    if alert.expires:
                        if alert.expires.tzinfo is None:
                            expires_dt = alert.expires.replace(tzinfo=UTC_TZ)
                        else:
                            expires_dt = alert.expires.astimezone(UTC_TZ)
                        expires_iso = expires_dt.isoformat()

                    sent_iso = None
                    if alert.sent:
                        if alert.sent.tzinfo is None:
                            sent_dt = alert.sent.replace(tzinfo=UTC_TZ)
                        else:
                            sent_dt = alert.sent.astimezone(UTC_TZ)
                        sent_iso = sent_dt.isoformat()

                    features.append({
                        'type': 'Feature',
                        'properties': {
                            'id': alert.id,
                            'identifier': alert.identifier,
                            'event': alert.event,
                            'severity': alert.severity,
                            'urgency': alert.urgency,
                            'headline': alert.headline,
                            'description': alert.description[:500] + '...' if len(
                                alert.description) > 500 else alert.description,
                            'sent': sent_iso,
                            'expires': expires_iso,
                            'area_desc': alert.area_desc,
                            'is_historical': True,
                            'is_county_wide': is_county_wide
                        },
                        'geometry': geometry
                    })

            return jsonify({
                'type': 'FeatureCollection',
                'features': features
            })

        except Exception as e:
            logger.error(f"Error getting historical alerts: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/boundaries')
    def get_boundaries():
        """Get all boundaries as GeoJSON"""
        try:
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 1000, type=int)
            boundary_type = request.args.get('type')
            search = request.args.get('search')

            query = db.session.query(
                Boundary.id, Boundary.name, Boundary.type, Boundary.description,
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            )

            if boundary_type:
                normalized_type = normalize_boundary_type(boundary_type)
                query = query.filter(func.lower(Boundary.type) == normalized_type)

            if search:
                query = query.filter(Boundary.name.ilike(f'%{search}%'))

            boundaries = query.paginate(
                page=page, per_page=per_page, error_out=False
            ).items

            features = []
            for boundary in boundaries:
                if boundary.geometry:
                    normalized_type = normalize_boundary_type(boundary.type)
                    features.append({
                        'type': 'Feature',
                        'properties': {
                            'id': boundary.id,
                            'name': boundary.name,
                            'type': normalized_type,
                            'raw_type': boundary.type,
                            'display_type': get_boundary_display_label(boundary.type),
                            'group': get_boundary_group(boundary.type),
                            'color': get_boundary_color(boundary.type),
                            'description': boundary.description
                        },
                        'geometry': json.loads(boundary.geometry)
                    })

            return jsonify({
                'type': 'FeatureCollection',
                'features': features
            })
        except Exception as e:
            logger.error(f"Error fetching boundaries: {str(e)}")
            return jsonify({'error': str(e)}), 500


    @app.route('/api/system_status')
    def api_system_status():
        """Get system status information using new helper functions with timezone support"""
        try:
            total_boundaries = Boundary.query.count()
            active_alerts = get_active_alerts_query().count()

            last_poll = PollHistory.query.order_by(desc(PollHistory.timestamp)).first()

            cpu = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            current_utc = utc_now()
            current_local = local_now()

            location_tz = get_location_timezone()
            return jsonify({
                'status': 'online',
                'timestamp': current_utc.isoformat(),
                'local_timestamp': current_local.isoformat(),
                'timezone': get_location_timezone_name(),
                'boundaries_count': total_boundaries,
                'active_alerts_count': active_alerts,
                'database_status': 'connected',
                'last_poll': {
                    'timestamp': last_poll.timestamp.isoformat() if last_poll else None,
                    'local_timestamp': last_poll.timestamp.astimezone(location_tz).isoformat() if last_poll else None,
                    'status': last_poll.status if last_poll else None,
                    'alerts_fetched': last_poll.alerts_fetched if last_poll else 0,
                    'alerts_new': last_poll.alerts_new if last_poll else 0
                } if last_poll else None,
                'system_resources': {
                    'cpu_usage_percent': cpu,
                    'memory_usage_percent': memory.percent,
                    'disk_usage_percent': disk.percent,
                    'disk_free_gb': disk.free // (1024 * 1024 * 1024)
                }
            })
        except Exception as e:
            logger.error(f"Error getting system status: {str(e)}")
            return jsonify({'error': f'Failed to get system status: {str(e)}'}), 500


    @app.route('/api/system_health')
    def api_system_health():
        """Get comprehensive system health information via API"""
        try:
            health_data = get_system_health()
            return jsonify(health_data)
        except Exception as e:
            logger.error(f"Error getting system health via API: {str(e)}")
            return jsonify({'error': str(e)}), 500


    # =============================================================================
    # ADMINISTRATIVE ROUTES
    # =============================================================================

    # =============================================================================
    # AUTHENTICATION ROUTES
    # =============================================================================


    def _is_safe_redirect_target(target: Optional[str]) -> bool:
        if not target:
            return False
        ref_url = urlparse(request.host_url)
        test_url = urlparse(urljoin(request.host_url, target))
        return (
            test_url.scheme in ('http', 'https')
            and ref_url.netloc == test_url.netloc
        )


    @app.route('/login', methods=['GET', 'POST'])
    def login():
        next_param = request.args.get('next') if request.method == 'GET' else request.form.get('next')
        if g.current_user:
            target = next_param if _is_safe_redirect_target(next_param) else url_for('admin')
            return redirect(target)

        error = None
        if request.method == 'POST':
            username = (request.form.get('username') or '').strip()
            password = request.form.get('password') or ''

            if not username or not password:
                error = 'Username and password are required.'
            else:
                user = AdminUser.query.filter(
                    func.lower(AdminUser.username) == username.lower()
                ).first()
                if user and user.is_active and user.check_password(password):
                    session['user_id'] = user.id
                    session.permanent = True
                    user.last_login_at = utc_now()
                    log_entry = SystemLog(
                        level='INFO',
                        message='Administrator logged in',
                        module='auth',
                        details={
                            'username': user.username,
                            'remote_addr': request.remote_addr,
                        },
                    )
                    db.session.add(user)
                    db.session.add(log_entry)
                    db.session.commit()

                    target = next_param if _is_safe_redirect_target(next_param) else url_for('admin')
                    return redirect(target)

                db.session.add(SystemLog(
                    level='WARNING',
                    message='Failed administrator login attempt',
                    module='auth',
                    details={
                        'username': username,
                        'remote_addr': request.remote_addr,
                    },
                ))
                db.session.commit()
                error = 'Invalid username or password.'

        show_setup = AdminUser.query.count() == 0

        return render_template(
            'login.html',
            error=error,
            next=next_param or url_for('admin'),
            show_setup=show_setup,
        )


    @app.route('/logout')
    def logout():
        user = g.current_user
        if user:
            db.session.add(SystemLog(
                level='INFO',
                message='Administrator logged out',
                module='auth',
                details={
                    'username': user.username,
                    'remote_addr': request.remote_addr,
                },
            ))
            db.session.commit()
        session.pop('user_id', None)
        flash('You have been signed out.')
        return redirect(url_for('login'))


    @app.route('/admin')
    def admin():
        """Admin interface"""
        try:
            setup_mode = getattr(g, 'admin_setup_mode', None)
            if setup_mode is None:
                setup_mode = AdminUser.query.count() == 0
            total_boundaries = Boundary.query.count()
            total_alerts = CAPAlert.query.count()
            active_alerts = get_active_alerts_query().count()
            expired_alerts = get_expired_alerts_query().count()

            boundary_stats = db.session.query(
                Boundary.type, func.count(Boundary.id).label('count')
            ).group_by(Boundary.type).all()

            location_settings = get_location_settings()
            manual_same_defaults = manual_default_same_codes()
            location_settings_view = dict(location_settings)
            location_settings_view.setdefault('same_codes', manual_same_defaults)

            eas_enabled = app.config.get('EAS_BROADCAST_ENABLED', False)
            total_eas_messages = EASMessage.query.count() if eas_enabled else 0
            recent_eas_messages = []
            if eas_enabled:
                recent_eas_messages = (
                    EASMessage.query.order_by(EASMessage.created_at.desc()).limit(10).all()
                )

            eas_event_options = [
                {'code': code, 'name': entry.get('name', code)}
                for code, entry in EVENT_CODE_REGISTRY.items()
                if '?' not in code
            ]
            eas_event_options.sort(key=lambda item: item['code'])

            eas_state_tree = get_us_state_county_tree()
            eas_lookup = get_same_lookup()
            originator_choices = [
                {
                    'code': code,
                    'description': ORIGINATOR_DESCRIPTIONS.get(code, ''),
                }
                for code in PRIMARY_ORIGINATORS
            ]

            return render_template('admin.html',
                                   total_boundaries=total_boundaries,
                                   total_alerts=total_alerts,
                                   active_alerts=active_alerts,
                                   expired_alerts=expired_alerts,
                                   boundary_stats=boundary_stats,
                                   location_settings=location_settings_view,
                                   eas_enabled=eas_enabled,
                                   eas_total_messages=total_eas_messages,
                                   eas_recent_messages=recent_eas_messages,
                                   eas_web_subdir=app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages'),
                                   eas_event_codes=eas_event_options,
                                   eas_originator=EAS_CONFIG.get('originator', 'WXR'),
                                   eas_station_id=EAS_CONFIG.get('station_id', 'EASNODES'),
                                   eas_attention_seconds=EAS_CONFIG.get('attention_tone_seconds', 8),
                                   eas_sample_rate=EAS_CONFIG.get('sample_rate', 44100),
                                   eas_tts_provider=(EAS_CONFIG.get('tts_provider') or '').strip().lower(),
                                   eas_fips_states=eas_state_tree,
                                   eas_fips_lookup=eas_lookup,
                                   eas_originator_descriptions=ORIGINATOR_DESCRIPTIONS,
                                   eas_originator_choices=originator_choices,
                                   eas_header_fields=SAME_HEADER_FIELD_DESCRIPTIONS,
                                   eas_p_digit_meanings=P_DIGIT_MEANINGS,
                                   eas_default_same_codes=manual_same_defaults,
                                   setup_mode=setup_mode,
                                   )
        except Exception as e:
            logger.error(f"Error rendering admin template: {str(e)}")
            return f"<h1>Admin Interface</h1><p>Admin panel loading...</p><p><a href='/'>← Back to Main</a></p>"


    @app.route('/admin/users', methods=['GET', 'POST'])
    def admin_users():
        if request.method == 'GET':
            users = AdminUser.query.order_by(AdminUser.username.asc()).all()
            return jsonify({'users': [user.to_safe_dict() for user in users]})

        payload = request.get_json(silent=True) or {}
        username = (payload.get('username') or '').strip()
        password = payload.get('password') or ''

        creating_first_user = AdminUser.query.count() == 0
        if g.current_user is None and not creating_first_user:
            return jsonify({'error': 'Authentication required.'}), 401

        if not username or not password:
            return jsonify({'error': 'Username and password are required.'}), 400

        if not USERNAME_PATTERN.match(username):
            return jsonify({'error': 'Usernames must be 3-64 characters and may include letters, numbers, dots, underscores, and hyphens.'}), 400

        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

        existing = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first()
        if existing:
            return jsonify({'error': 'Username already exists.'}), 400

        new_user = AdminUser(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.add(SystemLog(
            level='INFO',
            message='Administrator account created',
            module='auth',
            details={
                'username': new_user.username,
                'created_by': g.current_user.username if g.current_user else 'initial_setup',
            },
        ))
        db.session.commit()

        return jsonify({'message': 'User created successfully.', 'user': new_user.to_safe_dict()}), 201


    @app.route('/admin/users/<int:user_id>', methods=['PATCH', 'DELETE'])
    def admin_user_detail(user_id: int):
        user = AdminUser.query.get_or_404(user_id)

        if request.method == 'PATCH':
            payload = request.get_json(silent=True) or {}
            password = payload.get('password') or ''
            if len(password) < 8:
                return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

            user.set_password(password)
            db.session.add(user)
            db.session.add(SystemLog(
                level='INFO',
                message='Administrator password reset',
                module='auth',
                details={
                    'username': user.username,
                    'updated_by': g.current_user.username if g.current_user else None,
                },
            ))
            db.session.commit()
            return jsonify({'message': 'Password updated successfully.', 'user': user.to_safe_dict()})

        if user.id == getattr(g.current_user, 'id', None):
            return jsonify({'error': 'You cannot delete your own account while logged in.'}), 400

        active_users = AdminUser.query.filter(AdminUser.is_active.is_(True)).count()
        if user.is_active and active_users <= 1:
            return jsonify({'error': 'At least one active administrator account is required.'}), 400

        db.session.delete(user)
        db.session.add(SystemLog(
            level='WARNING',
            message='Administrator account deleted',
            module='auth',
            details={
                'username': user.username,
                'deleted_by': g.current_user.username if g.current_user else None,
            },
        ))
        db.session.commit()
        return jsonify({'message': 'User deleted successfully.'})


    @app.route('/eas_messages/<int:message_id>/audio', methods=['GET'])
    def eas_message_audio(message_id: int):
        variant = (request.args.get('variant') or 'primary').strip().lower()
        if variant not in {'primary', 'eom'}:
            abort(400, description='Unsupported audio variant.')

        message = EASMessage.query.get_or_404(message_id)
        data = load_or_cache_audio_data(message, variant=variant)
        if not data:
            abort(404, description='Audio not available.')

        download = request.args.get('download', '').strip().lower()
        as_attachment = download in {'1', 'true', 'yes', 'download'}

        if variant == 'eom':
            filename = (message.metadata_payload or {}).get('eom_filename') if message.metadata_payload else None
            if not filename:
                filename = f'eas_message_{message.id}_eom.wav'
        else:
            filename = message.audio_filename or f'eas_message_{message.id}.wav'

        file_obj = io.BytesIO(data)
        file_obj.seek(0)
        response = send_file(
            file_obj,
            mimetype='audio/wav',
            as_attachment=as_attachment,
            download_name=filename,
            max_age=0,
            conditional=False,
        )
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Accel-Buffering'] = 'no'
        return response


    @app.route('/eas_messages/<int:message_id>/summary', methods=['GET'])
    def eas_message_summary(message_id: int):
        message = EASMessage.query.get_or_404(message_id)
        payload = load_or_cache_summary_payload(message)
        if payload is None:
            abort(404, description='Summary not available.')

        body = json.dumps(payload, indent=2, ensure_ascii=False)
        response = app.response_class(body, mimetype='application/json')
        filename = message.text_filename or f'eas_message_{message.id}_summary.json'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response


    @app.route('/admin/eas_messages', methods=['GET'])
    def admin_eas_messages():
        if not app.config.get('EAS_BROADCAST_ENABLED', False):
            return jsonify({'messages': [], 'total': 0})

        try:
            limit = request.args.get('limit', type=int) or 50
            limit = min(max(limit, 1), 500)
            base_query = EASMessage.query.order_by(EASMessage.created_at.desc())
            messages = base_query.limit(limit).all()
            total = base_query.count()

            items = []
            for message in messages:
                data = message.to_dict()
                audio_url = url_for('eas_message_audio', message_id=message.id)
                if message.text_payload:
                    text_url = url_for('eas_message_summary', message_id=message.id)
                else:
                    static_prefix = get_eas_static_prefix()
                    text_path = '/'.join(part for part in [static_prefix, message.text_filename] if part)
                    text_url = url_for('static', filename=text_path) if text_path else None
                items.append({
                    **data,
                    'audio_url': audio_url,
                    'text_url': text_url,
                    'detail_url': url_for('audio_detail', message_id=message.id),
                })

            return jsonify({'messages': items, 'total': total})
        except Exception as exc:
            logger.error(f"Failed to list EAS messages: {exc}")
            return jsonify({'error': 'Unable to load EAS messages'}), 500


    @app.route('/admin/eas_messages/<int:message_id>', methods=['DELETE'])
    def admin_delete_eas_message(message_id: int):
        message = EASMessage.query.get_or_404(message_id)

        try:
            remove_eas_files(message)
            db.session.delete(message)
            db.session.add(SystemLog(
                level='WARNING',
                message='EAS message deleted',
                module='eas',
                details={
                    'message_id': message_id,
                    'deleted_by': getattr(g.current_user, 'username', None),
                },
            ))
            db.session.commit()
        except Exception as exc:
            logger.error(f"Failed to delete EAS message {message_id}: {exc}")
            db.session.rollback()
            return jsonify({'error': 'Failed to delete EAS message.'}), 500

        return jsonify({'message': 'EAS message deleted.', 'id': message_id})


    @app.route('/admin/eas_messages/purge', methods=['POST'])
    def admin_purge_eas_messages():
        if g.current_user is None:
            return jsonify({'error': 'Authentication required.'}), 401

        payload = request.get_json(silent=True) or {}

        ids = payload.get('ids')
        cutoff: Optional[datetime] = None

        if ids:
            try:
                id_list = [int(item) for item in ids if item is not None]
            except (TypeError, ValueError):
                return jsonify({'error': 'ids must be a list of integers.'}), 400
            query = EASMessage.query.filter(EASMessage.id.in_(id_list))
        else:
            before_text = payload.get('before')
            older_than_days = payload.get('older_than_days')

            if before_text:
                normalised = before_text.strip().replace('Z', '+00:00')
                try:
                    cutoff = datetime.fromisoformat(normalised)
                except ValueError:
                    return jsonify({'error': 'Unable to parse the provided cutoff timestamp.'}), 400
            elif older_than_days is not None:
                try:
                    days = int(older_than_days)
                except (TypeError, ValueError):
                    return jsonify({'error': 'older_than_days must be an integer.'}), 400
                if days < 0:
                    return jsonify({'error': 'older_than_days must be non-negative.'}), 400
                cutoff = utc_now() - timedelta(days=days)
            else:
                return jsonify({'error': 'Provide ids, before, or older_than_days to select messages to purge.'}), 400

            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            query = EASMessage.query.filter(EASMessage.created_at < cutoff)

        messages = query.all()
        if not messages:
            return jsonify({'message': 'No EAS messages matched the purge criteria.', 'deleted': 0})

        deleted_ids: List[int] = []
        for message in messages:
            deleted_ids.append(message.id)
            remove_eas_files(message)
            db.session.delete(message)

        try:
            db.session.add(SystemLog(
                level='WARNING',
                message='EAS messages purged',
                module='eas',
                details={
                    'deleted_ids': deleted_ids,
                    'deleted_by': getattr(g.current_user, 'username', None),
                },
            ))
            db.session.commit()
        except Exception as exc:
            logger.error(f"Failed to purge EAS messages: {exc}")
            db.session.rollback()
            return jsonify({'error': 'Failed to purge EAS messages.'}), 500

        return jsonify({'message': f'Deleted {len(deleted_ids)} EAS messages.', 'deleted': len(deleted_ids), 'ids': deleted_ids})


    @app.route('/admin/eas/manual_generate', methods=['POST'])
    def admin_manual_eas_generate():
        creating_first_user = AdminUser.query.count() == 0
        if g.current_user is None and not creating_first_user:
            return jsonify({'error': 'Authentication required.'}), 401

        payload = request.get_json(silent=True) or {}

        def _validation_error(message: str, status: int = 400):
            return jsonify({'error': message}), status

        identifier = (payload.get('identifier') or '').strip()[:120]
        if not identifier:
            identifier = f"MANUAL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        event_code = (payload.get('event_code') or '').strip().upper()
        if not event_code or len(event_code) != 3 or not event_code.isalnum():
            return _validation_error('Event code must be a three-character SAME identifier.')
        if event_code not in EVENT_CODE_REGISTRY or '?' in event_code:
            return _validation_error('Select a recognised SAME event code.')

        event_name = (payload.get('event_name') or '').strip()
        if not event_name:
            registry_entry = EVENT_CODE_REGISTRY.get(event_code)
            event_name = registry_entry.get('name', event_code) if registry_entry else event_code

        same_input = payload.get('same_codes')
        if isinstance(same_input, str):
            raw_codes = re.split(r'[^0-9]+', same_input)
        elif isinstance(same_input, list):
            raw_codes = []
            for item in same_input:
                if item is None:
                    continue
                raw_codes.extend(re.split(r'[^0-9]+', str(item)))
        else:
            raw_codes = []

        location_codes: List[str] = []
        for code in raw_codes:
            digits = ''.join(ch for ch in str(code) if ch.isdigit())
            if not digits:
                continue
            location_codes.append(digits.zfill(6)[:6])

        if not location_codes:
            return _validation_error('At least one SAME/FIPS location code is required.')

        try:
            duration_minutes = float(payload.get('duration_minutes', 15) or 15)
        except (TypeError, ValueError):
            return _validation_error('Duration must be a numeric value representing minutes.')
        if duration_minutes <= 0:
            return _validation_error('Duration must be greater than zero minutes.')

        tone_seconds_raw = payload.get('tone_seconds')
        if tone_seconds_raw in (None, '', 'null'):
            tone_seconds = None
        else:
            try:
                tone_seconds = float(tone_seconds_raw)
            except (TypeError, ValueError):
                return _validation_error('Tone duration must be numeric.')

        tone_profile_raw = (payload.get('tone_profile') or 'attention').strip().lower()
        if tone_profile_raw in {'none', 'omit', 'off', 'disabled'}:
            tone_profile = 'none'
        elif tone_profile_raw in {'1050', '1050hz', 'single'}:
            tone_profile = '1050hz'
        else:
            tone_profile = 'attention'

        if tone_profile == 'none':
            tone_seconds = 0.0
        elif tone_seconds is not None and tone_seconds <= 0:
            return _validation_error('Tone duration must be greater than zero seconds when a signal is included.')

        include_tts = bool(payload.get('include_tts', True))

        allowed_originators = set(PRIMARY_ORIGINATORS)
        originator = (payload.get('originator') or EAS_CONFIG.get('originator', 'WXR')).strip().upper() or 'WXR'
        if originator not in allowed_originators:
            return _validation_error('Originator must be one of the authorised SAME senders.')

        station_id = (payload.get('station_id') or EAS_CONFIG.get('station_id', 'EASNODES')).strip() or 'EASNODES'

        status = (payload.get('status') or 'Actual').strip() or 'Actual'
        message_type = (payload.get('message_type') or 'Alert').strip() or 'Alert'

        try:
            sample_rate = int(payload.get('sample_rate') or EAS_CONFIG.get('sample_rate', 44100) or 44100)
        except (TypeError, ValueError):
            return _validation_error('Sample rate must be an integer value.')
        if sample_rate < 8000 or sample_rate > 48000:
            return _validation_error('Sample rate must be between 8000 and 48000 Hz.')

        sent_dt = datetime.now(timezone.utc)
        expires_dt = sent_dt + timedelta(minutes=duration_minutes)

        manual_config = dict(EAS_CONFIG)
        manual_config['enabled'] = True
        manual_config['originator'] = originator[:3].upper()
        manual_config['station_id'] = station_id.upper().ljust(8)[:8]
        manual_config['attention_tone_seconds'] = tone_seconds if tone_seconds is not None else manual_config.get('attention_tone_seconds', 8)
        manual_config['sample_rate'] = sample_rate

        alert_object = SimpleNamespace(
            identifier=identifier,
            event=event_name or event_code,
            headline=(payload.get('headline') or '').strip(),
            description=(payload.get('message') or '').strip(),
            instruction=(payload.get('instruction') or '').strip(),
            sent=sent_dt,
            expires=expires_dt,
            status=status,
            message_type=message_type,
        )

        payload_wrapper: Dict[str, Any] = {
            'identifier': identifier,
            'sent': sent_dt,
            'expires': expires_dt,
            'status': status,
            'message_type': message_type,
            'raw_json': {
                'properties': {
                    'geocode': {
                        'SAME': location_codes,
                    }
                }
            },
        }

        try:
            header, formatted_locations, resolved_event_code = build_same_header(
                alert_object,
                payload_wrapper,
                manual_config,
                location_settings=None,
            )
            generator = EASAudioGenerator(manual_config, logger)
            components = generator.build_manual_components(
                alert_object,
                header,
                repeats=3,
                tone_profile=tone_profile,
                tone_duration=tone_seconds,
                include_tts=include_tts,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Failed to build manual EAS package: {exc}")
            return jsonify({'error': 'Unable to generate EAS audio components.'}), 500

        def _safe_base(value: str) -> str:
            cleaned = re.sub(r'[^A-Za-z0-9]+', '_', value).strip('_')
            return cleaned or 'manual_eas'

        base_name = _safe_base(identifier)
        sample_rate = components.get('sample_rate', sample_rate)

        output_root = str(manual_config.get('output_dir') or app.config.get('EAS_OUTPUT_DIR') or '').strip()
        if not output_root:
            logger.error('Manual EAS output directory is not configured.')
            return jsonify({'error': 'Manual EAS output directory is not configured.'}), 500

        manual_root = os.path.join(output_root, 'manual')
        os.makedirs(manual_root, exist_ok=True)

        timestamp_tag = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        slug = f"{base_name}_{timestamp_tag}"
        event_dir = os.path.join(manual_root, slug)
        os.makedirs(event_dir, exist_ok=True)
        storage_root = '/'.join(part for part in ['manual', slug] if part)
        web_prefix = app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')

        def _package_audio(samples: List[int], suffix: str) -> Optional[Dict[str, Any]]:
            if not samples:
                return None
            wav_bytes = samples_to_wav_bytes(samples, sample_rate)
            duration = round(len(samples) / sample_rate, 3)
            filename = f"{slug}_{suffix}.wav"
            file_path = os.path.join(event_dir, filename)
            with open(file_path, 'wb') as handle:
                handle.write(wav_bytes)

            storage_subpath = '/'.join(part for part in [storage_root, filename] if part)
            web_parts = [web_prefix, storage_subpath] if web_prefix else [storage_subpath]
            web_path = '/'.join(part for part in web_parts if part)
            download_url = url_for('static', filename=web_path)
            data_url = f"data:audio/wav;base64,{base64.b64encode(wav_bytes).decode('ascii')}"
            return {
                'filename': filename,
                'data_url': data_url,
                'download_url': download_url,
                'storage_subpath': storage_subpath,
                'duration_seconds': duration,
                'size_bytes': len(wav_bytes),
            }

        state_tree = get_us_state_county_tree()
        state_index = {
            state.get('state_fips'): {'abbr': state.get('abbr'), 'name': state.get('name')}
            for state in state_tree
            if state.get('state_fips')
        }
        same_lookup = get_same_lookup()
        header_detail = describe_same_header(header, lookup=same_lookup, state_index=state_index)

        same_component = _package_audio(components.get('same_samples') or [], 'same')
        attention_component = _package_audio(components.get('attention_samples') or [], 'attention')
        tts_component = _package_audio(components.get('tts_samples') or [], 'tts')
        eom_component = _package_audio(components.get('eom_samples') or [], 'eom')
        composite_component = _package_audio(components.get('composite_samples') or [], 'full')

        stored_components = {
            'same': same_component,
            'attention': attention_component,
            'tts': tts_component,
            'eom': eom_component,
            'composite': composite_component,
        }

        response_payload: Dict[str, Any] = {
            'identifier': identifier,
            'event_code': resolved_event_code,
            'event_name': event_name,
            'same_header': header,
            'same_locations': formatted_locations,
            'eom_header': components.get('eom_header'),
            'tone_profile': components.get('tone_profile'),
            'tone_seconds': components.get('tone_seconds'),
            'message_text': components.get('message_text'),
            'tts_warning': components.get('tts_warning'),
            'tts_provider': components.get('tts_provider'),
            'duration_minutes': duration_minutes,
            'sent_at': sent_dt.isoformat(),
            'expires_at': expires_dt.isoformat(),
            'components': stored_components,
            'sample_rate': sample_rate,
            'same_header_detail': header_detail,
            'storage_path': storage_root,
        }

        summary_filename = f"{slug}_summary.json"
        summary_path = os.path.join(event_dir, summary_filename)

        summary_components = {
            key: {
                'filename': value['filename'],
                'duration_seconds': value['duration_seconds'],
                'size_bytes': value['size_bytes'],
                'storage_subpath': value['storage_subpath'],
            }
            for key, value in stored_components.items()
            if value
        }

        summary_payload = {
            'identifier': identifier,
            'event_code': resolved_event_code,
            'event_name': event_name,
            'same_header': header,
            'same_locations': formatted_locations,
            'tone_profile': components.get('tone_profile'),
            'tone_seconds': components.get('tone_seconds'),
            'duration_minutes': duration_minutes,
            'sample_rate': sample_rate,
            'status': status,
            'message_type': message_type,
            'sent_at': sent_dt.isoformat(),
            'expires_at': expires_dt.isoformat(),
            'headline': alert_object.headline,
            'message_text': components.get('message_text'),
            'instruction_text': alert_object.instruction,
            'components': summary_components,
        }

        with open(summary_path, 'w', encoding='utf-8') as handle:
            json.dump(summary_payload, handle, indent=2)

        summary_subpath = '/'.join(part for part in [storage_root, summary_filename] if part)
        summary_parts = [web_prefix, summary_subpath] if web_prefix else [summary_subpath]
        summary_web_path = '/'.join(part for part in summary_parts if part)
        summary_url = url_for('static', filename=summary_web_path)

        response_payload['export_url'] = summary_url

        archive_time = datetime.now(timezone.utc)
        ManualEASActivation.query.filter(ManualEASActivation.archived_at.is_(None)).update(
            {'archived_at': archive_time}, synchronize_session=False
        )

        db_components = {
            key: {
                'filename': value['filename'],
                'duration_seconds': value['duration_seconds'],
                'size_bytes': value['size_bytes'],
                'storage_subpath': value['storage_subpath'],
            }
            for key, value in stored_components.items()
            if value
        }

        activation_record = ManualEASActivation(
            identifier=identifier,
            event_code=resolved_event_code,
            event_name=event_name or resolved_event_code,
            status=status,
            message_type=message_type,
            same_header=header,
            same_locations=formatted_locations,
            tone_profile=components.get('tone_profile') or 'attention',
            tone_seconds=components.get('tone_seconds'),
            sample_rate=sample_rate,
            includes_tts=bool(tts_component),
            tts_warning=components.get('tts_warning'),
            sent_at=sent_dt,
            expires_at=expires_dt,
            headline=alert_object.headline,
            message_text=components.get('message_text'),
            instruction_text=alert_object.instruction,
            duration_minutes=duration_minutes,
            storage_path=storage_root,
            summary_filename=summary_filename,
            components_payload=db_components,
            metadata_payload={
                'summary_subpath': summary_subpath,
                'web_prefix': web_prefix,
                'includes_tts': bool(tts_component),
            },
        )

        try:
            db.session.add(activation_record)
            db.session.flush()
            db.session.add(SystemLog(
                level='INFO',
                message='Manual EAS package generated',
                module='admin',
                details={
                    'identifier': identifier,
                    'event_code': resolved_event_code,
                    'location_count': len(formatted_locations),
                    'tone_profile': response_payload['tone_profile'],
                    'tts_included': bool(tts_component),
                    'manual_activation_id': activation_record.id,
                },
            ))
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.error('Failed to persist manual EAS activation: %s', exc)
            return jsonify({'error': 'Unable to persist manual activation details.'}), 500

        response_payload['activation'] = {
            'id': activation_record.id,
            'created_at': activation_record.created_at.isoformat() if activation_record.created_at else None,
            'print_url': url_for('manual_eas_print', event_id=activation_record.id),
            'export_url': summary_url,
            'components': {
                key: {
                    'download_url': value['download_url'],
                    'filename': value['filename'],
                }
                for key, value in stored_components.items()
                if value
            },
        }

        return jsonify(response_payload)


    @app.route('/admin/eas/manual_events', methods=['GET'])
    def admin_manual_eas_events():
        creating_first_user = AdminUser.query.count() == 0
        if g.current_user is None and not creating_first_user:
            return jsonify({'error': 'Authentication required.'}), 401

        try:
            limit = request.args.get('limit', type=int) or 100
            limit = min(max(limit, 1), 500)
            total = ManualEASActivation.query.count()
            events = (
                ManualEASActivation.query.order_by(ManualEASActivation.created_at.desc())
                .limit(limit)
                .all()
            )

            web_prefix = app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')
            items = []

            for event in events:
                components_payload = event.components_payload or {}

                def _component_with_url(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
                    if not meta:
                        return None
                    storage_subpath = meta.get('storage_subpath')
                    web_parts = [web_prefix, storage_subpath] if storage_subpath else []
                    web_path = '/'.join(part for part in web_parts if part)
                    download_url = url_for('static', filename=web_path) if storage_subpath else None
                    return {
                        'filename': meta.get('filename'),
                        'duration_seconds': meta.get('duration_seconds'),
                        'size_bytes': meta.get('size_bytes'),
                        'storage_subpath': storage_subpath,
                        'download_url': download_url,
                    }

                summary_subpath = None
                if event.summary_filename:
                    summary_subpath = '/'.join(
                        part for part in [event.storage_path, event.summary_filename] if part
                    )
                export_url = (
                    url_for('manual_eas_export', event_id=event.id)
                    if summary_subpath
                    else None
                )

                items.append({
                    'id': event.id,
                    'identifier': event.identifier,
                    'event_code': event.event_code,
                    'event_name': event.event_name,
                    'status': event.status,
                    'message_type': event.message_type,
                    'same_header': event.same_header,
                    'created_at': event.created_at.isoformat() if event.created_at else None,
                    'archived_at': event.archived_at.isoformat() if event.archived_at else None,
                    'print_url': url_for('manual_eas_print', event_id=event.id),
                    'export_url': export_url,
                    'components': {
                        key: _component_with_url(meta)
                        for key, meta in components_payload.items()
                    },
                })

            return jsonify({'events': items, 'total': total})
        except Exception as exc:
            logger.error('Failed to list manual EAS activations: %s', exc)
            return jsonify({'error': 'Unable to load manual activations.'}), 500


    @app.route('/admin/eas/manual_events/<int:event_id>/print')
    def manual_eas_print(event_id: int):
        creating_first_user = AdminUser.query.count() == 0
        if g.current_user is None and not creating_first_user:
            return redirect(url_for('login'))

        event = ManualEASActivation.query.get_or_404(event_id)
        components_payload = event.components_payload or {}
        web_prefix = app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')

        def _component_with_url(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not meta:
                return None
            storage_subpath = meta.get('storage_subpath')
            web_parts = [web_prefix, storage_subpath] if storage_subpath else []
            web_path = '/'.join(part for part in web_parts if part)
            download_url = url_for('static', filename=web_path) if storage_subpath else None
            return {
                'filename': meta.get('filename'),
                'duration_seconds': meta.get('duration_seconds'),
                'size_bytes': meta.get('size_bytes'),
                'download_url': download_url,
            }

        components: Dict[str, Dict[str, Any]] = {}
        for key, meta in components_payload.items():
            component_value = _component_with_url(meta)
            if component_value:
                components[key] = component_value

        state_tree = get_us_state_county_tree()
        state_index = {
            state.get('state_fips'): {'abbr': state.get('abbr'), 'name': state.get('name')}
            for state in state_tree
            if state.get('state_fips')
        }
        same_lookup = get_same_lookup()
        header_detail = describe_same_header(event.same_header, lookup=same_lookup, state_index=state_index)

        return render_template(
            'manual_eas_print.html',
            event=event,
            components=components,
            header_detail=header_detail,
            summary_url=url_for('manual_eas_export', event_id=event.id)
            if event.summary_filename
            else None,
        )


    @app.route('/admin/eas/manual_events/<int:event_id>/export')
    def manual_eas_export(event_id: int):
        creating_first_user = AdminUser.query.count() == 0
        if g.current_user is None and not creating_first_user:
            return abort(401)

        event = ManualEASActivation.query.get_or_404(event_id)
        if not event.summary_filename:
            return abort(404)

        output_root = str(app.config.get('EAS_OUTPUT_DIR') or '').strip()
        if not output_root:
            return abort(404)

        file_path = os.path.join(output_root, event.storage_path or '', event.summary_filename)
        if not os.path.exists(file_path):
            return abort(404)

        return send_file(
            file_path,
            as_attachment=True,
            download_name=event.summary_filename,
            mimetype='application/json',
        )
