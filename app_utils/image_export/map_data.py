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

"""Database lookups behind the coverage map.

County reference outlines, the SAME geocodes carried in a CAP payload, and
the county-union fallback geometry used when ``cap_alerts.geom`` is NULL.
Split out of ``maps.py`` so its drawing code is not interleaved with
PostGIS queries; ``maps`` re-exports every name.

Each function degrades to an empty / ``None`` result rather than raising
when there is no application context, no PostGIS and no boundary table —
an offline render still produces a complete card, just without county
context.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fetch_county_outlines(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    db_session: Any = None, *, alert_geom: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return simplified GeoJSON geometries for the US counties that
    intersect the given lon/lat bounding box.

    These are drawn as muted reference lines *under* the alert polygon so
    the affected area carries geographic context (which county / counties
    it falls in) — mirroring the county boundaries on official NWS warning
    graphics.

    When *alert_geom* is supplied each row also carries:

    * ``affected`` — whether the county intersects the alert polygon, which
      lets the renderer draw those borders brighter than the surrounding
      reference lines;
    * ``point`` — an ``(lon, lat)`` guaranteed to lie inside the county
      (``ST_PointOnSurface``, not the centroid, which can fall outside a
      crescent-shaped or multi-part county), used to anchor its name label.

    *db_session* lets callers running outside a Flask application context
    (the CAP poller / monitoring services) supply their own SQLAlchemy
    session; when omitted, the Flask-SQLAlchemy request session is used.

    Returns an empty list when the boundary table is unavailable, empty, or
    there is no application / database context (e.g. unit tests, an offline
    render), so the map renderer degrades gracefully to a polygon-only view.
    """
    try:
        from sqlalchemy import text as _text

        if db_session is None:
            from app_core.extensions import db
            db_session = db.session
    except Exception:
        return []

    # Simplify tolerance in degrees.  County lines are reference context,
    # not the subject, so a coarse outline keeps the vertex count (and the
    # draw cost) low without visibly changing the shape at share-card
    # resolution.  Scale it to the viewport so a tightly-zoomed single-county
    # warning still gets a faithful border.
    tol = max(max_lon - min_lon, max_lat - min_lat, 0.01) * 0.0015

    params: Dict[str, Any] = {
        "tol": tol,
        "min_lon": min_lon, "min_lat": min_lat,
        "max_lon": max_lon, "max_lat": max_lat,
    }
    if alert_geom is not None:
        params["alert_geom"] = json.dumps(alert_geom)
        affected_sql = (
            "COALESCE(ST_Intersects(geom, "
            "ST_SetSRID(ST_GeomFromGeoJSON(:alert_geom), 4326)), FALSE)"
        )
    else:
        affected_sql = "FALSE"

    try:
        rows = db_session.execute(
            _text(
                f"""
                SELECT name,
                       ST_AsGeoJSON(
                           ST_SimplifyPreserveTopology(geom, :tol), 5
                       ) AS gj,
                       ST_X(ST_PointOnSurface(geom)) AS lon,
                       ST_Y(ST_PointOnSurface(geom)) AS lat,
                       {affected_sql} AS affected
                FROM us_county_boundaries
                WHERE geom && ST_MakeEnvelope(
                          :min_lon, :min_lat, :max_lon, :max_lat, 4326
                      )
                LIMIT 80
                """
            ),
            params,
        ).fetchall()
    except Exception:
        # No table, no PostGIS, no DB session — silently skip; the alert
        # polygon alone is still a complete map.
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            entry: Dict[str, Any] = {
                'name': row.name,
                'geom': json.loads(row.gj),
                'affected': bool(getattr(row, 'affected', False)),
            }
            lon, lat = getattr(row, 'lon', None), getattr(row, 'lat', None)
            if lon is not None and lat is not None:
                entry['point'] = (float(lon), float(lat))
            out.append(entry)
        except Exception:
            continue
    return out


def _alert_same_codes(alert: Any) -> List[str]:
    """Return the 6-digit SAME geocodes carried in *alert*'s raw CAP JSON.

    These identify the affected counties for products that are county-coded
    rather than polygon-drawn (most watches/advisories, and any alert whose
    polygon failed to parse at ingest).
    """
    raw = getattr(alert, 'raw_json', None)
    if not isinstance(raw, dict):
        return []
    geocode = (raw.get('properties') or {}).get('geocode') or {}
    codes = geocode.get('SAME') or []
    if isinstance(codes, str):
        codes = [codes]
    return [
        c for c in codes
        if isinstance(c, str) and len(c) == 6 and c.isdigit()
    ]


def _fetch_same_union_geom(
    db_session: Any, same_codes: List[str],
) -> Optional[Dict[str, Any]]:
    """Return the GeoJSON union of the county boundaries for *same_codes*.

    Fallback geometry for the coverage map when ``cap_alerts.geom`` is NULL:
    the union of the affected counties is exactly the shape official NWS
    county-based warning graphics show.  SAME codes are ``0SSCCC`` — the
    leading zero is dropped to obtain the 5-digit Census GEOID; ``0SS000``
    means the whole state.  Returns ``None`` when the boundary table is
    unavailable or nothing matches, so the caller degrades to the
    "Map not available" placeholder as before.
    """
    if db_session is None or not same_codes:
        return None

    geoids: set = set()
    state_fps: set = set()
    for code in same_codes:
        if code.endswith('000'):
            state_fps.add(code[1:3])
        else:
            geoids.add(code[1:])
    if not geoids and not state_fps:
        return None

    conditions: List[str] = []
    params: Dict[str, Any] = {}
    if geoids:
        conditions.append("geoid = ANY(:geoids)")
        params["geoids"] = sorted(geoids)
    if state_fps:
        conditions.append("statefp = ANY(:state_fps)")
        params["state_fps"] = sorted(state_fps)

    try:
        from sqlalchemy import text as _text

        gj = db_session.execute(
            _text(
                "SELECT ST_AsGeoJSON("
                "  ST_SimplifyPreserveTopology("
                "    ST_Multi(ST_Union(geom)), 0.002), 5)"
                " FROM us_county_boundaries"
                f" WHERE ({' OR '.join(conditions)}) AND geom IS NOT NULL"
            ),
            params,
        ).scalar()
    except Exception as exc:
        logger.debug("County-union fallback geometry unavailable: %s", exc)
        # A failed SELECT poisons a PostgreSQL transaction; roll back so the
        # caller's session stays usable for the rest of the email pipeline.
        try:
            db_session.rollback()
        except Exception:
            pass
        return None

    if not gj:
        return None
    try:
        geom = json.loads(gj)
    except (TypeError, ValueError):
        return None
    if isinstance(geom, dict) and geom.get('coordinates'):
        return geom
    return None
