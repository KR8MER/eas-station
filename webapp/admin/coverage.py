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

"""Coverage calculation helpers for admin routes."""

import json
from typing import Any, Dict, List, Tuple

from flask import current_app
from geoalchemy2 import Geography
from sqlalchemy import cast, func, text

from app_core.models import Boundary, CAPAlert, Intersection, USCountyBoundary
from app_core.extensions import db

# Conversion constant: square metres → square miles
_SQM_PER_SQMI = 2_589_988.11


def _us_county_table_ready() -> bool:
    """Return True if the us_county_boundaries table exists and has rows."""
    try:
        row_check = db.session.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables"
                "  WHERE table_name = 'us_county_boundaries'"
                ")"
            )
        ).scalar()
        if not row_check:
            return False
        count = db.session.execute(
            text("SELECT COUNT(*) FROM us_county_boundaries LIMIT 1")
        ).scalar()
        return bool(count and count > 0)
    except Exception:
        return False


def try_build_geometry_from_same_codes(alert_id: int) -> bool:
    """Attempt to build alert geometry from available sources.

    Tries sources in priority order:
    1. Polygon embedded in ``raw_json['geometry']`` (NOAA GeoJSON feature body).
       This always takes priority — even if geometry was previously stored from
       SAME codes — so that an alert whose polygon arrives after initial ingest
       gets the accurate partial-coverage geometry rather than the coarser
       full-county union built from SAME codes.
    2. ``alert.geom`` already set from a previous run (no polygon in raw_json).
    3. SAME geocodes matched against the ``us_county_boundaries`` table.
       **Only reached when the alert carries no polygon geometry at all**
       (e.g. county-wide watches, advisories, and statements that use SAME codes
       instead of a specific area polygon).  If ``raw_json['geometry']`` has
       coordinates but Priority 1 failed to parse them, this step is skipped so
       that a coarse county union is never substituted for a localized event.

    Uses a SAVEPOINT so that failures never corrupt the caller's session.
    Call this *before* calculate_coverage_percentages, not inside it.

    Returns True if the alert now has geometry, False otherwise.
    """
    try:
        alert = CAPAlert.query.get(alert_id)
        if not alert:
            return False

        raw_json = alert.raw_json if isinstance(alert.raw_json, dict) else {}

        # --- Priority 1: actual polygon from raw_json['geometry'] ---
        # Always preferred: covers the real affected area rather than the full
        # county union that SAME codes produce.  We update even if geom is
        # already set so stale SAME-derived geometry gets replaced once the
        # real polygon is available.
        raw_geom = raw_json.get('geometry')
        if raw_geom and isinstance(raw_geom, dict) and raw_geom.get('coordinates'):
            nested = db.session.begin_nested()
            try:
                geom_json = json.dumps(raw_geom)
                result = db.session.execute(
                    text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)"),
                    {"g": geom_json},
                ).scalar()
                if result is not None:
                    alert.geom = result
                    nested.commit()
                    db.session.commit()
                    current_app.logger.info(
                        'Built geometry from raw_json[geometry] for alert %s',
                        alert.identifier,
                    )
                    return True
                nested.rollback()
            except Exception as exc:
                current_app.logger.debug(
                    'raw_json[geometry] parse failed for alert %s: %s',
                    alert_id, exc,
                )
                nested.rollback()

        # --- Priority 2: geometry already stored (and no raw_json polygon) ---
        if alert.geom:
            return True

        # --- Priority 3: build from SAME geocodes via county boundary table ---
        # Guard: only use SAME codes when the alert genuinely carries no polygon
        # geometry.  If raw_json['geometry'] has coordinates (the alert IS
        # polygon-based) but Priority 1 failed to parse/store them, substituting
        # a full-county union would produce inflated, inaccurate coverage for a
        # localized event (e.g. a thunderstorm warning covering part of a county).
        # Return False here — the admin UI will surface an actionable error.
        raw_geom_present = bool(
            raw_geom and isinstance(raw_geom, dict) and raw_geom.get('coordinates')
        )
        if raw_geom_present:
            current_app.logger.debug(
                'Alert %s has polygon in raw_json but parse failed; '
                'skipping SAME code fallback to avoid inflated coverage',
                alert_id,
            )
            return False

        if not _us_county_table_ready():
            return False

        same_codes = raw_json.get('properties', {}).get('geocode', {}).get('SAME', [])
        if not same_codes:
            return False

        geoids = set()
        statewide_state_fps = set()

        for code in same_codes:
            if not isinstance(code, str) or len(code) < 5:
                continue
            if code.endswith('000'):
                # Statewide: SAME 039000 → state FIPS "39"
                state_fp = code[1:3] if len(code) == 6 else code.lstrip('0')[:2]
                statewide_state_fps.add(state_fp)
                continue
            # SAME codes are always 6 chars: 0SSCCC.  Drop the single leading
            # prefix zero to obtain the 5-digit Census GEOID (SSCCC).
            # Using lstrip('0') would over-strip codes for states 01-09
            # (e.g. "001001" → "1001" instead of the correct "01001").
            geoid = code[1:]
            geoids.add(geoid)

        if not geoids and not statewide_state_fps:
            return False

        # Use a SAVEPOINT so that any DB error is contained
        nested = db.session.begin_nested()
        try:
            conditions = []
            params: Dict[str, Any] = {}

            if geoids:
                conditions.append("geoid = ANY(:geoids)")
                params["geoids"] = list(geoids)
            if statewide_state_fps:
                conditions.append("statefp = ANY(:state_fps)")
                params["state_fps"] = list(statewide_state_fps)

            where_clause = " OR ".join(conditions)

            count = db.session.execute(
                text(f"SELECT COUNT(*) FROM us_county_boundaries WHERE ({where_clause}) AND geom IS NOT NULL"),
                params,
            ).scalar()

            if not count:
                nested.rollback()
                return False

            union_geom = db.session.execute(
                text(f"""
                    SELECT ST_SetSRID(ST_Multi(ST_Union(geom)), 4326)
                    FROM us_county_boundaries
                    WHERE ({where_clause}) AND geom IS NOT NULL
                """),
                params,
            ).scalar()

            if union_geom is None:
                nested.rollback()
                return False

            alert.geom = union_geom
            nested.commit()
            db.session.commit()

            current_app.logger.info(
                'Built geometry from %d SAME codes (%d counties) for alert %s',
                len(same_codes), count, alert.identifier,
            )
            return True

        except Exception as exc:
            current_app.logger.warning(
                'SAME geometry build failed for alert %s: %s', alert_id, exc
            )
            nested.rollback()
            return False

    except Exception as exc:
        current_app.logger.warning('SAME geometry build skipped for alert %s: %s', alert_id, exc)
        return False


def calculate_coverage_percentages(alert_id, intersections):
    """Calculate coverage metrics for each boundary type and the overall county.

    Important: call ``try_build_geometry_from_same_codes`` before this function
    so that alerts with SAME-derived geometry are handled.

    Area values are computed using PostGIS geography type (``::geography``),
    which returns accurate square metres regardless of the stored SRID.
    ``intersected_area_sqmi`` in each result dict gives the human-readable
    square-mile figure for display.
    """

    coverage_data: Dict[str, Dict[str, Any]] = {}

    try:
        alert = CAPAlert.query.get(alert_id)
        if not alert or not alert.geom:
            return coverage_data

        # Detect whether the stored geometry came from the real NWS polygon or
        # was synthesised from SAME broadcast codes.  SAME-derived geometry is a
        # union of entire county polygons, so its intersection with any one of
        # those counties is ≈100% — a misleading "county-wide" reading.
        raw_json = alert.raw_json if isinstance(alert.raw_json, dict) else {}
        raw_geom = raw_json.get('geometry')
        geom_from_same_codes = not (
            raw_geom and isinstance(raw_geom, dict) and raw_geom.get('coordinates')
        )

        boundary_types: Dict[str, List[Tuple[Intersection, Boundary]]] = {}
        for intersection, boundary in intersections:
            boundary_types.setdefault(boundary.type, []).append((intersection, boundary))

        for boundary_type, boundaries in boundary_types.items():
            if not boundaries:
                continue

            # Count all boundaries of this type for display purposes
            total_count = Boundary.query.filter_by(type=boundary_type).count()
            if not total_count:
                continue

            # Coverage percentage:
            #   sum(intersection areas) / sum(full areas of intersecting boundaries)
            # Both areas use ::geography so the ratio is accurate.
            boundary_ids = [boundary.id for _, boundary in boundaries]
            total_area_query = db.session.query(
                func.sum(func.ST_Area(cast(Boundary.geom, Geography()))).label('total_area')
            ).filter(
                Boundary.id.in_(boundary_ids),
                Boundary.geom.isnot(None),
            ).first()

            total_area = total_area_query.total_area if total_area_query and total_area_query.total_area else 0

            # Stored intersection_area values may be in square degrees (legacy) or
            # square metres (post-fix).  Re-compute live from the geography cast so
            # the percentage is always accurate against the geography-based denominator.
            if total_area > 0 and boundaries:
                boundary_id_list = [b.id for _, b in boundaries]
                live_area_row = db.session.execute(
                    text(
                        "SELECT SUM(ST_Area(ST_Intersection(a.geom, b.geom)::geography))"
                        " FROM cap_alerts a, boundaries b"
                        " WHERE a.id = :alert_id AND b.id = ANY(:bids)"
                        "   AND ST_Intersects(a.geom, b.geom)"
                    ),
                    {'alert_id': alert_id, 'bids': boundary_id_list},
                ).first()
                intersected_area = float(live_area_row[0] or 0) if live_area_row else 0.0
            else:
                intersected_area = 0.0

            coverage_percentage = 0.0
            if total_area > 0:
                coverage_percentage = (intersected_area / total_area) * 100
                coverage_percentage = min(100.0, max(0.0, coverage_percentage))

            coverage_data[boundary_type] = {
                'total_boundaries': total_count,
                'affected_boundaries': len(boundaries),
                'coverage_percentage': round(coverage_percentage, 1),
                'total_area_sqm': total_area,
                'intersected_area_sqm': intersected_area,
                'intersected_area_sqmi': round(intersected_area / _SQM_PER_SQMI, 1),
            }

        # ---------------------------------------------------------------------------
        # County coverage — always use the CONFIGURED county boundary, never a
        # random intersecting county.  The intersections list may contain a
        # neighbouring county's boundary (e.g. Allen County) if the real NWS polygon
        # happened to touch it; falling back to that boundary would give the wrong
        # percentage (this was the root cause of the 99.4% / Allen County bug).
        # ---------------------------------------------------------------------------
        county_boundary = None
        _county_name_configured = False  # tracks whether a county name is set
        try:
            from app_core.location import get_location_settings
            _settings = get_location_settings()
            _cname = (_settings.get('county_name', '') or '').split(',')[0].lower().replace(' county', '').strip()
            _county_name_configured = bool(_cname)
            if _cname:
                # 1. Check intersections list — only accept the configured county.
                county_intersections = [b for _, b in intersections if b.type == 'county']
                county_boundary = next(
                    (b for b in county_intersections
                     if _cname in (b.name or '').lower().replace(' county', '').strip()),
                    None,  # never fall back to a different county
                )
                # 2. Query Boundary table directly by configured county name.
                if county_boundary is None:
                    county_boundary = (
                        Boundary.query.filter_by(type='county')
                        .filter(func.lower(Boundary.name).contains(_cname))
                        .first()
                    )
        except Exception:
            pass
        # 3. Last resort: only when NO county name is configured at all.
        # Never pick a random county boundary when a county name is set but
        # no matching record was found — that would silently swap Putnam for
        # Allen County (or whichever county is first in the Boundary table),
        # reproducing the 99.4% / wrong-county bug.
        if county_boundary is None and not _county_name_configured:
            county_boundary = Boundary.query.filter_by(type='county').first()

        if county_boundary and county_boundary.geom:
            try:
                # Use ::geography for accurate square-metre areas so that the
                # percentage and the square-mile figure are both correct.
                county_intersection_query = db.session.query(
                    func.ST_Area(
                        cast(func.ST_Intersection(alert.geom, county_boundary.geom), Geography())
                    ).label('intersection_area'),
                    func.ST_Area(cast(county_boundary.geom, Geography())).label('total_county_area'),
                ).filter(
                    func.ST_Intersects(alert.geom, county_boundary.geom)
                ).first()

                if county_intersection_query:
                    county_coverage = 0.0
                    intersection_area = county_intersection_query.intersection_area or 0.0
                    total_county_area = county_intersection_query.total_county_area
                    if total_county_area:
                        county_coverage = (intersection_area / total_county_area) * 100
                        county_coverage = min(100.0, max(0.0, county_coverage))

                    coverage_data['county'] = {
                        'coverage_percentage': round(county_coverage, 1),
                        'total_area_sqm': total_county_area,
                        'total_area_sqmi': round(total_county_area / _SQM_PER_SQMI, 1),
                        'intersected_area_sqm': intersection_area,
                        'intersected_area_sqmi': round(intersection_area / _SQM_PER_SQMI, 1),
                        'is_estimated': geom_from_same_codes,
                    }
                else:
                    coverage_data['county'] = {
                        'coverage_percentage': 0.0,
                        'total_area_sqm': None,
                        'total_area_sqmi': None,
                        'intersected_area_sqm': 0.0,
                        'intersected_area_sqmi': 0.0,
                        'is_estimated': geom_from_same_codes,
                    }
            except Exception as exc:
                current_app.logger.warning(
                    'County coverage query failed for alert %s: %s', alert_id, exc
                )
        elif county_boundary is None and _us_county_table_ready():
            # No Boundary record of type='county' was uploaded, but the Census
            # TIGER us_county_boundaries table is available.  Use it to compute
            # what percentage of the configured county the alert polygon covers.
            try:
                from app_core.location import get_location_settings
                from app_core.county_boundaries import same_codes_to_geoids
                _settings = get_location_settings()
                geoids = same_codes_to_geoids(_settings.get('fips_codes') or [])
                if geoids:
                    # When the station is configured to monitor multiple FIPS codes
                    # (e.g. a multi-county coverage area), always prefer the county
                    # whose name matches the configured county_name rather than
                    # returning the first record by database insertion order.
                    # Without this, Allen County (GEOID 39003) is returned before
                    # Putnam County (39137) because it appears first in the Census
                    # shapefile, producing the 99.4% / wrong-county bug.
                    _cname_census = (
                        (_settings.get('county_name', '') or '')
                        .split(',')[0].lower().replace(' county', '').strip()
                    )
                    ucb = None
                    if _cname_census:
                        ucb = (
                            USCountyBoundary.query
                            .filter(USCountyBoundary.geoid.in_(geoids))
                            .filter(USCountyBoundary.geom.isnot(None))
                            .filter(func.lower(USCountyBoundary.name).contains(_cname_census))
                            .first()
                        )
                    if ucb is None:
                        ucb = (
                            USCountyBoundary.query
                            .filter(USCountyBoundary.geoid.in_(geoids))
                            .filter(USCountyBoundary.geom.isnot(None))
                            .first()
                        )
                    if ucb:
                        # Use ::geography for accurate square-metre results.
                        row = db.session.execute(
                            text(
                                "SELECT"
                                " ST_Area(ST_Intersection(a.geom, c.geom)::geography)"
                                "   AS intersection_area,"
                                " ST_Area(c.geom::geography) AS total_county_area"
                                " FROM cap_alerts a, us_county_boundaries c"
                                " WHERE a.id = :alert_id"
                                "   AND c.geoid = :geoid"
                                "   AND ST_Intersects(a.geom, c.geom)"
                            ),
                            {'alert_id': alert_id, 'geoid': ucb.geoid},
                        ).first()
                        if row:
                            intersection_area = row.intersection_area or 0.0
                            total_county_area = row.total_county_area
                            county_coverage = 0.0
                            if total_county_area:
                                county_coverage = (intersection_area / total_county_area) * 100
                                county_coverage = min(100.0, max(0.0, county_coverage))
                            coverage_data['county'] = {
                                'coverage_percentage': round(county_coverage, 1),
                                'total_area_sqm': total_county_area,
                                'total_area_sqmi': round(total_county_area / _SQM_PER_SQMI, 1),
                                'intersected_area_sqm': intersection_area,
                                'intersected_area_sqmi': round(intersection_area / _SQM_PER_SQMI, 1),
                                'is_estimated': geom_from_same_codes,
                            }
                        else:
                            coverage_data['county'] = {
                                'coverage_percentage': 0.0,
                                'total_area_sqm': None,
                                'total_area_sqmi': None,
                                'intersected_area_sqm': 0.0,
                                'intersected_area_sqmi': 0.0,
                                'is_estimated': geom_from_same_codes,
                            }
            except Exception as exc:
                current_app.logger.warning(
                    'County coverage (us_county_boundaries fallback) failed for alert %s: %s',
                    alert_id, exc,
                )

    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.error('Error calculating coverage percentages: %s', exc)

    return coverage_data


__all__ = ['calculate_coverage_percentages', 'try_build_geometry_from_same_codes']
