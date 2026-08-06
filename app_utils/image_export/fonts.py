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

"""Font loading, caching and text measurement."""

from typing import Dict, List, Optional

from PIL import ImageFont


# ─── Font loading ────────────────────────────────────────────────────────────
# Cached at module level so repeated calls (e.g. _render_map → labels → main
# generator) share one font set instead of paying truetype open cost each time.
_FONT_CACHE: Optional[Dict[str, ImageFont.FreeTypeFont]] = None


_FONT_REG_PATHS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
]
_FONT_BOLD_PATHS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
]


def _load_font(paths: List[str], size: int) -> ImageFont.FreeTypeFont:
    """Load the first TrueType path that exists at *size* — or Pillow's
    built-in default if none are available.  Result is not cached here;
    callers should memoise as appropriate."""
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default(size=size)


def _load_fonts() -> Dict[str, ImageFont.FreeTypeFont]:
    """Return a dict of sized fonts; falls back to Pillow built-in.

    Result is memoized in ``_FONT_CACHE`` so subsequent calls skip the
    truetype file lookups — this is the "pre-render assets" hook: the
    expensive font setup runs once at first share and is reused for
    every subsequent render in the process.
    """
    global _FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE

    _FONT_CACHE = {
        'title':  _load_font(_FONT_BOLD_PATHS, 30),
        'head':   _load_font(_FONT_BOLD_PATHS, 18),
        'bold':   _load_font(_FONT_BOLD_PATHS, 15),
        'normal': _load_font(_FONT_REG_PATHS,  14),
        # Body copy — 13 px is the floor for comfortable reading once
        # social platforms re-encode + downscale the card in the feed.
        'small':  _load_font(_FONT_REG_PATHS,  13),
        'tiny':   _load_font(_FONT_REG_PATHS,  11),
        'label':  _load_font(_FONT_BOLD_PATHS, 11),
        'threat': _load_font(_FONT_BOLD_PATHS, 15),
        'mono':   _load_font(_FONT_REG_PATHS,  11),
    }
    return _FONT_CACHE


# Per-size title-font cache so each layout's bumped headline only pays
# the truetype-load cost once across the process lifetime.
_TITLE_FONT_CACHE: Dict[int, ImageFont.FreeTypeFont] = {}


def _title_font_for(size: int) -> ImageFont.FreeTypeFont:
    """Return the bold title font at *size*, memoised by size."""
    if size not in _TITLE_FONT_CACHE:
        _TITLE_FONT_CACHE[size] = _load_font(_FONT_BOLD_PATHS, size)
    return _TITLE_FONT_CACHE[size]

# ─── Text measurement helpers ────────────────────────────────────────────────
def _tw(font: ImageFont.FreeTypeFont, text: str) -> int:
    bb = font.getbbox(text)
    return bb[2] - bb[0]


def _th(font: ImageFont.FreeTypeFont, text: str) -> int:
    bb = font.getbbox(text)
    return bb[3] - bb[1]


def _truncate(font: ImageFont.FreeTypeFont, text: str, max_w: int) -> str:
    """Truncate *text* with an ellipsis to fit within *max_w* pixels."""
    if _tw(font, text) <= max_w:
        return text
    ellipsis = '…'
    while len(text) > 0 and _tw(font, text + ellipsis) > max_w:
        text = text[:-1]
    return text + ellipsis
