"""Admin routes for US county boundary management."""

from __future__ import annotations

import json as _json
import logging
import os
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request, current_app
from sqlalchemy import text
from werkzeug.utils import secure_filename

from app_core.auth.roles import require_permission
from app_core.county_boundaries import (
    delete_counties,
    get_county_count,
    get_loaded_states,
    load_counties_from_shapefile,
    search_counties,
    STATE_ABBREV_TO_FIPS,
    _find_bundled_shapefile,
    _table_exists,
)
from app_core.extensions import db
from app_core.models import USCountyBoundary

logger = logging.getLogger(__name__)

county_boundaries_bp = Blueprint("county_boundaries", __name__)


@county_boundaries_bp.route("/county_boundaries")
@require_permission("system.configure")
def county_boundaries_page():
    """Admin page for managing US county boundaries."""
    total = get_county_count()
    states = get_loaded_states()
    table_ok = _table_exists()
    bundled_path = _find_bundled_shapefile()

    return render_template(
        "admin/county_boundaries.html",
        total_counties=total,
        loaded_states=states,
        table_exists=table_ok,
        bundled_shapefile_available=bundled_path is not None,
        bundled_shapefile_path=str(bundled_path) if bundled_path else None,
        state_list=sorted(STATE_ABBREV_TO_FIPS.keys()),
    )


@county_boundaries_bp.route("/county_boundaries/info")
@require_permission("system.configure")
def county_boundaries_info():
    """Return county boundary stats as JSON."""
    return jsonify({
        "success": True,
        "total_counties": get_county_count(),
        "states": get_loaded_states(),
    })


@county_boundaries_bp.route("/county_boundaries/search")
@require_permission("system.configure")
def county_boundaries_search():
    """Search county boundaries."""
    query = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 50)), 200)
    results = search_counties(query, limit=limit)
    return jsonify({"success": True, "results": results, "count": len(results)})


@county_boundaries_bp.route("/county_boundaries/load", methods=["POST"])
@require_permission("system.configure")
def county_boundaries_load():
    """Load county boundaries from bundled shapefile."""
    state_filter = request.form.get("state") or request.json.get("state") if request.is_json else request.form.get("state")
    replace = (request.form.get("replace") or (request.json.get("replace") if request.is_json else "")) == "true"

    from app_core.county_boundaries import _find_bundled_shapefile
    shp_path = _find_bundled_shapefile()
    if not shp_path:
        return jsonify({"success": False, "error": "Bundled shapefile not found on server"}), 404

    result = load_counties_from_shapefile(
        str(shp_path),
        state_filter=state_filter or None,
        replace=replace,
    )

    if result.get("error"):
        return jsonify({"success": False, "error": result["error"]}), 400

    state_label = f" for {state_filter}" if state_filter else ""
    return jsonify({
        "success": True,
        "message": (
            f"Loaded {result['inserted']} county boundaries{state_label}"
            f" ({result['skipped']} skipped, {result['errors']} errors)"
        ),
        **result,
    })


@county_boundaries_bp.route("/county_boundaries/upload", methods=["POST"])
@require_permission("system.configure")
def county_boundaries_upload():
    """Upload a shapefile ZIP and load county boundaries."""
    import tempfile
    import zipfile

    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"success": False, "error": "No file uploaded"}), 400

    filename = secure_filename(uploaded.filename)
    if not filename.lower().endswith(".zip"):
        return jsonify({"success": False, "error": "Only .zip shapefile archives are accepted"}), 400

    state_filter = request.form.get("state") or None
    replace = request.form.get("replace") == "true"

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, filename)
        uploaded.save(zip_path)

        try:
            with zipfile.ZipFile(zip_path) as zf:
                dest = os.path.realpath(tmpdir)
                for member in zf.infolist():
                    member_dest = os.path.realpath(os.path.join(dest, member.filename))
                    if not member_dest.startswith(dest + os.sep):
                        return jsonify({"success": False, "error": "Invalid ZIP file: path traversal detected"}), 400
                    zf.extract(member, tmpdir)
        except zipfile.BadZipFile:
            return jsonify({"success": False, "error": "Invalid ZIP file"}), 400

        # Find .shp file in extracted contents
        shp_files = list(Path(tmpdir).rglob("*.shp"))
        if not shp_files:
            return jsonify({"success": False, "error": "No .shp file found in ZIP archive"}), 400

        result = load_counties_from_shapefile(
            str(shp_files[0]),
            state_filter=state_filter,
            replace=replace,
        )

    if result.get("error"):
        return jsonify({"success": False, "error": result["error"]}), 400

    return jsonify({
        "success": True,
        "message": f"Loaded {result['inserted']} county boundaries from upload",
        **result,
    })


@county_boundaries_bp.route("/county_boundaries/delete", methods=["POST"])
@require_permission("system.configure")
def county_boundaries_delete():
    """Delete county boundaries, optionally filtered by state."""
    state_filter = None
    if request.is_json:
        state_filter = request.json.get("state")
    else:
        state_filter = request.form.get("state")

    count = delete_counties(state_filter=state_filter or None)
    label = f" for {state_filter}" if state_filter else ""
    return jsonify({
        "success": True,
        "message": f"Deleted {count} county boundaries{label}",
        "deleted": count,
    })


@county_boundaries_bp.route("/county_boundaries/status")
@require_permission("system.configure")
def county_boundaries_status():
    """Return detailed table diagnostics as JSON.

    Response fields:
        table_exists     – bool, whether the us_county_boundaries table is in the DB
        total_counties   – int, total row count (0 if table missing)
        states_loaded    – int, distinct states with data
        bundled_shapefile – str or null, absolute path of the bundled shapefile
        bundled_available – bool
    """
    table_ok = _table_exists()
    total = get_county_count() if table_ok else 0
    states = get_loaded_states() if table_ok else []
    shp = _find_bundled_shapefile()

    return jsonify({
        "table_exists": table_ok,
        "total_counties": total,
        "states_loaded": len(states),
        "bundled_shapefile": str(shp) if shp else None,
        "bundled_available": shp is not None,
    })


@county_boundaries_bp.route("/county_boundaries/lookup")
@require_permission("system.configure")
def county_boundaries_lookup():
    """Look up one or more SAME codes or GEOIDs and return matching rows.

    Query params:
        same   – comma-separated 6-digit SAME codes  (e.g. ``039137,001001``)
        geoid  – comma-separated 5-digit Census GEOIDs (e.g. ``39137,01001``)

    Either param may be supplied; both may be combined.
    """
    same_raw = request.args.get("same", "").strip()
    geoid_raw = request.args.get("geoid", "").strip()

    same_codes = [s.strip() for s in same_raw.split(",") if s.strip()]
    geoid_codes = [g.strip() for g in geoid_raw.split(",") if g.strip()]

    # Convert SAME codes → GEOIDs: drop the leading '0' prefix
    for code in same_codes:
        if len(code) == 6:
            geoid_codes.append(code[1:])

    geoid_codes = list(set(geoid_codes))  # deduplicate

    if not geoid_codes:
        return jsonify({"error": "Provide at least one same or geoid parameter"}), 400

    try:
        rows = (
            USCountyBoundary.query
            .filter(USCountyBoundary.geoid.in_(geoid_codes))
            .order_by(USCountyBoundary.state_name, USCountyBoundary.name)
            .all()
        )
    except Exception as exc:
        current_app.logger.warning("County lookup query failed: %s", exc)
        return jsonify({"error": "Database query failed"}), 500

    results = [
        {
            "geoid": r.geoid,
            "same_code": r.same_code,
            "name": r.name,
            "namelsad": r.namelsad or r.name,
            "stusps": r.stusps,
            "state_name": r.state_name,
            "has_geometry": r.geom is not None,
        }
        for r in rows
    ]

    missing = [g for g in geoid_codes if g not in {r["geoid"] for r in results}]

    return jsonify({
        "queried": geoid_codes,
        "found": len(results),
        "missing": missing,
        "results": results,
    })


@county_boundaries_bp.route("/county_boundaries/geojson")
@require_permission("system.configure")
def county_boundaries_geojson():
    """Return county boundaries as a GeoJSON FeatureCollection.

    Query params:
        state  – two-letter state abbreviation (e.g. ``OH``) **or** the
                 2-digit zero-padded state FIPS code (e.g. ``39`` or ``01``).
                 Required; limits payload to a single state.
    """
    from app_core.county_boundaries import STATE_FIPS_TO_ABBREV

    state_filter = request.args.get("state", "").strip().upper()
    if not state_filter:
        return jsonify({"error": "state parameter is required"}), 400

    # Accept either "OH" (abbreviation) or "39" / "01" (state FIPS)
    if state_filter.isdigit():
        state_fips = state_filter.zfill(2)
        if state_fips not in STATE_FIPS_TO_ABBREV:
            return jsonify({"error": f"Unknown state FIPS: {state_filter}"}), 400
    else:
        state_fips = STATE_ABBREV_TO_FIPS.get(state_filter)
        if not state_fips:
            return jsonify({"error": f"Unknown state abbreviation: {state_filter}"}), 400

    try:
        rows = db.session.execute(
            text(
                """
                SELECT
                    geoid,
                    name,
                    namelsad,
                    stusps,
                    state_name,
                    statefp,
                    countyfp,
                    ST_AsGeoJSON(geom, 5)::text AS geom_json
                FROM us_county_boundaries
                WHERE statefp = :statefp AND geom IS NOT NULL
                ORDER BY name
                """
            ),
            {"statefp": state_fips},
        ).fetchall()
    except Exception as exc:
        current_app.logger.warning("County boundaries GeoJSON query failed: %s", exc)
        return jsonify({"error": "Database query failed"}), 500

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": _json.loads(row.geom_json),
            "properties": {
                "geoid": row.geoid,
                "name": row.name,
                "namelsad": row.namelsad or row.name,
                "stusps": row.stusps,
                "state_name": row.state_name,
                "same_code": f"0{row.statefp}{row.countyfp}",
            },
        })

    geojson = _json.dumps({"type": "FeatureCollection", "features": features})
    return Response(geojson, mimetype="application/geo+json")


__all__ = ["county_boundaries_bp"]
