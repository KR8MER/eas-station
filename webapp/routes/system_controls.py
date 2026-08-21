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

"""Routes for system-level controls including GPIO relay management."""

import json
from datetime import datetime, timedelta, timezone

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
    GPIOBehavior,
    GPIOInputAction,
    GPIO_BEHAVIOR_LABELS,
    GPIO_INPUT_ACTION_IMPLEMENTED,
    GPIO_INPUT_ACTION_LABELS,
    load_gpio_behavior_matrix_from_db,
    load_gpio_interlock_groups_from_db,
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


def _gpio_config_warnings(configured_pins, logger, interlock_groups=None):
    """Return operator-readable warnings about the GPIO behavior matrix and
    any relay interlock groups whose members share a hold-triggering behavior.

    Reuses ``GPIOBehaviorManager.validate_configuration()`` -- the same
    checks the GPIO subprocess runs at startup -- but without a controller,
    so nothing here can touch the physical lines. Purely diagnostic; any
    failure is swallowed so the caller's page still renders. Module-level
    (not nested in ``register()``) so both the GPIO Control page and the
    Relay Interlock Groups page can share it.
    """
    try:
        from app_utils.gpio import GPIOBehaviorManager

        oled_enabled = _get_oled_enabled_status()
        matrix = load_gpio_behavior_matrix_from_db(logger, oled_enabled=oled_enabled)
        interlock_groups = interlock_groups or []
        if not matrix and not interlock_groups:
            return []
        manager = GPIOBehaviorManager(
            controller=None,
            pin_configs=configured_pins,
            behavior_matrix=matrix,
            logger=None,
            interlock_groups=interlock_groups,
        )
        return list(manager.validate_configuration())
    except Exception as exc:  # pragma: no cover - diagnostic only
        if logger:
            logger.debug("GPIO behavior/interlock validation skipped: %s", exc)
        return []


def pin_reservation_is_active(reserved_for, oled_enabled):
    """Whether a *fixed* physical-wiring reservation actually competes for its pin.

    ``reserved_for`` (from ``app_utils.pi_pinout.PinDefinition``) is a static
    label describing what a pin is soldered to on the Argon case -- it is
    set whether or not that hardware feature is installed/enabled. Treating
    it as an active claimant unconditionally causes a false-positive
    conflict: e.g. BCM 14 is reserved for "Argon OLED module", so enabling
    GPS or Zigbee on the Pi's default primary UART (which also lives on BCM
    14) used to flag a conflict even with the OLED completely disabled.
    """
    if not reserved_for:
        return False
    if reserved_for == "Argon OLED module":
        return bool(oled_enabled)
    return True


def register(app: Flask, logger) -> None:
    """Register system control routes on the Flask application."""

    route_logger = logger.getChild("system_controls")

    def _get_configured_gpio_pins():
        """Load GPIO pin configuration from database-backed hardware settings."""

        oled_enabled = _get_oled_enabled_status()
        return load_gpio_pin_configs_from_db(route_logger, oled_enabled=oled_enabled)

    def _gpio_pins_snapshot():
        """Return ``(pins, live)`` for the configured GPIO pins.

        The web process must NOT build a GPIOController — only the
        eas-station-gpio subprocess can claim the physical lines.  When that
        subprocess is up it publishes a live pin-state snapshot to Redis
        (``app_core.gpio_commands.get_pin_states``); we render from that.  When
        it's down we still list the configured pins (state ``unknown``) so the
        page isn't empty.  ``live`` is ``True`` when the snapshot came from the
        running subprocess.
        """
        from app_core.gpio_commands import get_pin_states

        snapshot = get_pin_states()
        if snapshot.get("available"):
            return snapshot.get("pins", []), True

        pins = []
        for config in _get_configured_gpio_pins():
            pins.append(
                {
                    "pin": config.pin,
                    "name": config.name,
                    "state": "unknown",
                    "enabled": config.enabled,
                    "active_high": config.active_high,
                    "is_active": False,
                    "flash_enabled": config.flash_enabled,
                    "flash_interval_ms": config.flash_interval_ms,
                    "flash_partner_pin": config.flash_partner_pin,
                }
            )
        return pins, False

    def _behavior_matrix_warnings(configured_pins):
        """Return operator-readable GPIO behavior/interlock warnings for the
        control panel. Thin wrapper over the shared module-level helper."""
        interlock_groups = load_gpio_interlock_groups_from_db(route_logger)
        return _gpio_config_warnings(configured_pins, route_logger, interlock_groups)

    def _dynamic_hardware_reservations():
        """Return ``{bcm: [{\'source\', \'detail\'}, ...]}`` for GPIO pins claimed
        by settings-driven hardware features.

        Unlike the fixed Argon OLED wiring in ``app_utils.pi_pinout`` (soldered
        to specific pins forever), these four features each store *which* pin
        they use as an Integer column in ``HardwareSettings`` and an operator
        can repoint them any time from Admin -> Hardware Settings. A pin map
        that only knows the static reservations silently shows those pins as
        "available" even while genuinely in use -- e.g. the GPS PPS input and
        the NeoPixel strip both default to BCM 18, a real conflict the page
        previously had no way to surface. Computed fresh on every render (not
        cached) so a settings change is reflected immediately.
        """
        from app_core.hardware_settings import (
            get_dead_air_settings,
            get_gps_settings,
            get_neopixel_settings,
            get_oled_settings,
            get_zigbee_settings,
        )

        reservations: dict = {}

        def _claim(pin, source, detail):
            if pin is None:
                return
            try:
                pin = int(pin)
            except (TypeError, ValueError):
                return
            reservations.setdefault(pin, []).append({"source": source, "detail": detail})

        def _is_primary_uart_port(port):
            """True when *port* names the Pi's primary hardware UART.

            GPS and Zigbee both configure a serial device path rather than a
            pin number, but that device can be the primary UART -- which is
            permanently wired to BCM 14 (TXD0) / BCM 15 (RXD0) -- and both
            features default to it (``/dev/serial0`` for GPS,
            ``/dev/ttyAMA0`` for Zigbee in HardwareSettings' column
            defaults). ``/dev/serial0`` is the stable alias documented in
            docs/hardware/GPS_HAT_SETUP.md; the raw device name varies by Pi
            model (``ttyAMA0``/``ttyS0`` on Pi 3/4, ``ttyAMA10`` etc. via the
            RP1 chip on Pi 5), so match the ``ttyAMA*`` family generally
            rather than a single hardcoded name.
            """
            if not port:
                return False
            normalized = str(port).strip().lower()
            if normalized in ("/dev/serial0", "/dev/ttys0"):
                return True
            return normalized.startswith("/dev/ttyama")

        try:
            dead_air = get_dead_air_settings()
            if dead_air.get("buzzer_gpio_pin"):
                _claim(
                    dead_air["buzzer_gpio_pin"],
                    "Dead-air rack buzzer",
                    "Sounds while station audio is silent and unacknowledged.",
                )

            neopixel = get_neopixel_settings()
            if neopixel.get("enabled"):
                _claim(
                    neopixel.get("gpio_pin"),
                    "NeoPixel indicator strip",
                    "Drives the WS2812B status LEDs.",
                )

            gps = get_gps_settings()
            if gps.get("enabled"):
                _claim(
                    gps.get("pps_gpio_pin"),
                    "GPS PPS input",
                    "1-pulse-per-second timing signal from the GPS receiver.",
                )
                if _is_primary_uart_port(gps.get("serial_port")):
                    detail = (
                        f"GPS serial port {gps.get('serial_port')} is the Pi's "
                        "primary hardware UART -- permanently wired to this pin."
                    )
                    _claim(14, "GPS receiver (UART TXD0)", detail)
                    _claim(15, "GPS receiver (UART RXD0)", detail)

            oled = get_oled_settings()
            if oled.get("enabled"):
                _claim(
                    oled.get("button_gpio"),
                    "OLED display button",
                    "Physical button wired to the Argon OLED module.",
                )

            zigbee = get_zigbee_settings()
            if zigbee.get("enabled") and _is_primary_uart_port(zigbee.get("port")):
                detail = (
                    f"Zigbee serial port {zigbee.get('port')} is the Pi's "
                    "primary hardware UART -- permanently wired to this pin."
                )
                _claim(14, "Zigbee coordinator (UART TXD0)", detail)
                _claim(15, "Zigbee coordinator (UART RXD0)", detail)
        except Exception as exc:  # pragma: no cover - diagnostic only
            route_logger.debug("Dynamic GPIO reservation lookup skipped: %s", exc)

        return reservations

    def _build_pin_entry(pin_def, config_map, behavior_matrix, hardware_reservations, oled_enabled):
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
            "hardware_reservations": [],
            "conflict": False,
            "direction": "output",
            "input_action": None,
            "input_bounce_ms": 50.0,
            "input_hold_confirm_seconds": None,
        }

        if pin_def.is_gpio and pin_def.bcm is not None:
            config = config_map.get(pin_def.bcm)
            entry["configured"] = config is not None
            entry["active_high"] = config.active_high if config else None
            entry["direction"] = config.direction if config else "output"
            entry["input_action"] = config.input_action if config else None
            entry["input_bounce_ms"] = config.input_bounce_ms if config else 50.0
            entry["input_hold_confirm_seconds"] = config.input_hold_confirm_seconds if config else None
            behaviors = behavior_matrix.get(pin_def.bcm, set())
            entry["behaviors"] = [behavior.value for behavior in sorted(behaviors, key=lambda b: b.value)]

            claims = hardware_reservations.get(pin_def.bcm, [])
            entry["hardware_reservations"] = claims
            reserved_and_active = pin_reservation_is_active(pin_def.reserved_for, oled_enabled)
            entry["reserved_active"] = reserved_and_active
            # Conflict when two hardware features claim the same pin, when a
            # hardware-claimed pin also has a relay behavior assigned to it,
            # or when it collides with a fixed reservation (e.g. the Argon
            # OLED's wiring) -- either way the pin cannot do both jobs at once.
            entry["conflict"] = (
                len(claims) > 1
                or (bool(claims) and entry["configured"])
                or (bool(claims) and reserved_and_active)
            )

        return entry

    def _build_pin_rows():
        oled_enabled = _get_oled_enabled_status()
        configs = load_gpio_pin_configs_from_db(route_logger, oled_enabled=oled_enabled)
        behavior_matrix = load_gpio_behavior_matrix_from_db(route_logger, oled_enabled=oled_enabled)
        config_map = {cfg.pin: cfg for cfg in configs}
        hardware_reservations = _dynamic_hardware_reservations()

        rows = []
        for left_pin, right_pin in PIN_ROWS:
            rows.append(
                {
                    "left": _build_pin_entry(left_pin, config_map, behavior_matrix, hardware_reservations, oled_enabled),
                    "right": _build_pin_entry(right_pin, config_map, behavior_matrix, hardware_reservations, oled_enabled),
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
            pins_list, _live = _gpio_pins_snapshot()

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

    @app.route("/api/gpio/live-pin-states")
    @require_permission('gpio.view')
    def gpio_live_pin_states():
        """Return live electrical state for all GPIO pins plus PPS data from GPS.

        Combines:
        - Software-managed output-pin states from GPIOController
        - PPS pulse data from the GPS Redis key (for the configured PPS input pin)

        Returns a dict keyed by BCM pin number so the GPIO pin map page can
        annotate each pin card with a live HIGH/LOW indicator.
        """
        result: dict = {}

        # --- Output pins from the GPIO subprocess's published snapshot ---
        try:
            pins_list, live = _gpio_pins_snapshot()
            for info in pins_list:
                pin = info.get("pin")
                if pin is None:
                    continue
                bcm = str(pin)
                is_active = bool(info.get("is_active", False))
                # Only report an electrical HIGH/LOW from a live subprocess
                # reading; fallback (config-only) pins are UNKNOWN.  Translate
                # logical active -> electrical level using the pin's polarity so
                # active-low relays aren't inverted.
                if not live or str(info.get("state", "")).lower() == "unknown":
                    electrical_state = "UNKNOWN"
                else:
                    active_high = bool(info.get("active_high", True))
                    electrical_high = is_active if active_high else not is_active
                    electrical_state = "HIGH" if electrical_high else "LOW"
                result[bcm] = {
                    "bcm": pin,
                    "source": "gpio_controller",
                    "is_active": is_active,
                    "state": electrical_state,
                    "name": info.get("name", f"GPIO {pin}"),
                }
        except Exception as exc:
            route_logger.debug("live-pin-states: GPIO snapshot unavailable: %s", exc)

        # --- PPS input pin from GPS Redis key ---
        try:
            from app_core.redis_client import get_redis_client
            redis = get_redis_client(max_retries=1)
            if redis:
                raw = redis.get("gps:status")
                if raw:
                    gps_data = json.loads(raw)
                    pps_pin = gps_data.get("pps_gpio_pin")
                    pps_count = gps_data.get("pps_pulse_count", 0)
                    pps_last = gps_data.get("pps_last_pulse_at")
                    pps_age = None
                    if pps_last:
                        try:
                            pulse_dt = datetime.fromisoformat(pps_last)
                            pps_age = round(
                                (datetime.now(timezone.utc) - pulse_dt).total_seconds(), 2
                            )
                        except Exception:
                            pass
                    if pps_pin is not None:
                        bcm_key = str(pps_pin)
                        # PPS is "HIGH" if we have seen a pulse in the last 2s
                        pps_high = pps_age is not None and pps_age < 2.0
                        result[bcm_key] = {
                            "bcm": pps_pin,
                            "source": "gps_pps",
                            "is_active": pps_high,
                            "state": "HIGH" if pps_high else "LOW",
                            "name": f"PPS (BCM {pps_pin})",
                            "pps_pulse_count": pps_count,
                            "pps_pulse_age_s": pps_age,
                        }
        except Exception as exc:
            route_logger.debug("live-pin-states: GPS Redis unavailable: %s", exc)

        return jsonify({"success": True, "pins": result})

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
            from app_core.gpio_commands import get_pin_states, publish_gpio_command

            data = request.get_json(silent=True) or {}
            reason = data.get("reason", "Manual activation via web UI")
            activation_type = data.get("activation_type", "manual")
            operator = _get_current_user()

            # Best-effort fast-fail: check the pin's interlock group membership
            # against the last-published live-state snapshot so an obviously
            # conflicting request gets an immediate, specific error instead of
            # a silent no-op once the subprocess refuses it. This is racy by
            # nature (the snapshot can be a moment stale) -- the authoritative,
            # race-free guarantee is GPIOController.activate()'s own check
            # under its lock; this only improves the UX for the common case.
            interlock_groups = load_gpio_interlock_groups_from_db(route_logger)
            conflicting_group = next((g for g in interlock_groups if pin in g.pins), None)
            if conflicting_group is not None:
                snapshot = get_pin_states()
                active_by_pin = {
                    p.get("pin"): p.get("is_active")
                    for p in snapshot.get("pins", [])
                }
                conflicting_pin = next(
                    (
                        sibling for sibling in conflicting_group.pins
                        if sibling != pin and active_by_pin.get(sibling)
                    ),
                    None,
                )
                if conflicting_pin is not None:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": (
                                    f"Pin {pin} is interlocked with pin {conflicting_pin} "
                                    f"(group '{conflicting_group.name}'), which is currently active."
                                ),
                            }
                        ),
                        409,
                    )

            # The web process can't drive the pins directly — hand the command
            # to the eas-station-gpio subprocess that owns them.
            receivers = publish_gpio_command(
                "activate",
                pin=pin,
                operator=operator,
                reason=reason,
                activation_type=activation_type,
            )

            if receivers > 0:
                return jsonify(
                    {
                        "success": True,
                        "message": f"Activation of pin {pin} requested",
                        "pin": pin,
                    }
                )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": (
                            "GPIO is disabled or the GPIO service is not running — "
                            "enable GPIO and start the eas-station-gpio service to "
                            "control relays."
                        ),
                    }
                ),
                503,
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
            from app_core.gpio_commands import publish_gpio_command

            data = request.get_json(silent=True) or {}
            force = data.get("force", False)

            receivers = publish_gpio_command("deactivate", pin=pin, force=force)

            if receivers > 0:
                return jsonify(
                    {
                        "success": True,
                        "message": f"Deactivation of pin {pin} requested",
                        "pin": pin,
                    }
                )
            return (
                jsonify(
                    {
                        "success": False,
                        "error": (
                            "GPIO is disabled or the GPIO service is not running — "
                            "enable GPIO and start the eas-station-gpio service to "
                            "control relays."
                        ),
                    }
                ),
                503,
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
            snapshot_pins, live = _gpio_pins_snapshot()
            configured_pins = _get_configured_gpio_pins()
            configured_count = len(configured_pins)

            # The eas-station-gpio subprocess owns the pins and publishes their
            # live state to Redis.  Merge that snapshot onto the configured pins
            # so the panel shows configured pins even when the subprocess hasn't
            # reported yet (e.g. service restart pending).
            state_map = {
                int(info["pin"]): info
                for info in snapshot_pins
                if info.get("pin") is not None
            }

            pin_entries = []
            for config in configured_pins:
                runtime_state = state_map.pop(config.pin, None)
                if runtime_state is not None:
                    runtime_state['runtime_loaded'] = live
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

            # Keep any subprocess-only pins visible for diagnostics.
            for extra_pin in sorted(state_map.keys()):
                info = state_map[extra_pin]
                info['runtime_loaded'] = live
                pin_entries.append(info)

            environment_issues = []
            if not live and configured_count:
                environment_issues.append(
                    "GPIO is disabled or the GPIO service (eas-station-gpio) is not "
                    "reporting state. Relays cannot be controlled until GPIO is "
                    "enabled and the service is running."
                )

            # Behaviour-matrix warnings (e.g. "no pin will key the transmitter")
            # were only logged by the GPIO subprocess at startup, where an
            # operator never sees them — so a matrix that silently leaves the
            # air chain unkeyed during an automated RWT looked healthy here.
            environment_issues.extend(_behavior_matrix_warnings(configured_pins))

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
                environment_issues=environment_issues,
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
                GPIOBehavior.TRANSMITTER_PTT,
                GPIOBehavior.AUDIO_MUTE,
                GPIOBehavior.DURATION_OF_ALERT,
                GPIOBehavior.PLAYOUT,
                GPIOBehavior.FLASH,
                GPIOBehavior.FIVE_SECONDS,
                GPIOBehavior.INCOMING_ALERT,
                GPIOBehavior.FORWARDING_ALERT,
                GPIOBehavior.GATE_PENDING,
            ]
            behavior_descriptions = {
                GPIOBehavior.TRANSMITTER_PTT.value: "Key the transmitter (PTT) for the full broadcast. Assign this to the transmit relay pin.",
                GPIOBehavior.AUDIO_MUTE.value: "Mute or duck station program audio while the EAS alert is on air.",
                GPIOBehavior.DURATION_OF_ALERT.value: "Hold the relay active until the alert finishes.",
                GPIOBehavior.PLAYOUT.value: "Activate while tones and audio playout are running.",
                GPIOBehavior.FLASH.value: "Blink the pin rapidly at the start of the alert to drive strobes.",
                GPIOBehavior.FIVE_SECONDS.value: "Pulse the pin for five seconds when playout begins.",
                GPIOBehavior.INCOMING_ALERT.value: "Pulse when a new alert is ingested or queued.",
                GPIOBehavior.FORWARDING_ALERT.value: "Activate for the full duration of any forwarded broadcast (relay from monitoring inputs).",
                GPIOBehavior.GATE_PENDING.value: "Hold active while one or more alerts are waiting in the Pending Alerts queue (gated-alerts hold-off timer). Assign this to a lamp or buzzer that tells an operator something needs review.",
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
                    "direction": config.direction,
                    "input_action": config.input_action,
                    "input_bounce_ms": config.input_bounce_ms,
                    "input_hold_confirm_seconds": config.input_hold_confirm_seconds,
                }
                for config in configured_pins
            }

            # Only actions implemented end-to-end are offered -- the enum
            # ships complete (Forward/Dump exist as values) so later phases
            # don't need another JSONB-shape touch, but the UI only offers
            # what currently does something.
            input_action_options = [
                {"value": action.value, "label": GPIO_INPUT_ACTION_LABELS[action]}
                for action in GPIO_INPUT_ACTION_IMPLEMENTED
                if action != GPIOInputAction.NONE
            ]

            return render_template(
                "gpio_pin_map.html",
                pin_rows=pin_rows,
                behavior_options=behavior_options,
                pin_config_map=pin_config_map,
                input_action_options=input_action_options,
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
