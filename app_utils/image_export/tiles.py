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

"""Basemap tile projection, fetching and two-level caching.

Slippy-map projection maths, GeoJSON bbox/centroid/zoom selection, a bounded
in-memory LRU and a disk-backed second level that survives worker restarts.

Two raster tile providers are supported: plain OpenStreetMap (the
zero-config default) and CARTO's Dark Matter style (requires a free API
key configured via Settings -> Map Tiles -- see app_core.map_tile_settings)
-- see maps.py's _render_map() for where the provider/key is resolved.
Both are standard 256px XYZ tile pyramids, so the projection math and zoom
selection below are provider-agnostic; only _fetch_tile()'s URL and the
cache keys (which now carry the provider so switching providers can never
serve a stale tile cached under the other one) know the difference.
"""

import io
import math
import os
from collections import OrderedDict
from threading import Lock
from typing import Dict, List, Optional, Tuple

import requests as _http
from PIL import Image

from .layout import (
    TILE_SIZE,
)


# ─── OSM tile helpers ────────────────────────────────────────────────────────
def _lon_to_tx(lon: float, z: int) -> float:
    return (lon + 180.0) / 360.0 * (2 ** z)


def _lat_to_ty(lat: float, z: int) -> float:
    lat_r = math.radians(lat)
    return (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * (2 ** z)


def _geojson_bbox(geom: Dict) -> Optional[Tuple[float, float, float, float]]:
    """Return (min_lon, min_lat, max_lon, max_lat) from a GeoJSON geometry."""
    gtype = geom.get('type', '')
    coords = geom.get('coordinates', [])
    lons: List[float] = []
    lats: List[float] = []

    def _collect(ring: List) -> None:
        for pt in ring:
            lons.append(float(pt[0]))
            lats.append(float(pt[1]))

    if gtype == 'Polygon':
        for ring in coords:
            _collect(ring)
    elif gtype == 'MultiPolygon':
        for poly in coords:
            for ring in poly:
                _collect(ring)
    elif gtype == 'Point' and coords:
        lons.append(float(coords[0]))
        lats.append(float(coords[1]))
    else:
        return None

    if not lons:
        return None
    return (min(lons), min(lats), max(lons), max(lats))


def _geojson_centroid(geom: Dict) -> Optional[Tuple[float, float]]:
    """Return (lon, lat) bounding-box centre of a GeoJSON geometry."""
    bbox = _geojson_bbox(geom)
    if bbox is None:
        return None
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _detail_zoom(min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                 map_w: int, map_h: int, *, max_tiles: int = 30) -> int:
    """Zoom to *source* tiles from, given that the crop is resampled anyway.

The renderer used to pick the integer zoom at which the bbox fit 1:1
    inside the map slot, and then crop a fixed window at that zoom.  That
    conflated detail with framing and made the subject small: the bbox had
    to occupy under 60% of the frame, and flooring to an integer zoom could
    halve that again, so an alert polygon could end up covering barely a
    tenth of the map.

    Now the renderer crops to the bbox and resamples to the slot, so the
    zoom only has to decide *tile detail*, not framing.  So pick the highest zoom
    whose native pixels still cover the bbox at least as densely as the
    output needs (downscaling stays sharp; upscaling goes soft), subject to
    a tile budget so a state-wide watch does not fetch hundreds of tiles.
    """
    best = 4
    for z in range(4, 16):
        tx1, tx2 = _lon_to_tx(min_lon, z), _lon_to_tx(max_lon, z)
        ty1, ty2 = _lat_to_ty(max_lat, z), _lat_to_ty(min_lat, z)
        span_w = (tx2 - tx1) * TILE_SIZE
        span_h = (ty2 - ty1) * TILE_SIZE
        if span_w <= 0 or span_h <= 0:
            continue
        # Count tiles exactly the way ``_render_map`` will — floor/ceil of the
        # bbox edges plus a one-tile margin on each side.  An approximation
        # here silently under-counts and the renderer then bails out to the
        # "Map not available" placeholder, which is worse than a coarser zoom.
        n_tiles = (
            (math.ceil(tx2) + 1) - (math.floor(tx1) - 1) + 1
        ) * (
            (math.ceil(ty2) + 1) - (math.floor(ty1) - 1) + 1
        )
        if n_tiles > max_tiles:
            break
        best = z
        # Native resolution now meets or exceeds the output slot in both
        # axes; going further only fetches more tiles to throw pixels away.
        if span_w >= map_w and span_h >= map_h:
            break
    return best


# ─── Tile fetch + cache ─────────────────────────────────────────────────────
# OpenStreetMap's tile-usage policy asks consumers to cache tiles aggressively
# (CARTO's is no less strict); every re-render of the same alert used to
# refetch up to 30 tiles.  This bounded LRU keeps the most recently fetched
# tiles in memory so subsequent renders within the same worker process answer
# instantly and stop hammering the tile host.  Tiles are immutable for our
# purposes (zoom level pins the source pyramid), so caching is safe — only
# Pillow's underlying bytes are kept; ``Image.copy()`` on read returns a
# fresh handle that downstream code can crop/paste into without mutating the
# cached copy.
#
# The cache key carries the provider (not just z/tx/ty) so switching
# providers in Settings -> Map Tiles can never serve a tile that was cached
# under the *other* provider for the same tile coordinate.

_TILE_CACHE_MAX = 256
_TILE_CACHE: "OrderedDict[Tuple[str, int, int, int], bytes]" = OrderedDict()
_TILE_CACHE_LOCK = Lock()


def _tile_cache_get(key: Tuple[str, int, int, int]) -> Optional[bytes]:
    with _TILE_CACHE_LOCK:
        if key in _TILE_CACHE:
            _TILE_CACHE.move_to_end(key)
            return _TILE_CACHE[key]
    return None


def _tile_cache_put(key: Tuple[str, int, int, int], data: bytes) -> None:
    with _TILE_CACHE_LOCK:
        _TILE_CACHE[key] = data
        _TILE_CACHE.move_to_end(key)
        while len(_TILE_CACHE) > _TILE_CACHE_MAX:
            _TILE_CACHE.popitem(last=False)


def _tile_cache_clear() -> None:
    """Drop every cached tile — exposed for tests; not used by the renderer."""
    with _TILE_CACHE_LOCK:
        _TILE_CACHE.clear()


# ── Disk-backed second-level cache ───────────────────────────────────────────
# The in-memory LRU above covers within-process re-renders, but each fresh
# worker process pays the OSM round-trip again — wasteful on a typical
# multi-worker WSGI deployment (gunicorn restarts, gevent recycle).  A small
# disk cache survives those restarts.  OSM tiles are effectively immutable
# at our timescale; we never expire, but a future janitor task can prune by
# mtime if the cache outgrows its quota.
#
# Three levels up from app_utils/image_export/tiles.py is the repository root.
# This was two levels when the renderer was a single app_utils/image_export.py;
# the package split moved every module one directory deeper.  Getting it wrong
# is silent — tiles just cache to the wrong directory — so it is asserted in
# tests/test_image_export_themes.py.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TILE_DISK_CACHE_DIR_DEFAULT = os.path.join(_REPO_ROOT, 'data', 'tile-cache')


def _tile_disk_cache_dir() -> Optional[str]:
    """Return the resolved tile-cache directory, or None if disabled.

    Honours the ``EAS_TILE_CACHE_DIR`` env var so deployments can point
    the cache at a host-mounted volume.  Empty string disables disk
    caching entirely (useful for tests and for environments where the
    working tree is read-only).
    """
    path = os.environ.get('EAS_TILE_CACHE_DIR', _TILE_DISK_CACHE_DIR_DEFAULT)
    if not path:
        return None
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return None
    return path


def _tile_disk_path(key: Tuple[str, int, int, int]) -> Optional[str]:
    """Filesystem path for a tile, or None when disk caching is disabled."""
    base = _tile_disk_cache_dir()
    if base is None:
        return None
    provider, z, tx, ty = key
    return os.path.join(base, f'{provider}_{z}_{tx}_{ty}.png')


def _tile_disk_get(key: Tuple[str, int, int, int]) -> Optional[bytes]:
    path = _tile_disk_path(key)
    if path is None or not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def _tile_disk_put(key: Tuple[str, int, int, int], data: bytes) -> None:
    path = _tile_disk_path(key)
    if path is None:
        return
    # Write to a sibling temp file and rename — atomic on POSIX so a
    # concurrent reader never sees a half-written tile.
    tmp = f'{path}.{os.getpid()}.tmp'
    try:
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        # Disk full / read-only filesystem / etc. — silently degrade to
        # the in-memory cache for this render.
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _fetch_tile(tx: int, ty: int, z: int, *,
                provider: str = 'osm', api_key: Optional[str] = None,
                ) -> Optional[Image.Image]:
    """Fetch (or return the cached copy of) one 256px raster tile.

    Args:
        provider: 'osm' (default) or 'carto_dark'. Unrecognized values,
            or 'carto_dark' with no api_key, fall back to 'osm' -- a
            misconfigured provider must never break map rendering.
        api_key: CARTO API key, required for 'carto_dark'. Ignored for
            'osm'.
    """
    if provider != 'carto_dark' or not api_key:
        provider = 'osm'
    key = (provider, z, tx, ty)

    # L1: in-process LRU.
    cached = _tile_cache_get(key)
    if cached is not None:
        try:
            return Image.open(io.BytesIO(cached)).convert('RGB')
        except Exception:
            # Cached entry corrupt — evict and continue to disk.
            with _TILE_CACHE_LOCK:
                _TILE_CACHE.pop(key, None)

    # L2: disk cache.  Survives worker restarts and shared by every
    # process pointed at the same cache directory.
    disk = _tile_disk_get(key)
    if disk is not None:
        try:
            img = Image.open(io.BytesIO(disk)).convert('RGB')
            _tile_cache_put(key, disk)
            return img
        except Exception:
            # Corrupt on-disk tile — drop it and fall through to HTTP.
            try:
                path = _tile_disk_path(key)
                if path:
                    os.unlink(path)
            except OSError:
                pass

    # L3: live fetch.
    if provider == 'carto_dark':
        url = f'https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{tx}/{ty}.png?key={api_key}'
    else:
        url = f'https://tile.openstreetmap.org/{z}/{tx}/{ty}.png'
    try:
        r = _http.get(
            url, timeout=4,
            headers={'User-Agent': 'EASStation/1.0 (+https://github.com/KR8MER/eas-station)'},
        )
        if r.status_code == 200:
            _tile_cache_put(key, r.content)
            _tile_disk_put(key, r.content)
            return Image.open(io.BytesIO(r.content)).convert('RGB')
    except Exception:
        pass
    return None
