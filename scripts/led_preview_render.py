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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from scripts.dotmatrix_preview_font import CELL_H, CELL_W, blit_text
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


def _normalise_led_lines(lines: Optional[Sequence[Any]]) -> List[str]:
    """Coerce LED render output (strings or per-line dicts) to plain text rows."""
    out: List[str] = []
    for line in (lines or [])[:4]:
        if isinstance(line, dict):
            out.append(str(line.get('text', '')))
        elif line is None:
            out.append('')
        else:
            out.append(str(line))
    while len(out) < 4:
        out.append('')
    return out


def _render_led_glow(
    gw: int,
    gh: int,
    lit: Callable[[int, int], bool],
    on_rgb: Tuple[int, int, int],
    scale: int,
) -> Optional[str]:
    """Shared round-dot-plus-glow rasterizer for the LED sign preview.

    ``lit(x, y)`` reports whether the pixel at grid position (x, y) is on;
    render_led_preview() and render_led_elements_preview() differ only in
    where their pixels come from (a 0/1 text grid vs. a PIL image), so the
    actual dot/glow drawing lives here once instead of twice.
    """
    W, H = gw * scale, gh * scale
    radius = scale * 0.40
    base = Image.new('RGB', (W, H), _LED_BG)
    draw = ImageDraw.Draw(base)
    glow = Image.new('RGB', (W, H), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    dim_glow = tuple(int(v * 0.55) for v in on_rgb)
    for y in range(gh):
        for x in range(gw):
            cx = x * scale + scale / 2
            cy = y * scale + scale / 2
            if lit(x, y):
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
) -> Optional[str]:
    """Render the LED Network Sign content as a glowing dot-matrix PNG.

    Returns a ``data:image/png;base64,...`` URI, or ``None`` if Pillow is
    unavailable or rendering fails.
    """
    if not PIL_AVAILABLE:
        return None
    try:
        on_rgb = _LED_COLORS.get(str(color or 'AMBER').upper(), _LED_COLORS['AMBER'])
        text_lines = _normalise_led_lines(lines)

        gw, gh = cols * CELL_W, rows * CELL_H
        grid = [[0] * gw for _ in range(gh)]
        for i, line in enumerate(text_lines[:rows]):
            blit_text(grid, 0, i * CELL_H, line[:cols])

        return _render_led_glow(gw, gh, lambda x, y: bool(grid[y][x]), on_rgb, scale)
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

        return _render_led_glow(gw, gh, lambda x, y: bool(pixels[x, y]), on_rgb, scale)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("LED elements preview render failed: %s", exc)
        return None
