from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from flask import Flask, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db
from app_core.location import get_location_settings
from app_core.models import RadioReceiver
from app_core.radio import (
    ensure_radio_tables,
    enumerate_devices,
    check_soapysdr_installation,
    get_device_capabilities,
    get_recommended_settings,
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


def _receiver_to_dict(receiver: RadioReceiver) -> Dict[str, Any]:
    latest = receiver.latest_status()
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
        "latest_status": (
            {
                "reported_at": latest.reported_at.isoformat() if latest and latest.reported_at else None,
                "locked": bool(latest.locked) if latest else None,
                "signal_strength": latest.signal_strength if latest else None,
                "last_error": latest.last_error if latest else None,
                "capture_mode": latest.capture_mode if latest else None,
                "capture_path": latest.capture_path if latest else None,
            }
            if latest
            else None
        ),
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

    # Sample rate is required
    if not partial or "sample_rate" in payload:
        sample_rate_val = payload.get("sample_rate")
        if sample_rate_val in (None, "", []):
            return None, "Sample rate is required."
        try:
            sample_rate = int(sample_rate_val)
            if sample_rate <= 0:
                raise ValueError
            data["sample_rate"] = sample_rate
        except Exception:
            return None, "Sample rate must be a positive integer."

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

    if "auto_start" in payload or not partial:
        data["auto_start"] = _coerce_bool(payload.get("auto_start"), True)

    if "enabled" in payload or not partial:
        data["enabled"] = _coerce_bool(payload.get("enabled"), True)

    if "notes" in payload:
        notes = payload.get("notes")
        data["notes"] = str(notes).strip() if notes not in (None, "") else None

    return data, None


def register(app: Flask, logger) -> None:
    route_logger = logger.getChild("routes_settings_radio")

    @app.route("/settings/radio")
    def radio_settings() -> Any:
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:  # pragma: no cover - defensive
            route_logger.debug("Radio table validation failed: %s", exc)

        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        location_settings = get_location_settings()

        return render_template(
            "settings/radio.html",
            receivers=[_receiver_to_dict(receiver) for receiver in receivers],
            location_settings=location_settings,
        )

    @app.route("/api/radio/receivers", methods=["GET"])
    def api_list_receivers() -> Any:
        ensure_radio_tables(route_logger)
        receivers = RadioReceiver.query.order_by(RadioReceiver.display_name.asc(), RadioReceiver.identifier.asc()).all()
        return jsonify({"receivers": [_receiver_to_dict(receiver) for receiver in receivers]})

    @app.route("/api/radio/receivers", methods=["POST"])
    def api_create_receiver() -> Any:
        ensure_radio_tables(route_logger)
        payload = request.get_json(silent=True) or {}
        data, error = _parse_receiver_payload(payload)
        if error:
            return jsonify({"error": error}), 400

        existing = RadioReceiver.query.filter_by(identifier=data["identifier"]).first()
        if existing:
            return jsonify({"error": "A receiver with this identifier already exists."}), 400

        receiver = RadioReceiver(**data)
        try:
            db.session.add(receiver)
            db.session.commit()
        except SQLAlchemyError as exc:
            route_logger.error("Failed to create receiver: %s", exc)
            db.session.rollback()
            return jsonify({"error": "Failed to save receiver."}), 500

        return jsonify({"receiver": _receiver_to_dict(receiver)}), 201

    @app.route("/api/radio/receivers/<int:receiver_id>", methods=["PUT", "PATCH"])
    def api_update_receiver(receiver_id: int) -> Any:
        ensure_radio_tables(route_logger)
        receiver = RadioReceiver.query.get_or_404(receiver_id)
        payload = request.get_json(silent=True) or {}
        data, error = _parse_receiver_payload(payload, partial=True)
        if error:
            return jsonify({"error": error}), 400

        if "identifier" in data and data["identifier"] != receiver.identifier:
            conflict = RadioReceiver.query.filter_by(identifier=data["identifier"]).first()
            if conflict and conflict.id != receiver.id:
                return jsonify({"error": "Another receiver already uses this identifier."}), 400

        for key, value in data.items():
            setattr(receiver, key, value)

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            route_logger.error("Failed to update receiver %s: %s", receiver.identifier, exc)
            db.session.rollback()
            return jsonify({"error": "Failed to update receiver."}), 500

        return jsonify({"receiver": _receiver_to_dict(receiver)})

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
            return jsonify({"error": "Failed to delete receiver."}), 500

        return jsonify({"success": True})

    @app.route("/api/radio/receivers/<int:receiver_id>/restart", methods=["POST"])
    def api_restart_receiver(receiver_id: int) -> Any:
        """Restart a receiver to recover from errors."""
        ensure_radio_tables(route_logger)
        receiver_record = RadioReceiver.query.get_or_404(receiver_id)

        from app_core.extensions import get_radio_manager
        radio_manager = get_radio_manager()

        # Get the receiver instance from RadioManager
        receiver_instance = radio_manager.get_receiver(receiver_record.identifier)

        if not receiver_instance:
            return jsonify({
                "error": f"Receiver '{receiver_record.identifier}' not loaded in RadioManager",
                "hint": "Try restarting the web application to reload receivers"
            }), 404

        try:
            # Stop the receiver
            route_logger.info("Stopping receiver %s for restart", receiver_record.identifier)
            receiver_instance.stop()

            # Start it again
            route_logger.info("Starting receiver %s", receiver_record.identifier)
            receiver_instance.start()

            # Get updated status
            status = receiver_instance.get_status()

            return jsonify({
                "success": True,
                "message": f"Receiver '{receiver_record.display_name}' restarted successfully",
                "status": {
                    "locked": status.locked,
                    "signal_strength": status.signal_strength,
                    "last_error": status.last_error
                }
            })
        except Exception as exc:
            route_logger.error("Failed to restart receiver %s: %s", receiver_record.identifier, exc, exc_info=True)
            return jsonify({
                "error": f"Failed to restart receiver: {str(exc)}"
            }), 500

    @app.route("/api/radio/discover", methods=["GET"])
    def api_discover_devices() -> Any:
        """Enumerate all SoapySDR-compatible devices connected to the system."""
        try:
            devices = enumerate_devices()
            return jsonify({"devices": devices, "count": len(devices)})
        except Exception as exc:
            route_logger.error("Device enumeration failed: %s", exc)
            return jsonify({"error": str(exc), "devices": []}), 500

    @app.route("/api/radio/devices/simple", methods=["GET"])
    def api_list_devices_simple() -> Any:
        """List detected SDR devices in simplified format for dropdown selection."""
        try:
            devices = enumerate_devices()

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
            return jsonify({"error": str(exc), "devices": []}), 500

    @app.route("/api/radio/validate-frequency", methods=["POST"])
    def api_validate_frequency() -> Any:
        """Validate frequency input based on service type."""
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
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/radio/diagnostics", methods=["GET"])
    def api_radio_diagnostics() -> Any:
        """Check SoapySDR installation status and available drivers."""
        try:
            diagnostics = check_soapysdr_installation()
            return jsonify(diagnostics)
        except Exception as exc:
            route_logger.error("Diagnostics check failed: %s", exc)
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

            capabilities = get_device_capabilities(driver, device_args if device_args else None)
            if capabilities is None:
                return jsonify({"error": f"Unable to query capabilities for driver '{driver}'"}), 404

            return jsonify(capabilities)
        except Exception as exc:
            route_logger.error("Failed to query capabilities for driver '%s': %s", driver, exc)
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

            sample_rate = receiver.sample_rate if receiver.sample_rate else 2400000

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
            # Don't leak sensitive exception details to client
            return jsonify({"error": "Failed to generate waveform data"}), 500

    @app.route("/api/radio/spectrum/<int:receiver_id>", methods=["GET"])
    @app.route("/api/radio/spectrum/by-identifier/<string:identifier>", methods=["GET"])
    def api_radio_spectrum(receiver_id: int = None, identifier: str = None) -> Any:
        """Get real-time spectrum data for waterfall display.

        Can be accessed by numeric ID or string identifier:
        - /api/radio/spectrum/1
        - /api/radio/spectrum/by-identifier/wxj93
        """
        try:
            # Try to import NumPy, but handle gracefully if not available
            try:
                import numpy as np
            except ImportError:
                route_logger.error("NumPy not available for spectrum generation")
                return jsonify({"error": "Spectrum feature requires NumPy"}), 503

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

            # Get the radio manager and receiver
            from app_core.extensions import get_radio_manager
            radio_manager = get_radio_manager()
            receiver_instance = radio_manager.get_receiver(receiver.identifier)

            if not receiver_instance:
                route_logger.warning(
                    "Receiver instance not found in RadioManager for identifier=%s (id=%s). "
                    "Available receivers: %s",
                    receiver.identifier,
                    receiver_id,
                    list(radio_manager._receivers.keys())
                )
                return jsonify({
                    "error": "Receiver not running",
                    "hint": "Receiver may need to be started or reloaded"
                }), 404

            # Get recent IQ samples
            iq_samples = receiver_instance.get_samples(num_samples=2048)

            if iq_samples is None or len(iq_samples) == 0:
                route_logger.warning(
                    "No samples available from receiver %s (id=%s). Status: %s",
                    receiver.identifier,
                    receiver_id,
                    receiver_instance.get_status()
                )
                return jsonify({
                    "error": "No samples available",
                    "hint": "Receiver may be starting up or not locked to signal"
                }), 503

            # Compute FFT
            fft_size = min(len(iq_samples), 2048)
            window = np.hanning(fft_size)
            windowed = iq_samples[:fft_size] * window
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

            # Calculate frequency bins
            sample_rate = receiver.sample_rate if receiver.sample_rate else 2400000
            freq_min = receiver.frequency_hz - (sample_rate / 2)
            freq_max = receiver.frequency_hz + (sample_rate / 2)

            return jsonify({
                "receiver_id": receiver_id,
                "identifier": receiver.identifier,
                "display_name": receiver.display_name,
                "sample_rate": sample_rate,
                "center_frequency": receiver.frequency_hz,
                "freq_min": freq_min,
                "freq_max": freq_max,
                "fft_size": fft_size,
                "spectrum": spectrum_data,
                "timestamp": time.time()
            })

        except Exception as exc:
            route_logger.error("Failed to get spectrum data for receiver %s: %s", receiver_id, exc)
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
                "name": "SOAPY_SDR_UNDERFLOW",
                "explanation": "Buffer underflow - not enough data provided",
                "solutions": [
                    "Increase buffer size",
                    "Check application performance",
                    "Reduce sample rate"
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
    def api_radio_diagnostics_status() -> Any:
        """Get comprehensive diagnostic information about RadioManager and receivers."""
        try:
            from app_core.extensions import get_radio_manager

            # Get database receivers
            receivers_db = RadioReceiver.query.all()
            enabled_receivers = [r for r in receivers_db if r.enabled]
            auto_start_receivers = [r for r in enabled_receivers if r.auto_start]

            # Get RadioManager status
            radio_manager = get_radio_manager()
            available_drivers = list(radio_manager.available_drivers().keys())

            # Get loaded receiver instances
            loaded_receivers = {}
            if hasattr(radio_manager, '_receivers'):
                for identifier, receiver_instance in radio_manager._receivers.items():
                    status = receiver_instance.get_status()

                    # Decode error message if present
                    error_info = _decode_soapysdr_error(status.last_error) if status.last_error else None

                    # Test sample buffer
                    samples_available = False
                    sample_count = 0
                    if hasattr(receiver_instance, 'get_samples'):
                        try:
                            samples = receiver_instance.get_samples(num_samples=100)
                            if samples is not None:
                                samples_available = True
                                sample_count = len(samples)
                        except Exception as e:
                            route_logger.debug(f"Error getting samples from {identifier}: {e}")

                    # Look up receiver ID from database
                    receiver_db = RadioReceiver.query.filter_by(identifier=identifier).first()
                    receiver_id = receiver_db.id if receiver_db else None

                    loaded_receivers[identifier] = {
                        "identifier": identifier,
                        "receiver_id": receiver_id,
                        "running": receiver_instance._running.is_set() if hasattr(receiver_instance, '_running') else False,
                        "locked": status.locked,
                        "signal_strength": status.signal_strength,
                        "last_error": status.last_error,
                        "error_decoded": error_info,
                        "reported_at": status.reported_at.isoformat() if status.reported_at else None,
                        "samples_available": samples_available,
                        "sample_count": sample_count,
                        "config": {
                            "frequency_hz": receiver_instance.config.frequency_hz,
                            "sample_rate": receiver_instance.config.sample_rate,
                            "driver": receiver_instance.config.driver,
                            "modulation_type": receiver_instance.config.modulation_type,
                        } if hasattr(receiver_instance, 'config') else {}
                    }

            # Calculate summary statistics
            running_count = sum(1 for r in loaded_receivers.values() if r['running'])
            locked_count = sum(1 for r in loaded_receivers.values() if r['locked'])
            with_samples_count = sum(1 for r in loaded_receivers.values() if r['samples_available'])

            # Determine overall health status
            if len(loaded_receivers) == 0 and len(enabled_receivers) > 0:
                health_status = "error"
                health_message = "RadioManager not initialized - restart required"
            elif locked_count > 0 and with_samples_count > 0:
                health_status = "healthy"
                health_message = "Audio pipeline operational"
            elif running_count > 0 and locked_count == 0:
                health_status = "warning"
                health_message = "Receivers running but not locked to signal"
            elif len(enabled_receivers) == 0:
                health_status = "info"
                health_message = "No receivers configured"
            else:
                health_status = "warning"
                health_message = "Some receivers may have issues"

            return jsonify({
                "timestamp": time.time(),
                "health_status": health_status,
                "health_message": health_message,
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
            return jsonify({
                "error": str(exc),
                "health_status": "error",
                "health_message": f"Diagnostic check failed: {exc}"
            }), 500

    @app.route("/settings/radio/diagnostics")
    def radio_diagnostics_page() -> Any:
        """Display radio receiver diagnostics page."""
        try:
            ensure_radio_tables(route_logger)
        except Exception as exc:
            route_logger.debug("Radio table validation failed: %s", exc)

        return render_template("settings/radio_diagnostics.html")


__all__ = ["register"]
