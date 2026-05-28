"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Social media image export for alert details.

Generates a Facebook-ready 1200×630 PNG for a given CAP alert containing:
- A stormy-sky header with procedural lightning bolts (same visual
  language as the site's lightning theme), the event name, and severity
- Static OpenStreetMap tile background with the alert polygon drawn on top
- Storm threat badges (tornado, wind, hail) when present
- NWS headline, affected areas, description, and safety instructions —
  the priority sections for a share card, sized to fill the available
  space rather than being clipped at an arbitrary line count
- County coverage and storm-motion summary when space remains
- Alert header and footer with timing info

Operator-only fields (VTAC strings, issuing-office block) are
intentionally omitted — they're technical noise for social sharing and
previously crowded out the readable copy.

The map tile layer is fetched live from OpenStreetMap.  If tiles are
unavailable (network timeout, offline environment, …) the map area is
replaced with a plain dark background; all data cards are unaffected.

Usage::

    from app_utils.image_export import generate_alert_image
    png_bytes = generate_alert_image(alert, coverage_data, ipaws_data, location_settings)
"""

import io
import json
import math
import os
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import requests as _http
from PIL import Image, ImageDraw, ImageFilter, ImageFont, PngImagePlugin

# ─── Canonical brand logo ──────────────────────────────────────────────────
# Single source of truth for the EAS Station brand logo raster used inside
# the share image.  Update both the SVG (static/img/eas-system-wordmark.svg)
# and re-rasterize this PNG to refresh every consumer — favicons, on-page
# <img> tags, this share-image renderer.
_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'static', 'img', 'eas-system-wordmark.png',
)
_LOGO_CACHE: Optional[Image.Image] = None


def _load_logo() -> Optional[Image.Image]:
    """Load the canonical EAS Station logo PNG (cached, RGBA)."""
    global _LOGO_CACHE
    if _LOGO_CACHE is not None:
        return _LOGO_CACHE
    try:
        with Image.open(_LOGO_PATH) as im:
            _LOGO_CACHE = im.convert('RGBA').copy()
        return _LOGO_CACHE
    except Exception:
        return None


# ─── Canvas layouts ─────────────────────────────────────────────────────────
# The share card renders into one of several preset canvases that target the
# common social-platform aspect ratios.  Each preset bundles the canvas
# dimensions plus the rectangles for the chrome (header / footer) and the
# two content slots (map + info panel).  The info-panel drawers (threats,
# headline, areas, description, instructions, …) all operate on a generic
# rectangle, so a new layout is just a different set of numbers — no new
# drawing code per aspect ratio.

from dataclasses import dataclass


@dataclass(frozen=True)
class _Layout:
    """Geometry for a single share-card aspect-ratio variant."""
    width: int
    height: int
    header_h: int
    footer_h: int
    # Map slot rectangle: (x, y, w, h).
    map_rect: Tuple[int, int, int, int]
    # Info-panel slot rectangle (where text sections render).
    info_rect: Tuple[int, int, int, int]
    # Width of the dark scrim under the header text (left edge) for
    # legibility against the particle layer.
    header_scrim_w: int
    # Whether to draw the thin vertical divider between map and info
    # (only used in side-by-side layouts).
    show_vertical_divider: bool = False
    # Outer rounded-corner radius.
    corner_r: int = 18
    # Inner map rounded-corner radius (0 for full-bleed map).
    map_corner_r: int = 14


# Facebook / Twitter / LinkedIn open-graph cards — horizontal split with
# the map on the left and the text panel on the right.
_LAYOUT_LANDSCAPE = _Layout(
    width=1200, height=630,
    header_h=90, footer_h=50,
    map_rect=(0, 90, 582, 490),
    info_rect=(590, 98, 594, 482),
    header_scrim_w=560,
    show_vertical_divider=True,
    map_corner_r=14,
)

# Instagram / Mastodon / generic square feed card — stacked layout with
# header → map → info → footer down the centre line.
_LAYOUT_SQUARE = _Layout(
    width=1080, height=1080,
    header_h=110, footer_h=60,
    map_rect=(0, 110, 1080, 540),
    info_rect=(16, 658, 1048, 358),
    header_scrim_w=600,
    map_corner_r=0,
)

# Instagram portrait (4:5) — taller info panel, slightly shorter map.
_LAYOUT_PORTRAIT = _Layout(
    width=1080, height=1350,
    header_h=120, footer_h=60,
    map_rect=(0, 120, 1080, 540),
    info_rect=(16, 668, 1048, 615),
    header_scrim_w=600,
    map_corner_r=0,
)

# Instagram / TikTok / Snapchat Stories & Reels (9:16) — phone-first
# vertical layout with a tall info panel for longer descriptions.
_LAYOUT_STORY = _Layout(
    width=1080, height=1920,
    header_h=140, footer_h=70,
    map_rect=(0, 140, 1080, 800),
    info_rect=(16, 950, 1048, 894),
    header_scrim_w=620,
    map_corner_r=0,
)

_LAYOUTS: Dict[str, _Layout] = {
    'landscape': _LAYOUT_LANDSCAPE,
    'square':    _LAYOUT_SQUARE,
    'portrait':  _LAYOUT_PORTRAIT,
    'story':     _LAYOUT_STORY,
}

# Module-level constants preserved for backward compatibility — anything
# that previously imported these names still gets the original landscape
# numbers.  New code should reach into ``_Layout`` instances instead.
FB_WIDTH    = _LAYOUT_LANDSCAPE.width
FB_HEIGHT   = _LAYOUT_LANDSCAPE.height
HEADER_H    = _LAYOUT_LANDSCAPE.header_h
FOOTER_H    = _LAYOUT_LANDSCAPE.footer_h
BODY_H      = FB_HEIGHT - HEADER_H - FOOTER_H
MAP_W       = _LAYOUT_LANDSCAPE.map_rect[2]
MAP_H       = _LAYOUT_LANDSCAPE.map_rect[3]
INFO_X      = _LAYOUT_LANDSCAPE.info_rect[0]
INFO_W      = _LAYOUT_LANDSCAPE.info_rect[2]
TILE_SIZE   = 256

# ─── Colour palette ─────────────────────────────────────────────────────────
_BG         = (22,  27,  38)
_PANEL      = (30,  36,  51)
_CARD       = (38,  45,  63)
_STRIP      = (14,  18,  30)
_DIVIDER    = (55,  65,  88)
_TEXT       = (230, 235, 245)
_TEXT_SEC   = (155, 165, 190)
_TEXT_MUT   = ( 95, 108, 132)
WHITE       = (255, 255, 255)

# Corner radius used for the outer canvas and inner panels — anything ≥ 10
# rounds enough to read as "designed" instead of "screenshot" on a feed.
CORNER_R    = 22
MAP_CORNER_R    = 14
CARD_CORNER_R   = 6

_SEVERITY: Dict[str, Tuple[int, int, int]] = {
    'extreme':  (220,  53,  69),
    'severe':   (253, 126,  20),
    'moderate': (255, 193,   7),
    'minor':    ( 13, 110, 253),
    'unknown':  (108, 117, 125),
}
_THREAT_CLR: Dict[str, Tuple[int, int, int]] = {
    'observed': (220,  53,  69),
    'radar':    (255, 193,   7),
    'possible': (253, 126,  20),
    'none':     ( 80,  95, 120),
}

# ─── Event theming ───────────────────────────────────────────────────────────
# Each theme drives the header gradient, accent colour (section headers,
# polygon stroke, callouts) and the decorative particle layer painted
# behind the title. Particle styles: 'bolts' | 'snow' | 'rain' | 'sun' |
# 'embers' | 'wind' | 'haze' | 'none'.
#
# Themes are keyed off the CAP event name (lowercased substring match).
# This is intentionally data-driven so adding a new event type is one line.
_Theme = Dict[str, Any]

# Generic fallback themes derived from severity so unfamiliar events still
# get a reasonable look.  Tone-mapped from the original severity palette.
_THEME_DEFAULT: _Theme = {
    'top':       ( 25,  30,  55),
    'bottom':    ( 70,  95, 150),
    'accent':    ( 70, 130, 200),
    'particles': 'bolts',
    'particle_intensity': 0.7,
}

# Event → theme map.  Keys are lowercase substrings tested against the CAP
# event name.  Order matters — first match wins, so list specific events
# before generic ones (e.g. "winter storm" before "storm").
_THEMES: List[Tuple[str, _Theme]] = [
    # ── Convective / severe storms ──────────────────────────────────────
    ('tornado', {
        'top':       ( 70,   0,   0),
        'bottom':    (180,  25,  35),
        'accent':    (220,  53,  69),
        'particles': 'bolts',
        'particle_intensity': 1.1,
    }),
    ('severe thunderstorm', {
        'top':       ( 35,  20,  60),
        'bottom':    (220, 110,  30),
        'accent':    (253, 126,  20),
        'particles': 'bolts',
        'particle_intensity': 1.0,
    }),
    ('thunderstorm', {
        'top':       ( 30,  35,  70),
        'bottom':    ( 95, 110, 180),
        'accent':    (110, 140, 220),
        'particles': 'bolts',
        'particle_intensity': 0.95,
    }),
    # ── Wind / hurricane ────────────────────────────────────────────────
    # NOTE: 'wind chill' must be matched *before* the winter section,
    # otherwise 'cold' or 'wind' would steal it.  All wind-family keys
    # are ordered most-specific → least-specific.
    ('wind chill', {
        'top':       ( 20,  50,  85),
        'bottom':    ( 75, 125, 180),
        'accent':    (155, 200, 235),
        'particles': 'snow',
        'particle_intensity': 0.6,
    }),
    ('hurricane', {
        'top':       ( 60,   0,  60),
        'bottom':    (190,  60, 120),
        'accent':    (220,  90, 150),
        'particles': 'wind',
        'particle_intensity': 1.0,
    }),
    ('tropical', {
        'top':       ( 40,  20,  70),
        'bottom':    (160,  70, 140),
        'accent':    (200,  90, 160),
        'particles': 'wind',
        'particle_intensity': 0.9,
    }),
    ('high wind', {
        'top':       ( 30,  45,  75),
        'bottom':    (110, 135, 175),
        'accent':    (140, 170, 210),
        'particles': 'wind',
        'particle_intensity': 0.95,
    }),
    ('wind', {
        'top':       ( 35,  50,  80),
        'bottom':    (120, 150, 190),
        'accent':    (160, 190, 220),
        'particles': 'wind',
        'particle_intensity': 0.8,
    }),
    # ── Winter / cold ───────────────────────────────────────────────────
    ('blizzard', {
        'top':       ( 20,  35,  70),
        'bottom':    (100, 145, 200),
        'accent':    (170, 215, 245),
        'particles': 'snow',
        'particle_intensity': 1.2,
    }),
    ('winter', {
        'top':       ( 25,  45,  85),
        'bottom':    ( 95, 145, 200),
        'accent':    (170, 215, 245),
        'particles': 'snow',
        'particle_intensity': 1.0,
    }),
    ('ice', {
        'top':       ( 30,  55,  90),
        'bottom':    (110, 165, 210),
        'accent':    (180, 220, 245),
        'particles': 'snow',
        'particle_intensity': 0.9,
    }),
    ('snow', {
        'top':       ( 30,  55,  95),
        'bottom':    (105, 155, 205),
        'accent':    (175, 220, 245),
        'particles': 'snow',
        'particle_intensity': 1.0,
    }),
    ('freeze', {
        'top':       ( 20,  50,  90),
        'bottom':    ( 80, 130, 185),
        'accent':    (160, 210, 240),
        'particles': 'snow',
        'particle_intensity': 0.8,
    }),
    ('frost', {
        'top':       ( 25,  60,  95),
        'bottom':    ( 90, 140, 195),
        'accent':    (170, 215, 245),
        'particles': 'snow',
        'particle_intensity': 0.7,
    }),
    ('cold', {
        'top':       ( 20,  45,  80),
        'bottom':    ( 80, 130, 185),
        'accent':    (160, 210, 240),
        'particles': 'snow',
        'particle_intensity': 0.7,
    }),
    # ── Water ───────────────────────────────────────────────────────────
    ('flash flood', {
        'top':       (  5,  35,  60),
        'bottom':    ( 35, 110, 145),
        'accent':    ( 45, 165, 200),
        'particles': 'rain',
        'particle_intensity': 1.1,
    }),
    ('flood', {
        'top':       ( 10,  45,  70),
        'bottom':    ( 30, 115, 150),
        'accent':    ( 50, 170, 205),
        'particles': 'rain',
        'particle_intensity': 0.95,
    }),
    ('coastal', {
        'top':       ( 10,  50,  80),
        'bottom':    ( 35, 130, 165),
        'accent':    ( 60, 180, 215),
        'particles': 'rain',
        'particle_intensity': 0.7,
    }),
    ('marine', {
        'top':       ( 10,  50,  80),
        'bottom':    ( 35, 130, 165),
        'accent':    ( 60, 180, 215),
        'particles': 'rain',
        'particle_intensity': 0.6,
    }),
    ('rip current', {
        'top':       ( 15,  60,  90),
        'bottom':    ( 40, 145, 185),
        'accent':    ( 65, 195, 225),
        'particles': 'rain',
        'particle_intensity': 0.5,
    }),
    ('rain', {
        'top':       ( 15,  45,  70),
        'bottom':    ( 50, 120, 160),
        'accent':    ( 65, 180, 215),
        'particles': 'rain',
        'particle_intensity': 0.85,
    }),
    # ── Heat ────────────────────────────────────────────────────────────
    ('excessive heat', {
        'top':       (110,   0,   0),
        'bottom':    (245, 145,   0),
        'accent':    (255, 200,  60),
        'particles': 'sun',
        'particle_intensity': 1.1,
    }),
    ('heat', {
        'top':       (130,  20,   0),
        'bottom':    (240, 165,  20),
        'accent':    (255, 210,  80),
        'particles': 'sun',
        'particle_intensity': 1.0,
    }),
    # ── Fire ────────────────────────────────────────────────────────────
    ('red flag', {
        'top':       ( 40,   0,   0),
        'bottom':    (200,  50,  20),
        'accent':    (255, 130,  40),
        'particles': 'embers',
        'particle_intensity': 1.0,
    }),
    ('fire weather', {
        'top':       ( 30,   0,   0),
        'bottom':    (190,  40,  10),
        'accent':    (255, 120,  30),
        'particles': 'embers',
        'particle_intensity': 1.0,
    }),
    ('fire', {
        'top':       ( 30,   0,   0),
        'bottom':    (180,  35,   5),
        'accent':    (255, 115,  25),
        'particles': 'embers',
        'particle_intensity': 1.0,
    }),
    ('smoke', {
        'top':       ( 35,  30,  35),
        'bottom':    (130, 110, 100),
        'accent':    (210, 180, 140),
        'particles': 'embers',
        'particle_intensity': 0.6,
    }),
    # ── Visibility / atmosphere ─────────────────────────────────────────
    ('fog', {
        'top':       ( 55,  60,  70),
        'bottom':    (140, 150, 165),
        'accent':    (180, 200, 220),
        'particles': 'haze',
        'particle_intensity': 1.0,
    }),
    ('dense fog', {
        'top':       ( 50,  55,  65),
        'bottom':    (130, 140, 155),
        'accent':    (175, 195, 215),
        'particles': 'haze',
        'particle_intensity': 1.1,
    }),
    ('dust', {
        'top':       ( 70,  55,  35),
        'bottom':    (190, 155,  95),
        'accent':    (220, 185, 130),
        'particles': 'haze',
        'particle_intensity': 0.9,
    }),
    # ── Civil / non-weather ─────────────────────────────────────────────
    ('amber', {
        'top':       ( 90,  60,   0),
        'bottom':    (235, 175,  30),
        'accent':    (255, 205,  70),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    ('civil', {
        'top':       ( 50,   0,   5),
        'bottom':    (180,  40,  50),
        'accent':    (220,  70,  90),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    ('evacuation', {
        'top':       ( 70,   0,   0),
        'bottom':    (210,  60,  35),
        'accent':    (245, 120,  60),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    ('hazardous materials', {
        'top':       ( 50,  60,   0),
        'bottom':    (175, 195,  50),
        'accent':    (215, 230,  90),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    ('shelter', {
        'top':       ( 60,  40,   0),
        'bottom':    (200, 145,  40),
        'accent':    (240, 180,  70),
        'particles': 'none',
        'particle_intensity': 0.0,
    }),
    # Catch-all storm before plain 'storm'
    ('storm', {
        'top':       ( 30,  35,  70),
        'bottom':    ( 95, 110, 180),
        'accent':    (110, 140, 220),
        'particles': 'bolts',
        'particle_intensity': 0.9,
    }),
]


def _resolve_theme(event_name: str, severity: str) -> _Theme:
    """Return the theme that best fits *event_name*; fall back to severity."""
    name = (event_name or '').lower()
    for key, theme in _THEMES:
        if key in name:
            return theme
    # Fall back: tint the default theme with the severity colour so we
    # still get event-appropriate gradients for unknown events.
    sev_clr = _SEVERITY.get((severity or '').lower(), _SEVERITY['unknown'])
    return {
        'top':       _darken(sev_clr, 0.65),
        'bottom':    sev_clr,
        'accent':    sev_clr,
        'particles': 'bolts',
        'particle_intensity': 0.6,
    }


def _theme_supports_storm_motion(theme: _Theme) -> bool:
    """Storm-motion overlay only makes sense for convective/wind events."""
    return theme.get('particles') in ('bolts', 'wind', 'rain')


# ─── Font loading ────────────────────────────────────────────────────────────
# Cached at module level so repeated calls (e.g. _render_map → labels → main
# generator) share one font set instead of paying truetype open cost each time.
_FONT_CACHE: Optional[Dict[str, ImageFont.FreeTypeFont]] = None


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

    _reg = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    ]
    _bold = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    ]

    def _load(paths: List[str], size: int) -> ImageFont.FreeTypeFont:
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except (IOError, OSError):
                pass
        return ImageFont.load_default(size=size)

    _FONT_CACHE = {
        'title':  _load(_bold, 30),
        'head':   _load(_bold, 18),
        'bold':   _load(_bold, 15),
        'normal': _load(_reg,  14),
        'small':  _load(_reg,  12),
        'tiny':   _load(_reg,  11),
        'label':  _load(_bold, 11),
        'threat': _load(_bold, 15),
        'mono':   _load(_reg,  11),
    }
    return _FONT_CACHE


# ─── Colour helpers ──────────────────────────────────────────────────────────
def _darken(c: Tuple[int, int, int], f: float) -> Tuple[int, int, int]:
    return tuple(max(0, int(v * (1.0 - f))) for v in c)  # type: ignore[return-value]


def _pct_bar_color(pct: float) -> Tuple[int, int, int]:
    if pct >= 95:  return (40, 167,  69)
    if pct >= 75:  return (255, 193,   7)
    if pct >= 50:  return ( 13, 110, 253)
    return (108, 117, 125)


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


def _draw_pill(draw: ImageDraw.ImageDraw,
               font: ImageFont.FreeTypeFont,
               text: str,
               fill: Tuple[int, int, int],
               x: int, y: int,
               *,
               text_color: Tuple[int, int, int] = (255, 255, 255),
               pad_x: int = 9, pad_y: int = 3) -> int:
    """Draw a rounded-rectangle pill at (x, y) with *text* inside.

    Returns the x-coordinate of the pill's right edge so the caller can
    chain multiple pills horizontally without re-measuring.
    """
    text_w = _tw(font, text)
    text_h = _th(font, text)
    pill_w = text_w + pad_x * 2
    pill_h = text_h + pad_y * 2
    radius = max(2, pill_h // 2)
    draw.rounded_rectangle((x, y, x + pill_w, y + pill_h),
                           radius=radius, fill=fill)
    # Pillow's ``getbbox`` excludes the top-side bearing of TrueType
    # fonts, so subtract the bbox top to get the baseline-aligned y.
    bbox_top = font.getbbox(text)[1]
    draw.text((x + pad_x, y + pad_y - bbox_top), text, font=font, fill=text_color)
    return x + pill_w


def _resolve_local_tz():
    """Return the configured location tzinfo without forcing the full
    ``app_utils`` package init (which pulls in psutil and friends).

    Honours the same ``DEFAULT_TIMEZONE`` env var that
    ``app_utils.time.get_location_timezone`` reads, so behaviour stays
    consistent across the rest of the app.
    """
    tz_name = os.environ.get('DEFAULT_TIMEZONE', 'America/New_York')
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        try:
            import pytz
            return pytz.timezone(tz_name)
        except Exception:
            from datetime import timezone
            return timezone.utc


def _short_local_dt(dt: Any, ref: Optional[Any] = None) -> str:
    """Compact local-time label for the share-card footer.

    Returns e.g. ``"6:29 PM EDT"`` when *dt* and *ref* share a calendar
    day (or *ref* is None), or ``"May 19 · 6:29 PM EDT"`` when they
    don't, so an "Expires …" stamp can never appear earlier than
    "Issued …" on a quick read.
    """
    from datetime import datetime, timezone

    tz = _resolve_local_tz()

    def _to_local(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if getattr(value, 'tzinfo', None) is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(tz)

    local = _to_local(dt)
    if local is None:
        return ''

    show_date = False
    if ref is not None:
        ref_local = _to_local(ref)
        if ref_local is not None and local.date() != ref_local.date():
            show_date = True

    # %I gives zero-padded hour ("06"); strip the leading zero for the
    # share card without relying on platform-specific %-I.
    time_part = local.strftime('%I:%M %p %Z')
    if time_part.startswith('0'):
        time_part = time_part[1:]
    if show_date:
        date_part = local.strftime('%b %d').replace(' 0', ' ')
        return f"{date_part} · {time_part}"
    return time_part


# ─── ALL-CAPS → sentence-case humanizer ─────────────────────────────────────
# NWS CAP feeds arrive ALL-CAPS (a legacy of teletype-era systems).  Rendering
# them shouted on a share card is the single biggest legibility hit — bodies
# of text in caps are ~10–20% slower to read.  These helpers detect a shouted
# string and rebuild a readable sentence-case form while keeping known
# acronyms (NWS, EDT, MPH, …) and US state names properly capitalised.

# Tokens that should remain ALL-CAPS after humanising.
_PRESERVE_ACRONYMS = frozenset([
    # Issuing agencies / source systems
    'NWS', 'WFO', 'NOAA', 'NHC', 'SPC', 'WPC', 'CPC', 'IPAWS', 'FEMA',
    'EAS', 'EOC', 'NCEP', 'NWR',
    # Time zones (continental + AK/HI + Atlantic + Chamorro)
    'UTC', 'GMT', 'EST', 'EDT', 'CST', 'CDT', 'MST', 'MDT', 'PST', 'PDT',
    'AKST', 'AKDT', 'HST', 'HAST', 'AST', 'ADT', 'CHST', 'SST',
    # Compass points
    'N', 'NE', 'NNE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW',
    # Units
    'MPH', 'KPH', 'KMH', 'KTS', 'KT',
    'AM', 'PM',
    # Convective intensity
    'EF0', 'EF1', 'EF2', 'EF3', 'EF4', 'EF5',
    'F0', 'F1', 'F2', 'F3', 'F4', 'F5',
    # Protocols / identifiers commonly in alert text
    'CAP', 'VTEC', 'PVTEC', 'HVTEC', 'UGC', 'WMO', 'FIPS', 'SAME',
    'AMBER', 'AWIPS',  # AMBER is technically a backronym but is brand-cased
])

# US state / territory codes (kept uppercase)
_US_STATE_CODES = frozenset([
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC', 'PR', 'VI', 'GU', 'AS', 'MP',
])

# Full US state / territory names (lowercase key → display form).
_US_STATES = {
    'alabama': 'Alabama', 'alaska': 'Alaska', 'arizona': 'Arizona',
    'arkansas': 'Arkansas', 'california': 'California', 'colorado': 'Colorado',
    'connecticut': 'Connecticut', 'delaware': 'Delaware', 'florida': 'Florida',
    'georgia': 'Georgia', 'hawaii': 'Hawaii', 'idaho': 'Idaho',
    'illinois': 'Illinois', 'indiana': 'Indiana', 'iowa': 'Iowa',
    'kansas': 'Kansas', 'kentucky': 'Kentucky', 'louisiana': 'Louisiana',
    'maine': 'Maine', 'maryland': 'Maryland', 'massachusetts': 'Massachusetts',
    'michigan': 'Michigan', 'minnesota': 'Minnesota', 'mississippi': 'Mississippi',
    'missouri': 'Missouri', 'montana': 'Montana', 'nebraska': 'Nebraska',
    'nevada': 'Nevada', 'ohio': 'Ohio', 'oklahoma': 'Oklahoma',
    'oregon': 'Oregon', 'pennsylvania': 'Pennsylvania', 'tennessee': 'Tennessee',
    'texas': 'Texas', 'utah': 'Utah', 'vermont': 'Vermont', 'virginia': 'Virginia',
    'washington': 'Washington', 'wisconsin': 'Wisconsin', 'wyoming': 'Wyoming',
    'guam': 'Guam',
}

# Stopwords kept lowercase when title-casing enumeration lists (cities of X, Y…).
_LIST_STOPWORDS = frozenset([
    'of', 'and', 'or', 'the', 'a', 'an', 'in', 'on', 'at', 'to', 'by',
])

# Triggers that flag a coming proper-noun enumeration (NWS texts list
# affected cities/counties after these phrases).
_LIST_TRIGGER_RE = re.compile(
    r'\b(cities?\s+of|counties?\s+of|towns?\s+of|villages?\s+of|'
    r'townships?\s+of|parishes?\s+of|boroughs?\s+of|community\s+of|'
    r'communities\s+of)\b([^.]*)',
    flags=re.IGNORECASE,
)


def _is_shouting(text: str, threshold: float = 0.80) -> bool:
    """True when *text* is dominantly uppercase — likely an NWS feed string."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 12:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= threshold


def _humanize_caps_text(text: str) -> str:
    """Convert ALL-CAPS NWS-style text to readable sentence case.

    Only operates when *text* is dominantly uppercase.  The output:
    - lowercases the body,
    - capitalises the first letter and any letter following sentence
      punctuation,
    - restores known acronyms (NWS, EDT, MPH, …) and US state codes,
    - title-cases full US state names,
    - title-cases the proper-noun enumeration that follows triggers like
      "cities of" / "counties of".
    """
    if not text or not _is_shouting(text):
        return text

    out = text.lower()

    # Capitalise the very first alphabetic character.
    for i, ch in enumerate(out):
        if ch.isalpha():
            out = out[:i] + ch.upper() + out[i + 1:]
            break

    # Capitalise after sentence-ending punctuation.
    out = re.sub(
        r'([.!?]\s+)([a-z])',
        lambda m: m.group(1) + m.group(2).upper(),
        out,
    )

    def _restore_word(m: 're.Match[str]') -> str:
        word = m.group(0)
        upper = word.upper()
        if upper in _PRESERVE_ACRONYMS:
            return upper
        lower = word.lower()
        if lower in _US_STATES:
            return _US_STATES[lower]
        return word

    out = re.sub(r"[A-Za-z]+", _restore_word, out)

    # State codes are intentionally NOT in the global preserve set — too
    # many overlap with common English words (IN, OR, ME, HI, OK, PA, MA,
    # LA, DE, …) so a blanket uppercase would turn "in effect" into
    # "IN effect".  Only uppercase them when they appear at the END of a
    # comma-prefixed list item — i.e. the unambiguous "City, ST" pattern
    # closed by a list separator (``, ;``), sentence punctuation
    # (``. ! ?``), or end-of-string.  Crucially the lookahead does NOT
    # match a trailing space, since ``, in a vehicle`` and ``, or in a``
    # would otherwise look identical to ``, OH `` and get mis-shouted.
    def _state_code_after_comma(m: 're.Match[str]') -> str:
        prefix, code = m.group(1), m.group(2)
        return prefix + code.upper() if code.upper() in _US_STATE_CODES else m.group(0)

    out = re.sub(
        r'(,\s+)([A-Za-z]{2})(?=[.,;:!?]|$)',
        _state_code_after_comma,
        out,
    )

    # Title-case proper nouns inside enumeration phrases ("cities of A, B,
    # and C") — preserves city/county names that lowercase otherwise.
    def _title_list(m: 're.Match[str]') -> str:
        head, body = m.group(1), m.group(2)

        def _title_word(wm: 're.Match[str]') -> str:
            w = wm.group(0)
            if w.upper() in _PRESERVE_ACRONYMS:
                return w.upper()
            if w.lower() in _LIST_STOPWORDS:
                return w.lower()
            return w[:1].upper() + w[1:].lower()

        body = re.sub(r"[A-Za-z]+", _title_word, body)
        return head + body

    out = _LIST_TRIGGER_RE.sub(_title_list, out)
    return out


# ─── Lightning bolt renderer (matches the site's lightning theme) ───────────
# Ported from static/js/core/lightning.js so social-share images carry the
# same stormy-sky visual identity as the web UI.

def _lb_trunk(rng: random.Random, start_x: float, start_y: float,
              end_y: float, segments: int, drift: float) -> List[Tuple[float, float]]:
    """Jagged descending trunk with uneven step length — real bolts aren't even zigzags."""
    pts: List[Tuple[float, float]] = [(start_x, start_y)]
    x, y = start_x, start_y
    avg_step = (end_y - start_y) / max(1, segments)
    for _ in range(1, segments):
        step = avg_step * rng.uniform(0.55, 1.45)
        y = min(end_y, y + step)
        x += rng.uniform(-drift, drift)
        pts.append((x, y))
    pts.append((x + rng.uniform(-drift, drift), end_y))
    return pts


def _lb_branches(rng: random.Random, parent: List[Tuple[float, float]],
                 spawn_chance: float, depth: int, base_width: float,
                 side_hint: int) -> List[Dict[str, Any]]:
    """Branches fork from interior trunk vertices and may recurse."""
    out: List[Dict[str, Any]] = []
    if depth <= 0:
        return out
    for i in range(1, len(parent) - 1):
        if rng.random() >= spawn_chance:
            continue
        ox, oy = parent[i]
        direction = side_hint * (1 if rng.random() < 0.75 else -1)
        length = rng.uniform(40, 140)
        segs = rng.randint(3, 7)
        step = length / segs
        angle = rng.uniform(0.55, 1.25)
        branch: List[Tuple[float, float]] = [(ox, oy)]
        cx, cy = ox, oy
        for _ in range(segs):
            lateral = math.sin(angle + rng.uniform(-0.35, 0.35)) * step * direction
            descent = math.cos(angle) * step * 0.65 + rng.uniform(-step * 0.15, step * 0.35)
            cx += lateral
            cy += descent
            branch.append((cx, cy))
        out.append({'points': branch, 'width': base_width})
        if depth > 1 and rng.random() < spawn_chance * 0.6:
            out.extend(_lb_branches(rng, branch, spawn_chance * 0.5,
                                    depth - 1, base_width * 0.55, direction))
    return out


def _lb_render_polyline(draw: ImageDraw.ImageDraw,
                        points: List[Tuple[float, float]],
                        base_width: float, taper: float,
                        color: Tuple[int, int, int, int]) -> None:
    """Draw a tapered polyline — width shrinks toward the tip for a bolt-like feel."""
    total = len(points) - 1
    if total <= 0:
        return
    for i in range(total):
        t = i / total
        w = max(1, int(round(base_width * ((1 - t) ** taper))))
        p1 = (int(points[i][0]),     int(points[i][1]))
        p2 = (int(points[i + 1][0]), int(points[i + 1][1]))
        draw.line([p1, p2], fill=color, width=w)


def _draw_lightning_bolts(target: Image.Image, region: Tuple[int, int, int, int],
                          *, count: int = 2, seed: int = 0,
                          intensity: float = 1.0) -> None:
    """Composite glowing lightning bolts onto *target* within *region* (x, y, w, h).

    Bolts are rendered once as geometry, then drawn three times with
    shrinking widths and increasing opacity: a wide blurred halo, a
    medium-width glow, and a crisp white core.  This stack mimics the
    CSS drop-shadow layers used by the web UI's lightning.js so the
    share image carries the same visual identity.
    """
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return

    rng = random.Random(seed)

    # ── Geometry pass: build trunks + branches once, reuse for each layer ──
    bolts: List[Dict[str, Any]] = []
    # Extend virtual height so the trunk develops a natural zigzag rhythm
    # even when the physical region is short (e.g. the 90-px header).  We
    # draw into the full virtual range, then clip by the region when
    # compositing.
    vh = max(rh, 260)
    for _ in range(count):
        start_x  = rng.uniform(rw * 0.08, rw * 0.92)
        start_y  = rng.uniform(-vh * 0.20, -vh * 0.05)
        end_y    = vh + rng.uniform(-vh * 0.10, vh * 0.05)
        segments = rng.randint(12, 18)
        # Drift is per-step, proportional to segment length — this keeps
        # the bolt predominantly vertical instead of ping-ponging sideways.
        step_h   = (end_y - start_y) / segments
        drift    = step_h * rng.uniform(0.35, 0.75)
        side     = 1 if start_x < rw / 2 else -1

        trunk    = _lb_trunk(rng, start_x, start_y, end_y, segments, drift)
        branches = _lb_branches(rng, trunk, 0.38, 2, 1.6, side)
        bolts.append({'trunk': trunk, 'branches': branches})

    # Render geometry to three layers at different widths/opacities.
    def _stamp(width_trunk: float, width_branch: float,
               taper_t: float, taper_b: float, alpha: int) -> Image.Image:
        layer = Image.new('RGBA', (rw, vh), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        color = (255, 255, 255, min(255, max(0, int(alpha * intensity))))
        for bolt in bolts:
            _lb_render_polyline(ld, bolt['trunk'], width_trunk, taper_t, color)
            for b in bolt['branches']:
                _lb_render_polyline(ld, b['points'],
                                    max(1.0, b['width'] * width_branch),
                                    taper_b, color)
        return layer

    halo = _stamp(width_trunk=14, width_branch=7, taper_t=1.0, taper_b=1.3, alpha=110)
    glow = _stamp(width_trunk=7,  width_branch=4, taper_t=1.1, taper_b=1.4, alpha=170)
    core = _stamp(width_trunk=3,  width_branch=1, taper_t=1.3, taper_b=1.6, alpha=245)

    halo = halo.filter(ImageFilter.GaussianBlur(radius=10))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=3))

    # Composite onto target, clipping to the physical region height.
    def _paste(layer: Image.Image) -> None:
        cropped = layer.crop((0, 0, rw, rh))
        if target.mode != 'RGBA':
            base = target.convert('RGBA')
            base.alpha_composite(cropped, dest=(x0, y0))
            target.paste(base.convert('RGB'))
        else:
            target.alpha_composite(cropped, dest=(x0, y0))

    _paste(halo)
    _paste(glow)
    _paste(core)


# ─── Other particle styles (event-specific) ─────────────────────────────────
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


def _draw_snow(target: Image.Image, region: Tuple[int, int, int, int],
               *, seed: int = 0, intensity: float = 1.0) -> None:
    """Snowflake particles — drifting white dots and 6-armed stars."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0xA5A5)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    flake_count = int(45 * intensity)
    for _ in range(flake_count):
        fx = rng.uniform(0, rw)
        fy = rng.uniform(0, rh)
        r = rng.uniform(1.4, 3.6)
        alpha = int(rng.uniform(110, 220) * intensity)
        ld.ellipse((fx - r, fy - r, fx + r, fy + r),
                   fill=(255, 255, 255, min(255, alpha)))
    # A few larger stylised flakes with arms
    for _ in range(int(7 * intensity)):
        fx = rng.uniform(rw * 0.05, rw * 0.95)
        fy = rng.uniform(rh * 0.10, rh * 0.85)
        r = rng.uniform(4.0, 6.5)
        alpha = int(rng.uniform(180, 240) * intensity)
        col = (255, 255, 255, min(255, alpha))
        for k in range(6):
            ang = math.radians(k * 60)
            ex = fx + math.cos(ang) * r
            ey = fy + math.sin(ang) * r
            ld.line([(fx, fy), (ex, ey)], fill=col, width=1)
        ld.ellipse((fx - 1, fy - 1, fx + 1, fy + 1), fill=col)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.6))
    _composite(target, region, layer)


def _draw_rain(target: Image.Image, region: Tuple[int, int, int, int],
               *, seed: int = 0, intensity: float = 1.0) -> None:
    """Diagonal rain streaks."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0x3C3C)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    streak_count = int(55 * intensity)
    slant = 4   # x-offset per streak length
    for _ in range(streak_count):
        sx = rng.uniform(-rw * 0.1, rw)
        sy = rng.uniform(-rh * 0.3, rh)
        length = rng.uniform(rh * 0.20, rh * 0.55)
        alpha = int(rng.uniform(100, 200) * intensity)
        col = (200, 225, 255, min(255, alpha))
        ld.line([(sx, sy),
                 (sx + slant, sy + length)],
                fill=col, width=1)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.5))
    _composite(target, region, layer)


def _draw_sun_rays(target: Image.Image, region: Tuple[int, int, int, int],
                   *, seed: int = 0, intensity: float = 1.0) -> None:
    """Radial rays + warm glow ball — heat-advisory visual."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0x5E11)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    # Place sun centre off the right edge so rays sweep across the header
    cx = rw - rng.randint(40, 110)
    cy = rng.randint(-int(rh * 0.4), int(rh * 0.2))
    # Bright halo
    for r in range(120, 25, -8):
        a = int(8 * intensity * (1 - (r - 25) / 100))
        if a <= 0:
            continue
        ld.ellipse((cx - r, cy - r, cx + r, cy + r),
                   fill=(255, 230, 130, max(0, min(255, a))))
    # Rays
    n_rays = 14
    for k in range(n_rays):
        ang = 2 * math.pi * k / n_rays + rng.uniform(-0.05, 0.05)
        length = rng.uniform(rw * 0.45, rw * 0.85)
        ex = cx + math.cos(ang) * length
        ey = cy + math.sin(ang) * length
        alpha = int(rng.uniform(60, 160) * intensity)
        ld.line([(cx, cy), (ex, ey)],
                fill=(255, 220, 110, min(255, alpha)), width=2)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=2.0))
    # Bright core on top of the blur
    ld2 = ImageDraw.Draw(layer)
    ld2.ellipse((cx - 22, cy - 22, cx + 22, cy + 22),
                fill=(255, 240, 170, int(220 * intensity)))
    _composite(target, region, layer)


def _draw_embers(target: Image.Image, region: Tuple[int, int, int, int],
                 *, seed: int = 0, intensity: float = 1.0) -> None:
    """Rising hot embers — orange dots with glow, sparser at the top."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0xE3B5)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    count = int(55 * intensity)
    for _ in range(count):
        # Embers concentrate near the bottom — bias toward higher y
        fy = rh - (rng.random() ** 1.8) * rh
        fx = rng.uniform(0, rw)
        r = rng.uniform(1.0, 3.0)
        # Colour ramp: deep red at bottom → bright yellow toward top
        t = fy / max(1, rh)   # 0 top → 1 bottom
        red   = int(255)
        green = int(80 + (1 - t) * 150)
        blue  = int(20 + (1 - t) * 40)
        alpha = int(rng.uniform(120, 230) * intensity)
        ld.ellipse((fx - r, fy - r, fx + r, fy + r),
                   fill=(red, green, blue, min(255, alpha)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=1.2))
    # A few crisp sparks on top
    ld2 = ImageDraw.Draw(layer)
    for _ in range(int(10 * intensity)):
        fx = rng.uniform(0, rw)
        fy = rh - (rng.random() ** 1.6) * rh
        ld2.ellipse((fx - 1, fy - 1, fx + 1, fy + 1),
                    fill=(255, 245, 180, int(230 * intensity)))
    _composite(target, region, layer)


def _draw_wind_streaks(target: Image.Image, region: Tuple[int, int, int, int],
                       *, seed: int = 0, intensity: float = 1.0) -> None:
    """Horizontal motion streaks — wind/hurricane visual."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0x7777)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    streak_count = int(28 * intensity)
    for _ in range(streak_count):
        sy = rng.uniform(0, rh)
        sx = rng.uniform(-rw * 0.1, rw * 0.4)
        length = rng.uniform(rw * 0.20, rw * 0.55)
        width = rng.choice([1, 1, 2])
        alpha = int(rng.uniform(80, 180) * intensity)
        col = (235, 240, 255, min(255, alpha))
        # Slight upward curve to feel "blown"
        mx = sx + length * 0.5
        my = sy - rng.uniform(0, 4)
        ex = sx + length
        ey = sy
        # Quadratic-ish — approximate with two line segments
        ld.line([(sx, sy), (mx, my)], fill=col, width=width)
        ld.line([(mx, my), (ex, ey)], fill=col, width=width)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.7))
    _composite(target, region, layer)


def _draw_haze(target: Image.Image, region: Tuple[int, int, int, int],
               *, seed: int = 0, intensity: float = 1.0) -> None:
    """Soft horizontal fog/haze bands."""
    x0, y0, rw, rh = region
    if rw <= 0 or rh <= 0:
        return
    rng = random.Random(seed ^ 0x4ADE)
    layer = Image.new('RGBA', (rw, rh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    bands = 5
    for _ in range(bands):
        cy_ = rng.uniform(rh * 0.15, rh * 0.85)
        band_h = rng.uniform(rh * 0.15, rh * 0.35)
        alpha = int(rng.uniform(35, 70) * intensity)
        # Ellipse much wider than tall = horizontal smear
        ld.ellipse((-rw * 0.1, cy_ - band_h / 2,
                    rw * 1.1, cy_ + band_h / 2),
                   fill=(230, 235, 245, min(255, alpha)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=8.0))
    _composite(target, region, layer)


_PARTICLE_FNS = {
    'bolts':  lambda t, r, **kw: _draw_lightning_bolts(t, r, count=3, **kw),
    'snow':   _draw_snow,
    'rain':   _draw_rain,
    'sun':    _draw_sun_rays,
    'embers': _draw_embers,
    'wind':   _draw_wind_streaks,
    'haze':   _draw_haze,
    'none':   None,
}


def _draw_themed_header(img: Image.Image, theme: _Theme,
                        seed: int = 0,
                        layout: Optional[_Layout] = None) -> None:
    """Paint a themed header: diagonal gradient + event-appropriate particles.

    Replaces the older single-colour vertical gradient + always-bolts
    combo.  The gradient runs diagonally (top-left → bottom-right) for
    a more dynamic feel, and the particle layer is event-specific:
    snowflakes for winter advisories, raindrops for floods, sun rays for
    heat, etc.  See ``_THEMES`` for the full mapping.
    """
    lay = layout or _LAYOUT_LANDSCAPE
    canvas_w = lay.width
    header_h = lay.header_h
    top = theme['top']
    bot = theme['bottom']
    # Diagonal gradient — compute t from a normal vector pointing from
    # the top-left corner to the bottom-right of the header.  Drawing per
    # row is fast enough and lets us shade left→right per row by sampling
    # the diagonal coordinate at line midpoint.
    diag = header_h + canvas_w * 0.35   # how far along the diagonal we go
    for y in range(header_h):
        # Two-stop interpolation with per-row x sweep so the right side
        # of the image runs ahead of the left — diagonal feel.
        row = Image.new('RGB', (canvas_w, 1), bot)
        rd = ImageDraw.Draw(row)
        for x in range(0, canvas_w, 8):   # step by 8 px — visually smooth, fast
            t = (y + x * 0.35) / diag
            t = max(0.0, min(1.0, t))
            r = int(top[0] * (1 - t) + bot[0] * t)
            g = int(top[1] * (1 - t) + bot[1] * t)
            b = int(top[2] * (1 - t) + bot[2] * t)
            rd.line([(x, 0), (min(canvas_w, x + 8), 0)], fill=(r, g, b))
        img.paste(row, (0, y))
    # Slight darkening at the very top edge so the title reads clearly
    # against the brighter parts of the gradient.
    shade = Image.new('RGBA', (canvas_w, header_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(28):
        a = int(60 * (1 - y / 28))
        sd.line([(0, y), (canvas_w, y)], fill=(0, 0, 0, a))
    base = img.convert('RGBA')
    base.alpha_composite(shade)
    img.paste(base.convert('RGB'))
    # Particle layer
    particle = theme.get('particles', 'bolts')
    intensity = float(theme.get('particle_intensity', 1.0))
    fn = _PARTICLE_FNS.get(particle)
    if fn is not None and intensity > 0.01:
        fn(img, (0, 0, canvas_w, header_h), seed=seed, intensity=intensity)


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


def _best_zoom(min_lon: float, min_lat: float, max_lon: float, max_lat: float,
               map_w: int, map_h: int) -> int:
    """Highest OSM zoom where bbox comfortably fits inside the map dimensions."""
    for z in range(15, 3, -1):
        tx1 = _lon_to_tx(min_lon, z)
        tx2 = _lon_to_tx(max_lon, z)
        ty1 = _lat_to_ty(max_lat, z)   # higher lat → lower tile-y
        ty2 = _lat_to_ty(min_lat, z)
        span_w = (tx2 - tx1) * TILE_SIZE
        span_h = (ty2 - ty1) * TILE_SIZE
        if span_w <= map_w * 0.60 and span_h <= map_h * 0.60:
            return z
    return 7


# ─── OSM tile fetch + cache ─────────────────────────────────────────────────
# OpenStreetMap's tile-usage policy asks consumers to cache tiles aggressively;
# every re-render of the same alert used to refetch up to 30 tiles.  This
# bounded LRU keeps the most recently fetched tiles in memory so subsequent
# renders within the same worker process answer instantly and stop hammering
# tile.openstreetmap.org.  Tiles are immutable for our purposes (zoom level
# pins the source pyramid), so caching is safe — only Pillow's underlying
# bytes are kept; ``Image.copy()`` on read returns a fresh handle that
# downstream code can crop/paste into without mutating the cached copy.

from collections import OrderedDict
from threading import Lock

_TILE_CACHE_MAX = 256
_TILE_CACHE: "OrderedDict[Tuple[int, int, int], bytes]" = OrderedDict()
_TILE_CACHE_LOCK = Lock()


def _tile_cache_get(key: Tuple[int, int, int]) -> Optional[bytes]:
    with _TILE_CACHE_LOCK:
        if key in _TILE_CACHE:
            _TILE_CACHE.move_to_end(key)
            return _TILE_CACHE[key]
    return None


def _tile_cache_put(key: Tuple[int, int, int], data: bytes) -> None:
    with _TILE_CACHE_LOCK:
        _TILE_CACHE[key] = data
        _TILE_CACHE.move_to_end(key)
        while len(_TILE_CACHE) > _TILE_CACHE_MAX:
            _TILE_CACHE.popitem(last=False)


def _tile_cache_clear() -> None:
    """Drop every cached tile — exposed for tests; not used by the renderer."""
    with _TILE_CACHE_LOCK:
        _TILE_CACHE.clear()


def _fetch_tile(tx: int, ty: int, z: int) -> Optional[Image.Image]:
    key = (z, tx, ty)
    cached = _tile_cache_get(key)
    if cached is not None:
        try:
            return Image.open(io.BytesIO(cached)).convert('RGB')
        except Exception:
            # Cached entry corrupt — evict and refetch.
            with _TILE_CACHE_LOCK:
                _TILE_CACHE.pop(key, None)

    url = f'https://tile.openstreetmap.org/{z}/{tx}/{ty}.png'
    try:
        r = _http.get(
            url, timeout=4,
            headers={'User-Agent': 'EASStation/1.0 (+https://github.com/KR8MER/eas-station)'},
        )
        if r.status_code == 200:
            _tile_cache_put(key, r.content)
            return Image.open(io.BytesIO(r.content)).convert('RGB')
    except Exception:
        pass
    return None


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


def _render_map(geom: Dict, severity: str,
                storm_motion: Optional[Dict] = None,
                theme: Optional[_Theme] = None,
                *, map_w: int = MAP_W, map_h: int = MAP_H) -> Image.Image:
    """Return a *map_w*×*map_h* RGB map image with the alert polygon overlaid.

    *theme* drives the polygon stroke / storm-motion accent colours; if
    omitted we fall back to the severity palette (legacy behaviour).

    The map intentionally renders only the alert polygon (plus optional
    storm-motion overlay) on top of OSM tiles — county/zone boundary
    outlines and centroid name labels were removed because they made
    the share image cluttered and unreadable when multiple boundaries
    overlapped.
    """
    fallback = Image.new('RGB', (map_w, map_h), (35, 42, 62))
    fd = ImageDraw.Draw(fallback)
    msg = 'Map not available'
    fonts = _load_fonts()
    fd.text(((map_w - _tw(fonts['small'], msg)) // 2, map_h // 2 - 8),
            msg, font=fonts['small'], fill=_TEXT_MUT)

    bbox = _geojson_bbox(geom)
    if bbox is None:
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

    # ── Polygon glow ──────────────────────────────────────────────────────
    # A blurred wider stroke sits behind the crisp outline so the affected
    # area "lifts" off the basemap and is unmistakable at thumbnail size.
    glow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for ring in rings:
        pts = _to_px(ring)
        if len(pts) >= 2:
            gd.line(pts + [pts[0]], fill=(*alr_clr, 230), width=9)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=6))

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
            od.line(closed, fill=(255, 255, 255), width=5)
            od.line(closed, fill=alr_clr,         width=3)

    # Storm motion overlay (new cone + tapered arrow + callout)
    if storm_motion:
        _draw_storm_track(canvas, storm_motion, z, tx_min, ty_min,
                          accent=alr_clr, fonts=fonts)
        od = ImageDraw.Draw(canvas)

    # ── Boundary overlays ─────────────────────────────────────────────────────
    # Boundary outlines and centroid name labels were intentionally removed:
    # when multiple county / zone boundaries overlapped (or sat close to the
    # alert polygon) the labels collided and produced a cluttered, unreadable
    # share image.  Only the alert polygon and storm-motion overlay are drawn.

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
    if cropped.size != (map_w, map_h):
        cropped = cropped.resize((map_w, map_h), Image.LANCZOS)

    cd = ImageDraw.Draw(cropped)

    # ── OSM attribution (required by tile usage policy) ───────────────────────
    attr     = '\u00a9 OpenStreetMap contributors'
    attr_fnt = fonts['tiny']
    aw, ah   = _tw(attr_fnt, attr), _th(attr_fnt, attr)
    ax, ay   = map_w - aw - 5, map_h - ah - 5
    cd.rectangle((ax - 2, ay - 1, map_w - 3, map_h - 3), fill=(0, 0, 0))
    cd.text((ax, ay), attr, font=attr_fnt, fill=(200, 200, 200))

    return cropped


# ─── Drawing helpers ─────────────────────────────────────────────────────────
def _section_header(draw: ImageDraw.ImageDraw, fonts: Dict,
                    alr_clr: Tuple, ix: int, iy: int, iw: int, title: str,
                    *, bg: Optional[Tuple[int, int, int]] = None) -> int:
    """Draw a coloured section header; return y after it.

    When *bg* is provided it overrides the default ``alr_clr``-derived
    fill — used by the instruction/action band to flag safety guidance
    with a warning-yellow header that stands apart from the neutral
    headline / description sections.
    """
    h = 20
    fill = bg if bg is not None else _darken(alr_clr, 0.25)
    draw.rectangle((ix, iy, ix + iw, iy + h), fill=fill)
    draw.text((ix + 7, iy + (h - _th(fonts['label'], title)) // 2),
              title, font=fonts['label'], fill=WHITE)
    return iy + h + 2


def _card_row(draw: ImageDraw.ImageDraw, ix: int, iy: int, iw: int, h: int) -> None:
    """Fill a single card-row background."""
    draw.rectangle((ix, iy, ix + iw, iy + h - 1), fill=_CARD)


# ─── Main public function ─────────────────────────────────────────────────────
def generate_alert_image(
    alert: Any,
    coverage_data: Dict[str, Any],
    ipaws_data: Optional[Dict[str, Any]],
    location_settings: Optional[Dict[str, Any]],
    aspect_ratio: str = 'landscape',
    image_format: str = 'png',
) -> bytes:
    """Generate a share-card image for *alert* in the requested aspect ratio.

    Args:
        alert:             CAPAlert model instance.
        coverage_data:     Dict returned by calculate_coverage_percentages().
        ipaws_data:        Dict returned by _extract_alert_display_data(), may be None.
        location_settings: Dict from get_location_settings(), may be None.
        aspect_ratio:      One of ``landscape`` (1200×630, default — FB/X/LI
            open-graph), ``square`` (1080×1080 — Instagram, Mastodon),
            ``portrait`` (1080×1350 — Instagram 4:5) or ``story``
            (1080×1920 — IG / TikTok / Snap).  Unknown values fall back
            to landscape so callers can pass any platform hint.
        image_format:      ``png`` (default, universal) or ``webp`` (lossy,
            ~30% smaller at equivalent quality, supported by every major
            social platform).  Unknown values fall back to ``png``.

    Returns:
        Raw image bytes in the requested container.
    """
    layout = _LAYOUTS.get(aspect_ratio, _LAYOUT_LANDSCAPE)
    fonts = _load_fonts()

    severity    = (getattr(alert, 'severity', '') or '').lower()
    event_name  = (getattr(alert, 'event', '') or 'Alert').upper()
    county_name = (location_settings or {}).get('county_name', 'County') or 'County'

    # Event-aware theme drives the header gradient, particle style, and
    # accent colour used for section headers + the polygon stroke.  We
    # keep the legacy ``alr_clr`` symbol pointing at the theme accent so
    # downstream draw helpers don't need signature changes.
    theme   = _resolve_theme(event_name, severity)
    alr_clr = tuple(theme['accent'])  # type: ignore[assignment]

    # Stable per-alert seed so each alert's bolt/snow/etc pattern is
    # reproducible across re-renders.
    alert_seed = hash((getattr(alert, 'id', 0) or 0, event_name)) & 0xFFFFFFFF

    # ── Base canvas ──────────────────────────────────────────────────────────
    img  = Image.new('RGB', (layout.width, layout.height), _BG)
    draw = ImageDraw.Draw(img)

    # ── Header bar (event-themed gradient + particles) ───────────────────────
    # Diagonal gradient + event-specific particle layer (bolts for storms,
    # snowflakes for winter, raindrops for floods, sun rays for heat, ...).
    _draw_themed_header(img, theme, seed=alert_seed, layout=layout)
    # Soft scrim under the title text for legibility against the particle
    # layer.  Only the left ~half — the right side is reserved for branding
    # and shows the particles clearly.
    scrim = Image.new('RGBA', (layout.width, layout.header_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    sd.rectangle((0, 0, layout.header_scrim_w, layout.header_h),
                 fill=(0, 0, 0, 75))
    base = img.convert('RGBA')
    base.alpha_composite(scrim)
    img.paste(base.convert('RGB'))
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, layout.header_h - 2, layout.width, layout.header_h),
                   fill=_darken(alr_clr, 0.45))

    # Event name (left).  Title y is tuned to leave room for the sub-line
    # below; sub-line y sits below the title font's natural height.
    title_y = 10
    draw.text((16, title_y), event_name, font=fonts['title'], fill=WHITE)
    title_h = _th(fonts['title'], event_name)

    # Metadata row — severity becomes a coloured pill (the single most
    # glanceable signal for "how worried should I be") with urgency /
    # certainty rendered as quieter secondary text.  Status renders as a
    # neutral pill but only when it isn't the default "Actual" (which
    # holds for ~all production alerts and just adds noise).
    sub_y = title_y + title_h + 8
    pill_x = 18

    severity_val = (getattr(alert, 'severity', '') or '').strip()
    if severity_val:
        sev_color = _SEVERITY.get(
            severity_val.lower(),
            _SEVERITY.get('unknown', (108, 117, 125)),
        )
        pill_x = _draw_pill(draw, fonts['label'], severity_val.upper(),
                            sev_color, pill_x, sub_y)
        pill_x += 8

    status_val = (getattr(alert, 'status', '') or '').strip()
    if status_val and status_val.lower() != 'actual':
        pill_x = _draw_pill(draw, fonts['label'], status_val.upper(),
                            (108, 117, 125), pill_x, sub_y)
        pill_x += 8

    extras: List[str] = []
    for attr, label in [('urgency', 'Urgency'), ('certainty', 'Certainty')]:
        val = (getattr(alert, attr, '') or '').strip()
        if val:
            extras.append(f'{label}: {val}')
    if extras:
        extra_text = '  ·  '.join(extras)
        # Optically centre the small text against the pill height so the
        # baseline lines up cleanly instead of riding above the pill.
        pill_h = _th(fonts['label'], 'Mg') + 6  # mirrors _draw_pill padding
        extra_y = sub_y + (pill_h - _th(fonts['small'], extra_text)) // 2 - 1
        draw.text((pill_x, extra_y), extra_text, font=fonts['small'],
                  fill=(*WHITE, 200))  # type: ignore[arg-type]

    # Branding (top-right) — render the canonical EAS Station wordmark image
    # so updating the brand asset is just a matter of swapping the file at
    # static/img/eas-system-wordmark.png (rasterized from the SVG).  Fall
    # back to the legacy text mark only if the file is missing or fails to
    # load.
    logo = _load_logo()
    brand_right = layout.width - 16
    if logo is not None:
        logo_h = layout.header_h - 16
        # Preserve aspect ratio
        ratio = logo_h / float(logo.height)
        logo_w = max(1, int(round(logo.width * ratio)))
        logo_resized = logo.resize((logo_w, logo_h), Image.LANCZOS)
        # Dim the wordmark slightly so it reads as a corner mark instead
        # of competing with the headline.  Multiply the alpha channel by
        # 0.78 — opaque enough to stay legible against the gradient,
        # quiet enough to defer to the title.
        r_ch, g_ch, b_ch, a_ch = logo_resized.split()
        a_ch = a_ch.point(lambda v: int(v * 0.78))
        logo_resized = Image.merge('RGBA', (r_ch, g_ch, b_ch, a_ch))
        lx = brand_right - logo_w
        ly = (layout.header_h - logo_h) // 2
        # Paste with the logo's own alpha so the header gradient shows through
        base_rgba = img.convert('RGBA')
        base_rgba.alpha_composite(logo_resized, dest=(lx, ly))
        img.paste(base_rgba.convert('RGB'))
        draw = ImageDraw.Draw(img)
    else:
        brand = 'EAS STATION'
        draw.text((brand_right - _tw(fonts['head'], brand), 10),
                  brand, font=fonts['head'], fill=WHITE)

    # ── Map slot ────────────────────────────────────────────────────────────
    # Map rectangle comes from the layout: side-by-side for landscape (map
    # on the left), stacked for square/portrait (map below the header).
    map_x, map_y, map_w, map_h = layout.map_rect

    # Storm motion is only meaningful for convective / wind / water events.
    # Suppress it on advisories like FROST / HEAT / FOG where the IPAWS
    # blob may still carry a stale motion vector — it adds noise without
    # information for non-convective events.
    storm_motion = (ipaws_data or {}).get('storm_motion')
    if storm_motion and not _theme_supports_storm_motion(theme):
        storm_motion = None
    map_img: Optional[Image.Image] = None
    try:
        from app_core.extensions import db
        from app_core.models import CAPAlert as _CA
        from sqlalchemy import func as _func
        alert_id = getattr(alert, 'id', None)
        if alert_id is not None:
            geom_json = (
                db.session.query(_func.ST_AsGeoJSON(_CA.geom))
                .filter(_CA.id == alert_id)
                .scalar()
            )
            if geom_json:
                map_img = _render_map(json.loads(geom_json), severity,
                                      storm_motion=storm_motion,
                                      theme=theme,
                                      map_w=map_w, map_h=map_h)
    except Exception:
        pass

    if map_img is None:
        map_img = Image.new('RGB', (map_w, map_h), (34, 42, 60))
        md = ImageDraw.Draw(map_img)
        lbl = 'Map not available'
        md.text(((map_w - _tw(fonts['small'], lbl)) // 2, map_h // 2 - 8),
                lbl, font=fonts['small'], fill=_TEXT_MUT)

    # Round the map's corners so it sits visually inside the rounded
    # canvas instead of butting up against sharp 90° edges.  Skip when
    # the layout asked for a full-bleed map (corner_r = 0).
    if layout.map_corner_r > 0:
        map_img = _round_image_corners(map_img, layout.map_corner_r, bg=_BG)
    img.paste(map_img, (map_x, map_y))

    # Thin vertical separator — only meaningful in side-by-side layouts.
    if layout.show_vertical_divider:
        div_x = map_x + map_w
        draw.line([(div_x, map_y),
                   (div_x, layout.height - layout.footer_h)],
                  fill=_darken(alr_clr, 0.20), width=3)

    # ── Info panel ──────────────────────────────────────────────────────────
    ix, iy_top, iw, ih = layout.info_rect
    iy  = iy_top
    bot = iy_top + ih

    # Priority order for a share card: storm threats (when dangerous), the
    # headline, WHO is affected, WHAT is happening, WHAT to do.  Coverage /
    # storm motion come last so they only consume space the copy doesn't
    # need.  VTAC codes and the issuing-office block are intentionally
    # omitted — they're operator data, not share-worthy info, and were the
    # main reason long descriptions were being clipped.
    iy = _draw_threats(draw, fonts, alr_clr, ix, iy, iw, bot, ipaws_data)
    iy = _draw_nws_headline(draw, fonts, alr_clr, ix, iy, iw, bot, alert, ipaws_data)
    iy = _draw_areas(draw, fonts, alr_clr, ix, iy, iw, bot, alert)
    iy = _draw_description(draw, fonts, alr_clr, ix, iy, iw, bot, alert)
    iy = _draw_instruction(draw, fonts, alr_clr, ix, iy, iw, bot, alert)
    iy = _draw_coverage(draw, fonts, alr_clr, ix, iy, iw, bot, coverage_data, county_name)
    iy = _draw_compass_section(draw, fonts, alr_clr, ix, iy, iw, bot, ipaws_data)

    # ── Footer ────────────────────────────────────────────────────────────────
    fy = layout.height - layout.footer_h
    draw.rectangle((0, fy, layout.width, layout.height), fill=_STRIP)
    draw.line([(0, fy), (layout.width, fy)], fill=_DIVIDER, width=1)

    timing: List[str] = []
    try:
        sent = getattr(alert, 'sent', None)
        expires = getattr(alert, 'expires', None)
        if sent:
            timing.append(f"Issued {_short_local_dt(sent, ref=None)}")
        if expires:
            # When the expiration falls on a different calendar day than the
            # issue time, include the date so "Expires 10:00 PM" isn't
            # ambiguous; otherwise keep it to the bare time.
            timing.append(f"Expires {_short_local_dt(expires, ref=sent)}")
    except Exception:
        pass

    if timing:
        t_str = '  ·  '.join(timing)
        ty_pos = fy + (layout.footer_h - _th(fonts['small'], t_str)) // 2
        draw.text((12, ty_pos), t_str, font=fonts['small'], fill=_TEXT_SEC)

    credit = 'EAS Station  •  Emergency Alert System'
    cy_pos = fy + (layout.footer_h - _th(fonts['small'], credit)) // 2
    draw.text((layout.width - _tw(fonts['small'], credit) - 12, cy_pos),
              credit, font=fonts['small'], fill=_TEXT_MUT)

    # ── Round outer corners and serialise ────────────────────────────────────
    # Soft rounded corners across the whole share card — matches modern
    # feed cards and stops the image looking like a screenshot.  PNG keeps
    # the corner pixels fully transparent so renderers that respect alpha
    # show a true rounded shape; renderers that flatten get the matte
    # they composite against (usually white on social feeds).
    img_rounded = _round_image_corners(img, layout.corner_r, bg=None)

    fmt = (image_format or 'png').strip().lower()
    buf = io.BytesIO()

    if fmt == 'webp':
        # ``method=4`` is a good balance between encode time and final
        # size; ``quality=92`` keeps the gradient header artefact-free
        # while still saving ~30% versus the equivalent PNG.  Pillow does
        # not add EXIF or timestamps to WebP by default, so no explicit
        # metadata stripping step is needed.
        img_rounded.save(buf, format='WEBP', quality=92, method=4)
        return buf.getvalue()

    # Default: PNG with minimal metadata.  Passing an explicit
    # ``pnginfo`` suppresses Pillow's default tIME chunk (which would
    # leak a server timestamp) and any inherited EXIF, while keeping a
    # small ``Software`` tag so exports remain auditable.  ``alert_id``
    # is included as a stable identifier so duplicate uploads can be
    # deduped without leaking PII.
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text('Software', 'EAS Station')
    alert_id = getattr(alert, 'id', None)
    if alert_id is not None:
        pnginfo.add_text('Source', f'alert/{alert_id}')

    img_rounded.save(buf, format='PNG', optimize=True, pnginfo=pnginfo)
    return buf.getvalue()


# ─── Threat-card icon helpers ─────────────────────────────────────────────────
def _icon_wind(draw: ImageDraw.ImageDraw, cx: int, cy: int,
               color: Tuple[int, int, int]) -> None:
    """Three descending-width pill bars representing wind gusts."""
    bars    = [(32, 0), (25, 0), (18, 0)]  # (width, x-offset)
    bar_h   = 6
    spacing = 5
    total_h = len(bars) * bar_h + (len(bars) - 1) * spacing
    y0 = cy - total_h // 2
    for i, (w, xo) in enumerate(bars):
        y = y0 + i * (bar_h + spacing)
        x0 = cx - w // 2 + xo
        draw.rounded_rectangle((x0, y, x0 + w, y + bar_h), radius=3, fill=color)


def _icon_hail(draw: ImageDraw.ImageDraw, cx: int, cy: int,
               color: Tuple[int, int, int]) -> None:
    """Simple cloud arc with hailstone circles beneath it."""
    r = 12
    # Cloud top: semicircle arc
    draw.arc((cx - r, cy - r - 4, cx + r, cy + r - 4),
             start=180, end=360, fill=color, width=3)
    # Cloud base: horizontal line connecting the arc ends
    draw.line([(cx - r, cy + r - 5), (cx + r, cy + r - 5)], fill=color, width=3)
    # Hailstones (2 rows of dots)
    for dx, dy in [(-8, 9), (0, 9), (8, 9), (-4, 16), (4, 16)]:
        rr = 3
        draw.ellipse((cx + dx - rr, cy + dy - rr, cx + dx + rr, cy + dy + rr),
                     fill=color)


def _icon_tornado(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                  color: Tuple[int, int, int]) -> None:
    """Tapering funnel (wide at top, narrowing to a point)."""
    widths  = [30, 22, 15, 9, 4]
    bar_h   = 5
    spacing = 4
    total_h = len(widths) * bar_h + (len(widths) - 1) * spacing
    y0 = cy - total_h // 2
    for i, w in enumerate(widths):
        y = y0 + i * (bar_h + spacing)
        x0 = cx - w // 2
        draw.rounded_rectangle((x0, y, x0 + w, y + bar_h), radius=2, fill=color)
    # Narrow tail below the funnel
    tail_y = y0 + total_h
    draw.line([(cx, tail_y), (cx, tail_y + 6)], fill=color, width=2)


_ICON_FN = {
    'wind':    _icon_wind,
    'hail':    _icon_hail,
    'tornado': _icon_tornado,
}


# ─── Info-panel section drawers ───────────────────────────────────────────────
def _draw_threats(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                  ix: int, iy: int, iw: int, bot: int,
                  ipaws_data: Optional[Dict]) -> int:
    """Draw graphical threat cards — one card per active hazard."""
    threat_data = (ipaws_data or {}).get('threat_data', {})
    if not threat_data:
        return iy

    # Collect present threats in display order
    active = [(k, threat_data[k]) for k in ('tornado', 'wind', 'hail')
              if threat_data.get(k)]
    if not active:
        return iy

    n       = len(active)
    gap     = 5
    card_w  = (iw - gap * (n - 1)) // n
    card_h  = 108
    # Reserve space for the section header (22px) + card height before
    # committing to drawing anything, so we never leave an orphan header.
    if iy + 22 + card_h > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'STORM THREATS')

    for i, (key, t) in enumerate(active):
        cx   = ix + i * (card_w + gap)
        cy   = iy
        ce_x = cx + card_w // 2   # card horizontal centre

        level   = t.get('level', 'none')
        lvl_clr = _THREAT_CLR.get(level, _THREAT_CLR['none'])

        # Card background: slight colour tint based on threat level
        bg = tuple(int(lvl_clr[j] * 0.18 + _CARD[j] * 0.82) for j in range(3))

        draw.rounded_rectangle((cx, cy, cx + card_w, cy + card_h),
                               radius=7, fill=bg,
                               outline=lvl_clr, width=1)

        # ── Icon (top section) ──────────────────────────────────────────────
        icon_fn = _ICON_FN.get(key)
        if icon_fn:
            icon_fn(draw, ce_x, cy + 28, lvl_clr)

        # ── Primary value (large number or short label) ─────────────────────
        if key == 'wind':
            val = t.get('gust', '')
            unit = t.get('gust_unit', 'MPH')
        elif key == 'hail':
            size = t.get('size', '')
            val  = f'{size}"' if size else ''
            unit = t.get('descriptor', '')
        else:  # tornado
            val  = t.get('display', '')
            unit = ''

        vfont = fonts['head']   # 18 pt bold
        vw    = _tw(vfont, val)
        draw.text((ce_x - vw // 2, cy + 52), val, font=vfont, fill=_TEXT)

        # ── Unit / descriptor ───────────────────────────────────────────────
        if unit:
            uw = _tw(fonts['tiny'], unit)
            draw.text((ce_x - uw // 2, cy + 73), unit,
                      font=fonts['tiny'], fill=_TEXT_SEC)

        # ── Threat level (coloured) ─────────────────────────────────────────
        disp = t.get('display', '') if key != 'tornado' else ''
        if disp and key in ('wind', 'hail'):
            dw = _tw(fonts['tiny'], disp)
            draw.text((ce_x - dw // 2, cy + 84), disp,
                      font=fonts['tiny'], fill=lvl_clr)

        # ── Category label at bottom ────────────────────────────────────────
        cat = key.upper()
        cw  = _tw(fonts['label'], cat)
        draw.text((ce_x - cw // 2, cy + 95), cat,
                  font=fonts['label'], fill=_TEXT_MUT)

    return iy + card_h + 6


def _draw_coverage(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                   ix: int, iy: int, iw: int, bot: int,
                   coverage_data: Dict, county_name: str) -> int:
    if not coverage_data:
        return iy

    # ── Decide what's worth showing ─────────────────────────────────────────
    # When the configured county is outside the affected polygon, county
    # coverage will be 0.0%.  Rendering a "0.0% (est.) of <County>" row with
    # an empty bar reads as a calculation bug; suppress the row in that
    # case.  Drop the whole section if neither the county nor any service
    # type has measurable overlap — there is nothing left to display.
    county = coverage_data.get('county', {}) or {}
    county_pct = float(county.get('coverage_percentage', 0) or 0)
    show_county_row = bool(county) and county_pct >= 0.05

    svc_parts: List[str] = []
    for stype, sdata in sorted(coverage_data.items()):
        if stype == 'county':
            continue
        affected = int(sdata.get('affected_boundaries', 0) or 0)
        total    = int(sdata.get('total_boundaries',    0) or 0)
        if total > 0 and affected > 0:
            svc_parts.append(f'{stype.title()}: {affected}/{total}')

    if not show_county_row and not svc_parts:
        return iy

    # Reserve section-header (22) + at least one row of content before
    # drawing anything — otherwise we'd leave an orphan "COVERAGE" title.
    if iy + 22 + 22 > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'COVERAGE')

    if show_county_row:
        est   = county.get('is_estimated', False)
        row_h = 32
        if iy + row_h <= bot:
            _card_row(draw, ix, iy, iw, row_h)

            # Percentage label
            tag  = ' (est.)' if est else ''
            lbl  = f'{county_pct:.1f}%{tag} of {county_name}'
            lbl  = _truncate(fonts['small'], lbl, iw - 16)
            draw.text((ix + 8, iy + 4), lbl, font=fonts['small'], fill=_TEXT)

            # Progress bar — empty track plus a fill clamped to a true
            # 0–100% width (no minimum-width fudge that would misrepresent
            # near-zero coverage as a visible sliver).
            bar_x, bar_y = ix + 8, iy + 21
            bar_w, bar_h = iw - 16, 6
            draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                                   radius=3, fill=(55, 65, 88))
            fill_w = int(bar_w * min(county_pct, 100) / 100)
            if fill_w > 0:
                draw.rounded_rectangle(
                    (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
                    radius=3, fill=_pct_bar_color(county_pct),
                )
            iy += row_h + 3

    if svc_parts and iy + 22 <= bot:
        _card_row(draw, ix, iy, iw, 22)
        svc_text = _truncate(fonts['tiny'], '  ·  '.join(svc_parts), iw - 14)
        draw.text((ix + 7, iy + (22 - _th(fonts['tiny'], svc_text)) // 2),
                  svc_text, font=fonts['tiny'], fill=_TEXT_SEC)
        iy += 24

    return iy + 6


def _draw_areas(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                ix: int, iy: int, iw: int, bot: int, alert: Any) -> int:
    area_desc = (getattr(alert, 'area_desc', '') or '').strip()
    if not area_desc or iy + 30 > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'AFFECTED AREAS')

    # Split on semicolons, clean up, display up to ~3 rows
    segments = [s.strip() for s in area_desc.split(';') if s.strip()]
    font = fonts['small']
    row_h = 21

    # Try to fit all segments on as few rows as possible
    current_line = ''
    for seg in segments:
        candidate = f'{current_line}; {seg}' if current_line else seg
        if _tw(font, candidate) <= iw - 14:
            current_line = candidate
        else:
            if current_line and iy + row_h <= bot:
                _card_row(draw, ix, iy, iw, row_h)
                draw.text((ix + 7, iy + (row_h - _th(font, current_line)) // 2),
                          current_line, font=font, fill=_TEXT)
                iy += row_h + 1
            current_line = seg

    if current_line and iy + row_h <= bot:
        _card_row(draw, ix, iy, iw, row_h)
        line = _truncate(font, current_line, iw - 14)
        draw.text((ix + 7, iy + (row_h - _th(font, line)) // 2),
                  line, font=font, fill=_TEXT)
        iy += row_h + 1

    return iy + 4


def _draw_compass_section(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                          ix: int, iy: int, iw: int, bot: int,
                          ipaws_data: Optional[Dict]) -> int:
    """Draw a circular compass rose with the storm motion arrow + speed/direction text."""
    storm = (ipaws_data or {}).get('storm_motion', {})
    if not storm:
        return iy

    toward_deg    = storm.get('toward_deg')
    direction_deg = storm.get('direction_deg')
    compass_toward = storm.get('compass_toward', '')
    compass_from   = storm.get('compass_from', storm.get('compass', ''))
    speed_mph      = storm.get('speed_mph', '')
    speed_kt       = storm.get('speed_kt', '')

    if toward_deg is None and not compass_toward and not speed_mph:
        return iy

    section_h = 88
    if iy + 22 + section_h + 6 > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'STORM MOTION')
    draw.rectangle((ix, iy, ix + iw, iy + section_h), fill=_CARD)

    # ── Compass rose ──────────────────────────────────────────────────────────
    r   = 30                   # ring radius
    ccx = ix + r + 16          # compass centre-x
    ccy = iy + section_h // 2  # compass centre-y

    ring_clr = _TEXT_MUT
    draw.ellipse((ccx - r, ccy - r, ccx + r, ccy + r), outline=ring_clr, width=2)

    # Cardinal ticks + labels
    for deg, lbl in [(0, 'N'), (90, 'E'), (180, 'S'), (270, 'W')]:
        ang = math.radians(deg)
        sx  =  math.sin(ang)
        sy  = -math.cos(ang)   # screen y grows downward
        # Tick mark
        draw.line([
            (ccx + int(sx * (r - 6)), ccy + int(sy * (r - 6))),
            (ccx + int(sx * r),       ccy + int(sy * r)),
        ], fill=ring_clr, width=2)
        # Label just outside the ring
        lx = ccx + int(sx * (r + 9))
        ly = ccy + int(sy * (r + 9))
        draw.text((lx - _tw(fonts['tiny'], lbl) // 2,
                   ly - _th(fonts['tiny'], lbl) // 2),
                  lbl, font=fonts['tiny'], fill=ring_clr)

    # Intermediate ticks (45°)
    for deg in [45, 135, 225, 315]:
        ang = math.radians(deg)
        sx, sy = math.sin(ang), -math.cos(ang)
        draw.line([
            (ccx + int(sx * (r - 4)), ccy + int(sy * (r - 4))),
            (ccx + int(sx * r),       ccy + int(sy * r)),
        ], fill=ring_clr, width=1)

    # Directional arrow
    if toward_deg is not None:
        ang = math.radians(toward_deg)
        dx  =  math.sin(ang)
        dy  = -math.cos(ang)

        tip_x = ccx + int(dx * (r - 7))
        tip_y = ccy + int(dy * (r - 7))
        tail_x = ccx - int(dx * int(r * 0.38))
        tail_y = ccy - int(dy * int(r * 0.38))

        draw.line([(tail_x, tail_y), (tip_x, tip_y)], fill=alr_clr, width=3)

        w_ang = 0.45
        hw    = 7
        lw_x = tip_x - int((dx * math.cos( w_ang) - dy * math.sin( w_ang)) * hw)
        lw_y = tip_y - int((dy * math.cos( w_ang) + dx * math.sin( w_ang)) * hw)
        rw_x = tip_x - int((dx * math.cos(-w_ang) - dy * math.sin(-w_ang)) * hw)
        rw_y = tip_y - int((dy * math.cos(-w_ang) + dx * math.sin(-w_ang)) * hw)
        draw.polygon([(tip_x, tip_y), (lw_x, lw_y), (rw_x, rw_y)], fill=alr_clr)

    # Centre dot
    draw.ellipse((ccx - 3, ccy - 3, ccx + 3, ccy + 3), fill=ring_clr)

    # ── Text block to the right of the compass ────────────────────────────────
    tx   = ccx + r + 18
    tw_  = iw - (tx - ix) - 8
    ty   = iy + 10
    lh   = 17

    if compass_toward:
        hstr = f'Heading {compass_toward}'
        if toward_deg is not None:
            hstr += f' ({int(toward_deg)}\u00b0)'
        draw.text((tx, ty), hstr, font=fonts['bold'], fill=_TEXT)
        ty += lh + 2

    if compass_from:
        fstr = f'From {compass_from}'
        if direction_deg is not None:
            fstr += f' ({int(direction_deg)}\u00b0)'
        draw.text((tx, ty), fstr, font=fonts['small'], fill=_TEXT_SEC)
        ty += lh

    if speed_mph:
        sstr = f'{speed_mph} MPH'
        if speed_kt:
            sstr += f'  ({speed_kt} kt)'
        draw.text((tx, ty), sstr, font=fonts['bold'], fill=_TEXT)
        ty += lh + 2

    # Storm position (newest track point)
    track = storm.get('track', [])
    if track:
        try:
            lat, lon = float(track[-1][0]), float(track[-1][1])
            pstr = f'Position: {lat:.2f}, {lon:.2f}'
            draw.text((tx, ty), _truncate(fonts['tiny'], pstr, tw_),
                      font=fonts['tiny'], fill=_TEXT_MUT)
        except (TypeError, IndexError, ValueError):
            pass

    return iy + section_h + 6


def _draw_nws_headline(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                       ix: int, iy: int, iw: int, bot: int,
                       alert: Any, ipaws_data: Optional[Dict]) -> int:
    """Render the NWS operational headline (ALL-CAPS quote block).

    Falls back to alert.headline when nws_headline is absent.
    The alert.description is intentionally omitted — it's too long to
    truncate meaningfully in a social-media image.
    """
    nws_head = (ipaws_data or {}).get('nws_headline', '').strip()
    pub_head = (getattr(alert, 'headline', '') or '').strip()
    text     = nws_head or pub_head

    if not text or iy + 30 > bot:
        return iy

    # NWS-style headlines are often shouted; humanise before rendering.
    text = _humanize_caps_text(text)

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'HEADLINE')

    # Word-wrap (leave 10 px for the quote bar on the left)
    font  = fonts['small']
    max_w = iw - 18
    words = text.split()
    lines: List[str] = []
    line  = ''
    for word in words:
        candidate = (line + ' ' + word).strip()
        if _tw(font, candidate) <= max_w:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)

    row_h = 19
    for ltext in lines:
        if iy + row_h > bot:
            break
        _card_row(draw, ix, iy, iw, row_h)
        # Coloured quote bar on the left edge
        draw.rectangle((ix, iy, ix + 3, iy + row_h), fill=alr_clr)
        draw.text((ix + 10, iy + (row_h - _th(font, ltext)) // 2),
                  ltext, font=font, fill=_TEXT)
        iy += row_h + 1

    return iy + 4


def _wrap_text(font: ImageFont.FreeTypeFont, text: str,
               max_w: int, max_lines: int = 8) -> List[str]:
    """Word-wrap *text* into lines that fit within *max_w* pixels."""
    words = text.split()
    lines: List[str] = []
    line = ''
    for word in words:
        candidate = (line + ' ' + word).strip()
        if _tw(font, candidate) <= max_w:
            line = candidate
        else:
            if line:
                lines.append(line)
                if len(lines) >= max_lines:
                    # Truncate the last line with ellipsis
                    lines[-1] = _truncate(font, lines[-1], max_w)
                    return lines
            line = word
    if line:
        if len(lines) >= max_lines:
            lines[-1] = _truncate(font, lines[-1] + ' ' + line, max_w)
        else:
            lines.append(line)
    return lines


def _draw_description(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                      ix: int, iy: int, iw: int, bot: int,
                      alert: Any) -> int:
    """Render the alert description text (word-wrapped, space-limited)."""
    desc = (getattr(alert, 'description', '') or '').strip()
    if not desc or iy + 30 > bot:
        return iy

    # Clean up NWS description formatting: collapse multiple whitespace,
    # strip leading asterisks/bullets, normalise newlines to spaces.
    desc = re.sub(r'\s*\n\s*', ' ', desc)
    desc = re.sub(r'\s{2,}', ' ', desc)
    desc = re.sub(r'^\*\s*', '', desc)
    desc = desc.strip()

    if not desc:
        return iy

    # De-shout NWS text — bodies of all-caps are noticeably slower to read.
    desc = _humanize_caps_text(desc)

    font = fonts['small']
    row_h = 18
    # Reserve the 22px section header + at least one row before committing.
    if iy + 22 + row_h > bot:
        return iy

    iy = _section_header(draw, fonts, alr_clr, ix, iy, iw, 'DESCRIPTION')

    max_w = iw - 14
    # Fill all remaining vertical space rather than capping at an arbitrary
    # line count — long descriptions previously ended mid-sentence because
    # the cap was 6 lines regardless of how much room was left.
    avail_lines = max(1, (bot - iy) // (row_h + 1))
    lines = _wrap_text(font, desc, max_w, max_lines=avail_lines)

    for ltext in lines:
        if iy + row_h > bot:
            break
        _card_row(draw, ix, iy, iw, row_h)
        draw.text((ix + 7, iy + (row_h - _th(font, ltext)) // 2),
                  ltext, font=font, fill=_TEXT)
        iy += row_h + 1

    return iy + 4


_INSTR_ACCENT = (255, 193, 7)  # warning-yellow accent bar


def _draw_instruction(draw: ImageDraw.ImageDraw, fonts: Dict, alr_clr: Tuple,
                      ix: int, iy: int, iw: int, bot: int,
                      alert: Any) -> int:
    """Render safety guidance with a stronger visual treatment.

    The CAP ``instruction`` field is the one thing on a share card a
    reader can act on — "move to an interior room", "shelter in
    place", "evacuate if instructed" — so it gets a warning-yellow
    section header (visually distinct from the neutral event-coloured
    headers used for HEADLINE / DESCRIPTION) plus a thicker accent bar
    on each row.  The header reads "ACTION" instead of "INSTRUCTIONS"
    because "ACTION" is shorter and imperative — it tells the reader
    *what this section is for*, not just *what's in it*.
    """
    instr = (getattr(alert, 'instruction', '') or '').strip()
    if not instr or iy + 30 > bot:
        return iy

    instr = re.sub(r'\s*\n\s*', ' ', instr)
    instr = re.sub(r'\s{2,}', ' ', instr)
    instr = instr.strip()

    if not instr:
        return iy

    instr = _humanize_caps_text(instr)

    font = fonts['small']
    row_h = 18
    if iy + 22 + row_h > bot:
        return iy

    # Warning-coloured section header so the action band reads as
    # distinct from the neutral headline / description sections.  Using
    # a deeply-darkened amber preserves WCAG-style contrast against the
    # white label text.
    iy = _section_header(
        draw, fonts, alr_clr, ix, iy, iw, 'ACTION',
        bg=_darken(_INSTR_ACCENT, 0.55),
    )

    accent_w = 4  # was 3 — thicker bar reads better at thumbnail size
    max_w = iw - 12 - accent_w
    # Fill remaining vertical space instead of capping at 4 lines.
    avail_lines = max(1, (bot - iy) // (row_h + 1))
    lines = _wrap_text(font, instr, max_w, max_lines=avail_lines)

    for ltext in lines:
        if iy + row_h > bot:
            break
        _card_row(draw, ix, iy, iw, row_h)
        # Warning-yellow accent bar on the left edge.
        draw.rectangle((ix, iy, ix + accent_w, iy + row_h), fill=_INSTR_ACCENT)
        draw.text((ix + accent_w + 7, iy + (row_h - _th(font, ltext)) // 2),
                  ltext, font=font, fill=_TEXT)
        iy += row_h + 1

    return iy + 4


__all__ = ['generate_alert_image']
