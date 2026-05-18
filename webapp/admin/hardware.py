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
import shutil
import socket
import subprocess
from datetime import datetime, timezone
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
from app_utils.chrony_parser import (
    parse_chronyc_tracking_csv as _parse_chronyc_tracking_csv,
    parse_chronyc_sources_csv as _parse_chronyc_sources_csv,
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
            expected_source=str(gps_settings.get('gps_source', 'auto') or 'auto'),
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


# Mirror of the helper's _APT_ALLOWLIST. Defense in depth: even if the
# web tier is asked to install something not on this list, we reject it
# before the request reaches the privileged daemon. The helper has the
# final say either way; this just produces a nicer error in the UI.
_GPS_HAT_APT_ALLOWLIST = frozenset({
    "chrony",
    "gpsd",
    "gpsd-clients",
    "pps-tools",
    "util-linux-extra",
    "i2c-tools",
})


@hardware_bp.route('/hardware/gps-hat/apt-install', methods=['POST'])
@require_permission('system.configure')
def gps_hat_apt_install():
    """Install one or more packages from the GPS-HAT-related allowlist.

    Body:
        {"packages": ["chrony", "gpsd", ...], "update_first": true}

    Every package name must appear in :data:`_GPS_HAT_APT_ALLOWLIST` and
    in the helper's ``_APT_ALLOWLIST`` (defense in depth — both lists
    are kept identical by hand). The helper streams ``apt-get update``
    and ``apt-get install`` output; this endpoint collects the streamed
    output into the response. A streaming Server-Sent-Events variant
    can be added later if the install runtimes get long.
    """
    try:
        body = request.get_json(silent=True) or {}
        raw_packages = body.get("packages", [])
        if not isinstance(raw_packages, list) or not raw_packages:
            raise BadRequest("packages must be a non-empty list of strings")
        if len(raw_packages) > len(_GPS_HAT_APT_ALLOWLIST):
            raise BadRequest(
                f"too many packages requested (max {len(_GPS_HAT_APT_ALLOWLIST)})"
            )
        bad: list = []
        for entry in raw_packages:
            if not isinstance(entry, str):
                raise BadRequest("every package name must be a string")
            name = entry.strip()
            if name not in _GPS_HAT_APT_ALLOWLIST:
                bad.append(name)
        if bad:
            return jsonify({
                "ok": False,
                "error": f"packages not in allowlist: {', '.join(bad)}",
                "allowlist": sorted(_GPS_HAT_APT_ALLOWLIST),
            }), 400
        update_first = bool(body.get("update_first", True))

        result = hwsetup_call(
            "apt_install",
            {"packages": raw_packages, "update_first": update_first},
            timeout=720.0,            # apt update + install + dpkg-query verify
            raise_on_error=False,
        )
        result_event = result.get("result_event") or {}
        status = 200 if result.get("ok") else 409
        return jsonify({
            "ok": result.get("ok", False),
            "exit_code": result.get("exit_code"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error"),
            "packages": result_event.get("packages"),
            "installed_state": result_event.get("installed_state"),
        }), status
    except HelperUnavailable as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "helper_available": False,
        }), 503
    except BadRequest:
        raise
    except Exception as exc:
        logger.exception("hwsetup apt_install failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


def _forward_to_helper(action: str, params: Dict[str, Any], *, timeout: float = 30.0):
    """Common wrapper for config-edit endpoints. Returns (json_dict, http_status).

    Delegates *all* security-sensitive validation to the helper itself —
    this layer just shapes the JSON response. The helper's allowlists,
    regexes, and bounds are the actual security boundary; the web tier
    only does enough validation to reject obvious garbage early.
    """
    try:
        result = hwsetup_call(action, params, timeout=timeout, raise_on_error=False)
    except HelperUnavailable as exc:
        return {"ok": False, "error": str(exc), "helper_available": False}, 503
    result_event = result.get("result_event") or {}
    payload = {
        "ok": result.get("ok", False),
        "exit_code": result.get("exit_code"),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "error": result.get("error"),
    }
    # Pass through any fields the action reports beyond the standard set
    # so the UI can render path / changed / backup / requires_reboot etc.
    for key in (
        "path", "changed", "backup", "requires_reboot",
        "devices", "options", "start_daemon", "usbauto",
        "ensure_rtcsync", "ensure_pps_refclock", "pps_device",
        "skipped_directives", "user_already_has",
        "overlay", "params", "action", "duplicates_removed",
    ):
        if key in result_event:
            payload[key] = result_event[key]
    status = 200 if payload["ok"] else 409
    return payload, status


@hardware_bp.route('/hardware/gps-hat/gpsd-config', methods=['POST'])
@require_permission('system.configure')
def gps_hat_gpsd_config():
    """Rewrite /etc/default/gpsd from a tight schema (helper enforces).

    Body: ``{"devices": ["/dev/serial0", "/dev/pps0"],
             "options": "-n -b -s 9600",
             "start_daemon": true, "usbauto": false}``
    """
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        payload, status = _forward_to_helper("gpsd_config_write", body, timeout=10.0)
        return jsonify(payload), status
    except BadRequest:
        raise
    except Exception as exc:
        logger.exception("hwsetup gpsd_config_write failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@hardware_bp.route('/hardware/gps-hat/chrony-config', methods=['POST'])
@require_permission('system.configure')
def gps_hat_chrony_config():
    """Append (or refresh) the eas-station-managed block in chrony.conf.

    Body: ``{"ensure_rtcsync": true, "ensure_pps_refclock": true,
             "pps_device": "/dev/pps0"}``
    """
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        payload, status = _forward_to_helper("chrony_config_ensure", body, timeout=10.0)
        return jsonify(payload), status
    except BadRequest:
        raise
    except Exception as exc:
        logger.exception("hwsetup chrony_config_ensure failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


_GPS_HAT_SYSTEMCTL_UNITS = frozenset({
    "chrony.service",
    "gpsd.service",
    "gpsd.socket",
})

_GPS_HAT_SYSTEMCTL_VERBS = frozenset({
    "start", "stop", "restart",
    "enable", "disable",
    "mask", "unmask",
})


@hardware_bp.route('/hardware/gps-hat/systemctl', methods=['POST'])
@require_permission('system.configure')
def gps_hat_systemctl():
    """Run a single systemctl verb against one of the GPS-HAT-related
    units. The web tier mirrors the helper's allowlists so an
    obviously-wrong request is rejected before it even reaches the
    privileged daemon.

    Body: ``{"unit": "<unit>", "verb": "<verb>", "now": false}``

    Allowed units: chrony.service, gpsd.service, gpsd.socket.
    Allowed verbs: start, stop, restart, enable, disable, mask, unmask.
    ``now`` is only valid with enable / disable / mask / unmask.
    """
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        unit = body.get("unit")
        verb = body.get("verb")
        if unit not in _GPS_HAT_SYSTEMCTL_UNITS:
            return jsonify({
                "ok": False,
                "error": f"unit must be one of: {sorted(_GPS_HAT_SYSTEMCTL_UNITS)}",
            }), 400
        if verb not in _GPS_HAT_SYSTEMCTL_VERBS:
            return jsonify({
                "ok": False,
                "error": f"verb must be one of: {sorted(_GPS_HAT_SYSTEMCTL_VERBS)}",
            }), 400
        now_flag = body.get("now", False)
        if not isinstance(now_flag, bool):
            raise BadRequest("now must be a boolean")

        try:
            result = hwsetup_call(
                "systemctl_action",
                {"unit": unit, "verb": verb, "now": now_flag},
                timeout=45.0,
                raise_on_error=False,
            )
        except HelperUnavailable as exc:
            return jsonify({
                "ok": False,
                "error": str(exc),
                "helper_available": False,
            }), 503

        result_event = result.get("result_event") or {}
        status = 200 if result.get("ok") else 409
        return jsonify({
            "ok": result.get("ok", False),
            "exit_code": result.get("exit_code"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error"),
            "unit": result_event.get("unit", unit),
            "verb": result_event.get("verb", verb),
            "now": result_event.get("now", now_flag),
            "state": result_event.get("state"),
        }), status
    except BadRequest:
        raise
    except Exception as exc:
        logger.exception("hwsetup systemctl_action failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@hardware_bp.route('/hardware/gps-hat/config-txt-overlay', methods=['POST'])
@require_permission('system.configure')
def gps_hat_config_txt_overlay():
    """Idempotently install a single dtoverlay= line in config.txt.

    Body: ``{"overlay": "i2c-rtc", "params": "rv3028,addr=0x52"}`` or
          ``{"overlay": "pps-gpio", "params": "gpiopin=18"}`` or
          ``{"overlay": "disable-bt", "params": ""}``
    """
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        payload, status = _forward_to_helper("config_txt_set_overlay", body, timeout=10.0)
        return jsonify(payload), status
    except BadRequest:
        raise
    except Exception as exc:
        logger.exception("hwsetup config_txt_set_overlay failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@hardware_bp.route('/hardware/gps-hat/source-mode', methods=['POST'])
@require_permission('system.configure')
def gps_hat_source_mode():
    """Set the GPS NMEA source mode from a GPS HAT diagnostic action.

    Body: ``{"gps_source": "auto"|"serial"|"gpsd"}``

    This is intentionally narrow: the full hardware settings form can update
    every hardware field, but the diagnostic panel only needs a one-click way
    to move off direct-serial mode so gpsd can own the UART for chrony's
    SHM+PPS refclock chain. Restarting the hardware service is handled by the
    action runner's follow-up step.
    """
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        src = str(body.get('gps_source', 'gpsd') or 'gpsd').strip().lower()
        if src not in ('auto', 'serial', 'gpsd'):
            raise BadRequest("gps_source must be one of: auto, serial, gpsd")

        settings = update_hardware_settings({'gps_source': src})
        invalidate_hardware_settings_cache()
        return jsonify({
            "ok": True,
            "success": True,
            "gps_source": settings.gps_source,
            "stdout": f"GPS NMEA source set to {settings.gps_source}.\n",
            "requires_restart": True,
        })
    except BadRequest:
        raise
    except Exception as exc:
        logger.exception("gps_hat_source_mode failed")
        db.session.rollback()
        return jsonify({"ok": False, "success": False, "error": str(exc)}), 500


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
            'gps_gpsd_port',
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

        # gps_source is a string enum — clamp to known values so a stale
        # form post or a JSON client cannot store nonsense that the GPS
        # Manager would then refuse to act on.
        if 'gps_source' in data and data['gps_source'] is not None:
            src = str(data['gps_source']).strip().lower()
            if src not in ('auto', 'serial', 'gpsd'):
                src = 'auto'
            data['gps_source'] = src
        if 'gps_gpsd_port' in data and data['gps_gpsd_port'] is not None:
            try:
                p = int(data['gps_gpsd_port'])
            except (TypeError, ValueError):
                p = 2947
            if not (1 <= p <= 65535):
                p = 2947
            data['gps_gpsd_port'] = p

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


# ---------------------------------------------------------------------------
# GPS & Time Dashboard — chrogps-dash style page.
#
# Surfaces the live GPS fix and chrony state on a dedicated page modelled on
# https://w0chp.radio/chrogps-dash/ — System Tracking, Satellite Skyview,
# per-PRN signal levels, Chrony Sources table, Satellite SNR table.  All data
# is read-only; the page is purely observational and reuses the existing
# /api/hardware/gps/status endpoint plus the chrony CSV parsers in
# app_utils.chrony_parser (kept as a pure module so they're testable
# without the Flask stack).
# ---------------------------------------------------------------------------


def _collect_chrony_dashboard_data() -> Dict[str, Any]:
    """Run ``chronyc -c tracking`` and ``chronyc -c sources``, parse both.

    Returns a dict with ``tool_present``, ``tracking_ok``, ``tracking``
    (parsed dict, possibly empty), and ``sources`` (list).  Failures are
    tolerated — the dashboard renders the partial information rather than
    erroring out the whole page.
    """
    out: Dict[str, Any] = {
        "tool_present": shutil.which("chronyc") is not None,
        "tracking_ok": False,
        "tracking": {},
        "sources": [],
    }
    if not out["tool_present"]:
        return out
    try:
        rc = subprocess.run(
            ["chronyc", "-c", "tracking"],
            capture_output=True, text=True, timeout=2.5,
        )
        if rc.returncode == 0 and rc.stdout.strip():
            out["tracking"] = _parse_chronyc_tracking_csv(rc.stdout)
            out["tracking_ok"] = True
    except (subprocess.TimeoutExpired, OSError):
        pass
    try:
        rc = subprocess.run(
            ["chronyc", "-c", "sources"],
            capture_output=True, text=True, timeout=2.5,
        )
        if rc.returncode == 0 and rc.stdout.strip():
            out["sources"] = _parse_chronyc_sources_csv(rc.stdout)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return out


@hardware_bp.route('/gps-dashboard')
@require_permission('system.configure')
def gps_dashboard_page():
    """Render the chrogps-dash style GPS & Time dashboard page.

    The template fetches its live data from
    ``/admin/api/gps-dashboard/data`` and re-polls on a configurable
    interval (3/5/10/30 s).
    """
    try:
        gps_settings = get_gps_settings() or {}
        return render_template(
            'admin/gps_dashboard.html',
            gps_settings=gps_settings,
        )
    except Exception as exc:
        logger.error(f"Failed to load GPS dashboard: {exc}")
        flash(f"Error loading GPS dashboard: {exc}", "error")
        return redirect(url_for('hardware.hardware_settings_page'))


@hardware_bp.route('/api/gps-dashboard/data', methods=['GET'])
@require_permission('system.configure')
def gps_dashboard_data():
    """Aggregate GPS fix + chrony state + host info for the GPS dashboard.

    Composition:
      * ``gps`` — live status from the hardware-service
        ``/api/hardware/gps/status`` endpoint (proxied via
        ``call_hardware_service``).  Falls back to ``{}`` if the
        hardware service is unreachable so the chrony half of the
        dashboard still renders.
      * ``chrony`` — parsed ``chronyc -c tracking`` + ``chronyc -c
        sources`` output; collected locally because chronyc is normally
        installed on the same host as the webapp.
      * ``host`` — hostname/uptime so the header banner can show the
        node identity (chrogps-dash convention).
    """
    # Imported here (rather than at module top) to avoid a circular
    # import: webapp.admin.network → app_core.config → … → admin.__init__
    # which itself imports this module.  This is the documented pattern
    # already used elsewhere in the admin package.
    from webapp.admin.network import call_hardware_service

    # GPS fix from the hardware service.  Tolerant of an unreachable
    # service so the dashboard's chrony half still works during a
    # hardware-service crash or restart.
    try:
        gps_payload = call_hardware_service('/api/hardware/gps/status', method='GET') or {}
        if isinstance(gps_payload, dict) and gps_payload.get('success') is False:
            # call_hardware_service returns {'success': False, ...} on
            # failure; surface a generic error rather than the upstream
            # error string so we don't risk leaking implementation
            # details (paths, internal hostnames) to the browser.
            gps_payload = {"_error": "hardware_service_unavailable"}
    except Exception:  # defensive — must never 500 the dashboard
        # Log the full exception server-side for the operator while
        # returning a generic, fixed string to the client.  Avoids the
        # stack-trace-exposure pattern flagged by CodeQL.
        logger.warning("GPS dashboard: hardware service call failed", exc_info=True)
        gps_payload = {"_error": "hardware_service_unavailable"}

    chrony_payload = _collect_chrony_dashboard_data()

    host_info: Dict[str, Any] = {
        "hostname": socket.gethostname(),
        "now_utc": datetime.now(timezone.utc).isoformat(),
    }

    return jsonify({
        "ok": True,
        "gps": gps_payload,
        "chrony": chrony_payload,
        "host": host_info,
    })


@hardware_bp.route('/api/gps-dashboard/trends', methods=['GET'])
@require_permission('system.configure')
def gps_dashboard_trends():
    """Return the server-side trend ring buffer for the GPS dashboard.

    Proxies ``/api/hardware/gps/trends`` from the hardware service.  A
    ``?window=`` query parameter is forwarded so the hardware service
    can pick the appropriate resolution tier (5 s raw → 1 h buckets);
    the dashboard JS uses this to keep sample count roughly constant
    regardless of the selected window.  The page's normal live polling
    continues to append fresh samples on top of the seeded history.
    """
    # Same lazy import pattern used by gps_dashboard_data() above to
    # avoid a circular import via webapp.admin.network.
    from webapp.admin.network import call_hardware_service

    # Whitelist windows so we never forward arbitrary client-supplied
    # query strings to the internal hardware service.
    _ALLOWED_WINDOWS = ('1h', '6h', '24h', '7d', '30d', '90d')
    window = (request.args.get('window') or '1h').lower()
    if window not in _ALLOWED_WINDOWS:
        window = '1h'
    endpoint = f'/api/hardware/gps/trends?window={window}'

    try:
        payload = call_hardware_service(endpoint, method='GET') or {}
        if isinstance(payload, dict) and payload.get('success') is False:
            payload = {'samples': []}
        if not isinstance(payload, dict) or 'samples' not in payload:
            payload = {'samples': []}
        samples = payload.get('samples')
        if isinstance(samples, list) and len(samples) > 5000:
            payload['samples'] = samples[-5000:]
            payload['truncated'] = True
    except Exception:
        # Mirror the defensive logging used by gps_dashboard_data():
        # log full detail server-side, return a generic empty payload
        # to the client (no stack-trace exposure).
        logger.warning(
            "GPS dashboard: hardware service trends call failed",
            exc_info=True,
        )
        payload = {'samples': []}

    return jsonify(payload)
