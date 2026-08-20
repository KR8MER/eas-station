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

"""USB tower light support (Adafruit #5125 and ANDONT stack lights)."""

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional



# ---------------------------------------------------------------------------
# USB Tower Light support (Adafruit #5125 / CH34x-based stack lights)
# ---------------------------------------------------------------------------

# Command byte protocol: high-nibble = action (0x1x=on, 0x2x=off, 0x4x=blink)
#                        low-nibble  = segment (0x?1=red, 0x?2=yellow,
#                                               0x?4=green, 0x?8=buzzer)
_TOWER_CMD_RED_ON     = 0x11
_TOWER_CMD_RED_OFF    = 0x21
_TOWER_CMD_RED_BLINK  = 0x41
_TOWER_CMD_YEL_ON     = 0x12
_TOWER_CMD_YEL_OFF    = 0x22
_TOWER_CMD_YEL_BLINK  = 0x42
_TOWER_CMD_GRN_ON     = 0x14
_TOWER_CMD_GRN_OFF    = 0x24
_TOWER_CMD_GRN_BLINK  = 0x44
_TOWER_CMD_BUZ_ON     = 0x18
_TOWER_CMD_BUZ_OFF    = 0x28
_TOWER_CMD_BUZ_BLINK  = 0x48


# ---------------------------------------------------------------------------
# ANDONT 7-colour USB stack light protocol
#
# Frame: 0xFF <lighting mode> <buzzer mode> <flash frequency> 0xAA
# e.g. FF 02 01 01 AA -> green light with buzzer, steady-on, not flashing
# ---------------------------------------------------------------------------
_ANDONT_FRAME_START = 0xFF
_ANDONT_FRAME_END   = 0xAA

_ANDONT_COLOR_CODES = {
    "off":     0x01,
    "green":   0x02,
    "blue":    0x03,
    "red":     0x04,
    "cyan":    0x05,
    "yellow":  0x06,
    "magenta": 0x07,
    "white":   0x08,
}

# The vendor's published table lists 0x01=on / 0x02=off, but real
# hardware behaves the opposite way (confirmed on an actual ANDONT
# light): 0x02 sounds the buzzer, 0x01 silences it.
_ANDONT_BUZZER_ON  = 0x02
_ANDONT_BUZZER_OFF = 0x01

_ANDONT_FLASH_NONE = 0x01  # steady on
_ANDONT_FLASH_FAST = 0x02  # ~0.85 s per cycle

TOWER_LIGHT_PROTOCOLS = ("adafruit", "andont")

# Colours selectable per state. The Adafruit #5125 only has red/yellow/green
# segments; unsupported colours fall back to that protocol's default.
TOWER_LIGHT_COLORS = ("red", "yellow", "green", "blue", "cyan", "magenta", "white")

# Adafruit per-segment (on, off, blink) command bytes.
_TOWER_SEGMENT_CMDS = {
    "red":    (_TOWER_CMD_RED_ON, _TOWER_CMD_RED_OFF, _TOWER_CMD_RED_BLINK),
    "yellow": (_TOWER_CMD_YEL_ON, _TOWER_CMD_YEL_OFF, _TOWER_CMD_YEL_BLINK),
    "green":  (_TOWER_CMD_GRN_ON, _TOWER_CMD_GRN_OFF, _TOWER_CMD_GRN_BLINK),
}


@dataclass
class TowerLightConfig:
    """Configuration for a USB serial stack light.

    Two wire protocols are supported, selected by :attr:`protocol`:

    * ``"adafruit"`` — Adafruit USB Tri-Color Tower Light (#5125) and
      compatible CH34x lights. Three independent segments (red, yellow,
      green) plus a buzzer, single-byte commands. Only red / yellow /
      green are valid state colours; anything else falls back to the
      state default.
    * ``"andont"`` — ANDONT 7-colour USB stack light. One colour at a
      time from off / green / blue / red / cyan / yellow / magenta /
      white, driven by ``FF <color> <buzzer> <flash> AA`` frames.
    """

    serial_port: str = "/dev/ttyUSB0"  # Serial port path (e.g. /dev/ttyUSB0)
    baudrate: int = 9600               # Fixed at 9600 for these devices
    protocol: str = "adafruit"         # 'adafruit' or 'andont'
    # Alert response configuration
    alert_buzzer: bool = False         # Sound buzzer on active alert
    buzzer_disabled: bool = False      # Master kill switch — never sound the buzzer
    incoming_uses_yellow: bool = True  # Indicate the incoming (pre-alert) state
    blink_on_alert: bool = True        # Use hardware blink/flash mode during alerts
    # State -> colour mapping
    standby_color: str = "green"       # System ready
    incoming_color: str = "yellow"     # Alert received, playout not started
    alert_color: str = "red"           # Active alert
    test_color: str = "cyan"           # Test broadcasts (RWT/RMT/NPT/DMO)
    fault_enabled: bool = True         # Indicate Redis / alert-pipeline loss
    fault_color: str = "magenta"       # System fault
    # Dead air: a monitored source has gone silent for longer than its
    # configured hold-off. Ranks with the other faults (above any alert
    # indication) because a silent monitored source means the station is
    # not monitoring anything -- the one failure no other indicator shows.
    silence_enabled: bool = True
    silence_color: str = "magenta"     # Dead air on a monitored source
    silence_buzzer: bool = False       # Sound the tower buzzer on dead air
    # Pending Alerts: alerts held in the gated-alerts review queue
    gate_pending_enabled: bool = True  # Indicate alerts awaiting operator review
    gate_pending_color: str = "blue"   # Pending Alerts queue non-empty
    # Severity-based alert colours (replace alert_color when enabled)
    severity_colors_enabled: bool = False
    warning_color: str = "red"         # WRN product class
    watch_color: str = "yellow"        # WCH product class
    advisory_color: str = "white"      # ADV / everything else
    # Quiet hours: standby light off on a schedule (alerts still show)
    quiet_enabled: bool = False
    quiet_start: str = "22:00"         # HH:MM local time
    quiet_end: str = "07:00"


class TowerLightController:
    """Controller for the Adafruit USB Tri-Color Tower Light (product #5125).

    Uses a single-byte serial command protocol to independently control three
    LED colours (red, yellow, green) and a buzzer over a CH34x USB-UART
    adapter.

    The device is entirely self-contained; no GPIO pins are required.  It
    integrates with the same alert lifecycle as :class:`GPIOController` and
    :class:`NeopixelController`.

    Example::

        config = TowerLightConfig(serial_port="/dev/ttyUSB1")
        tower = TowerLightController(config, logger=logger)
        if tower.start():
            tower.start_alert()    # Red blink + optional buzzer
            ...
            tower.end_alert()      # Return to green standby
            tower.cleanup()
    """

    def __init__(self, config: TowerLightConfig, logger=None) -> None:
        self.config = config
        self.logger = logger
        self._serial: Optional[Any] = None
        self._available = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Lifecycle

    def start(self) -> bool:
        """Open the serial port and set the tower to standby (green on).

        Returns ``True`` when the port was opened successfully.
        """
        with self._lock:
            try:
                import serial  # pyserial – already in requirements.txt

                self._serial = serial.Serial(
                    self.config.serial_port,
                    self.config.baudrate,
                    timeout=1,
                )
                # CH340-based lights can drop bytes written immediately
                # after the port opens (the adapter resets on open), so
                # let it settle before the first state frame goes out.
                time.sleep(1.0)
                self._available = True
                if self.logger:
                    self.logger.info(
                        "USB tower light opened on %s at %d baud",
                        self.config.serial_port,
                        self.config.baudrate,
                    )
            except Exception as exc:  # pragma: no cover - device-dependent
                self._available = False
                if self.logger:
                    self.logger.warning(
                        "USB tower light unavailable on %s: %s",
                        self.config.serial_port,
                        exc,
                    )

            self.set_standby()
            return self._available

    def cleanup(self) -> None:
        """Turn everything off and close the serial port."""
        with self._lock:
            self.all_off()
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
            self._available = False

    # ------------------------------------------------------------------
    # Low-level command dispatch

    def _send(self, command: int) -> bool:
        """Write a single command byte to the serial port.

        Returns ``True`` on success, ``False`` on failure (e.g. port closed).
        """
        if self._serial is None:
            return False
        try:
            self._serial.write(bytes([command]))
            return True
        except Exception as exc:  # pragma: no cover - device-dependent
            if self.logger:
                self.logger.warning("Tower light write failed: %s", exc)
            return False

    def _is_andont(self) -> bool:
        return (self.config.protocol or "adafruit").strip().lower() == "andont"

    def _send_andont(self, color: str, buzzer_on: bool = False, flash: bool = False) -> bool:
        """Write one complete ANDONT state frame.

        The ANDONT light has no per-segment commands — every write is a
        full ``FF <color> <buzzer> <flash> AA`` frame that replaces the
        previous state (one colour at a time).
        """
        if self._serial is None:
            return False
        frame = bytes([
            _ANDONT_FRAME_START,
            _ANDONT_COLOR_CODES.get(color, _ANDONT_COLOR_CODES["off"]),
            _ANDONT_BUZZER_ON if buzzer_on else _ANDONT_BUZZER_OFF,
            _ANDONT_FLASH_FAST if flash else _ANDONT_FLASH_NONE,
            _ANDONT_FRAME_END,
        ])
        try:
            self._serial.write(frame)
            return True
        except Exception as exc:  # pragma: no cover - device-dependent
            if self.logger:
                self.logger.warning("Tower light write failed: %s", exc)
            return False

    def show_state(self, color: str, flash: bool = False, buzzer: bool = False,
                   fallback: str = "off") -> None:
        """Drive the light to an arbitrary colour/flash/buzzer state.

        ``color`` may be ``"off"``. Colours the active protocol cannot
        render fall back to *fallback*, then to off. The buzzer master
        kill switch (:attr:`TowerLightConfig.buzzer_disabled`) is
        enforced here so no caller can bypass it.
        """
        if self.config.buzzer_disabled:
            buzzer = False
        color = str(color or "").strip().lower()
        fallback = str(fallback or "").strip().lower()
        with self._lock:
            if self._is_andont():
                valid = color if color in _ANDONT_COLOR_CODES else (
                    fallback if fallback in _ANDONT_COLOR_CODES else "off")
                self._send_andont(valid, buzzer_on=buzzer, flash=flash)
                return
            valid = color if color in _TOWER_SEGMENT_CMDS else (
                fallback if fallback in _TOWER_SEGMENT_CMDS else None)
            self._send(_TOWER_CMD_BUZ_ON if buzzer else _TOWER_CMD_BUZ_OFF)
            for name, (_on, off_cmd, _blink) in _TOWER_SEGMENT_CMDS.items():
                if name != valid:
                    self._send(off_cmd)
            if valid is not None:
                on_cmd, _off, blink_cmd = _TOWER_SEGMENT_CMDS[valid]
                self._send(blink_cmd if flash else on_cmd)

    # ------------------------------------------------------------------
    # Segment control (Adafruit protocol primitives)

    def red(self, state: str = "on") -> None:
        """Control the red segment.  *state* is ``'on'``, ``'off'``, or ``'blink'``."""
        with self._lock:
            cmd = {
                "on":    _TOWER_CMD_RED_ON,
                "off":   _TOWER_CMD_RED_OFF,
                "blink": _TOWER_CMD_RED_BLINK,
            }.get(state.lower(), _TOWER_CMD_RED_OFF)
            self._send(cmd)

    def yellow(self, state: str = "on") -> None:
        """Control the yellow segment.  *state* is ``'on'``, ``'off'``, or ``'blink'``."""
        with self._lock:
            cmd = {
                "on":    _TOWER_CMD_YEL_ON,
                "off":   _TOWER_CMD_YEL_OFF,
                "blink": _TOWER_CMD_YEL_BLINK,
            }.get(state.lower(), _TOWER_CMD_YEL_OFF)
            self._send(cmd)

    def green(self, state: str = "on") -> None:
        """Control the green segment.  *state* is ``'on'``, ``'off'``, or ``'blink'``."""
        with self._lock:
            cmd = {
                "on":    _TOWER_CMD_GRN_ON,
                "off":   _TOWER_CMD_GRN_OFF,
                "blink": _TOWER_CMD_GRN_BLINK,
            }.get(state.lower(), _TOWER_CMD_GRN_OFF)
            self._send(cmd)

    def buzzer(self, state: str = "on") -> None:
        """Control the buzzer.  *state* is ``'on'``, ``'off'``, or ``'blink'``."""
        with self._lock:
            cmd = {
                "on":    _TOWER_CMD_BUZ_ON,
                "off":   _TOWER_CMD_BUZ_OFF,
                "blink": _TOWER_CMD_BUZ_BLINK,
            }.get(state.lower(), _TOWER_CMD_BUZ_OFF)
            self._send(cmd)

    def all_off(self) -> None:
        """Turn all segments and the buzzer off."""
        self.show_state("off", flash=False, buzzer=False)

    def set_standby(self) -> None:
        """Show 'system ready': the configured standby colour (default green)."""
        self.show_state(self.config.standby_color, flash=False, buzzer=False,
                        fallback="green")

    # ------------------------------------------------------------------
    # Alert integration

    def start_incoming_alert(self) -> None:
        """Signal that an alert has been received but playout has not started.

        Shows the configured incoming colour (default yellow), blinking
        when :attr:`TowerLightConfig.blink_on_alert` is set. Does nothing
        when :attr:`TowerLightConfig.incoming_uses_yellow` is ``False``.
        """
        if not self.config.incoming_uses_yellow:
            return

        self.show_state(self.config.incoming_color, flash=self.config.blink_on_alert,
                        buzzer=False, fallback="yellow")
        if self.logger:
            self.logger.info(
                "Tower light: incoming alert (%s %s)",
                self.config.incoming_color,
                "blink" if self.config.blink_on_alert else "on",
            )

    def start_alert(self) -> None:
        """Signal an active alert: configured colour on/blink, optional buzzer."""
        self.show_state(self.config.alert_color, flash=self.config.blink_on_alert,
                        buzzer=self.config.alert_buzzer, fallback="red")
        if self.logger:
            self.logger.info(
                "Tower light: alert active (%s %s, buzzer=%s)",
                self.config.alert_color,
                "blink" if self.config.blink_on_alert else "on",
                self.config.alert_buzzer and not self.config.buzzer_disabled,
            )

    def end_alert(self) -> None:
        """Return to standby after an alert ends."""
        self.set_standby()
        if self.logger:
            self.logger.info("Tower light: alert ended; returning to standby")

    # ------------------------------------------------------------------
    # Status

    @property
    def is_available(self) -> bool:
        """``True`` when the serial port was successfully opened."""
        return self._available

    def get_status(self) -> Dict[str, Any]:
        """Return a status dict suitable for the web UI / Redis metrics."""
        return {
            "available": self._available,
            "serial_port": self.config.serial_port,
            "baudrate": self.config.baudrate,
            "protocol": self.config.protocol,
            "alert_buzzer": self.config.alert_buzzer,
            "buzzer_disabled": self.config.buzzer_disabled,
            "blink_on_alert": self.config.blink_on_alert,
            "standby_color": self.config.standby_color,
            "incoming_color": self.config.incoming_color,
            "alert_color": self.config.alert_color,
            "test_color": self.config.test_color,
            "fault_enabled": self.config.fault_enabled,
            "fault_color": self.config.fault_color,
            "gate_pending_enabled": self.config.gate_pending_enabled,
            "gate_pending_color": self.config.gate_pending_color,
            "severity_colors_enabled": self.config.severity_colors_enabled,
            "quiet_enabled": self.config.quiet_enabled,
        }
