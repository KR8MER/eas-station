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

"""Server-side preview image renderer for the VFD.

Split out of services/displays/preview_render.py (which re-exports these
functions) to keep that module under the repo's file-size guideline once it
grew a third display type. All functions are best-effort: if Pillow is
unavailable or anything goes wrong they return ``None`` and the page falls
back to a simple idle message.

VFD -- Noritake GU140x32F-7000B: 140x32 graphical VFD with the characteristic
blue-green (CIG phosphor) glow on dark glass. Rendered from the same
draw-command list that drives the panel.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence

from scripts.dotmatrix_preview_font import CELL_H, CELL_W, blit_text
from scripts.preview_render_common import (
    Image,
    ImageChops,
    ImageDraw,
    ImageFilter,
    ImageOps,
    PIL_AVAILABLE,
    encode_preview_png,
)

logger = logging.getLogger(__name__)

# Noritake CIG blue-green phosphor.
_VFD_ON = (108, 236, 214)
_VFD_BG = (2, 16, 14)


def _vfd_grid_from_commands(commands: Sequence[Dict[str, Any]], width: int, height: int) -> List[List[int]]:
    """Execute the VFD draw-command list onto a 0/1 pixel grid."""
    grid = [[0] * width for _ in range(height)]

    def set_px(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            grid[y][x] = 1

    def line(x1: int, y1: int, x2: int, y2: int) -> None:
        # Integer Bresenham so diagonal dividers render correctly.
        dx = abs(x2 - x1)
        dy = -abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx + dy
        x, y = x1, y1
        while True:
            set_px(x, y)
            if x == x2 and y == y2:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    for cmd in commands or []:
        ctype = cmd.get('type')
        if ctype == 'clear':
            grid = [[0] * width for _ in range(height)]
        elif ctype == 'text':
            blit_text(grid, int(cmd.get('x', 0)), int(cmd.get('y', 0)), str(cmd.get('text', '')))
        elif ctype == 'line':
            line(int(cmd.get('x1', 0)), int(cmd.get('y1', 0)), int(cmd.get('x2', 0)), int(cmd.get('y2', 0)))
        elif ctype == 'rectangle':
            x1 = int(cmd.get('x1', 0)); y1 = int(cmd.get('y1', 0))
            x2 = int(cmd.get('x2', 0)); y2 = int(cmd.get('y2', 0))
            if cmd.get('filled'):
                for yy in range(min(y1, y2), max(y1, y2) + 1):
                    for xx in range(min(x1, x2), max(x1, x2) + 1):
                        set_px(xx, yy)
            else:
                line(x1, y1, x2, y1)
                line(x1, y2, x2, y2)
                line(x1, y1, x1, y2)
                line(x2, y1, x2, y2)
    return grid


def _render_vfd_grid(grid: List[List[int]], width: int, height: int, scale: int = 9) -> Optional[str]:
    if not PIL_AVAILABLE:
        return None
    try:
        W, H = width * scale, height * scale
        base = Image.new('RGB', (W, H), _VFD_BG)
        draw = ImageDraw.Draw(base)
        pad = max(0.0, scale * 0.06)
        for y in range(height):
            for x in range(width):
                if grid[y][x]:
                    x0 = x * scale + pad
                    y0 = y * scale + pad
                    draw.rectangle([x0, y0, x0 + scale - 2 * pad, y0 + scale - 2 * pad], fill=_VFD_ON)
        glow = base.filter(ImageFilter.GaussianBlur(scale * 0.55))
        glow = Image.eval(glow, lambda v: int(v * 0.8))
        return encode_preview_png(ImageChops.screen(base, glow))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("VFD preview render failed: %s", exc)
        return None


def render_vfd_preview(
    commands: Optional[Sequence[Dict[str, Any]]],
    width: int = 140,
    height: int = 32,
    scale: int = 9,
) -> Optional[str]:
    """Render VFD draw-commands to a blue-green VFD PNG (data URI), or None.

    Legacy path for the old per-primitive command shape. Screens rendered
    through scripts.vfd_controller.render_vfd_elements() (icons, gauges,
    compass, multi-value bar charts) use render_vfd_elements_preview()
    instead, below.
    """
    if not PIL_AVAILABLE:
        return None
    try:
        grid = _vfd_grid_from_commands(commands or [], width, height)
        return _render_vfd_grid(grid, width, height, scale)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("VFD preview render failed: %s", exc)
        return None


def render_vfd_elements_preview(
    elements: Optional[Sequence[Dict[str, Any]]],
    width: int = 140,
    height: int = 32,
    scale: int = 9,
) -> Optional[str]:
    """Render a resolved VFD element list to a blue-green VFD PNG.

    Calls scripts.vfd_controller.render_vfd_elements() -- the exact same
    pure function NoritakeVFDController.render_frame() uses to build the
    real hardware bitmap -- so the preview can never drift from what the
    physical panel is actually showing (the old command-grid path
    reimplemented drawing logic a second time; this one doesn't).
    """
    if not PIL_AVAILABLE or not elements:
        return None
    try:
        from scripts.vfd_controller import render_vfd_elements

        mono = render_vfd_elements(list(elements), width, height)
        rgb = mono.convert("L").resize((width * scale, height * scale), Image.NEAREST)
        base = ImageOps.colorize(rgb, black=_VFD_BG, white=_VFD_ON)
        glow = base.filter(ImageFilter.GaussianBlur(scale * 0.55))
        glow = Image.eval(glow, lambda v: int(v * 0.8))
        return encode_preview_png(ImageChops.screen(base, glow))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("VFD elements preview render failed: %s", exc)
        return None


def render_vfd_idle(
    lines: Optional[Sequence[str]] = None,
    width: int = 140,
    height: int = 32,
    scale: int = 9,
) -> Optional[str]:
    """Render a simple centred idle screen for the VFD (blue-green)."""
    if not PIL_AVAILABLE:
        return None
    try:
        text_lines = list(lines or ["EAS STATION", "READY"])[:2]
        grid = [[0] * width for _ in range(height)]
        for i, line in enumerate(text_lines):
            text = str(line)
            text_w = len(text) * CELL_W
            x = max(0, (width - text_w) // 2)
            y = 2 + i * (CELL_H + 4)
            blit_text(grid, x, y, text)
        return _render_vfd_grid(grid, width, height, scale)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("VFD idle render failed: %s", exc)
        return None
