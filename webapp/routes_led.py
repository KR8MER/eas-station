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

"""LED sign routes extracted from the application entrypoint."""

import os
from typing import Any, Dict, List

from flask import Flask, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import OperationalError

from app_core.extensions import db
import app_core.led as led_module
from app_core.led import (
    Color,
    DisplayMode,
    Font,
    FontSize,
    MessagePriority,
    SpecialFunction,
    Speed,
    ensure_led_tables,
)
from app_core.models import LEDMessage, LEDSignStatus
from app_utils import utc_now


def register(app: Flask, logger) -> None:
    """Register LED dashboard and API endpoints."""

    route_logger = logger.getChild("routes_led")

    def _led_enums_available() -> bool:
        return all(enum is not None for enum in (Color, Font, DisplayMode, Speed))

    @app.route("/led")
    def led_redirect():
        return redirect(url_for("led_control"))

    @app.route("/led_control")
    def led_control():
        try:
            ensure_led_tables()

            # Get LED status from controller if available
            led_status = led_module.led_controller.get_status() if led_module.led_controller else None

            # If controller isn't available, create status from environment
            if not led_status:
                from app_core.led import LED_SIGN_IP, LED_SIGN_PORT
                led_status = {
                    'connected': False,
                    'host': LED_SIGN_IP,
                    'port': LED_SIGN_PORT,
                    'model': 'Alpha 9120C',
                    'protocol': 'M-Protocol',
                }

            try:
                recent_messages = (
                    LEDMessage.query.order_by(LEDMessage.created_at.desc()).limit(10).all()
                )
            except OperationalError as db_error:
                if "led_messages" in str(getattr(db_error, "orig", "")):
                    route_logger.warning("LED messages table missing; creating tables now")
                    db.create_all()
                    recent_messages = (
                        LEDMessage.query.order_by(LEDMessage.created_at.desc()).limit(10).all()
                    )
                else:
                    raise

            canned_messages: List[Dict[str, Any]] = []
            if led_module.led_controller:
                for name, config in led_module.led_controller.canned_messages.items():
                    lines = config.get("lines") or config.get("text") or []
                    if isinstance(lines, str):
                        lines = [lines]

                    canned_messages.append(
                        {
                            "name": name,
                            "lines": lines,
                            "color": _enum_label(config.get("color")),
                            "font": _enum_label(config.get("font")),
                            "mode": _enum_label(config.get("mode")),
                            "speed": _enum_label(
                                config.get("speed", Speed.SPEED_3)
                            ),
                            "hold_time": config.get("hold_time", 5),
                            "priority": _enum_label(
                                config.get("priority", MessagePriority.NORMAL)
                            ),
                        }
                    )
            else:
                canned_messages = []

            return render_template(
                "led_control.html",
                led_status=led_status,
                recent_messages=recent_messages,
                canned_messages=canned_messages,
                led_available=led_module.LED_AVAILABLE,
            )
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Error loading LED control page: %s", exc)
            return (
                "<h1>LED Control Error</h1>"
                f"<p>{exc}</p><p><a href='/'>← Back to Main</a></p>"
            )

    @app.route("/api/led/send_message", methods=["POST"])
    def api_led_send_message():
        try:
            ensure_led_tables()

            payload = request.get_json(silent=True) or {}

            if not led_module.led_controller:
                return jsonify({"success": False, "error": "LED controller not available"})

            if not _led_enums_available():
                return jsonify({"success": False, "error": "LED library enums unavailable"})

            # Validate enums are not None
            if not all([Color, Font, DisplayMode, Speed, MessagePriority]):
                return jsonify({"success": False, "error": "LED enums not properly initialized"})

            raw_lines = payload.get("lines")
            if raw_lines is None:
                return jsonify({"success": False, "error": "At least one line of text is required"})

            if isinstance(raw_lines, str):
                raw_lines = raw_lines.splitlines()

            if not isinstance(raw_lines, list):
                return jsonify({"success": False, "error": "Lines must be provided as a list"})

            sanitised_lines: List[Any] = []
            flattened_lines: List[str] = []

            for entry in raw_lines:
                if isinstance(entry, dict):
                    cleaned_line: Dict[str, Any] = {}
                    for key in ("display_position", "font", "color", "rgb_color", "mode", "speed"):
                        value = entry.get(key) if entry else None
                        if value not in (None, "", []):
                            cleaned_line[key] = value

                    specials = entry.get("special_functions") if entry else None
                    if specials:
                        cleaned_line["special_functions"] = specials

                    segments_payload = []
                    raw_segments = entry.get("segments") if entry else None
                    if isinstance(raw_segments, list) and raw_segments:
                        for raw_segment in raw_segments:
                            if isinstance(raw_segment, dict):
                                segment_text = str(raw_segment.get("text", ""))
                                cleaned_segment: Dict[str, Any] = {"text": segment_text}
                                for seg_key in ("font", "color", "rgb_color", "mode", "speed"):
                                    seg_value = raw_segment.get(seg_key) if raw_segment else None
                                    if seg_value not in (None, "", []):
                                        cleaned_segment[seg_key] = seg_value
                                seg_specials = raw_segment.get("special_functions") if raw_segment else None
                                if seg_specials:
                                    cleaned_segment["special_functions"] = seg_specials
                            else:
                                cleaned_segment = {"text": str(raw_segment or "")}
                            segments_payload.append(cleaned_segment)

                    if segments_payload:
                        cleaned_line["segments"] = segments_payload

                    line_text = entry.get("text") if entry else None
                    if isinstance(line_text, str):
                        cleaned_line["text"] = line_text
                        flattened_lines.append(line_text)
                    elif segments_payload:
                        flattened_lines.append(" ".join(seg.get("text", "") if seg else "" for seg in segments_payload))
                    sanitised_lines.append(cleaned_line)
                else:
                    line_text = str(entry or "")
                    sanitised_lines.append(line_text)
                    flattened_lines.append(line_text)

            color_name = str(payload.get("color") or "RED").upper()
            font_name = str(payload.get("font") or "DEFAULT").upper()
            mode_name = str(payload.get("mode") or "HOLD").upper()
            speed_name = str(payload.get("speed") or "SPEED_3").upper()

            # Safe enum lookups with better error handling
            try:
                color = Color[color_name] if Color else None
                if not color:
                    return jsonify({"success": False, "error": "Color enum not available"})
            except (KeyError, TypeError):
                return jsonify({"success": False, "error": f"Unknown color {color_name}"})

            try:
                font = Font[font_name] if Font else None
                if not font and FontSize:
                    try:
                        font = FontSize[font_name]
                    except (KeyError, TypeError):
                        pass
                if not font:
                    return jsonify({"success": False, "error": f"Unknown font {font_name}"})
            except (KeyError, TypeError):
                return jsonify({"success": False, "error": f"Unknown font {font_name}"})

            try:
                mode = DisplayMode[mode_name] if DisplayMode else None
                if not mode:
                    return jsonify({"success": False, "error": "DisplayMode enum not available"})
            except (KeyError, TypeError):
                return jsonify({"success": False, "error": f"Unknown mode {mode_name}"})

            try:
                speed = Speed[speed_name] if Speed else None
                if not speed:
                    return jsonify({"success": False, "error": "Speed enum not available"})
            except (KeyError, TypeError):
                return jsonify({"success": False, "error": f"Unknown speed {speed_name}"})

            # Handle priority as either int or string
            priority_value = payload.get("priority")
            priority = None
            if isinstance(priority_value, int):
                try:
                    priority = MessagePriority(priority_value) if MessagePriority else None
                except (ValueError, KeyError, TypeError):
                    pass
            else:
                priority_name = str(priority_value or "NORMAL").upper()
                try:
                    priority = MessagePriority[priority_name] if MessagePriority else None
                except (KeyError, TypeError):
                    pass

            if not priority:
                priority = MessagePriority.NORMAL if MessagePriority else None
                if not priority:
                    return jsonify({"success": False, "error": "MessagePriority enum not available"})

            hold_time = int(payload.get("hold_time", 5))
            special_functions_raw = payload.get("special_functions")
            special_functions = []
            if special_functions_raw and SpecialFunction:
                for func_name in special_functions_raw:
                    try:
                        special_functions.append(SpecialFunction[str(func_name).upper()])
                    except (KeyError, TypeError, AttributeError):
                        route_logger.warning("Ignoring unknown special function: %s", func_name)

            def _gather_values(field_name: str) -> set:
                values = set()
                for line in sanitised_lines:
                    if isinstance(line, dict) and line:
                        value = line.get(field_name)
                        if value:
                            values.add(str(value).upper())
                        segments = line.get("segments", [])
                        if segments:
                            for segment in segments:
                                if segment:
                                    seg_value = segment.get(field_name) if isinstance(segment, dict) else None
                                    if seg_value:
                                        values.add(str(seg_value).upper())
                return values

            color_values = _gather_values("color")
            rgb_values = _gather_values("rgb_color")
            mode_values = _gather_values("mode")
            speed_values = _gather_values("speed")

            if color_values and rgb_values:
                color_summary = "MIXED"
            elif color_values:
                color_summary = next(iter(color_values)) if len(color_values) == 1 else "MIXED"
            elif rgb_values:
                color_summary = (
                    f"RGB-{next(iter(rgb_values))}"
                    if len(rgb_values) == 1
                    else "RGB-MULTI"
                )
            else:
                color_summary = color.name if color and hasattr(color, 'name') else "RED"

            mode_summary = next(iter(mode_values)) if len(mode_values) == 1 else (
                "MIXED" if mode_values else (mode.name if mode and hasattr(mode, 'name') else "HOLD")
            )
            speed_summary = next(iter(speed_values)) if len(speed_values) == 1 else (
                "MIXED" if speed_values else (speed.name if speed and hasattr(speed, 'name') else "SPEED_3")
            )

            led_message = LEDMessage(
                message_type="custom",
                content="\n".join(flattened_lines),
                priority=priority.value if priority and hasattr(priority, 'value') else 2,
                color=color_summary,
                font_size=font.name if font and hasattr(font, 'name') else "DEFAULT",
                effect=mode_summary,
                speed=speed_summary,
                display_time=hold_time,
                scheduled_time=utc_now(),
            )
            db.session.add(led_message)
            db.session.commit()

            result = led_module.led_controller.send_message(
                lines=sanitised_lines,
                color=color,
                font=font,
                mode=mode,
                speed=speed,
                hold_time=hold_time,
                special_functions=special_functions or None,
                priority=priority,
            )

            if result:
                led_message.sent_at = utc_now()
                db.session.commit()

            return jsonify(
                {
                    "success": result,
                    "message_id": led_message.id,
                    "timestamp": utc_now().isoformat(),
                }
            )
        except TypeError as exc:
            route_logger.error("Type error sending LED message: %s", exc, exc_info=True)
            return jsonify({"success": False, "error": f"Invalid data type in request: {str(exc)}"})
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.error("Error sending LED message: %s", exc, exc_info=True)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/led/send_canned", methods=["POST"])
    def api_led_send_canned():
        try:
            ensure_led_tables()

            data = request.get_json(silent=True) or {}
            message_name = data.get("message_name")
            parameters = data.get("parameters", {})

            if not message_name:
                return jsonify({"success": False, "error": "Message name is required"})

            if not led_module.led_controller:
                return jsonify({"success": False, "error": "LED controller not available"})

            led_message = LEDMessage(
                message_type="canned",
                content=message_name,
                priority=2,
                scheduled_time=utc_now(),
            )
            db.session.add(led_message)
            db.session.commit()

            result = led_module.led_controller.send_canned_message(message_name, **parameters)

            if result:
                led_message.sent_at = utc_now()
                db.session.commit()

            return jsonify(
                {
                    "success": result,
                    "message_id": led_message.id,
                    "timestamp": utc_now().isoformat(),
                }
            )
        except Exception as exc:
            route_logger.error("Error sending canned message: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/led/clear", methods=["POST"])
    def api_led_clear():
        try:
            ensure_led_tables()

            if not led_module.led_controller:
                return jsonify({"success": False, "error": "LED controller not available"})

            result = led_module.led_controller.clear_display()

            if result:
                led_message = LEDMessage(
                    message_type="system",
                    content="DISPLAY_CLEARED",
                    priority=1,
                    scheduled_time=utc_now(),
                    sent_at=utc_now(),
                )
                db.session.add(led_message)
                db.session.commit()

            return jsonify({"success": result, "timestamp": utc_now().isoformat()})
        except Exception as exc:
            route_logger.error("Error clearing LED display: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/led/brightness", methods=["POST"])
    def api_led_brightness():
        try:
            ensure_led_tables()

            data = request.get_json(silent=True) or {}
            brightness = int(data.get("brightness", 10))

            if not 1 <= brightness <= 16:
                return jsonify({"success": False, "error": "Brightness must be between 1 and 16"})

            if not led_module.led_controller:
                return jsonify({"success": False, "error": "LED controller not available"})

            result = led_module.led_controller.set_brightness(brightness)

            if result:
                ip_address = os.getenv("LED_SIGN_IP", "")
                status = LEDSignStatus.query.filter_by(sign_ip=ip_address).first()
                if status:
                    status.brightness_level = brightness
                    status.last_update = utc_now()
                    db.session.commit()

            return jsonify({"success": result, "brightness": brightness})
        except Exception as exc:
            route_logger.error("Error setting LED brightness: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/led/test", methods=["POST"])
    def api_led_test():
        try:
            if not led_module.led_controller:
                return jsonify({"success": False, "error": "LED controller not available"})

            result = led_module.led_controller.test_all_features()

            led_message = LEDMessage(
                message_type="system",
                content="FEATURE_TEST",
                priority=1,
                scheduled_time=utc_now(),
                sent_at=utc_now() if result else None,
            )
            db.session.add(led_message)
            db.session.commit()

            return jsonify({"success": result, "message": "Test sequence started"})
        except Exception as exc:
            route_logger.error("Error running LED test: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/led/emergency", methods=["POST"])
    def api_led_emergency():
        try:
            data = request.get_json(silent=True) or {}
            message = data.get("message", "EMERGENCY ALERT")
            duration = int(data.get("duration", 30))

            if not led_module.led_controller:
                return jsonify({"success": False, "error": "LED controller not available"})

            led_message = LEDMessage(
                message_type="emergency",
                content=message,
                priority=0,
                display_time=duration,
                scheduled_time=utc_now(),
            )
            db.session.add(led_message)
            db.session.commit()

            result = led_module.led_controller.emergency_override(message, duration)

            if result:
                led_message.sent_at = utc_now()
                db.session.commit()

            return jsonify({"success": result, "message_id": led_message.id, "duration": duration})
        except Exception as exc:
            route_logger.error("Error sending emergency message: %s", exc)
            return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/led/status")
    def api_led_status():
        try:
            from app_core.led import LED_SIGN_IP, LED_SIGN_PORT

            # Check if health check is requested (default: True for active monitoring)
            check_health = request.args.get('health_check', 'true').lower() == 'true'

            if not led_module.led_controller:
                # Return configuration even when not connected
                return jsonify({
                    "success": True,
                    "connected": False,
                    "host": LED_SIGN_IP,
                    "port": LED_SIGN_PORT,
                    "error": "LED controller not available - check bridge connection",
                    "timestamp": utc_now().isoformat(),
                })

            # Get status with optional active health check
            status = led_module.led_controller.get_status(check_health=check_health)

            return jsonify({
                "success": True,
                "connected": status.get('connected', False),
                "host": status.get('host'),
                "port": status.get('port'),
                "health_checked": check_health,
                "timestamp": utc_now().isoformat(),
            })
        except Exception as exc:
            route_logger.error("Error retrieving LED status: %s", exc)
            from app_core.led import LED_SIGN_IP, LED_SIGN_PORT
            return jsonify({
                "success": False,
                "connected": False,
                "host": LED_SIGN_IP,
                "port": LED_SIGN_PORT,
                "error": str(exc)
            })

    @app.route("/api/led/messages")
    def api_led_messages():
        try:
            ensure_led_tables()

            messages = (
                LEDMessage.query.order_by(LEDMessage.created_at.desc()).limit(50).all()
            )
            serialized = [
                {
                    "id": message.id,
                    "message_type": message.message_type,
                    "content": message.content,
                    "priority": message.priority,
                    "status": "sent" if message.sent_at else "pending",
                    "scheduled_time": message.scheduled_time.isoformat()
                    if message.scheduled_time
                    else None,
                    "sent_at": message.sent_at.isoformat() if message.sent_at else None,
                    "created_at": message.created_at.isoformat() if message.created_at else None,
                }
                for message in messages
            ]
            return jsonify({"success": True, "messages": serialized, "count": len(serialized)})
        except Exception as exc:
            route_logger.error("Error retrieving LED messages: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/led/canned_messages")
    def api_led_canned_messages():
        if not led_module.led_controller:
            return jsonify({"success": False, "error": "LED controller not available"})

        canned = []
        for name, config in led_module.led_controller.canned_messages.items():
            canned.append(
                {
                    "name": name,
                    "lines": config.get("lines") or config.get("text"),
                    "parameters": list((config.get("parameters") or {}).keys()),
                }
            )

        return jsonify({"success": True, "messages": canned})

    @app.route("/api/led/serial_config", methods=["GET", "POST"])
    def api_led_serial_config():
        """Get or set serial configuration for the LED sign adapter."""
        import os

        if request.method == "GET":
            # Return current serial configuration from database, falling back to environment
            try:
                ensure_led_tables()
                status_record = LEDSignStatus.query.first()

                if status_record and status_record.serial_mode and status_record.baud_rate:
                    # Use database values if available
                    config = {
                        "serial_mode": status_record.serial_mode,
                        "baud_rate": status_record.baud_rate,
                        "led_sign_ip": os.getenv("LED_SIGN_IP", ""),
                        "led_sign_port": int(os.getenv("LED_SIGN_PORT", "10001")),
                    }
                else:
                    # Fall back to environment variables
                    config = {
                        "serial_mode": os.getenv("LED_SERIAL_MODE", "RS232"),
                        "baud_rate": int(os.getenv("LED_BAUD_RATE", "9600")),
                        "led_sign_ip": os.getenv("LED_SIGN_IP", ""),
                        "led_sign_port": int(os.getenv("LED_SIGN_PORT", "10001")),
                    }

                return jsonify({"success": True, "config": config})

            except Exception as db_error:
                route_logger.warning(f"Could not retrieve serial config from database: {db_error}")
                # Fall back to environment variables on error
                config = {
                    "serial_mode": os.getenv("LED_SERIAL_MODE", "RS232"),
                    "baud_rate": int(os.getenv("LED_BAUD_RATE", "9600")),
                    "led_sign_ip": os.getenv("LED_SIGN_IP", ""),
                    "led_sign_port": int(os.getenv("LED_SIGN_PORT", "10001")),
                }
                return jsonify({"success": True, "config": config})

        elif request.method == "POST":
            try:
                data = request.get_json(silent=True) or {}
                serial_mode = data.get("serial_mode", "RS232")
                baud_rate = int(data.get("baud_rate", 9600))

                # Validate serial mode
                if serial_mode not in ["RS232", "RS485"]:
                    return jsonify({"success": False, "error": "Invalid serial mode. Must be RS232 or RS485."})

                # Validate baud rate
                valid_baud_rates = [9600, 19200, 38400, 57600, 115200]
                if baud_rate not in valid_baud_rates:
                    return jsonify({"success": False, "error": f"Invalid baud rate. Must be one of {valid_baud_rates}."})

                # Note: These settings are informational only and stored in the database
                # The actual serial configuration must be set on the Lantronix adapter
                route_logger.info(f"LED serial configuration updated: {serial_mode} @ {baud_rate} baud")

                # Store configuration in LEDSignStatus table
                try:
                    ensure_led_tables()

                    # Check if there's an existing status record
                    status_record = LEDSignStatus.query.first()
                    if not status_record:
                        status_record = LEDSignStatus(
                            sign_ip=os.getenv("LED_SIGN_IP", "192.168.1.100"),
                            serial_mode=serial_mode,
                            baud_rate=baud_rate,
                            brightness_level=10,
                            is_connected=False,
                            last_update=utc_now(),
                        )
                        db.session.add(status_record)
                    else:
                        # Update existing record with new serial configuration
                        status_record.serial_mode = serial_mode
                        status_record.baud_rate = baud_rate
                        status_record.last_update = utc_now()

                    db.session.commit()

                except Exception as db_error:
                    route_logger.warning(f"Could not store serial config in database: {db_error}")
                    return jsonify({"success": False, "error": f"Database error: {str(db_error)}"})

                return jsonify({
                    "success": True,
                    "message": f"Serial configuration saved: {serial_mode} @ {baud_rate} baud",
                    "config": {
                        "serial_mode": serial_mode,
                        "baud_rate": baud_rate,
                    },
                    "note": "Remember to configure these same settings on your Lantronix adapter."
                })
            except Exception as exc:
                route_logger.error(f"Error saving serial configuration: {exc}")
                return jsonify({"success": False, "error": str(exc)})

    @app.route("/api/led/reconnect", methods=["POST"])
    def api_led_reconnect():
        """Attempt to reinitialize the LED controller connection."""
        try:
            from app_core.led import LED_SIGN_IP, LED_SIGN_PORT, LEDSignController, get_location_settings
            import app_core.led as led_module

            route_logger.info(f"Attempting to reconnect to LED sign at {LED_SIGN_IP}:{LED_SIGN_PORT}")

            # Try to create a new controller directly (bypass initialise_led_controller's checks)
            try:
                settings = get_location_settings()
                controller = LEDSignController(
                    LED_SIGN_IP,
                    LED_SIGN_PORT,
                    location_settings=settings,
                )

                # Check if connected
                if controller.connected:
                    # Update the global variables
                    led_module.led_controller = controller
                    led_module.LED_AVAILABLE = True

                    route_logger.info(f"Successfully reconnected to LED sign at {LED_SIGN_IP}:{LED_SIGN_PORT}")

                    return jsonify({
                        "success": True,
                        "message": f"Successfully connected to LED sign at {LED_SIGN_IP}:{LED_SIGN_PORT}",
                        "connected": True
                    })
                else:
                    return jsonify({
                        "success": False,
                        "error": f"Could not connect to LED sign at {LED_SIGN_IP}:{LED_SIGN_PORT}. Check bridge is powered on and configured as TCP Server on port {LED_SIGN_PORT}.",
                        "connected": False
                    })

            except Exception as connect_error:
                route_logger.error(f"Error creating LED controller: {connect_error}")
                return jsonify({
                    "success": False,
                    "error": f"Failed to create controller: {str(connect_error)}",
                    "connected": False
                })

        except Exception as exc:
            route_logger.error(f"Error reconnecting to LED sign: {exc}")
            return jsonify({
                "success": False,
                "error": str(exc),
                "connected": False
            })


def _enum_label(value: Any) -> str:
    if hasattr(value, "name"):
        return value.name
    return str(value)


__all__ = ["register"]
