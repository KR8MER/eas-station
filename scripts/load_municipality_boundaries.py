#!/usr/bin/env python3
"""CLI wrapper for loading US incorporated-place (city/village) boundaries.

Thin argparse layer over app_core/municipality_boundaries.py -- see that
module's docstring for the "why" (affected-municipalities display, why
Places and not county subdivisions/townships, why RWTScheduleConfig.same_codes
and not AlertFilterSettings.fips_codes, why county scoping needs a real
spatial test). The same load logic also backs the admin UI's "Load Cities &
Villages" button on Settings -> Data & Storage -> Boundaries
(webapp/admin/boundaries.py's /admin/load_municipality_boundaries route) --
this script exists for one-off/scripted use, not because the feature is
CLI-only.

Usage (use the project virtualenv Python)::

    # Load cities/villages for every county in the Weekly Test Automation
    # page's configured "Default RWT Counties"
    /opt/eas-station/venv/bin/python scripts/load_municipality_boundaries.py

    # Load only Ohio, or only specific counties, regardless of settings
    /opt/eas-station/venv/bin/python scripts/load_municipality_boundaries.py --state OH
    /opt/eas-station/venv/bin/python scripts/load_municipality_boundaries.py --county-fips 039095 039173

    # Specify a local shapefile instead of downloading
    /opt/eas-station/venv/bin/python scripts/load_municipality_boundaries.py --shapefile data/shapefiles/cb_2024_us_place_500k/cb_2024_us_place_500k.shp

Data source: US Census Bureau Cartographic Boundary Files (500k resolution)
https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html

To pick up a newer year's release, bump the "2024" in
app_core/municipality_boundaries.py's SHAPEFILE_URL / _SHAPEFILE_DIR /
_SHAPEFILE_NAME (Census publishes a new GENZ vintage most years) and delete
the old data/shapefiles/cb_* directory so it re-downloads.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(
        description="Load US incorporated city/village boundaries from Census TIGER/Line shapefiles"
    )
    parser.add_argument("--shapefile", help="Path to a local .shp file (skips download)")
    parser.add_argument(
        "--state",
        help="Load every city/village in this state (e.g. OH), ignoring fips_codes/--county-fips",
    )
    parser.add_argument(
        "--county-fips",
        nargs="+",
        help="Load only cities/villages intersecting these county FIPS codes "
             "(space-separated, 5- or 6-digit). Defaults to the Weekly Test "
             "Automation page's Default RWT Counties.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing villages/cities boundaries in the requested scope before loading",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except (ImportError, PermissionError, OSError):
        pass

    from app import app
    with app.app_context():
        from app_core.municipality_boundaries import (
            county_fips5,
            download_shapefile,
            get_default_coverage_counties,
            load_places_from_shapefile,
        )

        county_fips = args.county_fips
        if not args.state and not county_fips:
            county_fips = get_default_coverage_counties()
            if not county_fips:
                print(
                    "No --county-fips/--state given and the Weekly Test Automation "
                    "page's 'Default RWT Counties' aren't configured. Nothing to "
                    "load -- pass one of those, or configure RWT coverage counties "
                    "first (/rwt-schedule)."
                )
                sys.exit(1)
            print(f"Using this station's configured RWT coverage counties: {county_fips}")

        shp_path = args.shapefile or str(download_shapefile())
        print(f"Loading from {shp_path}")

        result = load_places_from_shapefile(
            shp_path,
            county_fips=county_fips,
            state_filter=args.state,
            replace=args.replace,
        )

        if result.get("error"):
            print(f"Error: {result['error']}")
            sys.exit(1)

        if args.replace:
            print(f"Deleted {result['deleted']} existing villages boundaries in scope")
        print(
            f"Done: {result['inserted']} inserted, {result['skipped_existing']} already present, "
            f"{result['skipped_cdp']} unincorporated CDPs skipped, "
            f"{result['skipped_out_of_scope']} outside the requested county/state scope"
        )
        print(f"\nLoaded {result['inserted']} city/village boundaries")


if __name__ == "__main__":
    main()
