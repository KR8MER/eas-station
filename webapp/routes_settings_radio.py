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

import io
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, render_template, request, send_file
from sqlalchemy.exc import SQLAlchemyError

from app_core.cache import cache
from app_core.extensions import db, get_radio_manager, get_redis_client
from app_core.location import get_location_settings
from app_core.models import RadioReceiver
from app_core.radio import (
    ensure_radio_tables,
    check_soapysdr_installation,
    get_recommended_settings,
    validate_sample_rate_for_driver,
    SDR_PRESETS,
)
from app_core.radio.service_config import (
    get_service_config,
    validate_frequency,
    format_frequency_display,
    get_frequency_placeholder,
    get_frequency_help_text,
    NOAA_FREQUENCIES,
)
from webapp.admin.audio_ingest import (
    ensure_sdr_audio_monitor_source,
    list_radio_managed_audio_sources,
    remove_radio_managed_audio_source,
    _get_audio_controller,
    _get_icecast_stream_url,
)


_module_logger = logging.getLogger(__name__)


# IQ-capture configuration (mirrors sdr_hardware_service.RADIO_CAPTURE_DIR).
# Captures are produced by the SDR service via the capture_iq command and
# read back here for download. The directory is also the allow-list root
# for path-traversal validation in the download route.
RADIO_CAPTURE_DIR = os.environ.get(
    "RADIO_CAPTURE_DIR", "/var/log/eas-station/captures"
)
# Default capture window in seconds; bounded by the SDR ring buffer (~2 s)
# and the SDR-service-side RADIO_CAPTURE_MAX_SAMPLES cap (8M samples).
RADIO_CAPTURE_DEFAULT_DURATION_SEC = 1.0
RADIO_CAPTURE_MAX_DURATION_SEC = 5.0
# Redis key prefix for capture metadata (path lookup for the download route).
RADIO_CAPTURE_REDIS_PREFIX = "radio:diag:capture:"
RADIO_CAPTURE_REDIS_TTL_SEC = 600


def _is_path_within(child: str, parent: str) -> bool:
    """Return True iff ``child`` resolves to a path under ``parent``.

    Used as a path-traversal guard for the download endpoint: the SDR
    service returns the on-disk path of the capture file, and we only
    serve it if it lives inside RADIO_CAPTURE_DIR.
    """
    try:
        child_abs = os.path.realpath(child)
        parent_abs = os.path.realpath(parent)
        # commonpath raises ValueError on different drives (Windows); on
        # POSIX it's the cheapest containment check available.
        return os.path.commonpath([child_abs, parent_abs]) == parent_abs
    except (ValueError, OSError):
        return False


def _log_radio_event(
    level: str,
    message: str,
    *,
    module_suffix: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist radio UI events to the shared SystemLog table."""

    try:
        manager = get_radio_manager()
    except Exception as exc:  # pragma: no cover - defensive logging
        _module_logger.debug(
            "Unable to acquire RadioManager for log emission: %s", exc, exc_info=True
        )
        return

    module = "radio.ui"
    if module_suffix:
        module = f"{module}.{module_suffix}"

    try:
        manager.log_event(level, message, module=module, details=details)
    except Exception as exc:  # pragma: no cover - defensive logging
        _module_logger.debug(
            "RadioManager.log_event failed for message '%s': %s", message, exc, exc_info=True
        )


def _send_sdr_command(action: str, **kwargs) -> Dict[str, Any]:
    """Send a command to the sdr-service via Redis and wait for response."""
    try:
        redis_client = get_redis_client()
        command_id = str(uuid.uuid4())
        
        command = {
            "action": action,
            "command_id": command_id,
            **kwargs
        }
        
        redis_client.rpush("sdr:commands", json.dumps(command))
        
        # Wait for result (5s timeout)
        start_time = time.time()
        while time.time() - start_time < 5.0:
            result_json = redis_client.get(f"sdr:command_result:{command_id}")
            if result_json:
                return json.loads(result_json)
            time.sleep(0.1)
            
        return {"success": False, "error": "Timeout waiting for sdr-service"}
        
    except Exception as e:
        return {"success": False, "error": str(e)}


def _make_offline_status(last_error: str, **flags) -> Dict[str, Any]:
    """Create a status dict for offline/unavailable receiver states."""
    status = {
        "reported_at": None,
        "locked": False,
        "signal_strength": None,
        "last_error": last_error,
        "capture_mode": None,
        "capture_path": None,
        "samples_available": False,
        "sample_count": 0,
        "running": False,
    }
    status.update(flags)
    return status


def _receiver_to_dict(receiver: RadioReceiver) -> Dict[str, Any]:
    # Try to get latest status, but handle DetachedInstanceError gracefully
    # This can happen if the receiver object is not bound to a session
    try:
        latest = receiver.latest_status()
    except Exception:
        # If we can't access the relationship, just skip the status
        latest = None

    # In separated architecture, status comes from Redis (published by sdr-service)
    # Try to get status from Redis first, fall back to database
    redis_status = None
    redis_available = False
    radio_manager_found = False
    try:
        from app_core.redis_client import get_redis_client
        redis_client = get_redis_client()
        redis_available = True

        # Read sdr-service metrics from Redis (published to sdr:metrics)
        sdr_metrics_json = redis_client.get("sdr:metrics")
        if sdr_metrics_json:
            if isinstance(sdr_metrics_json, bytes):
                sdr_metrics_json = sdr_metrics_json.decode('utf-8')
            radio_manager_data = json.loads(sdr_metrics_json)
            radio_manager_found = True

            # Find this receiver's status in the Redis data
            receivers_data = radio_manager_data.get("receivers", {})
            if receiver.identifier in receivers_data:
                redis_receiver = receivers_data[receiver.identifier]
                redis_status = {
                    "reported_at": redis_receiver.get("reported_at"),
                    "locked": redis_receiver.get("locked", False),
                    "signal_strength": redis_receiver.get("signal_strength"),
                    "last_error": redis_receiver.get("last_error"),
                    "capture_mode": None,  # Not tracked in Redis
                    "capture_path": None,  # Not tracked in Redis
                    "samples_available": redis_receiver.get("samples_available", False),
                    "sample_count": redis_receiver.get("sample_count", 0),
                    "running": redis_receiver.get("running", False),
                }
    except Exception as redis_exc:
        # Redis not available or error parsing - fall back to database status
        _module_logger.debug("Could not read receiver status from Redis: %s", redis_exc)

    # Use Redis status if available (it's more current), otherwise use database status
    if redis_status is not None:
        status_data = redis_status
    elif latest is not None:
        status_data = {
            "reported_at": latest.reported_at.isoformat() if latest.reported_at else None,
            "locked": bool(latest.locked),
            "signal_strength": latest.signal_strength,
            "last_error": latest.last_error,
            "capture_mode": latest.capture_mode,
            "capture_path": latest.capture_path,
            "samples_available": False,  # Database status doesn't track sample buffer
            "sample_count": 0,
            "running": False,  # Database status doesn't track running state
        }
    elif radio_manager_found:
        # Redis has radio_manager metrics but this receiver isn't loaded yet
        status_data = _make_offline_status(
            "Receiver not loaded in audio service",
            not_loaded=True
        )
    elif redis_available:
        # Redis is available but no radio_manager metrics yet (audio-service may not be running)
        status_data = _make_offline_status(
            "Audio service not publishing metrics",
            service_unavailable=True
        )
    else:
        # No status available at all - provide minimal structure
        status_data = _make_offline_status(
            "No status available",
            offline=True
        )

    return {
        "id": receiver.id,
        "identifier": receiver.identifier,
        "display_name": receiver.display_name,
        "driver": receiver.driver,
        "frequency_hz": receiver.frequency_hz,
        "sample_rate": receiver.sample_rate,
        "gain": receiver.gain,
        "channel": receiver.channel,
        "serial": receiver.serial,
        "auto_start": receiver.auto_start,
        "enabled": receiver.enabled,
        "notes": receiver.notes,
        "modulation_type": receiver.modulation_type,
        "audio_output": receiver.audio_output,
        "stereo_enabled": receiver.stereo_enabled,
        "deemphasis_us": receiver.deemphasis_us,
        "enable_rbds": receiver.enable_rbds,
        "squelch_enabled": receiver.squelch_enabled,
        "squelch_threshold_db": receiver.squelch_threshold_db,
        "squelch_open_ms": receiver.squelch_open_ms,
        "squelch_close_ms": receiver.squelch_close_ms,
        "squelch_alarm": receiver.squelch_alarm,
        "latest_status": status_data,
    }


def _parse_receiver_payload(payload: Dict[str, Any], *, partial: bool = False) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse and validate SDR receiver configuration payload.

    Note: Streams are no longer supported via RadioReceiver. Use the AudioSource
    system for stream configuration instead.
    """
    data: Dict[str, Any] = {}

    def _coerce_bool(value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        return bool(value)

    if not partial or "identifier" in payload:
        identifier = str(payload.get("identifier", "")).strip()
        if not identifier:
            return None, "Identifier is required."
        data["identifier"] = identifier

    if not partial or "display_name" in payload:
        display_name = str(payload.get("display_name", "")).strip()
        if not display_name:
            return None, "Display name is required."
        data["display_name"] = display_name

    # Driver is required
    if not partial or "driver" in payload:
        driver = str(payload.get("driver", "")).strip()
        if not driver:
            return None, "Driver is required."
        data["driver"] = driver

    # Frequency is required
    if not partial or "frequency_hz" in payload:
        frequency_val = payload.get("frequency_hz")
        if frequency_val in (None, "", []):
            return None, "Frequency is required."
        try:
            frequency = float(frequency_val)
            if frequency <= 0:
                raise ValueError
            data["frequency_hz"] = frequency
        except Exception:
            return None, "Frequency must be a positive number of hertz."

    # IQ Sample rate is required (this is the SDR hardware rate, e.g., 2.4 MHz)
    if not partial or "sample_rate" in payload:
        sample_rate_val = payload.get("sample_rate")
        if sample_rate_val in (None, "", []):
            return None, "IQ sample rate is required."
        try:
            sample_rate = int(sample_rate_val)
            if sample_rate <= 0:
                raise ValueError
            data["sample_rate"] = sample_rate

            # Validate sample rate compatibility with driver
            if "driver" in data:
                try:
                    # Get serial for hardware-specific validation if available
                    device_args = None
                    if data.get("serial"):
                        device_args = {"serial": data["serial"]}

                    is_valid, error_msg = validate_sample_rate_for_driver(
                        data["driver"], sample_rate, device_args
                    )
                    if not is_valid:
                        return None, error_msg
                except Exception as validation_exc:
                    # If validation fails unexpectedly, log and skip validation
                    _module_logger.warning(
                        f"Sample rate validation failed for {data['driver']}: {validation_exc}",
                        exc_info=True
                    )
                    # Allow the sample rate anyway - hardware validation is not critical

        except ValueError:
            return None, "IQ sample rate must be a positive integer."

    # Audio sample rate (optional) - this is the demodulated audio output rate (e.g., 48 kHz)
    # If not specified, it will be auto-selected based on modulation type
    if "audio_sample_rate" in payload:
        audio_sample_rate_val = payload.get("audio_sample_rate")
        if audio_sample_rate_val in (None, "", []):
            data["audio_sample_rate"] = None  # Will use auto-selection
        else:
            try:
                audio_sample_rate = int(audio_sample_rate_val)
                if audio_sample_rate <= 0:
                    raise ValueError
                # Sanity check: audio rates should be in kHz range (< 100 kHz)
                if audio_sample_rate >= 100000:
                    return None, "Audio sample rate should be in kHz range (e.g., 48000), not MHz range."
                data["audio_sample_rate"] = audio_sample_rate
            except ValueError:
                return None, "Audio sample rate must be a positive integer."

    if "gain" in payload:
        gain = payload.get("gain")
        if gain in (None, "", []):
            data["gain"] = None
        else:
            try:
                data["gain"] = float(gain)
            except Exception:
                return None, "Gain must be numeric."

    if "channel" in payload:
        channel = payload.get("channel")
        if channel in (None, "", []):
            data["channel"] = None
        else:
            try:
                parsed_channel = int(channel)
                if parsed_channel < 0:
                    raise ValueError
                data["channel"] = parsed_channel
            except Exception:
                return None, "Channel must be a non-negative integer."

    if "serial" in payload:
        serial = payload.get("serial")
        data["serial"] = str(serial).strip() if serial not in (None, "") else None

    if not partial or "modulation_type" in payload:
        modulation_raw = payload.get("modulation_type", "IQ")
        _module_logger.debug(f"Processing modulation_type: raw={modulation_raw!r}")
        if modulation_raw in (None, ""):
            if not partial:
                data["modulation_type"] = "IQ"
        else:
            modulation = str(modulation_raw).strip().upper()
            allowed_modulations = {"IQ", "FM", "AM", "NFM", "WFM"}
            if modulation not in allowed_modulations:
                return None, "Invalid modulation type."
            data["modulation_type"] = modulation
            _module_logger.debug(f"Set modulation_type to: {modulation}")

    if not partial or "audio_output" in payload:
        audio_output_raw = payload.get("audio_output")
        audio_output_value = _coerce_bool(audio_output_raw, False)
        _module_logger.debug(f"Processing audio_output: raw={audio_output_raw!r}, coerced={audio_output_value}")
        data["audio_output"] = audio_output_value

    if not partial or "stereo_enabled" in payload:
        data["stereo_enabled"] = _coerce_bool(payload.get("stereo_enabled"), True)

    if not partial or "deemphasis_us" in payload:
        deemphasis_val = payload.get("deemphasis_us", 75.0)
        if deemphasis_val in (None, "", []):
            if not partial:
                data["deemphasis_us"] = 75.0
        else:
            try:
                deemphasis = float(deemphasis_val)
                if deemphasis <= 0:
                    raise ValueError
                data["deemphasis_us"] = deemphasis
            except Exception:
                return None, "De-emphasis must be a positive number of microseconds."

    if not partial or "enable_rbds" in payload:
        data["enable_rbds"] = _coerce_bool(payload.get("enable_rbds"), False)

    if "auto_start" in payload or not partial:
        data["auto_start"] = _coerce_bool(payload.get("auto_start"), True)

    if "enabled" in payload or not partial:
        data["enabled"] = _coerce_bool(payload.get("enabled"), True)

    if not partial or "squelch_enabled" in payload:
        data["squelch_enabled"] = _coerce_bool(payload.get("squelch_enabled"), False)

    if not partial or "squelch_alarm" in payload:
        data["squelch_alarm"] = _coerce_bool(payload.get("squelch_alarm"), False)

    if not partial or "squelch_threshold_db" in payload:
        threshold_val = payload.get("squelch_threshold_db")
        if threshold_val in (None, "", []):
            data["squelch_threshold_db"] = -65.0
        else:
            try:
                parsed_threshold = float(threshold_val)
                if parsed_threshold > 0 or parsed_threshold < -160:
                    raise ValueError
                data["squelch_threshold_db"] = parsed_threshold
            except Exception:
                return None, "Squelch threshold must be between -160 and 0 dBFS."

    if not partial or "squelch_open_ms" in payload:
        open_val = payload.get("squelch_open_ms")
        if open_val in (None, "", []):
            data["squelch_open_ms"] = 150
        else:
            try:
                parsed_open = int(open_val)
                if parsed_open < 0 or parsed_open > 60000:
                    raise ValueError
                data["squelch_open_ms"] = parsed_open
            except Exception:
                return None, "Squelch open delay must be between 0 and 60000 milliseconds."

    if not partial or "squelch_close_ms" in payload:
        close_val = payload.get("squelch_close_ms")
        if close_val in (None, "", []):
            data["squelch_close_ms"] = 750
        else:
            try:
                parsed_close = int(close_val)
                if parsed_close < 0 or parsed_close > 60000:
                    raise ValueError
                data["squelch_close_ms"] = parsed_close
            except Exception:
                return None, "Squelch hang time must be between 0 and 60000 milliseconds."

    if "notes" in payload:
        notes = payload.get("notes")
        data["notes"] = str(notes).strip() if notes not in (None, "") else None

    return data, None


def _sync_radio_manager_state(route_logger) -> Dict[str, Any]:
    """Reload radio manager configuration after CRUD operations."""

    summary: Dict[str, Any] = {
        "configured": 0,
        "auto_started": [],
        "errors": [],
    }
    
    enabled_receivers = RadioReceiver.query.filter_by(enabled=True).all()
    summary["configured"] = len(enabled_receivers)

    # CRITICAL: In separated architecture, tell sdr-service to reload receivers from database
    # This ensures sdr-service picks up newly created/updated/deleted receivers
    try:
        reload_result = _send_sdr_command("reload_receivers")
        if reload_result.get("success"):
            route_logger.info(
                "SDR service reloaded: %d receivers configured, %d started",
                reload_result.get("receivers_configured", 0),
                reload_result.get("receivers_started", 0)
            )
            # Only report actually started receivers, not just those with auto_start flag
            started_count = reload_result.get("receivers_started", 0)
            if started_count > 0:
                # Get the list of receivers that should have started
                auto_start_receivers = [r.identifier for r in enabled_receivers if r.auto_start]
                # Truncate to actual started count
                summary["auto_started"] = auto_start_receivers[:started_count]
            else:
                summary["auto_started"] = []
        else:
            error_msg = reload_result.get("error", "Unknown error")
            route_logger.warning("SDR service reload failed: %s", error_msg)
            summary["errors"].append(f"SDR service: {error_msg}")
    except Exception as exc:
        route_logger.error("Failed to communicate with SDR service: %s", exc)
        summary["errors"].append(f"SDR service unreachable: {exc}")
        
        # Fall back to app-side radio manager (for backward compatibility)
        try:
            radio_manager = get_radio_manager()
            radio_manager.configure_from_records(enabled_receivers)

            for receiver in enabled_receivers:
                instance = radio_manager.get_receiver(receiver.identifier)

                if instance is not None and receiver.auto_start:
                    try:
                        instance.start()
                        summary["auto_started"].append(receiver.identifier)
                    except Exception as exc:  # pragma: no cover - hardware specific
                        message = f"Failed to auto-start {receiver.identifier}: {exc}"
                        route_logger.error(message, exc_info=True)
                        summary["errors"].append(message)
                        _log_radio_event(
                            "ERROR",
                            message,
                            module_suffix="sync",
                            details={
                                "identifier": receiver.identifier,
                                "error": str(exc),
                            },
                        )
        except Exception as fallback_exc:
            route_logger.error("Fallback radio manager also failed: %s", fallback_exc)
            summary["errors"].append(str(fallback_exc))

    _sync_audio_monitors(route_logger, enabled_receivers)

    return summary


def _sync_audio_monitors(route_logger, receivers: List[RadioReceiver]) -> None:
    """Ensure each receiver with audio output has an Icecast-backed monitor."""

    active_sources: set[str] = set()

    for receiver in receivers:
        try:
            result = ensure_sdr_audio_monitor_source(
                receiver,
                start_immediately=receiver.auto_start,
                commit=True,
            )
        except Exception as exc:
            route_logger.error(
                "Failed to ensure audio monitor for %s: %s",
                receiver.identifier,
                exc,
                exc_info=True,
            )
            _log_radio_event(
                "ERROR",
                f"Failed to ensure audio monitor for {receiver.identifier}: {exc}",
                module_suffix="audio",
                details={
                    "identifier": receiver.identifier,
                    "error": str(exc),
                },
            )
            continue

        source_name = result.get("source_name")
        if source_name and not result.get("removed"):
            active_sources.add(source_name)

    for config in list_radio_managed_audio_sources():
        if config.name in active_sources:
            continue
        try:
            if remove_radio_managed_audio_source(config.name):
                route_logger.info("Removed inactive SDR audio monitor %s", config.name)
        except Exception as exc:
            route_logger.error(
                "Failed to remove SDR audio monitor %s: %s", config.name, exc, exc_info=True
            )
            _log_radio_event(
                "ERROR",
                f"Failed to remove SDR audio monitor {config.name}: {exc}",
                module_suffix="audio",
                details={
                    "source_name": config.name,
                    "error": str(exc),
                },
            )


def register(app: Flask, logger) -> None:
    route_logger = logger.getChild("routes_settings_radio")

    @app.route("/admin/radio")
    def radio_settings() -> Any:
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("Radio table validation failed: %s", exc)

        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        location_settings = get_location_settings()

        return render_template(
            "admin/radio.html",
            receivers=[_receiver_to_dict(receiver) for receiver in receivers],
            location_settings=location_settings,
        )

    @app.route("/api/radio/receivers", methods=["GET"])
    @cache.cached(timeout=15, key_prefix='receivers_list')
    def api_list_receivers() -> Any:
        ensure_radio_tables(route_logger)
        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        return jsonify({"receivers": [_receiver_to_dict(receiver) for receiver in receivers]})

    @app.route("/api/radio/receivers", methods=["POST"])
    def api_create_receiver() -> Any:
        try:
            ensure_radio_tables(route_logger)
            payload = request.get_json(silent=True) or {}

            route_logger.info(f"Creating new receiver with payload: {payload}")

            data, error = _parse_receiver_payload(payload)
            if error:
                route_logger.error(f"Validation error for new receiver: {error}")
                return jsonify({"error": error}), 400

            existing = RadioReceiver.query.filter_by(identifier=data["identifier"]).first()
            if existing:
                return jsonify({"error": "A receiver with this identifier already exists."}), 400

            receiver = RadioReceiver(**data)
            try:
                db.session.add(receiver)
                db.session.commit()
                receiver_id = receiver.id
            except SQLAlchemyError as exc:
                route_logger.error("Failed to create receiver: %s", exc)
                db.session.rollback()
                _log_radio_event(
                    "ERROR",
                    f"Failed to create receiver {data.get('identifier')}: {exc}",
                    module_suffix="crud",
                    details={
                        "identifier": data.get("identifier"),
                        "error": str(exc),
                    },
                )
                return jsonify({"error": "Failed to save receiver."}), 500

            manager_state = _sync_radio_manager_state(route_logger)

            # Re-query the receiver to ensure it's bound to the session
            receiver = db.session.query(RadioReceiver).filter_by(id=receiver_id).first()
            if not receiver:
                return jsonify({"error": "Receiver not found after creation."}), 404

            # Ensure the receiver is in the current session
            db.session.refresh(receiver)

            # Clear the cached receiver list so it shows updated data
            cache.delete('receivers_list')

            return jsonify({
                "receiver": _receiver_to_dict(receiver),
                "radio_manager": manager_state,
            }), 201

        except Exception as exc:
            # Catch ALL unexpected errors and return JSON instead of HTML
            route_logger.error(f"Unexpected error creating receiver: {exc}", exc_info=True)
            return jsonify({
                "error": f"Unexpected error: {str(exc)}",
                "type": type(exc).__name__
            }), 500

    @app.route("/api/radio/receivers/<int:receiver_id>", methods=["PUT", "PATCH"])
    def api_update_receiver(receiver_id: int) -> Any:
        try:
            ensure_radio_tables(route_logger)
            receiver = RadioReceiver.query.get_or_404(receiver_id)
            payload = request.get_json(silent=True) or {}

            route_logger.info(f"Updating receiver {receiver_id} with payload: {payload}")

            data, error = _parse_receiver_payload(payload, partial=True)
            if error:
                route_logger.error(f"Validation error for receiver {receiver_id}: {error}")
                return jsonify({"error": error}), 400

            if "identifier" in data and data["identifier"] != receiver.identifier:
                conflict = RadioReceiver.query.filter_by(identifier=data["identifier"]).first()
                if conflict and conflict.id != receiver.id:
                    return jsonify({"error": "Another receiver already uses this identifier."}), 400

            # Detect frequency-only changes so we can issue a live retune
            # instead of bouncing the whole audio system.  A change counts as
            # "frequency only" when nothing else (driver, sample rate, gain,
            # modulation, enabled state, identifier, …) is being touched.
            receiver_identifier = receiver.identifier
            old_frequency = receiver.frequency_hz
            new_frequency = data.get("frequency_hz")
            non_freq_keys = {k for k in data.keys() if k != "frequency_hz"}
            frequency_only_change = (
                "frequency_hz" in data
                and not non_freq_keys
                and new_frequency is not None
                and float(new_frequency) != float(old_frequency or 0)
                and bool(receiver.enabled)
            )

            for key, value in data.items():
                setattr(receiver, key, value)

            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                route_logger.error("Failed to update receiver %s: %s", receiver.identifier, exc)
                db.session.rollback()
                _log_radio_event(
                    "ERROR",
                    f"Failed to update receiver {receiver.identifier}: {exc}",
                    module_suffix="crud",
                    details={
                        "identifier": receiver.identifier,
                        "error": str(exc),
                    },
                )
                return jsonify({"error": "Failed to update receiver."}), 500

            # Try a live retune first when only the frequency changed.  If the
            # driver/device cannot retune live, fall back to the full reload.
            manager_state: Optional[Dict[str, Any]] = None
            if frequency_only_change:
                tune_result = _send_sdr_command(
                    "tune_frequency",
                    receiver_id=receiver_identifier,
                    frequency_hz=float(new_frequency),
                )
                if tune_result.get("success"):
                    route_logger.info(
                        "Live retune succeeded for %s: %.6f MHz -> %.6f MHz",
                        receiver_identifier,
                        float(old_frequency or 0) / 1_000_000,
                        float(new_frequency) / 1_000_000,
                    )
                    manager_state = {
                        "configured": 1,
                        "auto_started": [],
                        "errors": [],
                        "live_retune": True,
                    }
                else:
                    route_logger.warning(
                        "Live retune unavailable for %s (%s); falling back to reload",
                        receiver_identifier,
                        tune_result.get("error", "unknown reason"),
                    )

            if manager_state is None:
                manager_state = _sync_radio_manager_state(route_logger)

            # Explicitly re-query with a fresh session query to avoid DetachedInstanceError
            # We use filter_by + first() instead of get() to ensure a fresh query
            receiver = db.session.query(RadioReceiver).filter_by(id=receiver_id).first()
            if not receiver:
                return jsonify({"error": "Receiver not found after update."}), 404

            # Ensure the receiver is in the current session
            db.session.refresh(receiver)

            # Clear the cached receiver list so it shows updated data
            cache.delete('receivers_list')

            return jsonify({
                "receiver": _receiver_to_dict(receiver),
                "radio_manager": manager_state,
            })

        except Exception as exc:
            # Catch ALL unexpected errors and return JSON instead of HTML
            route_logger.error(f"Unexpected error updating receiver {receiver_id}: {exc}", exc_info=True)
            return jsonify({
                "error": f"Unexpected error: {str(exc)}",
                "type": type(exc).__name__
            }), 500

    @app.route("/api/radio/receivers/<int:receiver_id>", methods=["DELETE"])
    def api_delete_receiver(receiver_id: int) -> Any:
        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)

        try:
            db.session.delete(receiver)
            db.session.commit()
        except SQLAlchemyError as exc:
            route_logger.error("Failed to delete receiver %s: %s", receiver.identifier, exc)
            db.session.rollback()
            _log_radio_event(
                "ERROR",
                f"Failed to delete receiver {receiver.identifier}: {exc}",
                module_suffix="crud",
                details={
                    "identifier": receiver.identifier,
                    "error": str(exc),
                },
            )
            return jsonify({"error": "Failed to delete receiver."}), 500

        manager_state = _sync_radio_manager_state(route_logger)

        # Clear the cached receiver list so it shows updated data
        cache.delete('receivers_list')

        return jsonify({"success": True, "radio_manager": manager_state})

    @app.route("/api/radio/receivers/<int:receiver_id>/restart", methods=["POST"])
    def api_restart_receiver(receiver_id: int) -> Any:
        """Restart a receiver to recover from errors.

        This sends a restart command via Redis to SDR hardware service process,
        which has direct access to RadioManager and SDR hardware.
        """
        ensure_radio_tables(route_logger)
        receiver_record = RadioReceiver.query.get_or_404(receiver_id)

        try:
            # Generate unique command ID for tracking
            command_id = str(uuid.uuid4())

            # Get Redis client
            redis_client = get_redis_client()

            # Send restart command to sdr-service
            command = {
                "action": "restart",
                "receiver_id": receiver_record.identifier,
                "command_id": command_id,
            }

            route_logger.info(
                "Sending restart command to sdr-service for receiver %s (command_id=%s)",
                receiver_record.identifier,
                command_id
            )

            redis_client.rpush("sdr:commands", json.dumps(command))

            # Wait for result (with timeout)
            timeout = 10  # seconds
            start_time = time.time()
            result = None

            while time.time() - start_time < timeout:
                result_json = redis_client.get(f"sdr:command_result:{command_id}")
                if result_json:
                    result = json.loads(result_json)
                    break
                time.sleep(0.2)  # Poll every 200ms

            if not result:
                route_logger.error(
                    "Timeout waiting for restart command result (command_id=%s)",
                    command_id
                )
                return jsonify({
                    "error": "Timeout waiting for sdr-service to process restart command",
                    "hint": "Check if sdr-service is running: sudo systemctl status eas-station-sdr.service"
                }), 504

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                route_logger.error(
                    "Failed to restart receiver %s: %s",
                    receiver_record.identifier,
                    error_msg
                )
                _log_radio_event(
                    "ERROR",
                    f"Failed to restart receiver {receiver_record.identifier}: {error_msg}",
                    module_suffix="actions",
                    details={
                        "identifier": receiver_record.identifier,
                        "error": error_msg,
                    },
                )
                return jsonify({
                    "error": f"Failed to restart receiver: {error_msg}"
                }), 500

            # Success!
            receiver_status = result.get("status", {})

            _log_radio_event(
                "INFO",
                f"Restarted receiver {receiver_record.identifier}",
                module_suffix="actions",
                details={
                    "identifier": receiver_record.identifier,
                    "locked": receiver_status.get("locked"),
                    "signal_strength": receiver_status.get("signal_strength"),
                },
            )

            return jsonify({
                "success": True,
                "message": f"Receiver '{receiver_record.display_name}' restarted successfully",
                "status": receiver_status
            })

        except Exception as exc:
            route_logger.error(
                "Failed to send restart command for receiver %s: %s",
                receiver_record.identifier,
                exc,
                exc_info=True
            )
            _log_radio_event(
                "ERROR",
                f"Failed to restart receiver {receiver_record.identifier}: {exc}",
                module_suffix="actions",
                details={
                    "identifier": receiver_record.identifier,
                    "error": str(exc),
                },
            )
            return jsonify({
                "error": f"Failed to restart receiver: {str(exc)}"
            }), 500

    @app.route("/api/radio/receivers/<int:receiver_id>/audio-monitor", methods=["POST"])
    def api_ensure_audio_monitor(receiver_id: int) -> Any:
        """Ensure an SDR audio monitor exists for the receiver and optionally start it."""

        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)
        payload = request.get_json(silent=True) or {}
        start_now = bool(payload.get("start"))

        try:
            result = ensure_sdr_audio_monitor_source(
                receiver,
                start_immediately=start_now,
                commit=True,
            )
        except Exception as exc:
            route_logger.error(
                "Failed to ensure audio monitor for %s: %s",
                receiver.identifier,
                exc,
                exc_info=True,
            )
            _log_radio_event(
                "ERROR",
                f"Failed to ensure audio monitor for {receiver.identifier}: {exc}",
                module_suffix="audio.ensure",
                details={
                    "identifier": receiver.identifier,
                    "error": str(exc),
                },
            )
            return jsonify({"error": "Unable to provision audio monitor."}), 500

        source_name = result.get("source_name")
        controller = None
        adapter = None
        status_value = None
        metadata = None
        icecast_url = None

        try:
            controller = _get_audio_controller()
        except Exception:
            controller = None

        if controller and source_name:
            adapter = controller._sources.get(source_name)
            if adapter is not None:
                status = getattr(adapter, "status", None)
                status_value = status.value if status else None
                metrics = getattr(adapter, "metrics", None)
                metadata = getattr(metrics, "metadata", None)
                icecast_url = _get_icecast_stream_url(source_name)

        response_payload: Dict[str, Any] = {
            "success": True,
            "source_name": source_name,
            "created": bool(result.get("created")),
            "updated": bool(result.get("updated")),
            "removed": bool(result.get("removed")),
            "started": bool(result.get("started")),
            "icecast_started": bool(result.get("icecast_started")),
            "status": status_value,
            "icecast_url": icecast_url,
            "metadata": metadata,
            "receiver_enabled": bool(receiver.enabled),
            "audio_output": bool(receiver.audio_output),
        }

        if start_now:
            response_payload["message"] = (
                "Audio monitor started successfully." if response_payload["started"]
                else "Audio monitor start requested."
            )

        return jsonify(response_payload)

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
            _log_radio_event(
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
            _log_radio_event(
                "ERROR",
                f"Device enumeration failed: {exc}",
                module_suffix="discovery",
                details={"error": str(exc)},
            )
            return jsonify({"error": str(exc), "devices": []}), 500

    @app.route("/api/radio/validate-frequency", methods=["POST"])
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
            _log_radio_event(
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
            _log_radio_event(
                "ERROR",
                f"Failed to get service config for {service_type}: {exc}",
                module_suffix="validation",
                details={
                    "error": str(exc),
                    "service_type": service_type,
                },
            )
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/radio/diagnostics", methods=["GET"])
    def api_radio_diagnostics() -> Any:
        """Check SoapySDR installation status and available drivers."""
        try:
            diagnostics = check_soapysdr_installation()
            return jsonify(diagnostics)
        except Exception as exc:
            route_logger.error("Diagnostics check failed: %s", exc)
            _log_radio_event(
                "ERROR",
                f"Diagnostics check failed: {exc}",
                module_suffix="diagnostics",
                details={"error": str(exc)},
            )
            return jsonify({"error": str(exc), "ready": False}), 500

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
            _log_radio_event(
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

    @app.route("/api/radio/presets", methods=["GET"])
    def api_radio_presets() -> Any:
        """Get preset configurations for common SDR use cases."""
        return jsonify({"presets": SDR_PRESETS})

    @app.route("/api/radio/presets/<preset_key>", methods=["GET"])
    def api_radio_preset(preset_key: str) -> Any:
        """Get a specific preset configuration."""
        preset = SDR_PRESETS.get(preset_key)
        if preset is None:
            return jsonify({"error": f"Preset '{preset_key}' not found"}), 404
        return jsonify({"preset": preset})

    @app.route("/api/radio/waveform/<int:receiver_id>", methods=["GET"])
    def api_radio_waveform(receiver_id: int) -> Any:
        """Get real-time waveform data for a specific receiver."""
        try:
            # Try to import NumPy, but handle gracefully if not available
            try:
                import numpy as np
            except ImportError:
                route_logger.error("NumPy not available for waveform generation")
                _log_radio_event(
                    "ERROR",
                    "NumPy not available for waveform generation",
                    module_suffix="waveform",
                    details={"receiver_id": receiver_id},
                )
                return jsonify({"error": "Waveform feature requires NumPy"}), 503

            receiver = RadioReceiver.query.get_or_404(receiver_id)

            # Check if there's an active audio controller for this receiver
            # For now, return simulated waveform data
            # In a production system, this would connect to the actual audio pipeline

            # Return random waveform data for demonstration
            # Bound the samples parameter to prevent expensive requests
            try:
                num_samples = int(request.args.get('samples', 512))
                num_samples = max(64, min(num_samples, 2048))  # Clamp between 64 and 2048
            except (ValueError, TypeError):
                num_samples = 512  # Default

            # Use correct default based on driver type
            if receiver.sample_rate:
                sample_rate = receiver.sample_rate
            else:
                driver_lower = (receiver.driver or '').lower()
                sample_rate = 2500000 if 'airspy' in driver_lower else 2400000

            # Generate simulated waveform (in production, this would be real audio data)
            waveform = np.random.randn(num_samples) * 0.1  # Small random noise
            # Add a sine wave to make it more interesting
            t = np.arange(num_samples) / sample_rate
            frequency = 1000  # 1kHz tone
            waveform += 0.3 * np.sin(2 * np.pi * frequency * t)

            # Convert to list for JSON serialization
            waveform_data = waveform.tolist()

            return jsonify({
                "receiver_id": receiver_id,
                "identifier": receiver.identifier,
                "display_name": receiver.display_name,
                "sample_rate": sample_rate,
                "num_samples": num_samples,
                "waveform": waveform_data,
                "timestamp": time.time()
            })

        except Exception as exc:
            route_logger.error("Failed to get waveform data for receiver %s: %s", receiver_id, exc)
            _log_radio_event(
                "ERROR",
                f"Failed to get waveform data for receiver {receiver_id}: {exc}",
                module_suffix="waveform",
                details={
                    "receiver_id": receiver_id,
                    "error": str(exc),
                },
            )
            # Don't leak sensitive exception details to client
            return jsonify({"error": "Failed to generate waveform data"}), 500

    @app.route("/api/radio/spectrum/<int:receiver_id>", methods=["GET"])
    @app.route("/api/radio/spectrum/by-identifier/<string:identifier>", methods=["GET"])
    def api_radio_spectrum(receiver_id: int = None, identifier: str = None) -> Any:
        """Get real-time spectrum data for waterfall display.

        Can be accessed by numeric ID or string identifier:
        - /api/radio/spectrum/1
        - /api/radio/spectrum/by-identifier/wxj93

        Spectrum data is published to Redis by the SDR hardware service
        and consumed by the web application for display.
        """
        try:
            # Look up receiver by ID or identifier
            if identifier:
                receiver = RadioReceiver.query.filter_by(identifier=identifier).first()
                if not receiver:
                    return jsonify({
                        "error": f"Receiver '{identifier}' not found",
                        "hint": "Check receiver identifier"
                    }), 404
            else:
                receiver = RadioReceiver.query.get_or_404(receiver_id)

            receiver_identifier = receiver.identifier

            # First, try to get spectrum data from Redis (published by SDR hardware service process)
            try:
                from app_core.redis_client import get_redis_client
                redis_client = get_redis_client()

                # Try to read pre-computed spectrum from Redis
                spectrum_key = f"eas:spectrum:{receiver_identifier}"
                spectrum_raw = redis_client.get(spectrum_key)

                if spectrum_raw:
                    try:
                        if isinstance(spectrum_raw, bytes):
                            spectrum_raw = spectrum_raw.decode('utf-8')
                        spectrum_payload = json.loads(spectrum_raw)

                        # Check if this is an error status from sdr-service
                        status = spectrum_payload.get('status')
                        if status in ('stopped', 'no_samples'):
                            # Return error info but with 200 OK so UI can display it properly
                            return jsonify({
                                "receiver_id": receiver.id,
                                "identifier": receiver_identifier,
                                "display_name": receiver.display_name,
                                "sample_rate": spectrum_payload.get('sample_rate', receiver.sample_rate),
                                "center_frequency": spectrum_payload.get('center_frequency', receiver.frequency_hz),
                                "freq_min": spectrum_payload.get('freq_min', receiver.frequency_hz - (receiver.sample_rate / 2) if receiver.sample_rate else 0),
                                "freq_max": spectrum_payload.get('freq_max', receiver.frequency_hz + (receiver.sample_rate / 2) if receiver.sample_rate else 0),
                                "fft_size": 0,
                                "spectrum": [],
                                "timestamp": spectrum_payload.get('timestamp', time.time()),
                                "source": "redis",
                                "status": status,
                                "error": spectrum_payload.get('error', 'No samples available')
                            })

                        # Return normal spectrum data from Redis
                        return jsonify({
                            "receiver_id": receiver.id,
                            "identifier": receiver_identifier,
                            "display_name": receiver.display_name,
                            "sample_rate": spectrum_payload.get('sample_rate', receiver.sample_rate),
                            "center_frequency": spectrum_payload.get('center_frequency', receiver.frequency_hz),
                            "freq_min": spectrum_payload.get('freq_min', receiver.frequency_hz - (receiver.sample_rate / 2) if receiver.sample_rate else 0),
                            "freq_max": spectrum_payload.get('freq_max', receiver.frequency_hz + (receiver.sample_rate / 2) if receiver.sample_rate else 0),
                            "fft_size": spectrum_payload.get('fft_size', 2048),
                            "spectrum": spectrum_payload.get('spectrum', []),
                            "timestamp": spectrum_payload.get('timestamp', time.time()),
                            "source": "redis",
                            "status": "available",
                            "modulation_type": receiver.modulation_type,
                            "audio_output": receiver.audio_output,
                            "demod_frequency": receiver.frequency_hz  # Frequency being demodulated
                        })
                    except (json.JSONDecodeError, KeyError) as e:
                        route_logger.debug(f"Error parsing spectrum from Redis: {e}")

            except Exception as redis_exc:
                route_logger.debug(f"Could not read spectrum from Redis: {redis_exc}")

            # Fallback: Request spectrum from sdr-service via Redis command queue
            try:
                import numpy as np
            except ImportError:
                route_logger.error("NumPy not available for spectrum generation")
                return jsonify({
                    "error": "Spectrum data not available",
                    "hint": "NumPy is required for spectrum generation"
                }), 503

            try:
                # Generate unique command ID
                command_id = str(uuid.uuid4())

                # Get Redis client for command queue
                redis_client = get_redis_client()

                # Send get_spectrum command to sdr-service
                command = {
                    "action": "get_spectrum",
                    "receiver_id": receiver_identifier,
                    "command_id": command_id,
                    "num_samples": 2048,
                }

                route_logger.debug(
                    "Requesting spectrum from sdr-service for receiver %s (command_id=%s)",
                    receiver_identifier,
                    command_id
                )

                redis_client.rpush("sdr:commands", json.dumps(command))

                # Wait for result (with timeout)
                timeout = 5  # seconds
                start_time = time.time()
                result = None

                while time.time() - start_time < timeout:
                    result_json = redis_client.get(f"sdr:command_result:{command_id}")
                    if result_json:
                        result = json.loads(result_json)
                        break
                    time.sleep(0.1)  # Poll every 100ms

                if not result:
                    route_logger.warning(
                        "Timeout waiting for spectrum data from sdr-service (command_id=%s)",
                        command_id
                    )
                    return jsonify({
                        "error": "Timeout waiting for sdr-service",
                        "hint": "Check if sdr-service is running: sudo systemctl status eas-station-sdr.service"
                    }), 504

                if not result.get("success"):
                    error_msg = result.get("error", "Unknown error")
                    route_logger.debug(
                        "Failed to get spectrum for receiver %s: %s",
                        receiver_identifier,
                        error_msg
                    )
                    return jsonify({
                        "error": "Spectrum data not available",
                        "hint": error_msg
                    }), 503

                # Extract IQ samples from result
                samples_list = result.get("samples", [])
                if not samples_list:
                    return jsonify({
                        "error": "No samples available",
                        "hint": "Receiver may be starting up or not locked to signal"
                    }), 503

                # Convert [real, imag] pairs to complex numpy array
                iq_samples = np.array([complex(s[0], s[1]) for s in samples_list])

                # Compute FFT
                fft_size = min(len(iq_samples), 2048)
                
                # Remove DC offset before FFT computation
                # This is critical for high-powered FM stations where the DC component
                # from the tuner's local oscillator leakage can dominate the spectrum
                # and make everything else look like "garbage" (horizontal lines)
                samples_slice = iq_samples[:fft_size]
                samples_for_fft = samples_slice - np.mean(samples_slice)
                
                window = np.hanning(fft_size)
                windowed = samples_for_fft * window
                fft_result = np.fft.fftshift(np.fft.fft(windowed))

                # Convert to magnitude (dB)
                magnitude = np.abs(fft_result)
                magnitude = np.where(magnitude > 0, magnitude, 1e-10)  # Avoid log(0)
                magnitude_db = 20 * np.log10(magnitude)

                # Normalize to 0-1 range for display
                min_db = magnitude_db.min()
                max_db = magnitude_db.max()
                if max_db > min_db:
                    normalized = (magnitude_db - min_db) / (max_db - min_db)
                else:
                    normalized = np.zeros_like(magnitude_db)

                # Convert to list for JSON
                spectrum_data = normalized.tolist()

                # Calculate frequency bins - use correct default based on driver
                if receiver.sample_rate:
                    sample_rate = receiver.sample_rate
                else:
                    driver_lower = (receiver.driver or '').lower()
                    sample_rate = 2500000 if 'airspy' in driver_lower else 2400000
                freq_min = receiver.frequency_hz - (sample_rate / 2)
                freq_max = receiver.frequency_hz + (sample_rate / 2)

                return jsonify({
                    "receiver_id": receiver.id,
                    "identifier": receiver_identifier,
                    "display_name": receiver.display_name,
                    "sample_rate": sample_rate,
                    "center_frequency": receiver.frequency_hz,
                    "freq_min": freq_min,
                    "freq_max": freq_max,
                    "fft_size": fft_size,
                    "spectrum": spectrum_data,
                    "timestamp": time.time(),
                    "source": "sdr-service",  # Indicate data came from SDR hardware service process
                    "modulation_type": receiver.modulation_type,
                    "audio_output": receiver.audio_output,
                    "demod_frequency": receiver.frequency_hz  # Frequency being demodulated
                })

            except Exception as command_exc:
                route_logger.error(
                    "Failed to get spectrum via command queue: %s",
                    command_exc,
                    exc_info=True
                )
                return jsonify({
                    "error": "Failed to get spectrum data",
                    "hint": "Check sdr-service logs: sudo journalctl -u eas-station-sdr.service -n 50"
                }), 503

        except Exception as exc:
            route_logger.error("Failed to get spectrum data for receiver %s: %s", receiver_id, exc)
            _log_radio_event(
                "ERROR",
                f"Failed to get spectrum data for receiver {receiver_id}: {exc}",
                module_suffix="spectrum",
                details={
                    "receiver_id": receiver_id,
                    "identifier": identifier,
                    "error": str(exc),
                },
            )
            return jsonify({"error": "Failed to generate spectrum data"}), 500

    @app.route("/api/monitoring/radio", methods=["GET"])
    def api_monitoring_radio() -> Any:
        """Get monitoring status for all radio receivers (includes latest status updates)."""
        ensure_radio_tables(route_logger)
        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        return jsonify({"receivers": [_receiver_to_dict(receiver) for receiver in receivers]})

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
            _log_radio_event(
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

    @app.route(
        "/api/radio/diagnostics/capture/<int:receiver_id>", methods=["POST"]
    )
    def api_radio_diagnostics_capture(receiver_id: int) -> Any:
        """Trigger an IQ capture-to-disk for a receiver.

        Sends a ``capture_iq`` command to sdr-service, which writes a
        complex64 ``.npy`` file under ``RADIO_CAPTURE_DIR``. The path is
        stashed in Redis keyed by a new ``capture_id`` so the user can
        download it via GET .../capture/<capture_id>/download.

        Request body (optional JSON):
            duration_sec: float, capture duration in seconds. Bounded by
                ``RADIO_CAPTURE_MAX_DURATION_SEC`` and the SDR ring buffer.
        """
        ensure_radio_tables(route_logger)
        receiver_record = RadioReceiver.query.get_or_404(receiver_id)

        payload = request.get_json(silent=True) or {}
        try:
            duration_sec = float(
                payload.get("duration_sec", RADIO_CAPTURE_DEFAULT_DURATION_SEC)
            )
        except (TypeError, ValueError):
            duration_sec = RADIO_CAPTURE_DEFAULT_DURATION_SEC
        duration_sec = max(0.05, min(duration_sec, RADIO_CAPTURE_MAX_DURATION_SEC))

        effective_rate = receiver_record.sample_rate or 250_000
        num_samples = int(duration_sec * effective_rate)

        try:
            command_id = str(uuid.uuid4())
            redis_client = get_redis_client()

            command = {
                "action": "capture_iq",
                "receiver_id": receiver_record.identifier,
                "command_id": command_id,
                "num_samples": num_samples,
            }

            route_logger.info(
                "Sending capture_iq to sdr-service for receiver %s "
                "(num_samples=%d, command_id=%s)",
                receiver_record.identifier, num_samples, command_id,
            )
            redis_client.rpush("sdr:commands", json.dumps(command))

            # The capture itself is bounded by ring-buffer size so the
            # sdr-service hand-off is sub-second; allow generous slack for
            # disk write on slow storage.
            timeout = 15.0
            start_time = time.time()
            result = None
            while time.time() - start_time < timeout:
                result_json = redis_client.get(
                    f"sdr:command_result:{command_id}"
                )
                if result_json:
                    result = json.loads(result_json)
                    break
                time.sleep(0.1)

            if not result:
                return jsonify({
                    "error": "Timeout waiting for sdr-service to write capture",
                    "hint": (
                        "Check if sdr-service is running: "
                        "sudo systemctl status eas-station-sdr.service"
                    ),
                }), 504

            if not result.get("success"):
                return jsonify({
                    "error": "Capture failed",
                    "hint": result.get("error", "Unknown error"),
                }), 503

            capture_path = result.get("path")
            if not capture_path or not _is_path_within(
                capture_path, RADIO_CAPTURE_DIR
            ):
                # Defence-in-depth: refuse to register a capture whose
                # on-disk path falls outside the allow-list directory.
                route_logger.error(
                    "Rejecting capture with out-of-tree path: %s", capture_path
                )
                return jsonify({
                    "error": "Capture stored at unexpected location",
                }), 500

            capture_id = uuid.uuid4().hex
            metadata = {
                "path": capture_path,
                "filename": result.get("filename"),
                "num_samples": result.get("num_samples"),
                "sample_rate": result.get("sample_rate"),
                "frequency_hz": result.get("frequency_hz"),
                "size_bytes": result.get("size_bytes"),
                "dtype": result.get("dtype", "complex64"),
                "receiver_id": receiver_record.id,
                "receiver_identifier": receiver_record.identifier,
                "created_at": time.time(),
            }
            redis_client.setex(
                f"{RADIO_CAPTURE_REDIS_PREFIX}{capture_id}",
                RADIO_CAPTURE_REDIS_TTL_SEC,
                json.dumps(metadata),
            )

            _log_radio_event(
                "INFO",
                f"IQ capture written for {receiver_record.identifier}: "
                f"{metadata['num_samples']} samples, "
                f"{metadata['size_bytes']} bytes",
                module_suffix="diagnostics",
                details={
                    "receiver_id": receiver_record.id,
                    "capture_id": capture_id,
                    "filename": metadata["filename"],
                },
            )

            return jsonify({
                "capture_id": capture_id,
                "filename": metadata["filename"],
                "num_samples": metadata["num_samples"],
                "sample_rate": metadata["sample_rate"],
                "frequency_hz": metadata["frequency_hz"],
                "size_bytes": metadata["size_bytes"],
                "dtype": metadata["dtype"],
                "expires_in_sec": RADIO_CAPTURE_REDIS_TTL_SEC,
                "download_url": (
                    f"/api/radio/diagnostics/capture/{capture_id}/download"
                ),
            })

        except Exception as exc:
            route_logger.error(
                "Failed to capture IQ for receiver %s: %s",
                receiver_id, exc, exc_info=True,
            )
            return jsonify({
                "error": "Failed to capture IQ samples",
            }), 500

    @app.route(
        "/api/radio/diagnostics/capture/<capture_id>/download", methods=["GET"]
    )
    def api_radio_diagnostics_capture_download(capture_id: str) -> Any:
        """Stream a previously-written IQ capture as a .npy attachment.

        The capture file is deleted after a successful download so the
        capture directory doesn't accumulate stale files on shared hosts.
        """
        # Reject anything that's not a hex UUID — capture IDs we mint are
        # ``uuid.uuid4().hex`` (32 hex chars). This blocks path traversal
        # via the URL segment before we even hit Redis.
        if not capture_id or len(capture_id) > 64 or not all(
            c in "0123456789abcdef" for c in capture_id
        ):
            return jsonify({"error": "Invalid capture id"}), 400

        try:
            redis_client = get_redis_client()
            raw = redis_client.get(f"{RADIO_CAPTURE_REDIS_PREFIX}{capture_id}")
            if not raw:
                return jsonify({
                    "error": "Capture not found or expired",
                }), 404

            metadata = json.loads(raw)
            capture_path = metadata.get("path")
            if not capture_path or not _is_path_within(
                capture_path, RADIO_CAPTURE_DIR
            ):
                # Path-traversal guard: the on-disk path must live inside
                # the allow-list directory. Defends against a tampered
                # Redis value.
                route_logger.error(
                    "Refusing to serve capture %s with out-of-tree path: %s",
                    capture_id, capture_path,
                )
                return jsonify({"error": "Capture path not allowed"}), 400

            if not os.path.isfile(capture_path):
                redis_client.delete(
                    f"{RADIO_CAPTURE_REDIS_PREFIX}{capture_id}"
                )
                return jsonify({
                    "error": "Capture file no longer exists",
                }), 410

            filename = metadata.get("filename") or os.path.basename(
                capture_path
            )

            # Read the file into memory and remove it immediately, then
            # serve from BytesIO. Capture files are bounded by
            # RADIO_CAPTURE_MAX_SAMPLES (~64 MB) so in-memory streaming is
            # acceptable, and it avoids relying on response.call_on_close
            # firing at the right moment to clean up.
            with open(capture_path, "rb") as fh:
                file_bytes = fh.read()
            try:
                os.remove(capture_path)
            except OSError as cleanup_exc:
                route_logger.debug(
                    "Failed to remove capture %s after read: %s",
                    capture_path, cleanup_exc,
                )
            redis_client.delete(
                f"{RADIO_CAPTURE_REDIS_PREFIX}{capture_id}"
            )

            return send_file(
                io.BytesIO(file_bytes),
                mimetype="application/octet-stream",
                as_attachment=True,
                download_name=filename,
            )

        except Exception as exc:
            route_logger.error(
                "Failed to download capture %s: %s",
                capture_id, exc, exc_info=True,
            )
            return jsonify({"error": "Failed to download capture"}), 500

    @app.route("/admin/radio/diagnostics")
    def radio_diagnostics_page() -> Any:
        """Display radio receiver diagnostics page."""
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:
            route_logger.debug("Radio table validation failed: %s", exc)

        return render_template("admin/radio_diagnostics.html")


__all__ = ["register"]
