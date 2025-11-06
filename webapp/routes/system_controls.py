"""Routes for system-level controls including GPIO relay management."""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import (
    Flask,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    session,
)

from app_core.extensions import db
from app_core.models import GPIOActivationLog
from app_utils.gpio import GPIOActivationType
from app_utils.time import utc_now


def register(app: Flask, logger) -> None:
    """Register system control routes on the Flask application."""

    route_logger = logger.getChild("system_controls")

    def _get_gpio_controller():
        """Get or create the global GPIO controller instance."""
        if not hasattr(current_app, "gpio_controller"):
            from app_utils.gpio import GPIOController

            current_app.gpio_controller = GPIOController(
                db_session=db.session, logger=route_logger
            )

            # Load GPIO configuration from environment/database
            _load_gpio_configuration(current_app.gpio_controller)

        return current_app.gpio_controller

    def _load_gpio_configuration(controller):
        """Load GPIO pin configurations from environment variables."""
        import os
        from app_utils.gpio import GPIOPinConfig

        # Load EAS transmitter GPIO configuration
        eas_gpio_pin = os.getenv("EAS_GPIO_PIN")
        if eas_gpio_pin:
            try:
                pin_number = int(eas_gpio_pin)
                active_high = os.getenv("EAS_GPIO_ACTIVE_STATE", "HIGH").upper() != "LOW"
                hold_seconds = float(os.getenv("EAS_GPIO_HOLD_SECONDS", "5") or 5)
                watchdog_seconds = float(os.getenv("EAS_GPIO_WATCHDOG_SECONDS", "300") or 300)

                config = GPIOPinConfig(
                    pin=pin_number,
                    name="EAS Transmitter PTT",
                    active_high=active_high,
                    hold_seconds=hold_seconds,
                    watchdog_seconds=watchdog_seconds,
                    enabled=True,
                )

                controller.add_pin(config)
                route_logger.info(f"Loaded EAS GPIO configuration: pin {pin_number}")
            except Exception as exc:
                route_logger.error(f"Failed to load EAS GPIO configuration: {exc}")

        # Load additional GPIO pins from environment (comma-separated list)
        # Format: PIN:NAME:ACTIVE_HIGH:HOLD_SECONDS:WATCHDOG_SECONDS
        additional_pins = os.getenv("GPIO_ADDITIONAL_PINS", "").strip()
        if additional_pins:
            for pin_config in additional_pins.split(","):
                try:
                    parts = pin_config.strip().split(":")
                    if len(parts) < 2:
                        continue

                    pin_number = int(parts[0])
                    name = parts[1]
                    active_high = parts[2].upper() != "LOW" if len(parts) > 2 else True
                    hold_seconds = float(parts[3]) if len(parts) > 3 else 5.0
                    watchdog_seconds = float(parts[4]) if len(parts) > 4 else 300.0

                    config = GPIOPinConfig(
                        pin=pin_number,
                        name=name,
                        active_high=active_high,
                        hold_seconds=hold_seconds,
                        watchdog_seconds=watchdog_seconds,
                        enabled=True,
                    )

                    controller.add_pin(config)
                    route_logger.info(f"Loaded additional GPIO pin: {pin_number} ({name})")
                except Exception as exc:
                    route_logger.error(f"Failed to parse GPIO config '{pin_config}': {exc}")

        # Load individual GPIO_PIN_<number> environment variables
        # Format: GPIO_PIN_17=HIGH:5:300:My Pin Name
        # or just: GPIO_PIN_17=17 (pin number only)
        import re
        gpio_pin_pattern = re.compile(r'^GPIO_PIN_(\d+)$')
        for env_key, env_value in os.environ.items():
            match = gpio_pin_pattern.match(env_key)
            if match:
                try:
                    pin_number = int(match.group(1))
                    value = env_value.strip()

                    # Parse value - could be just pin number or colon-separated config
                    # Format: [ACTIVE_STATE]:[HOLD_SECONDS]:[WATCHDOG_SECONDS]:[NAME]
                    if ':' in value:
                        parts = value.split(':')
                        active_high = parts[0].upper() != "LOW" if parts[0] else True
                        hold_seconds = float(parts[1]) if len(parts) > 1 and parts[1] else 5.0
                        watchdog_seconds = float(parts[2]) if len(parts) > 2 and parts[2] else 300.0
                        name = parts[3] if len(parts) > 3 and parts[3] else f"GPIO Pin {pin_number}"
                    else:
                        # Simple format - just validate it's a number or HIGH/LOW
                        if value.upper() in ('HIGH', 'LOW'):
                            active_high = value.upper() != "LOW"
                        else:
                            # Assume it's the pin number confirmation
                            int(value)  # Validate it's a number
                            active_high = True
                        name = f"GPIO Pin {pin_number}"
                        hold_seconds = 5.0
                        watchdog_seconds = 300.0

                    config = GPIOPinConfig(
                        pin=pin_number,
                        name=name,
                        active_high=active_high,
                        hold_seconds=hold_seconds,
                        watchdog_seconds=watchdog_seconds,
                        enabled=True,
                    )

                    controller.add_pin(config)
                    route_logger.info(f"Loaded GPIO pin from {env_key}: pin {pin_number} ({name})")
                except Exception as exc:
                    route_logger.error(f"Failed to parse {env_key}={env_value}: {exc}")

    def _get_current_user() -> str:
        """Get current username from session."""
        return session.get("username", "anonymous")

    @app.route("/api/gpio/status")
    def gpio_status():
        """Get current status of all configured GPIO pins."""
        try:
            controller = _get_gpio_controller()
            states = controller.get_all_states()

            return jsonify(
                {
                    "success": True,
                    "pins": list(states.values()),
                    "timestamp": datetime.now().isoformat(),
                }
            )
        except Exception as exc:
            route_logger.error(f"Failed to get GPIO status: {exc}")
            return (
                jsonify({"success": False, "error": str(exc)}),
                500,
            )

    @app.route("/api/gpio/activate/<int:pin>", methods=["POST"])
    def gpio_activate(pin: int):
        """Manually activate a GPIO pin.

        Request body:
            {
                "reason": "Manual test activation",
                "activation_type": "manual"  // or "test", "override"
            }
        """
        try:
            controller = _get_gpio_controller()
            data = request.get_json() or {}

            reason = data.get("reason", "Manual activation via web UI")
            activation_type_str = data.get("activation_type", "manual")

            # Parse activation type
            try:
                activation_type = GPIOActivationType[activation_type_str.upper()]
            except KeyError:
                activation_type = GPIOActivationType.MANUAL

            # Get current user
            operator = _get_current_user()

            # Activate the pin
            success = controller.activate(
                pin=pin,
                activation_type=activation_type,
                operator=operator,
                reason=reason,
            )

            if success:
                return jsonify(
                    {
                        "success": True,
                        "message": f"Pin {pin} activated successfully",
                        "pin": pin,
                    }
                )
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Failed to activate pin {pin}",
                        }
                    ),
                    400,
                )

        except Exception as exc:
            route_logger.error(f"Failed to activate GPIO pin {pin}: {exc}")
            return (
                jsonify({"success": False, "error": str(exc)}),
                500,
            )

    @app.route("/api/gpio/deactivate/<int:pin>", methods=["POST"])
    def gpio_deactivate(pin: int):
        """Manually deactivate a GPIO pin.

        Request body:
            {
                "force": false  // If true, ignore hold time
            }
        """
        try:
            controller = _get_gpio_controller()
            data = request.get_json() or {}
            force = data.get("force", False)

            success = controller.deactivate(pin=pin, force=force)

            if success:
                return jsonify(
                    {
                        "success": True,
                        "message": f"Pin {pin} deactivated successfully",
                        "pin": pin,
                    }
                )
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Failed to deactivate pin {pin}",
                        }
                    ),
                    400,
                )

        except Exception as exc:
            route_logger.error(f"Failed to deactivate GPIO pin {pin}: {exc}")
            return (
                jsonify({"success": False, "error": str(exc)}),
                500,
            )

    @app.route("/api/gpio/history")
    def gpio_history():
        """Get GPIO activation history.

        Query parameters:
            pin: Filter by pin number (optional)
            hours: Hours of history to retrieve (default: 24)
            limit: Maximum number of records (default: 100)
        """
        try:
            pin = request.args.get("pin", type=int)
            hours = request.args.get("hours", default=24, type=int)
            limit = request.args.get("limit", default=100, type=int)

            # Clamp limits
            hours = max(1, min(hours, 168))  # Max 1 week
            limit = max(1, min(limit, 1000))

            # Build query
            cutoff = utc_now() - timedelta(hours=hours)
            query = db.session.query(GPIOActivationLog).filter(
                GPIOActivationLog.activated_at >= cutoff
            )

            if pin is not None:
                query = query.filter(GPIOActivationLog.pin == pin)

            # Order by most recent first
            query = query.order_by(GPIOActivationLog.activated_at.desc())
            query = query.limit(limit)

            logs = query.all()

            return jsonify(
                {
                    "success": True,
                    "count": len(logs),
                    "logs": [log.to_dict() for log in logs],
                    "filters": {
                        "pin": pin,
                        "hours": hours,
                        "limit": limit,
                    },
                }
            )

        except Exception as exc:
            route_logger.error(f"Failed to retrieve GPIO history: {exc}")
            return (
                jsonify({"success": False, "error": str(exc)}),
                500,
            )

    @app.route("/api/gpio/statistics")
    def gpio_statistics():
        """Get GPIO activation statistics.

        Query parameters:
            days: Number of days for statistics (default: 7)
        """
        try:
            days = request.args.get("days", default=7, type=int)
            days = max(1, min(days, 90))  # Clamp to 1-90 days

            cutoff = utc_now() - timedelta(days=days)

            # Get activation counts by pin
            from sqlalchemy import func, case

            pin_stats = (
                db.session.query(
                    GPIOActivationLog.pin,
                    func.count(GPIOActivationLog.id).label("activation_count"),
                    func.avg(GPIOActivationLog.duration_seconds).label("avg_duration"),
                    func.max(GPIOActivationLog.duration_seconds).label("max_duration"),
                    func.sum(
                        case(
                            (GPIOActivationLog.success.is_(False), 1),
                            else_=0,
                        )
                    ).label("failure_count"),
                )
                .filter(GPIOActivationLog.activated_at >= cutoff)
                .group_by(GPIOActivationLog.pin)
                .all()
            )

            # Get activation counts by type
            type_stats = (
                db.session.query(
                    GPIOActivationLog.activation_type,
                    func.count(GPIOActivationLog.id).label("count"),
                )
                .filter(GPIOActivationLog.activated_at >= cutoff)
                .group_by(GPIOActivationLog.activation_type)
                .all()
            )

            return jsonify(
                {
                    "success": True,
                    "days": days,
                    "by_pin": [
                        {
                            "pin": stat.pin,
                            "activation_count": stat.activation_count,
                            "avg_duration_seconds": float(stat.avg_duration or 0),
                            "max_duration_seconds": float(stat.max_duration or 0),
                            "failure_count": int(stat.failure_count or 0),
                        }
                        for stat in pin_stats
                    ],
                    "by_type": [
                        {"activation_type": stat.activation_type, "count": stat.count}
                        for stat in type_stats
                    ],
                }
            )

        except Exception as exc:
            route_logger.error(f"Failed to generate GPIO statistics: {exc}")
            return (
                jsonify({"success": False, "error": str(exc)}),
                500,
            )

    @app.route("/admin/gpio")
    def gpio_control_panel():
        """Render the GPIO control panel page."""
        try:
            controller = _get_gpio_controller()
            states = controller.get_all_states()

            # Get recent history (last 24 hours)
            cutoff = utc_now() - timedelta(hours=24)
            recent_logs = (
                db.session.query(GPIOActivationLog)
                .filter(GPIOActivationLog.activated_at >= cutoff)
                .order_by(GPIOActivationLog.activated_at.desc())
                .limit(50)
                .all()
            )

            return render_template(
                "gpio_control.html",
                pins=list(states.values()),
                recent_logs=recent_logs,
                current_user=_get_current_user(),
            )

        except Exception as exc:
            route_logger.error(f"Failed to render GPIO control panel: {exc}")
            return (
                render_template(
                    "error.html",
                    error_message=f"Failed to load GPIO control panel: {exc}",
                ),
                500,
            )
