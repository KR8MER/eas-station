"""Screen manager service for LED and VFD display rotation.

This module manages automatic screen rotation, scheduling, and display updates
for custom screen templates.
"""

import logging
import random
import textwrap
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional

from flask import Flask

from app_utils import ALERT_SOURCE_IPAWS, ALERT_SOURCE_MANUAL

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
        # Pixel-by-pixel scrolling configuration
        self._oled_scroll_offset = 0
        self._oled_scroll_effect = None
        self._oled_scroll_speed = 2  # pixels per frame
        self._oled_scroll_fps = 30  # frames per second
        self._current_alert_id: Optional[int] = None
        self._current_alert_priority: Optional[int] = None
        self._current_alert_text: Optional[str] = None
        self._last_oled_alert_render = datetime.min
        self._active_alert_cache: List[Dict[str, Any]] = []
        self._active_alert_cache_timestamp = datetime.min
        self._active_alert_cache_ttl = timedelta(seconds=1)

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

                # Use faster loop for smooth OLED scrolling
                time.sleep(0.033)  # ~30 FPS for smooth scrolling

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

        now = datetime.utcnow()
        if self._oled_rotation.get('skip_on_alert') and self._handle_oled_alert_preemption(now):
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

    def _handle_oled_alert_preemption(self, now: datetime) -> bool:
        """Display high-priority alerts on the OLED, preempting normal rotation."""

        alerts = self._get_cached_active_alerts(now)
        if not alerts:
            if self._current_alert_id is not None:
                self._reset_oled_alert_state()
            return False

        alerts.sort(
            key=lambda entry: (
                entry['priority_rank'],
                -entry['priority_ts'].timestamp(),
                entry['id'],
            )
        )
        top_alert = alerts[0]

        if (
            self._current_alert_id != top_alert['id']
            or self._current_alert_priority != top_alert['priority_rank']
            or self._current_alert_text != top_alert['body_text']
        ):
            self._prepare_alert_scroll(top_alert)

        if self._oled_scroll_effect is None:
            return True

        # Calculate frame interval based on FPS
        frame_interval = timedelta(seconds=1.0 / self._oled_scroll_fps)

        if now - self._last_oled_alert_render < frame_interval:
            return True

        self._display_alert_scroll_frame(top_alert)
        self._last_oled_alert_render = now
        self._last_oled_update = now

        # Advance scroll offset (loop is handled in display function)
        self._oled_scroll_offset += self._oled_scroll_speed

        return True

    def _prepare_alert_scroll(self, alert_meta: Dict[str, Any]) -> None:
        """Prepare alert text for right-to-left scrolling."""
        try:
            import app_core.oled as oled_module
        except Exception as exc:
            logger.debug("OLED module unavailable: %s", exc)
            return

        # Get scroll configuration from environment
        self._oled_scroll_speed = oled_module.OLED_SCROLL_SPEED
        self._oled_scroll_fps = oled_module.OLED_SCROLL_FPS

        # We're using simple right-to-left scrolling
        self._oled_scroll_effect = True  # Just a flag to indicate scrolling is active
        self._oled_scroll_offset = 0
        self._current_alert_id = alert_meta.get('id')
        self._current_alert_priority = alert_meta.get('priority_rank')
        self._current_alert_text = alert_meta.get('body_text')
        header = alert_meta.get('header_text') or alert_meta.get('event') or 'Alert'
        logger.info("OLED alert scroll engaged: %s (speed: %spx at %sfps)", header, self._oled_scroll_speed, self._oled_scroll_fps)

    def _display_alert_scroll_frame(self, alert_meta: Dict[str, Any]) -> None:
        """Render a single frame of the scrolling alert animation."""
        if self._oled_scroll_effect is None:
            return

        try:
            from app_core.oled import OLEDLine, initialise_oled_display
            import app_core.oled as oled_module
            from PIL import Image, ImageDraw
        except Exception as exc:  # pragma: no cover - hardware optional
            logger.debug("OLED controller unavailable for alert display: %s", exc)
            return

        controller = oled_module.oled_controller or initialise_oled_display(logger)
        if controller is None:
            return

        # Get current date/time for header in local timezone
        from app_utils.time import local_now
        now = local_now()
        header_text = now.strftime("%m/%d/%y %I:%M:%S %p")

        body_text = alert_meta.get('body_text') or 'Active alert in effect.'

        # Clean body text by collapsing whitespace and removing newlines
        body_text = ' '.join(body_text.split())

        # Get display dimensions
        width = controller.width
        height = controller.height

        # Create final display image
        active_invert = controller.default_invert
        background = 255 if active_invert else 0
        text_colour = 0 if active_invert else 255
        display_image = Image.new("1", (width, height), color=background)
        draw = ImageDraw.Draw(display_image)

        # Render static date/time header at top (y=0)
        header_font = controller._fonts.get('small', controller._fonts['small'])
        draw.text((0, 0), header_text, font=header_font, fill=text_colour)

        # Calculate header height for positioning body text
        header_height = controller._line_height(header_font) + 1  # Minimal spacing

        # Render scrolling body text with HUGE font
        body_font = controller._fonts.get('huge', controller._fonts.get('xlarge', controller._fonts.get('large', controller._fonts['small'])))

        # Calculate text width for scrolling
        try:
            text_width = int(draw.textlength(body_text, font=body_font))
        except AttributeError:
            text_width = body_font.getsize(body_text)[0]

        # Calculate scroll position (right to left)
        scroll_x = width - self._oled_scroll_offset

        # If text has scrolled completely off the left, reset to right
        # Reset when right edge reaches left edge of screen for continuous loop
        if scroll_x <= -text_width:
            self._oled_scroll_offset = 0
            scroll_x = width

        # Draw the scrolling text
        body_y = header_height
        draw.text((scroll_x, body_y), body_text, font=body_font, fill=text_colour)

        # Display the final image
        controller.device.display(display_image)

        logger.debug(
            "OLED alert scroll: %s (offset %s, x_pos %s)",
            header_text,
            self._oled_scroll_offset,
            scroll_x,
        )

    def _reset_oled_alert_state(self) -> None:
        """Reset OLED alert scroll state."""
        self._oled_scroll_offset = 0
        self._oled_scroll_effect = None
        self._current_alert_id = None
        self._current_alert_priority = None
        self._current_alert_text = None
        self._last_oled_alert_render = datetime.min

    def _get_cached_active_alerts(self, now: datetime) -> List[Dict[str, Any]]:
        if now - self._active_alert_cache_timestamp <= self._active_alert_cache_ttl:
            return list(self._active_alert_cache)

        payloads = self._query_active_alert_payloads()
        self._active_alert_cache = payloads
        self._active_alert_cache_timestamp = now
        return list(payloads)

    def _query_active_alert_payloads(self) -> List[Dict[str, Any]]:
        try:
            from sqlalchemy.orm import load_only

            from app_core.alerts import (
                get_active_alerts_query,
                load_alert_plain_text_map,
            )
            from app_core.models import CAPAlert
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Unable to query active alerts for OLED: %s", exc)
            return []

        query = (
            get_active_alerts_query()
            .options(
                load_only(
                    CAPAlert.id,
                    CAPAlert.event,
                    CAPAlert.severity,
                    CAPAlert.headline,
                    CAPAlert.description,
                    CAPAlert.instruction,
                    CAPAlert.area_desc,
                    CAPAlert.expires,
                    CAPAlert.sent,
                    CAPAlert.updated_at,
                    CAPAlert.created_at,
                    CAPAlert.source,
                )
            )
            .order_by(CAPAlert.sent.desc())
        )

        alerts = query.all()
        if not alerts:
            return []

        alert_ids = [alert.id for alert in alerts if alert.id]
        plain_text_map = load_alert_plain_text_map(alert_ids)
        severity_order = {
            'Extreme': 0,
            'Severe': 1,
            'Moderate': 2,
            'Minor': 3,
            'Unknown': 4,
        }

        payloads: List[Dict[str, Any]] = []
        for alert in alerts:
            if not alert.id:
                continue

            severity = (alert.severity or 'Unknown').title()
            priority_rank = severity_order.get(severity, len(severity_order))
            source_value = getattr(alert, 'source', None)
            is_eas_source = source_value in {ALERT_SOURCE_IPAWS, ALERT_SOURCE_MANUAL}
            body_text = self._compose_alert_body_text(alert, plain_text_map, is_eas_source)
            header_text = self._format_alert_header(alert, severity)
            payloads.append(
                {
                    'id': alert.id,
                    'severity': severity,
                    'event': alert.event,
                    'source': source_value,
                    'body_text': body_text,
                    'header_text': header_text,
                    'priority_rank': priority_rank,
                    'priority_ts': self._extract_alert_priority_timestamp(alert),
                }
            )

        return payloads

    @staticmethod
    def _compose_alert_body_text(alert, plain_text_map: Dict[int, str], is_eas_source: bool) -> str:
        if is_eas_source:
            plain_text = plain_text_map.get(alert.id)
            if plain_text:
                return plain_text.strip()

        segments: List[str] = []
        for attr in ('headline', 'description', 'instruction'):
            value = getattr(alert, attr, '') or ''
            if value:
                segments.append(str(value).strip())

        combined = '\n\n'.join(segments).strip()
        if combined:
            return combined

        fallback = getattr(alert, 'event', None) or 'Active alert in effect.'
        return str(fallback)

    @staticmethod
    def _format_alert_header(alert, severity: str) -> str:
        parts = []
        severity_value = severity.strip()
        if severity_value:
            parts.append(severity_value)
        event_value = getattr(alert, 'event', '') or ''
        if event_value:
            parts.append(str(event_value).strip())
        header = ' '.join(parts).strip()
        return header or 'Alert'

    @staticmethod
    def _extract_alert_priority_timestamp(alert) -> datetime:
        for attr_name in ('sent', 'updated_at', 'created_at'):
            candidate = getattr(alert, attr_name, None)
            if isinstance(candidate, datetime):
                return candidate.replace(tzinfo=None) if candidate.tzinfo else candidate
        return datetime.utcnow()

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
