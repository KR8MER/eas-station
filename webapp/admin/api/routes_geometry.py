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

"""``/api/alerts/<id>/geometry`` — one alert as GeoJSON.

Returns the alert's own geometry plus every boundary it intersects, which is
what the alert map layer draws.
"""

from flask import jsonify
from sqlalchemy import func

from app_core.extensions import db
from app_core.models import Boundary, CAPAlert, Intersection
from app_utils import UTC_TZ
from app_utils.optimized_parsing import json_loads

from ..coverage import try_build_geometry_from_same_codes

from .blueprint import api_bp
from .county import _detect_county_wide


# Route definitions

@api_bp.route('/api/alerts/<int:alert_id>/geometry')
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
            CAPAlert.raw_json,
            func.ST_AsGeoJSON(CAPAlert.geom).label('geometry'),
        ).filter(CAPAlert.id == alert_id).first()

        if not alert:
            return jsonify({'error': 'Alert not found'}), 404

        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(func.lower(Boundary.type) == 'county').first()

            if county_geom and county_geom.geometry:
                county_boundary = json_loads(county_geom.geometry)
        except Exception as exc:  # pragma: no cover - defensive logging
            api_bp.logger.warning("Could not get county boundary: %s", exc)

        geometry = None
        is_county_wide = False

        if alert.geometry:
            geometry = json_loads(alert.geometry)
        else:
            # Try to build geometry from SAME geocodes (multi-county IPAWS)
            try_build_geometry_from_same_codes(alert_id)
            geom_json = db.session.query(
                func.ST_AsGeoJSON(CAPAlert.geom)
            ).filter(CAPAlert.id == alert_id).scalar()
            if geom_json:
                geometry = json_loads(geom_json)

            # Fallback: use county boundary if alert is county-wide
            if not geometry and county_boundary and _detect_county_wide(alert):
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
                            'geometry': json_loads(boundary_geom_json),
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

        # Extract SAME codes so the frontend can render affected counties
        # even when PostGIS geometry building fails.
        same_codes: list = []
        if alert.raw_json and isinstance(alert.raw_json, dict):
            same_codes = (
                alert.raw_json
                .get('properties', {})
                .get('geocode', {})
                .get('SAME', [])
            ) or []

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
                    'same_codes': same_codes,
                },
                # geometry may be null; the frontend handles that gracefully
                'geometry': geometry,
            },
            'intersecting_boundaries': {
                'type': 'FeatureCollection',
                'features': intersecting_boundaries,
            },
        }

        return jsonify(response_data)

    except Exception as exc:  # pragma: no cover - defensive logging
        api_bp.logger.error("Error getting alert geometry: %s", exc, exc_info=True)
        return jsonify({'error': 'Failed to retrieve alert geometry'}), 500
