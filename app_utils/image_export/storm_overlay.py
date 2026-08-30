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

"""The storm-motion overlay: cone of uncertainty, arrow and callout.

Split out of ``maps.py`` — it is the single largest piece of drawing code
in the map inset and shares nothing with the rest of it beyond the
tile-coordinate helpers.  ``maps`` re-exports it, so existing imports are
unaffected.
"""

import math
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from .layout import TILE_SIZE
from .fonts import _th, _title_font_for, _tw
from .tiles import _lat_to_ty, _lon_to_tx


def _draw_storm_track(canvas: Image.Image, storm: Dict,
                      z: int, tx_min: int, ty_min: int,
                      accent: Optional[Tuple[int, int, int]] = None,
                      fonts: Optional[Dict] = None,
                      overlay_scale: float = 1.0) -> None:
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

    *overlay_scale* multiplies every pixel dimension here.  The caller
    draws on the full tile canvas and resamples it down to the map slot
    afterwards, so without this the cone and arrow arrive on the finished
    card proportionally smaller than they were tuned to be.
    """
    def _s(v: float) -> int:
        """Scale a canvas-pixel constant, never below one pixel."""
        return max(1, int(round(v * overlay_scale)))

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
            r = _s(3)
            px, py = pts[i]
            ld.ellipse((px - r - 1, py - r - 1, px + r + 1, py + r + 1),
                       fill=(0, 0, 0, alpha))
            ld.ellipse((px - r, py - r, px + r, py + r),
                       fill=(*arrow_fill, alpha))
            # Connecting hair-line shadow
            if i > 0:
                pp = pts[i - 1]
                ld.line([pp, (px, py)], fill=(0, 0, 0, 90), width=_s(2))
                ld.line([pp, (px, py)], fill=(*arrow_fill, alpha), width=_s(1))

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
        cone_len = _s(max(60, min(180, 60 + mph * 2.4)))
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
        dash_len = _s(8)
        gap_len = _s(6)
        seg = dash_len + gap_len
        total = int(math.hypot(tip_x - last_x, tip_y - last_y))
        for i in range(0, total, seg):
            sx0 = last_x + int(dx * i)
            sy0 = last_y + int(dy * i)
            sx1 = last_x + int(dx * min(total, i + dash_len))
            sy1 = last_y + int(dy * min(total, i + dash_len))
            ld.line([(sx0, sy0), (sx1, sy1)],
                    fill=(*arrow_fill, 200), width=_s(2))

        # ── Tapered arrow from "now" position toward forecast tip ─────────
        # Draw three stacked polylines: shadow, glow, core.
        arrow_len = min(_s(60), max(_s(36), cone_len // 2))
        atip_x = last_x + int(dx * arrow_len)
        atip_y = last_y + int(dy * arrow_len)

        # Tail vector (perpendicular)
        nx, ny = -dy, dx       # 90° rotation
        tail_w = _s(7)
        head_w = _s(14)
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
        sh = [(p[0] + _s(2), p[1] + _s(2)) for p in arrow_poly]
        ld.polygon(sh, fill=(0, 0, 0, 180))
        ld.polygon(arrow_poly, fill=(*arrow_fill, 240),
                   outline=(255, 255, 255, 200))

        cone_drawn = True

    # ── "Now" marker — ping rings + bright disc at the newest waypoint ────
    # The outward-fading rings read as a live radar ping / location pulse
    # (the same convention as a "you are here" map dot) even in a still
    # image -- a static disc alone gave no sense that this point is a
    # detection, not just a pin.
    for ring_r, ring_a in ((14, 45), (10, 75)):
        rr = _s(ring_r)
        ld.ellipse((last_x - rr, last_y - rr, last_x + rr, last_y + rr),
                   outline=arrow_fill + (ring_a,), width=_s(2))
    r = _s(6)
    ld.ellipse((last_x - r - _s(2), last_y - r - _s(2),
                last_x + r + _s(2), last_y + r + _s(2)), fill=(0, 0, 0, 220))
    ld.ellipse((last_x - r, last_y - r,
                last_x + r, last_y + r), fill=(255, 255, 255, 240))
    ld.ellipse((last_x - _s(3), last_y - _s(3),
                last_x + _s(3), last_y + _s(3)), fill=arrow_fill + (255,))

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
            # The callout is text, so it cannot just be scaled up as a
            # shape — draw it from a proportionally larger face so it lands
            # at its intended size once the canvas is resampled down.
            if abs(overlay_scale - 1.0) > 0.02:
                f = _title_font_for(max(9, int(round(11 * overlay_scale))))
            else:
                f = fonts.get('label', fonts.get('small'))
            cd = ImageDraw.Draw(canvas)
            pad_x, pad_y = _s(7), _s(4)
            tw_ = _tw(f, label)
            th_ = _th(f, label)
            box_w = tw_ + pad_x * 2
            box_h = th_ + pad_y * 2 + _s(2)

            # Offset far enough along the heading that the pill's near edge
            # clears the arrow tip — anchoring its *centre* just past the tip
            # left the box lying back over the arrow it labels.
            lead = arrow_len + _s(12) + max(box_w, box_h) // 2
            anchor_x = (last_x + int(dx * lead)
                        if toward_deg is not None else last_x + _s(14))
            anchor_y = (last_y + int(dy * lead)
                        if toward_deg is not None else last_y - box_h - _s(8))

            bx = anchor_x - box_w // 2
            by = anchor_y - box_h // 2
            # Clamp to canvas
            bx = max(_s(4), min(cw - box_w - _s(4), bx))
            by = max(_s(4), min(ch - box_h - _s(4), by))

            # Card background — pill-shaped, dark with accent border
            cd.rounded_rectangle((bx, by, bx + box_w, by + box_h),
                                 radius=box_h // 2,
                                 fill=(15, 20, 30),
                                 outline=arrow_fill, width=_s(2))
            # Leader line from arrow tip to box edge
            if toward_deg is not None:
                cd.line([(last_x + int(dx * arrow_len),
                          last_y + int(dy * arrow_len)),
                         (bx + box_w // 2, by + box_h // 2)],
                        fill=arrow_fill, width=_s(1))
            cd.text((bx + pad_x, by + pad_y - f.getbbox(label)[1]),
                    label, font=f, fill=(255, 255, 255))
