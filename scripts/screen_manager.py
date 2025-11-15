"""Screen manager service for LED and VFD display rotation.

This module manages automatic screen rotation, scheduling, and display updates
for custom screen templates.
"""

import logging
import random
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional

from flask import Flask

logger = logging.getLogger(__name__)


SNAPSHOT_SCREEN_TEMPLATE = {
    "name": "oled_snapshot_preview",
    "display_type": "oled",
    "enabled": True,
    "priority": 0,
    "refresh_interval": 15,
    "duration": 10,
    "template_data": {
        "clear": True,
        "lines": [
            {"text": "{now.datetime}", "wrap": False, "y": 0, "max_width": 124},
            {
                "text": "Status {status.status} | Alerts {status.active_alerts_count}",
                "y": 10,
                "wrap": False,
                "max_width": 124,
            },
            {"text": "{status.status_summary}", "y": 22, "max_width": 124},
            {
                "text": "Alert {alerts.features[0].properties.event}",
                "y": 34,
                "max_width": 124,
                "allow_empty": True,
            },
            {
                "text": "CPU {status.system_resources.cpu_usage_percent}%  MEM {status.system_resources.memory_usage_percent}%",
                "y": 46,
                "wrap": False,
                "max_width": 124,
            },
            {
                "text": "Audio Peak {audio.live_metrics[0].peak_level_db} dB", "y": 52, "allow_empty": True
            },
        ],
    },
    "data_sources": [
        {"endpoint": "/api/system_status", "var_name": "status"},
        {"endpoint": "/api/audio/metrics", "var_name": "audio"},
        {"endpoint": "/api/alerts", "var_name": "alerts"},
    ],
}


class ScreenManager:
    """Manages screen rotation and display updates."""

    def __init__(self, app: Optional[Flask] = None):
        """Initialize the screen manager.

        Args:
            app: Flask application instance
        """
        self.app = app
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._led_rotation: Optional[Dict] = None
        self._vfd_rotation: Optional[Dict] = None
        self._oled_rotation: Optional[Dict] = None
        self._led_current_index = 0
        self._vfd_current_index = 0
        self._oled_current_index = 0
        self._last_led_update = datetime.min
        self._last_vfd_update = datetime.min
        self._last_oled_update = datetime.min
        self._oled_button = None
        self._oled_button_actions: Deque[str] = deque()
        self._oled_button_lock = threading.Lock()
        self._oled_button_held = False
        self._oled_button_initialized = False

    def init_app(self, app: Flask):
        """Initialize with Flask app context.

        Args:
            app: Flask application instance
        """
        self.app = app

    def start(self):
        """Start the screen manager background thread."""
        if self._running:
            logger.warning("Screen manager already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Screen manager started")

    def stop(self):
        """Stop the screen manager background thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Screen manager stopped")

    def _run_loop(self):
        """Main loop for screen rotation."""
        while self._running:
            try:
                self._ensure_oled_button_listener()
                if self.app:
                    with self.app.app_context():
                        self._update_rotations()
                        self._check_led_rotation()
                        self._check_vfd_rotation()
                        self._check_oled_rotation()
                        self._process_oled_button_actions()
                else:
                    logger.warning("No app context available")

                time.sleep(1)  # Check every second

            except Exception as e:
                logger.error(f"Error in screen manager loop: {e}")
                time.sleep(5)

    def _update_rotations(self):
        """Load active screen rotations from database."""
        try:
            from app_core.models import ScreenRotation

            # Get active LED rotation
            led_rotation = ScreenRotation.query.filter_by(
                display_type='led',
                enabled=True
            ).first()

            if led_rotation:
                self._led_rotation = led_rotation.to_dict()
            else:
                # Clear cache if no active rotation found
                self._led_rotation = None

            # Get active VFD rotation
            vfd_rotation = ScreenRotation.query.filter_by(
                display_type='vfd',
                enabled=True
            ).first()

            if vfd_rotation:
                self._vfd_rotation = vfd_rotation.to_dict()
            else:
                # Clear cache if no active rotation found
                self._vfd_rotation = None

            # Get active OLED rotation
            oled_rotation = ScreenRotation.query.filter_by(
                display_type='oled',
                enabled=True
            ).first()

            if oled_rotation:
                self._oled_rotation = oled_rotation.to_dict()
            else:
                self._oled_rotation = None

        except Exception as e:
            logger.error(f"Error loading rotations: {e}")

    def _check_led_rotation(self):
        """Check if LED screen should rotate."""
        if not self._led_rotation:
            return

        # Check if we should skip rotation due to active alerts
        if self._led_rotation.get('skip_on_alert') and self._has_active_alerts():
            return

        # Get screen sequence
        screens = self._led_rotation.get('screens', [])
        if not screens:
            return

        # Get current screen index
        current_index = self._led_current_index
        if current_index >= len(screens):
            current_index = 0
            self._led_current_index = 0

        # Get current screen config
        screen_config = screens[current_index]
        duration = screen_config.get('duration', 10)

        # Check if it's time to rotate
        now = datetime.utcnow()
        if now - self._last_led_update >= timedelta(seconds=duration):
            # Display next screen
            self._display_led_screen(screen_config)
            self._last_led_update = now

            # Move to next screen
            current_index += 1
            if current_index >= len(screens):
                current_index = 0

                # Randomize if enabled
                if self._led_rotation.get('randomize'):
                    random.shuffle(screens)
                    self._led_rotation['screens'] = screens

            self._led_current_index = current_index

            # Update database
            self._update_rotation_state('led', current_index, now)

    def _check_vfd_rotation(self):
        """Check if VFD screen should rotate."""
        if not self._vfd_rotation:
            return

        # Check if we should skip rotation due to active alerts
        if self._vfd_rotation.get('skip_on_alert') and self._has_active_alerts():
            return

        # Get screen sequence
        screens = self._vfd_rotation.get('screens', [])
        if not screens:
            return

        # Get current screen index
        current_index = self._vfd_current_index
        if current_index >= len(screens):
            current_index = 0
            self._vfd_current_index = 0

        # Get current screen config
        screen_config = screens[current_index]
        duration = screen_config.get('duration', 10)

        # Check if it's time to rotate
        now = datetime.utcnow()
        if now - self._last_vfd_update >= timedelta(seconds=duration):
            # Display next screen
            self._display_vfd_screen(screen_config)
            self._last_vfd_update = now

            # Move to next screen
            current_index += 1
            if current_index >= len(screens):
                current_index = 0

                # Randomize if enabled
                if self._vfd_rotation.get('randomize'):
                    random.shuffle(screens)
                    self._vfd_rotation['screens'] = screens

            self._vfd_current_index = current_index

            # Update database
            self._update_rotation_state('vfd', current_index, now)

    def _check_oled_rotation(self):
        """Check if OLED screen should rotate."""
        if not self._oled_rotation:
            return

        if self._oled_rotation.get('skip_on_alert') and self._has_active_alerts():
            return

        screens = self._oled_rotation.get('screens', [])
        if not screens:
            return

        current_index = self._oled_current_index
        if current_index >= len(screens):
            current_index = 0
            self._oled_current_index = 0

        screen_config = screens[current_index]
        duration = screen_config.get('duration', 10)

        now = datetime.utcnow()
        if now - self._last_oled_update >= timedelta(seconds=duration):
            self._display_oled_screen(screen_config)
            self._last_oled_update = now

            current_index += 1
            if current_index >= len(screens):
                current_index = 0

                if self._oled_rotation.get('randomize'):
                    random.shuffle(screens)
                    self._oled_rotation['screens'] = screens

            self._oled_current_index = current_index

            self._update_rotation_state('oled', current_index, now)

    def _ensure_oled_button_listener(self) -> None:
        """Attach callbacks for the Argon OLED button when available."""

        if self._oled_button_initialized:
            return

        try:
            from app_core.oled import ensure_oled_button
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("OLED button support unavailable: %s", exc)
            self._oled_button_initialized = True
            return

        button = ensure_oled_button(logger)
        if button is None:
            self._oled_button_initialized = True
            return

        button.when_pressed = self._handle_oled_button_press
        button.when_released = self._handle_oled_button_release
        button.when_held = self._handle_oled_button_hold
        self._oled_button = button
        self._oled_button_initialized = True
        logger.info("OLED front-panel button listener registered")

    def _queue_oled_button_action(self, action: str) -> None:
        with self._oled_button_lock:
            self._oled_button_actions.append(action)

    def _handle_oled_button_press(self) -> None:  # pragma: no cover - hardware callback
        self._oled_button_held = False

    def _handle_oled_button_hold(self) -> None:  # pragma: no cover - hardware callback
        self._oled_button_held = True
        self._queue_oled_button_action('snapshot')

    def _handle_oled_button_release(self) -> None:  # pragma: no cover - hardware callback
        if not self._oled_button_held:
            self._queue_oled_button_action('advance')
        self._oled_button_held = False

    def _process_oled_button_actions(self) -> None:
        pending: List[str] = []
        with self._oled_button_lock:
            while self._oled_button_actions:
                pending.append(self._oled_button_actions.popleft())

        for action in pending:
            if action == 'advance':
                self._advance_oled_rotation()
            elif action == 'snapshot':
                self._display_oled_snapshot()

    def _advance_oled_rotation(self) -> None:
        if not self._oled_rotation:
            return

        screens = self._oled_rotation.get('screens', [])
        if not screens:
            return

        current_index = self._oled_current_index
        if current_index >= len(screens):
            current_index = 0
            self._oled_current_index = 0

        screen_config = screens[current_index]
        self._display_oled_screen(screen_config)

        now = datetime.utcnow()
        self._last_oled_update = now

        current_index += 1
        if current_index >= len(screens):
            current_index = 0
            if self._oled_rotation.get('randomize'):
                random.shuffle(screens)
                self._oled_rotation['screens'] = screens

        self._oled_current_index = current_index
        self._update_rotation_state('oled', current_index, now)

    def _display_oled_snapshot(self) -> None:
        try:
            from app_core.oled import OLEDLine, initialise_oled_display
            import app_core.oled as oled_module
            from scripts.screen_renderer import ScreenRenderer
        except Exception as exc:  # pragma: no cover - renderer dependencies
            logger.debug("Unable to prepare OLED snapshot: %s", exc)
            return

        controller = oled_module.oled_controller or initialise_oled_display(logger)
        if controller is None:
            return

        renderer = ScreenRenderer()
        rendered = renderer.render_screen(SNAPSHOT_SCREEN_TEMPLATE)
        if not rendered:
            return

        raw_lines = rendered.get('lines', [])
        if not isinstance(raw_lines, list):
            return

        line_objects: List[OLEDLine] = []
        for entry in raw_lines:
            if isinstance(entry, OLEDLine):
                line_objects.append(entry)
                continue

            if not isinstance(entry, dict):
                continue

            text = str(entry.get('text', ''))
            try:
                x_value = int(entry.get('x', 0) or 0)
            except (TypeError, ValueError):
                x_value = 0

            y_raw = entry.get('y')
            try:
                y_value = int(y_raw) if y_raw is not None else None
            except (TypeError, ValueError):
                y_value = None

            max_width_raw = entry.get('max_width')
            try:
                max_width_value = int(max_width_raw) if max_width_raw is not None else None
            except (TypeError, ValueError):
                max_width_value = None

            try:
                spacing_value = int(entry.get('spacing', 2))
            except (TypeError, ValueError):
                spacing_value = 2

            line_objects.append(
                OLEDLine(
                    text=text,
                    x=x_value,
                    y=y_value,
                    font=str(entry.get('font', 'small')),
                    wrap=bool(entry.get('wrap', True)),
                    max_width=max_width_value,
                    spacing=spacing_value,
                    invert=entry.get('invert'),
                    allow_empty=bool(entry.get('allow_empty', False)),
                )
            )

        controller.display_lines(
            line_objects,
            clear=rendered.get('clear', True),
            invert=rendered.get('invert'),
        )

        now = datetime.utcnow()
        self._last_oled_update = now
        self._update_rotation_state('oled', self._oled_current_index, now)
        logger.info("Displayed OLED snapshot via front-panel button")

    def _convert_led_enum(self, enum_class, value_str: str, default):
        """Convert a string to an LED enum value.

        Args:
            enum_class: The enum class (Color, DisplayMode, Speed, etc.)
            value_str: String name of the enum value
            default: Default value if conversion fails

        Returns:
            Enum value or default
        """
        if enum_class is None:
            return default

        # If already an enum, return as-is
        if isinstance(value_str, enum_class):
            return value_str

        # Try to get enum by name
        try:
            return getattr(enum_class, value_str)
        except AttributeError:
            logger.warning(f"Unknown enum value '{value_str}' for {enum_class.__name__}, using default")
            return default

    def _display_led_screen(self, screen_config: Dict):
        """Display a screen on the LED sign.

        Args:
            screen_config: Screen configuration from rotation
        """
        try:
            from app_core.models import DisplayScreen, db
            from scripts.screen_renderer import ScreenRenderer
            import app_core.led as led_module

            screen_id = screen_config.get('screen_id')
            if not screen_id:
                return

            # Get screen from database
            screen = DisplayScreen.query.get(screen_id)
            if not screen or not screen.enabled:
                return

            # Render screen
            renderer = ScreenRenderer()
            rendered = renderer.render_screen(screen.to_dict())

            if not rendered:
                return

            # Send to LED display
            if led_module.led_controller:
                lines = rendered.get('lines', [])
                color_str = rendered.get('color', 'AMBER')
                mode_str = rendered.get('mode', 'HOLD')
                speed_str = rendered.get('speed', 'SPEED_3')

                # Convert strings to enum values
                color = self._convert_led_enum(led_module.Color, color_str, led_module.Color.AMBER if led_module.Color else color_str)
                mode = self._convert_led_enum(led_module.DisplayMode, mode_str, led_module.DisplayMode.HOLD if led_module.DisplayMode else mode_str)
                speed = self._convert_led_enum(led_module.Speed, speed_str, led_module.Speed.SPEED_3 if led_module.Speed else speed_str)

                led_module.led_controller.send_message(
                    lines=lines,
                    color=color,
                    mode=mode,
                    speed=speed,
                )

                # Update screen statistics
                screen.display_count += 1
                screen.last_displayed_at = datetime.utcnow()
                db.session.commit()

                logger.info(f"Displayed LED screen: {screen.name}")

        except Exception as e:
            logger.error(f"Error displaying LED screen: {e}")

    def _display_vfd_screen(self, screen_config: Dict):
        """Display a screen on the VFD display.

        Args:
            screen_config: Screen configuration from rotation
        """
        try:
            from app_core.models import DisplayScreen, db
            from scripts.screen_renderer import ScreenRenderer
            import app_core.vfd as vfd_module

            screen_id = screen_config.get('screen_id')
            if not screen_id:
                return

            # Get screen from database
            screen = DisplayScreen.query.get(screen_id)
            if not screen or not screen.enabled:
                return

            # Render screen
            renderer = ScreenRenderer()
            commands = renderer.render_screen(screen.to_dict())

            if not commands:
                return

            # Send to VFD display
            if vfd_module.vfd_controller:
                for command in commands:
                    cmd_type = command.get('type')

                    if cmd_type == 'clear':
                        vfd_module.vfd_controller.clear_display()

                    elif cmd_type == 'text':
                        vfd_module.vfd_controller.draw_text(
                            command.get('text', ''),
                            command.get('x', 0),
                            command.get('y', 0),
                        )

                    elif cmd_type == 'rectangle':
                        vfd_module.vfd_controller.draw_rectangle(
                            command.get('x1', 0),
                            command.get('y1', 0),
                            command.get('x2', 10),
                            command.get('y2', 10),
                            filled=command.get('filled', False),
                        )

                    elif cmd_type == 'line':
                        vfd_module.vfd_controller.draw_line(
                            command.get('x1', 0),
                            command.get('y1', 0),
                            command.get('x2', 10),
                            command.get('y2', 10),
                        )

                # Update screen statistics
                screen.display_count += 1
                screen.last_displayed_at = datetime.utcnow()
                db.session.commit()

                logger.info(f"Displayed VFD screen: {screen.name}")

        except Exception as e:
            logger.error(f"Error displaying VFD screen: {e}")

    def _display_oled_screen(self, screen_config: Dict):
        """Display a screen on the OLED module."""

        try:
            from app_core.models import DisplayScreen, db
            from scripts.screen_renderer import ScreenRenderer
            import app_core.oled as oled_module
            from app_core.oled import OLEDLine, initialise_oled_display

            screen_id = screen_config.get('screen_id')
            if not screen_id:
                return

            screen = DisplayScreen.query.get(screen_id)
            if not screen or not screen.enabled:
                return

            renderer = ScreenRenderer()
            rendered = renderer.render_screen(screen.to_dict())

            if not rendered:
                return

            controller = oled_module.oled_controller or initialise_oled_display(logger)
            if controller is None:
                return

            raw_lines = rendered.get('lines', [])
            if not isinstance(raw_lines, list):
                return

            line_objects: List[OLEDLine] = []
            for entry in raw_lines:
                if isinstance(entry, OLEDLine):
                    line_objects.append(entry)
                    continue

                if not isinstance(entry, dict):
                    continue

                text = str(entry.get('text', ''))

                try:
                    x_value = int(entry.get('x', 0) or 0)
                except (TypeError, ValueError):
                    x_value = 0

                y_raw = entry.get('y')
                try:
                    y_value = int(y_raw) if y_raw is not None else None
                except (TypeError, ValueError):
                    y_value = None

                max_width_raw = entry.get('max_width')
                try:
                    max_width_value = int(max_width_raw) if max_width_raw is not None else None
                except (TypeError, ValueError):
                    max_width_value = None

                try:
                    spacing_value = int(entry.get('spacing', 2))
                except (TypeError, ValueError):
                    spacing_value = 2

                line_objects.append(
                    OLEDLine(
                        text=text,
                        x=x_value,
                        y=y_value,
                        font=str(entry.get('font', 'small')),
                        wrap=bool(entry.get('wrap', True)),
                        max_width=max_width_value,
                        spacing=spacing_value,
                        invert=entry.get('invert'),
                        allow_empty=bool(entry.get('allow_empty', False)),
                    )
                )

            if (
                not line_objects
                and not rendered.get('allow_empty_frame', False)
                and not rendered.get('clear', True)
            ):
                return

            controller.display_lines(
                line_objects,
                clear=rendered.get('clear', True),
                invert=rendered.get('invert'),
            )

            screen.display_count += 1
            screen.last_displayed_at = datetime.utcnow()
            db.session.commit()

            logger.info(f"Displayed OLED screen: {screen.name}")

        except Exception as e:
            logger.error(f"Error displaying OLED screen: {e}")

    def _has_active_alerts(self) -> bool:
        """Check if there are active alerts.

        Returns:
            True if there are active alerts
        """
        try:
            from app_core.models import CAPAlert
            from datetime import datetime

            count = CAPAlert.query.filter(
                CAPAlert.expires > datetime.utcnow()
            ).count()

            return count > 0

        except Exception as e:
            logger.error(f"Error checking active alerts: {e}")
            return False

    def _update_rotation_state(self, display_type: str, current_index: int, timestamp: datetime):
        """Update rotation state in database.

        Args:
            display_type: 'led', 'vfd', or 'oled'
            current_index: Current screen index
            timestamp: Timestamp of last rotation
        """
        try:
            from app_core.models import ScreenRotation, db

            rotation = ScreenRotation.query.filter_by(
                display_type=display_type,
                enabled=True
            ).first()

            if rotation:
                rotation.current_screen_index = current_index
                rotation.last_rotation_at = timestamp
                db.session.commit()

        except Exception as e:
            logger.error(f"Error updating rotation state: {e}")


# Global instance
screen_manager = ScreenManager()
