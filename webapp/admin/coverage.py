"""Coverage calculation helpers for admin routes."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from flask import current_app
from sqlalchemy import func

from app_core.models import Boundary, CAPAlert, Intersection
from app_core.extensions import db


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


__all__ = ['calculate_coverage_percentages']
