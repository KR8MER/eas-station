"""Radio receiver management primitives for multi-SDR support."""

from .drivers import AirspyReceiver, RTLSDRReceiver, register_builtin_drivers
from .manager import ReceiverInterface, ReceiverConfig, RadioManager, ReceiverStatus
from .schema import ensure_radio_tables, ensure_radio_squelch_columns
from .discovery import (
    enumerate_devices,
    get_device_capabilities,
    check_soapysdr_installation,
    get_recommended_settings,
    NOAA_WEATHER_FREQUENCIES,
    SDR_PRESETS,
)

__all__ = [
    "ReceiverInterface",
    "ReceiverConfig",
    "RadioManager",
    "ReceiverStatus",
    "ensure_radio_tables",
    "ensure_radio_squelch_columns",
    "AirspyReceiver",
    "RTLSDRReceiver",
    "register_builtin_drivers",
    "enumerate_devices",
    "get_device_capabilities",
    "check_soapysdr_installation",
    "get_recommended_settings",
    "NOAA_WEATHER_FREQUENCIES",
    "SDR_PRESETS",
]
