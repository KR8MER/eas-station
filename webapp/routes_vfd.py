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

"""VFD display routes for Noritake GU140x32F-7000B graphics control."""

from __future__ import annotations

import base64
import io
import os
from typing import Any, Dict

from flask import Flask, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import OperationalError
from PIL import Image

from app_core.extensions import db
from app_core.vfd import (
    VFD_AVAILABLE,
    VFD_BAUDRATE,
    VFD_PORT,
    VFDBrightness,
    ensure_vfd_tables,
    vfd_controller,
)
from app_core.models import VFDDisplay, VFDStatus
from app_utils import utc_now


def register(app: Flask, logger) -> None:
    """Register VFD dashboard and API endpoints."""

    route_logger = logger.getChild("routes_vfd")

    @app.route("/vfd")
    def vfd_redirect():
        return redirect(url_for("vfd_control"))

    @app.route("/vfd_control")
    def vfd_control():
        """VFD control dashboard."""
        try:
            ensure_vfd_tables()

            vfd_status = vfd_controller.get_status() if vfd_controller else None

            try:
                recent_displays = (
                    VFDDisplay.query.order_by(VFDDisplay.created_at.desc()).limit(10).all()
                )
            except OperationalError as db_error:
                if "vfd_displays" in str(getattr(db_error, "orig", "")):
                    route_logger.warning("VFD displays table missing; creating tables now")
                    db.create_all()
                    recent_displays = (
                        VFDDisplay.query.order_by(VFDDisplay.created_at.desc()).limit(10).all()
                    )
                else:
                    raise

            # Get current status from database
            try:
                db_status = VFDStatus.query.first()
            except OperationalError:
                db_status = None

            return render_template(
                "vfd_control.html",
                vfd_status=vfd_status,
                db_status=db_status,
                recent_displays=recent_displays,
                vfd_available=VFD_AVAILABLE,
                brightness_levels=list(VFDBrightness),
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Error loading VFD control page: %s", exc)
            return (
                "<h1>VFD Control Error</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/api/vfd/status", methods=["GET"])
    def api_vfd_status():
        """Get VFD display status."""
        try:
            if not vfd_controller:
                return jsonify({
                    "success": False,
                    "error": "VFD controller not available",
                    "available": False
                })

            status = vfd_controller.get_status()
            return jsonify({
                "success": True,
                "status": status,
                "available": VFD_AVAILABLE
            })

        except Exception as exc:
            route_logger.error("Error getting VFD status: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/clear", methods=["POST"])
    def api_vfd_clear():
        """Clear the VFD display."""
        try:
            ensure_vfd_tables()

            if not vfd_controller:
                return jsonify({"success": False, "error": "VFD controller not available"})

            vfd_controller.clear_screen()

            # Update database status
            db_status = VFDStatus.query.first()
            if db_status:
                db_status.current_content_type = None
                db_status.last_update = utc_now()
                db.session.commit()

            return jsonify({"success": True, "message": "VFD display cleared"})

        except Exception as exc:
            route_logger.error("Error clearing VFD: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/brightness", methods=["POST"])
    def api_vfd_brightness():
        """Set VFD brightness level."""
        try:
            ensure_vfd_tables()

            payload = request.get_json(silent=True) or {}
            level = payload.get("level")

            if level is None:
                return jsonify({"success": False, "error": "Brightness level required"})

            if not vfd_controller:
                return jsonify({"success": False, "error": "VFD controller not available"})

            # Convert to brightness enum
            try:
                brightness = VFDBrightness(int(level))
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": f"Invalid brightness level. Must be 0-7"
                })

            vfd_controller.set_brightness(brightness)

            # Update database
            db_status = VFDStatus.query.first()
            if not db_status:
                db_status = VFDStatus(port=VFD_PORT, baudrate=VFD_BAUDRATE)
                db.session.add(db_status)

            db_status.brightness_level = level
            db_status.last_update = utc_now()
            db.session.commit()

            return jsonify({
                "success": True,
                "message": f"Brightness set to level {level}"
            })

        except Exception as exc:
            route_logger.error("Error setting VFD brightness: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/text", methods=["POST"])
    def api_vfd_text():
        """Display text on VFD."""
        try:
            ensure_vfd_tables()

            payload = request.get_json(silent=True) or {}
            text = payload.get("text")
            x = int(payload.get("x", 0))
            y = int(payload.get("y", 0))

            if not text:
                return jsonify({"success": False, "error": "Text required"})

            if not vfd_controller:
                return jsonify({"success": False, "error": "VFD controller not available"})

            vfd_controller.draw_text(x, y, text)

            # Save to database
            display = VFDDisplay(
                content_type="text",
                content_data=text,
                x_position=x,
                y_position=y,
                displayed_at=utc_now()
            )
            db.session.add(display)

            # Update status
            db_status = VFDStatus.query.first()
            if db_status:
                db_status.current_content_type = "text"
                db_status.last_update = utc_now()

            db.session.commit()

            return jsonify({
                "success": True,
                "message": f"Text displayed at ({x}, {y})"
            })

        except Exception as exc:
            route_logger.error("Error displaying text on VFD: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/image", methods=["POST"])
    def api_vfd_image():
        """Display an image on VFD from uploaded file or base64 data."""
        try:
            ensure_vfd_tables()

            if not vfd_controller:
                return jsonify({"success": False, "error": "VFD controller not available"})

            x = int(request.form.get("x", 0))
            y = int(request.form.get("y", 0))

            # Check for file upload
            if "image" in request.files:
                file = request.files["image"]
                if file.filename == "":
                    return jsonify({"success": False, "error": "No file selected"})

                # Validate file extension
                ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico'}
                file_ext = os.path.splitext(file.filename)[1].lower()
                if file_ext not in ALLOWED_EXTENSIONS:
                    return jsonify({
                        "success": False,
                        "error": f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
                    }), 400

                # Validate file size (max 5MB)
                MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)

                if file_size > MAX_FILE_SIZE:
                    return jsonify({
                        "success": False,
                        "error": f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
                    }), 400

                image_data = file.read()

                # Validate that it's actually a valid image
                try:
                    img = Image.open(io.BytesIO(image_data))
                    img.verify()  # Verify it's a valid image
                    # Reset file pointer as verify() consumes the data
                    file.seek(0)
                    image_data = file.read()
                except Exception as img_error:
                    return jsonify({
                        "success": False,
                        "error": f"Invalid or corrupted image file: {str(img_error)}"
                    }), 400

            # Check for base64 data
            elif request.is_json:
                payload = request.get_json()
                base64_data = payload.get("image_data")
                if not base64_data:
                    return jsonify({"success": False, "error": "No image data provided"})

                # Decode base64
                try:
                    image_data = base64.b64decode(base64_data)
                except Exception as decode_error:
                    return jsonify({
                        "success": False,
                        "error": f"Invalid base64 data: {decode_error}"
                    })

                # Validate size (max 5MB)
                MAX_FILE_SIZE = 5 * 1024 * 1024
                if len(image_data) > MAX_FILE_SIZE:
                    return jsonify({
                        "success": False,
                        "error": f"Image data too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
                    }), 400

                # Validate that it's actually a valid image
                try:
                    img = Image.open(io.BytesIO(image_data))
                    img.verify()  # Verify it's a valid image
                except Exception as img_error:
                    return jsonify({
                        "success": False,
                        "error": f"Invalid or corrupted image data: {str(img_error)}"
                    }), 400

                x = int(payload.get("x", 0))
                y = int(payload.get("y", 0))

            else:
                return jsonify({
                    "success": False,
                    "error": "No image data provided (use file upload or base64)"
                })

            # Display image
            vfd_controller.display_image_from_bytes(image_data, x, y)

            # Save to database
            display = VFDDisplay(
                content_type="image",
                binary_data=image_data,
                x_position=x,
                y_position=y,
                displayed_at=utc_now()
            )
            db.session.add(display)

            # Update status
            db_status = VFDStatus.query.first()
            if db_status:
                db_status.current_content_type = "image"
                db_status.last_update = utc_now()

            db.session.commit()

            return jsonify({
                "success": True,
                "message": f"Image displayed at ({x}, {y})"
            })

        except Exception as exc:
            route_logger.error("Error displaying image on VFD: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/graphics/pixel", methods=["POST"])
    def api_vfd_pixel():
        """Draw a pixel on VFD."""
        try:
            if not vfd_controller:
                return jsonify({"success": False, "error": "VFD controller not available"})

            payload = request.get_json(silent=True) or {}
            x = payload.get("x")
            y = payload.get("y")
            state = payload.get("state", True)

            if x is None or y is None:
                return jsonify({"success": False, "error": "x and y coordinates required"})

            vfd_controller.draw_pixel(int(x), int(y), bool(state))

            return jsonify({"success": True, "message": f"Pixel drawn at ({x}, {y})"})

        except Exception as exc:
            route_logger.error("Error drawing pixel on VFD: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/graphics/line", methods=["POST"])
    def api_vfd_line():
        """Draw a line on VFD."""
        try:
            if not vfd_controller:
                return jsonify({"success": False, "error": "VFD controller not available"})

            payload = request.get_json(silent=True) or {}
            x1 = payload.get("x1")
            y1 = payload.get("y1")
            x2 = payload.get("x2")
            y2 = payload.get("y2")

            if any(v is None for v in [x1, y1, x2, y2]):
                return jsonify({
                    "success": False,
                    "error": "x1, y1, x2, y2 coordinates required"
                })

            vfd_controller.draw_line(int(x1), int(y1), int(x2), int(y2))

            return jsonify({
                "success": True,
                "message": f"Line drawn from ({x1}, {y1}) to ({x2}, {y2})"
            })

        except Exception as exc:
            route_logger.error("Error drawing line on VFD: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/graphics/rectangle", methods=["POST"])
    def api_vfd_rectangle():
        """Draw a rectangle on VFD."""
        try:
            if not vfd_controller:
                return jsonify({"success": False, "error": "VFD controller not available"})

            payload = request.get_json(silent=True) or {}
            x1 = payload.get("x1")
            y1 = payload.get("y1")
            x2 = payload.get("x2")
            y2 = payload.get("y2")
            filled = payload.get("filled", False)

            if any(v is None for v in [x1, y1, x2, y2]):
                return jsonify({
                    "success": False,
                    "error": "x1, y1, x2, y2 coordinates required"
                })

            vfd_controller.draw_rectangle(
                int(x1), int(y1), int(x2), int(y2), bool(filled)
            )

            return jsonify({
                "success": True,
                "message": f"Rectangle drawn at ({x1}, {y1}) to ({x2}, {y2})"
            })

        except Exception as exc:
            route_logger.error("Error drawing rectangle on VFD: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/graphics/progress", methods=["POST"])
    def api_vfd_progress():
        """Draw a progress bar on VFD."""
        try:
            if not vfd_controller:
                return jsonify({"success": False, "error": "VFD controller not available"})

            payload = request.get_json(silent=True) or {}
            x = int(payload.get("x", 0))
            y = int(payload.get("y", 0))
            width = int(payload.get("width", 100))
            height = int(payload.get("height", 8))
            progress = float(payload.get("progress", 0.0))

            vfd_controller.draw_progress_bar(x, y, width, height, progress)

            return jsonify({
                "success": True,
                "message": f"Progress bar drawn at ({x}, {y}): {progress * 100:.0f}%"
            })

        except Exception as exc:
            route_logger.error("Error drawing progress bar on VFD: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/vfd/displays", methods=["GET"])
    def api_vfd_displays():
        """Get recent VFD display history."""
        try:
            ensure_vfd_tables()

            displays = (
                VFDDisplay.query
                .order_by(VFDDisplay.created_at.desc())
                .limit(50)
                .all()
            )

            result = []
            for display in displays:
                result.append({
                    "id": display.id,
                    "content_type": display.content_type,
                    "content_data": display.content_data,
                    "x_position": display.x_position,
                    "y_position": display.y_position,
                    "priority": display.priority,
                    "displayed_at": display.displayed_at.isoformat() if display.displayed_at else None,
                    "created_at": display.created_at.isoformat() if display.created_at else None,
                })

            return jsonify({"success": True, "displays": result})

        except Exception as exc:
            route_logger.error("Error getting VFD displays: %s", exc)
            return jsonify({"success": False, "error": str(exc)})


def _enum_label(value) -> str:
    """Extract enum label for display."""
    if value is None:
        return ""
    if hasattr(value, "name"):
        return value.name
    return str(value)
