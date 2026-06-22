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

"""Custom screen management routes for LED and VFD displays."""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError

from app_core.auth.decorators import require_auth, require_role
from app_core.config import DISPLAYS_SERVICE_URL
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
    def display_screen_now(screen_id: int):
        """Display a screen immediately by proxying to eas-station-displays.service.

        All physical display access (OLED/LED/VFD) is delegated to the
        displays subsystem (port 5104, Phase 4 of the hardware_service.py
        split).  The web worker must never open I2C/GPIO/serial device
        nodes directly: blocking ioctl() calls stall the gevent event loop
        and can deadlock with the displays service's own I2C session.
        """
        try:
            screen = DisplayScreen.query.get(screen_id)

            if not screen:
                return jsonify({"error": "Screen not found"}), 404

            # Proxy the push request to the displays subsystem service.
            hw_url = f"{DISPLAYS_SERVICE_URL}/api/hardware/display/push"
            payload = json.dumps({"screen_id": screen_id}).encode()
            hw_req = urllib.request.Request(
                hw_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(hw_req, timeout=15) as hw_resp:
                    hw_body = hw_resp.read()
                hw_data = json.loads(hw_body)
                if not hw_data.get("success"):
                    err = hw_data.get("error", "Unknown error from hardware service")
                    route_logger.error("Hardware service push failed: %s", err)
                    return jsonify({"error": err}), 503
            except urllib.error.HTTPError as exc:
                try:
                    err_body = json.loads(exc.read()).get("error", str(exc))
                except Exception:
                    err_body = str(exc)
                route_logger.error("Hardware service returned %s: %s", exc.code, err_body)
                return jsonify({"error": f"Hardware service error: {err_body}"}), exc.code
            except (urllib.error.URLError, OSError) as exc:
                route_logger.warning(
                    "Hardware service unavailable at %s: %s", hw_url, exc)
                return jsonify({
                    "error": (
                        "Displays service (eas-station-displays.service) is not reachable. "
                        "Ensure it is running: sudo systemctl start eas-station-displays.service"
                    )
                }), 503

            route_logger.info("Displayed screen via hardware service: %s (ID: %s)",
                              screen.name, screen.id)

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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
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
    @require_auth
    @require_role("Admin", "Operator")
    def get_displays_current_state():
        """Get the current state of all displays.

        Display state is published to Redis by eas-station-displays.service.
        The web worker reads from Redis only — it must never open I2C/GPIO/serial
        device nodes directly (see display_screen_now() for the reasoning).
        """
        try:
            # Read display state from Redis (published by the displays subsystem).
            try:
                from app_core.redis_client import get_redis_client
                redis_client = get_redis_client()
                display_state_json = redis_client.get("hardware:display_state")
                if display_state_json:
                    state = json.loads(display_state_json)
                    route_logger.debug("Display state retrieved from Redis (displays subsystem)")
                    return jsonify(state)
                else:
                    route_logger.warning(
                        "No display state in Redis — eas-station-displays.service may not be running"
                    )
            except Exception as e:
                route_logger.warning("Failed to get display state from Redis: %s", e)

            # Hardware service is unavailable: return an empty-but-valid state so
            # the UI degrades gracefully instead of showing a JS error.
            return jsonify({
                "oled": {"enabled": False, "width": 128, "height": 64,
                         "current_screen": None, "scroll_offset": 0, "alert_active": False},
                "vfd":  {"enabled": False, "width": 140, "height": 32, "current_screen": None},
                "led":  {"enabled": False, "lines": 4, "chars_per_line": 20,
                         "current_message": None, "color": "AMBER"},
                "hardware_service_available": False,
            })

        except Exception as e:
            route_logger.error("Error getting display states: %s", e)
            return jsonify({"error": str(e)}), 500
