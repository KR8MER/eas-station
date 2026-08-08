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

"""Validating and normalising an inbound receiver payload.

One function, deliberately: it is the whole write-side contract for
``POST``/``PUT`` on ``/api/radio/receivers`` — every field's type, range and
cross-field rule in one readable place.
"""

from typing import Any, Dict, Optional, Tuple

from app_core.radio import (
    validate_sample_rate_for_driver,
)

from .deps import _module_logger


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

    if "external_lna_db" in payload:
        lna = payload.get("external_lna_db")
        if lna in (None, "", []):
            data["external_lna_db"] = 0.0
        else:
            try:
                lna_val = float(lna)
            except Exception:
                return None, "External LNA gain must be numeric."
            if lna_val < 0.0:
                return None, "External LNA gain cannot be negative."
            data["external_lna_db"] = lna_val

    if "bias_t_enabled" in payload:
        bias = payload.get("bias_t_enabled")
        if isinstance(bias, str):
            bias = bias.strip().lower() in ("1", "true", "yes", "on")
        data["bias_t_enabled"] = bool(bias)

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


__all__ = [
    "_parse_receiver_payload",
]
