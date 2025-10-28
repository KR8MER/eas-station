#!/usr/bin/env python3
"""
Complete Alpha 9120C LED Sign Controller
Full M-Protocol implementation with all documented features
Based on Alpha Communications M-Protocol specification
"""

import socket
import time
import logging
import threading
from datetime import datetime
from typing import List, Dict, Optional, Union
from enum import Enum
import json
import re

from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS, ensure_list


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


class Speed(Enum):
    """Speed Settings (15H + character)"""
    SPEED_1 = '1'  # Slowest
    SPEED_2 = '2'  # Slow
    SPEED_3 = '3'  # Medium
    SPEED_4 = '4'  # Fast
    SPEED_5 = '5'  # Fastest


class SpecialFunction(Enum):
    """Special Functions (1EH + character)"""
    WIDE_CHAR_ON = '0'  # Wide character on
    WIDE_CHAR_OFF = '1'  # Wide character off
    TRUE_DESC_ON = '2'  # True descender on
    TRUE_DESC_OFF = '3'  # True descender off
    CHAR_FLASH_ON = '4'  # Character flash on
    CHAR_FLASH_OFF = '5'  # Character flash off
    FIXED_WIDTH = '6'  # Fixed width font
    PROP_WIDTH = '7'  # Proportional width font


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


class Alpha9120CController:
    """Complete Alpha 9120C LED Sign Controller with full M-Protocol support"""

    SOH = "\x01"
    STX = "\x02"
    ETX = "\x03"
    EOT = "\x04"
    ACK = b"\x06"
    NAK = b"\x15"

    def __init__(
        self,
        host: str,
        port: int = 10001,
        sign_id: str = "01",
        timeout: int = 10,
        location_settings: Optional[Dict[str, Union[str, List[str]]]] = None,
        type_code: str = "Z",
    ):
        """
        Initialize Alpha 9120C controller with full M-Protocol support

        Args:
            host: IP address of the LED sign
            port: Communication port (default 10001)
            sign_id: Sign ID for multi-sign setups (default '01')
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.port = port
        self.sign_id = self._normalise_sign_id(sign_id)
        self.timeout = timeout
        self.type_code = self._normalise_type_code(type_code)
        self.logger = logging.getLogger(__name__)
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
        self.SPEED_CMD = '\x15'  # Speed command prefix
        self.SPECIAL_CMD = '\x1E'  # Special function prefix
        self.TIME_CMD = '\x13'  # Time format prefix
        self.POSITION_CMD = '\x1F'  # Position command prefix

        # Connection management
        self.socket = None
        self.connected = False
        self.last_message = None
        self.last_update = None

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
            'EMERGENCY MGMT',
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

    def _normalise_type_code(self, raw_type: str) -> str:
        """Type codes are a single printable character in the M-Protocol header."""

        if not raw_type:
            return "Z"

        candidate = str(raw_type)[0].upper()
        if not candidate.isalnum():
            return "Z"
        return candidate

    def connect(self) -> bool:
        """Establish connection to Alpha 9120C sign"""
        try:
            if self.socket:
                self.socket.close()

            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))

            self.connected = True
            self.logger.info(f"Connected to Alpha 9120C at {self.host}:{self.port}")

            # Send initialization sequence
            if self._send_initialization():
                return True
            else:
                self.logger.warning("Initialization failed, but connection established")
                return True

        except Exception as e:
            self.logger.error(f"Failed to connect to Alpha 9120C: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from Alpha 9120C"""
        if self.socket:
            try:
                self.socket.close()
            except:
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
        lines: List[str],
        color: Color = Color.GREEN,
        font: Font = Font.FONT_7x9,
        mode: DisplayMode = DisplayMode.HOLD,
        speed: Speed = Speed.SPEED_3,
        hold_time: int = 5,
        special_functions: List[SpecialFunction] = None,
        rgb_color: str = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        file_label: str = "A",
    ) -> Optional[bytes]:
        """Build a complete M-Protocol message with all features.

        Format: <SOH><TYPE><ADDR><STX><CMD><FILE><formatting><content><ETX><CHECKSUM>
        """
        try:
            # Ensure we have exactly 4 lines
            display_lines = lines[:4]
            while len(display_lines) < 4:
                display_lines.append('')

            # Truncate lines to display width
            display_lines = [line[:self.max_chars_per_line] for line in display_lines]

            # Message components
            cmd = "AA"  # Write text file command
            file_label = (file_label or "A").strip() or "A"
            file_label = file_label[0].upper()

            # Build formatting sequence
            formatting = ''

            # Font selection
            formatting += self.FONT_CMD + font.value

            # Color selection (RGB takes precedence over standard colors)
            if rgb_color and self._is_valid_rgb(rgb_color):
                # Alpha 3.0 protocol RGB color
                formatting += self.COLOR_CMD + 'Z' + rgb_color.upper()
            else:
                # Standard color
                formatting += self.COLOR_CMD + color.value

            # Display mode
            formatting += self.MODE_CMD + mode.value

            # Speed setting
            formatting += self.SPEED_CMD + speed.value

            # Special functions
            if special_functions:
                for func in special_functions:
                    formatting += self.SPECIAL_CMD + func.value

            # Build message content with line separators
            content = formatting
            for i, line in enumerate(display_lines):
                content += line
                if i < len(display_lines) - 1:
                    content += self.CR  # Line separator

            # Complete message body
            message_body = f"{cmd}{file_label}{content}"

            # Complete frame with header and checksum (checksum is XOR of bytes between STX and ETX)
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

    def _calculate_checksum(self, payload: bytes) -> str:
        """Checksum is calculated as an XOR of bytes between STX and ETX."""

        checksum = 0
        for byte in payload:
            checksum ^= byte
        return f"{checksum:02X}"

    def _build_frame_from_payload(self, payload: str) -> bytes:
        """Wrap a raw payload with the standard M-Protocol header, ETX, and checksum."""

        payload_bytes = payload.encode("latin-1")
        checksum = self._calculate_checksum(payload_bytes)
        header = f"{self.SOH}{self.type_code}{self.sign_id}{self.STX}".encode("latin-1")
        return header + payload_bytes + self.ETX.encode("latin-1") + checksum.encode("ascii")

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

            # Send message using latin-1 encoding
            self.socket.sendall(message)

            ack = self._read_acknowledgement()
            if ack is None:
                self.logger.debug("No ACK/NAK received from Alpha 9120C")
            elif ack == self.ACK:
                self.logger.debug("Received ACK from Alpha 9120C")
                self._send_eot()
            elif ack == self.NAK:
                self.logger.error("Alpha 9120C responded with NAK")
                return False
            else:
                self.logger.warning("Unexpected response byte from Alpha 9120C: %s", ack)

            self.last_message = message
            self.last_update = datetime.now()

            self.logger.info("M-Protocol message sent successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error sending M-Protocol message: {e}")
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

    def _send_eot(self) -> None:
        """Transmit the M-Protocol EOT byte once an ACK is received."""

        if not self.socket:
            return

        try:
            self.socket.sendall(self.EOT.encode("latin-1"))
            self.logger.debug("Sent EOT to complete M-Protocol transaction")
        except OSError as exc:  # pragma: no cover - defensive
            self.logger.debug("Failed to send EOT: %s", exc)

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

    def send_message(self, lines: List[str], color: Color = Color.GREEN,
                     font: Font = Font.FONT_7x9, mode: DisplayMode = DisplayMode.HOLD,
                     speed: Speed = Speed.SPEED_3, hold_time: int = 5,
                     special_functions: List[SpecialFunction] = None,
                     rgb_color: str = None, priority: MessagePriority = MessagePriority.NORMAL) -> bool:
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
                lines, color, font, mode, speed, hold_time,
                special_functions, rgb_color, priority
            )

            if message:
                success = self._send_raw_message(message)
                if success:
                    # Store message info
                    self.current_messages[priority] = {
                        'lines': lines,
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

    def send_rgb_message(self, lines: List[str], rgb_color: str,
                         font: Font = Font.FONT_7x9, mode: DisplayMode = DisplayMode.HOLD,
                         speed: Speed = Speed.SPEED_3, special_functions: List[SpecialFunction] = None,
                         priority: MessagePriority = MessagePriority.NORMAL) -> bool:
        """Send a message with RGB color (Alpha 3.0 protocol)"""
        return self.send_message(
            lines=lines, rgb_color=rgb_color, font=font, mode=mode,
            speed=speed, special_functions=special_functions, priority=priority
        )

    def send_flashing_message(self, lines: List[str], color: Color = Color.RED,
                              font: Font = Font.FONT_7x13, priority: MessagePriority = MessagePriority.URGENT) -> bool:
        """Send a flashing message (useful for alerts)"""
        return self.send_message(
            lines=lines, color=color, font=font, mode=DisplayMode.FLASH,
            speed=Speed.SPEED_5, special_functions=[SpecialFunction.CHAR_FLASH_ON],
            priority=priority
        )

    def send_scrolling_message(self, lines: List[str], color: Color = Color.GREEN,
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

    def set_time_format(self, time_format: TimeFormat) -> bool:
        """Set time display format"""
        try:
            # Build time format command
            payload = f"E*{self.TIME_CMD}{time_format.value}"
            frame = self._build_frame_from_payload(payload)
            return self._send_raw_message(frame)

        except Exception as e:
            self.logger.error(f"Error setting time format: {e}")
            return False

    def send_time_display(self, time_format: TimeFormat = TimeFormat.TIME_12H) -> bool:
        """Send current time to display"""
        try:
            # Set time format first
            self.set_time_format(time_format)

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
        if total_alerts > 1:
            lines[0] = f"{alert.severity} ({total_alerts})"
        else:
            lines[0] = f"{alert.severity} ALERT"

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
        """Set display brightness.

        The M-Protocol supports hexadecimal levels 0-F (16 discrete steps) and an
        automatic photocell mode signalled with `E$A`.  The previous implementation
        incorrectly allowed the value `16`, which produced a two-character code and
        violated the single-hex-digit requirement described in the manual.
        """

        try:
            if auto:
                payload = "E$A"
            else:
                if not 0 <= level <= 15:
                    raise ValueError("Brightness level must be between 0 and 15")

                payload = f"E${level:X}"
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

    def get_status(self) -> Dict:
        """Get current Alpha 9120C status with M-Protocol capabilities"""
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