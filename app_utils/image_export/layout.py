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

"""Canvas layout presets for each social-platform aspect ratio.

Each preset bundles the canvas dimensions plus the rectangles for the chrome
(header / footer) and the two content slots (map + info panel), so a new
aspect ratio is a new set of numbers rather than new drawing code.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


# ─── Canvas layouts ─────────────────────────────────────────────────────────
# The share card renders into one of several preset canvases that target the
# common social-platform aspect ratios.  Each preset bundles the canvas
# dimensions plus the rectangles for the chrome (header / footer) and the
# two content slots (map + info panel).  The info-panel drawers (threats,
# headline, areas, description, instructions, …) all operate on a generic
# rectangle, so a new layout is just a different set of numbers — no new
# drawing code per aspect ratio.

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
    # Title font size (px).  Default 30 matches the original landscape
    # design; portrait / story preset values bump this so the headline
    # still reads near-fullscreen on a phone.
    title_size: int = 30


# Facebook / Twitter / LinkedIn open-graph cards — horizontal split with
# the map on the left and the text panel on the right. The map is the
# dominant element (75% of width) with a narrow broadcast-style callout
# column alongside it -- panels.py's info-panel drawers switch to a
# compact vertical stack (damage callout / EXPIRES / stat boxes / WHAT TO
# DO) below INFO_NARROW_MAX_W rather than the wider gauge-card layout,
# which doesn't fit a column this narrow.
_LAYOUT_LANDSCAPE = _Layout(
    width=1200, height=630,
    header_h=90, footer_h=50,
    map_rect=(0, 90, 900, 490),
    info_rect=(908, 98, 284, 482),
    header_scrim_w=560,
    show_vertical_divider=True,
    map_corner_r=14,
    title_size=30,
)

# Instagram / Mastodon / generic square feed card — stacked layout with
# header → map → info → footer down the centre line.  Header gets a
# slightly taller bar + bigger title to balance the larger canvas.
_LAYOUT_SQUARE = _Layout(
    width=1080, height=1080,
    header_h=118, footer_h=60,
    map_rect=(0, 118, 1080, 540),
    info_rect=(16, 666, 1048, 354),
    header_scrim_w=600,
    map_corner_r=0,
    title_size=36,
)

# Instagram portrait (4:5) — taller info panel, slightly shorter map.
_LAYOUT_PORTRAIT = _Layout(
    width=1080, height=1350,
    header_h=125, footer_h=60,
    map_rect=(0, 125, 1080, 540),
    info_rect=(16, 673, 1048, 612),
    header_scrim_w=600,
    map_corner_r=0,
    title_size=38,
)

# Instagram / TikTok / Snapchat Stories & Reels (9:16) — phone-first
# vertical layout with a tall info panel for longer descriptions.  Title
# is roughly 60% larger than landscape so the headline still reads at
# arm's-length on a phone, where Stories are typically viewed.
_LAYOUT_STORY = _Layout(
    width=1080, height=1920,
    header_h=160, footer_h=70,
    map_rect=(0, 160, 1080, 800),
    info_rect=(16, 970, 1048, 880),
    header_scrim_w=620,
    map_corner_r=0,
    title_size=48,
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

# Below this info-panel width, render.py switches from the wide gauge-card
# info-panel stack to the compact broadcast-style column (damage callout,
# EXPIRES block, stacked stat boxes, one-line motion readout, WHAT TO DO).
# Keyed off actual geometry rather than aspect-ratio name so any future
# narrow layout gets the same treatment automatically.
INFO_NARROW_MAX_W = 400

# Corner radius used for the outer canvas and inner panels — anything ≥ 10
# rounds enough to read as "designed" instead of "screenshot" on a feed.
CORNER_R    = 22
MAP_CORNER_R    = 14
CARD_CORNER_R   = 6
