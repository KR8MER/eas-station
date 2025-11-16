"""OLED display integration helpers for the Argon Industria SSD1306 module."""

from __future__ import annotations

import logging
import os
import threading
import textwrap
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional

from app_utils.gpio import ensure_gpiozero_pin_factory

logger = logging.getLogger(__name__)

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

try:  # pragma: no cover - optional dependency
    from gpiozero import Button
except Exception:  # pragma: no cover - gpiozero optional on non-RPi
    Button = None  # type: ignore[assignment]


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: str) -> int:
    value = os.getenv(name, default).strip()
    base = 16 if value.startswith("0x") else 10
    try:
        return int(value, base)
    except (TypeError, ValueError):
        logger.warning("Invalid integer for %s=%s; using default %s", name, value, default)
        return int(default, base)


def _env_float(name: str, default: str) -> float:
    value = os.getenv(name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Invalid float for %s=%s; using default %s", name, value, default)
        return float(default)


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
            for idx, segment in enumerate(segments):
                line_y = entry.y if entry.y is not None else cursor_y
                if line_y >= self.height:
                    break

                fill_colour = text_colour
                if entry.invert is True:
                    fill_colour = background
                elif entry.invert is False:
                    fill_colour = text_colour

                draw.text((x, line_y), segment, font=font, fill=fill_colour)

                line_height = self._line_height(font)
                spacing = max(0, entry.spacing)
                if entry.y is None:
                    cursor_y = line_y + line_height + spacing
                else:
                    entry.y = line_y + line_height + spacing
                    cursor_y = max(cursor_y, entry.y)

        self.device.display(image)

    def prepare_scroll_content(
        self,
        lines: List[OLEDLine],
        *,
        invert: Optional[bool] = None,
    ) -> tuple[Image.Image, Dict[str, int]]:
        """
        Pre-render the full text content to a single image buffer.

        This method is called once before the animation loop to render all text
        into a large buffer. The animation loop then only needs to crop and display
        portions of this buffer, making it much more efficient than redrawing text
        on every frame.

        Args:
            lines: List of OLEDLine objects to render
            invert: Whether to invert colors

        Returns:
            A tuple of (content_image, dimensions) where:
            - content_image: PIL Image containing the fully rendered content
            - dimensions: Dict with 'max_x' and 'max_y' indicating content bounds
        """
        active_invert = self.default_invert if invert is None else invert
        background = 255 if active_invert else 0
        text_colour = 0 if active_invert else 255

        # Create the full content image (may be larger than display)
        content_image = Image.new("1", (self.width * 2, self.height * 2), color=background)
        content_draw = ImageDraw.Draw(content_image)

        # Render all lines to the content image
        cursor_y = 0
        max_x = 0
        max_y = 0

        for entry in lines:
            if not entry.text and not entry.allow_empty:
                continue

            font_key = entry.font.lower()
            font = self._fonts.get(font_key, self._fonts["small"])
            x = max(0, entry.x)
            max_width = entry.max_width
            if entry.wrap and not max_width:
                max_width = self.width - x

            segments = self._wrap_text(content_draw, entry.text, font, max_width, entry.wrap)
            for segment in segments:
                line_y = entry.y if entry.y is not None else cursor_y

                fill_colour = text_colour
                if entry.invert is True:
                    fill_colour = background
                elif entry.invert is False:
                    fill_colour = text_colour

                content_draw.text((x, line_y), segment, font=font, fill=fill_colour)

                # Track content bounds
                try:
                    text_width = content_draw.textlength(segment, font=font)
                except AttributeError:
                    text_width = font.getsize(segment)[0]

                max_x = max(max_x, x + int(text_width))

                line_height = self._line_height(font)
                max_y = max(max_y, line_y + line_height)

                spacing = max(0, entry.spacing)
                if entry.y is None:
                    cursor_y = line_y + line_height + spacing
                else:
                    cursor_y = max(cursor_y, line_y + line_height + spacing)

        return content_image, {'max_x': max_x, 'max_y': max_y}

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
        frame. This results in smooth, fluid scrolling even on resource-constrained
        devices.

        Args:
            content_image: Pre-rendered PIL Image from prepare_scroll_content()
            dimensions: Dict with 'max_x' and 'max_y' from prepare_scroll_content()
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
            src_x = offset
            src_y = 0
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


OLED_ENABLED = _env_flag("OLED_ENABLED", "false")
OLED_WIDTH = max(16, _env_int("OLED_WIDTH", "128"))
OLED_HEIGHT = max(16, _env_int("OLED_HEIGHT", "64"))
OLED_I2C_BUS = _env_int("OLED_I2C_BUS", "1")
OLED_I2C_ADDRESS = _env_int("OLED_I2C_ADDRESS", "0x3C")
OLED_ROTATE = (_env_int("OLED_ROTATE", "0") % 360) // 90
OLED_CONTRAST = os.getenv("OLED_CONTRAST")
OLED_FONT_PATH = os.getenv("OLED_FONT_PATH")
OLED_DEFAULT_INVERT = _env_flag("OLED_DEFAULT_INVERT", "false")
OLED_BUTTON_GPIO = _env_int("OLED_BUTTON_GPIO", "4")
OLED_BUTTON_HOLD_SECONDS = max(0.5, _env_float("OLED_BUTTON_HOLD_SECONDS", "1.25"))

# Scroll animation configuration
OLED_SCROLL_EFFECT = os.getenv("OLED_SCROLL_EFFECT", "scroll_left").lower()
OLED_SCROLL_SPEED = max(1, _env_int("OLED_SCROLL_SPEED", "4"))  # Pixels per frame (1-10)
OLED_SCROLL_FPS = max(5, min(60, _env_int("OLED_SCROLL_FPS", "60")))  # Frames per second

OLED_AVAILABLE = False
oled_controller: Optional[ArgonOLEDController] = None
oled_button_device: Optional[Button] = None

_oled_lock = threading.Lock()


def ensure_oled_button(log: Optional[logging.Logger] = None) -> Optional[Button]:
    """Initialise and return the OLED front-panel button if available."""

    if Button is None:
        if log:
            log.debug("gpiozero Button class unavailable; skipping OLED button setup")
        return None

    if not OLED_ENABLED:
        if log:
            log.debug("OLED button disabled because OLED module is disabled")
        return None

    logger_ref = log or logger

    with _oled_lock:
        global oled_button_device
        if oled_button_device is not None:
            return oled_button_device

        if not ensure_gpiozero_pin_factory(logger_ref):
            logger_ref.debug("gpiozero pin factory unavailable; cannot initialise OLED button")
            return None

        try:
            button = Button(
                OLED_BUTTON_GPIO,
                pull_up=True,
                hold_time=OLED_BUTTON_HOLD_SECONDS,
                bounce_time=0.05,
            )
        except Exception as exc:  # pragma: no cover - hardware specific
            logger_ref.warning(
                "Failed to initialise OLED button on GPIO %s: %s",
                OLED_BUTTON_GPIO,
                exc,
            )
            return None

        oled_button_device = button
        logger_ref.info(
            "OLED button initialised on GPIO %s with hold time %.2fs",
            OLED_BUTTON_GPIO,
            OLED_BUTTON_HOLD_SECONDS,
        )
        return oled_button_device


def initialise_oled_display(log: Optional[logging.Logger] = None) -> Optional[ArgonOLEDController]:
    """Initialise the OLED controller if configuration permits."""

    global OLED_AVAILABLE, oled_controller

    logger_ref = log or logger

    if not OLED_ENABLED:
        logger_ref.info("OLED display disabled via configuration")
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

        try:
            controller = ArgonOLEDController(
                width=OLED_WIDTH,
                height=OLED_HEIGHT,
                i2c_bus=OLED_I2C_BUS,
                i2c_address=OLED_I2C_ADDRESS,
                rotate=OLED_ROTATE,
                contrast=int(OLED_CONTRAST) if OLED_CONTRAST else None,
                font_path=OLED_FONT_PATH,
                default_invert=OLED_DEFAULT_INVERT,
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
            OLED_I2C_BUS,
            OLED_I2C_ADDRESS,
            OLED_WIDTH,
            OLED_HEIGHT,
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
    "OLED_ENABLED",
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
