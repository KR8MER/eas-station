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

"""NEXRAD Level II radar decode -- the raw per-site volume scan (~250m
range-gate resolution near the radar), not the Level III national mosaic
_fetch_radar_overlay() in maps.py pulls from Iowa Environmental Mesonet's
WMS-T service (~1km, blocky at close zoom). This is the fine-grained look
public radar apps show near a site; it degrades toward that same
blockiness at long range from one, since beam width genuinely grows with
distance -- no amount of resolution here changes the physics.

Source: NOAA's public Level II archive on AWS Open Data
(bucket ``unidata-nexrad-level2``, no credentials needed), decoded with
Py-ART (github.com/ARM-DOE/pyart). Site coordinates come from the NWS API
(api.weather.gov/radar/stations), cached in-process.

Best-effort throughout: every public function returns ``None`` on any
failure (no site in range, no volume near the requested time, a download
or decode error) rather than raising. Callers must fall back to the WMS
mosaic -- this must never be the reason a radar overlay fails to render.
"""

import logging
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

import numpy as np
import requests
from PIL import Image

logger = logging.getLogger('eas')

_L2_BUCKET = 'unidata-nexrad-level2'
_STATIONS_URL = 'https://api.weather.gov/radar/stations'
_USER_AGENT = 'EASStation/1.0 (+https://github.com/KR8MER/eas-station)'

# A WSR-88D's nominal base-reflectivity range. Beyond this there is no
# volume data for a site at all, not just a coarser one.
_MAX_SITE_RANGE_KM = 230.0

# Same NWS base-reflectivity ramp as maps.py's WMS-mosaic legend
# (_REFLECTIVITY_LEGEND there imports this list, so both sources agree on
# what a color means).
REFLECTIVITY_LEGEND = [
    ('5', (100, 200, 100)),
    ('20', (40, 160, 40)),
    ('30', (240, 230, 60)),
    ('40', (250, 160, 40)),
    ('50', (220, 40, 40)),
    ('60+', (200, 60, 200)),
]
_STOP_VALUES = np.array([5, 20, 30, 40, 50, 60], dtype=float)
_STOP_R = np.array([100, 40, 240, 250, 220, 200], dtype=float)
_STOP_G = np.array([200, 160, 230, 160, 40, 60], dtype=float)
_STOP_B = np.array([100, 40, 60, 40, 40, 200], dtype=float)


def _legend_hex_colors() -> List[str]:
    """REFLECTIVITY_LEGEND's colors as ``#rrggbb`` strings, in stop order --
    matplotlib's ListedColormap wants hex/named colors, not raw RGB
    tuples. Kept as its own function so the exact same stop values back
    both the legend swatches and what _plot_ppi actually draws."""
    return [
        f'#{r:02x}{g:02x}{b:02x}'
        for r, g, b in zip(_STOP_R.astype(int), _STOP_G.astype(int), _STOP_B.astype(int))
    ]


# ── Site lookup ─────────────────────────────────────────────────────────────

_sites_cache: Optional[List[Tuple[str, float, float]]] = None
_sites_cache_at: Optional[datetime] = None
_SITES_TTL = timedelta(hours=6)


def _load_sites() -> List[Tuple[str, float, float]]:
    """(site_id, lat, lon) for every WSR-88D site, from the NWS API.

    The site list essentially never changes -- a multi-hour cache just
    avoids a network round-trip on every render.
    """
    global _sites_cache, _sites_cache_at
    now = datetime.now(timezone.utc)
    if _sites_cache is not None and _sites_cache_at and now - _sites_cache_at < _SITES_TTL:
        return _sites_cache

    try:
        resp = requests.get(_STATIONS_URL, headers={'User-Agent': _USER_AGENT}, timeout=10)
        resp.raise_for_status()
        sites = []
        for feat in resp.json().get('features', []):
            props = feat.get('properties', {})
            if props.get('stationType') != 'WSR-88D':
                continue
            coords = (feat.get('geometry') or {}).get('coordinates')
            site_id = props.get('id')
            if not coords or not site_id:
                continue
            sites.append((site_id, float(coords[1]), float(coords[0])))
    except Exception as exc:
        logger.debug("Level II site list fetch failed: %s", exc)
        return _sites_cache or []

    if sites:
        _sites_cache = sites
        _sites_cache_at = now
    return _sites_cache or []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_site(lat: float, lon: float) -> Optional[str]:
    """The closest WSR-88D site to (lat, lon), or None if every site is
    beyond nominal base-reflectivity range (a genuine coverage gap)."""
    best_id, best_km = None, None
    for site_id, s_lat, s_lon in _load_sites():
        km = _haversine_km(lat, lon, s_lat, s_lon)
        if best_km is None or km < best_km:
            best_id, best_km = site_id, km
    if best_id is not None and best_km is not None and best_km <= _MAX_SITE_RANGE_KM:
        return best_id
    return None


# ── Volume lookup (S3) ──────────────────────────────────────────────────────

def _s3_client():
    # Imported lazily so a plain `import radar_level2` (e.g. for
    # REFLECTIVITY_LEGEND) doesn't pay boto3's import cost.
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    return boto3.client('s3', config=Config(signature_version=UNSIGNED))


def _list_day_keys(s3, site: str, day: datetime) -> List[str]:
    prefix = f"{day.year:04d}/{day.month:02d}/{day.day:02d}/{site}/"
    try:
        resp = s3.list_objects_v2(Bucket=_L2_BUCKET, Prefix=prefix, MaxKeys=1000)
    except Exception as exc:
        logger.debug("Level II S3 listing failed for %s: %s", prefix, exc)
        return []
    # `_MDM` keys are a metadata sidecar, not a volume file.
    return [o['Key'] for o in resp.get('Contents', []) if not o['Key'].endswith('_MDM')]


def _parse_key_time(key: str) -> Optional[datetime]:
    # e.g. "2026/08/10/KCLE/KCLE20260810_005739_V06"
    fname = key.rsplit('/', 1)[-1]
    try:
        datestr = fname[4:12]
        timestr = fname[13:19]
        return datetime.strptime(datestr + timestr, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        return None


def find_volume_key(s3, site: str, when: Optional[datetime], tolerance_minutes: float = 6.0) -> Optional[str]:
    """The Level II volume for *site* nearest *when* (UTC), within
    *tolerance_minutes*. *when=None* means live -- the latest available
    volume for today (or yesterday, in the few minutes right after UTC
    midnight before today has any)."""
    if when is None:
        now = datetime.now(timezone.utc)
        keys = _list_day_keys(s3, site, now)
        if not keys:
            keys = _list_day_keys(s3, site, now - timedelta(days=1))
        return sorted(keys)[-1] if keys else None

    when = when.astimezone(timezone.utc) if when.tzinfo else when.replace(tzinfo=timezone.utc)
    candidates = _list_day_keys(s3, site, when)
    # A volume just either side of UTC midnight can land on the adjacent day.
    if when.hour == 0:
        candidates += _list_day_keys(s3, site, when - timedelta(days=1))
    elif when.hour == 23:
        candidates += _list_day_keys(s3, site, when + timedelta(days=1))

    best_key, best_diff = None, None
    for key in candidates:
        t = _parse_key_time(key)
        if t is None:
            continue
        diff = abs((t - when).total_seconds())
        if best_diff is None or diff < best_diff:
            best_key, best_diff = key, diff
    if best_key is not None and best_diff is not None and best_diff <= tolerance_minutes * 60:
        return best_key
    return None


# ── Decode, plot ─────────────────────────────────────────────────────────────

#: Gaussian sigma (pixels) for _soften_beam_edges. Real hardware angular
#: resolution -- confirmed by rendering the same bbox at 4x the pixel
#: density and finding the band pattern unchanged, the diagnostic that
#: rules out a rasterization artifact -- means adjacent-beam boundaries
#: read as hard vertical bands at typical alert-polygon zoom (tens of km).
#: Deliberately light: enough to soften those seams, not enough to blur
#: real storm structure (hook echoes, core gradients) back into the mush
#: pyart.map.grid_from_radars produced, which is why that approach was
#: dropped in the first place.
_SOFTEN_SIGMA_PX = 2.5


def _soften_beam_edges(img: Image.Image, sigma: float = _SOFTEN_SIGMA_PX) -> Image.Image:
    """Light Gaussian blur across real (not artifact) beam-to-beam seams.

    Blurring RGBA naively bleeds color from fully-transparent "no echo"
    pixels (whatever arbitrary RGB a masked cell happens to carry) into
    visible edges. Alpha-premultiplying first, blurring, then dividing
    back out avoids that -- standard technique, not obvious enough to
    skip documenting.
    """
    from scipy.ndimage import gaussian_filter

    arr = np.asarray(img, dtype=np.float64)
    rgb, alpha = arr[..., :3], arr[..., 3:4]
    premultiplied = rgb * (alpha / 255.0)

    blurred_premult = gaussian_filter(premultiplied, sigma=(sigma, sigma, 0))
    blurred_alpha = gaussian_filter(alpha, sigma=(sigma, sigma, 0))

    safe_alpha = np.where(blurred_alpha > 1e-6, blurred_alpha, 1.0)
    out_rgb = np.clip(blurred_premult / (safe_alpha / 255.0), 0, 255)
    out = np.concatenate([out_rgb, np.clip(blurred_alpha, 0, 255)], axis=-1)
    return Image.fromarray(out.astype(np.uint8), mode='RGBA')


def _plot_ppi(
    radar: Any,
    center_lat: float,
    center_lon: float,
    deg_lat: float,
    deg_lon: float,
    canvas_w: int,
    canvas_h: int,
    opacity: float = 1.0,
) -> Optional[Image.Image]:
    """Render the lowest sweep's reflectivity as a geographic PPI plot via
    Py-ART's own ``RadarMapDisplay.plot_ppi_map`` -- each gate drawn as its
    true azimuth/range quadrilateral (matplotlib ``pcolormesh`` under the
    hood), not interpolated onto a Cartesian grid the way
    ``pyart.map.grid_from_radars`` does. That interpolation was tried
    first and produced a visibly smoothed result -- blurry blobs even at
    very high output resolution, confirmed by requesting the same bbox at
    increasing pixel counts and finding no new detail appeared. This is
    the sharp, gate-accurate look public radar apps show.

    Returns None (not raises) on any rendering failure, same contract as
    the rest of this module -- a bad sweep must fall back to WMS, not
    break the caller.
    """
    import io

    import cartopy.crs as ccrs
    import cmweather  # noqa: F401 -- registers the 'NWSRef' colormap on import
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import pyart

    # cmweather's 'NWSRef' is the standard ~15-band NWS reflectivity scale
    # (the same one RadarScope, GRLevel3 and NWS's own displays use) --
    # far finer than a hand-rolled 6-color ramp, which is coarse enough to
    # flatten real storm structure (hook echoes, gradient detail) into
    # solid blocks. REFLECTIVITY_LEGEND's 6 labels stay as the on-page
    # legend's tick marks (RadarScope's legend does the same -- a handful
    # of labels along a much finer continuous scale, not one label per
    # color actually drawn).
    #
    # Sub-5-dBZ returns are masked out before plotting (matches the
    # legend's stated floor and the WMS mosaic's own convention) rather
    # than via vmin, so they render fully transparent instead of the
    # colormap's bottom color.
    field = radar.fields['reflectivity']['data']
    radar.fields['reflectivity']['data'] = np.ma.masked_less(field, _STOP_VALUES[0])

    fig = plt.figure(figsize=(canvas_w / 100, canvas_h / 100), dpi=100)
    try:
        display = pyart.graph.RadarMapDisplay(radar)
        display.plot_ppi_map(
            'reflectivity', sweep=0,
            min_lon=center_lon - deg_lon, max_lon=center_lon + deg_lon,
            min_lat=center_lat - deg_lat, max_lat=center_lat + deg_lat,
            # Web Mercator, matching the OSM basemap tiles this composites
            # onto -- PlateCarree (plain lat/lon) has a different
            # north-south scale at non-equatorial latitudes, which
            # misaligned/distorted the overlay against the basemap and
            # hazard polygon underneath it.
            projection=ccrs.epsg(3857),
            cmap='NWSRef', vmin=_STOP_VALUES[0], vmax=75, alpha=opacity,
            colorbar_flag=False, title_flag=False,
            add_grid_lines=False, embellish=False,
            fig=fig,
        )
        ax = fig.axes[0]
        ax.set_axis_off()
        ax.set_position([0, 0, 1, 1])
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, transparent=True, pad_inches=0)
        buf.seek(0)
        img = Image.open(buf).convert('RGBA')
        img.load()  # decode fully before the buffer goes out of scope
        return _soften_beam_edges(img)
    finally:
        # Agg figures are not reclaimed by Python's normal GC (matplotlib
        # keeps its own registry) -- explicit close is required or every
        # render leaks a full canvas for the life of the worker process.
        plt.close(fig)


def render_frame(
    center_lat: float,
    center_lon: float,
    when: Optional[datetime],
    half_width_m: float,
    canvas_w: int,
    canvas_h: int,
    opacity: float = 1.0,
) -> Optional[Image.Image]:
    """Colorized base-reflectivity RGBA image, rendered as a geographic PPI
    plot (real gate quadrilaterals, no interpolation -- see _plot_ppi) at
    (canvas_w x canvas_h) spanning +/-half_width_m around (center_lat,
    center_lon) at *when* (None = latest/live).

    Best-effort: returns None on any failure (no site in range, no volume
    near *when*, download/decode/grid error). Callers fall back to the
    Level III WMS mosaic.
    """
    site = nearest_site(center_lat, center_lon)
    if site is None:
        logger.debug("Level II: no WSR-88D site within range of (%.3f, %.3f)", center_lat, center_lon)
        return None

    s3 = _s3_client()
    key = find_volume_key(s3, site, when)
    if key is None:
        logger.debug("Level II: no volume for %s near %s", site, when)
        return None

    tmp_path = None
    try:
        # Deferred: pyart's import chain (numpy/scipy/matplotlib/xarray)
        # costs a few seconds -- only pay it on an actual render.
        import pyart

        fd, tmp_path = tempfile.mkstemp(suffix='.ar2v')
        os.close(fd)
        s3.download_file(_L2_BUCKET, key, tmp_path)
        radar = pyart.io.read_nexrad_archive(tmp_path)

        deg_lat = half_width_m / 111000.0
        deg_lon = half_width_m / (111000.0 * math.cos(math.radians(center_lat)))
        return _plot_ppi(
            radar, center_lat, center_lon, deg_lat, deg_lon, canvas_w, canvas_h,
            opacity=opacity,
        )
    except Exception as exc:
        logger.warning("Level II render failed (site=%s, key=%s): %s", site, key, exc)
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
