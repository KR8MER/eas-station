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

"""Radio receiver management primitives for multi-SDR support."""

# Driver, manager, and discovery imports require optional system-level
# dependencies (SoapySDR, hardware libs).  Pure-DSP modules such as
# ``demodulation`` must remain importable without them.

try:
    from .drivers import AirspyReceiver, RTLSDRReceiver, register_builtin_drivers
    from .manager import ReceiverInterface, ReceiverConfig, RadioManager, ReceiverStatus
    from .schema import (
        ensure_radio_tables,
        ensure_radio_squelch_columns,
        ensure_radio_audio_sample_rate_column,
        ensure_radio_frequency_correction_column,
    )
    from .discovery import (
        enumerate_devices,
        get_device_capabilities,
        check_soapysdr_installation,
        get_recommended_settings,
        validate_sample_rate_for_driver,
        NOAA_WEATHER_FREQUENCIES,
        SDR_PRESETS,
    )
    _RADIO_DRIVERS_AVAILABLE = True
except ImportError:  # pragma: no cover
    AirspyReceiver = None  # type: ignore[assignment,misc]
    RTLSDRReceiver = None  # type: ignore[assignment,misc]
    register_builtin_drivers = None  # type: ignore[assignment]
    ReceiverInterface = None  # type: ignore[assignment,misc]
    ReceiverConfig = None  # type: ignore[assignment,misc]
    RadioManager = None  # type: ignore[assignment,misc]
    ReceiverStatus = None  # type: ignore[assignment,misc]
    ensure_radio_tables = None  # type: ignore[assignment]
    ensure_radio_squelch_columns = None  # type: ignore[assignment]
    ensure_radio_audio_sample_rate_column = None  # type: ignore[assignment]
    ensure_radio_frequency_correction_column = None  # type: ignore[assignment]
    enumerate_devices = None  # type: ignore[assignment]
    get_device_capabilities = None  # type: ignore[assignment]
    check_soapysdr_installation = None  # type: ignore[assignment]
    get_recommended_settings = None  # type: ignore[assignment]
    validate_sample_rate_for_driver = None  # type: ignore[assignment]
    NOAA_WEATHER_FREQUENCIES = None  # type: ignore[assignment]
    SDR_PRESETS = None  # type: ignore[assignment]
    _RADIO_DRIVERS_AVAILABLE = False

__all__ = [
    "ReceiverInterface",
    "ReceiverConfig",
    "RadioManager",
    "ReceiverStatus",
    "ensure_radio_tables",
    "ensure_radio_squelch_columns",
    "ensure_radio_audio_sample_rate_column",
    "ensure_radio_frequency_correction_column",
    "AirspyReceiver",
    "RTLSDRReceiver",
    "register_builtin_drivers",
    "enumerate_devices",
    "get_device_capabilities",
    "check_soapysdr_installation",
    "get_recommended_settings",
    "validate_sample_rate_for_driver",
    "NOAA_WEATHER_FREQUENCIES",
    "SDR_PRESETS",
]
