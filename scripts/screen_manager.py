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
        "elements": [
            # Header (y=0-13, medium inverted)
            {"type": "text", "text": "SNAPSHOT", "x": 0, "y": 0, "font": "medium", "invert": True},
            # CPU bar (y=17-27)
            {"type": "text", "text": "CPU", "x": 0, "y": 17, "font": "small"},
            {"type": "bar", "value": "{status.system_resources.cpu_usage_percent}", "x": 26, "y": 18, "width": 76, "height": 7},
            {"type": "text", "text": "{status.system_resources.cpu_usage_percent}%", "x": 105, "y": 17, "font": "small"},
            # Memory bar (y=30-40)
            {"type": "text", "text": "MEM", "x": 0, "y": 30, "font": "small"},
            {"type": "bar", "value": "{status.system_resources.memory_usage_percent}", "x": 26, "y": 31, "width": 76, "height": 7},
            {"type": "text", "text": "{status.system_resources.memory_usage_percent}%", "x": 105, "y": 30, "font": "small"},
            # Status and alerts (y=43-53)
            {"type": "text", "text": "{status.status} - {status.active_alerts_count} alerts", "x": 0, "y": 43, "font": "small"},
            # Date/time (y=56-63)
            {"type": "text", "text": "{now.date} {now.time_24}", "x": 0, "y": 56, "font": "small"},
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
        self._oled_scroll_speed = 4  # pixels per frame (increased for faster scrolling)
        self._oled_scroll_fps = 60  # frames per second (increased for ultra-smooth scrolling)
        self._oled_screen_scroll_state: Optional[Dict[str, Any]] = None
        self._oled_screen_scroll_offset = 0
        self._last_oled_screen_frame_time = 0.0  # Use monotonic time for precise frame timing
        self._current_alert_id: Optional[int] = None
        self._current_alert_priority: Optional[int] = None
        self._current_alert_text: Optional[str] = None
        self._last_oled_alert_render_time = 0.0  # Use monotonic time for precise frame timing
        self._cached_header_text: Optional[str] = None  # Cache to reduce flickering
        self._cached_header_image = None  # Pre-rendered header to avoid redraw
        self._cached_scroll_canvas = None  # Pre-rendered full scrolling text
        self._cached_scroll_dimensions = None  # Dimensions from prepare_scroll_content
        self._cached_scroll_max_offset = 0  # Maximum offset before loop reset
        self._cached_body_area_height = 0  # Height of body scrolling area
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
        """Main loop for screen rotation with precise timing for smooth scrolling."""
        target_fps = 60  # Target FPS for smooth OLED scrolling
        target_interval = 1.0 / target_fps  # Target time per loop iteration

        while self._running:
            loop_start = time.monotonic()

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

            except Exception as e:
                logger.error(f"Error in screen manager loop: {e}")
                time.sleep(5)
                continue

            # Calculate how long to sleep to maintain target FPS
            # This accounts for processing time to ensure consistent frame timing
            loop_duration = time.monotonic() - loop_start
            sleep_time = max(0, target_interval - loop_duration)

            if sleep_time > 0:
                time.sleep(sleep_time)

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
            self._clear_oled_screen_scroll_state()
            return

        now = datetime.utcnow()
        if self._oled_rotation.get('skip_on_alert') and self._handle_oled_alert_preemption(now):
            self._clear_oled_screen_scroll_state()
            return

        screens = self._oled_rotation.get('screens', [])
        if not screens:
            self._clear_oled_screen_scroll_state()
            return

        current_index = self._oled_current_index
        if current_index >= len(screens):
            current_index = 0
            self._oled_current_index = 0

        screen_config = screens[current_index]
        duration = screen_config.get('duration', 10)

        # Update any in-progress OLED scroll animations even if the rotation entry
        # has not advanced yet.
        self._update_active_oled_scroll(now)

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

            # Check if using new elements-based format (for bar graphs, etc.)
            raw_elements = rendered.get('elements')
            if raw_elements is not None and isinstance(raw_elements, list):
                # New elements-based format
                controller.render_frame(
                    raw_elements,
                    clear=rendered.get('clear', True),
                    invert=rendered.get('invert'),
                )

                screen.display_count += 1
                screen.last_displayed_at = datetime.utcnow()
                db.session.commit()

                logger.info(f"Displayed OLED screen (elements): {screen.name}")
                return

            # Legacy lines-based format
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

            # Reset any previous animation context before showing the new frame.
            self._clear_oled_screen_scroll_state()

            scroll_started = self._start_oled_template_scroll(
                controller,
                line_objects,
                rendered,
                oled_module,
            )

            if not scroll_started:
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

    def _start_oled_template_scroll(
        self,
        controller,
        line_objects: List["OLEDLine"],
        rendered: Dict[str, Any],
        oled_module,
    ) -> bool:
        """Prepare scroll state for template-driven OLED animations."""

        scroll_effect = rendered.get('scroll_effect')
        if not isinstance(scroll_effect, str):
            return False

        effect_name = scroll_effect.strip().lower()
        if not effect_name or effect_name == 'static':
            return False

        try:
            from app_core.oled import OLEDScrollEffect
        except Exception as exc:  # pragma: no cover - hardware optional
            logger.debug("OLED scroll effects unavailable: %s", exc)
            return False

        try:
            effect = OLEDScrollEffect(effect_name)
        except ValueError:
            logger.warning("Unknown OLED scroll effect '%s' in template", effect_name)
            return False

        try:
            raw_speed = rendered.get('scroll_speed')
            speed = int(raw_speed) if raw_speed is not None else oled_module.OLED_SCROLL_SPEED
        except (TypeError, ValueError):
            speed = oled_module.OLED_SCROLL_SPEED

        try:
            raw_fps = rendered.get('scroll_fps')
            fps = int(raw_fps) if raw_fps is not None else oled_module.OLED_SCROLL_FPS
        except (TypeError, ValueError):
            fps = oled_module.OLED_SCROLL_FPS

        speed = max(1, min(20, speed))
        fps = max(5, min(60, fps))

        # Pre-render the content once before starting the animation
        try:
            content_image, dimensions = controller.prepare_scroll_content(
                line_objects,
                invert=rendered.get('invert'),
            )
        except Exception as exc:
            logger.error("Unable to prepare OLED scroll content: %s", exc)
            return False

        # Pass dimensions directly - contains original_width, separator_width, max_x, max_y
        max_offset = self._resolve_scroll_limit(effect, dimensions, controller)
        if max_offset <= 0:
            return False

        # Render the first frame to display the initial state
        try:
            controller.render_scroll_frame(
                content_image,
                dimensions,
                effect,
                offset=0,
                invert=rendered.get('invert'),
            )
        except Exception as exc:
            logger.error("Unable to start OLED scroll: %s", exc)
            return False

        # Store the pre-rendered content for use in animation frames
        self._oled_screen_scroll_state = {
            'content_image': content_image,
            'dimensions': dimensions,
            'effect': effect,
            'invert': rendered.get('invert'),
            'speed': speed,
            'fps': fps,
            'max_offset': max_offset,
        }
        self._oled_screen_scroll_offset = 0
        self._last_oled_screen_frame_time = time.monotonic()
        return True

    def _clear_oled_screen_scroll_state(self) -> None:
        """Reset cached scroll animation data for normal OLED screens."""

        self._oled_screen_scroll_state = None
        self._oled_screen_scroll_offset = 0
        self._last_oled_screen_frame_time = 0.0

    def _update_active_oled_scroll(self, now: datetime) -> None:
        """Advance OLED template scrolling when active."""

        if not self._oled_screen_scroll_state:
            return

        try:
            import app_core.oled as oled_module
            from app_core.oled import initialise_oled_display
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("OLED module unavailable for scrolling: %s", exc)
            self._clear_oled_screen_scroll_state()
            return

        controller = oled_module.oled_controller or initialise_oled_display(logger)
        if controller is None:
            self._clear_oled_screen_scroll_state()
            return

        state = self._oled_screen_scroll_state
        current_time = time.monotonic()

        # Calculate frame interval based on FPS
        frame_interval = 1.0 / max(1, state['fps'])

        # Calculate elapsed time since last frame
        elapsed = current_time - self._last_oled_screen_frame_time

        # Only render if we've exceeded the frame interval
        if elapsed < frame_interval:
            return

        try:
            controller.render_scroll_frame(
                state['content_image'],
                state['dimensions'],
                state['effect'],
                offset=self._oled_screen_scroll_offset,
                invert=state.get('invert'),
            )
        except Exception as exc:
            logger.error("Error rendering OLED scroll frame: %s", exc)
            self._clear_oled_screen_scroll_state()
            return

        # Update timing with actual current time
        self._last_oled_screen_frame_time = current_time

        # Advance scroll offset proportional to elapsed time for smooth scrolling
        expected_frames = elapsed / frame_interval
        pixels_to_advance = max(1, int(state['speed'] * expected_frames))
        self._oled_screen_scroll_offset += pixels_to_advance

        # Handle loop wraparound
        if self._oled_screen_scroll_offset >= max(1, state['max_offset']):
            self._oled_screen_scroll_offset = 0

    def _resolve_scroll_limit(self, effect, extents: Dict[str, int], controller) -> int:
        """Map a scroll effect to the maximum offset required before looping.
        
        For horizontal scrolling with the padded buffer approach, the limit is set to 
        original_width + separator_width. This ensures the animation completes one full 
        cycle (showing all of the original text plus the separator) before resetting to 
        offset 0 for a seamless loop.
        """

        try:
            from app_core.oled import OLEDScrollEffect
        except Exception:  # pragma: no cover - optional dependency
            return max(controller.width, controller.height)

        # For horizontal scrolling, use original_width + separator_width for the loop point
        if effect in (OLEDScrollEffect.SCROLL_LEFT, OLEDScrollEffect.SCROLL_RIGHT):
            original_width = extents.get('original_width', controller.width)
            separator_width = extents.get('separator_width', 0)
            return original_width + separator_width
            
        # For vertical scrolling, use the content height
        if effect in (OLEDScrollEffect.SCROLL_UP, OLEDScrollEffect.SCROLL_DOWN):
            vertical_limit = max(controller.height, extents.get('max_y', controller.height))
            return vertical_limit
            
        # Wipe effects use display dimensions
        if effect in (OLEDScrollEffect.WIPE_LEFT, OLEDScrollEffect.WIPE_RIGHT):
            return controller.width
        if effect in (OLEDScrollEffect.WIPE_UP, OLEDScrollEffect.WIPE_DOWN):
            return controller.height
            
        # Fade effect
        if effect == OLEDScrollEffect.FADE_IN:
            return 4

        # Default fallback
        horizontal_limit = max(controller.width, extents.get('max_x', controller.width))
        vertical_limit = max(controller.height, extents.get('max_y', controller.height))
        return max(horizontal_limit, vertical_limit)

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

        # Use monotonic time for precise frame timing
        current_time = time.monotonic()

        # Calculate target frame interval based on FPS
        frame_interval = 1.0 / max(1, self._oled_scroll_fps)

        # Calculate elapsed time since last frame
        elapsed = current_time - self._last_oled_alert_render_time

        # Only render if we've exceeded the frame interval
        if elapsed < frame_interval:
            return True

        # Render the frame
        self._display_alert_scroll_frame(top_alert)

        # Update timing - use actual current time for precision
        self._last_oled_alert_render_time = current_time
        self._last_oled_update = now

        # Advance scroll offset proportional to elapsed time for smooth scrolling
        # This compensates for any timing variations
        expected_frames = elapsed / frame_interval
        pixels_to_advance = int(self._oled_scroll_speed * expected_frames)
        self._oled_scroll_offset += pixels_to_advance

        return True

    def _prepare_alert_scroll(self, alert_meta: Dict[str, Any]) -> None:
        """Prepare alert text for right-to-left scrolling using seamless scrolling API."""
        try:
            import app_core.oled as oled_module
            from app_core.oled import initialise_oled_display, OLEDLine
            from PIL import Image, ImageDraw
        except Exception as exc:
            logger.debug("OLED module unavailable: %s", exc)
            return

        controller = oled_module.oled_controller or initialise_oled_display(logger)
        if controller is None:
            return

        # Get scroll configuration from environment
        self._oled_scroll_speed = oled_module.OLED_SCROLL_SPEED
        self._oled_scroll_fps = oled_module.OLED_SCROLL_FPS

        # Reset state
        self._oled_scroll_effect = True  # Just a flag to indicate scrolling is active
        self._oled_scroll_offset = 0
        self._cached_header_text = None  # Clear cache for new alert
        self._cached_header_image = None
        self._current_alert_id = alert_meta.get('id')
        self._current_alert_priority = alert_meta.get('priority_rank')
        self._current_alert_text = alert_meta.get('body_text')

        # Pre-render the entire scrolling text canvas for smooth scrolling
        body_text = alert_meta.get('body_text') or 'Active alert in effect.'
        body_text = ' '.join(body_text.split())  # Clean whitespace

        # Get display parameters
        width = controller.width
        height = controller.height
        active_invert = controller.default_invert

        # Calculate body area dimensions
        header_font = controller._fonts.get('small', controller._fonts['small'])
        header_height = controller._line_height(header_font) + 1
        body_height = height - header_height

        # Always use HUGE font for maximum visibility (user preference)
        body_font_name = 'huge'
        logger.info("Using HUGE font for scrolling alert (%s chars)", len(body_text))

        # Calculate text height
        body_font = controller._fonts.get(body_font_name, controller._fonts.get('xlarge', controller._fonts.get('large', controller._fonts['small'])))
        temp_img = Image.new("1", (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        try:
            # Get text bounding box for accurate height
            bbox = temp_draw.textbbox((0, 0), body_text, font=body_font)
            text_height = bbox[3] - bbox[1]
        except AttributeError:
            # Fallback for older PIL versions
            text_height = body_font.getsize(body_text)[1]

        # Position text to start immediately at top of body area (y=0 in body coordinates)
        # This ensures the header and scrolling text don't have a gap between them
        text_y = 0

        # Use the seamless scrolling API with OLEDLine
        # This will create a buffer with pattern: [text][separator][text]
        # ensuring only ONE copy of the text is visible at any time
        lines = [
            OLEDLine(
                text=body_text,
                x=0,
                y=text_y,
                font=body_font_name,
                wrap=False,  # Keep as single line for smooth scrolling
                allow_empty=False,
            )
        ]

        try:
            # Use prepare_scroll_content which handles seamless looping correctly
            scroll_canvas, dimensions = controller.prepare_scroll_content(
                lines,
                invert=active_invert,
            )

            # Crop to body area height (prepare_scroll_content may return full display height)
            if scroll_canvas.height > body_height:
                scroll_canvas = scroll_canvas.crop((0, 0, scroll_canvas.width, body_height))

        except Exception as e:
            logger.error(f"Failed to create scroll canvas: {e}")
            raise

        # Cache the pre-rendered canvas and dimensions
        self._cached_scroll_canvas = scroll_canvas
        self._cached_scroll_dimensions = dimensions
        self._cached_body_area_height = body_height

        # Calculate max offset for seamless looping
        # This is original_width + separator_width as per the seamless scrolling algorithm
        original_width = dimensions.get('original_width', width)
        separator_width = dimensions.get('separator_width', width)
        self._cached_scroll_max_offset = original_width + separator_width

        header = alert_meta.get('header_text') or alert_meta.get('event') or 'Alert'
        logger.info(
            "OLED alert scroll started: %s (offset limit: %spx, %spx at %sfps)",
            header, self._cached_scroll_max_offset, self._oled_scroll_speed, self._oled_scroll_fps
        )

    def _display_alert_scroll_frame(self, alert_meta: Dict[str, Any]) -> None:
        """Render a single frame of the scrolling alert animation using seamless scrolling."""
        if self._oled_scroll_effect is None or self._cached_scroll_canvas is None:
            return

        try:
            from app_core.oled import initialise_oled_display
            import app_core.oled as oled_module
            from PIL import Image
        except Exception as exc:  # pragma: no cover - hardware optional
            logger.debug("OLED controller unavailable for alert display: %s", exc)
            return

        controller = oled_module.oled_controller or initialise_oled_display(logger)
        if controller is None:
            return

        # Get current date/time for header in local timezone
        from app_utils.time import local_now
        now = local_now()
        # Remove seconds from header to reduce update frequency and flickering
        header_text = now.strftime("%m/%d/%y %I:%M %p")

        # Get display dimensions
        width = controller.width
        height = controller.height

        # Setup display parameters
        active_invert = controller.default_invert
        background = 255 if active_invert else 0
        text_colour = 0 if active_invert else 255

        # Get fonts and calculate header height
        header_font = controller._fonts.get('small', controller._fonts['small'])
        header_height = controller._line_height(header_font) + 1

        # Only recreate header image if text changed (reduces flickering)
        if self._cached_header_text != header_text or self._cached_header_image is None:
            from PIL import ImageDraw
            header_image = Image.new("1", (width, header_height), color=background)
            header_draw = ImageDraw.Draw(header_image)
            header_draw.text((0, 0), header_text, font=header_font, fill=text_colour)
            self._cached_header_image = header_image
            self._cached_header_text = header_text

        # Create final display image and paste cached header
        display_image = Image.new("1", (width, height), color=background)
        display_image.paste(self._cached_header_image, (0, 0))

        # Crop the visible window from pre-rendered seamless scroll canvas
        # The canvas has pattern: [text][separator][text] for seamless looping
        crop_left = self._oled_scroll_offset
        crop_right = crop_left + width
        crop_box = (crop_left, 0, crop_right, self._cached_body_area_height)

        # Crop the visible window from pre-rendered canvas
        try:
            body_window = self._cached_scroll_canvas.crop(crop_box)
        except Exception as e:
            logger.error(f"❌ Crop failed! crop_box={crop_box}, canvas_size={self._cached_scroll_canvas.size}: {e}")
            return

        # Paste the scrolling body below the header
        display_image.paste(body_window, (0, header_height))

        # Store and display the final image
        controller._last_image = display_image.copy()  # Store for preview
        controller.device.display(display_image)

        # Check if we need to loop back using the seamless loop point
        # Loop at original_width + separator_width for seamless transition
        if self._oled_scroll_offset >= self._cached_scroll_max_offset:
            self._oled_scroll_offset = 0

    def _reset_oled_alert_state(self) -> None:
        """Reset OLED alert scroll state."""
        self._oled_scroll_offset = 0
        self._oled_scroll_effect = None
        self._cached_header_text = None
        self._cached_header_image = None
        self._cached_scroll_canvas = None
        self._cached_scroll_dimensions = None
        self._cached_scroll_max_offset = 0
        self._cached_body_area_height = 0
        self._current_alert_id = None
        self._current_alert_priority = None
        self._current_alert_text = None
        self._last_oled_alert_render_time = 0.0

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
