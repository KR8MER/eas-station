#!/usr/bin/env python3
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

"""
Download NWS GIS data files for EAS Station.

Downloads two official NOAA/NWS shapefiles into the ``assets/`` directory:

1. **Public Forecast Zones** (``z_*.dbf``) from
   https://www.weather.gov/gis/PublicZones
   Used by the zone catalog (``tools/sync_zone_catalog.py``).

2. **NWR Political Subdivisions / Partial Counties** (``cs*.dbf``) from
   https://www.weather.gov/gis/NWRPartialCounties
   Used to resolve SAME partition-digit codes such as 627137
   (NOAA Hazard Services partial-county alert targeting;
    see https://vlab.noaa.gov/web/hazard-services/partial-county-alerts).

3. **Marine Zones** (``mz*.dbf``) from
   https://www.weather.gov/gis/MarineZones
   The NWS UGC zones for coastal, Great Lakes, and offshore waters
   (prefixes ``AM``, ``AN``, ``GM``, ``LC``, ``LE``, ``LH``, ``LM``, ``LO``,
   ``LS``, ``PH``, ``PK``, ``PM``, ``PS``, ``PZ``, ``SL``). Schema is
   compatible with the public-zone DBF, so the same loader and
   ``tools/sync_zone_catalog.py`` import them into ``nws_zones``.

Usage::

    python tools/download_nws_gis_data.py             # download all three
    python tools/download_nws_gis_data.py --zones     # only public zone catalog
    python tools/download_nws_gis_data.py --partial   # only partial counties
    python tools/download_nws_gis_data.py --marine    # only marine zone catalog
    python tools/download_nws_gis_data.py --dry-run   # print URLs, do not download

See ``docs/reference/NWS_ZONE_CATALOG.md`` for the full refresh procedure.
"""

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# NWS data source URLs
# ---------------------------------------------------------------------------

# Landing page that lists the current zone-catalog ZIP download link.
ZONES_INDEX_URL = "https://www.weather.gov/gis/PublicZones"

# Landing page that lists the current partial-county ZIP download link.
PARTIAL_COUNTIES_INDEX_URL = "https://www.weather.gov/gis/NWRPartialCounties"

# Landing page that lists the current marine-zone ZIP download link.
MARINE_ZONES_INDEX_URL = "https://www.weather.gov/gis/MarineZones"

# NOAA Vlab reference for the Hazard Services partial-county alert spec:
# https://vlab.noaa.gov/web/hazard-services/partial-county-alerts

# Shapefiles are hosted under this base path:
SHAPEFILES_BASE = "https://www.weather.gov"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"

# Patterns that match the ZIP filenames linked from the NWS index pages.
# e.g.  z_18mr25.zip   z_03mr25.zip
#       cs16ap26.zip   cs18mr25.zip   cs_25mr19.zip
_ZONE_ZIP_RE = re.compile(r'href="([^"]*\bz_\d{2}[a-z]{2}\d{2}\.zip[^"]*)"', re.I)
_PARTIAL_ZIP_RE = re.compile(r'href="([^"]*\bcs_?\d{2}[a-z]{2}\d{2}\.zip[^"]*)"', re.I)
_MARINE_ZIP_RE = re.compile(r'href="([^"]*\bmz_?\d{2}[a-z]{2}\d{2}\.zip[^"]*)"', re.I)

# Hard-coded fallback URLs used when the index page cannot be fetched/parsed.
# Update these whenever NOAA publishes a new vintage of the shapefiles.
_ZONE_FALLBACK = "https://www.weather.gov/source/gis/Shapefiles/WSOM/z_18mr25.zip"
_PARTIAL_FALLBACK = "https://www.weather.gov/source/gis/Shapefiles/County/cs16ap26.zip"
_MARINE_FALLBACK = "https://www.weather.gov/source/gis/Shapefiles/WSOM/mz18mr25.zip"

_USER_AGENT = (
    "Mozilla/5.0 (compatible; EASStation/1.0; "
    "+https://github.com/KR8MER/eas-station)"
)

# Only allow fetches from the official NWS domain to limit the attack surface.
_ALLOWED_HOST = "www.weather.gov"


def _get(url: str, timeout: int = 30) -> bytes:
    """Fetch *url* and return the raw response body.

    Raises ``ValueError`` if *url* does not belong to the allowed NWS host.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != _ALLOWED_HOST:
        raise ValueError(
            f"Refusing to fetch from untrusted host: {url!r}. "
            f"Only https://{_ALLOWED_HOST}/ URLs are permitted."
        )
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def _find_zip_url(index_url: str, pattern: re.Pattern, fallback: str) -> str:
    """Scrape *index_url* for a ZIP href matching *pattern*.

    Returns the first match (resolved to an absolute URL), or *fallback* if
    the page cannot be fetched or no match is found.
    """
    try:
        html = _get(index_url).decode("utf-8", errors="replace")
    except (URLError, HTTPError, OSError) as exc:
        print(f"  [warn] Could not fetch {index_url}: {exc}; using fallback URL")
        return fallback

    matches = pattern.findall(html)
    if not matches:
        print(
            f"  [warn] No matching ZIP link found on {index_url}; using fallback URL"
        )
        return fallback

    href = matches[0]
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return SHAPEFILES_BASE + href
    return SHAPEFILES_BASE + "/" + href.lstrip("./")


def _extract_dbf(zip_bytes: bytes, zip_url: str) -> Optional[tuple[str, bytes]]:
    """Return ``(filename, data)`` for the first ``.dbf`` inside *zip_bytes*."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            dbf_names = [n for n in zf.namelist() if n.lower().endswith(".dbf")]
            if not dbf_names:
                print(f"  [error] No .dbf file found in {zip_url}")
                return None
            # Prefer the file whose basename matches the ZIP name
            zip_stem = Path(zip_url.split("?")[0]).stem.lower()
            chosen = next(
                (n for n in dbf_names if Path(n).stem.lower() == zip_stem),
                dbf_names[0],
            )
            return Path(chosen).name, zf.read(chosen)
    except zipfile.BadZipFile as exc:
        print(f"  [error] Could not open ZIP from {zip_url}: {exc}")
        return None


def _download_and_install(
    index_url: str,
    pattern: re.Pattern,
    fallback: str,
    label: str,
    dry_run: bool,
) -> bool:
    """Locate, download, and extract the NWS shapefile ZIP.

    Returns True on success (or dry-run), False on error.
    """
    print(f"\n{'─' * 60}")
    print(f"Fetching {label} index: {index_url}")
    zip_url = _find_zip_url(index_url, pattern, fallback)
    print(f"  ZIP URL: {zip_url}")

    if dry_run:
        print("  [dry-run] Skipping download.")
        return True

    print("  Downloading …", end=" ", flush=True)
    try:
        zip_bytes = _get(zip_url, timeout=120)
    except (URLError, HTTPError, OSError) as exc:
        print(f"\n  [error] Download failed: {exc}")
        return False
    print(f"ok ({len(zip_bytes):,} bytes)")

    result = _extract_dbf(zip_bytes, zip_url)
    if result is None:
        return False
    dbf_name, dbf_data = result

    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _ASSETS_DIR / dbf_name
    dest.write_bytes(dbf_data)
    print(f"  Saved → {dest.resolve()}  ({len(dbf_data):,} bytes)")

    # Remove stale files with the same prefix (e.g. old z_05mr24.dbf when
    # new z_18mr25.dbf is installed) so auto-detection always picks the newest.
    prefix = re.sub(r"_?\d{2}[a-z]{2}\d{2}\.dbf$", "", dbf_name.lower())
    for old in _ASSETS_DIR.glob(f"{prefix}*.dbf"):
        if old.name != dbf_name:
            old.unlink(missing_ok=True)
            print(f"  Removed stale file: {old.name}")

    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download NWS GIS shapefiles (zones and partial counties) "
        "into the EAS Station assets/ directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--zones",
        action="store_true",
        help="Download only the Public Forecast Zones file (z_*.dbf).",
    )
    parser.add_argument(
        "--partial",
        action="store_true",
        help="Download only the NWR Partial Counties file (cs*.dbf).",
    )
    parser.add_argument(
        "--marine",
        action="store_true",
        help="Download only the NWS Marine Zones file (mz*.dbf).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve download URLs and print them without downloading.",
    )
    args = parser.parse_args(argv)

    # Default: download all unless one or more explicit flags are set.
    any_explicit = args.zones or args.partial or args.marine
    do_zones = args.zones or not any_explicit
    do_partial = args.partial or not any_explicit
    do_marine = args.marine or not any_explicit

    success = True

    if do_zones:
        ok = _download_and_install(
            index_url=ZONES_INDEX_URL,
            pattern=_ZONE_ZIP_RE,
            fallback=_ZONE_FALLBACK,
            label="Public Forecast Zones",
            dry_run=args.dry_run,
        )
        success = success and ok

    if do_partial:
        ok = _download_and_install(
            index_url=PARTIAL_COUNTIES_INDEX_URL,
            pattern=_PARTIAL_ZIP_RE,
            fallback=_PARTIAL_FALLBACK,
            label="NWR Partial Counties (political subdivisions)",
            dry_run=args.dry_run,
        )
        success = success and ok

    if do_marine:
        ok = _download_and_install(
            index_url=MARINE_ZONES_INDEX_URL,
            pattern=_MARINE_ZIP_RE,
            fallback=_MARINE_FALLBACK,
            label="Marine Zones (coastal, Great Lakes, offshore)",
            dry_run=args.dry_run,
        )
        success = success and ok

    if not args.dry_run:
        if success:
            print(
                "\n✓ GIS data downloaded successfully.\n"
                "  Re-run  python tools/sync_zone_catalog.py  to import zone records\n"
                "  into the database."
            )
        else:
            print(
                "\n✗ One or more downloads failed. Check network connectivity and retry.",
                file=sys.stderr,
            )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
