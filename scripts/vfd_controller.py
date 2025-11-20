"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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
            baudrate: Communication baud rate (default: 38400)
            timeout: Serial read timeout in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial: Optional[serial.Serial] = None
        self.connected = False
        self.current_brightness = VFDBrightness.LEVEL_7

    def connect(self) -> bool:
        """
        Connect to the VFD display via serial port.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )

            # Allow time for connection to stabilize
            time.sleep(0.1)

            # Initialize display
            self.initialize_display()

            self.connected = True
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
