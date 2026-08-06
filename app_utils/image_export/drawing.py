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

"""Low-level drawing primitives shared across the renderer.

Pills, RGBA compositing, rounded corners, section headers and card rows -
used by the map, the header, the info panels and the top-level renderer
alike.
"""

from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .palette import (
    WHITE, _CARD, _SECTION_BG,
)
from .fonts import (
    _th, _tw,
)


def _draw_pill(draw: ImageDraw.ImageDraw,
               font: ImageFont.FreeTypeFont,
               text: str,
               fill: Tuple[int, int, int],
               x: int, y: int,
               *,
               text_color: Tuple[int, int, int] = (255, 255, 255),
               pad_x: int = 9, pad_y: int = 3,
               outline: Optional[Tuple[int, int, int]] = None,
               outline_w: int = 0) -> int:
    """Draw a rounded-rectangle pill at (x, y) with *text* inside.

    *outline* draws a casing ring around the pill — used by the header
    badges so a colour-filled pill still pops when it lands on a
    same-coloured part of the event gradient.

    Returns the x-coordinate of the pill's right edge so the caller can
    chain multiple pills horizontally without re-measuring.
    """
    text_w = _tw(font, text)
    text_h = _th(font, text)
    pill_w = text_w + pad_x * 2
    pill_h = text_h + pad_y * 2
    radius = max(2, pill_h // 2)
    draw.rounded_rectangle((x, y, x + pill_w, y + pill_h),
                           radius=radius, fill=fill,
                           outline=outline,
                           width=outline_w if outline is not None else 0)
    # Pillow's ``getbbox`` excludes the top-side bearing of TrueType
    # fonts, so subtract the bbox top to get the baseline-aligned y.
    bbox_top = font.getbbox(text)[1]
    draw.text((x + pad_x, y + pad_y - bbox_top), text, font=font, fill=text_color)
    return x + pill_w

def _composite(target: Image.Image, region: Tuple[int, int, int, int],
               layer: Image.Image) -> None:
    """Composite *layer* (RGBA) at *region*'s top-left over *target* (RGB/RGBA)."""
    x0, y0, _rw, _rh = region
    if target.mode != 'RGBA':
        base = target.convert('RGBA')
        base.alpha_composite(layer, dest=(x0, y0))
        target.paste(base.convert('RGB'))
    else:
        target.alpha_composite(layer, dest=(x0, y0))

# ─── Rounded-corner helpers ─────────────────────────────────────────────────
def _round_image_corners(img: Image.Image, radius: int,
                         bg: Optional[Tuple[int, int, int]] = None
                         ) -> Image.Image:
    """Return *img* with its outer corners rounded to *radius* pixels.

    The mask is built with ``ImageDraw.rounded_rectangle`` and applied to
    the alpha channel.  When *bg* is ``None`` the result is RGBA with
    fully transparent corners (preferred for social feeds that respect
    PNG alpha).  When *bg* is a colour tuple the result is flattened RGB
    against that background — used for nested elements that get pasted
    back into a parent canvas (e.g. the map inset).
    """
    if radius <= 0:
        return img
    w, h = img.size
    mask = Image.new('L', (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    rgba = img.convert('RGBA')
    rgba.putalpha(mask)
    if bg is None:
        return rgba
    out = Image.new('RGB', (w, h), bg)
    out.paste(rgba, (0, 0), mask)
    return out

# ─── Drawing helpers ─────────────────────────────────────────────────────────
def _section_header(draw: ImageDraw.ImageDraw, fonts: Dict,
                    alr_clr: Tuple, ix: int, iy: int, iw: int, title: str,
                    *, bg: Optional[Tuple[int, int, int]] = None,
                    stripe: Optional[Tuple[int, int, int]] = None) -> int:
    """Draw a section header; return y after it.

    Default appearance: a neutral dark slate band with a thin
    event-coloured stripe on the left edge.  That keeps the
    event-theme accent threaded through every section without giving
    HEADLINE / AFFECTED AREAS / DESCRIPTION the same loud event-colour
    fill, which previously made them blur into a single stripe at
    thumbnail size.  Sections that genuinely need a distinct fill
    (the ACTION band) pass ``bg=`` to override.
    """
    h = 20
    stripe_w = 4
    fill = bg if bg is not None else _SECTION_BG
    accent = stripe if stripe is not None else alr_clr
    draw.rectangle((ix, iy, ix + iw, iy + h), fill=fill)
    draw.rectangle((ix, iy, ix + stripe_w, iy + h), fill=accent)
    # Label offset clears the stripe.
    draw.text((ix + stripe_w + 6,
               iy + (h - _th(fonts['label'], title)) // 2),
              title, font=fonts['label'], fill=WHITE)
    return iy + h + 2


def _card_row(draw: ImageDraw.ImageDraw, ix: int, iy: int, iw: int, h: int) -> None:
    """Fill a single card-row background."""
    draw.rectangle((ix, iy, ix + iw, iy + h - 1), fill=_CARD)
