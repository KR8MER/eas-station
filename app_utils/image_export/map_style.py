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

"""Making the basemap read as background instead of subject.

A raw OpenStreetMap tile is the loudest thing on the share card: pastel
landcover, orange and red motorways, and dozens of town labels, all at
full saturation.  Dropped into a dark card it reads as a bright rectangle
pasted in from somewhere else, and the alert polygon — the entire point of
the map — has to compete with the road network for attention.

Broadcast and NWS warning graphics solve this the same way every time:
knock the basemap back to a desaturated, darkened ground, then let the
hazard be the only saturated thing in frame.  These helpers do that
(:func:`tone_basemap`, :func:`apply_vignette`) and place the small number
of labels worth keeping without letting them collide
(:func:`place_labels`).
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageEnhance

from .fonts import _th, _tw


# Cool slate the basemap is tinted toward — sits in the same family as the
# card background (``palette._BG``) so the map reads as part of the card
# rather than an embedded screenshot.
_BASEMAP_TINT = (30, 38, 58)


def tone_basemap(img: Image.Image, *,
                 saturation: float = 0.38,
                 brightness: float = 0.58,
                 contrast: float = 1.18,
                 tint: Tuple[int, int, int] = _BASEMAP_TINT,
                 tint_strength: float = 0.30) -> Image.Image:
    """Knock the tile mosaic back so the hazard overlay is what reads.

    Saturation comes down first (motorway orange and landcover green are
    the worst offenders), then a small contrast lift to hold the road and
    water separation, then brightness, then a blend toward the card's slate
    so the map sits in the card's colour world.

    The order is load-bearing. ``ImageEnhance.Contrast`` blends each pixel
    away from the image's *mean* grey, and an OSM tile is overwhelmingly
    pale landcover — so running contrast after the darkening step pushes
    that bright majority straight back toward white and quietly undoes it.
    Contrast therefore has to come first, leaving brightness as the last
    luminance operation. Tinting is last so the tint is not itself
    desaturated away.
    """
    out = img.convert('RGB')
    out = ImageEnhance.Color(out).enhance(saturation)
    out = ImageEnhance.Contrast(out).enhance(contrast)
    out = ImageEnhance.Brightness(out).enhance(brightness)
    if tint_strength > 0:
        out = Image.blend(out, Image.new('RGB', out.size, tint), tint_strength)
    return out


# tone_basemap()'s defaults above are tuned for OSM's light, high-saturation
# tiles -- correct for the zero-config default provider, wrong for a source
# that's already dark and desaturated (CARTO's Dark Matter style). Running
# the same heavy darken/desaturate on an already-dark tile would over-darken
# it and (via the mean-grey-seeking Contrast step) fight its own palette.
#
# An earlier version of this preset left brightness/contrast at identity,
# reasoning that a dark-native source needs no darkening. That missed a
# second problem: CARTO's own roads/labels sit only ~50-65 (out of 255)
# above its near-black background -- a real but very low-contrast signal.
# The card's Lanczos resize (stitched tiles -> exact map_rect pixels) and
# the radar layer's alpha composite on top both survive fine on OSM's much
# higher-contrast tiles, but wash CARTO's thin, low-contrast linework down
# to imperceptible. The fix is not "add contrast" in tone_basemap()'s own
# mean-grey-seeking sense (which fights a dark palette the same way it
# would fight this) -- it's a brightness lift big enough to pull that
# ~50-65 signal into a range that survives downstream resampling, plus a
# mild contrast lift to keep blacks from flattening back out along with it.
TONE_PRESET_DARK_NATIVE: Dict[str, float] = dict(
    saturation=1.0, brightness=3.0, contrast=1.4, tint_strength=0.30,
)


def _vignette_mask(w: int, h: int, *, inner: float = 0.52,
                   max_alpha: int = 125) -> Image.Image:
    """Build a radial falloff mask, transparent at the centre.

    Computed at low resolution and scaled up — the gradient is smooth by
    construction, so the interpolation costs nothing visually and saves
    iterating over every pixel of a 1080-wide map.
    """
    sw = sh = 48
    mask = Image.new('L', (sw, sh), 0)
    px = mask.load()
    for y in range(sh):
        ny = (y + 0.5) / sh * 2.0 - 1.0
        for x in range(sw):
            nx = (x + 0.5) / sw * 2.0 - 1.0
            # Normalised radius: 1.0 at the corners.
            d = math.hypot(nx, ny) / math.sqrt(2.0)
            t = (d - inner) / max(1.0 - inner, 1e-6)
            t = max(0.0, min(1.0, t))
            px[x, y] = int(max_alpha * t * t)   # quadratic → gentle onset
    return mask.resize((w, h), Image.BILINEAR)


def apply_vignette(img: Image.Image, *, inner: float = 0.52,
                   max_alpha: int = 125) -> Image.Image:
    """Darken the map's edges so it fades into the card instead of ending.

    Without this the map inset terminates in four hard bright edges against
    the dark panel — the single strongest "screenshot pasted in" cue on the
    whole card.  It also pulls the eye toward the centre, which is where
    the alert polygon is framed.
    """
    w, h = img.size
    out = img.convert('RGBA')
    shade = Image.new('RGBA', (w, h), (0, 0, 0, 255))
    shade.putalpha(_vignette_mask(w, h, inner=inner, max_alpha=max_alpha))
    out.alpha_composite(shade)
    return out.convert('RGB')


# ─── Label placement ─────────────────────────────────────────────────────────

def place_labels(img: Image.Image, fonts: Dict,
                 labels: Sequence[Tuple[str, Tuple[int, int]]], *,
                 max_labels: int = 6,
                 margin: int = 6,
                 avoid: Optional[Sequence[Tuple[int, int, int, int]]] = None,
                 ) -> int:
    """Draw place labels at the given points, skipping any that collide.

    County name labels were dropped from the share card once before because
    drawing one per boundary produced overlapping, unreadable text whenever
    several counties sat close together.  The answer is not "no labels" —
    a map with no place names cannot answer "where is this?" — it is to
    place them greedily in priority order and drop the ones that do not
    fit:

    * *labels* is consumed in order, so callers put the ones that matter
      most (counties actually inside the alert) first;
    * a label whose box overlaps an already-placed label, an entry in
      *avoid* (the scale bar and attribution strip), or the image edge is
      skipped rather than shifted, because nudging a label off its own
      county is worse than omitting it;
    * at most *max_labels* are drawn, so a 40-county flood watch does not
      turn into a wall of text.

    Each label is a dark pill with white text, which reads on both bright
    landcover and dark water without needing to know what is underneath.

    Returns the number of labels actually drawn.
    """
    if not labels:
        return 0

    font = fonts.get('tiny', fonts.get('small'))
    draw = ImageDraw.Draw(img)
    w, h = img.size
    pad_x, pad_y = 5, 3

    boxes: List[Tuple[int, int, int, int]] = list(avoid or [])
    drawn = 0

    for text, (px, py) in labels:
        if drawn >= max_labels:
            break
        text = (text or '').strip()
        if not text:
            continue

        tw_, th_ = _tw(font, text), _th(font, text)
        bw, bh = tw_ + pad_x * 2, th_ + pad_y * 2
        x0 = int(px - bw / 2)
        y0 = int(py - bh / 2)
        x1, y1 = x0 + bw, y0 + bh

        # Fully inside the frame, or skipped — a half-clipped place name is
        # worse than none.
        if x0 < margin or y0 < margin or x1 > w - margin or y1 > h - margin:
            continue

        if any(x0 < bx1 and x1 > bx0 and y0 < by1 and y1 > by0
               for bx0, by0, bx1, by1 in boxes):
            continue

        draw.rounded_rectangle((x0, y0, x1, y1), radius=bh // 2,
                               fill=(12, 16, 26), outline=(140, 155, 185))
        draw.text((x0 + pad_x, y0 + pad_y - font.getbbox(text)[1]),
                  text, font=font, fill=(238, 243, 252))
        boxes.append((x0, y0, x1, y1))
        drawn += 1

    return drawn
