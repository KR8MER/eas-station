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

"""Map inset rendering: storm tracks, county outlines, scale bar."""

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
    _load_fonts, _th, _tw,
)
from .tiles import (
    _best_zoom, _fetch_tile, _geojson_bbox,
    _lat_to_ty, _lon_to_tx,
)

logger = logging.getLogger(__name__)

def _draw_storm_track(canvas: Image.Image, storm: Dict,
                      z: int, tx_min: int, ty_min: int,
                      accent: Optional[Tuple[int, int, int]] = None,
                      fonts: Optional[Dict] = None) -> None:
    """Draw a redesigned storm-motion overlay onto *canvas*.

    Replaces the old thin yellow line with:

    * A translucent forecast **cone of uncertainty** projected from the
      newest waypoint along ``toward_deg`` with a half-angle that
      widens with track speed (slower storms → tighter cone).
    * A tapered, glowing arrow with a wider tail and a sharp tip so the
      direction reads instantly even at thumbnail size.
    * Fading "ghost" waypoints for the historical track so motion
      history is visible without competing with the cone.
    * A small floating callout card ("SE @ 35 mph") anchored near the
      arrow tip, drawn only when speed/heading data is present.

    The cone and arrow are rendered onto an RGBA layer then composited
    so the translucent fill works correctly over the basemap.  All
    drawing is clipped to the canvas before composite to avoid Pillow
    polygon-fill artefacts when the cone extends past the edge.
    """
    track      = storm.get('track', [])
    toward_deg = storm.get('toward_deg')
    speed_mph  = storm.get('speed_mph')

    pts: List[Tuple[int, int]] = []
    for point in track:
        try:
            lat, lon = float(point[0]), float(point[1])
            px = int((_lon_to_tx(lon, z) - tx_min) * TILE_SIZE)
            py = int((_lat_to_ty(lat, z) - ty_min) * TILE_SIZE)
            pts.append((px, py))
        except (TypeError, IndexError, ValueError):
            continue

    if not pts:
        return

    cw, ch = canvas.size
    layer = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    arrow_fill = accent if accent is not None else (255, 220, 50)
    shadow     = (  0,   0,   0)

    # ── Ghost waypoints (oldest = faintest) ───────────────────────────────
    if len(pts) >= 2:
        n = len(pts)
        for i in range(n - 1):
            t = i / max(1, n - 1)
            alpha = int(50 + t * 130)   # 50 (oldest) → 180 (recent)
            r = 3
            px, py = pts[i]
            ld.ellipse((px - r - 1, py - r - 1, px + r + 1, py + r + 1),
                       fill=(0, 0, 0, alpha))
            ld.ellipse((px - r, py - r, px + r, py + r),
                       fill=(*arrow_fill, alpha))
            # Connecting hair-line shadow
            if i > 0:
                pp = pts[i - 1]
                ld.line([pp, (px, py)], fill=(0, 0, 0, 90), width=2)
                ld.line([pp, (px, py)], fill=(*arrow_fill, alpha), width=1)

    last_x, last_y = pts[-1]

    # ── Cone of uncertainty ───────────────────────────────────────────────
    cone_drawn = False
    if toward_deg is not None:
        ang = math.radians(toward_deg)
        dx  =  math.sin(ang)
        dy  = -math.cos(ang)

        # Cone length scales loosely with speed: slow storms get a short
        # cone, fast storms get a long one. Capped so it doesn't dominate.
        try:
            mph = float(speed_mph) if speed_mph not in (None, '') else 25.0
        except (TypeError, ValueError):
            mph = 25.0
        cone_len = int(max(60, min(180, 60 + mph * 2.4)))
        # Half-angle: ~22° for typical motion, narrower if very fast,
        # wider if very slow (low confidence).
        half_deg = 26.0 if mph < 20 else (20.0 if mph < 40 else 16.0)
        half = math.radians(half_deg)

        # Cone fan apex at last point, base along the forecast vector.
        # Use the rotation-of-direction trick: rotate (dx,dy) by ±half.
        def _rot(vx: float, vy: float, theta: float) -> Tuple[float, float]:
            c, s = math.cos(theta), math.sin(theta)
            return (vx * c - vy * s, vx * s + vy * c)

        # Build a smooth fan with intermediate samples for a curved base
        fan: List[Tuple[int, int]] = [(last_x, last_y)]
        steps = 9
        for i in range(steps + 1):
            theta = -half + (2 * half) * (i / steps)
            rx, ry = _rot(dx, dy, theta)
            fan.append((int(last_x + rx * cone_len),
                        int(last_y + ry * cone_len)))

        # Translucent fill + soft outline
        ld.polygon(fan, fill=(*arrow_fill, 55))
        ld.polygon(fan, outline=(*arrow_fill, 180))

        # Dashed centreline along the forecast vector
        tip_x = last_x + int(dx * cone_len)
        tip_y = last_y + int(dy * cone_len)
        dash_len = 8
        gap_len = 6
        seg = dash_len + gap_len
        total = int(math.hypot(tip_x - last_x, tip_y - last_y))
        for i in range(0, total, seg):
            sx0 = last_x + int(dx * i)
            sy0 = last_y + int(dy * i)
            sx1 = last_x + int(dx * min(total, i + dash_len))
            sy1 = last_y + int(dy * min(total, i + dash_len))
            ld.line([(sx0, sy0), (sx1, sy1)],
                    fill=(*arrow_fill, 200), width=2)

        # ── Tapered arrow from "now" position toward forecast tip ─────────
        # Draw three stacked polylines: shadow, glow, core.
        arrow_len = min(60, max(36, cone_len // 2))
        atip_x = last_x + int(dx * arrow_len)
        atip_y = last_y + int(dy * arrow_len)

        # Tail vector (perpendicular)
        nx, ny = -dy, dx       # 90° rotation
        tail_w = 7
        head_w = 14
        # Tail base corners
        tlx = int(last_x + nx * tail_w)
        tly = int(last_y + ny * tail_w)
        trx = int(last_x - nx * tail_w)
        try_ = int(last_y - ny * tail_w)
        # Mid waist (where the head meets the shaft)
        mid_x = last_x + int(dx * arrow_len * 0.55)
        mid_y = last_y + int(dy * arrow_len * 0.55)
        mlx = int(mid_x + nx * tail_w * 0.6)
        mly = int(mid_y + ny * tail_w * 0.6)
        mrx = int(mid_x - nx * tail_w * 0.6)
        mry = int(mid_y - ny * tail_w * 0.6)
        # Head wings
        hlx = int(mid_x + nx * head_w)
        hly = int(mid_y + ny * head_w)
        hrx = int(mid_x - nx * head_w)
        hry = int(mid_y - ny * head_w)

        arrow_poly = [
            (tlx, tly), (mlx, mly), (hlx, hly),
            (atip_x, atip_y),
            (hrx, hry), (mrx, mry), (trx, try_),
        ]
        # Shadow offset
        sh = [(p[0] + 2, p[1] + 2) for p in arrow_poly]
        ld.polygon(sh, fill=(0, 0, 0, 180))
        ld.polygon(arrow_poly, fill=(*arrow_fill, 240),
                   outline=(255, 255, 255, 200))

        cone_drawn = True

    # ── "Now" marker — bright disc at the newest waypoint ─────────────────
    r = 6
    ld.ellipse((last_x - r - 2, last_y - r - 2,
                last_x + r + 2, last_y + r + 2), fill=(0, 0, 0, 220))
    ld.ellipse((last_x - r, last_y - r,
                last_x + r, last_y + r), fill=(255, 255, 255, 240))
    ld.ellipse((last_x - 3, last_y - 3,
                last_x + 3, last_y + 3), fill=arrow_fill + (255,))

    # Composite the storm layer onto the basemap.
    base = canvas.convert('RGBA')
    base.alpha_composite(layer)
    composite = base.convert('RGB')
    canvas.paste(composite)

    # ── Callout card ("SE @ 35 mph") near the arrow tip ───────────────────
    if cone_drawn and fonts is not None:
        compass = storm.get('compass_toward') or ''
        speed_txt = ''
        if speed_mph not in (None, ''):
            try:
                speed_txt = f'{int(round(float(speed_mph)))} mph'
            except (TypeError, ValueError):
                speed_txt = ''
        if compass or speed_txt:
            label = ' @ '.join([s for s in (compass, speed_txt) if s])
            f = fonts.get('label', fonts.get('small'))
            cd = ImageDraw.Draw(canvas)
            pad_x, pad_y = 7, 4
            tw_ = _tw(f, label)
            th_ = _th(f, label)
            box_w = tw_ + pad_x * 2
            box_h = th_ + pad_y * 2 + 2

            # Default: place to the right of the tip; flip if off-canvas.
            anchor_x = last_x + int(dx * (arrow_len + 14)) if toward_deg is not None else last_x + 14
            anchor_y = last_y + int(dy * (arrow_len + 14)) if toward_deg is not None else last_y - box_h - 8

            bx = anchor_x - box_w // 2
            by = anchor_y - box_h // 2
            # Clamp to canvas
            bx = max(4, min(cw - box_w - 4, bx))
            by = max(4, min(ch - box_h - 4, by))

            # Card background — pill-shaped, dark with accent border
            cd.rounded_rectangle((bx, by, bx + box_w, by + box_h),
                                 radius=box_h // 2,
                                 fill=(15, 20, 30),
                                 outline=arrow_fill, width=2)
            # Leader line from arrow tip to box edge
            if toward_deg is not None:
                cd.line([(last_x + int(dx * arrow_len),
                          last_y + int(dy * arrow_len)),
                         (bx + box_w // 2, by + box_h // 2)],
                        fill=(*arrow_fill, 200) if False else arrow_fill,
                        width=1)
            cd.text((bx + pad_x, by + pad_y - 1),
                    label, font=f, fill=(255, 255, 255))


def _fetch_county_outlines(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    db_session: Any = None,
) -> List[Dict[str, Any]]:
    """Return simplified GeoJSON geometries for the US counties that
    intersect the given lon/lat bounding box.

    These are drawn as muted reference lines *under* the alert polygon so
    the affected area carries geographic context (which county / counties
    it falls in) — mirroring the county boundaries on official NWS warning
    graphics.

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

    try:
        rows = db_session.execute(
            _text(
                """
                SELECT name,
                       ST_AsGeoJSON(
                           ST_SimplifyPreserveTopology(geom, :tol), 5
                       ) AS gj
                FROM us_county_boundaries
                WHERE geom && ST_MakeEnvelope(
                          :min_lon, :min_lat, :max_lon, :max_lat, 4326
                      )
                LIMIT 80
                """
            ),
            {
                "tol": tol,
                "min_lon": min_lon, "min_lat": min_lat,
                "max_lon": max_lon, "max_lat": max_lat,
            },
        ).fetchall()
    except Exception:
        # No table, no PostGIS, no DB session — silently skip; the alert
        # polygon alone is still a complete map.
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            out.append({'name': row.name, 'geom': json.loads(row.gj)})
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
    lon_pad = max(max_lon - min_lon, 0.005) * 0.30
    lat_pad = max(max_lat - min_lat, 0.005) * 0.30
    min_lon -= lon_pad; max_lon += lon_pad
    min_lat -= lat_pad; max_lat += lat_pad

    z = _best_zoom(min_lon, min_lat, max_lon, max_lat, map_w, map_h)

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
    # 5/3/9 px stroke values were tuned against.
    stroke_scale = max(1.0, min(map_w, map_h) / 490.0)
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
                                      db_session=db_session)
    if counties:
        county_w = max(1, int(round(1.4 * stroke_scale)))
        county_layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        cl = ImageDraw.Draw(county_layer)
        for county in counties:
            cgeom = county.get('geom') or {}
            ctype = cgeom.get('type', '')
            ccoords = cgeom.get('coordinates', [])
            crings: List[List] = []
            if ctype == 'Polygon':
                crings = ccoords
            elif ctype == 'MultiPolygon':
                crings = [r for poly in ccoords for r in poly]
            for ring in crings:
                cpts = _to_px(ring)
                if len(cpts) >= 2:
                    closed = cpts + [cpts[0]]
                    # Dark casing then a light hairline so the border reads
                    # on both bright and dark basemap tiles without shouting.
                    cl.line(closed, fill=(18, 22, 31, 115), width=county_w + 1)
                    cl.line(closed, fill=(238, 242, 249, 150), width=county_w)
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
                          accent=alr_clr, fonts=fonts)
        od = ImageDraw.Draw(canvas)

    # ── Boundary labels ───────────────────────────────────────────────────────
    # County reference *outlines* are drawn above (under the alert polygon).
    # Centroid name labels remain intentionally omitted: when multiple county
    # boundaries overlapped (or sat close to the alert polygon) the labels
    # collided and produced a cluttered, unreadable share image.

    # Crop to MAP_W × MAP_H centred on the padded bbox
    cx = int((_lon_to_tx((min_lon + max_lon) / 2, z) - tx_min) * TILE_SIZE)
    cy = int((_lat_to_ty((min_lat + max_lat) / 2, z) - ty_min) * TILE_SIZE)

    x1 = max(0, cx - map_w // 2)
    y1 = max(0, cy - map_h // 2)
    x2 = min(canvas_w, x1 + map_w)
    y2 = min(canvas_h, y1 + map_h)

    if x2 - x1 < map_w:
        x1 = max(0, x2 - map_w)
    if y2 - y1 < map_h:
        y1 = max(0, y2 - map_h)

    cropped = canvas.crop((x1, y1, x2, y2))
    native_crop_w = max(1, x2 - x1)
    if cropped.size != (map_w, map_h):
        cropped = cropped.resize((map_w, map_h), Image.LANCZOS)

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

    # ── OSM attribution (required by tile usage policy) ───────────────────────
    attr     = '\u00a9 OpenStreetMap contributors'
    attr_fnt = fonts['tiny']
    aw, ah   = _tw(attr_fnt, attr), _th(attr_fnt, attr)
    ax, ay   = map_w - aw - 5, map_h - ah - 5
    cd.rectangle((ax - 2, ay - 1, map_w - 3, map_h - 3), fill=(0, 0, 0))
    cd.text((ax, ay), attr, font=attr_fnt, fill=(200, 200, 200))

    return cropped
