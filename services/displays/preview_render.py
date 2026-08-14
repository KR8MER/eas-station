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

"""Server-side preview image renderers for the VFD and LED Network Sign.

The Live Display Preview page used to draw hardcoded placeholder text for the
VFD (always green "EAS STATION - VFD") and flat single-colour HTML for the LED
sign, neither of which resembled the real hardware.  Following the same pattern
the OLED already uses -- where the controller ships an actual rendered
framebuffer as a base64 PNG -- these helpers render the *current* display
content to an image so the preview shows what the hardware is really putting
out:

* VFD  -- Noritake GU140x32F-7000B: 140x32 graphical VFD with the
  characteristic blue-green (CIG phosphor) glow on dark glass.  Rendered from
  the same draw-command list that drives the panel.
* LED  -- Alpha 9120C: 4 lines x 20 chars, dot-matrix, in the M-Protocol
  colour the message was sent with.

All functions are best-effort: if Pillow is unavailable or anything goes wrong
they return ``None`` and the page falls back to a simple idle message, so a
rendering problem can never take the preview API down.
"""

import base64
import io
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised wherever Pillow is installed
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Image = ImageChops = ImageDraw = ImageFilter = ImageOps = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False


# ── Compact 5x7 dot-matrix font ───────────────────────────────────────────────
# Uppercase letters, digits and the punctuation that shows up on EAS displays.
# Each glyph is 7 rows of 5 bits, modelled on the classic 5x7 LED/VFD cell.
_FONT_5x7: Dict[str, List[str]] = {
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
_CELL_W = 6
_CELL_H = 8

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

# Noritake CIG blue-green phosphor.
_VFD_ON = (108, 236, 214)
_VFD_BG = (2, 16, 14)

_LED_BG = (10, 9, 8)
_LED_OFF = (26, 22, 16)


def _glyph(ch: str) -> List[str]:
    return _FONT_5x7.get(ch.upper(), _FONT_5x7.get(ch, _FONT_5x7[' ']))


def _blit_text(grid: List[List[int]], x: int, y: int, text: str) -> None:
    """Stamp ``text`` into a 0/1 pixel ``grid`` at top-left pixel (x, y)."""
    h = len(grid)
    w = len(grid[0]) if h else 0
    cx = x
    for ch in str(text):
        g = _glyph(ch)
        for ry in range(7):
            row = g[ry]
            py = y + ry
            if py < 0 or py >= h:
                continue
            for rx in range(5):
                if row[rx] == '1':
                    px = cx + rx
                    if 0 <= px < w:
                        grid[py][px] = 1
        cx += _CELL_W


def _encode_png(img: "Image.Image", colors: int = 64) -> Optional[str]:
    """Encode a preview image as a base64 PNG data URI.

    The glow/bloom produces smooth gradients that balloon a truecolour PNG
    (and this gets published to Redis and polled by the browser every second),
    so the image is quantised to an adaptive palette first.  At 64 colours the
    glow is visually indistinguishable but the payload shrinks by ~10x.
    """
    try:
        out = img.convert("P", palette=Image.ADAPTIVE, colors=colors)
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to encode preview PNG: %s", exc)
        return None


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
    if not _PIL_AVAILABLE:
        return None
    try:
        on_rgb = _LED_COLORS.get(str(color or 'AMBER').upper(), _LED_COLORS['AMBER'])
        text_lines = _normalise_led_lines(lines)

        cell_w, cell_h = _CELL_W, _CELL_H
        gw, gh = cols * cell_w, rows * cell_h
        grid = [[0] * gw for _ in range(gh)]
        for i, line in enumerate(text_lines[:rows]):
            _blit_text(grid, 0, i * cell_h, line[:cols])

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
                if grid[y][x]:
                    gdraw.ellipse(
                        [cx - radius * 2, cy - radius * 2, cx + radius * 2, cy + radius * 2],
                        fill=dim_glow,
                    )
                    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=on_rgb)
                else:
                    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=_LED_OFF)
        glow = glow.filter(ImageFilter.GaussianBlur(scale * 0.45))
        return _encode_png(ImageChops.screen(base, glow))
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
    if not _PIL_AVAILABLE or not elements:
        return None
    try:
        from scripts.led_sign_controller import render_led_elements

        on_rgb = _LED_COLORS.get(str(color or 'AMBER').upper(), _LED_COLORS['AMBER'])
        mono = render_led_elements(list(elements))
        gw, gh = mono.size
        pixels = mono.load()

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
                if pixels[x, y]:
                    gdraw.ellipse(
                        [cx - radius * 2, cy - radius * 2, cx + radius * 2, cy + radius * 2],
                        fill=dim_glow,
                    )
                    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=on_rgb)
                else:
                    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=_LED_OFF)
        glow = glow.filter(ImageFilter.GaussianBlur(scale * 0.45))
        return _encode_png(ImageChops.screen(base, glow))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("LED elements preview render failed: %s", exc)
        return None


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
            _blit_text(grid, int(cmd.get('x', 0)), int(cmd.get('y', 0)), str(cmd.get('text', '')))
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
    if not _PIL_AVAILABLE:
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
        return _encode_png(ImageChops.screen(base, glow))
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
    if not _PIL_AVAILABLE:
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
    if not _PIL_AVAILABLE or not elements:
        return None
    try:
        from scripts.vfd_controller import render_vfd_elements

        mono = render_vfd_elements(list(elements), width, height)
        rgb = mono.convert("L").resize((width * scale, height * scale), Image.NEAREST)
        base = ImageOps.colorize(rgb, black=_VFD_BG, white=_VFD_ON)
        glow = base.filter(ImageFilter.GaussianBlur(scale * 0.55))
        glow = Image.eval(glow, lambda v: int(v * 0.8))
        return _encode_png(ImageChops.screen(base, glow))
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
    if not _PIL_AVAILABLE:
        return None
    try:
        text_lines = list(lines or ["EAS STATION", "READY"])[:2]
        grid = [[0] * width for _ in range(height)]
        for i, line in enumerate(text_lines):
            text = str(line)
            text_w = len(text) * _CELL_W
            x = max(0, (width - text_w) // 2)
            y = 2 + i * (_CELL_H + 4)
            _blit_text(grid, x, y, text)
        return _render_vfd_grid(grid, width, height, scale)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("VFD idle render failed: %s", exc)
        return None


__all__ = [
    "render_led_preview",
    "render_vfd_preview",
    "render_vfd_idle",
]
