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

"""Hardware settings management routes."""

import json
import logging
import subprocess
from typing import Any, Dict

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import BadRequest

from app_core.auth.roles import require_permission
from app_core.extensions import db
from app_core.hardware_settings import (
    get_gps_settings,
    get_hardware_settings,
    update_hardware_settings,
    invalidate_hardware_settings_cache,
)
from app_utils.gps_hat import collect_gps_hat_diagnostics
from app_utils.hwsetup_client import (
    HelperError,
    HelperUnavailable,
    call as hwsetup_call,
    is_helper_available,
)
from app_utils.pi_pinout import ARGON_OLED_RESERVED_BCM

logger = logging.getLogger(__name__)

# Create Blueprint for hardware routes
hardware_bp = Blueprint('hardware', __name__)


# Routes are relative to blueprint's url_prefix='/admin'
# e.g., route '/hardware' becomes '/admin/hardware'
@hardware_bp.route('/hardware')
@require_permission('system.configure')
def hardware_settings_page():
    """Display hardware settings configuration page."""
    try:
        settings = get_hardware_settings()

        return render_template(
            'admin/hardware_settings.html',
            settings=settings,
            reserved_gpio_pins=sorted(ARGON_OLED_RESERVED_BCM),
        )
    except Exception as exc:
        logger.error(f"Failed to load hardware settings: {exc}")
        flash(f"Error loading hardware settings: {exc}", "error")
        return redirect(url_for('dashboard.admin'))


@hardware_bp.route('/hardware/gps-hat/diagnostics', methods=['GET'])
@require_permission('system.configure')
def gps_hat_diagnostics():
    """Read-only probe of every GPS HAT prerequisite — RTC chip vs overlay,
    PPS device, gpsd / chrony / package state, ``/boot/firmware/config.txt``
    overlays, and the well-known failure modes (RV-3028 PORF, baud
    mismatch, ``hwclock`` missing on Bookworm, serial-port contention).

    The response is consumed by the "GPS HAT" diagnostic panel in the
    hardware settings UI. No state is modified.
    """
    try:
        gps_settings = get_gps_settings() or {}
        report = collect_gps_hat_diagnostics(
            expected_pps_pin=int(gps_settings.get('pps_gpio_pin', 18) or 18),
            expected_baud=int(gps_settings.get('baudrate', 9600) or 9600),
            logger=logger,
        )
        # Surface helper availability so the UI can show "Run" buttons (when
        # the privileged helper is installed and reachable) versus
        # copy-paste-only mode.
        report["helper"] = {"available": is_helper_available()}
        return jsonify({"ok": True, "report": report})
    except Exception as exc:
        logger.exception("GPS HAT diagnostics probe failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@hardware_bp.route('/hardware/gps-hat/ping', methods=['POST'])
@require_permission('system.configure')
def gps_hat_ping():
    """End-to-end check that the privileged helper daemon is wired up.

    POSTs ``{"message": "..."}`` to the hwsetup helper, returns the
    captured stdout. Useful as an integration test from the UI before
    the real action commits land.
    """
    try:
        body = request.get_json(silent=True) or {}
        message = body.get("message") or "pong"
        if not isinstance(message, str) or len(message) > 256:
            raise BadRequest("message must be a short string")
        result = hwsetup_call("ping", {"message": message}, timeout=2.0)
        return jsonify({
            "ok": True,
            "stdout": result.get("stdout", ""),
            "exit_code": result.get("exit_code"),
        })
    except HelperUnavailable as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "helper_available": False,
        }), 503
    except HelperError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "result": exc.result,
        }), 502
    except Exception as exc:
        logger.exception("hwsetup ping failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@hardware_bp.route('/hardware/gps-hat/seed-rtc', methods=['POST'])
@require_permission('system.configure')
def gps_hat_seed_rtc():
    """Write the (synchronized) system clock back to the RTC.

    Recovery action for two specific failure modes:

    * RV-3028 / DS3231 PORF set after a fresh-out-of-the-box HAT or a
      replaced coin cell — the chip refuses ``RTC_RD_TIME`` until a
      successful ``RTC_SET_TIME`` clears the flag.
    * Routine "I just configured chrony, push my disciplined time back
      to the RTC so cold boots come up correct."

    Body (optional):
        {"force_unsynced": false}

    By default we refuse to run when ``timedatectl`` reports the system
    clock is not NTP/GPS synchronized — writing a wrong time and then
    trusting it on next boot is a footgun. Set ``force_unsynced=true``
    to override (the UI surfaces this as an explicit checkbox).
    """
    try:
        body = request.get_json(silent=True) or {}
        force = bool(body.get("force_unsynced", False))
        result = hwsetup_call(
            "seed_rtc",
            {"force_unsynced": force},
            timeout=15.0,
            raise_on_error=False,
        )
        # Pass through the helper's verdict; the UI renders ok/error/details.
        status = 200 if result.get("ok") else 409
        result_event = result.get("result_event") or {}
        return jsonify({
            "ok": result.get("ok", False),
            "exit_code": result.get("exit_code"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error"),
            "ntp_synchronized": result_event.get("ntp_synchronized"),
            "system_time_iso": result_event.get("system_time_iso"),
            "rtc_time_after": result_event.get("rtc_time_after"),
        }), status
    except HelperUnavailable as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "helper_available": False,
        }), 503
    except Exception as exc:
        logger.exception("hwsetup seed_rtc failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@hardware_bp.route('/hardware/update', methods=['POST'])
@require_permission('system.configure')
def update_hardware():
    """Update hardware settings from form submission."""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        # Parse JSON fields
        if 'gpio_pin_map' in data and isinstance(data['gpio_pin_map'], str):
            try:
                data['gpio_pin_map'] = json.loads(data['gpio_pin_map']) if data['gpio_pin_map'].strip() else {}
            except json.JSONDecodeError as exc:
                raise BadRequest(f"Invalid GPIO pin map JSON: {exc}")

        if 'gpio_behavior_matrix' in data and isinstance(data['gpio_behavior_matrix'], str):
            try:
                data['gpio_behavior_matrix'] = json.loads(data['gpio_behavior_matrix']) if data['gpio_behavior_matrix'].strip() else {}
            except json.JSONDecodeError as exc:
                raise BadRequest(f"Invalid GPIO behavior matrix JSON: {exc}")

        # Convert boolean fields
        # HTML checkboxes are NOT included in form data when unchecked, so for
        # non-JSON form submissions we must explicitly set missing booleans to False.
        bool_fields = [
            'gpio_enabled', 'oled_enabled', 'oled_default_invert',
            'oled_button_active_high', 'screens_auto_start',
            'led_enabled', 'vfd_enabled', 'zigbee_enabled',
            'tower_light_enabled', 'tower_light_alert_buzzer',
            'tower_light_incoming_uses_yellow', 'tower_light_blink_on_alert',
            'neopixel_enabled', 'neopixel_flash_on_alert',
            'gps_enabled', 'gps_use_for_location', 'gps_use_for_time',
        ]
        for field in bool_fields:
            if field in data:
                if isinstance(data[field], str):
                    data[field] = data[field].lower() in ('true', '1', 'yes', 'on')
                else:
                    data[field] = bool(data[field])
            elif not request.is_json:
                # Checkbox was unchecked - explicitly set to False for form submissions
                data[field] = False

        # Convert integer fields
        int_fields = [
            'oled_i2c_bus', 'oled_i2c_address', 'oled_width', 'oled_height',
            'oled_rotate', 'oled_contrast', 'oled_button_gpio',
            'oled_scroll_speed', 'oled_scroll_fps',
            'led_port', 'led_baudrate', 'vfd_baudrate',
            'zigbee_baudrate', 'zigbee_channel',
            'tower_light_baudrate',
            'neopixel_gpio_pin', 'neopixel_num_pixels', 'neopixel_brightness',
            'neopixel_flash_interval_ms',
            'gps_baudrate', 'gps_pps_gpio_pin', 'gps_min_satellites',
        ]
        for field in int_fields:
            if field in data and data[field] is not None:
                if data[field] == '' or data[field] == 'None':
                    data[field] = None
                else:
                    try:
                        val = data[field]
                        # Use base 0 to auto-detect hex (0x), octal (0o), binary (0b) prefixes
                        # This is needed because the I2C address field displays as "0x3c"
                        data[field] = int(val, 0) if isinstance(val, str) else int(val)
                    except (TypeError, ValueError):
                        pass

        # Convert float fields
        float_fields = ['oled_button_hold_seconds']
        for field in float_fields:
            if field in data and data[field] is not None:
                try:
                    data[field] = float(data[field])
                except (TypeError, ValueError):
                    pass

        # Convert NeoPixel color hex strings (#rrggbb) to RGB dicts
        for color_field in ('neopixel_standby_color', 'neopixel_alert_color'):
            if color_field in data and isinstance(data[color_field], str):
                hex_val = data[color_field].lstrip('#')
                if len(hex_val) == 6:
                    try:
                        data[color_field] = {
                            'r': int(hex_val[0:2], 16),
                            'g': int(hex_val[2:4], 16),
                            'b': int(hex_val[4:6], 16),
                        }
                    except ValueError:
                        pass

        # Update settings
        settings = update_hardware_settings(data)
        invalidate_hardware_settings_cache()

        flash("Hardware settings updated successfully! Restart services for changes to take effect.", "success")

        if request.is_json:
            return jsonify({
                "success": True,
                "message": "Hardware settings updated",
                "settings": settings.to_dict(),
            })
        else:
            return redirect(url_for('hardware.hardware_settings_page'))

    except BadRequest as exc:
        logger.warning(f"Bad request updating hardware settings: {exc}")
        if request.is_json:
            return jsonify({"success": False, "error": str(exc)}), 400
        else:
            flash(str(exc), "error")
            return redirect(url_for('hardware.hardware_settings_page'))

    except Exception as exc:
        logger.error(f"Failed to update hardware settings: {exc}")
        db.session.rollback()
        if request.is_json:
            return jsonify({"success": False, "error": str(exc)}), 500
        else:
            flash(f"Error updating hardware settings: {exc}", "error")
            return redirect(url_for('hardware.hardware_settings_page'))


@hardware_bp.route('/hardware/restart-services', methods=['POST'])
@require_permission('system.configure')
def restart_hardware_services():
    """Restart hardware-related services to apply new settings."""
    try:
        # Restart only the hardware service (GPIO, OLED, Zigbee, displays)
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'eas-station-hardware.service'],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            flash("Services restarted successfully! Hardware changes are now active.", "success")
            return jsonify({"success": True, "message": "Services restarted"})
        else:
            error_msg = result.stderr or "Unknown error"
            flash(f"Failed to restart services: {error_msg}", "error")
            return jsonify({"success": False, "error": error_msg}), 500

    except subprocess.TimeoutExpired:
        flash("Service restart timed out - check status manually", "warning")
        return jsonify({"success": False, "error": "Timeout"}), 500
    except Exception as exc:
        logger.error(f"Failed to restart services: {exc}")
        flash(f"Error restarting services: {exc}", "error")
        return jsonify({"success": False, "error": str(exc)}), 500
