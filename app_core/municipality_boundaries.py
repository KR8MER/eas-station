"""US incorporated-place (city/village) boundary loading for the "affected
municipalities" display.

Provides admin-UI and CLI helpers for importing Census Bureau TIGER/Line
cartographic "Places" shapefiles into the generic ``boundaries`` table
(type ``villages``, already recognized by app_core/boundaries.py's
BOUNDARY_TYPE_CONFIG). Once loaded, the alert detail page's existing
boundary-intersection display starts showing named cities and villages with
no further UI work -- see webapp/admin/api/routes_alert_detail.py.

Mirrors app_core/county_boundaries.py's split (core logic here, thin
callers in webapp/admin/boundaries.py and scripts/load_municipality_boundaries.py)
rather than duplicating the load logic in both places.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import text

from .extensions import db
from .models import Boundary, RWTScheduleConfig

logger = logging.getLogger(__name__)

SHAPEFILE_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_place_500k.zip"
)
_SHAPEFILE_DIR = Path("data") / "shapefiles" / "cb_2024_us_place_500k"
_SHAPEFILE_NAME = "cb_2024_us_place_500k.shp"

# Reuses the existing "villages" boundary type (app_core/boundaries.py's
# BOUNDARY_TYPE_CONFIG, and already an option in the admin manual-upload
# dropdown) for both incorporated cities and villages -- see the module
# docstring in scripts/load_municipality_boundaries.py for why no separate
# "city" type was added.
BOUNDARY_TYPE = "villages"

# Same table as app_core/county_boundaries.py's STATE_ABBREV_TO_FIPS, kept
# separate rather than imported -- these are two independent data loaders.
STATE_ABBREV_TO_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12",
    "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18",
    "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23",
    "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38",
    "OH": "39", "OK": "40", "OR": "41", "PA": "42", "PR": "72",
    "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48",
    "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _find_bundled_shapefile() -> Optional[Path]:
    path = _project_root() / _SHAPEFILE_DIR / _SHAPEFILE_NAME
    return path if path.exists() else None


def download_shapefile() -> Path:
    """Download and extract the Census incorporated-places shapefile into
    data/shapefiles/, returning the local .shp path. No-op if already
    present."""
    import requests

    dest_dir = _project_root() / "data" / "shapefiles"
    extract_dir = dest_dir / _SHAPEFILE_DIR.name
    shp_path = extract_dir / _SHAPEFILE_NAME

    if shp_path.exists():
        return shp_path

    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / "cb_2024_us_place_500k.zip"

    if not zip_path.exists():
        logger.info("Downloading %s ...", SHAPEFILE_URL)
        resp = requests.get(SHAPEFILE_URL, stream=True, timeout=120)
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                f.write(chunk)

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    return shp_path


def county_fips5(code: str) -> str:
    """Normalize either a plain 5-digit Census county FIPS (SSCCC) or a
    6-digit SAME code (PSSCCC, P = portion digit -- see
    app_utils/fips_codes.py's _to_same_county_code, the inverse of this)
    down to the bare 5-digit STATEFP+COUNTYFP used throughout this module.
    Whether the input has a leading portion digit or not, the last 5
    digits are always state+county -- a SAME code's portion digit only
    ever describes a sub-county broadcast area, never a different county,
    so it's irrelevant to which county's places to load."""
    digits = ''.join(ch for ch in code if ch.isdigit())
    return digits.zfill(5)[-5:]


def get_default_coverage_counties() -> List[str]:
    """The station's configured RWT coverage counties (SAME codes), or []
    if not configured. Not AlertFilterSettings.fips_codes -- see this
    module's docstring."""
    config = RWTScheduleConfig.query.first()
    return list(config.same_codes or []) if config else []


def get_village_count() -> int:
    return Boundary.query.filter_by(type=BOUNDARY_TYPE).count()


def _intersects_scope(
    geojson_str: str, county_geoids: Optional[List[str]], state_fips: Optional[str],
) -> bool:
    if county_geoids is not None:
        return bool(db.session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM us_county_boundaries "
                "WHERE geoid = ANY(:geoids) "
                "AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)))"
            ),
            {"geoids": county_geoids, "g": geojson_str},
        ).scalar())
    if state_fips is not None:
        return bool(db.session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM us_county_boundaries "
                "WHERE statefp = :sfp "
                "AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)))"
            ),
            {"sfp": state_fips, "g": geojson_str},
        ).scalar())
    return True


def load_places_from_shapefile(
    shp_path: str,
    county_fips: Optional[List[str]] = None,
    state_filter: Optional[str] = None,
    replace: bool = False,
) -> Dict[str, Any]:
    """Load incorporated places (cities/villages, not CDPs) from a Places
    shapefile into the ``boundaries`` table, scoped to the given counties
    or state. Returns a summary dict; ``error`` is set on failure.

    County scoping is a real PostGIS ST_Intersects test against
    ``us_county_boundaries`` (already loaded by
    scripts/load_us_county_boundaries.py) rather than a FIPS-string
    compare -- the Places file has no per-record county field, since a
    place isn't nested inside exactly one county the way a township is.
    """
    import shapefile as shp

    state_fips = None
    if state_filter:
        state_fips = STATE_ABBREV_TO_FIPS.get(state_filter.upper())
        if not state_fips:
            return {"error": f"Unknown state abbreviation: {state_filter}"}

    county_geoids: Optional[List[str]] = None
    target_statefps: Optional[Set[str]] = None
    if county_fips:
        county_geoids = sorted({county_fips5(c) for c in county_fips if c.strip()})
        target_statefps = {g[:2] for g in county_geoids}
    elif state_fips is not None:
        target_statefps = {state_fips}
    else:
        return {"error": "No counties or state given to scope this load to"}

    try:
        sf = shp.Reader(shp_path)
    except Exception as exc:
        return {"error": f"Could not read shapefile: {exc}"}

    if replace:
        deleted = 0
        for boundary in Boundary.query.filter_by(type=BOUNDARY_TYPE).all():
            geojson_str = db.session.execute(
                text("SELECT ST_AsGeoJSON(:g)"), {"g": boundary.geom}
            ).scalar()
            if geojson_str and _intersects_scope(geojson_str, county_geoids, state_fips):
                db.session.delete(boundary)
                deleted += 1
        db.session.commit()
    else:
        deleted = 0

    inserted = 0
    skipped_existing = 0
    skipped_cdp = 0
    skipped_out_of_scope = 0

    for shape_rec in sf.iterShapeRecords():
        rec = shape_rec.record.as_dict()
        statefp = rec.get("STATEFP", "")

        if target_statefps is not None and statefp not in target_statefps:
            skipped_out_of_scope += 1
            continue

        name = rec.get("NAMELSAD") or rec.get("NAME") or ""
        if not name:
            continue
        if name.endswith("CDP"):
            skipped_cdp += 1
            continue

        geoid = rec.get("GEOID", "")
        state_name = rec.get("STATE_NAME", "")
        description = f"{state_name} (GEOID {geoid})".strip(" ")

        geojson_str = json.dumps(shape_rec.shape.__geo_interface__)

        if not _intersects_scope(geojson_str, county_geoids, state_fips):
            skipped_out_of_scope += 1
            continue

        if not replace:
            existing = Boundary.query.filter_by(
                type=BOUNDARY_TYPE, name=name, description=description,
            ).first()
            if existing:
                skipped_existing += 1
                continue

        boundary = Boundary(name=name, type=BOUNDARY_TYPE, description=description)
        boundary.geom = db.session.execute(
            text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)"),
            {"g": geojson_str},
        ).scalar()
        db.session.add(boundary)
        inserted += 1

        if inserted % 100 == 0:
            db.session.commit()

    db.session.commit()

    return {
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "skipped_cdp": skipped_cdp,
        "skipped_out_of_scope": skipped_out_of_scope,
        "deleted": deleted,
    }
