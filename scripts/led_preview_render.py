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

"""Server-side preview image renderer for the LED Network Sign.

Split out of services/displays/preview_render.py (which re-exports these
functions) to keep that module under the repo's file-size guideline once it
grew a third display type. All functions are best-effort: if Pillow is
unavailable or anything goes wrong they return ``None`` and the page falls
back to a simple idle message.

LED -- Alpha 9120C: 4 lines x 20 chars, dot-matrix, in the M-Protocol colour
the message was sent with.
"""

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from scripts.dotmatrix_preview_font import blit_text_scaled, cell_size
from scripts.preview_render_common import (
    Image,
    ImageChops,
    ImageDraw,
    ImageFilter,
    PIL_AVAILABLE,
    encode_preview_png,
)

logger = logging.getLogger(__name__)

# M-Protocol colour name -> RGB for an illuminated LED.  Mirrors the Alpha
# 9120C ``Color`` enum.  Effects that aren't a single solid colour fall back to
# amber, the sign's default.
_LED_COLORS: Dict[str, Tuple[int, int, int]] = {
    'RED': (255, 40, 40),
    'GREEN': (50, 255, 80),
    'AMBER': (255, 176, 0),
    'DIM_RED': (150, 28, 28),
    'DIM_GREEN': (36, 150, 56),
    'BROWN': (150, 96, 28),
    'ORANGE': (255, 110, 0),
    'YELLOW': (255, 230, 40),
    'RAINBOW_1': (255, 176, 0),
    'RAINBOW_2': (255, 176, 0),
    'COLOR_MIX': (255, 176, 0),
    'AUTO_COLOR': (255, 176, 0),
}

_LED_BG = (10, 9, 8)
_LED_OFF = (26, 22, 16)

_FONT_DOT_RE = re.compile(r'(\d+)\s*x\s*(\d+)', re.IGNORECASE)


def _font_dot_scale(font_name: Optional[str]) -> Tuple[int, int]:
    """Best-effort (scale_x, scale_y) for an Alpha ``Font`` enum name, e.g.
    ``FONT_7x9`` -> scale the base 5x7 glyph up to approximate a 7-wide,
    9-tall cell. See ``blit_text_scaled``'s docstring for the caveat this
    approximates the declared name, not verified sign firmware glyph data.
    """
    match = _FONT_DOT_RE.search(str(font_name or ''))
    if not match:
        return 1, 1
    target_w, target_h = int(match.group(1)), int(match.group(2))
    return max(1, round(target_w / 5)), max(1, round(target_h / 7))


def _normalise_led_rows(
    lines: Optional[Sequence[Any]],
    rows: int,
    default_font: str,
    default_color: str,
) -> List[Tuple[str, str, str]]:
    """Coerce LED render output (strings or per-line dicts) to
    ``(text, font, color)`` rows, falling back to the message-level
    font/color for plain-string lines or lines that don't override them.
    """
    out: List[Tuple[str, str, str]] = []
    for line in (lines or [])[:rows]:
        if isinstance(line, dict):
            out.append((
                str(line.get('text', '')),
                str(line.get('font') or default_font),
                str(line.get('color') or default_color),
            ))
        elif line is None:
            out.append(('', default_font, default_color))
        else:
            out.append((str(line), default_font, default_color))
    while len(out) < rows:
        out.append(('', default_font, default_color))
    return out


def _render_led_glow(
    gw: int,
    gh: int,
    color_at: Callable[[int, int], Optional[Tuple[int, int, int]]],
    scale: int,
) -> Optional[str]:
    """Shared round-dot-plus-glow rasterizer for the LED sign preview.

    ``color_at(x, y)`` returns the lit RGB colour for grid position (x, y),
    or ``None`` if that dot is off. render_led_preview() and
    render_led_elements_preview() differ only in where their pixels (and,
    for scrolling text, per-line colour) come from, so the actual dot/glow
    drawing lives here once instead of twice.
    """
    W, H = gw * scale, gh * scale
    radius = scale * 0.40
    base = Image.new('RGB', (W, H), _LED_BG)
    draw = ImageDraw.Draw(base)
    glow = Image.new('RGB', (W, H), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for y in range(gh):
        for x in range(gw):
            cx = x * scale + scale / 2
            cy = y * scale + scale / 2
            on_rgb = color_at(x, y)
            if on_rgb is not None:
                dim_glow = tuple(int(v * 0.55) for v in on_rgb)
                gdraw.ellipse(
                    [cx - radius * 2, cy - radius * 2, cx + radius * 2, cy + radius * 2],
                    fill=dim_glow,
                )
                draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=on_rgb)
            else:
                draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=_LED_OFF)
    glow = glow.filter(ImageFilter.GaussianBlur(scale * 0.45))
    return encode_preview_png(ImageChops.screen(base, glow))


def render_led_preview(
    lines: Optional[Sequence[Any]],
    color: str = 'AMBER',
    cols: int = 20,
    rows: int = 4,
    scale: int = 8,
    font: str = 'FONT_7x9',
) -> Optional[str]:
    """Render the LED Network Sign content as a glowing dot-matrix PNG.

    ``font`` is the message-level Alpha ``Font`` enum name (``lines`` may
    override it per-row, same as ``color``); the rendered dot size scales
    with it -- see ``blit_text_scaled`` -- so picking a larger font actually
    looks larger in the preview instead of every font rendering identically.
    Each row keeps its own scaled height, so the overall image grows with
    the fonts actually selected rather than a fixed 4-line canvas; that's
    deliberate -- it's an honest signal that e.g. four rows of FONT_32x16
    wouldn't fit a compact sign, not a rendering bug.

    Returns a ``data:image/png;base64,...`` URI, or ``None`` if Pillow is
    unavailable or rendering fails.
    """
    if not PIL_AVAILABLE:
        return None
    try:
        default_font = str(font or 'FONT_7x9')
        default_color = str(color or 'AMBER')
        row_data = _normalise_led_rows(lines, rows, default_font, default_color)

        row_specs = []  # (text, scale_x, scale_y, cell_w, cell_h, rgb)
        max_cell_w = 0
        total_h = 0
        for text, row_font, row_color in row_data:
            sx, sy = _font_dot_scale(row_font)
            cell_w, cell_h = cell_size(sx, sy)
            rgb = _LED_COLORS.get(row_color.upper(), _LED_COLORS['AMBER'])
            row_specs.append((text[:cols], sx, sy, cell_w, cell_h, rgb))
            max_cell_w = max(max_cell_w, cell_w)
            total_h += cell_h

        gw = max(1, cols * max_cell_w)
        gh = max(1, total_h)
        grid = [[0] * gw for _ in range(gh)]
        color_grid: List[List[Optional[Tuple[int, int, int]]]] = [[None] * gw for _ in range(gh)]

        y_offset = 0
        for text, sx, sy, cell_w, cell_h, rgb in row_specs:
            blit_text_scaled(grid, 0, y_offset, text, sx, sy)
            for yy in range(y_offset, min(gh, y_offset + cell_h)):
                row = grid[yy]
                crow = color_grid[yy]
                for xx in range(gw):
                    if row[xx]:
                        crow[xx] = rgb
            y_offset += cell_h

        return _render_led_glow(gw, gh, lambda x, y: color_grid[y][x], scale)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("LED preview render failed: %s", exc)
        return None


def render_led_elements_preview(
    elements: Optional[Sequence[Dict[str, Any]]],
    color: str = 'AMBER',
    scale: int = 8,
) -> Optional[str]:
    """Render a resolved graphics-mode LED element list to a glowing
    dot-matrix PNG.

    Calls scripts.led_sign_controller.render_led_elements() -- the exact
    same pure function Alpha9120CController.render_frame() uses to build
    the real hardware bitmap -- then applies the same round-dot-plus-glow
    look render_led_preview() uses for scrolling text, but at the sign's
    native 160x16 resolution (one drawn dot per physical LED) instead of
    the coarser per-character cell grid text messages use.
    """
    if not PIL_AVAILABLE or not elements:
        return None
    try:
        from scripts.led_sign_controller import render_led_elements

        on_rgb = _LED_COLORS.get(str(color or 'AMBER').upper(), _LED_COLORS['AMBER'])
        mono = render_led_elements(list(elements))
        gw, gh = mono.size
        pixels = mono.load()

        return _render_led_glow(gw, gh, lambda x, y: on_rgb if pixels[x, y] else None, scale)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("LED elements preview render failed: %s", exc)
        return None
