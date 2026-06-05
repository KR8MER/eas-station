#!/usr/bin/env python3
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

"""
Complete Alpha 9120C LED Sign Controller
Full M-Protocol implementation with all documented features
Based on Alpha Communications M-Protocol specification
"""

import socket
import time
import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypedDict, Type, TypeVar, Union

import json
import re

from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS, ensure_list
from app_utils.alert_sources import normalize_alert_source

try:
    import serial as _pyserial  # pyserial
except ImportError:  # pragma: no cover - pyserial is in requirements.txt
    _pyserial = None


class _SerialSocketAdapter:
    """Socket-compatible wrapper around a pyserial connection.

    The Alpha M-Protocol send/receive code throughout this module was
    written against the TCP socket API (``sendall``, ``recv``,
    ``settimeout``, ``gettimeout``, ``close``).  Rather than fork every
    call site for serial, we expose the same surface on top of pyserial
    so the same protocol code works unchanged over RS-232/RS-485.

    ``recv`` is expected to raise ``socket.timeout`` when no data is
    available within the configured timeout (that's how the existing
    handshake code signals "no ACK yet"), so we mirror that here.
    """

    def __init__(self, port: str, baudrate: int, timeout: float):
        if _pyserial is None:
            raise RuntimeError(
                "pyserial is required for LED serial connections but is not installed"
            )
        self._timeout = float(timeout) if timeout is not None else None
        self._serial = _pyserial.Serial(
            port=port,
            baudrate=int(baudrate),
            bytesize=_pyserial.EIGHTBITS,
            parity=_pyserial.PARITY_NONE,
            stopbits=_pyserial.STOPBITS_ONE,
            timeout=self._timeout,
            write_timeout=self._timeout,
        )

    # --- socket API surface the controller uses ---

    def sendall(self, data: bytes) -> None:
        self._serial.write(data)
        # Flush so the sign sees complete frames even if the OS buffers
        # would otherwise hold them pending.
        try:
            self._serial.flush()
        except Exception:
            pass

    def recv(self, bufsize: int) -> bytes:
        # pyserial.read() returns "" / b"" if timeout expires before any
        # byte arrives.  The socket code throughout this module depends on
        # ``socket.timeout`` being raised in that case, so translate.
        data = self._serial.read(bufsize)
        if not data:
            raise socket.timeout("serial read timed out")
        return data

    def settimeout(self, value: Optional[float]) -> None:
        self._timeout = value
        self._serial.timeout = value
        self._serial.write_timeout = value

    def gettimeout(self) -> Optional[float]:
        return self._timeout

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass


class MessagePriority(Enum):
    """Message priority levels"""
    EMERGENCY = 0
    URGENT = 1
    NORMAL = 2
    LOW = 3


class Color(Enum):
    """M-Protocol Color Codes (1CH + character)"""
    RED = '1'  # 1CH + "1" (31H) = Red
    GREEN = '2'  # 1CH + "2" (32H) = Green
    AMBER = '3'  # 1CH + "3" (33H) = Amber
    DIM_RED = '4'  # 1CH + "4" (34H) = Dim red
    DIM_GREEN = '5'  # 1CH + "5" (35H) = Dim green
    BROWN = '6'  # 1CH + "6" (36H) = Brown
    ORANGE = '7'  # 1CH + "7" (37H) = Orange
    YELLOW = '8'  # 1CH + "8" (38H) = Yellow
    RAINBOW_1 = '9'  # 1CH + "9" (39H) = Rainbow 1
    RAINBOW_2 = 'A'  # 1CH + "A" (41H) = Rainbow 2
    COLOR_MIX = 'B'  # 1CH + "B" (42H) = Color mix
    AUTO_COLOR = 'C'  # 1CH + "C" (43H) = Autocolor


class Font(Enum):
    """M-Protocol Font Selection (1AH + character)"""
    FONT_5x7 = '1'  # 5x7 dots
    FONT_6x7 = '2'  # 6x7 dots
    FONT_7x9 = '3'  # 7x9 dots
    FONT_8x7 = '4'  # 8x7 dots
    FONT_7x11 = '5'  # 7x11 dots
    FONT_15x7 = '6'  # 15x7 dots
    FONT_19x7 = '7'  # 19x7 dots
    FONT_7x13 = '8'  # 7x13 dots
    FONT_16x9 = '9'  # 16x9 dots
    FONT_32x16 = ':'  # 32x16 dots


class DisplayMode(Enum):
    """Display Mode Commands (1BH + character)"""
    ROTATE = 'a'  # Rotate (not for line mode)
    HOLD = 'b'  # Hold
    FLASH = 'c'  # Flash
    ROLL_UP = 'e'  # Roll up
    ROLL_DOWN = 'f'  # Roll down
    ROLL_LEFT = 'g'  # Roll left
    ROLL_RIGHT = 'h'  # Roll right
    WIPE_UP = 'i'  # Wipe up
    WIPE_DOWN = 'j'  # Wipe down
    WIPE_LEFT = 'k'  # Wipe left
    WIPE_RIGHT = 'l'  # Wipe right
    SCROLL = 'm'  # Scroll
    AUTO_MODE = 'o'  # Automode
    ROLL_IN = 'p'  # Roll in
    ROLL_OUT = 'q'  # Roll out
    WIPE_IN = 'r'  # Wipe in
    WIPE_OUT = 's'  # Wipe out
    COMPRESSED_ROTATE = 't'  # Compressed rotate
    EXPLODE = 'u'  # Explode
    CLOCK = 'v'  # Clock

    # Special (string) display modes.  Per the Alpha M-Protocol these are
    # encoded as the mode character 'n' followed by a one-character sub-code.
    # Because the frame builder appends ``mode.value`` verbatim after
    # ``ESC + position``, a two-character value (e.g. 'n0') yields exactly
    # ``ESC + position + n + 0`` on the wire, which is the correct encoding.
    # Hardware support depends on the sign's firmware -- verify on the
    # physical sign before relying on any of these.
    TWINKLE = 'n0'        # Twinkle
    SPARKLE = 'n1'        # Sparkle
    SNOW = 'n2'           # Snow
    INTERLOCK = 'n3'      # Interlock
    SWITCH = 'n4'         # Switch
    SLIDE = 'n5'          # Slide
    SPRAY = 'n6'          # Spray
    STARBURST = 'n7'      # Starburst
    WELCOME = 'n8'        # Welcome
    SLOT_MACHINE = 'n9'   # Slot machine
    NEWS_FLASH = 'nA'     # News flash
    TRUMPET = 'nB'        # Trumpet animation
    CYCLE_COLORS = 'nC'   # Cycle colors


class Speed(Enum):
    """Speed Settings (15H + character)"""
    SPEED_1 = '1'  # Slowest
    SPEED_2 = '2'  # Slow
    SPEED_3 = '3'  # Medium
    SPEED_4 = '4'  # Fast
    SPEED_5 = '5'  # Fastest


class SpecialFunction(Enum):
    """Character attribute control sequences (Alpha protocol ASCII table, p.80-81).

    Each value is the *complete* control sequence emitted inline in a TEXT
    file — these are distinct control codes, NOT all ``1EH`` + a digit.  The
    earlier revision routed every attribute through ``1EH`` (character spacing)
    with the wrong argument, so wide/descender/flash all did the wrong thing and
    emergency-alert flashing never worked.
    """
    WIDE_CHAR_ON = '\x12'        # 12H = enable wide characters
    WIDE_CHAR_OFF = '\x11'       # 11H = disable wide characters (default)
    TRUE_DESC_ON = '\x06\x31'    # 06H + '1' = true descenders on
    TRUE_DESC_OFF = '\x06\x30'   # 06H + '0' = true descenders off (default)
    CHAR_FLASH_ON = '\x07\x31'   # 07H + '1' = character flash on
    CHAR_FLASH_OFF = '\x07\x30'  # 07H + '0' = character flash off (default)
    FIXED_WIDTH = '\x1e\x31'     # 1EH + '1' = fixed-width characters
    PROP_WIDTH = '\x1e\x30'      # 1EH + '0' = proportional characters (default)


class TimeFormat(Enum):
    """Time Format Codes (13H + character)"""
    MMDDYY = '1'  # MM/DD/YY
    DDMMYY = '2'  # DD/MM/YY
    MMDDYYYY = '3'  # MM/DD/YYYY
    DDMMYYYY = '4'  # DD/MM/YYYY
    YYMMDD = '5'  # YY-MM-DD
    YYYYMMDD = '6'  # YYYY-MM-DD
    TIME_12H = '7'  # 12 hour format
    TIME_24H = '8'  # 24 hour format


class ReadSpecialExtCommand(Enum):
    """Type F - Read Special Functions (Extended)"""
    READ_SERIAL_NUMBER = 0x24  # Read sign serial number
    READ_MODEL_NUMBER = 0x25   # Read sign model
    READ_VERSION = 0x26        # Read firmware version
    READ_MEMORY_CONFIG = 0x30  # Read memory configuration
    READ_TEMPERATURE = 0x35    # Read internal temperature


class WriteSpecialExtCommand(Enum):
    """Write SPECIAL FUNCTION labels — the byte after ``E`` (manual Table 15).

    Codes verified against Alpha Sign Communications Protocol 9708-8061F,
    pp.21-26.  See docs/reference/protocols/ALPHA_M_PROTOCOL.md.
    """
    SET_TIME_OF_DAY = 0x20     # " "  Set Time of Day (HhMm, 24-hour)
    SET_SPEAKER = 0x21         # "!"  Enable/Disable speaker ("00"/"FF")
    SET_MEMORY = 0x24          # "$"  Clear Memory / Set Memory Configuration
    SET_DAY_OF_WEEK = 0x26     # "&"  Set Day of Week ("1"=Sun .. "7"=Sat)
    SET_TIME_FORMAT = 0x27     # "'"  Set Time Format ("S"=am/pm, "M"=24h)
    SET_RUN_TIME_TABLE = 0x29  # ")"  Set Run Time Table (FQQQQ)
    SOFT_RESET = 0x2C          # ","  Soft Reset (no data, non-destructive)
    SET_RUN_SEQUENCE = 0x2E    # "."  Set Run Sequence (KPF)
    SET_DIMMING = 0x2F         # "/"  Set Dimming Register (WWww, Solar signs)
    SET_RUN_DAY_TABLE = 0x32   # "2"  Set Run Day Table (FSs)
    SET_COUNTER = 0x35         # "5"  Set Counter
    SET_SERIAL_ADDRESS = 0x37  # "7"  Set Serial Address (two hex chars)
    SET_DATE = 0x3B            # ";"  Set Date (mmddyy)

    # Backwards-compatibility alias: older callers referenced SET_TIME_DATE.
    SET_TIME_DATE = 0x20


class ReadTextCommand(Enum):
    """Type B - Read Text File"""
    READ_TEXT_FILE = 0x42      # Read text from file label


class LineSegmentSpec(TypedDict, total=False):
    text: str
    color: Color
    rgb_color: str
    font: Font
    mode: DisplayMode
    speed: Speed
    special_functions: List[SpecialFunction]


class LineSpec(TypedDict, total=False):
    display_position: str
    font: Font
    color: Color
    rgb_color: str
    mode: DisplayMode
    speed: Speed
    special_functions: List[SpecialFunction]
    segments: List[LineSegmentSpec]


@dataclass
class FormatState:
    font: Optional[Font] = None
    color: Optional[Color] = None
    rgb_color: Optional[str] = None
    mode: Optional[DisplayMode] = None
    position: Optional[str] = None
    speed: Optional[Speed] = None


EnumType = TypeVar("EnumType", bound=Enum)


class Alpha9120CController:
    """Complete Alpha 9120C LED Sign Controller with full M-Protocol support"""

    LINE_POSITION_MAP: Tuple[str, ...] = tuple(chr(code) for code in range(0x20, 0x28))

    SOH = "\x01"
    STX = "\x02"
    ETX = "\x03"
    EOT = "\x04"
    ACK = b"\x06"
    NAK = b"\x15"
    # M-Protocol requires a wake-up sequence of NULL bytes at the head of
    # every transmission so the sign's UART can synchronise before the
    # SOH framing byte arrives.  The Alpha 9120C manual specifies five
    # NULLs as the minimum; some adapters lose the first byte or two so
    # we transmit five for headroom.
    WAKEUP = b"\x00\x00\x00\x00\x00"

    def __init__(
        self,
        host: str,
        port: int = 10001,
        sign_id: str = "01",
        timeout: int = 10,
        location_settings: Optional[Dict[str, Union[str, List[str]]]] = None,
        type_code: str = "Z",
        serial_port: Optional[str] = None,
        baudrate: int = 9600,
    ):
        """
        Initialize Alpha 9120C controller with full M-Protocol support

        Args:
            host: IP address of the LED sign (network mode)
            port: Communication port (network mode; default 10001)
            sign_id: Sign ID for multi-sign setups (default '01')
            timeout: Socket/serial timeout in seconds
            serial_port: Serial device (e.g. /dev/ttyUSB0).  When set the
                controller connects over RS-232/RS-485 instead of TCP; the
                ``host``/``port`` arguments are ignored in that mode.
            baudrate: Serial baud rate (default 9600, only used in serial
                mode).  The Alpha 9120C default per the M-Protocol manual.
        """
        self.host = host
        self.port = port
        self.sign_id = self._normalise_sign_id(sign_id)
        self.timeout = timeout
        self.type_code = self._normalise_type_code(type_code)
        self.logger = logging.getLogger(__name__)
        # Serial transport (optional).  When serial_port is set, we speak
        # the same M-Protocol frames over pyserial via _SerialSocketAdapter
        # instead of TCP.
        self.serial_port = serial_port
        self.baudrate = int(baudrate) if baudrate else 9600
        self.use_serial = bool(serial_port)
        self.location_settings = location_settings or DEFAULT_LOCATION_SETTINGS
        self.default_lines = self._normalise_lines(self.location_settings.get('led_default_lines'))

        # Alpha 9120C specifications
        self.max_chars_per_line = 20
        self.max_lines = 4
        self.supports_rgb = True
        self.supports_graphics = True

        # M-Protocol control characters
        self.ESC = '\x1B'  # Escape
        self.CR = '\x0D'  # Carriage return
        self.LF = '\x0A'  # Line feed

        # M-Protocol command characters
        self.COLOR_CMD = '\x1C'  # Color command prefix
        self.FONT_CMD = '\x1A'  # Font command prefix
        self.MODE_CMD = '\x1B'  # Display mode command prefix
        # NOTE: speed and character attributes are NOT a prefix + arg — speed is
        # a single byte 0x15-0x19 and each attribute has its own code (see the
        # Speed/SpecialFunction enums).  These two constants are retained only
        # for backwards reference and are no longer used to build frames.
        self.SPEED_CMD = '\x15'  # (legacy) Speed 1 control byte
        self.SPECIAL_CMD = '\x1E'  # (legacy) character-spacing control code
        self.TIME_CMD = '\x13'  # Time format prefix
        self.POSITION_CMD = '\x1F'  # Position command prefix

        # Connection management
        self.socket = None
        self.connected = False
        self.last_message = None
        self.last_update = None

        # ── Protocol frame debug capture ───────────────────────────────────
        # Ring buffer of the most recently transmitted M-Protocol frames so
        # the operator UI can show what was actually put on the wire.  Bounded
        # so it can never grow unboundedly during long-running operation.
        self._frame_history_max = 50
        self._frame_history: "deque[Dict[str, Any]]" = deque(maxlen=self._frame_history_max)
        self._frame_history_lock = threading.Lock()
        self._frame_history_seq = 0

        # Message storage
        self.current_messages = {}
        self.canned_messages = self._load_canned_messages()

        # Display state
        self.current_priority = MessagePriority.LOW
        self.display_active = True

        # Initialize connection
        self.connect()

    def _normalise_lines(self, lines: Optional[Union[List[str], str]]) -> List[str]:
        normalised = ensure_list(lines)
        trimmed = [str(line)[:20] for line in normalised[:4]]
        while len(trimmed) < 4:
            trimmed.append('')
        return trimmed

    def _load_canned_messages(self) -> Dict[str, Dict]:
        """Load predefined canned messages with full M-Protocol features"""
        county_name = str(self.location_settings.get('county_name', 'Configured County')).upper()
        welcome_lines = [
            'WELCOME TO',
            county_name,
            'EAS STATION',
            ''
        ]

        return {
            'welcome': {
                'lines': welcome_lines,
                'color': Color.GREEN,
                'font': Font.FONT_7x9,
                'mode': DisplayMode.WIPE_RIGHT,
                'speed': Speed.SPEED_3,
                'hold_time': 5,
                'priority': MessagePriority.LOW
            },
            'emergency_severe': {
                'lines': [
                    'EMERGENCY ALERT',
                    'SEVERE WEATHER',
                    'TAKE SHELTER',
                    'IMMEDIATELY'
                ],
                'color': Color.RED,
                'font': Font.FONT_7x13,
                'mode': DisplayMode.FLASH,
                'speed': Speed.SPEED_5,
                'hold_time': 2,
                'priority': MessagePriority.EMERGENCY,
                'special_functions': [SpecialFunction.CHAR_FLASH_ON]
            },
            'time_temp_display': {
                'lines': [
                    'CURRENT TIME',
                    '{time}',
                    'TEMPERATURE',
                    '{temp}°F'
                ],
                'color': Color.AMBER,
                'font': Font.FONT_7x11,
                'mode': DisplayMode.SCROLL,
                'speed': Speed.SPEED_2,
                'hold_time': 10,
                'priority': MessagePriority.LOW
            },
            'rainbow_test': {
                'lines': [
                    'RAINBOW TEST',
                    'COLOR CYCLING',
                    'ALPHA 9120C',
                    'M-PROTOCOL'
                ],
                'color': Color.RAINBOW_1,
                'font': Font.FONT_16x9,
                'mode': DisplayMode.EXPLODE,
                'speed': Speed.SPEED_4,
                'hold_time': 5,
                'priority': MessagePriority.NORMAL
            },
            'no_alerts': {
                'lines': self.default_lines,
                'color': Color.GREEN,
                'font': Font.FONT_7x9,
                'mode': DisplayMode.ROLL_LEFT,
                'speed': Speed.SPEED_2,
                'hold_time': 8,
                'priority': MessagePriority.NORMAL
            }
        }

    def _normalise_sign_id(self, raw_sign_id: str) -> str:
        """Ensure the sign address is two ASCII characters as required by the manual."""

        if not raw_sign_id:
            return "00"

        cleaned = re.sub(r"[^0-9A-Za-z]", "", str(raw_sign_id))
        if not cleaned:
            return "00"

        if len(cleaned) == 1:
            return cleaned.zfill(2).upper()

        return cleaned[:2].upper()

    def _coerce_enum(
        self,
        enum_cls: Type[EnumType],
        value: Optional[Union[EnumType, str]],
    ) -> Optional[EnumType]:
        if value is None:
            return None

        if isinstance(value, enum_cls):
            return value

        if isinstance(value, str):
            key = value.strip()
            if not key:
                return None
            try:
                return enum_cls[key.upper()]
            except KeyError:
                self.logger.warning("Ignoring unknown %s value: %s", enum_cls.__name__, value)
                return None

        self.logger.warning("Ignoring unsupported %s value: %s", enum_cls.__name__, value)
        return None

    def _coerce_special_functions(
        self,
        values: Optional[Sequence[Union[SpecialFunction, str]]],
    ) -> List[SpecialFunction]:
        if not values:
            return []

        special_functions: List[SpecialFunction] = []
        for item in values:
            if isinstance(item, SpecialFunction):
                if item not in special_functions:
                    special_functions.append(item)
                continue

            if isinstance(item, str):
                key = item.strip()
                if not key:
                    continue
                try:
                    enum_value = SpecialFunction[key.upper()]
                except KeyError:
                    self.logger.warning("Ignoring unknown special function: %s", item)
                    continue
                if enum_value not in special_functions:
                    special_functions.append(enum_value)

        return special_functions

    def _coerce_rgb(self, rgb_color: Optional[str]) -> Optional[str]:
        if not rgb_color:
            return None

        candidate = str(rgb_color).strip().upper()
        if self._is_valid_rgb(candidate):
            return candidate

        self.logger.warning("Ignoring invalid RGB color: %s", rgb_color)
        return None

    def _resolve_position(self, explicit: Optional[str], index: int) -> str:
        if explicit:
            char = str(explicit)[:1]
            if char:
                return char

        if 0 <= index < len(self.LINE_POSITION_MAP):
            return self.LINE_POSITION_MAP[index]

        return " "

    def _normalise_segment(self, segment: Union[str, LineSegmentSpec, Dict]) -> LineSegmentSpec:
        if isinstance(segment, str) or segment is None:
            return {'text': str(segment or '')}

        if not isinstance(segment, dict):
            self.logger.warning("Ignoring unsupported segment payload: %s", segment)
            return {'text': ''}

        text = str(segment.get('text', ''))
        normalised: LineSegmentSpec = {'text': text}

        font = self._coerce_enum(Font, segment.get('font'))
        if font:
            normalised['font'] = font

        color = self._coerce_enum(Color, segment.get('color'))
        if color:
            normalised['color'] = color

        rgb_value = self._coerce_rgb(segment.get('rgb_color'))
        if rgb_value:
            normalised['rgb_color'] = rgb_value

        mode = self._coerce_enum(DisplayMode, segment.get('mode'))
        if mode:
            normalised['mode'] = mode

        speed = self._coerce_enum(Speed, segment.get('speed'))
        if speed:
            normalised['speed'] = speed

        specials = self._coerce_special_functions(segment.get('special_functions'))
        if specials:
            normalised['special_functions'] = specials

        return normalised

    def _trim_segments(self, segments: List[LineSegmentSpec]) -> List[LineSegmentSpec]:
        remaining = self.max_chars_per_line
        trimmed: List[LineSegmentSpec] = []

        for segment in segments:
            text = segment.get('text', '') or ''
            if remaining <= 0:
                break

            allowed_text = text[:remaining]
            trimmed_segment = dict(segment)
            trimmed_segment['text'] = allowed_text
            trimmed.append(trimmed_segment)
            remaining -= len(allowed_text)

        if not trimmed:
            trimmed.append({'text': ''})

        return trimmed

    def _normalise_line_spec(
        self,
        raw_line: Union[str, LineSpec, Dict, None],
        index: int,
        default_display_position: Optional[str],
    ) -> LineSpec:
        if isinstance(raw_line, str) or raw_line is None:
            segments = [{'text': str(raw_line or '')}]
            return {
                'display_position': self._resolve_position(default_display_position if index == 0 else None, index),
                'segments': self._trim_segments(segments),
            }

        if not isinstance(raw_line, dict):
            self.logger.warning("Ignoring unsupported line payload: %s", raw_line)
            segments = [{'text': str(raw_line)}]
            return {
                'display_position': self._resolve_position(default_display_position if index == 0 else None, index),
                'segments': self._trim_segments(segments),
            }

        line_spec: LineSpec = {}

        explicit_position = raw_line.get('display_position')
        if explicit_position is None and index == 0:
            explicit_position = default_display_position
        line_spec['display_position'] = self._resolve_position(explicit_position, index)

        font = self._coerce_enum(Font, raw_line.get('font'))
        if font:
            line_spec['font'] = font

        color = self._coerce_enum(Color, raw_line.get('color'))
        if color:
            line_spec['color'] = color

        rgb_value = self._coerce_rgb(raw_line.get('rgb_color'))
        if rgb_value:
            line_spec['rgb_color'] = rgb_value

        mode = self._coerce_enum(DisplayMode, raw_line.get('mode'))
        if mode:
            line_spec['mode'] = mode

        speed = self._coerce_enum(Speed, raw_line.get('speed'))
        if speed:
            line_spec['speed'] = speed

        specials = self._coerce_special_functions(raw_line.get('special_functions'))
        if specials:
            line_spec['special_functions'] = specials

        raw_segments = raw_line.get('segments')
        segments: List[LineSegmentSpec] = []
        if isinstance(raw_segments, list):
            for raw_segment in raw_segments:
                segments.append(self._normalise_segment(raw_segment))
        else:
            segments.append(self._normalise_segment({
                'text': raw_line.get('text', ''),
                'font': raw_line.get('font'),
                'color': raw_line.get('color'),
                'rgb_color': raw_line.get('rgb_color'),
                'mode': raw_line.get('mode'),
                'speed': raw_line.get('speed'),
                'special_functions': raw_line.get('special_functions'),
            }))

        line_spec['segments'] = self._trim_segments(segments)
        return line_spec

    def _normalise_line_definitions(
        self,
        lines: Sequence[Union[str, LineSpec, Dict, None]],
        default_display_position: Optional[str],
    ) -> List[LineSpec]:
        normalised: List[LineSpec] = []
        for index, raw_line in enumerate(list(lines)[:self.max_lines]):
            normalised.append(self._normalise_line_spec(raw_line, index, default_display_position))

        while len(normalised) < self.max_lines:
            index = len(normalised)
            normalised.append({
                'display_position': self._resolve_position(None, index),
                'segments': [{'text': ''}],
            })

        return normalised

    def _normalise_type_code(self, raw_type: str) -> str:
        """Type codes are a single printable character in the M-Protocol header."""

        if not raw_type:
            return "Z"

        candidate = str(raw_type)[0].upper()
        if not candidate.isalnum():
            return "Z"
        return candidate

    def connect(self) -> bool:
        """Establish connection to Alpha 9120C sign (TCP or serial)."""
        try:
            if self.socket:
                self.socket.close()

            if self.use_serial:
                self.socket = _SerialSocketAdapter(
                    self.serial_port,
                    self.baudrate,
                    self.timeout,
                )
                self.connected = True
                self.logger.info(
                    "Connected to Alpha 9120C over serial %s @ %d baud",
                    self.serial_port,
                    self.baudrate,
                )
            else:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self.timeout)
                self.socket.connect((self.host, self.port))
                # Keep the (usually idle) link to the serial-to-Ethernet
                # adapter alive so a half-open connection is detected and
                # reconnected instead of silently swallowing the next frame.
                try:
                    from app_utils.network import enable_tcp_keepalive
                    enable_tcp_keepalive(self.socket)
                except Exception as exc:  # pragma: no cover - best effort
                    self.logger.debug("TCP keep-alive not enabled: %s", exc)
                self.connected = True
                self.logger.info(
                    "Connected to Alpha 9120C at %s:%s", self.host, self.port
                )

            # Send initialization sequence
            if self._send_initialization():
                return True
            else:
                self.logger.warning("Initialization failed, but connection established")
                return True

        except ConnectionRefusedError as exc:
            self.logger.warning(
                "Alpha 9120C at %s:%s refused the connection: %s. "
                "Set LED_SIGN_IP/LED_SIGN_PORT or start the hardware emulator to enable LED output.",
                self.host,
                self.port,
                exc,
            )
            self.connected = False
            return False
        except OSError as exc:
            target = (
                f"serial {self.serial_port} @ {self.baudrate} baud"
                if self.use_serial
                else f"{self.host}:{self.port}"
            )
            self.logger.error(
                "Failed to connect to Alpha 9120C at %s due to OS error: %s",
                target,
                exc,
            )
            self.connected = False
            return False
        except Exception as exc:
            self.logger.error("Failed to connect to Alpha 9120C: %s", exc)
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from Alpha 9120C"""
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        self.connected = False
        self.logger.info("Disconnected from Alpha 9120C")

    def _send_initialization(self) -> bool:
        """Send initialization sequence to Alpha 9120C"""
        try:
            # Send test message to verify connection
            test_lines = ['ALPHA 9120C', 'INITIALIZED', 'M-PROTOCOL', 'READY']
            init_msg = self._build_message(
                test_lines,
                color=Color.GREEN,
                font=Font.FONT_7x9,
                mode=DisplayMode.WIPE_IN,
                speed=Speed.SPEED_3
            )
            return self._send_raw_message(init_msg)
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            return False

    def _build_message(
        self,
        lines: Sequence[Union[str, LineSpec, Dict, None]],
        color: Color = Color.GREEN,
        font: Font = Font.FONT_7x9,
        mode: DisplayMode = DisplayMode.HOLD,
        speed: Speed = Speed.SPEED_3,
        hold_time: int = 5,
        special_functions: Optional[Sequence[Union[SpecialFunction, str]]] = None,
        rgb_color: str = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        file_label: str = "A",
        display_position: str = " ",
    ) -> Optional[bytes]:
        """Build a complete M-Protocol message with all features.

        Format: <SOH><TYPE><ADDR><STX><CMD><FILE><formatting><content><ETX><CHECKSUM>
        """
        try:
            # Normalise line definitions so each entry includes trimmed segments and
            # a resolved display-position byte.  The controller accepts plain
            # strings for backwards compatibility but operators can now provide a
            # structure that specifies colours, effects, and special functions on
            # a per-line or per-segment basis.
            normalised_lines = self._normalise_line_definitions(lines, display_position)

            # Message components
            # The manual specifies that the "Write Text File" command is a single
            # byte (`A`) followed by the one-character file label.  The previous
            # revision prefixed the payload with the string ``"AA"`` and then
            # added the label again which produced frames that began with
            # ``AAA``.  Alpha signs interpret the first two bytes as the command
            # and file label, so the redundant "A" resulted in the file name
            # being shifted and the payload rejected.  Build the command exactly
            # as documented: the single command byte and a single label
            # character.
            cmd = "A"  # Write text file command
            file_label = (file_label or "A").strip() or "A"
            file_label = file_label[0].upper()

            base_specials = self._coerce_special_functions(special_functions)
            default_rgb = self._coerce_rgb(rgb_color)
            state = FormatState()

            content_parts: List[str] = []

            for line_index, line_spec in enumerate(normalised_lines):
                line_segments = list(line_spec.get('segments', [])) or [{'text': ''}]
                line_specials = line_spec.get('special_functions', [])
                position_char = line_spec.get('display_position') or self._resolve_position(None, line_index)

                for segment in line_segments:
                    segment_text = segment.get('text', '') or ''

                    effective_font = segment.get('font') or line_spec.get('font') or font
                    effective_rgb = segment.get('rgb_color') or line_spec.get('rgb_color') or default_rgb
                    effective_color: Optional[Color]
                    if effective_rgb:
                        effective_color = None
                    else:
                        effective_color = segment.get('color') or line_spec.get('color') or color
                    effective_mode = segment.get('mode') or line_spec.get('mode') or mode
                    effective_speed = segment.get('speed') or line_spec.get('speed') or speed

                    combined_specials: List[SpecialFunction] = []
                    if base_specials:
                        combined_specials.extend(base_specials)
                    if line_specials:
                        for func in line_specials:
                            if func not in combined_specials:
                                combined_specials.append(func)
                    segment_specials = segment.get('special_functions', [])
                    if segment_specials:
                        for func in segment_specials:
                            if func not in combined_specials:
                                combined_specials.append(func)

                    segment_builder = ''

                    if effective_font and effective_font != state.font:
                        segment_builder += self.FONT_CMD + effective_font.value
                        state.font = effective_font

                    if effective_rgb:
                        if (state.rgb_color != effective_rgb) or state.color is not None:
                            segment_builder += self.COLOR_CMD + 'Z' + effective_rgb
                            state.rgb_color = effective_rgb
                            state.color = None
                    elif effective_color and (state.color != effective_color or state.rgb_color is not None):
                        segment_builder += self.COLOR_CMD + effective_color.value
                        state.color = effective_color
                        state.rgb_color = None

                    if effective_mode and (
                        state.mode != effective_mode or state.position != position_char
                    ):
                        segment_builder += self.MODE_CMD + position_char + effective_mode.value
                        state.mode = effective_mode
                        state.position = position_char

                    if effective_speed and state.speed != effective_speed:
                        # Speed is a single control byte: 0x15 = Speed 1 (slow)
                        # … 0x19 = Speed 5 (fast) — see the protocol ASCII table
                        # (manual p.36/81).  The Speed enum values are "1".."5",
                        # so the byte is 0x14 + N.  (The previous code emitted
                        # 0x15 followed by the ASCII digit, which always selected
                        # Speed 1 and printed a stray digit on the sign.)
                        segment_builder += chr(0x14 + int(effective_speed.value))
                        state.speed = effective_speed

                    if combined_specials:
                        for func in combined_specials:
                            # Each SpecialFunction.value is the full, correct
                            # control sequence for that attribute (e.g. flash =
                            # 0x07+'1', wide = 0x12); see the SpecialFunction
                            # enum.  Do NOT prefix with 0x1E — that code is only
                            # for character spacing.
                            segment_builder += func.value

                    segment_builder += segment_text
                    content_parts.append(segment_builder)

                if line_index < len(normalised_lines) - 1:
                    content_parts.append(self.CR)

            content = ''.join(content_parts)

            # Complete message body
            message_body = f"{cmd}{file_label}{content}"

            # Complete frame with header and checksum (16-bit sum over STX..ETX)
            frame = self._build_frame_from_payload(message_body)

            self.logger.debug(
                "Built M-Protocol frame: repr=%s hex=%s",
                repr(frame),
                " ".join(f"{byte:02X}" for byte in frame),
            )
            return frame

        except Exception as e:
            self.logger.error(f"Error building M-Protocol message: {e}")
            return None

    def _is_valid_rgb(self, rgb_color: str) -> bool:
        """Validate RGB color format (RRGGBB)"""
        return bool(re.match(r'^[0-9A-Fa-f]{6}$', rgb_color))

    def _calculate_checksum(self, data: bytes) -> str:
        """Compute the Alpha-protocol Checksum over ``data``.

        Per the manual (9708-8061F, p.11): *"Four ASCII digits that represent a
        16-bit hexadecimal summation of all transmitted data from the previous
        <STX> through the previous <ETX> inclusive. The most significant digit
        is first."*  Verified against the worked example on p.60:
        ``<STX>"AAHELLO"<ETX>`` → ``"01FB"``.

        ``data`` must therefore be the bytes from ``<STX>`` through ``<ETX>``
        inclusive.  (The previous implementation XOR'd the bytes and emitted
        only two hex digits, which the sign rejects as an invalid checksum.)
        """
        return f"{sum(data) & 0xFFFF:04X}"

    def _build_frame_from_payload(self, payload: str) -> bytes:
        """Wrap a raw payload as a fully-compliant M-Protocol transmission.

        Per the Alpha M-Protocol specification, every transmission has the
        following layout::

            <NUL>x5  <SOH>  <TT>  <AAAA>  <STX>  <payload>  <ETX>  <CC>  <EOT>

        Where the leading NULLs wake up the sign's UART, ``TT`` is the
        single-character type code (e.g. ``Z`` for all signs), ``AAAA`` is
        the two-character sign address, and ``CC`` is the four-hex-digit
        16-bit summation checksum of the bytes from ``STX`` through ``ETX``
        inclusive (see ``_calculate_checksum``).
        """

        payload_bytes = payload.encode("latin-1")
        stx_bytes = self.STX.encode("latin-1")
        etx_bytes = self.ETX.encode("latin-1")
        # Checksum covers <STX> through <ETX> inclusive (manual p.11/60).
        checksum = self._calculate_checksum(stx_bytes + payload_bytes + etx_bytes)
        header = f"{self.SOH}{self.type_code}{self.sign_id}{self.STX}".encode("latin-1")
        return (
            self.WAKEUP
            + header
            + payload_bytes
            + etx_bytes
            + checksum.encode("ascii")
            + self.EOT.encode("latin-1")
        )

    # ── Protocol frame debug capture helpers ──────────────────────────────

    @staticmethod
    def _format_frame_ascii(frame: bytes) -> str:
        """Render a frame as printable ASCII, with control bytes in <NAME> form.

        Used by the debug terminal so operators can spot SOH/STX/ETX/EOT
        boundaries without having to mentally translate hex.
        """
        ctrl_names = {
            0x00: "<NUL>", 0x01: "<SOH>", 0x02: "<STX>", 0x03: "<ETX>",
            0x04: "<EOT>", 0x06: "<ACK>", 0x0A: "<LF>",  0x0D: "<CR>",
            0x13: "<TIME>", 0x15: "<NAK>", 0x1A: "<FONT>", 0x1B: "<MODE>",
            0x1C: "<COLR>", 0x1E: "<SPEC>", 0x1F: "<POSN>",
        }
        out: List[str] = []
        for b in frame:
            if b in ctrl_names:
                out.append(ctrl_names[b])
            elif 0x20 <= b < 0x7F:
                out.append(chr(b))
            else:
                out.append(f"\\x{b:02X}")
        return "".join(out)

    def _record_frame_history(
        self,
        frame: bytes,
        kind: str,
        *,
        response: Optional[bytes] = None,
        ok: Optional[bool] = None,
        error: Optional[str] = None,
    ) -> None:
        """Append a transmitted M-Protocol frame to the bounded debug ring.

        Best-effort: any exception while recording is swallowed so capture
        cannot break the actual transmission.  The buffer is thread-safe.
        """
        try:
            with self._frame_history_lock:
                self._frame_history_seq += 1
                entry: Dict[str, Any] = {
                    "seq": self._frame_history_seq,
                    "timestamp": datetime.now().isoformat(),
                    "kind": kind,
                    "length": len(frame),
                    "hex": frame.hex(),
                    "ascii": self._format_frame_ascii(frame),
                    "transport": "serial" if self.use_serial else "tcp",
                    "destination": self.serial_port if self.use_serial else f"{self.host}:{self.port}",
                }
                if response is not None:
                    entry["response_hex"] = response.hex()
                    entry["response"] = (
                        "ACK" if response == self.ACK
                        else "NAK" if response == self.NAK
                        else f"0x{response.hex().upper()}"
                    )
                if ok is not None:
                    entry["ok"] = ok
                if error is not None:
                    entry["error"] = error
                self._frame_history.append(entry)
        except Exception:  # pragma: no cover - debug capture must never raise
            pass

    def get_frame_history(self, since_seq: int = 0) -> List[Dict[str, Any]]:
        """Return debug ring entries with ``seq`` strictly greater than ``since_seq``.

        Allows the UI to long-poll for new frames without re-fetching the
        entire buffer each time.
        """
        with self._frame_history_lock:
            return [entry for entry in self._frame_history if entry["seq"] > since_seq]

    def clear_frame_history(self) -> None:
        """Drop all captured frames from the debug ring buffer."""
        with self._frame_history_lock:
            self._frame_history.clear()

    def _send_raw_message(self, message: bytes) -> bool:
        """Send raw M-Protocol message to Alpha 9120C"""
        if not self.connected or not self.socket:
            if not self.connect():
                return False

        try:
            # Drain any spurious bytes before starting a new transaction as
            # documented in the Alpha M-Protocol handshake description.  The
            # controller occasionally leaves ACK/NAK bytes in the buffer after
            # sign power cycles, so clearing them avoids misinterpreting an
            # old response as the acknowledgement for the current frame.
            self._drain_input_buffer()

            # Send message using latin-1 encoding.  The frame already
            # terminates with EOT, so the sign processes the transaction
            # immediately and no separate EOT is required after the ACK.
            self.socket.sendall(message)

            ack = self._read_acknowledgement()
            if ack is None:
                self.logger.debug("No ACK/NAK received from Alpha 9120C")
            elif ack == self.ACK:
                self.logger.debug("Received ACK from Alpha 9120C")
            elif ack == self.NAK:
                self.logger.error("Alpha 9120C responded with NAK")
                self._record_frame_history(message, "message", response=ack, ok=False)
                return False
            else:
                self.logger.warning("Unexpected response byte from Alpha 9120C: %s", ack)

            self.last_message = message
            self.last_update = datetime.now()
            self._record_frame_history(message, "message", response=ack, ok=True)

            self.logger.info("M-Protocol message sent successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error sending M-Protocol message: {e}")
            self._record_frame_history(message, "message", ok=False, error=str(e))
            self.connected = False
            return False

    def _read_acknowledgement(self) -> Optional[bytes]:
        """Read an ACK (0x06) or NAK (0x15) response from the sign."""

        if not self.socket:
            return None

        original_timeout = self.socket.gettimeout()
        try:
            self.socket.settimeout(2)
            while True:
                chunk = self.socket.recv(1)
                if not chunk:
                    return None
                if chunk in (self.ACK, self.NAK):
                    return chunk
                # Ignore CR/LF or other whitespace that sometimes precedes ACK
                if chunk not in (b"\r", b"\n"):
                    return chunk
        except socket.timeout:
            return None
        finally:
            if self.socket:
                self.socket.settimeout(original_timeout or self.timeout)

    def _build_command_frame(self, command_code: str, data: bytes = b"") -> bytes:
        """Build a fully-compliant M-Protocol frame for a single command.

        ``command_code`` is the protocol command character (``"A"`` for
        write text, ``"B"`` for read text, ``"E"`` for write special
        function, ``"F"`` for read special function, ``"I"`` for write
        picture, etc.).  ``data`` is the command-specific payload after
        the command byte.
        """

        cmd_byte = (command_code or "")[:1]
        if not cmd_byte:
            raise ValueError("M-Protocol command code is required")
        payload = cmd_byte.encode("latin-1") + (data or b"")
        # Reuse the canonical frame builder so every transmission carries
        # the same wake-up, header, ETX, checksum, and EOT framing.
        return self._build_frame_from_payload(payload.decode("latin-1"))

    def _send_command_and_read_ack(self, frame: bytes, timeout: float = 2.0) -> Optional[bytes]:
        """Send a pre-built frame and return the ACK/NAK byte (or None)."""

        if not self.connected or not self.socket:
            if not self.connect():
                return None
        try:
            self._drain_input_buffer()
            self.socket.sendall(frame)
        except Exception as exc:
            self.logger.error("Error transmitting M-Protocol frame: %s", exc)
            self._record_frame_history(frame, "command", ok=False, error=str(exc))
            self.connected = False
            return None

        original_timeout = self.socket.gettimeout() if self.socket else None
        try:
            if self.socket:
                self.socket.settimeout(timeout)
            ack = self._read_acknowledgement()
            self._record_frame_history(
                frame, "command",
                response=ack,
                ok=(ack == self.ACK) if ack is not None else None,
            )
            return ack
        finally:
            if self.socket:
                self.socket.settimeout(original_timeout or self.timeout)

    def _drain_input_buffer(self) -> None:
        """Clear pending bytes from the socket before sending a new frame."""

        if not self.socket:
            return

        original_timeout = self.socket.gettimeout()
        try:
            self.socket.settimeout(0.1)
            while True:
                chunk = self.socket.recv(1024)
                if not chunk:
                    break
        except socket.timeout:
            pass
        except OSError:
            pass
        finally:
            if self.socket:
                self.socket.settimeout(original_timeout or self.timeout)

    def send_message(
        self,
        lines: Sequence[Union[str, LineSpec, Dict, None]],
        color: Color = Color.GREEN,
        font: Font = Font.FONT_7x9,
        mode: DisplayMode = DisplayMode.HOLD,
        speed: Speed = Speed.SPEED_3,
        hold_time: int = 5,
        special_functions: Optional[Sequence[Union[SpecialFunction, str]]] = None,
        rgb_color: str = None,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> bool:
        """Send a fully-featured message to the Alpha 9120C"""
        try:
            # Check priority
            if priority.value < self.current_priority.value:
                self.current_priority = priority
            elif priority.value > self.current_priority.value:
                self.logger.info(f"Message blocked - lower priority")
                return False

            # Build and send message
            message = self._build_message(
                lines=lines,
                color=color,
                font=font,
                mode=mode,
                speed=speed,
                hold_time=hold_time,
                special_functions=special_functions,
                rgb_color=rgb_color,
                priority=priority,
            )

            if message:
                success = self._send_raw_message(message)
                if success:
                    normalised = self._normalise_line_definitions(lines, " ")
                    flattened_lines = [
                        ''.join(segment.get('text', '') or '' for segment in spec.get('segments', []))
                        for spec in normalised
                    ]
                    # Store message info
                    self.current_messages[priority] = {
                        'lines': flattened_lines,
                        'color': color.name,
                        'font': font.name,
                        'mode': mode.name,
                        'speed': speed.name,
                        'rgb_color': rgb_color,
                        'timestamp': datetime.now()
                    }
                return success
            return False

        except Exception as e:
            self.logger.error(f"Error in send_message: {e}")
            return False

    def send_rgb_message(
        self,
        lines: Sequence[Union[str, LineSpec, Dict, None]],
        rgb_color: str,
        font: Font = Font.FONT_7x9,
        mode: DisplayMode = DisplayMode.HOLD,
        speed: Speed = Speed.SPEED_3,
        special_functions: Optional[Sequence[Union[SpecialFunction, str]]] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> bool:
        """Send a message with RGB color (Alpha 3.0 protocol)"""
        return self.send_message(
            lines=lines, rgb_color=rgb_color, font=font, mode=mode,
            speed=speed, special_functions=special_functions, priority=priority
        )

    def send_flashing_message(
        self,
        lines: Sequence[Union[str, LineSpec, Dict, None]],
        color: Color = Color.RED,
                              font: Font = Font.FONT_7x13, priority: MessagePriority = MessagePriority.URGENT) -> bool:
        """Send a flashing message (useful for alerts)"""
        return self.send_message(
            lines=lines, color=color, font=font, mode=DisplayMode.FLASH,
            speed=Speed.SPEED_5, special_functions=[SpecialFunction.CHAR_FLASH_ON],
            priority=priority
        )

    def send_scrolling_message(
        self,
        lines: Sequence[Union[str, LineSpec, Dict, None]],
        color: Color = Color.GREEN,
                               direction: str = 'left', speed: Speed = Speed.SPEED_3) -> bool:
        """Send a scrolling message"""
        mode_map = {
            'left': DisplayMode.ROLL_LEFT,
            'right': DisplayMode.ROLL_RIGHT,
            'up': DisplayMode.ROLL_UP,
            'down': DisplayMode.ROLL_DOWN
        }

        mode = mode_map.get(direction, DisplayMode.ROLL_LEFT)

        return self.send_message(
            lines=lines, color=color, mode=mode, speed=speed,
            font=Font.FONT_7x9
        )

    def send_canned_message(self, message_name: str, **kwargs) -> bool:
        """Send a predefined canned message with parameter substitution"""
        if message_name not in self.canned_messages:
            self.logger.error(f"Canned message '{message_name}' not found")
            return False

        try:
            msg_config = self.canned_messages[message_name].copy()

            # Substitute parameters in text lines
            lines = msg_config['lines'].copy()
            if kwargs:
                lines = [line.format(**kwargs) if line else line for line in lines]

            return self.send_message(
                lines=lines,
                color=msg_config['color'],
                font=msg_config['font'],
                mode=msg_config['mode'],
                speed=msg_config['speed'],
                special_functions=msg_config.get('special_functions'),
                priority=msg_config['priority']
            )

        except Exception as e:
            self.logger.error(f"Error sending canned message '{message_name}': {e}")
            return False

    def set_display_time_format(self, time_format: TimeFormat) -> bool:
        """Set the inline date/time format code (M-Protocol Type E, ``*``).

        This selects how ``\\x13X`` time placeholders render inside displayed
        messages (e.g. MM/DD/YY vs DD/MM/YYYY, 12-hour vs 24-hour clock).
        For configuring the sign's internal clock format see ``set_time_format``.
        """
        try:
            # Build time format command (Type E sub-command '*').
            payload = f"E*{self.TIME_CMD}{time_format.value}"
            frame = self._build_frame_from_payload(payload)
            return self._send_raw_message(frame)

        except Exception as e:
            self.logger.error(f"Error setting display time format: {e}")
            return False

    def send_time_display(self, time_format: TimeFormat = TimeFormat.TIME_12H) -> bool:
        """Send current time to display"""
        try:
            # Set time format first
            self.set_display_time_format(time_format)

            # Send time display message
            lines = [
                'CURRENT TIME',
                '{TIME}',  # Special time placeholder
                datetime.now().strftime('%m/%d/%Y'),
                ''
            ]

            return self.send_message(
                lines=lines, color=Color.AMBER, font=Font.FONT_7x11,
                mode=DisplayMode.SCROLL, speed=Speed.SPEED_2
            )

        except Exception as e:
            self.logger.error(f"Error sending time display: {e}")
            return False

    def display_alerts(self, alerts: List) -> bool:
        """Display CAP alerts with advanced M-Protocol features"""
        try:
            if not alerts:
                return self.send_canned_message('no_alerts')

            # Sort alerts by severity
            severity_order = {'Extreme': 0, 'Severe': 1, 'Moderate': 2, 'Minor': 3, 'Unknown': 4}
            sorted_alerts = sorted(alerts, key=lambda x: severity_order.get(x.severity, 4))

            top_alert = sorted_alerts[0]

            # Determine display parameters based on severity
            if top_alert.severity in ['Extreme', 'Severe']:
                return self.send_flashing_message(
                    lines=self._format_alert_for_display(top_alert, len(alerts)),
                    color=Color.RED,
                    font=Font.FONT_7x13,
                    priority=MessagePriority.EMERGENCY
                )
            elif top_alert.severity == 'Moderate':
                return self.send_message(
                    lines=self._format_alert_for_display(top_alert, len(alerts)),
                    color=Color.ORANGE,
                    font=Font.FONT_7x11,
                    mode=DisplayMode.FLASH,
                    speed=Speed.SPEED_4,
                    priority=MessagePriority.URGENT
                )
            else:
                return self.send_scrolling_message(
                    lines=self._format_alert_for_display(top_alert, len(alerts)),
                    color=Color.AMBER,
                    direction='left',
                    speed=Speed.SPEED_3
                )

        except Exception as e:
            self.logger.error(f"Error displaying alerts: {e}")
            return False

    def _format_alert_for_display(self, alert, total_alerts: int) -> List[str]:
        """Format a CAP alert for the 4-line Alpha 9120C display"""
        lines = ['', '', '', '']

        # Line 1: Alert count or severity
        source_label = normalize_alert_source(getattr(alert, 'source', None))
        if source_label == 'UNKNOWN':
            source_label = ''
        header_parts = []
        if source_label:
            header_parts.append(source_label)
        header_parts.append(alert.severity)
        header_text = ' '.join(part for part in header_parts if part)
        if total_alerts > 1:
            header_text = f"{header_text} ({total_alerts})"
        else:
            header_text = f"{header_text} ALERT"
        lines[0] = header_text[:self.max_chars_per_line]

        # Line 2: Event type
        lines[1] = alert.event[:self.max_chars_per_line]

        # Lines 3-4: Headline split across lines
        if alert.headline:
            words = alert.headline.split()
            line3_words = []
            line4_words = []

            current_line = line3_words
            current_length = 0

            for word in words:
                if current_length + len(word) + 1 <= self.max_chars_per_line:
                    current_line.append(word)
                    current_length += len(word) + 1
                elif current_line == line3_words:
                    current_line = line4_words
                    current_line.append(word)
                    current_length = len(word)
                else:
                    break

            lines[2] = ' '.join(line3_words)
            lines[3] = ' '.join(line4_words)

        return lines

    def clear_display(self) -> bool:
        """Clear the Alpha 9120C display"""
        try:
            return self.send_message(
                lines=['', '', '', ''],
                color=Color.GREEN,
                font=Font.FONT_7x9,
                mode=DisplayMode.HOLD,
                priority=MessagePriority.LOW
            )
        except Exception as e:
            self.logger.error(f"Error clearing display: {e}")
            return False

    def set_brightness(self, level: int, auto: bool = False) -> bool:
        """Set sign dimming via the Set Dimming Register (``E/``, 0x2F).

        Format ``WWww`` (manual p.23):

        * ``WW`` — when to dim: ``"00"`` = no dimming, ``"01"`` (dark) … ``"15"``
          (bright) selects the ambient-light threshold at which the sign dims.
        * ``ww`` — dimmed brightness level: ``"00"`` = 100%, ``"01"`` = 86%,
          ``"02"`` = 72%, ``"03"`` = 58%, ``"04"`` = 44%.

        ``level`` is mapped onto those five steps.  Both the 1-16 range used by
        the web UI and a 0-100 percentage (used by the diagnostic scripts) are
        accepted.  ``auto=True`` enables ambient-light dimming (``WW="07"``);
        otherwise ``WW="00"``.

        .. important::
           Per the protocol this register is **only effective on Solar signs**
           (AlphaEclipse signs use ``E@``; a standard 9120C may ignore it).
           This replaces the previous implementation, which emitted ``E$`` —
           the **Clear Memory / Set Memory Configuration** command — and so
           never actually set brightness and risked corrupting the sign's
           memory configuration.
        """
        try:
            # Normalise the incoming level to a 0..100 percentage.
            if level <= 16:
                pct = max(0, min(100, round((level / 16) * 100)))
            else:
                pct = max(0, min(100, int(level)))

            # Map percentage to the five documented brightness steps.
            # Higher percentage -> lower dim-step number (00 = brightest).
            if pct >= 90:
                ww = "00"
            elif pct >= 75:
                ww = "01"
            elif pct >= 60:
                ww = "02"
            elif pct >= 45:
                ww = "03"
            else:
                ww = "04"

            ww_threshold = "07" if auto else "00"
            payload = f"E/{ww_threshold}{ww}"
            frame = self._build_frame_from_payload(payload)
            return self._send_raw_message(frame)

        except Exception as e:
            self.logger.error(f"Error setting brightness: {e}")
            return False

    def emergency_override(self, message: str, duration: int = 30) -> bool:
        """Emergency message override with full M-Protocol features"""
        try:
            # Split message across lines
            words = message.split()
            lines = ['EMERGENCY', 'ALERT', '', '']

            # Distribute emergency text across lines 3-4
            if words:
                line3_words = []
                line4_words = []
                current_line = line3_words
                current_length = 0

                for word in words:
                    if current_length + len(word) + 1 <= self.max_chars_per_line:
                        current_line.append(word)
                        current_length += len(word) + 1
                    elif current_line == line3_words:
                        current_line = line4_words
                        current_line.append(word)
                        current_length = len(word)
                    else:
                        break

                lines[2] = ' '.join(line3_words)
                lines[3] = ' '.join(line4_words)

            success = self.send_flashing_message(
                lines=lines,
                color=Color.RED,
                font=Font.FONT_7x13,
                priority=MessagePriority.EMERGENCY
            )

            if success:
                def reset_priority():
                    time.sleep(duration)
                    self.current_priority = MessagePriority.LOW
                    self.send_canned_message('no_alerts')

                threading.Thread(target=reset_priority, daemon=True).start()

            return success

        except Exception as e:
            self.logger.error(f"Error in emergency override: {e}")
            return False

    def test_all_features(self) -> bool:
        """Comprehensive test of all M-Protocol features"""
        try:
            test_sequence = [
                # Color tests
                {'lines': ['COLOR TEST', 'RED', '', ''], 'color': Color.RED, 'hold_time': 2},
                {'lines': ['COLOR TEST', 'GREEN', '', ''], 'color': Color.GREEN, 'hold_time': 2},
                {'lines': ['COLOR TEST', 'AMBER', '', ''], 'color': Color.AMBER, 'hold_time': 2},
                {'lines': ['COLOR TEST', 'ORANGE', '', ''], 'color': Color.ORANGE, 'hold_time': 2},
                {'lines': ['COLOR TEST', 'RAINBOW', '', ''], 'color': Color.RAINBOW_1, 'hold_time': 3},

                # Font tests
                {'lines': ['FONT TEST', 'SMALL 5x7', '', ''], 'font': Font.FONT_5x7, 'hold_time': 2},
                {'lines': ['FONT TEST', 'MEDIUM 7x9', '', ''], 'font': Font.FONT_7x9, 'hold_time': 2},
                {'lines': ['FONT TEST', 'LARGE 7x13', '', ''], 'font': Font.FONT_7x13, 'hold_time': 2},

                # Effect tests
                {'lines': ['EFFECT TEST', 'WIPE RIGHT', '', ''], 'mode': DisplayMode.WIPE_RIGHT, 'hold_time': 3},
                {'lines': ['EFFECT TEST', 'ROLL LEFT', '', ''], 'mode': DisplayMode.ROLL_LEFT, 'hold_time': 3},
                {'lines': ['EFFECT TEST', 'FLASH', '', ''], 'mode': DisplayMode.FLASH, 'hold_time': 3},
                {'lines': ['EFFECT TEST', 'EXPLODE', '', ''], 'mode': DisplayMode.EXPLODE, 'hold_time': 3},

                # RGB test
                {'lines': ['RGB TEST', 'CUSTOM COLOR', 'FF6600', ''], 'rgb_color': 'FF6600', 'hold_time': 3},

                # Special functions test
                {'lines': ['SPECIAL TEST', 'FLASHING TEXT', '', ''],
                 'color': Color.YELLOW, 'special_functions': [SpecialFunction.CHAR_FLASH_ON], 'hold_time': 3},

                # Final test complete message
                {'lines': ['M-PROTOCOL', 'TEST COMPLETE', 'ALL FEATURES', 'VERIFIED'],
                 'color': Color.GREEN, 'mode': DisplayMode.WIPE_IN, 'hold_time': 3}
            ]

            def run_test_sequence():
                for test in test_sequence:
                    if not self.display_active:
                        break

                    # Set default values
                    test.setdefault('color', Color.GREEN)
                    test.setdefault('font', Font.FONT_7x9)
                    test.setdefault('mode', DisplayMode.HOLD)
                    test.setdefault('speed', Speed.SPEED_3)

                    self.send_message(**test)
                    time.sleep(test.get('hold_time', 2))

            threading.Thread(target=run_test_sequence, daemon=True).start()
            return True

        except Exception as e:
            self.logger.error(f"Error in comprehensive feature test: {e}")
            return False

    def health_check(self) -> bool:
        """
        Perform active health check by attempting to connect/verify socket.

        Returns:
            bool: True if bridge is responsive, False otherwise
        """
        if not self.connected or not self.socket:
            # Try to reconnect
            return self.connect()

        try:
            # Send a Type F read for the firmware version: a benign read
            # that doesn't change sign state.  Use the canonical frame
            # builder so the wakeup/header/checksum/EOT are correct.
            frame = self._build_command_frame(
                "F",
                bytes([ReadSpecialExtCommand.READ_VERSION.value]),
            )
            self._drain_input_buffer()
            self.socket.sendall(frame)
            self._record_frame_history(frame, "health_check")

            # Try to read ACK/NAK with short timeout
            original_timeout = self.socket.gettimeout()
            self.socket.settimeout(2.0)

            try:
                response = self.socket.recv(1)
                self.socket.settimeout(original_timeout)

                if response in (self.ACK, self.NAK):
                    self.connected = True
                    return True
                else:
                    # Unexpected response, try reconnect
                    self.logger.warning(
                        "Unexpected health check response: %s",
                        response.hex() if response else "<empty>",
                    )
                    self.disconnect()
                    return self.connect()

            except socket.timeout:
                self.socket.settimeout(original_timeout)
                self.logger.warning("Health check timeout - bridge not responding")
                self.disconnect()
                return False

        except Exception as e:
            self.logger.warning(f"Health check failed: {e}")
            self.disconnect()
            return False

    def _send_read_command(
        self,
        function_code: int,
        timeout: float = 3.0
    ) -> Optional[bytes]:
        """
        Send a Type F (Read Special Functions) command and return the response.
        
        Args:
            function_code: The function code to read (e.g., 0x24 for serial number)
            timeout: Timeout in seconds for waiting for response
            
        Returns:
            Response data (without ACK/ETX) or None if failed
        """
        if not self.connected or not self.socket:
            self.logger.warning("Not connected to sign")
            return None

        try:
            # Build Type F (Read Special Function Extended) frame.
            # Per spec: <NUL>x5 <SOH> <TT> <ADDR> <STX> 'F' <function> <ETX> <CHECKSUM> <EOT>
            frame = self._build_command_frame("F", bytes([function_code]))

            # Drain input buffer
            self._drain_input_buffer()

            # Send command
            self.socket.sendall(frame)
            self._record_frame_history(frame, "read_command")
            self.logger.debug(f"Sent read command: function=0x{function_code:02X}")
            
            # Read response with timeout
            original_timeout = self.socket.gettimeout()
            self.socket.settimeout(timeout)
            
            try:
                # Read first byte (should be ACK or NAK)
                first_byte = self.socket.recv(1)
                
                if not first_byte:
                    self.logger.error("No response from sign")
                    return None
                    
                if first_byte == b'\x15':  # NAK
                    self.logger.error(f"Sign returned NAK for function 0x{function_code:02X}")
                    return None
                    
                if first_byte != b'\x06':  # Not ACK
                    self.logger.error(f"Unexpected response: {first_byte.hex()}")
                    return None
                
                # ACK received, now read the data until ETX
                data = bytearray()
                while len(data) < 1024:  # Safety limit
                    chunk = self.socket.recv(1)
                    if not chunk:
                        break
                    if chunk == b'\x03':  # ETX - end of data
                        break
                    data.extend(chunk)
                
                self.socket.settimeout(original_timeout)
                
                if len(data) == 0:
                    self.logger.warning(f"Empty response for function 0x{function_code:02X}")
                    return None
                    
                self.logger.debug(f"Read {len(data)} bytes from sign")
                return bytes(data)
                
            except socket.timeout:
                self.socket.settimeout(original_timeout)
                self.logger.error(f"Timeout reading response for function 0x{function_code:02X}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error sending read command: {e}")
            return None

    def read_serial_number(self) -> Optional[str]:
        """
        Read sign serial number (M-Protocol Type F, Function 0x24).
        
        Returns:
            Sign serial number or None if failed
            
        Example:
            >>> led = Alpha9120CController(host='192.168.8.122', port=10001)
            >>> serial = led.read_serial_number()
            >>> print(f"Sign S/N: {serial}")
            Sign S/N: A9120C-12345
        """
        self.logger.info("Reading sign serial number...")
        data = self._send_read_command(ReadSpecialExtCommand.READ_SERIAL_NUMBER.value)
        
        if data is None:
            return None
            
        try:
            # Decode ASCII data
            serial = data.decode('ascii', errors='ignore').strip()
            self.logger.info(f"Sign serial number: {serial}")
            return serial
        except Exception as e:
            self.logger.error(f"Error decoding serial number: {e}")
            return None

    def read_model_number(self) -> Optional[str]:
        """
        Read sign model number (M-Protocol Type F, Function 0x25).
        
        Returns:
            Sign model number or None if failed
        """
        self.logger.info("Reading sign model number...")
        data = self._send_read_command(ReadSpecialExtCommand.READ_MODEL_NUMBER.value)
        
        if data is None:
            return None
            
        try:
            model = data.decode('ascii', errors='ignore').strip()
            self.logger.info(f"Sign model: {model}")
            return model
        except Exception as e:
            self.logger.error(f"Error decoding model number: {e}")
            return None

    def read_firmware_version(self) -> Optional[str]:
        """
        Read sign firmware version (M-Protocol Type F, Function 0x26).
        
        Returns:
            Firmware version or None if failed
        """
        self.logger.info("Reading firmware version...")
        data = self._send_read_command(ReadSpecialExtCommand.READ_VERSION.value)
        
        if data is None:
            return None
            
        try:
            version = data.decode('ascii', errors='ignore').strip()
            self.logger.info(f"Firmware version: {version}")
            return version
        except Exception as e:
            self.logger.error(f"Error decoding firmware version: {e}")
            return None

    def read_memory_configuration(self) -> Optional[Dict[str, any]]:
        """
        Read sign memory configuration (M-Protocol Type F, Function 0x30).
        
        Returns:
            Dictionary with memory info or None if failed
            Contains: total_memory, free_memory, file_count, etc.
        """
        self.logger.info("Reading memory configuration...")
        data = self._send_read_command(ReadSpecialExtCommand.READ_MEMORY_CONFIG.value)
        
        if data is None:
            return None
            
        try:
            # Parse memory configuration response
            # Format varies by sign model - attempt to parse ASCII format
            response_str = data.decode('ascii', errors='ignore').strip()
            
            # Try to extract numerical values
            memory_info = {'raw_response': response_str}
            
            # Look for common patterns
            if 'TOTAL' in response_str.upper() or 'FREE' in response_str.upper():
                # Parse text-based response
                parts = response_str.split()
                for i, part in enumerate(parts):
                    if 'TOTAL' in part.upper() and i + 1 < len(parts):
                        try:
                            memory_info['total_memory'] = int(parts[i + 1])
                        except ValueError:
                            pass
                    elif 'FREE' in part.upper() and i + 1 < len(parts):
                        try:
                            memory_info['free_memory'] = int(parts[i + 1])
                        except ValueError:
                            pass
            
            self.logger.info(f"Memory configuration: {memory_info}")
            return memory_info
            
        except Exception as e:
            self.logger.error(f"Error reading memory configuration: {e}")
            return None

    def read_temperature(self) -> Optional[float]:
        """
        Read sign internal temperature (M-Protocol Type F, Function 0x35).
        
        Returns:
            Temperature in Fahrenheit or None if failed
        """
        self.logger.info("Reading sign temperature...")
        data = self._send_read_command(ReadSpecialExtCommand.READ_TEMPERATURE.value)
        
        if data is None:
            return None
            
        try:
            # Parse temperature response
            response_str = data.decode('ascii', errors='ignore').strip()
            
            # Try to extract temperature value
            # Look for numeric pattern
            import re
            match = re.search(r'(\d+\.?\d*)', response_str)
            if match:
                temp = float(match.group(1))
                self.logger.info(f"Sign temperature: {temp}°F")
                return temp
            else:
                self.logger.warning(f"Could not parse temperature from: {response_str}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error reading temperature: {e}")
            return None

    def get_diagnostics(self) -> Dict[str, any]:
        """
        Read comprehensive diagnostic information from the sign.
        
        Returns:
            Dictionary with all available diagnostic data
        """
        self.logger.info("Reading sign diagnostics...")
        
        diagnostics = {
            'connected': self.connected,
            'host': self.host,
            'port': self.port,
            'timestamp': datetime.now().isoformat()
        }
        
        if self.connected:
            # Read all diagnostic information
            diagnostics['serial_number'] = self.read_serial_number()
            diagnostics['model_number'] = self.read_model_number()
            diagnostics['firmware_version'] = self.read_firmware_version()
            diagnostics['memory_info'] = self.read_memory_configuration()
            diagnostics['temperature'] = self.read_temperature()
        
        return diagnostics

    def set_time_of_day(self, dt: Optional[datetime] = None) -> bool:
        """Set the sign's time-of-day clock (Write Special Function ``E␠``, 0x20).

        Per the manual (p.21) the data is exactly four ASCII digits ``HhMm`` in
        24-hour format (e.g. ``"1530"`` for 3:30 pm).
        """
        if dt is None:
            dt = datetime.now()

        try:
            data = bytes([WriteSpecialExtCommand.SET_TIME_OF_DAY.value]) + dt.strftime("%H%M").encode("ascii")
            frame = self._build_command_frame("E", data)
            ack = self._send_command_and_read_ack(frame)
            if ack == self.ACK:
                self.logger.info("Time of day set: %s", dt.strftime("%H:%M"))
                return True
            self.logger.error("Set time of day not acknowledged (ack=%r)", ack)
            return False
        except Exception as e:
            self.logger.error(f"Error setting time of day: {e}")
            return False

    def set_date(self, dt: Optional[datetime] = None) -> bool:
        """Set the sign's date (Write Special Function ``E;``, 0x3B).

        Per the manual (p.26) the data is six ASCII digits ``mmddyy``.
        """
        if dt is None:
            dt = datetime.now()

        try:
            data = bytes([WriteSpecialExtCommand.SET_DATE.value]) + dt.strftime("%m%d%y").encode("ascii")
            frame = self._build_command_frame("E", data)
            ack = self._send_command_and_read_ack(frame)
            if ack == self.ACK:
                self.logger.info("Date set: %s", dt.strftime("%m/%d/%y"))
                return True
            self.logger.error("Set date not acknowledged (ack=%r)", ack)
            return False
        except Exception as e:
            self.logger.error(f"Error setting date: {e}")
            return False

    def set_time_and_date(self, dt: Optional[datetime] = None) -> bool:
        """Set both the sign's time-of-day clock and its date.

        The Alpha protocol uses two *separate* Write Special Function commands
        — Set Time of Day (``E␠``, 4 digits ``HhMm``) and Set Date (``E;``, 6
        digits ``mmddyy``).  (The previous implementation sent a single
        ``HH:MM:SS\\rMM/DD/YY`` string, which is not a valid data format.)
        """
        if dt is None:
            dt = datetime.now()

        ok_time = self.set_time_of_day(dt)
        ok_date = self.set_date(dt)
        return ok_time and ok_date

    def set_day_of_week(self, day: Optional[int] = None) -> bool:
        """Set the sign's day of week (Write Special Function ``E&``, 0x26).

        Args:
            day: 0=Sunday, 1=Monday, …, 6=Saturday. If None, uses today.

        Per the manual (p.22) the data is one ASCII digit ``"1"``=Sunday …
        ``"7"``=Saturday.  (The previous implementation used the wrong command
        code 0x22 and sent ``"0"``-``"6"`` instead of ``"1"``-``"7"``.)
        """
        if day is None:
            # Python weekday(): 0=Monday … 6=Sunday → 0=Sunday … 6=Saturday.
            day = (datetime.now().weekday() + 1) % 7

        if not 0 <= day <= 6:
            self.logger.error(f"Invalid day of week: {day} (must be 0-6)")
            return False

        if not self.connected or not self.socket:
            self.logger.warning("Not connected to sign")
            return False

        try:
            # Sign encoding is "1"=Sunday … "7"=Saturday, so add 1 to our index.
            data = bytes([WriteSpecialExtCommand.SET_DAY_OF_WEEK.value, ord('1') + day])
            frame = self._build_command_frame("E", data)

            days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
            self.logger.debug(f"Sent set day of week: {days[day]}")

            ack = self._send_command_and_read_ack(frame)

            if ack == self.ACK:
                self.logger.info(f"Day of week set successfully: {days[day]}")
                return True
            elif ack == self.NAK:
                self.logger.error("Sign returned NAK for set day of week")
                return False
            else:
                self.logger.error("No acknowledgement received")
                return False

        except Exception as e:
            self.logger.error(f"Error setting day of week: {e}")
            return False

    def set_time_format(self, format_24h: bool = True) -> bool:
        """
        Set sign time format to 12-hour or 24-hour (M-Protocol Type E, Function 0x27).
        
        Args:
            format_24h: True for 24-hour format, False for 12-hour format
            
        Returns:
            True if successful, False otherwise
        """
        if not self.connected or not self.socket:
            self.logger.warning("Not connected to sign")
            return False
            
        try:
            # Manual p.22: "S" = Standard am/pm, "M" = 24-hour (military).
            # (The previous code had this inverted — it sent "S" for 24-hour.)
            mode_byte = b'M' if format_24h else b'S'
            data = bytes([WriteSpecialExtCommand.SET_TIME_FORMAT.value]) + mode_byte
            frame = self._build_command_frame("E", data)

            format_str = "24-hour" if format_24h else "12-hour"
            self.logger.debug(f"Sent set time format: {format_str}")

            ack = self._send_command_and_read_ack(frame)

            if ack == self.ACK:
                self.logger.info(f"Time format set successfully: {format_str}")
                return True
            elif ack == self.NAK:
                self.logger.error("Sign returned NAK for set time format")
                return False
            else:
                self.logger.error("No acknowledgement received")
                return False

        except Exception as e:
            self.logger.error(f"Error setting time format: {e}")
            return False

    def set_run_mode(self, auto: bool = True) -> bool:
        """Deprecated — there is no auto/manual "run mode" command in the protocol.

        The Alpha Sign Communications Protocol has no global auto/manual toggle;
        scheduling is expressed through the Run Sequence (``E.``), Run Time
        Table (``E)``) and Run Day Table (``E2``) instead.  The previous
        implementation sent code ``0x2E`` (which is actually *Set Run Sequence*)
        with the byte ``'A'``/``'M'``, producing a malformed frame.  This now
        sends nothing and returns ``False`` so it can never put a bad frame on
        the wire.  Use :meth:`set_run_time_table` / :meth:`set_run_day_table`.
        """
        self.logger.warning(
            "set_run_mode() is not an M-Protocol command and is a no-op; "
            "use set_run_time_table()/set_run_day_table() for scheduling."
        )
        return False

    # ── Housekeeping (Write Special Function) ──────────────────────────────

    def soft_reset(self) -> bool:
        """Soft-reset the sign (Write Special Function ``E,``, 0x2C).

        Causes the sign to run its power-up diagnostics.  **Non-destructive** —
        memory is not cleared (manual p.22).
        """
        try:
            frame = self._build_command_frame(
                "E", bytes([WriteSpecialExtCommand.SOFT_RESET.value])
            )
            ack = self._send_command_and_read_ack(frame)
            ok = ack == self.ACK
            self.logger.info("Soft reset %s", "acknowledged" if ok else f"not acknowledged (ack={ack!r})")
            return ok
        except Exception as e:
            self.logger.error(f"Error sending soft reset: {e}")
            return False

    def set_serial_address(self, address: str) -> bool:
        """Set the sign's serial address (Write Special Function ``E7``, 0x37).

        Args:
            address: two ASCII hex characters, ``"00"``–``"FF"`` (manual p.26).

        .. note::
           After this succeeds the sign answers to the *new* address; update
           ``self.sign_id`` / your configuration accordingly.  A hardware DIP
           switch set to a non-``00`` address overrides this once power is
           cycled.
        """
        addr = str(address).strip().upper()
        if not re.fullmatch(r"[0-9A-F]{2}", addr):
            self.logger.error("Invalid serial address %r (need two hex digits 00-FF)", address)
            return False
        try:
            data = bytes([WriteSpecialExtCommand.SET_SERIAL_ADDRESS.value]) + addr.encode("ascii")
            frame = self._build_command_frame("E", data)
            ack = self._send_command_and_read_ack(frame)
            ok = ack == self.ACK
            if ok:
                self.logger.info("Serial address set to %s", addr)
            else:
                self.logger.error("Set serial address not acknowledged (ack=%r)", ack)
            return ok
        except Exception as e:
            self.logger.error(f"Error setting serial address: {e}")
            return False

    def set_run_time_table(self, file_label: str, start: int, stop: int) -> bool:
        """Set a TEXT file's Run Time Table entry (``E)``, 0x29) — format ``FQQQQ``.

        Args:
            file_label: one-character TEXT file label.
            start: start-time code (0x00–0xFF; see manual Appendix B).
            stop:  stop-time code (0x00–0xFF).
        """
        label = (str(file_label) or "A")[:1]
        if not (0 <= int(start) <= 0xFF and 0 <= int(stop) <= 0xFF):
            self.logger.error("Run-time start/stop must be 0x00-0xFF")
            return False
        try:
            payload = f"E)" + label + f"{int(start):02X}{int(stop):02X}"
            frame = self._build_frame_from_payload(payload)
            return self._send_raw_message(frame)
        except Exception as e:
            self.logger.error(f"Error setting run time table: {e}")
            return False

    def set_run_day_table(self, file_label: str, start_day: int, stop_day: int) -> bool:
        """Set a TEXT file's Run Day Table entry (``E2``, 0x32) — format ``FSs``.

        ``start_day``/``stop_day`` are single hex nibbles (manual p.24):
        ``0``=Daily, ``1``=Sun … ``7``=Sat, ``8``=Mon-Fri, ``9``=Weekends,
        ``A``=Always, ``B``=Never.
        """
        label = (str(file_label) or "A")[:1]
        if not (0 <= int(start_day) <= 0xF and 0 <= int(stop_day) <= 0xF):
            self.logger.error("Run-day start/stop must be a single hex nibble 0-F")
            return False
        try:
            payload = f"E2" + label + f"{int(start_day):X}{int(stop_day):X}"
            frame = self._build_frame_from_payload(payload)
            return self._send_raw_message(frame)
        except Exception as e:
            self.logger.error(f"Error setting run day table: {e}")
            return False

    def set_memory_configuration(self, files: Sequence[Dict[str, Any]]) -> bool:
        """Set the sign's Memory Configuration (``E$``, 0x24) — **destructive**.

        Each entry in ``files`` allocates one file and must provide:
        ``label`` (1 char), ``type`` (``"A"`` TEXT / ``"B"`` STRING /
        ``"D"`` DOTS), ``protection`` (``"U"``/``"L"``, default ``"U"``),
        ``size`` (int bytes, encoded as 4 hex digits), and ``qqqq`` (4-char
        trailing field: TEXT = start+stop time e.g. ``"FF00"``; STRING =
        ``"0000"``; DOTS = colour status).  Record format ``FTPSIZEQQQQ``
        (manual p.21).

        .. warning::
           Writing a Memory Configuration **overwrites the previous table and
           erases stored messages.**  Requires at least one file entry; call
           :meth:`clear_memory` to wipe.
        """
        if not files:
            self.logger.error("set_memory_configuration requires at least one file entry")
            return False
        try:
            records = ""
            for f in files:
                label = str(f.get("label", "A"))[:1] or "A"
                ftype = str(f.get("type", "A"))[:1].upper()
                if ftype not in ("A", "B", "D"):
                    self.logger.error("Invalid file type %r (A/B/D)", ftype)
                    return False
                prot = str(f.get("protection", "U"))[:1].upper()
                prot = prot if prot in ("U", "L") else "U"
                size = int(f.get("size", 0)) & 0xFFFF
                qqqq = str(f.get("qqqq", "FF00" if ftype == "A" else "0000"))[:4].upper().ljust(4, "0")
                records += f"{label}{ftype}{prot}{size:04X}{qqqq}"
            frame = self._build_frame_from_payload("E$" + records)
            return self._send_raw_message(frame)
        except Exception as e:
            self.logger.error(f"Error setting memory configuration: {e}")
            return False

    def clear_memory(self, confirm: bool = False) -> bool:
        """Clear the sign's memory (``E$`` with no data) — **destructive**.

        Erases all stored message files and the Memory Configuration table.
        Guarded: pass ``confirm=True`` to actually send it.
        """
        if not confirm:
            self.logger.warning("clear_memory() not sent — pass confirm=True (this erases the sign)")
            return False
        try:
            frame = self._build_frame_from_payload("E$")
            ok = self._send_raw_message(frame)
            if ok:
                self.logger.info("Clear Memory command sent")
            return ok
        except Exception as e:
            self.logger.error(f"Error clearing memory: {e}")
            return False

    def sync_time_with_system(self) -> bool:
        """
        Synchronize sign time with EAS Station system time.
        
        This is a convenience method that sets time, date, and day of week
        all at once using the current system time.
        
        Returns:
            True if all operations successful, False otherwise
        """
        self.logger.info("Synchronizing sign time with system time...")
        
        now = datetime.now()
        
        # Set time and date
        if not self.set_time_and_date(now):
            self.logger.error("Failed to set time and date")
            return False
            
        # Set day of week
        if not self.set_day_of_week():
            self.logger.warning("Failed to set day of week (continuing anyway)")
            # Don't fail completely if day of week doesn't work
            
        self.logger.info(f"Sign synchronized to: {now.strftime('%Y-%m-%d %H:%M:%S %A')}")
        return True

    def set_speaker(self, enabled: bool = True) -> bool:
        """Enable or disable the sign's speaker (Write Special Function ``E!``, 0x21).

        Args:
            enabled: True to enable speaker, False to disable

        Per the manual (p.21) the data is two ASCII characters: ``"00"`` =
        enable, ``"FF"`` = disable.  (The previous implementation used the
        wrong command code 0x23 and the bytes ``'E'``/``'D'``.)
        """
        if not self.connected or not self.socket:
            self.logger.warning("Not connected to sign")
            return False

        try:
            # "00" = enable speaker, "FF" = disable speaker.
            state_byte = b'00' if enabled else b'FF'
            data = bytes([WriteSpecialExtCommand.SET_SPEAKER.value]) + state_byte
            frame = self._build_command_frame("E", data)

            state_str = "enabled" if enabled else "disabled"
            self.logger.debug(f"Sent set speaker: {state_str}")

            ack = self._send_command_and_read_ack(frame)

            if ack == self.ACK:
                self.logger.info(f"Speaker {state_str} successfully")
                return True
            elif ack == self.NAK:
                self.logger.error("Sign returned NAK for set speaker")
                return False
            else:
                self.logger.error("No acknowledgement received")
                return False

        except Exception as e:
            self.logger.error(f"Error setting speaker: {e}")
            return False

    def beep(self, duration: int = 1) -> bool:
        """
        Make the sign beep for attention.

        The M-Protocol triggers a beep by writing one or more BEL (0x07)
        bytes into a transient text file.  The sign emits one tone per
        BEL byte, then displays the (empty) message.
        """
        if not self.connected:
            return False

        if duration < 1:
            duration = 1
        if duration > 9:
            duration = 9

        # Enable speaker first so the sign actually plays the BEL tones.
        if not self.set_speaker(True):
            self.logger.warning("Could not enable speaker for beep")
            return False

        try:
            # Write Text File "A" (file label '0') containing N BEL bytes.
            # Frame: <NUL>x5 <SOH> <TT> <ADDR> <STX> 'A' '0' <BEL>*N <ETX> <CHK> <EOT>
            data = b"0" + (b"\x07" * duration)
            frame = self._build_command_frame("A", data)
            success = self._send_raw_message(frame)
            if success:
                self.logger.info("Sign beeped %d time(s)", duration)
            return success
        except Exception as exc:
            self.logger.error("Error beeping sign: %s", exc)
            return False

    def read_text_file(self, file_label: str = '0') -> Optional[str]:
        """
        Read text from a specific file label (M-Protocol Type B).
        
        Args:
            file_label: File label to read (single ASCII character, typically '0'-'9' or 'A'-'Z')
            
        Returns:
            Text content of the file, or None if failed
            
        Example:
            >>> led = Alpha9120CController(host='192.168.8.122', port=10001)
            >>> text = led.read_text_file('0')
            >>> print(f"File 0 contains: {text}")
        """
        if not self.connected or not self.socket:
            self.logger.warning("Not connected to sign")
            return None
            
        try:
            # Build Type B (Read Text File) frame.
            # Per spec: <NUL>x5 <SOH> <TT> <ADDR> <STX> 'B' <file_label> <ETX> <CHECKSUM> <EOT>
            file_byte = file_label.encode('ascii')[:1] or b'0'
            frame = self._build_command_frame("B", file_byte)

            # Drain input buffer
            self._drain_input_buffer()

            # Send command
            self.socket.sendall(frame)
            self._record_frame_history(frame, "read_text_file")
            self.logger.debug(f"Sent read text file: {file_label}")
            
            # Read response with timeout
            original_timeout = self.socket.gettimeout()
            self.socket.settimeout(3.0)
            
            try:
                # Read first byte (should be ACK or NAK)
                first_byte = self.socket.recv(1)
                
                if not first_byte:
                    self.logger.error("No response from sign")
                    return None
                    
                if first_byte == b'\x15':  # NAK
                    self.logger.error(f"Sign returned NAK for read file {file_label}")
                    return None
                    
                if first_byte != b'\x06':  # Not ACK
                    self.logger.error(f"Unexpected response: {first_byte.hex()}")
                    return None
                
                # ACK received, now read the data until ETX
                data = bytearray()
                while len(data) < 4096:  # Safety limit
                    chunk = self.socket.recv(1)
                    if not chunk:
                        break
                    if chunk == b'\x03':  # ETX - end of data
                        break
                    data.extend(chunk)
                
                self.socket.settimeout(original_timeout)
                
                if len(data) == 0:
                    self.logger.warning(f"Empty file: {file_label}")
                    return ""
                    
                # Decode text
                text = data.decode('ascii', errors='ignore').strip()
                self.logger.info(f"Read {len(text)} characters from file {file_label}")
                return text
                
            except socket.timeout:
                self.socket.settimeout(original_timeout)
                self.logger.error(f"Timeout reading file {file_label}")
                return None
                
        except Exception as e:
            self.logger.error(f"Error reading text file: {e}")
            return None

    def send_dots_graphic(
        self,
        dots: List[List[int]],
        color: Color = Color.GREEN,
        file_label: str = "A",
    ) -> bool:
        """Send a pixel-art / dots graphic to the Alpha 9120C using the M-Protocol
        Picture File (Type I) command.

        Args:
            dots: 2-D list of rows; each cell is 1 (LED on) or 0 (LED off).
                  Maximum 160 columns × 16 rows.  The grid is automatically
                  padded/cropped to the sign's physical limits.
            color: M-Protocol color to apply to all lit pixels.
            file_label: Single-character file label used by the sign's memory
                        manager (default ``"A"``).

        Returns:
            True if the frame was accepted, False otherwise.

        Protocol notes:
            Frame layout::

                SOH type_code sign_id STX "I" label
                width_hi width_lo height
                <row_0_bytes> <row_1_bytes> ... <row_N_bytes>
                ETX checksum

            Each row is ``ceil(width / 8)`` bytes; the most-significant bit of
            the first byte corresponds to the leftmost pixel.  Unused trailing
            bits in the last byte of every row are set to zero.
        """
        if not dots:
            self.logger.warning("send_dots_graphic: empty dot grid supplied")
            return False

        MAX_COLS = 160
        MAX_ROWS = 16

        # Normalise and cap the grid dimensions.
        height = min(len(dots), MAX_ROWS)
        max_row_width = max((len(row) for row in dots), default=0)
        width = min(max_row_width, MAX_COLS)
        if width == 0:
            self.logger.warning("send_dots_graphic: zero-width dot grid")
            return False

        bytes_per_row = (width + 7) // 8

        try:
            label = (file_label or "A").strip() or "A"
            label = label[0].upper()

            # Colour command prefix to set the pixel colour.
            color_prefix = self.COLOR_CMD + color.value

            # Encode every row into packed bytes, then as two-hex-digit ASCII
            # pairs as expected by the sign firmware.
            row_hex_parts: List[str] = []
            for row_idx in range(height):
                raw_row = list(dots[row_idx]) if row_idx < len(dots) else []
                row_bytes = bytearray(bytes_per_row)
                for col_idx in range(width):
                    pixel = 1 if col_idx < len(raw_row) and raw_row[col_idx] else 0
                    if pixel:
                        byte_pos = col_idx // 8
                        bit_pos = 7 - (col_idx % 8)
                        row_bytes[byte_pos] |= (1 << bit_pos)
                row_hex_parts.append(
                    "".join(f"{b:02X}" for b in row_bytes)
                )

            # Dimension header encoded as 4-digit hex strings.
            width_hex = f"{width:04X}"
            height_hex = f"{height:02X}"

            payload = (
                f"I{label}"
                f"{color_prefix}"
                f"{width_hex}{height_hex}"
                + "".join(row_hex_parts)
            )

            frame = self._build_frame_from_payload(payload)
            success = self._send_raw_message(frame)

            if success:
                self.logger.info(
                    "Dots graphic sent: %dx%d pixels, color=%s",
                    width,
                    height,
                    color.name,
                )
            return success

        except Exception as exc:
            self.logger.error("Error sending dots graphic: %s", exc)
            return False

    def get_status(self, check_health: bool = False) -> Dict:
        """
        Get current Alpha 9120C status with M-Protocol capabilities.

        Args:
            check_health: If True, perform active health check before returning status

        Returns:
            Dict with status information
        """
        if check_health:
            self.connected = self.health_check()

        return {
            'connected': self.connected,
            'host': self.host,
            'port': self.port,
            'sign_id': self.sign_id,
            'model': 'Alpha 9120C',
            'protocol': 'M-Protocol (Full Implementation)',
            'display_type': '4-line multi-color',
            'max_chars_per_line': self.max_chars_per_line,
            'max_lines': self.max_lines,
            'supports_rgb': self.supports_rgb,
            'supports_graphics': self.supports_graphics,
            'available_colors': [color.name for color in Color],
            'available_fonts': [font.name for font in Font],
            'available_modes': [mode.name for mode in DisplayMode],
            'available_speeds': [speed.name for speed in Speed],
            'special_functions': [func.name for func in SpecialFunction],
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'current_priority': self.current_priority.name,
            'display_active': self.display_active,
            'messages_stored': len(self.current_messages)
        }

    def close(self):
        """Close connection and cleanup"""
        self.display_active = False
        self.disconnect()
        self.logger.info("Alpha 9120C M-Protocol controller closed")


# Provide backwards-compatible alias used by the Flask app
LEDSignController = Alpha9120CController


# Example usage and testing
def main():
    """Example usage with full M-Protocol features"""
    import argparse

    parser = argparse.ArgumentParser(description='Alpha 9120C M-Protocol Controller')
    parser.add_argument('--host', required=True, help='Alpha 9120C IP address')
    parser.add_argument('--port', type=int, default=10001, help='Port')
    parser.add_argument('--test', action='store_true', help='Run comprehensive feature test')
    parser.add_argument('--message', nargs='+', help='Custom message (up to 4 lines)')
    parser.add_argument('--canned', help='Canned message name')
    parser.add_argument('--rgb', help='RGB color (RRGGBB format)')
    parser.add_argument('--emergency', help='Emergency message')

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    controller = Alpha9120CController(args.host, args.port)

    try:
        if args.test:
            print("Running comprehensive M-Protocol feature test...")
            controller.test_all_features()
        elif args.emergency:
            print(f"Sending emergency message: {args.emergency}")
            controller.emergency_override(args.emergency)
        elif args.message:
            lines = args.message[:4]
            if args.rgb:
                print(f"Sending RGB message: {lines} with color {args.rgb}")
                controller.send_rgb_message(lines, args.rgb)
            else:
                print(f"Sending message: {lines}")
                controller.send_message(lines)
        elif args.canned:
            print(f"Sending canned message: {args.canned}")
            controller.send_canned_message(args.canned)
        else:
            print("No action specified. Use --test, --message, --canned, or --emergency")

        time.sleep(2)  # Let message display

    finally:
        controller.close()


if __name__ == '__main__':
    main()
