#!/usr/bin/env python3
"""
AlphaPremier LED Sign Controller
Supports full message display with colors, fonts, transitions and effects
Based on M-Protocol communication standards for AlphaPremier signs
"""

import socket
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Union
from enum import Enum
import json


class MessagePriority(Enum):
    """Message priority levels"""
    EMERGENCY = 0
    URGENT = 1
    NORMAL = 2
    LOW = 3


class FontSize(Enum):
    """Available font sizes"""
    SMALL = '1'
    MEDIUM = '2'
    LARGE = '3'
    EXTRA_LARGE = '4'


class Color(Enum):
    """Available colors"""
    RED = '1'
    GREEN = '2'
    AMBER = '3'
    YELLOW = '4'
    ORANGE = '5'
    WHITE = '6'
    BLUE = '7'
    CYAN = '8'
    MAGENTA = '9'


class Effect(Enum):
    """Display effects"""
    IMMEDIATE = 'A'
    XOPEN = 'B'
    CURTAIN_UP = 'C'
    CURTAIN_DOWN = 'D'
    SCROLL_LEFT = 'E'
    SCROLL_RIGHT = 'F'
    VOPEN = 'G'
    VCLOSE = 'H'
    SCROLL_UP = 'I'
    SCROLL_DOWN = 'J'
    HOLD = 'K'
    SNOW = 'L'
    TWINKLE = 'M'
    BLOCK_MOVE = 'N'
    RANDOM = 'O'
    HELLO_WORLD = 'P'
    SLOT_MACHINE = 'Q'
    NEWS_FLASH = 'S'
    TRUMPET_FANFARE = 'T'
    CYCLE_COLOR = 'U'


class Speed(Enum):
    """Animation speeds"""
    SLOWEST = '1'
    SLOW = '2'
    MEDIUM = '3'
    FAST = '4'
    FASTEST = '5'


class LEDSignController:
    """Enhanced LED Sign Controller for AlphaPremier signs"""

    def __init__(self, host: str, port: int = 10001, sign_id: str = '01', timeout: int = 10):
        """
        Initialize LED sign controller

        Args:
            host: IP address of the LED sign
            port: Communication port (default 10001)
            sign_id: Sign ID for multi-sign setups (default '01')
            timeout: Socket timeout in seconds
        """
        self.host = host
        self.port = port
        self.sign_id = sign_id
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

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

    def _load_canned_messages(self) -> Dict[str, Dict]:
        """Load predefined canned messages"""
        return {
            'welcome': {
                'text': 'WELCOME TO PUTNAM COUNTY',
                'color': Color.GREEN,
                'font': FontSize.LARGE,
                'effect': Effect.XOPEN,
                'speed': Speed.MEDIUM,
                'hold_time': 3,
                'priority': MessagePriority.LOW
            },
            'time_temp': {
                'text': 'TIME: {time} TEMP: {temp}°F',
                'color': Color.AMBER,
                'font': FontSize.MEDIUM,
                'effect': Effect.IMMEDIATE,
                'speed': Speed.MEDIUM,
                'hold_time': 5,
                'priority': MessagePriority.LOW
            },
            'emergency_test': {
                'text': 'EMERGENCY ALERT SYSTEM TEST',
                'color': Color.RED,
                'font': FontSize.LARGE,
                'effect': Effect.NEWS_FLASH,
                'speed': Speed.FAST,
                'hold_time': 2,
                'priority': MessagePriority.EMERGENCY
            },
            'weather_warning': {
                'text': 'SEVERE WEATHER WARNING',
                'color': Color.RED,
                'font': FontSize.EXTRA_LARGE,
                'effect': Effect.TWINKLE,
                'speed': Speed.FASTEST,
                'hold_time': 3,
                'priority': MessagePriority.EMERGENCY
            },
            'traffic_alert': {
                'text': 'TRAFFIC ADVISORY',
                'color': Color.ORANGE,
                'font': FontSize.LARGE,
                'effect': Effect.SCROLL_LEFT,
                'speed': Speed.MEDIUM,
                'hold_time': 4,
                'priority': MessagePriority.URGENT
            },
            'no_alerts': {
                'text': 'PUTNAM COUNTY EMERGENCY MANAGEMENT - NO ACTIVE ALERTS',
                'color': Color.GREEN,
                'font': FontSize.MEDIUM,
                'effect': Effect.SCROLL_LEFT,
                'speed': Speed.SLOW,
                'hold_time': 8,
                'priority': MessagePriority.NORMAL
            }
        }

    def connect(self) -> bool:
        """Establish connection to LED sign"""
        try:
            if self.socket:
                self.socket.close()

            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))

            self.connected = True
            self.logger.info(f"Connected to LED sign at {self.host}:{self.port}")

            # Send initial handshake/test
            if self._send_test_message():
                return True
            else:
                self.logger.warning("Test message failed, but connection established")
                return True

        except Exception as e:
            self.logger.error(f"Failed to connect to LED sign: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from LED sign"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.connected = False
        self.logger.info("Disconnected from LED sign")

    def _send_test_message(self) -> bool:
        """Send a test message to verify connection"""
        try:
            test_msg = self._build_message('SYSTEM READY', Color.GREEN, FontSize.MEDIUM, Effect.IMMEDIATE)
            return self._send_raw_message(test_msg)
        except Exception as e:
            self.logger.error(f"Test message failed: {e}")
            return False

    def _build_message(self, text: str, color: Color = Color.GREEN,
                       font: FontSize = FontSize.MEDIUM, effect: Effect = Effect.IMMEDIATE,
                       speed: Speed = Speed.MEDIUM, hold_time: int = 3,
                       priority: MessagePriority = MessagePriority.NORMAL) -> str:
        """
        Build a properly formatted M-Protocol message

        Message format: <ID><COMMAND><DATA><ETX>
        """
        try:
            # Message structure for AlphaPremier signs
            # STX (Start of Text)
            stx = '\x02'

            # Sign ID
            sign_id = self.sign_id

            # Command type (Write Text File)
            cmd = 'AA'

            # File label (A-Z, using A for main display)
            file_label = 'A'

            # ESC sequence for formatting
            esc = '\x1b'

            # Build formatting string
            # Font size
            font_cmd = f"{esc}${font.value}"

            # Color
            color_cmd = f"{esc}{color.value}"

            # Effect and speed
            effect_cmd = f"{esc}{effect.value}{speed.value}"

            # Text content (truncate if too long)
            display_text = text[:200]  # AlphaPremier typically supports up to 125-250 chars

            # Build complete message
            message_data = f"{font_cmd}{color_cmd}{effect_cmd}{display_text}"

            # ETX (End of Text)
            etx = '\x03'

            # Calculate checksum (XOR of all bytes between STX and ETX)
            checksum = 0
            message_body = f"{sign_id}{cmd}{file_label}{message_data}"
            for char in message_body:
                checksum ^= ord(char)

            # Format checksum as 2-digit hex
            checksum_str = f"{checksum:02X}"

            # Complete message
            complete_message = f"{stx}{message_body}{etx}{checksum_str}"

            self.logger.debug(f"Built message: {repr(complete_message)}")
            return complete_message

        except Exception as e:
            self.logger.error(f"Error building message: {e}")
            return None

    def _send_raw_message(self, message: str) -> bool:
        """Send raw message to LED sign"""
        if not self.connected or not self.socket:
            if not self.connect():
                return False

        try:
            # Send message
            self.socket.send(message.encode('latin-1'))

            # Wait for acknowledgment (optional - some signs don't send ACK)
            try:
                self.socket.settimeout(2)  # Short timeout for ACK
                response = self.socket.recv(10)
                self.logger.debug(f"Received response: {repr(response)}")
            except socket.timeout:
                self.logger.debug("No response from sign (normal for some models)")

            self.last_message = message
            self.last_update = datetime.now()

            self.logger.info("Message sent successfully to LED sign")
            return True

        except Exception as e:
            self.logger.error(f"Error sending message: {e}")
            self.connected = False
            return False

    def send_message(self, text: str, color: Color = Color.GREEN,
                     font: FontSize = FontSize.MEDIUM, effect: Effect = Effect.IMMEDIATE,
                     speed: Speed = Speed.MEDIUM, hold_time: int = 3,
                     priority: MessagePriority = MessagePriority.NORMAL) -> bool:
        """Send a formatted message to the LED sign"""
        try:
            # Check if we should override current message based on priority
            if priority.value < self.current_priority.value:
                self.current_priority = priority
            elif priority.value > self.current_priority.value:
                self.logger.info(
                    f"Message blocked - lower priority than current ({priority} vs {self.current_priority})")
                return False

            # Build and send message
            message = self._build_message(text, color, font, effect, speed, hold_time, priority)
            if message:
                success = self._send_raw_message(message)
                if success:
                    # Store message info
                    self.current_messages[priority] = {
                        'text': text,
                        'color': color,
                        'font': font,
                        'effect': effect,
                        'speed': speed,
                        'hold_time': hold_time,
                        'timestamp': datetime.now()
                    }
                return success
            return False

        except Exception as e:
            self.logger.error(f"Error in send_message: {e}")
            return False

    def send_canned_message(self, message_name: str, **kwargs) -> bool:
        """Send a predefined canned message with optional parameter substitution"""
        if message_name not in self.canned_messages:
            self.logger.error(f"Canned message '{message_name}' not found")
            return False

        try:
            msg_config = self.canned_messages[message_name].copy()

            # Substitute parameters in text
            text = msg_config['text']
            if kwargs:
                text = text.format(**kwargs)

            return self.send_message(
                text=text,
                color=msg_config['color'],
                font=msg_config['font'],
                effect=msg_config['effect'],
                speed=msg_config['speed'],
                hold_time=msg_config['hold_time'],
                priority=msg_config['priority']
            )

        except Exception as e:
            self.logger.error(f"Error sending canned message '{message_name}': {e}")
            return False

    def display_alerts(self, alerts: List) -> bool:
        """Display CAP alerts on the LED sign"""
        try:
            if not alerts:
                return self.display_default_message()

            # Sort alerts by severity
            severity_order = {'Extreme': 0, 'Severe': 1, 'Moderate': 2, 'Minor': 3, 'Unknown': 4}
            sorted_alerts = sorted(alerts, key=lambda x: severity_order.get(x.severity, 4))

            # Display the most severe alert
            top_alert = sorted_alerts[0]

            # Determine display parameters based on severity
            if top_alert.severity in ['Extreme', 'Severe']:
                color = Color.RED
                effect = Effect.TWINKLE
                speed = Speed.FASTEST
                font = FontSize.EXTRA_LARGE
                priority = MessagePriority.EMERGENCY
            elif top_alert.severity == 'Moderate':
                color = Color.ORANGE
                effect = Effect.NEWS_FLASH
                speed = Speed.FAST
                font = FontSize.LARGE
                priority = MessagePriority.URGENT
            else:
                color = Color.AMBER
                effect = Effect.SCROLL_LEFT
                speed = Speed.MEDIUM
                font = FontSize.MEDIUM
                priority = MessagePriority.NORMAL

            # Format alert text
            alert_text = f"{top_alert.event}: {top_alert.headline}"
            if len(alert_text) > 200:
                alert_text = alert_text[:197] + "..."

            # Add multiple alerts indicator if needed
            if len(alerts) > 1:
                alert_text = f"ALERT ({len(alerts)}): {alert_text}"

            return self.send_message(
                text=alert_text,
                color=color,
                font=font,
                effect=effect,
                speed=speed,
                priority=priority
            )

        except Exception as e:
            self.logger.error(f"Error displaying alerts: {e}")
            return False

    def display_default_message(self) -> bool:
        """Display default message when no alerts are active"""
        try:
            # Get current time and temperature (if available)
            current_time = datetime.now().strftime("%I:%M %p")

            # Try to get temperature from weather service (simplified)
            temp = "N/A"

            # Cycle through different default messages
            if hasattr(self, '_default_message_index'):
                self._default_message_index = (self._default_message_index + 1) % 3
            else:
                self._default_message_index = 0

            if self._default_message_index == 0:
                return self.send_canned_message('no_alerts')
            elif self._default_message_index == 1:
                return self.send_canned_message('time_temp', time=current_time, temp=temp)
            else:
                return self.send_canned_message('welcome')

        except Exception as e:
            self.logger.error(f"Error displaying default message: {e}")
            return False

    def clear_display(self) -> bool:
        """Clear the LED display"""
        try:
            return self.send_message(
                text=" ",
                color=Color.GREEN,
                font=FontSize.MEDIUM,
                effect=Effect.IMMEDIATE,
                priority=MessagePriority.LOW
            )
        except Exception as e:
            self.logger.error(f"Error clearing display: {e}")
            return False

    def set_brightness(self, level: int) -> bool:
        """Set display brightness (1-16, where 1 is dimmest, 16 is brightest)"""
        try:
            if not 1 <= level <= 16:
                raise ValueError("Brightness level must be between 1 and 16")

            # Build brightness command
            stx = '\x02'
            sign_id = self.sign_id
            cmd = 'E$'  # Set brightness command
            brightness_hex = f"{level:X}"
            etx = '\x03'

            # Calculate checksum
            message_body = f"{sign_id}{cmd}{brightness_hex}"
            checksum = 0
            for char in message_body:
                checksum ^= ord(char)
            checksum_str = f"{checksum:02X}"

            message = f"{stx}{message_body}{etx}{checksum_str}"

            return self._send_raw_message(message)

        except Exception as e:
            self.logger.error(f"Error setting brightness: {e}")
            return False

    def run_sequence(self, messages: List[Dict], repeat: bool = False) -> bool:
        """Run a sequence of messages"""
        try:
            def sequence_thread():
                while True:
                    for msg in messages:
                        if not self.display_active:
                            break

                        # Send message
                        self.send_message(**msg)

                        # Wait for hold time
                        time.sleep(msg.get('hold_time', 3))

                    if not repeat:
                        break

            thread = threading.Thread(target=sequence_thread, daemon=True)
            thread.start()
            return True

        except Exception as e:
            self.logger.error(f"Error running sequence: {e}")
            return False

    def emergency_override(self, message: str, duration: int = 30) -> bool:
        """Emergency message override - highest priority"""
        try:
            # Send emergency message
            success = self.send_message(
                text=f"EMERGENCY: {message}",
                color=Color.RED,
                font=FontSize.EXTRA_LARGE,
                effect=Effect.NEWS_FLASH,
                speed=Speed.FASTEST,
                priority=MessagePriority.EMERGENCY
            )

            if success:
                # Schedule return to normal after duration
                def reset_priority():
                    time.sleep(duration)
                    self.current_priority = MessagePriority.LOW
                    self.display_default_message()

                threading.Thread(target=reset_priority, daemon=True).start()

            return success

        except Exception as e:
            self.logger.error(f"Error in emergency override: {e}")
            return False

    def get_status(self) -> Dict:
        """Get current sign status"""
        return {
            'connected': self.connected,
            'host': self.host,
            'port': self.port,
            'sign_id': self.sign_id,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'current_priority': self.current_priority.name,
            'display_active': self.display_active,
            'messages_stored': len(self.current_messages)
        }

    def test_all_features(self) -> bool:
        """Test all sign features"""
        try:
            test_messages = [
                {'text': 'COLOR TEST RED', 'color': Color.RED, 'hold_time': 2},
                {'text': 'COLOR TEST GREEN', 'color': Color.GREEN, 'hold_time': 2},
                {'text': 'COLOR TEST AMBER', 'color': Color.AMBER, 'hold_time': 2},
                {'text': 'FONT TEST SMALL', 'font': FontSize.SMALL, 'hold_time': 2},
                {'text': 'FONT TEST LARGE', 'font': FontSize.LARGE, 'hold_time': 2},
                {'text': 'EFFECT TEST SCROLL', 'effect': Effect.SCROLL_LEFT, 'hold_time': 3},
                {'text': 'EFFECT TEST TWINKLE', 'effect': Effect.TWINKLE, 'hold_time': 3},
                {'text': 'TEST COMPLETE', 'color': Color.GREEN, 'effect': Effect.IMMEDIATE, 'hold_time': 2}
            ]

            return self.run_sequence(test_messages, repeat=False)

        except Exception as e:
            self.logger.error(f"Error in feature test: {e}")
            return False

    def close(self):
        """Close connection and cleanup"""
        self.display_active = False
        self.disconnect()
        self.logger.info("LED sign controller closed")


# Example usage and testing functions
def main():
    """Example usage of LED sign controller"""
    import argparse

    parser = argparse.ArgumentParser(description='LED Sign Controller Test')
    parser.add_argument('--host', required=True, help='LED sign IP address')
    parser.add_argument('--port', type=int, default=10001, help='LED sign port')
    parser.add_argument('--test', action='store_true', help='Run feature test')
    parser.add_argument('--message', help='Send custom message')
    parser.add_argument('--canned', help='Send canned message by name')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Create controller
    controller = LEDSignController(args.host, args.port)

    try:
        if args.test:
            print("Running feature test...")
            controller.test_all_features()
        elif args.message:
            print(f"Sending message: {args.message}")
            controller.send_message(args.message)
        elif args.canned:
            print(f"Sending canned message: {args.canned}")
            controller.send_canned_message(args.canned)
        else:
            print("No action specified. Use --test, --message, or --canned")

    finally:
        controller.close()


if __name__ == '__main__':
    main()