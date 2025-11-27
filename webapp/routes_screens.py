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

from __future__ import annotations

"""Custom screen management routes for LED and VFD displays."""

import json
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app_core.extensions import db
from app_core.models import DisplayScreen, ScreenRotation
from app_utils import utc_now
from scripts.screen_renderer import ScreenRenderer


def _convert_led_enum(enum_class, value_str: str, default):
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
        return default


# Display dimensions for bounds checking
DISPLAY_DIMENSIONS = {
    "oled": {"width": 128, "height": 64},
    "vfd": {"width": 140, "height": 32},
}


def _validate_element_bounds(template_data: Dict, display_type: str) -> List[str]:
    """Validate that screen elements are within display bounds.
    
    Args:
        template_data: Screen template data with elements
        display_type: Type of display (oled, vfd)
        
    Returns:
        List of warning messages for out-of-bounds elements
    """
    warnings = []
    dims = DISPLAY_DIMENSIONS.get(display_type)
    if not dims:
        return warnings
    
    max_width = dims["width"]
    max_height = dims["height"]
    
    elements = template_data.get("elements", [])
    for i, elem in enumerate(elements):
        elem_type = elem.get("type", "")
        x = elem.get("x", 0)
        y = elem.get("y", 0)
        
        # Check if starting position is out of bounds
        if x >= max_width:
            warnings.append(f"Element {i} ({elem_type}): x={x} exceeds display width ({max_width})")
        if y >= max_height:
            warnings.append(f"Element {i} ({elem_type}): y={y} exceeds display height ({max_height})")
        
        # Check bar/rectangle dimensions
        if elem_type in ["bar", "rectangle"]:
            width = elem.get("width", 0)
            height = elem.get("height", 0)
            if x + width > max_width:
                warnings.append(f"Element {i} ({elem_type}): x+width={x+width} exceeds display width ({max_width})")
            if y + height > max_height:
                warnings.append(f"Element {i} ({elem_type}): y+height={y+height} exceeds display height ({max_height})")
    
    return warnings


def register(app: Flask, logger) -> None:
    """Register custom screen management endpoints."""

    route_logger = logger.getChild("routes_screens")

    # ============================================================
    # Display Screen Management
    # ============================================================

    @app.route("/api/screens", methods=["GET"])
    def get_screens():
        """Get all display screens."""
        try:
            display_type = request.args.get("display_type")
            enabled_only = request.args.get("enabled", "false").lower() == "true"

            query = DisplayScreen.query

            if display_type:
                query = query.filter_by(display_type=display_type)

            if enabled_only:
                query = query.filter_by(enabled=True)

            screens = query.order_by(DisplayScreen.name).all()

            return jsonify({
                "screens": [screen.to_dict() for screen in screens]
            })

        except Exception as e:
            route_logger.error(f"Error fetching screens: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screens/<int:screen_id>", methods=["GET"])
    def get_screen(screen_id: int):
        """Get a specific display screen."""
        try:
            screen = DisplayScreen.query.get(screen_id)

            if not screen:
                return jsonify({"error": "Screen not found"}), 404

            return jsonify(screen.to_dict())

        except Exception as e:
            route_logger.error(f"Error fetching screen {screen_id}: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screens", methods=["POST"])
    def create_screen():
        """Create a new display screen."""
        try:
            data = request.get_json()

            if not data:
                return jsonify({"error": "No data provided"}), 400

            # Validate required fields
            required_fields = ["name", "display_type", "template_data"]
            for field in required_fields:
                if field not in data:
                    return jsonify({"error": f"Missing required field: {field}"}), 400

            # Validate display_type
            if data["display_type"] not in ["led", "vfd", "oled"]:
                return jsonify({"error": "display_type must be 'led', 'vfd', or 'oled'"}), 400

            # Validate element bounds for OLED/VFD displays
            template_data = data["template_data"]
            display_type = data["display_type"]
            if display_type in ["oled", "vfd"]:
                warnings = _validate_element_bounds(template_data, display_type)
                if warnings:
                    route_logger.warning(f"Screen '{data['name']}' has elements out of bounds: {warnings}")

            # Create screen
            screen = DisplayScreen(
                name=data["name"],
                description=data.get("description"),
                display_type=data["display_type"],
                enabled=data.get("enabled", True),
                priority=data.get("priority", 2),
                refresh_interval=data.get("refresh_interval", 30),
                duration=data.get("duration", 10),
                template_data=data["template_data"],
                data_sources=data.get("data_sources", []),
                conditions=data.get("conditions"),
            )

            db.session.add(screen)
            db.session.commit()

            route_logger.info(f"Created screen: {screen.name} (ID: {screen.id})")

            return jsonify(screen.to_dict()), 201

        except IntegrityError as e:
            db.session.rollback()
            route_logger.error(f"Integrity error creating screen: {e}")
            return jsonify({"error": "Screen with this name already exists"}), 409

        except Exception as e:
            db.session.rollback()
            route_logger.error(f"Error creating screen: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screens/<int:screen_id>", methods=["PUT"])
    def update_screen(screen_id: int):
        """Update a display screen."""
        try:
            screen = DisplayScreen.query.get(screen_id)

            if not screen:
                return jsonify({"error": "Screen not found"}), 404

            data = request.get_json()

            if not data:
                return jsonify({"error": "No data provided"}), 400

            # Update fields
            if "name" in data:
                screen.name = data["name"]
            if "description" in data:
                screen.description = data["description"]
            if "display_type" in data:
                if data["display_type"] not in ["led", "vfd", "oled"]:
                    return jsonify({"error": "display_type must be 'led', 'vfd', or 'oled'"}), 400
                screen.display_type = data["display_type"]
            if "enabled" in data:
                screen.enabled = data["enabled"]
            if "priority" in data:
                screen.priority = data["priority"]
            if "refresh_interval" in data:
                screen.refresh_interval = data["refresh_interval"]
            if "duration" in data:
                screen.duration = data["duration"]
            if "template_data" in data:
                screen.template_data = data["template_data"]
            if "data_sources" in data:
                screen.data_sources = data["data_sources"]
            if "conditions" in data:
                screen.conditions = data["conditions"]

            screen.updated_at = utc_now()
            db.session.commit()

            route_logger.info(f"Updated screen: {screen.name} (ID: {screen.id})")

            return jsonify(screen.to_dict())

        except IntegrityError as e:
            db.session.rollback()
            route_logger.error(f"Integrity error updating screen: {e}")
            return jsonify({"error": "Screen with this name already exists"}), 409

        except Exception as e:
            db.session.rollback()
            route_logger.error(f"Error updating screen {screen_id}: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screens/<int:screen_id>", methods=["DELETE"])
    def delete_screen(screen_id: int):
        """Delete a display screen."""
        try:
            screen = DisplayScreen.query.get(screen_id)

            if not screen:
                return jsonify({"error": "Screen not found"}), 404

            screen_name = screen.name
            db.session.delete(screen)
            db.session.commit()

            route_logger.info(f"Deleted screen: {screen_name} (ID: {screen_id})")

            return jsonify({"message": "Screen deleted successfully"})

        except Exception as e:
            db.session.rollback()
            route_logger.error(f"Error deleting screen {screen_id}: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screens/<int:screen_id>/preview", methods=["GET"])
    def preview_screen(screen_id: int):
        """Preview a screen's rendered output."""
        try:
            screen = DisplayScreen.query.get(screen_id)

            if not screen:
                return jsonify({"error": "Screen not found"}), 404

            # Render screen
            renderer = ScreenRenderer(allow_preview_samples=True)
            rendered = renderer.render_screen(screen.to_dict())

            if not rendered:
                return jsonify({"error": "Failed to render screen"}), 500

            return jsonify({
                "screen": screen.to_dict(),
                "rendered": rendered,
            })

        except Exception as e:
            route_logger.error(f"Error previewing screen {screen_id}: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/screens/<int:screen_id>/display", methods=["POST"])
    def display_screen_now(screen_id: int):
        """Display a screen immediately (override rotation)."""
        try:
            screen = DisplayScreen.query.get(screen_id)

            if not screen:
                return jsonify({"error": "Screen not found"}), 404

            # Render screen
            renderer = ScreenRenderer(allow_preview_samples=False)
            rendered = renderer.render_screen(screen.to_dict())

            if not rendered:
                return jsonify({"error": "Failed to render screen"}), 500

            # Display on appropriate device
            if screen.display_type == "led":
                import app_core.led as led_module

                if not led_module.led_controller:
                    return jsonify({"error": "LED controller not available"}), 503

                lines = rendered.get("lines", [])
                color_str = rendered.get("color", "AMBER")
                mode_str = rendered.get("mode", "HOLD")
                speed_str = rendered.get("speed", "SPEED_3")

                # Convert strings to enum values
                color = _convert_led_enum(led_module.Color, color_str, led_module.Color.AMBER if led_module.Color else color_str)
                mode = _convert_led_enum(led_module.DisplayMode, mode_str, led_module.DisplayMode.HOLD if led_module.DisplayMode else mode_str)
                speed = _convert_led_enum(led_module.Speed, speed_str, led_module.Speed.SPEED_3 if led_module.Speed else speed_str)

                led_module.led_controller.send_message(
                    lines=lines,
                    color=color,
                    mode=mode,
                    speed=speed,
                )

            elif screen.display_type == "vfd":
                from app_core.vfd import vfd_controller

                if not vfd_controller:
                    return jsonify({"error": "VFD controller not available"}), 503

                for command in rendered:
                    cmd_type = command.get("type")

                    if cmd_type == "clear":
                        vfd_controller.clear_display()

                    elif cmd_type == "text":
                        vfd_controller.draw_text(
                            command.get("text", ""),
                            command.get("x", 0),
                            command.get("y", 0),
                        )

                    elif cmd_type == "rectangle":
                        vfd_controller.draw_rectangle(
                            command.get("x1", 0),
                            command.get("y1", 0),
                            command.get("x2", 10),
                            command.get("y2", 10),
                            filled=command.get("filled", False),
                        )

                    elif cmd_type == "line":
                        vfd_controller.draw_line(
                            command.get("x1", 0),
                            command.get("y1", 0),
                            command.get("x2", 10),
                            command.get("y2", 10),
                        )
            elif screen.display_type == "oled":
                import app_core.oled as oled_module
                from app_core.oled import OLEDLine, initialise_oled_display

                controller = oled_module.oled_controller or initialise_oled_display(route_logger)
                if controller is None:
                    return jsonify({"error": "OLED controller not available"}), 503

                raw_lines = rendered.get("lines", [])
                if not isinstance(raw_lines, list):
                    return jsonify({"error": "Invalid OLED payload"}), 500

                line_objects: List[OLEDLine] = []
                for entry in raw_lines:
                    if isinstance(entry, OLEDLine):
                        line_objects.append(entry)
                        continue

                    if not isinstance(entry, dict):
                        continue

                    text = str(entry.get("text", ""))

                    try:
                        x_value = int(entry.get("x", 0) or 0)
                    except (TypeError, ValueError):
                        x_value = 0

                    y_raw = entry.get("y")
                    try:
                        y_value = int(y_raw) if y_raw is not None else None
                    except (TypeError, ValueError):
                        y_value = None

                    max_width_raw = entry.get("max_width")
                    try:
                        max_width_value = int(max_width_raw) if max_width_raw is not None else None
                    except (TypeError, ValueError):
                        max_width_value = None

                    try:
                        spacing_value = int(entry.get("spacing", 2))
                    except (TypeError, ValueError):
                        spacing_value = 2

                    line_objects.append(
                        OLEDLine(
                            text=text,
                            x=x_value,
                            y=y_value,
                            font=str(entry.get("font", "small")),
                            wrap=bool(entry.get("wrap", True)),
                            max_width=max_width_value,
                            spacing=spacing_value,
                            invert=entry.get("invert"),
                            allow_empty=bool(entry.get("allow_empty", False)),
                        )
                    )

                controller.display_lines(
                    line_objects,
                    clear=rendered.get("clear", True),
                    invert=rendered.get("invert"),
                )

            # Update statistics
            screen.display_count += 1
            screen.last_displayed_at = utc_now()
            db.session.commit()

            route_logger.info(f"Displayed screen: {screen.name} (ID: {screen.id})")

            return jsonify({
                "message": "Screen displayed successfully",
                "screen": screen.to_dict(),
            })

        except Exception as e:
            route_logger.error(f"Error displaying screen {screen_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ============================================================
    # Screen Rotation Management
    # ============================================================

    @app.route("/api/rotations", methods=["GET"])
    def get_rotations():
        """Get all screen rotations."""
        try:
            display_type = request.args.get("display_type")
            enabled_only = request.args.get("enabled", "false").lower() == "true"

            query = ScreenRotation.query

            if display_type:
                query = query.filter_by(display_type=display_type)

            if enabled_only:
                query = query.filter_by(enabled=True)

            rotations = query.order_by(ScreenRotation.name).all()

            return jsonify({
                "rotations": [rotation.to_dict() for rotation in rotations]
            })

        except Exception as e:
            route_logger.error(f"Error fetching rotations: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/rotations/<int:rotation_id>", methods=["GET"])
    def get_rotation(rotation_id: int):
        """Get a specific screen rotation."""
        try:
            rotation = ScreenRotation.query.get(rotation_id)

            if not rotation:
                return jsonify({"error": "Rotation not found"}), 404

            return jsonify(rotation.to_dict())

        except Exception as e:
            route_logger.error(f"Error fetching rotation {rotation_id}: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/rotations", methods=["POST"])
    def create_rotation():
        """Create a new screen rotation."""
        try:
            data = request.get_json()

            if not data:
                return jsonify({"error": "No data provided"}), 400

            # Validate required fields
            required_fields = ["name", "display_type", "screens"]
            for field in required_fields:
                if field not in data:
                    return jsonify({"error": f"Missing required field: {field}"}), 400

            # Validate display_type
            if data["display_type"] not in ["led", "vfd", "oled"]:
                return jsonify({"error": "display_type must be 'led', 'vfd', or 'oled'"}), 400

            # Create rotation
            rotation = ScreenRotation(
                name=data["name"],
                description=data.get("description"),
                display_type=data["display_type"],
                enabled=data.get("enabled", True),
                screens=data["screens"],
                randomize=data.get("randomize", False),
                skip_on_alert=data.get("skip_on_alert", True),
            )

            db.session.add(rotation)
            db.session.commit()

            route_logger.info(f"Created rotation: {rotation.name} (ID: {rotation.id})")

            return jsonify(rotation.to_dict()), 201

        except IntegrityError as e:
            db.session.rollback()
            route_logger.error(f"Integrity error creating rotation: {e}")
            return jsonify({"error": "Rotation with this name already exists"}), 409

        except Exception as e:
            db.session.rollback()
            route_logger.error(f"Error creating rotation: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/rotations/<int:rotation_id>", methods=["PUT"])
    def update_rotation(rotation_id: int):
        """Update a screen rotation."""
        try:
            rotation = ScreenRotation.query.get(rotation_id)

            if not rotation:
                return jsonify({"error": "Rotation not found"}), 404

            data = request.get_json()

            if not data:
                return jsonify({"error": "No data provided"}), 400

            # Update fields
            if "name" in data:
                rotation.name = data["name"]
            if "description" in data:
                rotation.description = data["description"]
            if "display_type" in data:
                if data["display_type"] not in ["led", "vfd", "oled"]:
                    return jsonify({"error": "display_type must be 'led', 'vfd', or 'oled'"}), 400
                rotation.display_type = data["display_type"]
            if "enabled" in data:
                rotation.enabled = data["enabled"]
            if "screens" in data:
                rotation.screens = data["screens"]
            if "randomize" in data:
                rotation.randomize = data["randomize"]
            if "skip_on_alert" in data:
                rotation.skip_on_alert = data["skip_on_alert"]

            rotation.updated_at = utc_now()
            db.session.commit()

            route_logger.info(f"Updated rotation: {rotation.name} (ID: {rotation.id})")

            return jsonify(rotation.to_dict())

        except IntegrityError as e:
            db.session.rollback()
            route_logger.error(f"Integrity error updating rotation: {e}")
            return jsonify({"error": "Rotation with this name already exists"}), 409

        except Exception as e:
            db.session.rollback()
            route_logger.error(f"Error updating rotation {rotation_id}: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/rotations/<int:rotation_id>", methods=["DELETE"])
    def delete_rotation(rotation_id: int):
        """Delete a screen rotation."""
        try:
            rotation = ScreenRotation.query.get(rotation_id)

            if not rotation:
                return jsonify({"error": "Rotation not found"}), 404

            rotation_name = rotation.name
            db.session.delete(rotation)
            db.session.commit()

            route_logger.info(f"Deleted rotation: {rotation_name} (ID: {rotation_id})")

            return jsonify({"message": "Rotation deleted successfully"})

        except Exception as e:
            db.session.rollback()
            route_logger.error(f"Error deleting rotation {rotation_id}: {e}")
            return jsonify({"error": str(e)}), 500

    # ============================================================
    # Web UI
    # ============================================================

    @app.route("/screens")
    def screens_page():
        """Custom screens management page."""
        try:
            return render_template("screens.html")
        except Exception as e:
            route_logger.error(f"Error loading screens page: {e}")
            return (
                "<h1>Screens Management Error</h1>"
                f"<p>{e}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/screens/new")
    def new_screen_editor():
        """Visual screen editor for creating new screens."""
        try:
            return render_template("screen_editor.html", screen=None)
        except Exception as e:
            route_logger.error(f"Error loading screen editor: {e}")
            return (
                "<h1>Screen Editor Error</h1>"
                f"<p>{e}</p><p><a href='/screens'>← Back to Screens</a></p>"
            )

    @app.route("/screens/editor/<int:screen_id>")
    def edit_screen_editor(screen_id: int):
        """Visual screen editor for editing existing screens."""
        try:
            screen = DisplayScreen.query.get(screen_id)

            if not screen:
                return (
                    "<h1>Screen Not Found</h1>"
                    f"<p>Screen ID {screen_id} not found</p>"
                    "<p><a href='/screens'>← Back to Screens</a></p>"
                ), 404

            return render_template("screen_editor.html", screen=screen)
        except Exception as e:
            route_logger.error(f"Error loading screen editor for {screen_id}: {e}")
            return (
                "<h1>Screen Editor Error</h1>"
                f"<p>{e}</p><p><a href='/screens'>← Back to Screens</a></p>"
            )

    @app.route("/displays/preview")
    def displays_preview_page():
        """Live preview of all display outputs."""
        try:
            return render_template("displays_preview.html")
        except Exception as e:
            route_logger.error(f"Error loading displays preview page: {e}")
            return (
                "<h1>Display Preview Error</h1>"
                f"<p>{e}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/api/displays/current-state")
    def get_displays_current_state():
        """Get the current state of all displays.

        In multi-container architecture, display state is published by the hardware-service
        container to Redis. This endpoint reads from Redis instead of accessing hardware directly.
        """
        try:
            # Try to get display state from Redis (published by hardware-service)
            try:
                from app_core.redis_client import get_redis_client
                redis_client = get_redis_client()

                # Get display state from Redis
                display_state_json = redis_client.get("hardware:display_state")

                if display_state_json:
                    # Parse and return the state from hardware-service
                    state = json.loads(display_state_json)
                    route_logger.debug("Display state retrieved from Redis (hardware-service)")
                    return jsonify(state)
                else:
                    route_logger.warning("No display state in Redis - hardware-service may not be running")

            except Exception as e:
                route_logger.warning(f"Failed to get display state from Redis: {e}")

            # Fallback: Try to get state directly (for single-container deployments)
            route_logger.debug("Falling back to direct hardware access")
            from scripts.screen_manager import screen_manager

            state = {
                "oled": {
                    "enabled": False,
                    "width": 128,
                    "height": 64,
                    "current_screen": None,
                    "scroll_offset": 0,
                    "alert_active": False,
                },
                "vfd": {
                    "enabled": False,
                    "width": 140,
                    "height": 32,
                    "current_screen": None,
                },
                "led": {
                    "enabled": False,
                    "lines": 4,
                    "chars_per_line": 20,
                    "current_message": None,
                    "color": "AMBER",
                },
            }

            # Get OLED state
            if screen_manager:
                try:
                    import app_core.oled as oled_module
                    # Check if controller exists and mark as enabled immediately
                    if oled_module.oled_controller:
                        state["oled"]["enabled"] = True

                        # Get basic controller info
                        try:
                            state["oled"]["width"] = oled_module.oled_controller.width
                            state["oled"]["height"] = oled_module.oled_controller.height
                        except Exception as e:
                            route_logger.warning(f"Error getting OLED dimensions: {e}")

                        # Get current screen name if available
                        try:
                            if hasattr(screen_manager, '_current_oled_screen'):
                                current_screen = screen_manager._current_oled_screen
                                if current_screen:
                                    state["oled"]["current_screen"] = current_screen.name if hasattr(current_screen, 'name') else str(current_screen)
                        except Exception as e:
                            route_logger.warning(f"Error getting OLED current screen: {e}")

                        # Get current alert state if scrolling
                        try:
                            if hasattr(screen_manager, '_oled_scroll_effect') and screen_manager._oled_scroll_effect:
                                state["oled"]["alert_active"] = True
                                state["oled"]["scroll_offset"] = screen_manager._oled_scroll_offset
                                state["oled"]["alert_text"] = screen_manager._current_alert_text or ""
                                state["oled"]["scroll_speed"] = screen_manager._oled_scroll_speed

                                # Get cached header
                                if hasattr(screen_manager, '_cached_header_text'):
                                    state["oled"]["header_text"] = screen_manager._cached_header_text
                        except Exception as e:
                            route_logger.warning(f"Error getting OLED alert state: {e}")

                        # Get preview image - don't let this failure affect enabled status
                        try:
                            preview_image = oled_module.oled_controller.get_preview_image_base64()
                            if preview_image:
                                state["oled"]["preview_image"] = preview_image
                        except Exception as e:
                            route_logger.warning(f"Error getting OLED preview image: {e}")

                except Exception as e:
                    route_logger.warning(f"Error checking OLED controller: {e}")

                # Get VFD state
                try:
                    from app_core.vfd import vfd_controller
                    if vfd_controller:
                        state["vfd"]["enabled"] = True
                except Exception as e:
                    route_logger.debug(f"Error getting VFD state: {e}")

                # Get LED state
                try:
                    import app_core.led as led_module
                    if led_module.led_controller:
                        state["led"]["enabled"] = True
                except Exception as e:
                    route_logger.debug(f"Error getting LED state: {e}")

            return jsonify(state)

        except Exception as e:
            route_logger.error(f"Error getting display states: {e}")
            return jsonify({"error": str(e)}), 500
