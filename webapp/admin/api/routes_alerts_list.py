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

"""``/api/alerts`` and ``/api/alerts/historical`` — the alert list feeds.

Both are cached read endpoints backing the alerts table and the historical
browser, and both use ``_get_location_terms`` for the "local" relevance filter.
"""

from datetime import datetime

from flask import jsonify, request
from sqlalchemy import func

from app_core.cache import cache
from app_core.extensions import db
from app_core.models import Boundary, CAPAlert
from app_utils import ALERT_SOURCE_IPAWS, ALERT_SOURCE_MANUAL, UTC_TZ, utc_now
from app_core.alerts import (
    get_active_alerts_query,
    get_expired_alerts_query,
    load_alert_plain_text_map,
)
from app_utils import is_alert_expired
from app_utils.optimized_parsing import json_loads

from ..coverage import try_build_geometry_from_same_codes

from .blueprint import api_bp
from .county import _get_location_terms


@api_bp.route('/api/alerts')
@cache.cached(timeout=30, query_string=True, key_prefix='alerts_list')
def get_alerts():
    """Get CAP alerts as GeoJSON with optional inclusion of expired alerts"""
    try:
        include_expired = request.args.get('include_expired', 'false').lower() == 'true'

        if include_expired:
            alerts_query = CAPAlert.query
            api_bp.logger.info("Including expired alerts in API response")
        else:
            alerts_query = get_active_alerts_query()
            api_bp.logger.info("Including only active alerts in API response")

        alerts = alerts_query.with_entities(
            CAPAlert.id,
            CAPAlert.identifier,
            CAPAlert.event,
            CAPAlert.severity,
            CAPAlert.urgency,
            CAPAlert.headline,
            CAPAlert.description,
            CAPAlert.expires,
            CAPAlert.area_desc,
            CAPAlert.source,
            CAPAlert.eas_forwarded,
            CAPAlert.eas_forwarding_reason,
            func.ST_AsGeoJSON(CAPAlert.geom).label('geometry'),
        ).all()

        alert_ids = [alert.id for alert in alerts if alert.id]
        plain_text_map = load_alert_plain_text_map(alert_ids)
        eas_sources = {ALERT_SOURCE_IPAWS, ALERT_SOURCE_MANUAL}

        # Load configured location terms once for the whole loop so we avoid
        # per-alert database round-trips and don't hardcode any location name.
        _county_short, _county_name_lower, _state_lower = _get_location_terms()

        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(func.lower(Boundary.type) == 'county').first()

            if county_geom and county_geom.geometry:
                county_boundary = json_loads(county_geom.geometry)
        except Exception as exc:  # pragma: no cover - defensive logging
            api_bp.logger.warning("Could not get county boundary: %s", exc)

        features = []
        for alert in alerts:
            geometry = None
            is_county_wide = False

            if alert.geometry:
                geometry = json_loads(alert.geometry)
            else:
                # Try to build geometry from SAME geocodes (IPAWS alerts)
                if try_build_geometry_from_same_codes(alert.id):
                    geom_json = db.session.query(
                        func.ST_AsGeoJSON(CAPAlert.geom)
                    ).filter(CAPAlert.id == alert.id).scalar()
                    if geom_json:
                        geometry = json_loads(geom_json)

                # Fallback: use county boundary if area_desc suggests county-wide
                if not geometry and alert.area_desc and any(
                    county_term in alert.area_desc.lower()
                    for county_term in filter(None, ['county', _county_short, _state_lower])
                ):
                    if county_boundary:
                        geometry = county_boundary
                        is_county_wide = True

            if not is_county_wide and alert.area_desc:
                area_lower = alert.area_desc.lower()

                if _county_short and _county_short in area_lower:
                    separator_count = max(area_lower.count(';'), area_lower.count(','))
                    if separator_count >= 2:
                        is_county_wide = True

                county_keywords = ['county', 'entire county']
                if _county_name_lower:
                    county_keywords.append(_county_name_lower)
                if any(keyword in area_lower for keyword in county_keywords):
                    is_county_wide = True

            source_value = alert.source
            plain_text = None
            if source_value in eas_sources:
                plain_text = plain_text_map.get(alert.id)

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
                            'source': source_value,
                            'plain_text': plain_text,
                            'expires_iso': expires_iso,
                            'is_county_wide': is_county_wide,
                            'is_expired': is_alert_expired(alert.expires),
                            'eas_forwarded': bool(alert.eas_forwarded),
                            'eas_forwarding_reason': alert.eas_forwarding_reason,
                        },
                        'geometry': geometry,
                    }
                )

        api_bp.logger.info('Returning %s alerts (include_expired=%s)', len(features), include_expired)

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
        api_bp.logger.error('Error getting alerts: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to retrieve alerts'}), 500

@api_bp.route('/api/alerts/historical')
@cache.cached(timeout=60, query_string=True, key_prefix='alerts_historical')
def get_historical_alerts():
    """Get historical alerts as GeoJSON with date filtering"""
    try:
        start_date = request.args.get('start_date') or request.args.get('start')
        end_date = request.args.get('end_date') or request.args.get('end')
        include_active = request.args.get('include_active', 'false').lower() == 'true'

        if include_active:
            query = CAPAlert.query
        else:
            query = get_expired_alerts_query()

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC_TZ)
            except ValueError:
                return jsonify({'error': 'Invalid start_date format. Use ISO 8601 format (e.g., 2024-01-15 or 2024-01-15T10:30:00).'}), 400
            query = query.filter(CAPAlert.sent >= start_dt)

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC_TZ)
            except ValueError:
                return jsonify({'error': 'Invalid end_date format. Use ISO 8601 format (e.g., 2024-01-15 or 2024-01-15T10:30:00).'}), 400
            query = query.filter(CAPAlert.sent <= end_dt)

        matching_ids = query.with_entities(CAPAlert.id).scalar_subquery()

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
            CAPAlert.id.in_(matching_ids)
        ).all()

        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(func.lower(Boundary.type) == 'county').first()

            if county_geom and county_geom.geometry:
                county_boundary = json_loads(county_geom.geometry)
        except Exception as exc:  # pragma: no cover - defensive logging
            api_bp.logger.warning("Could not get county boundary: %s", exc)

        # Load configured location terms once for the whole loop.
        _county_short, _county_name_lower, _state_lower = _get_location_terms()

        features = []
        for alert in alerts:
            geometry = None
            is_county_wide = False

            if alert.geometry:
                geometry = json_loads(alert.geometry)
            else:
                # Try to build geometry from SAME geocodes (IPAWS alerts)
                if try_build_geometry_from_same_codes(alert.id):
                    geom_json = db.session.query(
                        func.ST_AsGeoJSON(CAPAlert.geom)
                    ).filter(CAPAlert.id == alert.id).scalar()
                    if geom_json:
                        geometry = json_loads(geom_json)

                # Fallback: use county boundary if area_desc suggests county-wide
                if not geometry and alert.area_desc and any(
                    county_term in alert.area_desc.lower()
                    for county_term in filter(None, ['county', _county_short, _state_lower])
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

                description = alert.description or ''
                if len(description) > 500:
                    description = description[:500] + '...'

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
                            'description': description,
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
        api_bp.logger.error('Error getting historical alerts: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to retrieve historical alerts'}), 500
