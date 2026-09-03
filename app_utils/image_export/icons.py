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

"""Vector icons for the threat cards and info-panel section headers."""

from typing import Tuple

from PIL import ImageDraw


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


# ─── Section-header icons ──────────────────────────────────────────────────
# Small (~12px) glyphs drawn next to a section title -- kept to 2-3 draw
# calls each so they stay crisp at this size instead of turning to mush.
def _icon_flag(draw: ImageDraw.ImageDraw, cx: int, cy: int,
               color: Tuple[int, int, int]) -> None:
    """Small pennant -- marks the headline as the featured line."""
    draw.line([(cx - 5, cy - 6), (cx - 5, cy + 6)], fill=color, width=2)
    draw.polygon([(cx - 4, cy - 5), (cx + 5, cy - 1), (cx - 4, cy + 3)], fill=color)


def _icon_pin(draw: ImageDraw.ImageDraw, cx: int, cy: int,
              color: Tuple[int, int, int]) -> None:
    """Map pin -- teardrop marking a place, for affected areas."""
    r = 4
    draw.ellipse((cx - r, cy - r - 2, cx + r, cy + r - 2), fill=color)
    draw.polygon([(cx - 3, cy + 1), (cx + 3, cy + 1), (cx, cy + 6)], fill=color)


def _icon_lines(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                color: Tuple[int, int, int]) -> None:
    """Three horizontal bars -- a paragraph glyph, for prose sections."""
    for i, w in enumerate((11, 11, 7)):
        y = cy - 5 + i * 4
        draw.line([(cx - w // 2, y), (cx + w // 2, y)], fill=color, width=2)


def _icon_alert_triangle(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                         color: Tuple[int, int, int]) -> None:
    """Exclamation triangle -- storm threats."""
    draw.polygon([(cx, cy - 6), (cx - 6, cy + 5), (cx + 6, cy + 5)],
                 outline=color, width=2)
    draw.line([(cx, cy - 1), (cx, cy + 1)], fill=color, width=2)
    draw.ellipse((cx - 1, cy + 3, cx + 1, cy + 5), fill=color)


def _icon_ring(draw: ImageDraw.ImageDraw, cx: int, cy: int,
              color: Tuple[int, int, int]) -> None:
    """Partial ring -- a coverage/percentage glyph."""
    r = 5
    draw.arc((cx - r, cy - r, cx + r, cy + r), start=-90, end=190,
             fill=color, width=2)


def _icon_needle(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                 color: Tuple[int, int, int]) -> None:
    """Compass needle -- storm motion."""
    draw.polygon([(cx, cy - 6), (cx - 3, cy + 1), (cx + 3, cy + 1)], fill=color)
    draw.line([(cx, cy + 1), (cx, cy + 6)], fill=color, width=2)


def _icon_bolt(draw: ImageDraw.ImageDraw, cx: int, cy: int,
              color: Tuple[int, int, int]) -> None:
    """Lightning bolt -- the action/what-to-do band."""
    draw.polygon([
        (cx + 2, cy - 6), (cx - 4, cy + 1), (cx - 1, cy + 1),
        (cx - 2, cy + 6), (cx + 4, cy - 1), (cx + 1, cy - 1),
    ], fill=color)


# Keyed by the exact section title string _section_header() is called with
# (drawing.py) -- new sections silently render with no icon, which is a
# safe default, not a broken one.
_SECTION_ICON_FN = {
    'HEADLINE':       _icon_flag,
    'AFFECTED AREAS': _icon_pin,
    'DESCRIPTION':    _icon_lines,
    'STORM THREATS':  _icon_alert_triangle,
    'COVERAGE':       _icon_ring,
    'STORM MOTION':   _icon_needle,
    'WHAT TO DO':     _icon_bolt,
}
