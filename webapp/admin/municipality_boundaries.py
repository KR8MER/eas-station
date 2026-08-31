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

"""Admin routes for loading US city/village boundaries (the "affected
municipalities" data source) from Census TIGER/Line "Places" shapefiles.

Deletion reuses the existing generic
DELETE /admin/clear_boundaries/villages route in webapp/admin/boundaries.py
-- no separate delete route needed here.
"""

from flask import Blueprint, jsonify, request

from app_core.auth.roles import require_permission
from app_core.municipality_boundaries import (
    _find_bundled_shapefile,
    download_shapefile,
    get_default_coverage_counties,
    get_village_count,
    load_places_from_shapefile,
)

municipality_boundaries_bp = Blueprint("municipality_boundaries", __name__)


@municipality_boundaries_bp.route("/municipality_boundaries/status")
@require_permission("system.configure")
def municipality_boundaries_status():
    """Current city/village boundary count and configured coverage counties.

    Returns:
        200 with {village_count, coverage_counties, shapefile_cached}.
    """
    return jsonify({
        "success": True,
        "village_count": get_village_count(),
        "coverage_counties": get_default_coverage_counties(),
        "shapefile_cached": _find_bundled_shapefile() is not None,
    })


@municipality_boundaries_bp.route("/load_municipality_boundaries", methods=["POST"])
@require_permission("system.configure")
def load_municipality_boundaries():
    """Load city/village boundaries for the station's coverage counties.

    Downloads the Census "Places" cartographic shapefile on first use
    (cached under data/shapefiles/ afterward) and loads incorporated
    cities/villages -- not unincorporated CDPs -- intersecting the Weekly
    Test Automation page's configured Default RWT Counties.

    Body:
        replace (bool, optional): delete existing villages boundaries in
            scope before loading. Default false (skip already-loaded ones).

    Returns:
        200 with {success, message, inserted, skipped_existing, skipped_cdp,
        skipped_out_of_scope, deleted}.
        400 if no coverage counties are configured, or on a load error.
    """
    data = request.get_json(silent=True) or {}
    replace = bool(data.get("replace", False))

    county_fips = get_default_coverage_counties()
    if not county_fips:
        return jsonify({
            "error": "No coverage counties configured -- set the Weekly Test "
                     "Automation page's Default RWT Counties first (/rwt-schedule)",
        }), 400

    try:
        shp_path = str(download_shapefile())
    except Exception as exc:
        return jsonify({"error": f"Could not download Census shapefile: {exc}"}), 400

    result = load_places_from_shapefile(
        shp_path, county_fips=county_fips, replace=replace,
    )
    if result.get("error"):
        return jsonify({"error": result["error"]}), 400

    return jsonify({
        "success": True,
        "message": (
            f"Loaded {result['inserted']} city/village boundaries "
            f"({result['skipped_existing']} already present, "
            f"{result['skipped_cdp']} unincorporated CDPs skipped)"
        ),
        **result,
    })
