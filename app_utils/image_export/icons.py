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

"""Vector icons for the threat cards."""

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
