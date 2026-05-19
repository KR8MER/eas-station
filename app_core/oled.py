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

"""OLED display integration helpers for the Argon Industria SSD1306 module."""

import logging
import math
import os
import threading
import textwrap
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from app_utils.gpio import ensure_gpiozero_pin_factory

logger = logging.getLogger(__name__)

# Import hardware settings helper
try:
    from app_core.hardware_settings import get_oled_settings
    _SETTINGS_AVAILABLE = True
except ImportError:
    _SETTINGS_AVAILABLE = False

    def get_oled_settings():
        """Fallback when settings module not available."""
        return {}

try:  # pragma: no cover - optional dependency
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw, ImageFont
except Exception as import_error:  # pragma: no cover - optional dependency
    i2c = None  # type: ignore[assignment]
    ssd1306 = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]
    _IMPORT_ERROR = import_error
else:
    _IMPORT_ERROR = None

# gpiozero Button is imported lazily to avoid conflicts with gevent monkey-patching
# in the web service. The actual import happens in ensure_oled_button() when needed.
Button = None  # type: ignore[assignment]

def _get_gpiozero_button():
    """Lazily import gpiozero Button to avoid gevent conflicts."""
    global Button
    if Button is None:
        try:
            from gpiozero import Button as _Button
            Button = _Button
        except Exception:
            pass
    return Button


def _get_settings_or_env():
    """Get settings from database (hardware settings are only in database).

    Hardware settings (GPIO, OLED, LED Sign, VFD) are configured via the web UI
    at /admin/hardware and stored in the database. Environment variables are
    NOT supported for hardware configuration.
    """
    if _SETTINGS_AVAILABLE:
        try:
            return get_oled_settings()
        except Exception as exc:
            logger.warning("Failed to load OLED settings from database: %s; using defaults", exc)

    # Return sensible defaults if database not available (e.g., during testing)
    return {
        'enabled': False,  # Disabled by default - must be enabled via /admin/hardware
        'width': 128,
        'height': 64,
        'i2c_bus': 1,
        'i2c_address': 0x3C,
        'rotate': 0,
        'contrast': None,
        'font_path': None,
        'default_invert': False,
        'button_gpio': 4,
        'button_hold_seconds': 1.25,
        'button_active_high': False,
        'scroll_effect': 'scroll_left',
        'scroll_speed': 4,
        'scroll_fps': 30,
        'screens_auto_start': True,
    }


class OLEDScrollEffect(Enum):
    """Scroll effect types for OLED text animation."""
    SCROLL_LEFT = "scroll_left"      # Right to left (default)
    SCROLL_RIGHT = "scroll_right"    # Left to right
    SCROLL_UP = "scroll_up"          # Bottom to top
    SCROLL_DOWN = "scroll_down"      # Top to bottom
    WIPE_LEFT = "wipe_left"          # Wipe from right to left
    WIPE_RIGHT = "wipe_right"        # Wipe from left to right
    WIPE_UP = "wipe_up"              # Wipe from bottom to top
    WIPE_DOWN = "wipe_down"          # Wipe from top to bottom
    FADE_IN = "fade_in"              # Fade in (flash effect)
    STATIC = "static"                # No animation (instant display)


@dataclass
class OLEDLine:
    """Renderable line on the OLED panel."""

    text: str
    x: int = 0
    y: Optional[int] = None
    font: str = "small"
    wrap: bool = True
    max_width: Optional[int] = None
    spacing: int = 2
    invert: Optional[bool] = None
    allow_empty: bool = False


def _draw_icon_antenna(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw a radio antenna/tower icon."""
    cx = x + size // 2
    # Antenna mast
    draw.line([(cx, y + 2), (cx, y + size - 1)], fill=colour)
    # Signal arcs (left)
    draw.arc([(x, y - 1), (cx + 1, y + 5)], start=120, end=240, fill=colour)
    # Signal arcs (right)
    draw.arc([(cx - 1, y - 1), (x + size, y + 5)], start=300, end=60, fill=colour)
    # Base
    draw.line([(cx - 2, y + size - 1), (cx + 2, y + size - 1)], fill=colour)


def _draw_icon_speaker(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw a speaker/audio icon."""
    # Speaker body
    h = size - 2
    mid = y + size // 2
    draw.polygon([
        (x + 1, mid - h // 4), (x + size // 3, mid - h // 4),
        (x + size * 2 // 3, mid - h // 2), (x + size * 2 // 3, mid + h // 2),
        (x + size // 3, mid + h // 4), (x + 1, mid + h // 4),
    ], fill=colour)
    # Sound waves
    draw.arc(
        [(x + size * 2 // 3, mid - h // 3), (x + size - 1, mid + h // 3)],
        start=300, end=60, fill=colour,
    )


def _draw_icon_warning(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw a warning triangle icon."""
    cx = x + size // 2
    draw.polygon([
        (cx, y), (x, y + size - 1), (x + size - 1, y + size - 1),
    ], outline=colour)
    # Exclamation mark
    draw.line([(cx, y + 3), (cx, y + size - 4)], fill=colour)
    draw.point((cx, y + size - 2), fill=colour)


def _draw_icon_check(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw a checkmark icon."""
    draw.line([
        (x + 1, y + size // 2),
        (x + size // 3, y + size - 2),
        (x + size - 2, y + 1),
    ], fill=colour)


def _draw_icon_cross(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw an X/cross icon."""
    draw.line([(x + 1, y + 1), (x + size - 2, y + size - 2)], fill=colour)
    draw.line([(x + size - 2, y + 1), (x + 1, y + size - 2)], fill=colour)


def _draw_icon_network(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw a network/globe icon."""
    cx, cy = x + size // 2, y + size // 2
    r = size // 2 - 1
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=colour)
    # Horizontal line
    draw.line([(cx - r, cy), (cx + r, cy)], fill=colour)
    # Vertical ellipse
    draw.ellipse([(cx - r // 2, cy - r), (cx + r // 2, cy + r)], outline=colour)


def _draw_icon_shield(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw a shield/security icon."""
    cx = x + size // 2
    draw.polygon([
        (cx, y), (x, y + size // 3),
        (x + 1, y + size * 2 // 3), (cx, y + size - 1),
        (x + size - 2, y + size * 2 // 3), (x + size - 1, y + size // 3),
    ], outline=colour)


def _draw_icon_wave(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw an audio waveform icon."""
    mid_y = y + size // 2
    # Draw a mini sine wave
    for px in range(size):
        py = mid_y + int(math.sin(px * math.pi * 2 / size) * (size // 3))
        draw.point((x + px, py), fill=colour)


def _draw_icon_clock(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw a small clock icon."""
    cx, cy = x + size // 2, y + size // 2
    r = size // 2 - 1
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=colour)
    # Hour hand (pointing to ~10 o'clock)
    draw.line([(cx, cy), (cx - r // 2, cy - r // 2)], fill=colour)
    # Minute hand (pointing to 12)
    draw.line([(cx, cy), (cx, cy - r + 1)], fill=colour)


def _draw_icon_heartbeat(draw: Any, x: int, y: int, size: int, colour: int) -> None:
    """Draw a heartbeat/pulse icon."""
    mid_y = y + size // 2
    # Flat line, spike, flat line
    draw.line([(x, mid_y), (x + size // 4, mid_y)], fill=colour)
    draw.line([(x + size // 4, mid_y), (x + size * 3 // 8, y + 1)], fill=colour)
    draw.line([(x + size * 3 // 8, y + 1), (x + size // 2, y + size - 2)], fill=colour)
    draw.line([(x + size // 2, y + size - 2), (x + size * 5 // 8, mid_y)], fill=colour)
    draw.line([(x + size * 5 // 8, mid_y), (x + size - 1, mid_y)], fill=colour)


_ICON_RENDERERS = {
    "antenna": _draw_icon_antenna,
    "speaker": _draw_icon_speaker,
    "warning": _draw_icon_warning,
    "check": _draw_icon_check,
    "cross": _draw_icon_cross,
    "network": _draw_icon_network,
    "shield": _draw_icon_shield,
    "wave": _draw_icon_wave,
    "clock": _draw_icon_clock,
    "heartbeat": _draw_icon_heartbeat,
}


class ArgonOLEDController:
    """High-level helper that renders text frames to the SSD1306 OLED."""

    FONT_SIZES = {
        "small": 11,
        "medium": 14,
        "large": 18,
        "xlarge": 28,
        "huge": 36,
    }

    def __init__(
        self,
        *,
        width: int,
        height: int,
        i2c_bus: int,
        i2c_address: int,
        rotate: int = 0,
        contrast: Optional[int] = None,
        font_path: Optional[str] = None,
        default_invert: bool = False,
    ) -> None:
        if i2c is None or ssd1306 is None or Image is None or ImageDraw is None or ImageFont is None:
            raise RuntimeError("luma.oled or Pillow not installed")

        # I2C bus speed is configured at system level via /boot/firmware/config.txt
        # Set dtparam=i2c_arm_baudrate=400000 for fast 400kHz speed to eliminate
        # visible column-by-column refresh (default 100kHz causes "curtain" effect)
        serial = i2c(port=i2c_bus, address=i2c_address)
        self.device = ssd1306(serial, width=width, height=height, rotate=rotate)
        if contrast is not None:
            try:
                self.device.contrast(max(0, min(255, contrast)))
            except Exception:  # pragma: no cover - hardware specific
                logger.debug("OLED contrast adjustment unsupported on this driver revision")
        self.width = width
        self.height = height
        self.default_invert = default_invert
        self._fonts = self._load_fonts(font_path)
        self._last_image: Optional[Image.Image] = None  # Store last displayed image for preview

    @staticmethod
    def _measure_text(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, text: str) -> int:
        if not text:
            return 0
        try:
            return int(draw.textlength(text, font=font))
        except AttributeError:
            return font.getsize(text)[0]

    def _fit_text_to_width(
        self,
        draw: ImageDraw.ImageDraw,
        font: ImageFont.ImageFont,
        text: str,
        max_width: Optional[int],
        overflow_mode: str,
    ) -> str:
        if not text or not max_width or max_width <= 0:
            return text

        width = self._measure_text(draw, font, text)
        if width <= max_width:
            return text

        if overflow_mode == "trim":
            truncated = text
            while truncated and self._measure_text(draw, font, truncated) > max_width:
                truncated = truncated[:-1]
            return truncated

        ellipsis = "\u2026"
        ellipsis_width = self._measure_text(draw, font, ellipsis)
        if ellipsis_width >= max_width:
            return ellipsis

        available = max_width - ellipsis_width
        truncated = text
        while truncated and self._measure_text(draw, font, truncated) > available:
            truncated = truncated[:-1]
        return f"{truncated}{ellipsis}" if truncated else ellipsis

    def _load_fonts(self, font_path: Optional[str]) -> Dict[str, ImageFont.ImageFont]:
        fonts: Dict[str, ImageFont.ImageFont] = {}
        candidate_paths: Iterable[Optional[str]] = (
            font_path,
            "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
        for name, size in self.FONT_SIZES.items():
            loaded_font: Optional[ImageFont.ImageFont] = None
            for path in candidate_paths:
                if not path:
                    continue
                try:
                    loaded_font = ImageFont.truetype(path, size)
                    break
                except OSError:
                    continue
            if loaded_font is None:
                if name == "small":
                    loaded_font = ImageFont.load_default()
                else:
                    loaded_font = fonts.get("small", ImageFont.load_default())
                logger.debug("Falling back to default bitmap font for OLED size '%s'", name)
            fonts[name] = loaded_font
        return fonts

    def clear(self, invert: Optional[bool] = None) -> None:
        active_invert = self.default_invert if invert is None else invert
        background = 255 if active_invert else 0
        image = Image.new("1", (self.width, self.height), color=background)
        self._last_image = image.copy()  # Store for preview
        self.device.display(image)

    def display_lines(
        self,
        lines: List[OLEDLine],
        *,
        clear: bool = True,
        invert: Optional[bool] = None,
    ) -> None:
        if clear:
            active_invert = self.default_invert if invert is None else invert
        else:
            # When not clearing preserve the existing background polarity
            active_invert = invert if invert is not None else self.default_invert

        background = 255 if active_invert else 0
        text_colour = 0 if active_invert else 255

        image = Image.new("1", (self.width, self.height), color=background)
        draw = ImageDraw.Draw(image)

        cursor_y = 0
        for entry in lines:
            if not entry.text and not entry.allow_empty:
                continue

            font_key = entry.font.lower()
            font = self._fonts.get(font_key, self._fonts["small"])
            x = max(0, min(self.width - 1, entry.x))
            max_width = entry.max_width
            if entry.wrap and not max_width:
                max_width = self.width - x

            segments = self._wrap_text(draw, entry.text, font, max_width, entry.wrap)
            line_height = self._line_height(font)
            for idx, segment in enumerate(segments):
                line_y = entry.y if entry.y is not None else cursor_y
                # Skip this segment if it starts completely outside the display
                # Allow partial rendering - PIL clips naturally at image boundaries
                if line_y >= self.height:
                    continue

                fill_colour = text_colour
                if entry.invert is True:
                    fill_colour = background
                elif entry.invert is False:
                    fill_colour = text_colour

                draw.text((x, line_y), segment, font=font, fill=fill_colour)
                spacing = max(0, entry.spacing)
                if entry.y is None:
                    cursor_y = line_y + line_height + spacing
                else:
                    entry.y = line_y + line_height + spacing
                    cursor_y = max(cursor_y, entry.y)

        self._last_image = image.copy()  # Store for preview
        self.device.display(image)

    def render_frame(
        self,
        elements: List[Dict[str, Any]],
        *,
        clear: bool = True,
        invert: Optional[bool] = None,
    ) -> None:
        """Render a complete frame with text, bar graphs, and shapes.

        Professional composite rendering for audio equipment-style displays.
        Elements are rendered in order, allowing for layering effects.

        Args:
            elements: List of element dictionaries with 'type' and parameters
            clear: Whether to clear the display first
            invert: Whether to invert colors

        Element types:
            - {'type': 'text', 'text': str, 'x': int, 'y': int, 'font': str}
            - {'type': 'bar', 'x': int, 'y': int, 'width': int, 'height': int,
               'value': float, 'border': bool}
            - {'type': 'rectangle', 'x': int, 'y': int, 'width': int, 'height': int,
               'filled': bool}
        """
        if clear:
            active_invert = self.default_invert if invert is None else invert
        else:
            active_invert = invert if invert is not None else self.default_invert

        background = 255 if active_invert else 0
        draw_colour = 0 if active_invert else 255

        image = Image.new("1", (self.width, self.height), color=background)
        draw = ImageDraw.Draw(image)

        for element in elements:
            elem_type = element.get('type', '')

            if elem_type == 'text':
                # Text element
                text = str(element.get('text', ''))
                if not text:
                    continue

                x_anchor = max(0, min(self.width - 1, int(element.get('x', 0))))
                y = max(0, min(self.height - 1, element.get('y', 0)))
                font_key = element.get('font', 'small').lower()
                font = self._fonts.get(font_key, self._fonts["small"])
                align = str(element.get('align', 'left') or 'left').lower()
                overflow_mode = str(element.get('overflow', 'ellipsis') or 'ellipsis').lower()
                max_width = element.get('max_width')
                max_width_value = None
                if isinstance(max_width, (int, float)):
                    max_width_value = int(max_width)
                text = self._fit_text_to_width(draw, font, text, max_width_value, overflow_mode)
                text_width = self._measure_text(draw, font, text)
                if text_width <= 0:
                    continue

                if align == 'right':
                    x = max(0, x_anchor - text_width)
                elif align == 'center':
                    x = max(0, min(self.width - 1, x_anchor - text_width // 2))
                else:
                    x = x_anchor

                if x + text_width > self.width:
                    x = max(0, self.width - text_width)
                y = max(0, min(self.height - 1, y))

                # Allow partial rendering - PIL will naturally clip text that extends
                # beyond the image boundaries. Only skip if text starts completely
                # outside the visible display area.
                if y >= self.height:
                    continue
                # Note: We intentionally do NOT check if y + text_height > self.height
                # because PIL clips content naturally and partial text is better than
                # no text at all for readability.

                elem_invert = element.get('invert')
                if elem_invert is True:
                    fill_colour = background
                elif elem_invert is False:
                    fill_colour = draw_colour
                else:
                    fill_colour = draw_colour

                draw.text((x, y), text, font=font, fill=fill_colour)

            elif elem_type == 'bar':
                # Bar graph element
                x = max(0, element.get('x', 0))
                y = max(0, element.get('y', 0))
                width = max(1, element.get('width', 50))
                height = max(1, element.get('height', 8))
                value = max(0.0, min(100.0, element.get('value', 0.0)))
                show_border = element.get('border', True)

                # Check bounds
                if x >= self.width or y >= self.height:
                    continue

                # Clamp dimensions to display
                width = min(width, self.width - x)
                height = min(height, self.height - y)
                x2 = min(self.width - 1, x + width - 1)
                y2 = min(self.height - 1, y + height - 1)

                # Draw border if requested
                if show_border:
                    draw.rectangle(
                        [(x, y), (x2, y2)],
                        fill=None,
                        outline=draw_colour
                    )
                    # Fill area is inside border
                    fill_x = min(self.width - 1, x + 1)
                    fill_y = min(self.height - 1, y + 1)
                    interior_width = max(0, (x2 - x) - 1)
                    interior_height = max(0, (y2 - y) - 1)
                else:
                    fill_x = x
                    fill_y = y
                    interior_width = max(0, x2 - x + 1)
                    interior_height = max(0, y2 - y + 1)

                # Calculate and draw filled portion
                fill_width = int((value / 100.0) * interior_width)
                if fill_width > 0 and interior_height > 0:
                    fill_x2 = min(self.width - 1, fill_x + fill_width - 1)
                    fill_y2 = min(self.height - 1, fill_y + interior_height - 1)
                    draw.rectangle(
                        [(fill_x, fill_y), (fill_x2, fill_y2)],
                        fill=draw_colour,
                        outline=None
                    )

            elif elem_type == 'rectangle':
                # Rectangle element
                x = max(0, element.get('x', 0))
                y = max(0, element.get('y', 0))
                width = max(1, element.get('width', 10))
                height = max(1, element.get('height', 10))
                filled = element.get('filled', False)

                # Check bounds
                if x >= self.width or y >= self.height:
                    continue

                # Clamp to display
                width = min(width, self.width - x)
                height = min(height, self.height - y)
                x2 = min(self.width - 1, x + width - 1)
                y2 = min(self.height - 1, y + height - 1)

                if filled:
                    draw.rectangle(
                        [(x, y), (x2, y2)],
                        fill=draw_colour,
                        outline=None
                    )
                else:
                    draw.rectangle(
                        [(x, y), (x2, y2)],
                        fill=None,
                        outline=draw_colour
                    )

            elif elem_type == 'hline':
                # Horizontal line (convenient shorthand for dividers)
                x = max(0, element.get('x', 0))
                y = max(0, min(self.height - 1, element.get('y', 0)))
                width = element.get('width', self.width - x)
                width = max(1, min(width, self.width - x))
                draw.line([(x, y), (x + width - 1, y)], fill=draw_colour)

            elif elem_type == 'vline':
                # Vertical line
                x = max(0, min(self.width - 1, element.get('x', 0)))
                y = max(0, element.get('y', 0))
                height = element.get('height', self.height - y)
                height = max(1, min(height, self.height - y))
                draw.line([(x, y), (x, y + height - 1)], fill=draw_colour)

            elif elem_type == 'line':
                # Arbitrary line between two points
                x1 = max(0, min(self.width - 1, element.get('x1', 0)))
                y1 = max(0, min(self.height - 1, element.get('y1', 0)))
                x2 = max(0, min(self.width - 1, element.get('x2', 0)))
                y2 = max(0, min(self.height - 1, element.get('y2', 0)))
                line_width = max(1, element.get('width', 1))
                draw.line([(x1, y1), (x2, y2)], fill=draw_colour, width=line_width)

            elif elem_type == 'circle':
                # Circle or ellipse outline/filled
                cx = element.get('x', 32)
                cy = element.get('y', 32)
                radius = max(1, element.get('radius', 10))
                filled = element.get('filled', False)
                x1 = max(0, cx - radius)
                y1 = max(0, cy - radius)
                x2 = min(self.width - 1, cx + radius)
                y2 = min(self.height - 1, cy + radius)
                if filled:
                    draw.ellipse([(x1, y1), (x2, y2)], fill=draw_colour, outline=draw_colour)
                else:
                    draw.ellipse([(x1, y1), (x2, y2)], outline=draw_colour)

            elif elem_type == 'arc':
                # Arc segment of a circle
                cx = element.get('x', 32)
                cy = element.get('y', 32)
                radius = max(1, element.get('radius', 10))
                start_angle = element.get('start', 0)
                end_angle = element.get('end', 360)
                x1 = max(0, cx - radius)
                y1 = max(0, cy - radius)
                x2 = min(self.width - 1, cx + radius)
                y2 = min(self.height - 1, cy + radius)
                draw.arc([(x1, y1), (x2, y2)], start=start_angle, end=end_angle, fill=draw_colour)

            elif elem_type == 'icon':
                # Built-in vector icon from the icon library
                icon_name = str(element.get('name', '')).lower()
                x = max(0, element.get('x', 0))
                y = max(0, element.get('y', 0))
                size = max(6, element.get('size', 10))
                renderer_fn = _ICON_RENDERERS.get(icon_name)
                if renderer_fn:
                    renderer_fn(draw, x, y, size, draw_colour)

            elif elem_type == 'clock':
                # Analog clock face - reads system time, draws hands
                cx = element.get('x', 32)
                cy = element.get('y', 32)
                radius = max(8, element.get('radius', 28))
                show_seconds = element.get('show_seconds', False)
                show_ticks = element.get('show_ticks', True)

                try:
                    from app_utils.time import local_now
                    now = local_now()
                except ImportError:
                    from datetime import datetime as _dt
                    now = _dt.now()

                # Clock face outline
                draw.ellipse(
                    [(cx - radius, cy - radius), (cx + radius, cy + radius)],
                    outline=draw_colour,
                )

                # Hour tick marks
                if show_ticks:
                    for h in range(12):
                        angle = math.radians(h * 30 - 90)
                        is_major = h % 3 == 0
                        inner_r = radius - (4 if is_major else 2)
                        outer_r = radius - 1
                        tx1 = cx + int(inner_r * math.cos(angle))
                        ty1 = cy + int(inner_r * math.sin(angle))
                        tx2 = cx + int(outer_r * math.cos(angle))
                        ty2 = cy + int(outer_r * math.sin(angle))
                        draw.line([(tx1, ty1), (tx2, ty2)], fill=draw_colour)

                # Hour hand (short, thick)
                hour_frac = (now.hour % 12) + now.minute / 60.0
                hour_angle = math.radians(hour_frac * 30 - 90)
                hx = cx + int((radius * 0.5) * math.cos(hour_angle))
                hy = cy + int((radius * 0.5) * math.sin(hour_angle))
                draw.line([(cx, cy), (hx, hy)], fill=draw_colour, width=2)

                # Minute hand (long, thin)
                min_frac = now.minute + now.second / 60.0
                min_angle = math.radians(min_frac * 6 - 90)
                mx = cx + int((radius * 0.78) * math.cos(min_angle))
                my = cy + int((radius * 0.78) * math.sin(min_angle))
                draw.line([(cx, cy), (mx, my)], fill=draw_colour, width=1)

                # Second hand (thinnest, longest)
                if show_seconds:
                    sec_angle = math.radians(now.second * 6 - 90)
                    sx = cx + int((radius * 0.85) * math.cos(sec_angle))
                    sy = cy + int((radius * 0.85) * math.sin(sec_angle))
                    draw.line([(cx, cy), (sx, sy)], fill=draw_colour, width=1)

                # Center dot
                draw.ellipse(
                    [(cx - 1, cy - 1), (cx + 1, cy + 1)],
                    fill=draw_colour,
                )

            elif elem_type == 'gauge':
                # Semi-circular gauge (speedometer style)
                cx = element.get('x', 64)
                cy = element.get('y', 50)
                radius = max(8, element.get('radius', 24))
                value = max(0.0, min(100.0, element.get('value', 0.0)))

                # Draw arc background (180 degrees, bottom half open)
                draw.arc(
                    [(cx - radius, cy - radius), (cx + radius, cy + radius)],
                    start=180, end=360, fill=draw_colour,
                )

                # Draw tick marks along the arc
                for t in range(0, 11):
                    tick_angle = math.radians(180 + t * 18)  # 180..360
                    inner_r = radius - 3
                    outer_r = radius - 1
                    tx1 = cx + int(inner_r * math.cos(tick_angle))
                    ty1 = cy + int(inner_r * math.sin(tick_angle))
                    tx2 = cx + int(outer_r * math.cos(tick_angle))
                    ty2 = cy + int(outer_r * math.sin(tick_angle))
                    draw.line([(tx1, ty1), (tx2, ty2)], fill=draw_colour)

                # Needle
                needle_angle = math.radians(180 + (value / 100.0) * 180)
                nx = cx + int((radius * 0.7) * math.cos(needle_angle))
                ny = cy + int((radius * 0.7) * math.sin(needle_angle))
                draw.line([(cx, cy), (nx, ny)], fill=draw_colour, width=1)

                # Center dot
                draw.ellipse(
                    [(cx - 1, cy - 1), (cx + 1, cy + 1)],
                    fill=draw_colour,
                )

            elif elem_type == 'dotted_hline':
                # Dotted horizontal line (every other pixel)
                x = max(0, element.get('x', 0))
                y = max(0, min(self.height - 1, element.get('y', 0)))
                width = element.get('width', self.width - x)
                width = max(1, min(width, self.width - x))
                for px in range(0, width, 2):
                    draw.point((x + px, y), fill=draw_colour)

            elif elem_type == 'pixel_pattern':
                # Draw a custom pixel pattern from a hex-encoded bitmap
                # Each byte represents 8 horizontal pixels
                x = max(0, element.get('x', 0))
                y = max(0, element.get('y', 0))
                pattern_width = element.get('pattern_width', 8)
                hex_data = element.get('data', '')
                if hex_data:
                    try:
                        raw = bytes.fromhex(hex_data)
                        row = 0
                        col = 0
                        for byte_val in raw:
                            for bit in range(8):
                                if col + bit < pattern_width:
                                    if byte_val & (0x80 >> bit):
                                        px = x + col + bit
                                        py = y + row
                                        if 0 <= px < self.width and 0 <= py < self.height:
                                            draw.point((px, py), fill=draw_colour)
                            col += 8
                            if col >= pattern_width:
                                col = 0
                                row += 1
                    except (ValueError, TypeError):
                        pass

        self._last_image = image.copy()
        self.device.display(image)

    def prepare_scroll_content(
        self,
        lines: List[OLEDLine],
        *,
        invert: Optional[bool] = None,
    ) -> tuple[Image.Image, Dict[str, int]]:
        """
        Pre-render the full text content to a padded image buffer for seamless scrolling.

        For horizontal scrolling, creates a padded buffer with the pattern:
        [original_text][separator][original_text]
        
        This allows the animation loop to scroll through the buffer with simple offset
        incrementing. When the offset reaches the end of the first text + separator,
        it resets to 0, creating a seamless continuous loop without complex boundary
        calculations.

        Args:
            lines: List of OLEDLine objects to render
            invert: Whether to invert colors

        Returns:
            A tuple of (content_image, dimensions) where:
            - content_image: PIL Image containing the fully rendered padded content
            - dimensions: Dict with 'max_x', 'max_y', 'original_width', 'separator_width'
        """
        active_invert = self.default_invert if invert is None else invert
        background = 255 if active_invert else 0
        text_colour = 0 if active_invert else 255

        # First pass: calculate dimensions of original content
        temp_image = Image.new("1", (1, 1), color=background)
        temp_draw = ImageDraw.Draw(temp_image)
        
        cursor_y = 0
        original_width = 0
        max_y = 0
        
        # Store line rendering info for second pass
        line_render_info = []

        for entry in lines:
            if not entry.text and not entry.allow_empty:
                continue

            font_key = entry.font.lower()
            font = self._fonts.get(font_key, self._fonts["small"])
            x = max(0, entry.x)

            # Keep text as single continuous line for smooth scrolling
            text = entry.text
            line_y = entry.y if entry.y is not None else cursor_y

            fill_colour = text_colour
            if entry.invert is True:
                fill_colour = background
            elif entry.invert is False:
                fill_colour = text_colour

            # Calculate text width
            try:
                text_width = int(temp_draw.textlength(text, font=font))
            except AttributeError:
                text_width = font.getsize(text)[0]

            original_width = max(original_width, x + text_width)

            line_height = self._line_height(font)
            max_y = max(max_y, line_y + line_height)

            # Store for second pass
            line_render_info.append({
                'text': text,
                'x': x,
                'y': line_y,
                'font': font,
                'fill': fill_colour,
                'width': text_width,
            })

            spacing = max(0, entry.spacing)
            if entry.y is None:
                cursor_y = line_y + line_height + spacing
            else:
                cursor_y = max(cursor_y, line_y + line_height + spacing)

        # Calculate separator width
        separator = '   ***   '
        separator_font = self._fonts.get("small", self._fonts["small"])
        try:
            separator_width = int(temp_draw.textlength(separator, font=separator_font))
        except AttributeError:
            separator_width = separator_font.getsize(separator)[0]

        # Create padded buffer: [original][separator][original]
        # This creates a seamless loop for horizontal scrolling
        # 
        # CRITICAL: Ensure only ONE copy of the text is visible at any time by adding
        # sufficient padding. The separator plus any additional padding must be at least
        # display_width to prevent both text copies from appearing simultaneously.
        min_separator_and_padding = max(separator_width, self.width)
        
        # Buffer structure: [text][padding/separator][text]
        # The loop point is set to original_width + min_separator_and_padding
        loop_point = original_width + min_separator_and_padding
        min_buffer_width = loop_point + self.width
        padded_width = max(min_buffer_width, original_width + min_separator_and_padding + original_width)
        padded_height = max(max_y, self.height)
        
        content_image = Image.new("1", (padded_width, padded_height), color=background)
        content_draw = ImageDraw.Draw(content_image)

        # Render original content at position 0
        for info in line_render_info:
            content_draw.text((info['x'], info['y']), info['text'], font=info['font'], fill=info['fill'])

        # DO NOT render the separator text - it causes visual "two things scrolling" effect
        # The separator area provides the necessary spacing for seamless scrolling,
        # but rendering visible text (like "***") at a different Y position makes it look
        # like two separate elements are scrolling at different vertical positions.
        # Just leave this area blank for clean, single-element scrolling appearance.

        # Render original content again after separator+padding for seamless wrap
        for info in line_render_info:
            offset_x = original_width + min_separator_and_padding
            content_draw.text((offset_x + info['x'], info['y']), info['text'], font=info['font'], fill=info['fill'])

        return content_image, {
            'max_x': padded_width,
            'max_y': max_y,
            'original_width': original_width,
            'separator_width': min_separator_and_padding,  # Use actual padding width for loop calculation
        }

    def render_scroll_frame(
        self,
        content_image: Image.Image,
        dimensions: Dict[str, int],
        effect: OLEDScrollEffect,
        offset: int,
        *,
        invert: Optional[bool] = None,
    ) -> None:
        """
        Render a single frame of a scrolling animation from pre-rendered content.

        This method is optimized for performance - it only crops and displays portions
        of the pre-rendered content_image, avoiding expensive text rendering on every
        frame. With the padded buffer approach, horizontal scrolling is now a simple
        crop operation without any complex boundary calculations.

        Args:
            content_image: Pre-rendered PIL Image from prepare_scroll_content()
            dimensions: Dict with 'max_x', 'max_y', etc. from prepare_scroll_content()
            effect: The scroll effect to apply
            offset: Pixel offset for the current frame (0 to max_offset)
            invert: Whether to invert colors
        """
        active_invert = self.default_invert if invert is None else invert
        background = 255 if active_invert else 0

        max_x = dimensions.get('max_x', self.width)
        max_y = dimensions.get('max_y', self.height)

        # Create display image
        display_image = Image.new("1", (self.width, self.height), color=background)

        # Apply the effect
        if effect == OLEDScrollEffect.SCROLL_LEFT:
            # Scroll from right to left (text moves left)
            # With padded buffer, this is now a simple crop operation
            # The buffer contains [original][separator][original], so scrolling is seamless
            src_x = offset
            src_y = 0
            
            # Simple crop from padded buffer - no complex wrapping needed!
            # The pre-rendered buffer already contains the repeated text for seamless loop
            display_image.paste(content_image.crop((src_x, src_y, src_x + self.width, src_y + self.height)), (0, 0))

        elif effect == OLEDScrollEffect.SCROLL_RIGHT:
            # Scroll from left to right (text moves right)
            src_x = max(0, max_x - self.width - offset)
            src_y = 0
            display_image.paste(content_image.crop((src_x, src_y, src_x + self.width, src_y + self.height)), (0, 0))

        elif effect == OLEDScrollEffect.SCROLL_UP:
            # Scroll from bottom to top (text moves up)
            src_x = 0
            src_y = offset
            display_image.paste(content_image.crop((src_x, src_y, src_x + self.width, src_y + self.height)), (0, 0))

        elif effect == OLEDScrollEffect.SCROLL_DOWN:
            # Scroll from top to bottom (text moves down)
            src_x = 0
            src_y = max(0, max_y - self.height - offset)
            display_image.paste(content_image.crop((src_x, src_y, src_x + self.width, src_y + self.height)), (0, 0))

        elif effect == OLEDScrollEffect.WIPE_LEFT:
            # Wipe from right to left (reveal text from left)
            reveal_width = min(self.width, offset)
            src_x = 0
            src_y = 0
            cropped = content_image.crop((src_x, src_y, src_x + reveal_width, src_y + self.height))
            display_image.paste(cropped, (0, 0))

        elif effect == OLEDScrollEffect.WIPE_RIGHT:
            # Wipe from left to right (reveal text from right)
            reveal_width = min(self.width, offset)
            src_x = max(0, self.width - reveal_width)
            src_y = 0
            dest_x = self.width - reveal_width
            cropped = content_image.crop((src_x, src_y, src_x + reveal_width, src_y + self.height))
            display_image.paste(cropped, (dest_x, 0))

        elif effect == OLEDScrollEffect.WIPE_UP:
            # Wipe from bottom to top (reveal text from bottom)
            reveal_height = min(self.height, offset)
            src_x = 0
            src_y = max(0, self.height - reveal_height)
            dest_y = self.height - reveal_height
            cropped = content_image.crop((src_x, src_y, src_x + self.width, src_y + reveal_height))
            display_image.paste(cropped, (0, dest_y))

        elif effect == OLEDScrollEffect.WIPE_DOWN:
            # Wipe from top to bottom (reveal text from top)
            reveal_height = min(self.height, offset)
            src_x = 0
            src_y = 0
            cropped = content_image.crop((src_x, src_y, src_x + self.width, src_y + reveal_height))
            display_image.paste(cropped, (0, 0))

        elif effect == OLEDScrollEffect.FADE_IN:
            # Flash/fade effect (show on even offsets, hide on odd)
            if offset % 2 == 0:
                src_x = 0
                src_y = 0
                display_image.paste(content_image.crop((src_x, src_y, src_x + self.width, src_y + self.height)), (0, 0))

        elif effect == OLEDScrollEffect.STATIC:
            # No animation, just display
            src_x = 0
            src_y = 0
            display_image.paste(content_image.crop((src_x, src_y, src_x + self.width, src_y + self.height)), (0, 0))

        self._last_image = display_image.copy()  # Store for preview
        self.device.display(display_image)

    @staticmethod
    def _line_height(font: ImageFont.ImageFont) -> int:
        try:
            bbox = font.getbbox("Hg")
            return bbox[3] - bbox[1]
        except AttributeError:  # pragma: no cover - Pillow < 8 compatibility
            width, height = font.getsize("Hg")
            return height

    @staticmethod
    def _wrap_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: Optional[int],
        allow_wrap: bool,
    ) -> List[str]:
        if not allow_wrap or not max_width or max_width <= 0:
            return [text]

        try:
            sample_width = draw.textlength("M", font=font)
        except AttributeError:  # pragma: no cover - Pillow < 8 compatibility
            sample_width = font.getsize("M")[0]
        if sample_width <= 0:
            sample_width = 6
        max_chars = max(1, int(max_width / sample_width))

        wrapped: List[str] = []
        for paragraph in text.splitlines() or [""]:
            if not paragraph:
                wrapped.append("")
                continue
            wrapped.extend(textwrap.wrap(paragraph, width=max_chars) or [paragraph])
        return wrapped or [""]

    def draw_rectangle(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        filled: bool = False,
        invert: Optional[bool] = None,
        clear: bool = False,
    ) -> None:
        """Draw a rectangle on the OLED display.

        Args:
            x: Left edge X coordinate
            y: Top edge Y coordinate
            width: Rectangle width in pixels
            height: Rectangle height in pixels
            filled: If True, draw filled rectangle; if False, draw outline only
            invert: Whether to invert colors
            clear: Whether to clear the display first
        """
        active_invert = self.default_invert if invert is None else invert
        background = 255 if active_invert else 0
        draw_colour = 0 if active_invert else 255

        if clear:
            image = Image.new("1", (self.width, self.height), color=background)
        else:
            # Get current display or create new one
            if self._last_image is not None:
                image = self._last_image.copy()
            else:
                image = Image.new("1", (self.width, self.height), color=background)

        draw = ImageDraw.Draw(image)

        # Clamp coordinates to display bounds
        width = max(1, width)
        height = max(1, height)
        x1 = max(0, min(self.width - 1, x))
        y1 = max(0, min(self.height - 1, y))
        x2 = max(x1, min(self.width - 1, x + width - 1))
        y2 = max(y1, min(self.height - 1, y + height - 1))

        if filled:
            draw.rectangle([(x1, y1), (x2, y2)], fill=draw_colour, outline=None)
        else:
            draw.rectangle([(x1, y1), (x2, y2)], fill=None, outline=draw_colour)

        self._last_image = image.copy()
        self.device.display(image)

    def draw_bar_graph(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        value: float,
        *,
        show_border: bool = True,
        invert: Optional[bool] = None,
        clear: bool = False,
    ) -> None:
        """Draw a horizontal bar graph (meter) on the OLED display.

        Professional audio-style bar graph with border and filled level indicator.

        Args:
            x: Left edge X coordinate
            y: Top edge Y coordinate
            width: Total bar width in pixels
            height: Bar height in pixels
            value: Fill percentage (0.0 to 100.0)
            show_border: If True, draw border around bar
            invert: Whether to invert colors
            clear: Whether to clear the display first
        """
        active_invert = self.default_invert if invert is None else invert
        background = 255 if active_invert else 0
        draw_colour = 0 if active_invert else 255

        if clear:
            image = Image.new("1", (self.width, self.height), color=background)
        else:
            # Get current display or create new one
            if self._last_image is not None:
                image = self._last_image.copy()
            else:
                image = Image.new("1", (self.width, self.height), color=background)

        draw = ImageDraw.Draw(image)

        # Clamp coordinates and value
        x1 = max(0, min(self.width - 1, x))
        y1 = max(0, min(self.height - 1, y))
        bar_width = max(1, min(self.width - x1, width))
        bar_height = max(1, min(self.height - y1, height))
        value_clamped = max(0.0, min(100.0, value))
        x2 = min(self.width - 1, x1 + bar_width - 1)
        y2 = min(self.height - 1, y1 + bar_height - 1)

        # Draw border if requested
        if show_border:
            draw.rectangle(
                [(x1, y1), (x2, y2)],
                fill=None,
                outline=draw_colour
            )
            # Fill area is inside the border
            fill_x = min(self.width - 1, x1 + 1)
            fill_y = min(self.height - 1, y1 + 1)
            interior_width = max(0, (x2 - x1) - 1)
            interior_height = max(0, (y2 - y1) - 1)
        else:
            # No border, use full dimensions
            fill_x = x1
            fill_y = y1
            interior_width = max(0, x2 - x1 + 1)
            interior_height = max(0, y2 - y1 + 1)

        # Calculate filled portion width
        fill_width = int((value_clamped / 100.0) * interior_width)

        # Draw filled portion
        if fill_width > 0 and interior_height > 0:
            fill_x2 = min(self.width - 1, fill_x + fill_width - 1)
            fill_y2 = min(self.height - 1, fill_y + interior_height - 1)
            draw.rectangle(
                [(fill_x, fill_y), (fill_x2, fill_y2)],
                fill=draw_colour,
                outline=None
            )

        self._last_image = image.copy()
        self.device.display(image)

    def flash_invert(self, duration: float = 0.15) -> None:
        """Briefly invert the display for visual feedback.

        This provides immediate visual confirmation that a button press was detected,
        helping users verify GPIO functionality.

        Args:
            duration: How long to show the inverted display in seconds (default: 0.15)
        """
        if self._last_image is None:
            return

        try:
            import time
            from PIL import ImageOps

            # Invert the last displayed image
            inverted = ImageOps.invert(self._last_image.convert("L")).convert("1")
            self.device.display(inverted)

            # Wait for the specified duration
            time.sleep(duration)

            # Restore the original image
            self.device.display(self._last_image)

        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"Failed to flash invert display: {e}")

    def get_preview_image_base64(self) -> Optional[str]:
        """Get the last displayed image as a base64-encoded PNG.

        Returns:
            Base64-encoded PNG string, or None if no image available
        """
        if self._last_image is None:
            return None

        try:
            import base64
            import io

            # Convert monochrome image to RGB for PNG export
            rgb_image = self._last_image.convert("RGB")

            # Save to bytes buffer
            buffer = io.BytesIO()
            rgb_image.save(buffer, format="PNG")
            buffer.seek(0)

            # Encode as base64
            img_bytes = buffer.getvalue()
            b64_string = base64.b64encode(img_bytes).decode('utf-8')

            return f"data:image/png;base64,{b64_string}"
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"Failed to export OLED preview image: {e}")
            return None


# Load settings from database (cached at module level but refreshed on controller init)
_oled_settings = _get_settings_or_env()

# Module-level configuration (refreshed when initializing controller)
OLED_WIDTH = max(16, _oled_settings.get('width', 128))
OLED_HEIGHT = max(16, _oled_settings.get('height', 64))
OLED_I2C_BUS = _oled_settings.get('i2c_bus', 1)
OLED_I2C_ADDRESS = _oled_settings.get('i2c_address', 0x3C)
OLED_ROTATE = _oled_settings.get('rotate', 0)
OLED_CONTRAST = _oled_settings.get('contrast')
OLED_FONT_PATH = _oled_settings.get('font_path')
OLED_DEFAULT_INVERT = _oled_settings.get('default_invert', False)
OLED_BUTTON_GPIO = _oled_settings.get('button_gpio', 4)
OLED_BUTTON_HOLD_SECONDS = max(0.5, _oled_settings.get('button_hold_seconds', 1.25))
OLED_BUTTON_ACTIVE_HIGH = _oled_settings.get('button_active_high', False)

# Scroll animation configuration
OLED_SCROLL_EFFECT = _oled_settings.get('scroll_effect', 'scroll_left')
OLED_SCROLL_SPEED = max(1, _oled_settings.get('scroll_speed', 4))  # Pixels per frame (1-10)
OLED_SCROLL_FPS = max(5, min(60, _oled_settings.get('scroll_fps', 30)))  # Frames per second (default 30 for smooth I2C updates)

# IMPORTANT: Don't use OLED_ENABLED at module level - check in initialise_oled_display() instead
# This allows settings to be changed without reimporting the module
OLED_AVAILABLE = False
oled_controller: Optional[ArgonOLEDController] = None
oled_button_device: Optional[Button] = None

_oled_lock = threading.Lock()


def ensure_oled_button(log: Optional[logging.Logger] = None):
    """Initialise and return the OLED front-panel button if available.

    Returns:
        Button instance if successfully initialized, None otherwise.
        Returns existing button if already initialized.
    """
    # Lazy import to avoid gevent conflicts in web service
    ButtonClass = _get_gpiozero_button()

    if ButtonClass is None:
        if log:
            log.debug("gpiozero Button class unavailable; skipping OLED button setup")
        return None

    # Check if OLED is enabled and read GPIO config from database settings.
    # Always read fresh settings so that changes made via the web UI take effect
    # without requiring a service restart.
    oled_enabled = False
    oled_settings: dict = {}
    if _SETTINGS_AVAILABLE:
        try:
            oled_settings = get_oled_settings()
            oled_enabled = oled_settings.get('enabled', False)
        except Exception as exc:
            if log:
                log.warning("Failed to check OLED enabled status: %s", exc)

    if not oled_enabled:
        if log:
            log.debug("OLED button disabled because OLED module is disabled")
        return None

    # Use fresh DB values for GPIO config; fall back to module-level defaults
    gpio_pin = oled_settings.get('button_gpio', OLED_BUTTON_GPIO)
    active_high = oled_settings.get('button_active_high', OLED_BUTTON_ACTIVE_HIGH)
    hold_seconds = max(0.5, oled_settings.get('button_hold_seconds', OLED_BUTTON_HOLD_SECONDS))

    logger_ref = log or logger

    with _oled_lock:
        global oled_button_device

        # Return existing button if it's still valid
        if oled_button_device is not None:
            try:
                # Verify the button is still functional by checking its state
                _ = oled_button_device.is_pressed
                return oled_button_device
            except Exception as exc:
                logger_ref.warning("Existing OLED button device is invalid, re-initializing: %s", exc)
                try:
                    oled_button_device.close()
                except Exception:
                    pass
                oled_button_device = None

        if not ensure_gpiozero_pin_factory(logger_ref):
            logger_ref.debug("gpiozero pin factory unavailable; cannot initialise OLED button")
            return None

        try:
            # Configure button based on wiring:
            # - pull_up=True (default): Internal pull-up resistor enabled, button connects GPIO to GND when pressed
            # - pull_up=False: Internal pull-down resistor enabled, button connects GPIO to 3.3V when pressed
            # The button_active_high setting controls this for different enclosure wiring configurations
            button = ButtonClass(
                gpio_pin,
                pull_up=not active_high,
                hold_time=hold_seconds,
                bounce_time=0.05,
            )
        except Exception as exc:  # pragma: no cover - hardware specific
            logger_ref.warning(
                "Failed to initialise OLED button on GPIO %s: %s",
                gpio_pin,
                exc,
            )
            return None

        oled_button_device = button
        logger_ref.info(
            "OLED button initialised on GPIO %s with hold time %.2fs (active_%s)",
            gpio_pin,
            hold_seconds,
            "high" if active_high else "low",
        )
        return oled_button_device


def initialise_oled_display(log: Optional[logging.Logger] = None) -> Optional[ArgonOLEDController]:
    """Initialise the OLED controller if configuration permits."""

    global OLED_AVAILABLE, oled_controller

    logger_ref = log or logger

    # Check if OLED is enabled in database settings
    oled_settings = {}
    oled_enabled = False
    if _SETTINGS_AVAILABLE:
        try:
            oled_settings = get_oled_settings()
            oled_enabled = oled_settings.get('enabled', False)
        except Exception as exc:
            logger_ref.warning("Failed to load OLED settings from database: %s; using defaults", exc)

    if not oled_enabled:
        logger_ref.debug("OLED display disabled via configuration (enable in Admin > Hardware Settings)")
        OLED_AVAILABLE = False
        oled_controller = None
        return None

    if _IMPORT_ERROR is not None:
        logger_ref.warning("OLED dependencies unavailable: %s", _IMPORT_ERROR)
        OLED_AVAILABLE = False
        oled_controller = None
        return None

    with _oled_lock:
        if oled_controller is not None:
            OLED_AVAILABLE = True
            return oled_controller

        # Get configuration from settings (refresh module-level vars)
        width = max(16, oled_settings.get('width', 128))
        height = max(16, oled_settings.get('height', 64))
        i2c_bus = oled_settings.get('i2c_bus', 1)
        i2c_address = oled_settings.get('i2c_address', 0x3C)
        rotate = oled_settings.get('rotate', 0)
        contrast = oled_settings.get('contrast')
        font_path = oled_settings.get('font_path')
        default_invert = oled_settings.get('default_invert', False)

        try:
            controller = ArgonOLEDController(
                width=width,
                height=height,
                i2c_bus=i2c_bus,
                i2c_address=i2c_address,
                rotate=rotate,
                contrast=int(contrast) if contrast else None,
                font_path=font_path,
                default_invert=default_invert,
            )
        except Exception as exc:  # pragma: no cover - hardware specific
            logger_ref.error("Failed to initialise OLED display: %s", exc)
            OLED_AVAILABLE = False
            oled_controller = None
            return None

        oled_controller = controller
        OLED_AVAILABLE = True
        logger_ref.info(
            "OLED display initialised on I2C bus %s address 0x%02X (%sx%s)",
            i2c_bus,
            i2c_address,
            width,
            height,
        )
        return controller


__all__ = [
    "OLEDLine",
    "OLEDScrollEffect",
    "ArgonOLEDController",
    "OLED_AVAILABLE",
    "OLED_BUTTON_GPIO",
    "OLED_BUTTON_HOLD_SECONDS",
    "OLED_CONTRAST",
    "OLED_DEFAULT_INVERT",
    "OLED_FONT_PATH",
    "OLED_HEIGHT",
    "OLED_I2C_ADDRESS",
    "OLED_I2C_BUS",
    "OLED_ROTATE",
    "OLED_SCROLL_EFFECT",
    "OLED_SCROLL_FPS",
    "OLED_SCROLL_SPEED",
    "OLED_WIDTH",
    "ensure_oled_button",
    "initialise_oled_display",
    "oled_controller",
    "oled_button_device",
]
