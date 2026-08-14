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

"""
Noritake GU140x32F-7000B VFD Display Controller
================================================

This module provides a comprehensive driver for the Noritake GU140x32F-7000B
graphical VFD (Vacuum Fluorescent Display) using the GU-7000 series protocol.

Display Specifications:
- Resolution: 140 x 32 pixels
- Connection: UART/Serial
- Protocol: GU-7000 Series
- Brightness: 8 levels (0-7)
- Graphics: Full bitmap support

Author: Claude (Anthropic)
Date: 2025-11-05
"""

import serial
import time
import logging
from typing import Optional, Tuple, List
from enum import Enum
from PIL import Image, ImageDraw, ImageFont
import io

logger = logging.getLogger(__name__)


class VFDBrightness(Enum):
    """VFD brightness levels (0-7, where 7 is brightest)."""
    LEVEL_0 = 0  # Dimmest
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4
    LEVEL_5 = 5
    LEVEL_6 = 6
    LEVEL_7 = 7  # Brightest


class VFDFont(Enum):
    """Built-in VFD fonts."""
    FONT_5x7 = 0x01
    FONT_7x10 = 0x02
    FONT_10x14 = 0x03


class NoritakeVFDController:
    """
    Controller for Noritake GU140x32F-7000B VFD Display.

    This class implements the GU-7000 series protocol for controlling
    a graphical VFD display over UART/serial connection.

    Example usage:
        vfd = NoritakeVFDController(port='/dev/ttyUSB0', baudrate=38400)
        vfd.connect()
        vfd.clear_screen()
        vfd.draw_text(0, 0, "Hello World!")
        vfd.disconnect()
    """

    # Display constants
    WIDTH = 140
    HEIGHT = 32

    # Command constants (GU-7000 protocol)
    CMD_PREFIX = 0x1F
    CMD_INIT = 0x28
    CMD_CLEAR = 0x01
    CMD_HOME = 0x02
    CMD_BRIGHTNESS = 0x58
    CMD_CURSOR_POS = 0x24
    CMD_IMAGE_WRITE = 0x28
    CMD_PIXEL = 0x70
    CMD_LINE = 0x6C
    CMD_RECT = 0x72
    CMD_RECT_FILL = 0x78

    # ASCII control codes
    US = 0x1F  # Unit Separator
    ESC = 0x1B  # Escape

    def __init__(
        self,
        port: str = '/dev/ttyUSB0',
        baudrate: int = 38400,
        timeout: float = 1.0
    ):
        """
        Initialize the VFD controller.

        Args:
            port: Serial port device (e.g., '/dev/ttyUSB0', 'COM3')
                  or TCP socket URL (e.g., 'socket://192.168.8.122:10001')
            baudrate: Communication baud rate (default: 38400)
            timeout: Serial read timeout in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial: Optional[serial.Serial] = None
        self.connected = False
        self.current_brightness = VFDBrightness.LEVEL_7
        # Type-safe check for network connection
        self.is_network_connection = isinstance(port, str) and port.startswith('socket://') if port else False

    def connect(self) -> bool:
        """
        Connect to the VFD display via serial port or TCP socket.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Create serial connection
            # pyserial supports socket:// URLs for TCP connections
            if self.is_network_connection:
                # For network connections, pyserial handles socket:// URLs directly
                # No need to specify baudrate for network connections, but we set it anyway
                self.serial = serial.serial_for_url(
                    self.port,
                    baudrate=self.baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=self.timeout
                )
                # Enable TCP keep-alive on the underlying socket so a
                # half-open link to the serial-to-Ethernet adapter is
                # detected and reconnected rather than silently dropped.
                # pyserial's socket:// handler exposes the raw socket as
                # ``_socket``; guard in case that internal changes.
                try:
                    from app_utils.network import enable_tcp_keepalive
                    raw_sock = getattr(self.serial, "_socket", None)
                    if raw_sock is not None:
                        enable_tcp_keepalive(raw_sock)
                except Exception as exc:  # pragma: no cover - best effort
                    logger.debug(f"TCP keep-alive not enabled for VFD: {exc}")
                logger.info(f"Connecting to VFD via TCP socket: {self.port}")
            else:
                # Traditional serial port connection
                self.serial = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=self.timeout
                )
                logger.info(f"Connecting to VFD via serial port: {self.port}")

            # Allow time for connection to stabilize
            time.sleep(0.1)

            # Initialize display
            self.initialize_display()

            self.connected = True
            if self.is_network_connection:
                logger.info(f"Connected to Noritake VFD via network on {self.port}")
            else:
                logger.info(f"Connected to Noritake VFD on {self.port} at {self.baudrate} baud")
            return True

        except serial.SerialException as e:
            logger.error(f"Failed to connect to VFD on {self.port}: {e}")
            self.connected = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error connecting to VFD: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect from the VFD display."""
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.connected = False
            logger.info("Disconnected from Noritake VFD")

    def initialize_display(self) -> None:
        """
        Initialize the VFD display with default settings.
        Sets brightness and clears the screen.
        """
        if not self.serial or not self.serial.is_open:
            logger.error("Cannot initialize: serial port not open")
            return

        # Send initialization sequence
        self._write_byte(self.US)
        self._write_byte(self.CMD_INIT)
        self._write_byte(0x67)  # Initialize graphics mode
        self._write_byte(0x01)  # Mode 1
        self._write_byte(0x03)  # Parameter

        time.sleep(0.1)

        # Set brightness to maximum
        self.set_brightness(VFDBrightness.LEVEL_7)

        # Clear screen
        self.clear_screen()

        logger.info("VFD display initialized")

    def _write_byte(self, byte: int) -> None:
        """Write a single byte to the serial port."""
        if self.serial and self.serial.is_open:
            self.serial.write(bytes([byte]))

    def _write_bytes(self, data: bytes) -> None:
        """Write multiple bytes to the serial port."""
        if self.serial and self.serial.is_open:
            self.serial.write(data)

    def clear_screen(self) -> None:
        """Clear the entire display."""
        if not self.connected:
            logger.warning("VFD not connected, cannot clear screen")
            return

        # Send clear command
        self._write_byte(self.ESC)
        self._write_byte(self.CMD_CLEAR)
        time.sleep(0.05)  # Allow time for clear operation

        logger.debug("VFD screen cleared")

    def set_brightness(self, level: VFDBrightness) -> None:
        """
        Set display brightness level.

        Args:
            level: Brightness level (0-7)
        """
        if not self.connected:
            logger.warning("VFD not connected, cannot set brightness")
            return

        # Send brightness command
        self._write_byte(self.US)
        self._write_byte(self.CMD_BRIGHTNESS)
        self._write_byte(level.value)

        self.current_brightness = level
        logger.debug(f"VFD brightness set to {level.value}")

    def set_cursor_position(self, x: int, y: int) -> None:
        """
        Set cursor position for text output.

        Args:
            x: X coordinate (0-139)
            y: Y coordinate (0-31)
        """
        if not self.connected:
            return

        # Validate coordinates
        x = max(0, min(x, self.WIDTH - 1))
        y = max(0, min(y, self.HEIGHT - 1))

        # Send cursor position command
        self._write_byte(self.US)
        self._write_byte(self.CMD_CURSOR_POS)
        self._write_byte(x)
        self._write_byte(y)

    def draw_text(self, x: int, y: int, text: str) -> None:
        """
        Draw text at specified position.

        Args:
            x: X coordinate (pixels)
            y: Y coordinate (pixels)
            text: Text to display
        """
        if not self.connected:
            logger.warning("VFD not connected, cannot draw text")
            return

        # Set cursor position
        self.set_cursor_position(x, y)

        # Write text (ASCII characters)
        try:
            self._write_bytes(text.encode('ascii', errors='replace'))
            logger.debug(f"Drew text at ({x}, {y}): {text}")
        except Exception as e:
            logger.error(f"Error drawing text: {e}")

    def draw_pixel(self, x: int, y: int, state: bool = True) -> None:
        """
        Draw or clear a single pixel.

        Args:
            x: X coordinate (0-139)
            y: Y coordinate (0-31)
            state: True to turn pixel on, False to turn it off
        """
        if not self.connected:
            return

        # Validate coordinates
        if not (0 <= x < self.WIDTH and 0 <= y < self.HEIGHT):
            return

        # Send pixel command
        self._write_byte(self.US)
        self._write_byte(self.CMD_PIXEL)
        self._write_byte(1 if state else 0)  # Write or erase
        self._write_byte(x)
        self._write_byte(y)

    def draw_line(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """
        Draw a line between two points.

        Args:
            x1, y1: Start coordinates
            x2, y2: End coordinates
        """
        if not self.connected:
            return

        # Validate and clamp coordinates
        x1 = max(0, min(x1, self.WIDTH - 1))
        y1 = max(0, min(y1, self.HEIGHT - 1))
        x2 = max(0, min(x2, self.WIDTH - 1))
        y2 = max(0, min(y2, self.HEIGHT - 1))

        # Send line command
        self._write_byte(self.US)
        self._write_byte(self.CMD_LINE)
        self._write_byte(x1)
        self._write_byte(y1)
        self._write_byte(x2)
        self._write_byte(y2)

    def draw_rectangle(self, x1: int, y1: int, x2: int, y2: int, filled: bool = False) -> None:
        """
        Draw a rectangle.

        Args:
            x1, y1: Top-left corner
            x2, y2: Bottom-right corner
            filled: True for filled rectangle, False for outline
        """
        if not self.connected:
            return

        # Validate and clamp coordinates
        x1 = max(0, min(x1, self.WIDTH - 1))
        y1 = max(0, min(y1, self.HEIGHT - 1))
        x2 = max(0, min(x2, self.WIDTH - 1))
        y2 = max(0, min(y2, self.HEIGHT - 1))

        # Send rectangle command
        cmd = self.CMD_RECT_FILL if filled else self.CMD_RECT
        self._write_byte(self.US)
        self._write_byte(cmd)
        self._write_byte(x1)
        self._write_byte(y1)
        self._write_byte(x2)
        self._write_byte(y2)

    def draw_bitmap(self, x: int, y: int, width: int, height: int, bitmap_data: bytes) -> None:
        """
        Draw a bitmap image.

        Args:
            x: X coordinate (top-left)
            y: Y coordinate (top-left)
            width: Bitmap width in pixels
            height: Bitmap height in pixels
            bitmap_data: Raw bitmap data (1 bit per pixel, row-major)
        """
        if not self.connected:
            logger.warning("VFD not connected, cannot draw bitmap")
            return

        # Validate coordinates
        if x < 0 or y < 0 or x + width > self.WIDTH or y + height > self.HEIGHT:
            logger.warning(f"Bitmap exceeds display bounds: ({x},{y}) {width}x{height}")
            return

        # Send bitmap command (GU-7000 series)
        self._write_byte(self.US)
        self._write_byte(0x28)  # Image write command
        self._write_byte(0x66)  # Bitmap mode
        self._write_byte(0x11)  # 1-bit monochrome
        self._write_byte(width)
        self._write_byte(height)
        self._write_byte(x)
        self._write_byte(y)

        # Write bitmap data
        self._write_bytes(bitmap_data)

        logger.debug(f"Drew bitmap at ({x}, {y}): {width}x{height}")

    def render_frame(self, elements: List[dict], *, clear: bool = True) -> None:
        """Render a composite frame (text/shapes/icons/gauges) and push it
        as a single bitmap, instead of one GU-7000 draw command per element.

        Mirrors app_core.oled.ArgonOLEDController.render_frame()'s element
        vocabulary and reuses its icon glyph library directly (they're pure
        PIL functions, not OLED-specific) so the same screen-authoring
        mental model works on both display types. Built because the VFD
        previously only had per-primitive GU-7000 commands (text/line/
        rectangle) wired through the template system -- despite the
        hardware itself already supporting full bitmap pushes via
        draw_bitmap(), it never got the icon/gauge/circle/bar-chart
        vocabulary the OLED engine has.

        Element types: text, rectangle, line, hline, vline, circle, icon,
        bar (single meter), bars (multi-value chart), gauge, compass.
        See ArgonOLEDController.render_frame()'s docstring for per-type
        parameters -- identical here except the canvas is 140x32.

        The actual drawing lives in the module-level render_vfd_elements()
        so the web preview (services/displays/preview_render.py) can build
        the exact same image without a hardware connection, instead of
        maintaining a second, drifting reimplementation of this logic.
        """
        if not self.connected:
            logger.warning("VFD not connected, cannot render frame")
            return

        image = render_vfd_elements(elements, self.WIDTH, self.HEIGHT, font=self._vfd_font())

        if clear:
            self.clear_screen()
        bitmap_data = self._image_to_bitmap(image)
        self.draw_bitmap(0, 0, self.WIDTH, self.HEIGHT, bitmap_data)

    def _vfd_font(self) -> "ImageFont.ImageFont":
        """Small TrueType font used by render_frame(); falls back to PIL's
        tiny built-in bitmap font if DejaVuSans isn't available (same
        fallback chain as ArgonOLEDController._load_fonts()). 7px roughly
        matches the panel's native 5x7/7x10 font sizes -- enough vertical
        room for 3-4 text rows on the 32px-tall canvas."""
        if getattr(self, "_cached_vfd_font", None) is not None:
            return self._cached_vfd_font
        for path in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            try:
                self._cached_vfd_font = ImageFont.truetype(path, 7)
                return self._cached_vfd_font
            except OSError:
                continue
        self._cached_vfd_font = ImageFont.load_default()
        return self._cached_vfd_font

    def display_image(self, image_path: str, x: int = 0, y: int = 0) -> None:
        """
        Load and display an image file on the VFD.

        Args:
            image_path: Path to image file (PNG, JPG, BMP, etc.)
            x: X position to place image
            y: Y position to place image
        """
        try:
            # Load image with PIL
            img = Image.open(image_path)

            # Convert to 1-bit monochrome
            img = img.convert('1')

            # Get image dimensions
            width, height = img.size

            # Ensure image fits on display
            if x + width > self.WIDTH:
                width = self.WIDTH - x
            if y + height > self.HEIGHT:
                height = self.HEIGHT - y

            # Crop if necessary
            if img.size != (width, height):
                img = img.crop((0, 0, width, height))

            # Convert to bitmap bytes
            bitmap_data = self._image_to_bitmap(img)

            # Draw to display
            self.draw_bitmap(x, y, width, height, bitmap_data)

            logger.info(f"Displayed image from {image_path} at ({x}, {y})")

        except Exception as e:
            logger.error(f"Error displaying image {image_path}: {e}")

    def display_image_from_bytes(self, image_bytes: bytes, x: int = 0, y: int = 0) -> None:
        """
        Display an image from bytes data.

        Args:
            image_bytes: Image data in bytes
            x: X position
            y: Y position
        """
        try:
            # Load image from bytes
            img = Image.open(io.BytesIO(image_bytes))

            # Convert to 1-bit monochrome
            img = img.convert('1')

            # Get image dimensions
            width, height = img.size

            # Ensure image fits on display
            if x + width > self.WIDTH:
                width = self.WIDTH - x
            if y + height > self.HEIGHT:
                height = self.HEIGHT - y

            # Crop if necessary
            if img.size != (width, height):
                img = img.crop((0, 0, width, height))

            # Convert to bitmap bytes
            bitmap_data = self._image_to_bitmap(img)

            # Draw to display
            self.draw_bitmap(x, y, width, height, bitmap_data)

            logger.info(f"Displayed image from bytes at ({x}, {y})")

        except Exception as e:
            logger.error(f"Error displaying image from bytes: {e}")

    def create_text_image(
        self,
        text: str,
        font_size: int = 10,
        x: int = 0,
        y: int = 0
    ) -> None:
        """
        Create and display text as a rendered image (for better font control).

        Args:
            text: Text to render
            font_size: Font size in pixels
            x: X position
            y: Y position
        """
        try:
            # Create a new image for rendering
            img = Image.new('1', (self.WIDTH, font_size + 4), 0)
            draw = ImageDraw.Draw(img)

            # Use default font (can be customized with ImageFont.truetype)
            draw.text((2, 2), text, fill=1)

            # Get actual text bounding box
            bbox = draw.textbbox((2, 2), text)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]

            # Crop to text size
            img = img.crop((0, 0, min(width + 4, self.WIDTH), min(height + 4, self.HEIGHT)))

            # Convert to bitmap and display
            bitmap_data = self._image_to_bitmap(img)
            self.draw_bitmap(x, y, img.size[0], img.size[1], bitmap_data)

            logger.debug(f"Rendered text image: {text}")

        except Exception as e:
            logger.error(f"Error creating text image: {e}")

    def _image_to_bitmap(self, img: Image.Image) -> bytes:
        """
        Convert PIL Image to VFD bitmap format.

        Args:
            img: PIL Image in mode '1' (1-bit)

        Returns:
            Bitmap data as bytes
        """
        width, height = img.size

        # Calculate bytes per row (8 pixels per byte)
        bytes_per_row = (width + 7) // 8

        # Convert image to bytes
        bitmap_data = bytearray()

        for row in range(height):
            row_data = bytearray(bytes_per_row)
            for col in range(width):
                pixel = img.getpixel((col, row))
                if pixel:  # If pixel is white (on)
                    byte_index = col // 8
                    bit_index = 7 - (col % 8)
                    row_data[byte_index] |= (1 << bit_index)
            bitmap_data.extend(row_data)

        return bytes(bitmap_data)

    def draw_progress_bar(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        progress: float
    ) -> None:
        """
        Draw a progress bar.

        Args:
            x, y: Top-left corner
            width: Bar width in pixels
            height: Bar height in pixels
            progress: Progress value (0.0 to 1.0)
        """
        if not self.connected:
            return

        # Clamp progress
        progress = max(0.0, min(1.0, progress))

        # Draw outline
        self.draw_rectangle(x, y, x + width - 1, y + height - 1, filled=False)

        # Draw filled portion
        fill_width = int((width - 4) * progress)
        if fill_width > 0:
            self.draw_rectangle(
                x + 2,
                y + 2,
                x + 2 + fill_width,
                y + height - 3,
                filled=True
            )

    def get_status(self) -> dict:
        """
        Get current VFD status.

        Returns:
            Dictionary with status information
        """
        return {
            'connected': self.connected,
            'port': self.port,
            'baudrate': self.baudrate,
            'brightness': self.current_brightness.value,
            'width': self.WIDTH,
            'height': self.HEIGHT
        }

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False


# Singleton instance (initialized in app_core/vfd.py)
vfd_controller: Optional[NoritakeVFDController] = None


def get_vfd_controller() -> Optional[NoritakeVFDController]:
    """
    Get the global VFD controller instance.

    Returns:
        VFD controller instance or None if not initialized
    """
    global vfd_controller
    return vfd_controller


def init_vfd_controller(port: str, baudrate: int = 38400) -> Optional[NoritakeVFDController]:
    """
    Initialize the global VFD controller.

    Args:
        port: Serial port path
        baudrate: Communication baud rate

    Returns:
        Initialized VFD controller or None on failure
    """
    global vfd_controller

    try:
        vfd_controller = NoritakeVFDController(port=port, baudrate=baudrate)
        if vfd_controller.connect():
            logger.info("VFD controller initialized successfully")
            return vfd_controller
        else:
            logger.warning("VFD controller failed to connect")
            vfd_controller = None
            return None
    except Exception as e:
        logger.error(f"Failed to initialize VFD controller: {e}")
        vfd_controller = None
        return None


def _measure_text(draw: "ImageDraw.ImageDraw", font: "ImageFont.ImageFont", text: str) -> int:
    if not text:
        return 0
    try:
        return int(draw.textlength(text, font=font))
    except AttributeError:
        return font.getsize(text)[0]


def _fit_text_to_width(
    draw: "ImageDraw.ImageDraw",
    font: "ImageFont.ImageFont",
    text: str,
    max_width: Optional[int],
    overflow_mode: str,
) -> str:
    """Trim or ellipsize text to max_width -- same convention as
    ArgonOLEDController._fit_text_to_width(). Without this, a long alert
    event name or area description just draws past the 140px edge with no
    clipping at all (Pillow doesn't clip drawing ops to the canvas)."""
    if not text or not max_width or max_width <= 0:
        return text

    width = _measure_text(draw, font, text)
    if width <= max_width:
        return text

    if overflow_mode == "trim":
        truncated = text
        while truncated and _measure_text(draw, font, truncated) > max_width:
            truncated = truncated[:-1]
        return truncated

    ellipsis = "…"
    ellipsis_width = _measure_text(draw, font, ellipsis)
    if ellipsis_width >= max_width:
        return ellipsis

    available = max_width - ellipsis_width
    truncated = text
    while truncated and _measure_text(draw, font, truncated) > available:
        truncated = truncated[:-1]
    return f"{truncated}{ellipsis}" if truncated else ellipsis


_vfd_large_font: Optional["ImageFont.ImageFont"] = None


def _load_vfd_large_font() -> "ImageFont.ImageFont":
    """14pt bold -- a second, larger size so a screen's single most
    important value (a clock, a percentage) can visually lead the way
    OLED's font-size hierarchy (small/medium/large/xlarge) does, instead
    of every row on the VFD reading at the same flat 7px weight."""
    global _vfd_large_font
    if _vfd_large_font is None:
        try:
            _vfd_large_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
            )
        except OSError:
            _vfd_large_font = ImageFont.load_default()
    return _vfd_large_font


def render_vfd_elements(
    elements: List[dict],
    width: int = 140,
    height: int = 32,
    *,
    font: Optional["ImageFont.ImageFont"] = None,
) -> "Image.Image":
    """Pure function: draw a VFD element list to a 1-bit PIL Image.

    No hardware/serial dependency -- NoritakeVFDController.render_frame()
    calls this and pushes the result as a bitmap; the web preview
    (services/displays/preview_render.py) calls it directly to render an
    accurate PNG without a live device, instead of maintaining a second,
    drifting reimplementation of the same drawing logic.

    Element types: text, rectangle, line, hline, vline, circle, icon,
    bar (single meter), bars (multi-value chart), gauge, compass -- see
    app_core.oled.ArgonOLEDController.render_frame()'s docstring for
    per-type parameters (identical here except the canvas is 140x32). A
    text element may set "font": "large" for the 14pt bold hero size;
    default (unset, or any other value) is the base 7px font.
    """
    import math

    from app_core.oled import _ICON_RENDERERS

    if font is None:
        try:
            # 7px roughly matches the panel's native 5x7/7x10 font sizes
            # (VFDFont.FONT_5x7/FONT_7x10) -- 10px left only enough vertical
            # room for ~2 text rows on a 32px-tall canvas.
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 7)
        except OSError:
            font = ImageFont.load_default()

    image = Image.new("1", (width, height), color=0)
    draw = ImageDraw.Draw(image)
    colour = 1

    for element in elements:
        elem_type = element.get("type", "")

        if elem_type == "text":
            text = str(element.get("text", ""))
            if not text:
                continue
            text_font = _load_vfd_large_font() if element.get("font") == "large" else font
            x = max(0, min(width - 1, int(element.get("x", 0))))
            y = max(0, min(height - 1, int(element.get("y", 0))))
            max_width = element.get("max_width")
            if isinstance(max_width, (int, float)):
                overflow_mode = str(element.get("overflow", "ellipsis") or "ellipsis").lower()
                text = _fit_text_to_width(draw, text_font, text, int(max_width), overflow_mode)
            # invert=True is how a header banner's title stays readable
            # against its own filled rectangle (fill=colour on both would
            # draw white-on-white and vanish) -- same convention as
            # ArgonOLEDController.render_frame()'s text element.
            text_colour = 0 if element.get("invert") else colour
            draw.text((x, y), text, font=text_font, fill=text_colour)

        elif elem_type == "rectangle":
            x = max(0, element.get("x", 0))
            y = max(0, element.get("y", 0))
            w = max(1, element.get("width", 10))
            h = max(1, element.get("height", 10))
            x2 = min(width - 1, x + w - 1)
            y2 = min(height - 1, y + h - 1)
            if element.get("filled", False):
                draw.rectangle([(x, y), (x2, y2)], fill=colour)
            else:
                draw.rectangle([(x, y), (x2, y2)], outline=colour)

        elif elem_type == "line":
            draw.line(
                [
                    (element.get("x1", 0), element.get("y1", 0)),
                    (element.get("x2", 0), element.get("y2", 0)),
                ],
                fill=colour,
            )

        elif elem_type == "hline":
            x = max(0, element.get("x", 0))
            y = max(0, min(height - 1, element.get("y", 0)))
            w = max(1, min(element.get("width", width - x), width - x))
            draw.line([(x, y), (x + w - 1, y)], fill=colour)

        elif elem_type == "vline":
            x = max(0, min(width - 1, element.get("x", 0)))
            y = max(0, element.get("y", 0))
            h = max(1, min(element.get("height", height - y), height - y))
            draw.line([(x, y), (x, y + h - 1)], fill=colour)

        elif elem_type == "circle":
            cx = element.get("x", 16)
            cy = element.get("y", 16)
            r = max(1, element.get("radius", 8))
            bbox = [(cx - r, cy - r), (cx + r, cy + r)]
            if element.get("filled", False):
                draw.ellipse(bbox, fill=colour)
            else:
                draw.ellipse(bbox, outline=colour)

        elif elem_type == "icon":
            renderer_fn = _ICON_RENDERERS.get(str(element.get("name", "")).lower())
            if renderer_fn:
                icon_colour = 0 if element.get("invert") else colour
                renderer_fn(
                    draw,
                    max(0, element.get("x", 0)),
                    max(0, element.get("y", 0)),
                    max(6, element.get("size", 9)),
                    icon_colour,
                )

        elif elem_type == "bar":
            x = max(0, element.get("x", 0))
            y = max(0, element.get("y", 0))
            w = max(1, element.get("width", 50))
            h = max(1, element.get("height", 8))
            value = max(0.0, min(100.0, element.get("value", 0.0)))
            x2 = min(width - 1, x + w - 1)
            y2 = min(height - 1, y + h - 1)
            draw.rectangle([(x, y), (x2, y2)], outline=colour)
            fill_w = int((value / 100.0) * max(0, (x2 - x) - 1))
            if fill_w > 0:
                draw.rectangle([(x + 1, y + 1), (x + fill_w, y2 - 1)], fill=colour)

        elif elem_type == "segments":
            # Classic segmented LED VU-meter look: N discrete blocks in a
            # row, each outlined, lit solid up to `value`'s proportion of
            # `count`. Distinct from 'bar' (one continuous fill) -- built
            # because a single solid bar reads as a generic "progress bar"
            # rather than audio-gear-style metering.
            x = max(0, element.get("x", 0))
            y = max(0, element.get("y", 0))
            w = max(1, element.get("width", 100))
            h = max(1, element.get("height", 8))
            value = max(0.0, min(100.0, element.get("value", 0.0)))
            count = max(1, element.get("count", 10))
            gap = max(0, element.get("gap", 2))
            seg_w = max(1, (w - gap * (count - 1)) // count)
            lit = round((value / 100.0) * count)
            cursor_x = x
            for i in range(count):
                seg_x2 = min(width - 1, cursor_x + seg_w - 1)
                seg_y2 = min(height - 1, y + h - 1)
                if i < lit:
                    draw.rectangle([(cursor_x, y), (seg_x2, seg_y2)], fill=colour)
                else:
                    draw.rectangle([(cursor_x, y), (seg_x2, seg_y2)], outline=colour)
                cursor_x += seg_w + gap

        elif elem_type == "bars":
            x = max(0, element.get("x", 0))
            y = max(0, element.get("y", 0))
            w = max(1, element.get("width", 40))
            h = max(1, element.get("height", 16))
            values = element.get("values") or []
            max_value = element.get("max_value", 50.0) or 50.0
            gap = max(0, element.get("gap", 1))
            count = len(values)
            if count > 0:
                bar_w = max(1, (w - gap * (count - 1)) // count)
                cursor_x = x
                for raw_value in values:
                    try:
                        value = max(0.0, min(float(max_value), float(raw_value)))
                    except (TypeError, ValueError):
                        value = 0.0
                    bar_h = int((value / max_value) * h) if max_value > 0 else 0
                    if bar_h > 0:
                        draw.rectangle(
                            [(cursor_x, y + h - bar_h), (cursor_x + bar_w - 1, y + h - 1)],
                            fill=colour,
                        )
                    cursor_x += bar_w + gap

        elif elem_type == "gauge":
            cx = element.get("x", 32)
            cy = element.get("y", 28)
            r = max(6, element.get("radius", 16))
            value = max(0.0, min(100.0, element.get("value", 0.0)))
            draw.arc([(cx - r, cy - r), (cx + r, cy + r)], start=180, end=360, fill=colour)
            needle_angle = math.radians(180 + (value / 100.0) * 180)
            nx = cx + int((r * 0.8) * math.cos(needle_angle))
            ny = cy + int((r * 0.8) * math.sin(needle_angle))
            draw.line([(cx, cy), (nx, ny)], fill=colour)

        elif elem_type == "compass":
            cx = element.get("x", 20)
            cy = element.get("y", 16)
            r = max(6, element.get("radius", 12))
            heading = element.get("heading")
            draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=colour)
            for deg, label in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
                angle = math.radians(deg - 90)
                tx1 = cx + int((r - 3) * math.cos(angle))
                ty1 = cy + int((r - 3) * math.sin(angle))
                tx2 = cx + int((r - 1) * math.cos(angle))
                ty2 = cy + int((r - 1) * math.sin(angle))
                draw.line([(tx1, ty1), (tx2, ty2)], fill=colour)
            if isinstance(heading, (int, float)):
                needle_angle = math.radians(heading - 90)
                nx = cx + int((r * 0.7) * math.cos(needle_angle))
                ny = cy + int((r * 0.7) * math.sin(needle_angle))
                draw.line([(cx, cy), (nx, ny)], fill=colour, width=1)

    return image
