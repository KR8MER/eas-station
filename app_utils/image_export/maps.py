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

"""Map inset rendering: framing, county context and the scale bar.

The storm-motion overlay lives in :mod:`storm_overlay` and the PostGIS
lookups in :mod:`map_data`; both are re-exported here so existing
``from .maps import ...`` imports keep resolving.
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

from .layout import (
    MAP_H, MAP_W, TILE_SIZE,
)
from .palette import (
    _SEVERITY, _TEXT_MUT,
)
from .theme import (
    _Theme,
)
from .fonts import (
    _load_fonts, _th, _title_font_for, _tw,
)
from .tiles import (
    _detail_zoom, _fetch_tile, _geojson_bbox, _lat_to_ty, _lon_to_tx,
)
from .map_style import (
    apply_vignette, place_labels, tone_basemap,
)
from .map_data import (  # noqa: F401  (re-exported for compatibility)
    _alert_same_codes, _fetch_county_outlines, _fetch_same_union_geom,
)
from .storm_overlay import _draw_storm_track  # noqa: F401

logger = logging.getLogger(__name__)

# Nice round distances (miles) for the map scale bar, smallest → largest.
_SCALE_BAR_MILES = [
    0.1, 0.2, 0.25, 0.5, 1, 2, 3, 5, 10, 15, 20, 25, 50, 75,
    100, 150, 200, 300, 500, 1000,
]


def _nice_scale_miles(max_miles: float) -> float:
    """Return the largest 'nice' distance ≤ *max_miles* for the scale bar."""
    pick = _SCALE_BAR_MILES[0]
    for d in _SCALE_BAR_MILES:
        if d <= max_miles:
            pick = d
        else:
            break
    return pick


def _draw_scale_bar(img: Image.Image, fonts: Dict, *,
                    center_lat: float, z: int, resize_ratio: float = 1.0) -> None:
    """Draw a distance scale bar in the lower-left of the (cropped) map.

    Gives the reader an instant sense of how large the affected area is —
    a 5-mile hail core and a 200-mile flood watch look very different once
    there's a ruler on the map.  Distances are shown in miles for the US
    warning audience.

    *resize_ratio* accounts for the rare case where the native tile crop was
    resized to fit the map slot: each final pixel then covers proportionally
    more ground, so the metres-per-pixel figure is scaled to match.
    """
    map_w, map_h = img.size
    # Web-Mercator ground resolution at this latitude / zoom (256-px tiles).
    m_per_px = (156543.03392804097 * math.cos(math.radians(center_lat))
                / (2 ** z)) * max(resize_ratio, 1e-6)
    if m_per_px <= 0:
        return

    # Aim for a bar no wider than ~28% of the map; snap to a nice distance.
    max_px = map_w * 0.28
    max_miles = (max_px * m_per_px) / 1609.344
    if max_miles <= 0:
        return
    miles = _nice_scale_miles(max_miles)
    bar_px = int(round((miles * 1609.344) / m_per_px))
    if bar_px < 12:
        return

    label = (f'{miles:g} mi' if miles >= 1 else f'{miles:g} mi')

    fnt = fonts.get('tiny', fonts.get('small'))
    lbl_w = _tw(fnt, label)
    lbl_h = _th(fnt, label)

    pad = 5
    x0 = 10
    y0 = map_h - 12               # baseline of the bar
    box_w = max(bar_px, lbl_w) + pad * 2
    box_h = lbl_h + 12 + pad

    # Dark translucent backing so the bar reads on both light and dark tiles.
    backing = Image.new('RGBA', (box_w, box_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(backing)
    bd.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=5,
                         fill=(10, 14, 22, 165))
    base = img.convert('RGBA')
    base.alpha_composite(backing, dest=(x0 - pad, y0 - box_h + pad + 2))
    img.paste(base.convert('RGB'))

    d = ImageDraw.Draw(img)
    bar_y = y0
    # Main bar with end ticks.
    d.line([(x0, bar_y), (x0 + bar_px, bar_y)], fill=(255, 255, 255), width=2)
    for tx in (x0, x0 + bar_px):
        d.line([(tx, bar_y - 4), (tx, bar_y)], fill=(255, 255, 255), width=2)
    # Label centred over the bar.
    d.text((x0 + (bar_px - lbl_w) // 2, bar_y - 6 - lbl_h),
           label, font=fnt, fill=(235, 240, 248))


def _crop_window(min_lon: float, min_lat: float, max_lon: float, max_lat: float,
                 z: int, tx_min: int, ty_min: int,
                 canvas_w: int, canvas_h: int,
                 map_w: int, map_h: int) -> Tuple[Tuple[int, int, int, int], float]:
    """Return the canvas crop rectangle framing the bbox, and its scale.

    The renderer used to crop a fixed ``map_w × map_h`` window at whatever
    integer zoom happened to fit, which left the hazard occupying a small
    patch surrounded by unrelated geography.  Instead the crop is exactly
    the (already padded) bbox, widened or heightened to the slot's aspect
    ratio so nothing is squashed, and resampled to the slot — so the subject
    fills the frame at any zoom.

    The second return value is the resample factor (finished pixels per
    canvas pixel).  Overlays are drawn on the canvas before the resample,
    so they must be sized with it.
    """
    bx0 = (_lon_to_tx(min_lon, z) - tx_min) * TILE_SIZE
    bx1 = (_lon_to_tx(max_lon, z) - tx_min) * TILE_SIZE
    by0 = (_lat_to_ty(max_lat, z) - ty_min) * TILE_SIZE
    by1 = (_lat_to_ty(min_lat, z) - ty_min) * TILE_SIZE

    box_w = max(1.0, bx1 - bx0)
    box_h = max(1.0, by1 - by0)
    target_ar = map_w / float(map_h)
    if box_w / box_h < target_ar:
        box_w = box_h * target_ar          # too tall for the slot — widen
    else:
        box_h = box_w / target_ar          # too wide for the slot — heighten

    cx = (bx0 + bx1) / 2.0
    cy = (by0 + by1) / 2.0
    x1 = int(round(cx - box_w / 2.0))
    y1 = int(round(cy - box_h / 2.0))
    x2 = int(round(cx + box_w / 2.0))
    y2 = int(round(cy + box_h / 2.0))

    # Keep the window inside the fetched mosaic, shifting rather than
    # shrinking so the aspect ratio survives.
    if x2 - x1 > canvas_w:
        x1, x2 = 0, canvas_w
    elif x1 < 0:
        x1, x2 = 0, x2 - x1
    elif x2 > canvas_w:
        x1, x2 = x1 - (x2 - canvas_w), canvas_w
    if y2 - y1 > canvas_h:
        y1, y2 = 0, canvas_h
    elif y1 < 0:
        y1, y2 = 0, y2 - y1
    elif y2 > canvas_h:
        y1, y2 = y1 - (y2 - canvas_h), canvas_h

    render_scale = map_w / float(max(1, x2 - x1))
    return (x1, y1, x2, y2), render_scale


def _render_map(geom: Dict, severity: str,
                storm_motion: Optional[Dict] = None,
                theme: Optional[_Theme] = None,
                *, map_w: int = MAP_W, map_h: int = MAP_H,
                db_session: Any = None) -> Image.Image:
    """Return a *map_w*×*map_h* RGB map image with the alert polygon overlaid.

    *theme* drives the polygon stroke / storm-motion accent colours; if
    omitted we fall back to the severity palette (legacy behaviour).
    *db_session* is forwarded to the county-outline lookup so callers
    without a Flask application context still get county borders.

    On top of the OSM tiles the map renders muted county reference
    outlines, the alert polygon (plus optional storm-motion overlay), and
    a distance scale bar.  County *name labels* are intentionally omitted —
    they collided and cluttered the image when multiple boundaries
    overlapped — so only the borders themselves are drawn for context.
    """
    fallback = Image.new('RGB', (map_w, map_h), (35, 42, 62))
    fd = ImageDraw.Draw(fallback)
    msg = 'Map not available'
    fonts = _load_fonts()
    fd.text(((map_w - _tw(fonts['small'], msg)) // 2, map_h // 2 - 8),
            msg, font=fonts['small'], fill=_TEXT_MUT)

    bbox = _geojson_bbox(geom)
    if bbox is None:
        logger.warning(
            "Coverage map: geometry has no usable bounding box (type=%s); "
            "rendering 'Map not available' placeholder",
            geom.get('type'),
        )
        return fallback

    min_lon, min_lat, max_lon, max_lat = bbox
    # Breathing room around the hazard so it doesn't touch the frame edge.
    # The crop below frames exactly this box, so the padding is the whole
    # margin — it no longer compounds with a zoom-fitting fudge factor.
    lon_pad = max(max_lon - min_lon, 0.005) * 0.16
    lat_pad = max(max_lat - min_lat, 0.005) * 0.16
    min_lon -= lon_pad; max_lon += lon_pad
    min_lat -= lat_pad; max_lat += lat_pad

    z = _detail_zoom(min_lon, min_lat, max_lon, max_lat, map_w, map_h)

    tx_min = max(0,        int(math.floor(_lon_to_tx(min_lon, z))) - 1)
    tx_max = min(2**z - 1, int(math.ceil( _lon_to_tx(max_lon, z))) + 1)
    ty_min = max(0,        int(math.floor(_lat_to_ty(max_lat, z))) - 1)
    ty_max = min(2**z - 1, int(math.ceil( _lat_to_ty(min_lat, z))) + 1)

    n_tiles = (tx_max - tx_min + 1) * (ty_max - ty_min + 1)
    if n_tiles > 30:
        logger.warning(
            "Coverage map: bbox needs %d tiles at z%d (limit 30); "
            "rendering 'Map not available' placeholder",
            n_tiles, z,
        )
        return fallback

    canvas_w = (tx_max - tx_min + 1) * TILE_SIZE
    canvas_h = (ty_max - ty_min + 1) * TILE_SIZE
    canvas = Image.new('RGB', (canvas_w, canvas_h), (200, 200, 200))

    for ty in range(ty_min, ty_max + 1):
        for tx in range(tx_min, tx_max + 1):
            tile = _fetch_tile(tx, ty, z)
            if tile:
                canvas.paste(tile, ((tx - tx_min) * TILE_SIZE, (ty - ty_min) * TILE_SIZE))

    # ── Tone the basemap ──────────────────────────────────────────────────
    # Done before any overlay is drawn so only the tiles are knocked back:
    # the polygon, storm cone and labels keep their full intensity and are
    # the only saturated things on the map.
    canvas = tone_basemap(canvas)

    # ── Crop window, computed up front ────────────────────────────────────
    # Overlays are drawn in canvas pixels but the canvas is resampled to the
    # map slot at the end, so every stroke width has to be pre-divided by
    # that resample factor or it lands thinner than intended.  Working the
    # crop out here (rather than after drawing) is what makes that possible.
    crop_box, render_scale = _crop_window(
        min_lon, min_lat, max_lon, max_lat,
        z, tx_min, ty_min, canvas_w, canvas_h, map_w, map_h,
    )

    # Polygon colour: theme accent (event-aware) with severity as fallback.
    if theme is not None:
        alr_clr = tuple(theme.get('accent', _SEVERITY['unknown']))  # type: ignore[assignment]
    else:
        alr_clr = _SEVERITY.get(severity.lower(), _SEVERITY['unknown'])

    def _to_px(ring: List) -> List[Tuple[int, int]]:
        pts = []
        for pt in ring:
            px = int((_lon_to_tx(float(pt[0]), z) - tx_min) * TILE_SIZE)
            py = int((_lat_to_ty(float(pt[1]), z) - ty_min) * TILE_SIZE)
            pts.append((px, py))
        return pts

    gtype = geom.get('type', '')
    raw_coords = geom.get('coordinates', [])
    rings: List[List] = []
    if gtype == 'Polygon':
        rings = raw_coords
    elif gtype == 'MultiPolygon':
        rings = [r for poly in raw_coords for r in poly]

    # Stroke widths scale with the map's smallest dimension so the
    # affected polygon reads cleanly on larger canvases (Story, Portrait)
    # where the fixed thin stroke would otherwise look like a thread.
    # Reference is 490 px (landscape map height), the size the original
    # 5/3/9 px stroke values were tuned against.  Dividing by *render_scale*
    # converts "pixels in the finished map" into "pixels on the canvas we
    # are drawing on", so the stroke survives the resample at its intended
    # weight.
    stroke_scale = max(1.0, min(map_w, map_h) / 490.0) / max(render_scale, 1e-6)
    glow_w   = max(9,  int(round(9 * stroke_scale)))
    glow_r   = max(6,  int(round(6 * stroke_scale)))
    casing_w = max(5,  int(round(5 * stroke_scale)))
    core_w   = max(3,  int(round(3 * stroke_scale)))

    # ── County reference outlines ─────────────────────────────────────────
    # Muted county borders drawn *under* the alert polygon give the affected
    # area geographic context (which county / counties it covers) the way
    # official NWS warning graphics do.  Only outlines are drawn — no name
    # labels, which historically collided and cluttered the share image when
    # several boundaries overlapped.  Fetched from the local PostGIS table;
    # if it's unavailable the map simply falls back to a polygon-only view.
    counties = _fetch_county_outlines(min_lon, min_lat, max_lon, max_lat,
                                      db_session=db_session, alert_geom=geom)
    # Anchor points (canvas pixels) for the name labels drawn after the crop.
    county_labels: List[Tuple[str, bool, Tuple[int, int]]] = []
    if counties:
        county_w = max(1, int(round(1.4 * stroke_scale)))
        county_layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        cl = ImageDraw.Draw(county_layer)
        for county in counties:
            cgeom = county.get('geom') or {}
            ctype = cgeom.get('type', '')
            ccoords = cgeom.get('coordinates', [])
            affected = bool(county.get('affected'))
            crings: List[List] = []
            if ctype == 'Polygon':
                crings = ccoords
            elif ctype == 'MultiPolygon':
                crings = [r for poly in ccoords for r in poly]
            # Counties the alert actually covers get a brighter, slightly
            # heavier border; the rest stay quiet reference lines.  That is
            # how NWS warning graphics separate "in the warning" from
            # "here for context".
            if affected:
                line_clr, line_w = (255, 255, 255, 205), county_w + 1
            else:
                line_clr, line_w = (232, 238, 248, 120), county_w
            for ring in crings:
                cpts = _to_px(ring)
                if len(cpts) >= 2:
                    closed = cpts + [cpts[0]]
                    # Dark casing then a light hairline so the border reads
                    # on both bright and dark basemap tiles without shouting.
                    cl.line(closed, fill=(18, 22, 31, 130), width=line_w + 1)
                    cl.line(closed, fill=line_clr, width=line_w)

            point = county.get('point')
            name = (county.get('name') or '').strip()
            if name and point:
                try:
                    lx = int((_lon_to_tx(float(point[0]), z) - tx_min) * TILE_SIZE)
                    ly = int((_lat_to_ty(float(point[1]), z) - ty_min) * TILE_SIZE)
                    county_labels.append((name, affected, (lx, ly)))
                except (TypeError, ValueError):
                    pass
        base_rgba = canvas.convert('RGBA')
        base_rgba.alpha_composite(county_layer)
        canvas = base_rgba.convert('RGB')

    # ── Polygon glow ──────────────────────────────────────────────────────
    # A blurred wider stroke sits behind the crisp outline so the affected
    # area "lifts" off the basemap and is unmistakable at thumbnail size.
    glow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for ring in rings:
        pts = _to_px(ring)
        if len(pts) >= 2:
            gd.line(pts + [pts[0]], fill=(*alr_clr, 230), width=glow_w)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=glow_r))

    # Semi-transparent fill
    overlay = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    ov = ImageDraw.Draw(overlay)
    for ring in rings:
        pts = _to_px(ring)
        if len(pts) >= 3:
            ov.polygon(pts, fill=(*alr_clr, 70))

    base_rgba = canvas.convert('RGBA')
    base_rgba.alpha_composite(glow)
    base_rgba.alpha_composite(overlay)
    canvas = base_rgba.convert('RGB')

    # Solid outline on top (white casing for visibility, then accent core)
    od = ImageDraw.Draw(canvas)
    for ring in rings:
        pts = _to_px(ring)
        if len(pts) >= 2:
            closed = pts + [pts[0]]
            od.line(closed, fill=(255, 255, 255), width=casing_w)
            od.line(closed, fill=alr_clr,         width=core_w)

    # Storm motion overlay (new cone + tapered arrow + callout)
    if storm_motion:
        _draw_storm_track(canvas, storm_motion, z, tx_min, ty_min,
                          accent=alr_clr, fonts=fonts,
                          overlay_scale=1.0 / max(render_scale, 1e-6))
        od = ImageDraw.Draw(canvas)

    # ── Boundary labels ───────────────────────────────────────────────────────
    # County reference *outlines* are drawn above (under the alert polygon).
    # Centroid name labels remain intentionally omitted: when multiple county
    # boundaries overlapped (or sat close to the alert polygon) the labels
    # collided and produced a cluttered, unreadable share image.

    # ── Frame the padded bbox, then resample to the slot ──────────────────
    x1, y1, x2, y2 = crop_box
    cropped = canvas.crop(crop_box)
    native_crop_w = max(1, x2 - x1)
    native_crop_h = max(1, y2 - y1)
    if cropped.size != (map_w, map_h):
        cropped = cropped.resize((map_w, map_h), Image.LANCZOS)

    # Canvas → final-image coordinate transform for anything positioned
    # after the crop (currently the county labels).
    sx = map_w / float(native_crop_w)
    sy = map_h / float(native_crop_h)

    cd = ImageDraw.Draw(cropped)

    # ── Distance scale bar (lower-left) ───────────────────────────────────────
    # Gives the affected area a sense of real-world size — a 5-mile hail core
    # reads very differently from a 200-mile flood watch once there's a ruler
    # on the map.
    try:
        _draw_scale_bar(
            cropped, fonts,
            center_lat=(min_lat + max_lat) / 2.0, z=z,
            resize_ratio=native_crop_w / float(map_w),
        )
    except Exception:
        pass

    # ── Vignette ──────────────────────────────────────────────────────────────
    # Darken the edges so the inset fades into the card instead of ending in
    # four hard bright borders, and so the eye is pulled to the framed hazard.
    # Applied before the labels so those keep their full contrast.
    cropped = apply_vignette(cropped)
    cd = ImageDraw.Draw(cropped)

    # ── County name labels ──────────────────────────────────────────────────
    # A map with no place names cannot answer "where is this?".  Labels were
    # dropped once for colliding with each other; they are back with collision
    # avoidance, a priority order (counties inside the alert first) and
    # keep-out boxes over the scale bar and attribution so none lands on the
    # map's own chrome.
    if county_labels:
        keep_out = [
            (0, map_h - 44, 190, map_h),               # scale bar (lower-left)
            (map_w - 210, map_h - 26, map_w, map_h),   # attribution (lower-right)
        ]
        ordered = sorted(county_labels, key=lambda c: not c[1])
        anchors = [
            (name, (int(round((px - x1) * sx)), int(round((py - y1) * sy))))
            for name, _affected, (px, py) in ordered
        ]
        place_labels(cropped, fonts, anchors, max_labels=7, avoid=keep_out)
        cd = ImageDraw.Draw(cropped)

    # ── OSM attribution (required by tile usage policy) ───────────────────────
    attr     = '\u00a9 OpenStreetMap contributors'
    attr_fnt = fonts['tiny']
    aw, ah   = _tw(attr_fnt, attr), _th(attr_fnt, attr)
    ax, ay   = map_w - aw - 5, map_h - ah - 5
    cd.rectangle((ax - 2, ay - 1, map_w - 3, map_h - 3), fill=(0, 0, 0))
    cd.text((ax, ay), attr, font=attr_fnt, fill=(200, 200, 200))

    return cropped
