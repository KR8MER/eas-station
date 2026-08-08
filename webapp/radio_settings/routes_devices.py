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

"""Discovering hardware and describing what it can do."""

from typing import Any, Dict

from flask import Flask, jsonify, request

from app_core.auth.roles import require_permission
from app_core.radio.service_config import (
    get_service_config,
    validate_frequency,
    format_frequency_display,
    get_frequency_placeholder,
    get_frequency_help_text,
    NOAA_FREQUENCIES,
)

from . import deps
from .sdr_client import _send_sdr_command


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    @app.route("/api/radio/discover", methods=["GET"])
    def api_discover_devices() -> Any:
        """Enumerate all SoapySDR-compatible devices connected to the system."""
        try:
            # Use Redis command to discover devices via sdr-service
            result = _send_sdr_command("discover_devices")
            
            if result.get("success"):
                devices = result.get("devices", [])
                return jsonify({"devices": devices, "count": len(devices)})
            else:
                error = result.get("error", "Unknown error")
                raise ValueError(error)
                
        except Exception as exc:
            route_logger.error("Device enumeration failed: %s", exc)
            deps._log_radio_event(
                "ERROR",
                f"Device enumeration failed: {exc}",
                module_suffix="discovery",
                details={"error": str(exc)},
            )
            return jsonify({"error": str(exc), "devices": []}), 500

    @app.route("/api/radio/devices/simple", methods=["GET"])
    def api_list_devices_simple() -> Any:
        """List detected SDR devices in simplified format for dropdown selection."""
        try:
            # Use Redis command to discover devices via sdr-service
            result = _send_sdr_command("discover_devices")
            
            if not result.get("success"):
                raise ValueError(result.get("error", "Unknown error"))
                
            devices = result.get("devices", [])

            # Simplify device list for dropdown
            simple_devices = []
            for device in devices:
                driver = device.get('driver', 'unknown')
                serial = device.get('serial', '')
                label = device.get('label', '')

                # Create user-friendly label
                if 'rtl' in driver.lower():
                    device_type = 'RTL-SDR'
                elif 'airspy' in driver.lower():
                    device_type = 'Airspy'
                elif 'hackrf' in driver.lower():
                    device_type = 'HackRF'
                else:
                    device_type = driver.upper()

                display_name = f"{device_type}"
                if serial:
                    display_name += f" (S/N: {serial})"
                elif label:
                    display_name += f" ({label})"

                simple_devices.append({
                    'driver': driver,
                    'serial': serial,
                    'display_name': display_name,
                    'value': f"{driver}:{serial}" if serial else driver
                })

            return jsonify({"devices": simple_devices, "count": len(simple_devices)})
        except Exception as exc:
            route_logger.error("Device enumeration failed: %s", exc)
            deps._log_radio_event(
                "ERROR",
                f"Device enumeration failed: {exc}",
                module_suffix="discovery",
                details={"error": str(exc)},
            )
            return jsonify({"error": str(exc), "devices": []}), 500

    @app.route("/api/radio/validate-frequency", methods=["POST"])
    @require_permission('receivers.configure')
    def api_validate_frequency() -> Any:
        """Validate frequency input based on service type."""
        payload: Dict[str, Any] = {}
        service_type = None
        frequency_input = None
        try:
            payload = request.get_json() or {}
            service_type = payload.get('service_type', '').upper()
            frequency_input = payload.get('frequency', '')

            if not service_type or service_type not in ['AM', 'FM', 'NOAA']:
                return jsonify({"error": "Invalid service type"}), 400

            valid, frequency_hz, error_msg = validate_frequency(service_type, frequency_input)

            if valid:
                frequency_display = format_frequency_display(service_type, frequency_hz)
                return jsonify({
                    "valid": True,
                    "frequency_hz": frequency_hz,
                    "frequency_display": frequency_display
                })
            else:
                return jsonify({"valid": False, "error": error_msg}), 400

        except Exception as exc:
            route_logger.error("Frequency validation failed: %s", exc)
            deps._log_radio_event(
                "ERROR",
                f"Frequency validation failed: {exc}",
                module_suffix="validation",
                details={
                    "error": str(exc),
                    "service_type": service_type,
                    "frequency_input": frequency_input,
                },
            )
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/radio/service-config/<service_type>", methods=["GET"])
    def api_get_service_config(service_type: str) -> Any:
        """Get automatic configuration for a service type."""
        try:
            service_type = service_type.upper()
            if service_type not in ['AM', 'FM', 'NOAA']:
                return jsonify({"error": "Invalid service type"}), 400

            # Get config with placeholder frequency
            placeholder_freq = 97.9 if service_type == 'FM' else (162.4 if service_type == 'NOAA' else 0.8)
            config = get_service_config(service_type, placeholder_freq)

            # Add helper info
            config['frequency_placeholder'] = get_frequency_placeholder(service_type)
            config['frequency_help'] = get_frequency_help_text(service_type)

            if service_type == 'NOAA':
                config['valid_frequencies'] = NOAA_FREQUENCIES

            return jsonify(config)
        except Exception as exc:
            route_logger.error("Failed to get service config: %s", exc)
            deps._log_radio_event(
                "ERROR",
                f"Failed to get service config for {service_type}: {exc}",
                module_suffix="validation",
                details={
                    "error": str(exc),
                    "service_type": service_type,
                },
            )
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/radio/capabilities/<driver>", methods=["GET"])
    def api_device_capabilities(driver: str) -> Any:
        """Query capabilities of a specific SDR driver."""
        try:
            # Optional device-specific arguments from query params
            device_args = {}
            if request.args.get("serial"):
                device_args["serial"] = request.args.get("serial")
            if request.args.get("device_id"):
                device_args["device_id"] = request.args.get("device_id")

            # Use Redis command to get capabilities via sdr-service
            result = _send_sdr_command(
                "get_device_capabilities", 
                driver=driver, 
                device_args=device_args if device_args else None
            )
            
            if result.get("success"):
                capabilities = result.get("capabilities")
                if capabilities is None:
                    return jsonify({"error": f"Unable to query capabilities for driver '{driver}'"}), 404
                return jsonify(capabilities)
            else:
                # If sdr-service failed, raise exception to trigger failsafe
                raise ValueError(result.get("error", "Unknown error"))

        except Exception as exc:
            route_logger.error("Failed to query capabilities for driver '%s': %s", driver, exc, exc_info=True)
            deps._log_radio_event(
                "ERROR",
                f"Failed to query capabilities for driver '{driver}': {exc}",
                module_suffix="diagnostics",
                details={
                    "error": str(exc),
                    "driver": driver,
                    "device_args": device_args if 'device_args' in locals() else {},
                },
            )

            # FAILSAFE: Return hardcoded defaults instead of 500 error
            driver_lower = driver.lower()
            if 'airspy' in driver_lower:
                route_logger.info("Returning failsafe Airspy capabilities after error")
                return jsonify({
                    "driver": driver,
                    "hardware_info": {"failsafe": "true", "reason": str(exc)},
                    "num_channels": 1,
                    "sample_rates": [2500000, 10000000],  # Airspy R2 only supports 2.5 and 10 MSPS
                    "bandwidths": [],
                    "gains": {"LNA": {"min": 0, "max": 15, "step": 1}},
                    "frequency_ranges": [{"min": 24000000, "max": 1800000000}],
                    "antennas": ["RX"],
                })
            elif 'rtl' in driver_lower:
                route_logger.info("Returning failsafe RTL-SDR capabilities after error")
                return jsonify({
                    "driver": driver,
                    "hardware_info": {"failsafe": "true", "reason": str(exc)},
                    "num_channels": 1,
                    "sample_rates": [250000, 1024000, 1920000, 2048000, 2400000, 2560000],
                    "bandwidths": [],
                    "gains": {"TUNER": {"min": 0, "max": 49.6, "step": None}},
                    "frequency_ranges": [{"min": 24000000, "max": 1766000000}],
                    "antennas": ["RX"],
                })
            else:
                return jsonify({"error": str(exc)}), 500


__all__ = ["register"]
