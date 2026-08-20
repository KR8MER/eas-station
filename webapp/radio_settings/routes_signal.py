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

"""Live signal views: the audio waveform and the RF spectrum."""

import json
import time
import uuid
from typing import Any

from flask import Flask, jsonify, request

from app_core.config.redis_config import RedisChannels

from app_core.models import RadioReceiver
from app_core.radio.decimation import early_decimation_factor, effective_sample_rate

from . import deps


def _spectrum_axis(payload, receiver) -> dict:
    """Resolve the frequency axis for a spectrum payload.

    The FFT behind every spectrum view is computed on samples taken from
    the ring buffer, which sit *after* the early-decimation stage that
    high-rate SDRs use (see ``app_core.radio.decimation``). The RF span
    those bins cover is therefore the **effective** sample rate wide, not
    the hardware rate stored on the ``RadioReceiver`` row.

    Labelling the axis from ``receiver.sample_rate`` overstated the span
    by the decimation factor -- on a receiver configured for 1.024 MHz
    (decim 4, effective 256 kHz) a normal ~200 kHz-wide FM broadcast
    signal was drawn filling a span labelled 1.024 MHz, making it look
    five times wider than physically possible.

    Prefers the values the SDR service publishes (it knows the live
    decimation factor); falls back to recomputing them from the receiver
    row when an older service build omits them.

    Args:
        payload (dict): Spectrum payload from Redis or the command queue.
        receiver (RadioReceiver): The receiver row, used for fallbacks.

    Returns:
        dict: ``sample_rate``, ``hardware_sample_rate``,
        ``early_decim_factor``, ``center_frequency``, ``freq_min``,
        ``freq_max``. Frequencies are Hz; ``freq_min``/``freq_max`` are
        ``None`` when no centre frequency is known.
    """
    payload = payload or {}
    hardware_rate = receiver.sample_rate or 0

    # The service reports the post-decimation rate; recompute it locally
    # when absent so the axis is right even against an older sdr-service.
    try:
        sample_rate = int(payload.get('sample_rate') or 0)
    except (TypeError, ValueError):
        sample_rate = 0
    if sample_rate <= 0:
        sample_rate = effective_sample_rate(hardware_rate)

    try:
        decim_factor = int(payload.get('early_decim_factor') or 0)
    except (TypeError, ValueError):
        decim_factor = 0
    if decim_factor <= 0:
        decim_factor = early_decimation_factor(hardware_rate)

    centre = payload.get('center_frequency')
    if centre is None:
        centre = receiver.frequency_hz

    freq_min = payload.get('freq_min')
    freq_max = payload.get('freq_max')
    if freq_min is None or freq_max is None:
        if centre is not None and sample_rate > 0:
            half_span = sample_rate / 2.0
            freq_min = centre - half_span
            freq_max = centre + half_span
        else:
            freq_min = freq_max = None

    return {
        'sample_rate': sample_rate,
        'hardware_sample_rate': hardware_rate,
        'early_decim_factor': decim_factor,
        'center_frequency': centre,
        'freq_min': freq_min,
        'freq_max': freq_max,
    }


def register(app: Flask, route_logger) -> None:
    """Attach this module's routes to the app."""
    @app.route("/api/radio/waveform/<int:receiver_id>", methods=["GET"])
    def api_radio_waveform(receiver_id: int) -> Any:
        """Get real-time waveform data for a specific receiver."""
        try:
            # Try to import NumPy, but handle gracefully if not available
            try:
                import numpy as np
            except ImportError:
                route_logger.error("NumPy not available for waveform generation")
                deps._log_radio_event(
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
            deps._log_radio_event(
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

                # Try to read pre-computed spectrum from Redis. Shares
                # RedisChannels.SPECTRUM_PREFIX with sdr_hardware_service.py's
                # publisher -- these used to be two independently hardcoded
                # keys ("eas:spectrum:" here, "sdr:spectrum:" there) that
                # never matched, so this fast path always missed and every
                # request fell through to the slow command-queue fallback
                # below.
                spectrum_key = f"{RedisChannels.SPECTRUM_PREFIX}{receiver_identifier}"
                spectrum_raw = redis_client.get(spectrum_key)

                if spectrum_raw:
                    try:
                        if isinstance(spectrum_raw, bytes):
                            spectrum_raw = spectrum_raw.decode('utf-8')
                        spectrum_payload = json.loads(spectrum_raw)
                        axis = _spectrum_axis(spectrum_payload, receiver)

                        # Check if this is an error status from sdr-service
                        status = spectrum_payload.get('status')
                        if status in ('stopped', 'no_samples'):
                            # Return error info but with 200 OK so UI can display it properly
                            return jsonify({
                                "receiver_id": receiver.id,
                                "identifier": receiver_identifier,
                                "display_name": receiver.display_name,
                                "sample_rate": axis['sample_rate'],
                                "center_frequency": axis['center_frequency'],
                                "freq_min": axis['freq_min'],
                                "freq_max": axis['freq_max'],
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
                            "sample_rate": axis['sample_rate'],
                            "hardware_sample_rate": axis['hardware_sample_rate'],
                            "early_decim_factor": axis['early_decim_factor'],
                            "center_frequency": axis['center_frequency'],
                            "freq_min": axis['freq_min'],
                            "freq_max": axis['freq_max'],
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

                # Calculate frequency bins. These samples came straight
                # from the receiver's ring buffer, so they are already
                # decimated -- the span is the *effective* rate wide.
                # Using the configured hardware rate here drew the axis
                # up to 10x too wide (Airspy 2.5 MHz -> 250 kHz actual).
                if not receiver.sample_rate:
                    driver_lower = (receiver.driver or '').lower()
                    fallback_hw_rate = 2500000 if 'airspy' in driver_lower else 2400000
                else:
                    fallback_hw_rate = receiver.sample_rate
                axis = _spectrum_axis(
                    {
                        'sample_rate': result.get('sample_rate'),
                        'early_decim_factor': result.get('early_decim_factor'),
                        'center_frequency': result.get('center_frequency'),
                    },
                    receiver,
                )
                sample_rate = axis['sample_rate'] or effective_sample_rate(fallback_hw_rate)
                centre_hz = axis['center_frequency']
                if centre_hz is None:
                    centre_hz = receiver.frequency_hz
                if centre_hz is None:
                    # An unconfigured receiver has no axis to draw; the
                    # spectrum bins are still useful to the caller.
                    freq_min = freq_max = None
                else:
                    freq_min = centre_hz - (sample_rate / 2)
                    freq_max = centre_hz + (sample_rate / 2)

                return jsonify({
                    "receiver_id": receiver.id,
                    "identifier": receiver_identifier,
                    "display_name": receiver.display_name,
                    "sample_rate": sample_rate,
                    "hardware_sample_rate": axis['hardware_sample_rate'] or fallback_hw_rate,
                    "early_decim_factor": axis['early_decim_factor'],
                    "center_frequency": centre_hz,
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
            deps._log_radio_event(
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


__all__ = ["register"]
