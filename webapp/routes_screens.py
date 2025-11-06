"""Custom screen management routes for LED and VFD displays."""

from __future__ import annotations

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
            if data["display_type"] not in ["led", "vfd"]:
                return jsonify({"error": "display_type must be 'led' or 'vfd'"}), 400

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
                if data["display_type"] not in ["led", "vfd"]:
                    return jsonify({"error": "display_type must be 'led' or 'vfd'"}), 400
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
            renderer = ScreenRenderer()
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
            renderer = ScreenRenderer()
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
            if data["display_type"] not in ["led", "vfd"]:
                return jsonify({"error": "display_type must be 'led' or 'vfd'"}), 400

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
                if data["display_type"] not in ["led", "vfd"]:
                    return jsonify({"error": "display_type must be 'led' or 'vfd'"}), 400
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
