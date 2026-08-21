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

"""Routes for relay interlock (mutual-exclusion) group management.

Kept as its own module rather than growing ``webapp/routes/system_controls.py``
further (already well past the ~400-line modularity guideline) -- follows the
same plain ``register(app, logger)`` convention as its GPIO sibling.
"""

from flask import Flask, jsonify, render_template, request

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.models import RelayInterlockGroup, RelayInterlockMember
from app_utils.gpio import load_gpio_pin_configs_from_db
from app_utils.gpio.pin_types import GPIOInterlockGroup
from webapp.routes.system_controls import _get_oled_enabled_status, _gpio_config_warnings


def _interlock_cross_check_warnings(configured_pins, groups, route_logger):
    """Warn (never block) when interlock members share a hold-triggering behavior.

    Thin wrapper over the shared ``system_controls._gpio_config_warnings()``
    helper, filtered to just the interlock-relevant lines -- an unrelated
    "no pin will key the transmitter" warning doesn't belong on this page.
    """
    runtime_groups = [
        GPIOInterlockGroup(
            name=g.name,
            pins=frozenset(m.pin for m in g.members),
            force_deactivate_conflict=g.force_deactivate_conflict,
        )
        for g in groups
    ]
    all_warnings = _gpio_config_warnings(configured_pins, route_logger, runtime_groups)
    return [w for w in all_warnings if w.startswith("Interlock group ")]


def _group_to_dict_with_pin_names(group: RelayInterlockGroup, pin_names: dict) -> dict:
    data = group.to_dict()
    data["pin_labels"] = [
        f"BCM {pin} — {pin_names.get(pin, 'unconfigured')}" for pin in data["pins"]
    ]
    return data


def register(app: Flask, logger) -> None:
    """Register relay interlock group routes on the Flask application."""

    route_logger = logger.getChild("gpio_interlocks")

    @app.route("/admin/gpio/interlocks")
    @require_permission("gpio.view")
    def gpio_interlocks_page():
        """Render the Relay Interlock Groups management page."""
        oled_enabled = _get_oled_enabled_status()
        configured_pins = load_gpio_pin_configs_from_db(route_logger, oled_enabled=oled_enabled)
        pin_names = {cfg.pin: cfg.name for cfg in configured_pins}
        # Interlocks are an output-relay concept -- input pins (read, not
        # driven) don't belong in the membership picker.
        output_pins = [cfg for cfg in configured_pins if cfg.direction == "output"]

        groups = RelayInterlockGroup.query.order_by(RelayInterlockGroup.name.asc()).all()
        warnings = _interlock_cross_check_warnings(configured_pins, groups, route_logger)

        return render_template(
            "gpio_interlocks.html",
            groups=[_group_to_dict_with_pin_names(g, pin_names) for g in groups],
            available_pins=[{"pin": cfg.pin, "name": cfg.name} for cfg in output_pins],
            warnings=warnings,
        )

    @app.route("/api/gpio/interlocks", methods=["POST"])
    @require_permission("gpio.control")
    def gpio_interlocks_create():
        """Create a new relay interlock group."""
        try:
            data = request.get_json() or {}
            name = (data.get("name") or "").strip()
            pins = data.get("pins") or []
            force_deactivate_conflict = bool(data.get("force_deactivate_conflict", False))

            if not name:
                return jsonify({"success": False, "error": "Group name is required"}), 400
            if len(name) > 100:
                return jsonify({"success": False, "error": "Group name must be 100 characters or fewer"}), 400

            try:
                pins = sorted({int(p) for p in pins})
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "pins must be a list of GPIO pin numbers"}), 400

            if len(pins) < 2:
                return jsonify({"success": False, "error": "An interlock group needs at least 2 member pins"}), 400

            if RelayInterlockGroup.query.filter_by(name=name).first():
                return jsonify({"success": False, "error": f"A group named '{name}' already exists"}), 400

            group = RelayInterlockGroup(
                name=name,
                enabled=True,
                force_deactivate_conflict=force_deactivate_conflict,
            )
            db.session.add(group)
            db.session.flush()
            for pin in pins:
                db.session.add(RelayInterlockMember(group_id=group.id, pin=pin))
            db.session.commit()

            oled_enabled = _get_oled_enabled_status()
            configured_pins = load_gpio_pin_configs_from_db(route_logger, oled_enabled=oled_enabled)
            warnings = _interlock_cross_check_warnings(configured_pins, [group], route_logger)

            route_logger.info("Created relay interlock group %r (pins=%s)", name, pins)
            return jsonify({"success": True, "group": group.to_dict(), "warnings": warnings}), 201
        except Exception as exc:
            db.session.rollback()
            route_logger.error("Failed to create relay interlock group: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/gpio/interlocks/<int:group_id>", methods=["PUT"])
    @require_permission("gpio.control")
    def gpio_interlocks_update(group_id: int):
        """Update an existing relay interlock group."""
        try:
            group = RelayInterlockGroup.query.get_or_404(group_id)
            data = request.get_json() or {}

            if "name" in data:
                name = (data["name"] or "").strip()
                if not name:
                    return jsonify({"success": False, "error": "Group name cannot be empty"}), 400
                if len(name) > 100:
                    return jsonify({"success": False, "error": "Group name must be 100 characters or fewer"}), 400
                existing = RelayInterlockGroup.query.filter_by(name=name).first()
                if existing and existing.id != group_id:
                    return jsonify({"success": False, "error": f"A group named '{name}' already exists"}), 400
                group.name = name

            if "enabled" in data:
                group.enabled = bool(data["enabled"])

            if "force_deactivate_conflict" in data:
                group.force_deactivate_conflict = bool(data["force_deactivate_conflict"])

            if "pins" in data:
                try:
                    pins = sorted({int(p) for p in (data["pins"] or [])})
                except (TypeError, ValueError):
                    return jsonify({"success": False, "error": "pins must be a list of GPIO pin numbers"}), 400
                if len(pins) < 2:
                    return jsonify({"success": False, "error": "An interlock group needs at least 2 member pins"}), 400
                RelayInterlockMember.query.filter_by(group_id=group.id).delete()
                for pin in pins:
                    db.session.add(RelayInterlockMember(group_id=group.id, pin=pin))

            db.session.commit()

            oled_enabled = _get_oled_enabled_status()
            configured_pins = load_gpio_pin_configs_from_db(route_logger, oled_enabled=oled_enabled)
            warnings = _interlock_cross_check_warnings(configured_pins, [group], route_logger)

            route_logger.info("Updated relay interlock group %d (%r)", group_id, group.name)
            return jsonify({"success": True, "group": group.to_dict(), "warnings": warnings})
        except Exception as exc:
            db.session.rollback()
            route_logger.error("Failed to update relay interlock group %d: %s", group_id, exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/gpio/interlocks/<int:group_id>", methods=["DELETE"])
    @require_permission("gpio.control")
    def gpio_interlocks_delete(group_id: int):
        """Delete a relay interlock group."""
        try:
            group = RelayInterlockGroup.query.get_or_404(group_id)
            name = group.name
            db.session.delete(group)
            db.session.commit()
            route_logger.info("Deleted relay interlock group %d (%r)", group_id, name)
            return jsonify({"success": True, "message": f"Interlock group '{name}' deleted."})
        except Exception as exc:
            db.session.rollback()
            route_logger.error("Failed to delete relay interlock group %d: %s", group_id, exc)
            return jsonify({"success": False, "error": str(exc)}), 500
