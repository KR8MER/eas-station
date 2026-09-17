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

"""Compact 5x7 dot-matrix font shared by the LED and VFD preview renderers.

Uppercase letters, digits and the punctuation that shows up on EAS displays.
Each glyph is 7 rows of 5 bits, modelled on the classic 5x7 LED/VFD cell.
Split out of services/displays/preview_render.py alongside the other preview
renderers -- see scripts/led_preview_render.py and scripts/vfd_preview_render.py.
"""

from typing import Dict, List

FONT_5x7: Dict[str, List[str]] = {
    ' ': ["00000"] * 7,
    'A': ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    'B': ["11110", "10001", "11110", "10001", "10001", "10001", "11110"],
    'C': ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    'D': ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    'E': ["11111", "10000", "11110", "10000", "10000", "10000", "11111"],
    'F': ["11111", "10000", "11110", "10000", "10000", "10000", "10000"],
    'G': ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    'H': ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    'I': ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    'J': ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    'K': ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    'L': ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    'M': ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    'N': ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    'O': ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    'P': ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    'Q': ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    'R': ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    'S': ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    'T': ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    'U': ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    'V': ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    'W': ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    'X': ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    'Y': ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    'Z': ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    '0': ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    '1': ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    '2': ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    '3': ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    '4': ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    '5': ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    '6': ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    '7': ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    '8': ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    '9': ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ':': ["00000", "00100", "00100", "00000", "00100", "00100", "00000"],
    '/': ["00001", "00001", "00010", "00100", "01000", "10000", "10000"],
    '-': ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    '.': ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ',': ["00000", "00000", "00000", "00000", "01100", "00100", "01000"],
    '!': ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    '?': ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    '%': ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    '*': ["00000", "00100", "10101", "01110", "10101", "00100", "00000"],
    '#': ["01010", "01010", "11111", "01010", "11111", "01010", "01010"],
    '+': ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
    "'": ["00100", "00100", "01000", "00000", "00000", "00000", "00000"],
    '"': ["01010", "01010", "01010", "00000", "00000", "00000", "00000"],
    '(': ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ')': ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    '\xb0': ["01100", "10010", "10010", "01100", "00000", "00000", "00000"],
}

# Glyph cell metrics: 5 pixels wide + 1 spacing, 7 tall + 1 spacing.
CELL_W = 6
CELL_H = 8


def glyph(ch: str) -> List[str]:
    return FONT_5x7.get(ch.upper(), FONT_5x7.get(ch, FONT_5x7[' ']))


def blit_text(grid: List[List[int]], x: int, y: int, text: str) -> None:
    """Stamp ``text`` into a 0/1 pixel ``grid`` at top-left pixel (x, y)."""
    blit_text_scaled(grid, x, y, text)


def cell_size(scale_x: int = 1, scale_y: int = 1) -> "tuple[int, int]":
    """Cell dimensions (px) for text blitted at the given dot-scale factor."""
    scale_x = max(1, int(scale_x))
    scale_y = max(1, int(scale_y))
    return 5 * scale_x + scale_x, 7 * scale_y + scale_y


def blit_text_scaled(
    grid: List[List[int]], x: int, y: int, text: str, scale_x: int = 1, scale_y: int = 1
) -> "tuple[int, int]":
    """Like ``blit_text``, but replicates each dot of the base 5x7 glyph into
    a ``scale_x`` x ``scale_y`` block, approximating a larger/smaller LED
    font from the same glyph shapes. Returns the (width, height) of one
    character cell at this scale, i.e. what ``blit_text``'s fixed
    ``CELL_W``/``CELL_H`` are for scale (1, 1).

    This is a best-effort size approximation, not the sign firmware's actual
    glyph bitmaps -- see docs/reference/protocols/ALPHA_M_PROTOCOL.md §3.2,
    which found some Alpha ``Font`` enum names don't match what byte they
    really select on the wire. It's the best available signal without
    hardware to bench-test against.
    """
    scale_x = max(1, int(scale_x))
    scale_y = max(1, int(scale_y))
    h = len(grid)
    w = len(grid[0]) if h else 0
    cw, ch_ = cell_size(scale_x, scale_y)
    cx = x
    for ch in str(text):
        g = glyph(ch)
        for ry in range(7):
            row = g[ry]
            for rx in range(5):
                if row[rx] != '1':
                    continue
                for dy in range(scale_y):
                    py = y + ry * scale_y + dy
                    if py < 0 or py >= h:
                        continue
                    for dx in range(scale_x):
                        px = cx + rx * scale_x + dx
                        if 0 <= px < w:
                            grid[py][px] = 1
        cx += cw
    return cw, ch_
