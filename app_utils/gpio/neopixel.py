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

"""NeoPixel / WS2812B addressable LED strip support."""

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


from .pin_types import (
    MIN_FLASH_INTERVAL_MS,
)

try:  # pragma: no cover - rpi_ws281x requires DMA hardware and root on Raspberry Pi
    from rpi_ws281x import PixelStrip, Color as NeopixelColor  # type: ignore
    _NEOPIXEL_LIB_AVAILABLE = True
except Exception:  # pragma: no cover - not available on non-Pi environments
    PixelStrip = None  # type: ignore[assignment]
    NeopixelColor = None  # type: ignore[assignment]
    _NEOPIXEL_LIB_AVAILABLE = False

# ---------------------------------------------------------------------------
# NeoPixel / WS2812B addressable LED strip support
# ---------------------------------------------------------------------------

# Neopixel strip type constants (mirrors rpi_ws281x constants)
WS2811_STRIP_GRB = 0x00081000
WS2811_STRIP_RGB = 0x00081000  # same ordering bits, differs in channel setup
_NEO_STRIP_TYPES: Dict[str, int] = {
    "GRB": WS2811_STRIP_GRB,
    "RGB": 0x00080100,
    "BGR": 0x00080001,
    "RGBW": 0x18081000,
    "GRBW": 0x18081000,
}

# Frequency and DMA defaults for rpi_ws281x
_NEO_FREQ_HZ = 800_000  # 800kHz signal frequency
_NEO_DMA = 10           # DMA channel (safe default)
_NEO_INVERT = False     # Invert signal (for NPN transistor-level shifters)
_NEO_CHANNEL = 0        # PWM channel (0 = GPIO 18/12, 1 = GPIO 13/19)


@dataclass
class NeopixelConfig:
    """Configuration for a NeoPixel (WS2812B) LED strip attached to a single GPIO pin."""

    gpio_pin: int = 18          # BCM pin; 18 (hw PWM ch0) recommended for best timing
    num_pixels: int = 1         # Number of LEDs in the strip
    brightness: int = 128       # Global brightness 0-255
    led_order: str = "GRB"      # Byte order of the LEDs (WS2812B default is GRB)
    standby_color: tuple = (0, 10, 0)    # (r, g, b) shown when idle
    alert_color: tuple = (255, 0, 0)     # (r, g, b) shown during active alert
    flash_on_alert: bool = True          # Flash strip during active alert
    flash_interval_ms: int = 500         # Flash period in milliseconds


class _NullNeopixelStrip:
    """No-op strip used when rpi_ws281x hardware is unavailable."""

    def __init__(self, num_pixels: int) -> None:
        self._num_pixels = num_pixels
        self._pixels: List[int] = [0] * num_pixels

    def begin(self) -> None:
        pass

    def setPixelColor(self, n: int, color: int) -> None:
        if 0 <= n < self._num_pixels:
            self._pixels[n] = color

    def show(self) -> None:
        pass

    def setBrightness(self, brightness: int) -> None:
        pass

    def numPixels(self) -> int:
        return self._num_pixels

    @property
    def pixels(self) -> List[int]:
        return list(self._pixels)


def _make_neo_color(r: int, g: int, b: int) -> int:
    """Pack an (r, g, b) tuple into a 24-bit integer as used by rpi_ws281x."""
    if NeopixelColor is not None:
        return int(NeopixelColor(r, g, b))
    return (r << 16) | (g << 8) | b


class NeopixelController:
    """Controller for NeoPixel (WS2812B) addressable LED strips.

    Provides graceful degradation when ``rpi_ws281x`` is not installed or the
    underlying DMA hardware cannot be claimed (e.g. running in Docker or on a
    non-Raspberry-Pi host).

    Example::

        config = NeopixelConfig(gpio_pin=18, num_pixels=8, brightness=128)
        neo = NeopixelController(config, logger=logger)
        if neo.start():
            neo.start_alert()   # red flash during an EAS alert
            ...
            neo.end_alert()     # return to dim green standby
            neo.cleanup()
    """

    def __init__(self, config: NeopixelConfig, logger=None) -> None:
        self.config = config
        self.logger = logger
        self._strip: Optional[Any] = None
        self._available = False
        self._lock = threading.RLock()
        self._flash_thread: Optional[threading.Thread] = None
        self._flash_stop = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle

    def start(self) -> bool:
        """Initialise hardware and set the strip to the standby colour.

        Returns ``True`` when the real hardware was successfully claimed, or
        ``False`` when falling back to the null backend (no hardware / library
        not installed).
        """
        with self._lock:
            if _NEOPIXEL_LIB_AVAILABLE and PixelStrip is not None:
                strip_type = _NEO_STRIP_TYPES.get(
                    self.config.led_order.upper(), WS2811_STRIP_GRB
                )
                try:
                    strip = PixelStrip(
                        self.config.num_pixels,
                        self.config.gpio_pin,
                        _NEO_FREQ_HZ,
                        _NEO_DMA,
                        _NEO_INVERT,
                        self.config.brightness,
                        _NEO_CHANNEL,
                        strip_type,
                    )
                    strip.begin()
                    self._strip = strip
                    self._available = True
                    if self.logger:
                        self.logger.info(
                            "NeoPixel strip initialized: %d pixel(s) on GPIO %d "
                            "(order=%s, brightness=%d)",
                            self.config.num_pixels,
                            self.config.gpio_pin,
                            self.config.led_order,
                            self.config.brightness,
                        )
                except Exception as exc:  # pragma: no cover - DMA access depends on host
                    if self.logger:
                        self.logger.warning(
                            "NeoPixel hardware unavailable on GPIO %d: %s – "
                            "falling back to null strip (no LEDs will light)",
                            self.config.gpio_pin,
                            exc,
                        )
                    self._strip = _NullNeopixelStrip(self.config.num_pixels)
                    self._available = False
            else:
                if self.logger:
                    self.logger.warning(
                        "rpi_ws281x library not installed – NeoPixel strip on GPIO %d "
                        "running in null (no-op) mode.  Install rpi-ws281x to enable real LEDs.",
                        self.config.gpio_pin,
                    )
                self._strip = _NullNeopixelStrip(self.config.num_pixels)
                self._available = False

            self.set_standby()
            return self._available

    def cleanup(self) -> None:
        """Stop flash, turn off all pixels, and release hardware."""
        self.stop_flash()
        with self._lock:
            self.off()
            self._strip = None
            self._available = False

    # ------------------------------------------------------------------
    # Colour control

    def set_color(self, r: int, g: int, b: int) -> None:
        """Set every pixel to the given colour and push the update."""
        with self._lock:
            if self._strip is None:
                return
            color = _make_neo_color(r, g, b)
            for i in range(self.config.num_pixels):
                self._strip.setPixelColor(i, color)
            self._strip.show()

    def set_standby(self) -> None:
        """Show the configured standby colour."""
        r, g, b = self.config.standby_color
        self.set_color(r, g, b)

    def off(self) -> None:
        """Turn all pixels off."""
        self.set_color(0, 0, 0)

    # ------------------------------------------------------------------
    # Alert integration

    def start_alert(
        self,
        r: Optional[int] = None,
        g: Optional[int] = None,
        b: Optional[int] = None,
    ) -> None:
        """React to an active EAS alert.

        Sets the alert colour (or the configured default) and begins the
        flash pattern when ``flash_on_alert`` is enabled.

        Args:
            r: Red component override (0-255).  Uses ``config.alert_color`` when
               ``None``.
            g: Green component override.
            b: Blue component override.
        """
        ar, ag, ab = self.config.alert_color
        red = r if r is not None else ar
        green = g if g is not None else ag
        blue = b if b is not None else ab

        if self.config.flash_on_alert:
            self.start_flash(red, green, blue)
        else:
            self.stop_flash()
            self.set_color(red, green, blue)

        if self.logger:
            self.logger.info(
                "NeoPixel alert active: color=(%d,%d,%d), flash=%s",
                red, green, blue, self.config.flash_on_alert,
            )

    def end_alert(self) -> None:
        """Return the strip to standby after an alert has ended."""
        self.stop_flash()
        self.set_standby()
        if self.logger:
            self.logger.info("NeoPixel alert ended; returning to standby colour")

    # ------------------------------------------------------------------
    # Flash pattern

    def start_flash(self, r: int, g: int, b: int) -> None:
        """Begin an alternating flash between (r, g, b) and off.

        If a flash is already running it is replaced.
        """
        self.stop_flash()

        self._flash_stop.clear()
        self._flash_thread = threading.Thread(
            target=self._flash_worker,
            kwargs={"r": r, "g": g, "b": b},
            daemon=True,
            name=f"neopixel-flash-gpio{self.config.gpio_pin}",
        )
        self._flash_thread.start()

    def stop_flash(self) -> None:
        """Signal the flash thread to stop and wait for it to exit."""
        self._flash_stop.set()
        thread = self._flash_thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._flash_thread = None

    def _flash_worker(self, *, r: int, g: int, b: int) -> None:
        interval = max(MIN_FLASH_INTERVAL_MS, self.config.flash_interval_ms) / 1000.0
        phase = 0
        while not self._flash_stop.is_set():
            if phase == 0:
                self.set_color(r, g, b)
            else:
                self.set_color(0, 0, 0)
            phase = 1 - phase
            if self._flash_stop.wait(interval):
                break
        # Leave strip in standby state when flash ends
        self.set_standby()

    # ------------------------------------------------------------------
    # Status

    @property
    def is_available(self) -> bool:
        """``True`` when the real rpi_ws281x hardware is in use."""
        return self._available

    def get_status(self) -> Dict[str, Any]:
        """Return a status dict suitable for the web UI / Redis metrics."""
        return {
            "available": self._available,
            "gpio_pin": self.config.gpio_pin,
            "num_pixels": self.config.num_pixels,
            "brightness": self.config.brightness,
            "led_order": self.config.led_order,
            "standby_color": self.config.standby_color,
            "alert_color": self.config.alert_color,
            "flash_on_alert": self.config.flash_on_alert,
            "flash_interval_ms": self.config.flash_interval_ms,
            "flashing": self._flash_thread is not None and self._flash_thread.is_alive(),
        }
