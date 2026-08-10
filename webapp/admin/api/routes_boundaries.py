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

"""``/api/boundaries`` — the boundary layer feed for the maps."""

from flask import jsonify, request
from sqlalchemy import func

from app_core.cache import cache
from app_core.extensions import db
from app_core.models import Boundary, USCountyBoundary
from app_core.boundaries import (
    get_boundary_color,
    get_boundary_display_label,
    get_boundary_group,
    normalize_boundary_type,
)
from app_utils.optimized_parsing import json_loads

from .blueprint import api_bp


@api_bp.route('/api/boundaries')
@cache.cached(timeout=300, query_string=True, key_prefix='boundaries_list')
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
                        'geometry': json_loads(boundary.geometry),
                    }
                )

        # When no county-type Boundary records have been uploaded, serve the
        # configured county from the bundled us_county_boundaries (Census TIGER)
        # table so the map always shows the correct county outline without
        # requiring a manual GeoJSON upload.
        if not features and boundary_type and normalize_boundary_type(boundary_type) == 'county':
            try:
                from app_core.location import get_location_settings
                from app_core.county_boundaries import get_county_count, same_codes_to_geoids
                if get_county_count() > 0:
                    _settings = get_location_settings()
                    geoids = same_codes_to_geoids(_settings.get('fips_codes') or [])
                    if geoids:
                        ucb_rows = db.session.query(
                            USCountyBoundary.id,
                            USCountyBoundary.namelsad,
                            USCountyBoundary.name,
                            USCountyBoundary.geoid,
                            func.ST_AsGeoJSON(USCountyBoundary.geom).label('geometry'),
                        ).filter(
                            USCountyBoundary.geoid.in_(geoids),
                            USCountyBoundary.geom.isnot(None),
                        ).all()
                        for row in ucb_rows:
                            if row.geometry:
                                features.append(
                                    {
                                        'type': 'Feature',
                                        'properties': {
                                            'id': row.id,
                                            'name': row.namelsad or row.name,
                                            'type': 'county',
                                            'raw_type': 'county',
                                            'display_type': get_boundary_display_label('county'),
                                            'group': get_boundary_group('county'),
                                            'color': get_boundary_color('county'),
                                            'description': f'Census TIGER county boundary (GEOID {row.geoid})',
                                            'source': 'us_county_boundaries',
                                        },
                                        'geometry': json_loads(row.geometry),
                                    }
                                )
            except Exception as exc:
                api_bp.logger.warning(
                    'County boundary fallback to us_county_boundaries failed: %s', exc
                )

        return jsonify({'type': 'FeatureCollection', 'features': features})
    except Exception as exc:
        api_bp.logger.error('Error fetching boundaries: %s', exc, exc_info=True)
        return jsonify({'error': 'Failed to retrieve boundaries'}), 500
