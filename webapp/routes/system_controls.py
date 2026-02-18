"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Routes for system-level controls including GPIO relay management."""

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

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import GPIOActivationLog
from app_utils.gpio import (
    GPIOActivationType,
    GPIOBehavior,
    GPIO_BEHAVIOR_LABELS,
    load_gpio_behavior_matrix_from_db,
    load_gpio_pin_configs_from_db,
)
from app_utils.pi_pinout import PIN_ROWS
from app_utils.time import utc_now


def _get_oled_enabled_status():
    """Get OLED enabled status from database."""
    try:
        from app_core.hardware_settings import get_oled_settings
        oled_settings = get_oled_settings()
        return oled_settings.get('enabled', False)
    except Exception:
        return False


def register(app: Flask, logger) -> None:
    """Register system control routes on the Flask application."""

    route_logger = logger.getChild("system_controls")

    def _get_configured_gpio_pins():
        """Load GPIO pin configuration from database-backed hardware settings."""

        oled_enabled = _get_oled_enabled_status()
        return load_gpio_pin_configs_from_db(route_logger, oled_enabled=oled_enabled)

    def _sync_gpio_configuration(controller):
        """Keep in-memory controller pins aligned with persisted configuration."""

        configs = _get_configured_gpio_pins()
        configured_pins = {config.pin for config in configs}
        current_states = controller.get_all_states()
        loaded_pins = set(current_states.keys())

        # Remove stale pins that are no longer configured.
        for pin in loaded_pins - configured_pins:
            try:
                controller.remove_pin(pin)
                route_logger.info("Removed stale GPIO configuration for pin %s", pin)
            except Exception as exc:  # pragma: no cover - hardware teardown
                route_logger.error("Failed to remove stale GPIO pin %s: %s", pin, exc)

        # Add newly configured pins.
        for config in configs:
            if config.pin in loaded_pins:
                continue
            try:
                controller.add_pin(config)
                route_logger.info(
                    "Loaded GPIO configuration: pin %s (%s)", config.pin, config.name
                )
            except ValueError:
                route_logger.warning("GPIO pin %s already configured; skipping", config.pin)
            except Exception as exc:  # pragma: no cover - hardware setup
                route_logger.error(
                    "Failed to register GPIO pin %s (%s): %s",
                    config.pin,
                    config.name,
                    exc,
                )

        behavior_manager = getattr(controller, "behavior_manager", None)
        if behavior_manager:
            behavior_manager.update_pin_configs(configs)
            behavior_manager.update_behavior_matrix(
                load_gpio_behavior_matrix_from_db(route_logger)
            )

        return configs

    def _get_gpio_controller():
        """Get or create the global GPIO controller instance."""
        if not hasattr(current_app, "gpio_controller"):
            from app_utils.gpio import GPIOController

            current_app.gpio_controller = GPIOController(
                db_session=db.session, logger=route_logger
            )

        _sync_gpio_configuration(current_app.gpio_controller)
        return current_app.gpio_controller

    def _build_pin_entry(pin_def, config_map, behavior_matrix):
        entry = {
            "physical": pin_def.physical,
            "name": pin_def.name,
            "type": pin_def.pin_type,
            "bcm": pin_def.bcm,
            "description": pin_def.description,
            "is_gpio": pin_def.is_gpio,
            "reserved_for": pin_def.reserved_for,
            "reserved_detail": pin_def.reserved_detail,
            "configured": False,
            "active_high": None,
            "behaviors": [],
        }

        if pin_def.is_gpio and pin_def.bcm is not None:
            config = config_map.get(pin_def.bcm)
            entry["configured"] = config is not None
            entry["active_high"] = config.active_high if config else None
            behaviors = behavior_matrix.get(pin_def.bcm, set())
            entry["behaviors"] = [behavior.value for behavior in sorted(behaviors, key=lambda b: b.value)]

        return entry

    def _build_pin_rows():
        oled_enabled = _get_oled_enabled_status()
        configs = load_gpio_pin_configs_from_db(route_logger, oled_enabled=oled_enabled)
        behavior_matrix = load_gpio_behavior_matrix_from_db(route_logger, oled_enabled=oled_enabled)
        config_map = {cfg.pin: cfg for cfg in configs}

        rows = []
        for left_pin, right_pin in PIN_ROWS:
            rows.append(
                {
                    "left": _build_pin_entry(left_pin, config_map, behavior_matrix),
                    "right": _build_pin_entry(right_pin, config_map, behavior_matrix),
                }
            )
        return rows

    def _get_current_user() -> str:
        """Get current username from session."""
        return session.get("username", "anonymous")

    @app.route("/api/gpio/status")
    @require_permission('gpio.view')
    def gpio_status():
        """Get current status of all configured GPIO pins with summary data for OLED."""
        try:
            controller = _get_gpio_controller()
            states = controller.get_all_states()
            pins_list = list(states.values())
            
            # Calculate summary data for OLED display
            active_pins = [p for p in pins_list if p.get('is_active', False)]
            active_count = len(active_pins)
            
            # Create active pins summary
            if active_count == 0:
                active_pins_summary = "No active pins"
            elif active_count <= 3:
                active_pins_summary = ", ".join([f"GPIO{p['pin']}" for p in active_pins])
            else:
                first_three = ", ".join([f"GPIO{p['pin']}" for p in active_pins[:3]])
                active_pins_summary = f"{first_three} +{active_count - 3} more"
            
            # Get last activation from database
            last_activation = db.session.query(GPIOActivationLog).filter(
                GPIOActivationLog.success
            ).order_by(GPIOActivationLog.activated_at.desc()).first()
            
            if last_activation:
                time_ago = utc_now() - last_activation.activated_at
                if time_ago.total_seconds() < 60:
                    time_str = f"{int(time_ago.total_seconds())}s ago"
                elif time_ago.total_seconds() < 3600:
                    time_str = f"{int(time_ago.total_seconds() / 60)}m ago"
                else:
                    time_str = f"{int(time_ago.total_seconds() / 3600)}h ago"
                last_activation_summary = f"GPIO{last_activation.pin} {time_str}"
            else:
                last_activation_summary = "No recent activations"
            
            # Count activations today
            today_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
            activations_today = db.session.query(GPIOActivationLog).filter(
                GPIOActivationLog.activated_at >= today_start,
                GPIOActivationLog.success
            ).count()

            return jsonify(
                {
                    "success": True,
                    "pins": pins_list,
                    "timestamp": datetime.now().isoformat(),
                    # Summary data for OLED
                    "active_count": active_count,
                    "active_pins_summary": active_pins_summary,
                    "last_activation_summary": last_activation_summary,
                    "activations_today": activations_today,
                }
            )
        except Exception as exc:
            route_logger.error(f"Failed to get GPIO status: {exc}")
            return (
                jsonify({"success": False, "error": str(exc)}),
                500,
            )

    @app.route("/api/gpio/activate/<int:pin>", methods=["POST"])
    @require_permission('gpio.control')
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
    @require_permission('gpio.control')
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
    @require_permission('gpio.view')
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
    @require_permission('gpio.view')
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
    @require_permission('gpio.view')
    def gpio_control_panel():
        """Render the GPIO control panel page."""
        try:
            controller = _get_gpio_controller()
            states = controller.get_all_states()
            configured_pins = _get_configured_gpio_pins()
            configured_count = len(configured_pins)

            # Build display payload that includes configured pins even if runtime
            # controller has not loaded them yet (e.g., service restart pending).
            pin_entries = []
            state_map = {int(pin): info for pin, info in states.items()}

            for config in configured_pins:
                runtime_state = state_map.pop(config.pin, None)
                if runtime_state is not None:
                    runtime_state['runtime_loaded'] = True
                    pin_entries.append(runtime_state)
                    continue

                pin_entries.append(
                    {
                        'pin': config.pin,
                        'name': config.name,
                        'state': 'unloaded',
                        'enabled': config.enabled,
                        'active_high': config.active_high,
                        'is_active': False,
                        'flash_enabled': config.flash_enabled,
                        'flash_interval_ms': config.flash_interval_ms,
                        'flash_partner_pin': config.flash_partner_pin,
                        'runtime_loaded': False,
                    }
                )

            # Keep any controller-only pins visible for diagnostics.
            for extra_pin in sorted(state_map.keys()):
                info = state_map[extra_pin]
                info['runtime_loaded'] = True
                pin_entries.append(info)

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
                pins=pin_entries,
                recent_logs=recent_logs,
                current_user=_get_current_user(),
                configured_pin_count=configured_count,
                environment_issues=controller.get_environment_issues(),
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

    @app.route("/admin/gpio/pin-map")
    @require_permission('gpio.view')
    def gpio_pin_map():
        """Render the interactive Raspberry Pi pin map."""

        try:
            pin_rows = _build_pin_rows()
            behavior_order = [
                GPIOBehavior.DURATION_OF_ALERT,
                GPIOBehavior.PLAYOUT,
                GPIOBehavior.FLASH,
                GPIOBehavior.FIVE_SECONDS,
                GPIOBehavior.INCOMING_ALERT,
                GPIOBehavior.FORWARDING_ALERT,
            ]
            behavior_descriptions = {
                GPIOBehavior.DURATION_OF_ALERT.value: "Hold the relay active until the alert finishes.",
                GPIOBehavior.PLAYOUT.value: "Activate while tones and audio playout are running.",
                GPIOBehavior.FLASH.value: "Blink the pin rapidly at the start of the alert to drive strobes.",
                GPIOBehavior.FIVE_SECONDS.value: "Pulse the pin for five seconds when playout begins.",
                GPIOBehavior.INCOMING_ALERT.value: "Pulse when a new alert is ingested or queued.",
                GPIOBehavior.FORWARDING_ALERT.value: "Pulse when an alert is forwarded from monitoring inputs.",
            }
            behavior_options = [
                {
                    "value": behavior.value,
                    "label": GPIO_BEHAVIOR_LABELS.get(
                        behavior, behavior.value.replace("_", " ").title()
                    ),
                    "description": behavior_descriptions.get(behavior.value, ""),
                }
                for behavior in behavior_order
            ]

            oled_enabled = _get_oled_enabled_status()
            configured_pins = load_gpio_pin_configs_from_db(route_logger, oled_enabled=oled_enabled)
            pin_config_map = {
                str(config.pin): {
                    "name": config.name,
                    "active_high": config.active_high,
                    "hold_seconds": config.hold_seconds,
                    "watchdog_seconds": config.watchdog_seconds,
                    "flash_enabled": config.flash_enabled,
                    "flash_interval_ms": config.flash_interval_ms,
                    "flash_partner_pin": config.flash_partner_pin,
                }
                for config in configured_pins
            }

            return render_template(
                "gpio_pin_map.html",
                pin_rows=pin_rows,
                behavior_options=behavior_options,
                pin_config_map=pin_config_map,
            )
        except Exception as exc:  # pragma: no cover - rendering safety
            route_logger.error(f"Failed to render GPIO pin map: {exc}")
            return (
                render_template(
                    "error.html",
                    error_message=f"Failed to load GPIO pin map: {exc}",
                ),
                500,
            )
