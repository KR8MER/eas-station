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

"""Diagnostics status, and decoding SoapySDR's error strings."""

import time
from typing import Any

from flask import Flask, jsonify

from app_core.cache import cache
from app_core.models import RadioReceiver

from . import deps
from .serialization import _receiver_to_dict


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    def _decode_soapysdr_error(error_msg: str) -> dict:
        """Decode SoapySDR error codes and provide helpful explanations."""
        if not error_msg:
            return {"code": None, "name": None, "explanation": None, "solutions": []}

        # Extract error code from message like "SoapySDR readStream error: -4"
        import re
        match = re.search(r'error:\s*(-?\d+)', str(error_msg))
        if not match:
            return {"code": None, "name": None, "explanation": error_msg, "solutions": []}

        error_code = int(match.group(1))

        # SoapySDR error code mappings
        error_info = {
            -1: {
                "name": "SOAPY_SDR_TIMEOUT",
                "explanation": "Stream operation timed out",
                "solutions": [
                    "Check that SDR device is properly connected via USB",
                    "Try a different USB port (preferably USB 3.0)",
                    "Check USB cable quality and length",
                    "Reduce sample rate if using high rates",
                    "Check for USB power issues"
                ]
            },
            -2: {
                "name": "SOAPY_SDR_STREAM_ERROR",
                "explanation": "Streaming error occurred",
                "solutions": [
                    "Device may have been disconnected during operation",
                    "USB bandwidth may be insufficient",
                    "Try restarting the receiver",
                    "Check system logs (dmesg) for USB errors"
                ]
            },
            -3: {
                "name": "SOAPY_SDR_CORRUPTION",
                "explanation": "Data corruption detected",
                "solutions": [
                    "USB connection unstable - check cable",
                    "Electromagnetic interference may be present",
                    "Try a shielded USB cable",
                    "Move device away from interference sources"
                ]
            },
            -4: {
                "name": "SOAPY_SDR_OVERFLOW",
                "explanation": "Buffer overflow - system cannot keep up with data rate",
                "solutions": [
                    "Reduce sample rate to lower value",
                    "Close other applications using CPU/USB bandwidth",
                    "Enable hardware flow control if available",
                    "Increase system buffer sizes",
                    "Check for USB controller sharing with other devices"
                ]
            },
            -5: {
                "name": "SOAPY_SDR_NOT_SUPPORTED",
                "explanation": "Operation not supported by this device",
                "solutions": [
                    "Check device capabilities",
                    "Verify driver supports requested operation",
                    "Update SoapySDR and device drivers"
                ]
            },
            -6: {
                "name": "SOAPY_SDR_TIME_ERROR",
                "explanation": "Timing error in stream",
                "solutions": [
                    "Check system time synchronization",
                    "Reduce timing precision requirements"
                ]
            },
            -7: {
                "name": "SOAPY_SDR_NOT_LOCKED",
                "explanation": "PLL not locked - receiver tuner or reference clock not synchronized",
                "solutions": [
                    "Check antenna connection",
                    "Verify tuner frequency is supported",
                    "Check reference clock (if external)",
                    "Try a different frequency"
                ]
            }
        }

        info = error_info.get(error_code, {
            "name": f"UNKNOWN_ERROR_{error_code}",
            "explanation": f"Unknown SoapySDR error code: {error_code}",
            "solutions": [
                "Check SoapySDR documentation",
                "Try restarting the receiver",
                "Check device connection"
            ]
        })

        return {
            "code": error_code,
            "name": info["name"],
            "explanation": info["explanation"],
            "solutions": info["solutions"]
        }

    @app.route("/api/radio/diagnostics/status", methods=["GET"])
    @cache.cached(timeout=2, key_prefix='radio_diagnostics_status')
    def api_radio_diagnostics_status() -> Any:
        """Get comprehensive diagnostic information about RadioManager and receivers.

        Cached for 2 seconds to bound load when multiple admin dashboards
        (admin/radio, audio_monitoring, admin/radio/diagnostics) poll this
        endpoint at 1-2 second intervals.  The 2 s TTL preserves near-live
        status updates while flattening per-viewer database/Redis queries.
        """
        try:
            # Get database receivers
            receivers_db = RadioReceiver.query.all()
            enabled_receivers = [r for r in receivers_db if r.enabled]
            auto_start_receivers = [r for r in enabled_receivers if r.auto_start]

            # In separated architecture, RadioManager runs in SDR hardware service process
            # Read metrics from Redis (published by audio_service.py every 5 seconds)
            available_drivers = []
            loaded_receivers = {}
            redis_radio_manager = None

            try:
                from app_core.redis_client import get_redis_client
                import json

                redis_client = get_redis_client()

                # Read from sdr:metrics key (published by sdr_service.py)
                # Note: This was changed from eas:metrics to match the actual key published by sdr_service.py
                raw_metrics_json = redis_client.get("sdr:metrics")
                raw_metrics = {}

                if raw_metrics_json:
                    import json
                    try:
                        if isinstance(raw_metrics_json, bytes):
                            raw_metrics_json = raw_metrics_json.decode('utf-8')
                        raw_metrics = json.loads(raw_metrics_json)
                    except json.JSONDecodeError as e:
                        route_logger.warning("Failed to decode sdr:metrics JSON: %s", e)

                if raw_metrics:
                    # sdr_service.py publishes metrics directly as JSON
                    redis_radio_manager = raw_metrics

                    # Extract available drivers from receiver configs
                    receivers_data = raw_metrics.get("receivers", {})
                    if receivers_data:
                        available_drivers = list(set(r.get("driver") for r in receivers_data.values() if r.get("driver")))

                    # Convert sdr-service metrics to expected format
                    for identifier, receiver_data in receivers_data.items():
                                # Decode error message if present
                                error_info = _decode_soapysdr_error(receiver_data.get("last_error")) if receiver_data.get("last_error") else None

                                # Look up receiver ID from database
                                receiver_db = RadioReceiver.query.filter_by(identifier=identifier).first()
                                receiver_id = receiver_db.id if receiver_db else None

                                loaded_receivers[identifier] = {
                                    "identifier": identifier,
                                    "receiver_id": receiver_id,
                                    "running": receiver_data.get("running", False),
                                    "locked": receiver_data.get("locked", False),
                                    "signal_strength": receiver_data.get("signal_strength"),
                                    "last_error": receiver_data.get("last_error"),
                                    "error_decoded": error_info,
                                    "reported_at": receiver_data.get("reported_at"),
                                    "samples_available": receiver_data.get("samples_available", False),
                                    "sample_count": receiver_data.get("sample_count", 0),
                                    "config": receiver_data.get("config", {})
                                }

                    route_logger.debug("Loaded radio manager metrics from Redis: %d receivers", len(loaded_receivers))
                else:
                    route_logger.debug("No metrics found in Redis (key: eas:metrics)")

            except Exception as redis_exc:
                route_logger.warning("Could not read metrics from Redis: %s", redis_exc)

            # Get available drivers from database receiver records as fallback
            # (In separated architecture, we can't query RadioManager directly)
            if not available_drivers:
                try:
                    available_drivers = list(set(r.driver for r in receivers_db if r.driver))
                except Exception:
                    available_drivers = []

            # Calculate summary statistics
            running_count = sum(1 for r in loaded_receivers.values() if r['running'])
            locked_count = sum(1 for r in loaded_receivers.values() if r['locked'])
            with_samples_count = sum(1 for r in loaded_receivers.values() if r['samples_available'])

            # Determine overall health status
            if len(loaded_receivers) > 0:
                # We have receiver data (either from Redis or local)
                if locked_count > 0 and with_samples_count > 0:
                    health_status = "healthy"
                    health_message = "Audio pipeline operational"
                elif running_count > 0 and locked_count == 0:
                    health_status = "warning"
                    health_message = "Receivers running but not locked to signal"
                else:
                    health_status = "warning"
                    health_message = "Some receivers may have issues"
            elif len(enabled_receivers) > 0:
                # No receiver data but receivers are configured
                if redis_radio_manager is not None:
                    # We got data from Redis but no receivers - sdr-service may not have started them
                    health_status = "warning"
                    health_message = "SDR service running but no receivers active - check sdr-service logs"
                else:
                    # No Redis data at all - separated architecture, check sdr-service
                    health_status = "info"
                    health_message = "Radio processing handled by SDR hardware service process - check service logs with journalctl"
            else:
                health_status = "info"
                health_message = "No receivers configured"

            return jsonify({
                "timestamp": time.time(),
                "health_status": health_status,
                "health_message": health_message,
                "source": "redis" if redis_radio_manager else "local",
                "database": {
                    "total_receivers": len(receivers_db),
                    "enabled_receivers": len(enabled_receivers),
                    "auto_start_receivers": len(auto_start_receivers),
                    "receivers": [_receiver_to_dict(r) for r in receivers_db]
                },
                "radio_manager": {
                    "available_drivers": available_drivers,
                    "loaded_receiver_count": len(loaded_receivers),
                    "running_receiver_count": running_count,
                    "locked_receiver_count": locked_count,
                    "receivers_with_samples": with_samples_count,
                    "receivers": loaded_receivers
                },
                "summary": {
                    "database_receivers": len(receivers_db),
                    "enabled_receivers": len(enabled_receivers),
                    "auto_start_receivers": len(auto_start_receivers),
                    "loaded_instances": len(loaded_receivers),
                    "running_instances": running_count,
                    "locked_instances": locked_count,
                    "instances_with_samples": with_samples_count
                }
            })

        except Exception as exc:
            route_logger.error("Failed to get diagnostic status: %s", exc, exc_info=True)
            deps._log_radio_event(
                "ERROR",
                f"Failed to get radio diagnostic status: {exc}",
                module_suffix="diagnostics",
                details={"error": str(exc)},
            )
            return jsonify({
                "error": str(exc),
                "health_status": "error",
                "health_message": f"Diagnostic check failed: {exc}"
            }), 500


__all__ = ["register"]
