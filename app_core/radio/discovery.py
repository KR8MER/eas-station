"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Device discovery and diagnostic utilities for SoapySDR-based receivers."""

from typing import Dict, List, Any, Optional
import logging


logger = logging.getLogger(__name__)


# Common frequency presets for NOAA Weather Radio in the United States
NOAA_WEATHER_FREQUENCIES = {
    "162.400": "WX1 - 162.400 MHz",
    "162.425": "WX2 - 162.425 MHz",
    "162.450": "WX3 - 162.450 MHz",
    "162.475": "WX4 - 162.475 MHz",
    "162.500": "WX5 - 162.500 MHz",
    "162.525": "WX6 - 162.525 MHz",
    "162.550": "WX7 - 162.550 MHz",
}


# Common SDR presets
SDR_PRESETS = {
    "noaa_weather_rtlsdr": {
        "name": "NOAA Weather Radio (RTL-SDR)",
        "driver": "rtlsdr",
        "frequency_hz": 162_550_000,  # WX7 - adjust based on your area
        "sample_rate": 2_400_000,
        "gain": 49.6,
        "notes": "Common setup for NOAA Weather Radio monitoring with RTL-SDR dongles",
    },
    "noaa_weather_airspy": {
        "name": "NOAA Weather Radio (Airspy)",
        "driver": "airspy",
        "frequency_hz": 162_550_000,
        "sample_rate": 2_500_000,
        "gain": 21,
        "notes": "Common setup for NOAA Weather Radio monitoring with Airspy receivers",
    },
}


def enumerate_devices() -> List[Dict[str, Any]]:
    """
    Enumerate all SoapySDR-compatible devices connected to the system.

    Returns a list of device dictionaries with information about each discovered SDR.

    Returns:
        List of device info dictionaries, or empty list if SoapySDR is unavailable or no devices found.
    """
    try:
        import SoapySDR  # type: ignore
    except ImportError:
        logger.warning("SoapySDR Python bindings not found. Cannot enumerate devices.")
        return []

    try:
        devices = SoapySDR.Device.enumerate()

        results = []
        for idx, device_info in enumerate(devices):
            # Convert SoapySDRKwargs to dict first (doesn't support .get() method directly)
            device_dict = dict(device_info)
            parsed = {
                "index": idx,
                "driver": device_dict.get("driver", "unknown"),
                "label": device_dict.get("label", f"Device {idx}"),
                "serial": device_dict.get("serial", None),
                "manufacturer": device_dict.get("manufacturer", None),
                "product": device_dict.get("product", None),
                "hardware": device_dict.get("hardware", None),
                "device_id": device_dict.get("device_id", None),
                "raw_info": device_dict,
            }
            results.append(parsed)

        logger.info(f"Enumerated {len(results)} SoapySDR device(s)")
        return results

    except Exception as exc:
        logger.error(f"Failed to enumerate SoapySDR devices: {exc}")
        return []


def get_device_capabilities(driver: str, device_args: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """
    Query the capabilities of a specific SDR device.

    Args:
        driver: SoapySDR driver name (e.g., "rtlsdr", "airspy")
        device_args: Optional device arguments (e.g., {"serial": "12345"})

    Returns:
        Dictionary with device capabilities, or None if query fails.
    """
    try:
        import SoapySDR  # type: ignore
    except ImportError:
        logger.warning("SoapySDR Python bindings not found.")
        return None

    try:
        # Build device args - prioritize serial over device_id to avoid conflicts
        args = {"driver": driver}

        if device_args:
            # If serial is provided, use ONLY serial (don't mix with device_id)
            if "serial" in device_args and device_args["serial"]:
                args["serial"] = device_args["serial"]
            # Use device_id only if no serial is provided
            elif "device_id" in device_args and device_args["device_id"]:
                args["device_id"] = device_args["device_id"]
                args["serial"] = device_args["device_id"]

        device = SoapySDR.Device(args)

        capabilities = {
            "driver": driver,
            "hardware_info": device.getHardwareInfo(),
            "num_channels": device.getNumChannels(SoapySDR.SOAPY_SDR_RX),
            "sample_rates": [],
            "bandwidths": [],
            "gains": {},
            "frequency_ranges": [],
            "antennas": [],
        }

        # Get info for the first RX channel (channel 0)
        if capabilities["num_channels"] > 0:
            channel = 0

            # Sample rates
            try:
                sample_rates = device.listSampleRates(SoapySDR.SOAPY_SDR_RX, channel)
                capabilities["sample_rates"] = [int(sr) for sr in sample_rates]
            except Exception:
                pass

            # Bandwidths
            try:
                bandwidths = device.listBandwidths(SoapySDR.SOAPY_SDR_RX, channel)
                capabilities["bandwidths"] = [int(bw) for bw in bandwidths]
            except Exception:
                pass

            # Gain ranges
            try:
                gain_names = device.listGains(SoapySDR.SOAPY_SDR_RX, channel)
                for gain_name in gain_names:
                    gain_range = device.getGainRange(SoapySDR.SOAPY_SDR_RX, channel, gain_name)
                    capabilities["gains"][gain_name] = {
                        "min": gain_range.minimum(),
                        "max": gain_range.maximum(),
                        "step": gain_range.step() if hasattr(gain_range, 'step') else None,
                    }
            except Exception:
                pass

            # Frequency ranges
            try:
                freq_ranges = device.getFrequencyRange(SoapySDR.SOAPY_SDR_RX, channel)
                capabilities["frequency_ranges"] = [
                    {"min": fr.minimum(), "max": fr.maximum()}
                    for fr in freq_ranges
                ]
            except Exception:
                pass

            # Antennas
            try:
                antennas = device.listAntennas(SoapySDR.SOAPY_SDR_RX, channel)
                capabilities["antennas"] = list(antennas)
            except Exception:
                pass

        # Clean up
        try:
            if hasattr(device, 'unmake'):
                device.unmake()  # type: ignore[attr-defined]
            else:
                device.close()
        except Exception:
            pass

        return capabilities

    except Exception as exc:
        logger.error(f"Failed to query device capabilities for driver '{driver}': {exc}")

        # Return fallback default capabilities based on driver type
        # This allows UI to work even if device is busy/in-use
        driver_lower = driver.lower()

        if 'airspy' in driver_lower:
            logger.info(f"Returning fallback Airspy capabilities (device may be in use)")
            return {
                "driver": driver,
                "hardware_info": {"fallback": "true", "reason": "Device busy or unavailable"},
                "num_channels": 1,
                "sample_rates": [
                    312500, 625000, 1250000,  # Decimated rates
                    2500000, 10000000         # Base rates
                ],
                "bandwidths": [],
                "gains": {"LNA": {"min": 0, "max": 15, "step": 1}},
                "frequency_ranges": [{"min": 24000000, "max": 1800000000}],
                "antennas": ["RX"],
            }
        elif 'rtl' in driver_lower:
            logger.info(f"Returning fallback RTL-SDR capabilities (device may be in use)")
            return {
                "driver": driver,
                "hardware_info": {"fallback": "true", "reason": "Device busy or unavailable"},
                "num_channels": 1,
                "sample_rates": [
                    250000, 1024000, 1536000, 1792000, 1920000,
                    2048000, 2160000, 2400000, 2560000, 2880000, 3200000
                ],
                "bandwidths": [],
                "gains": {"TUNER": {"min": 0, "max": 49.6, "step": None}},
                "frequency_ranges": [{"min": 24000000, "max": 1766000000}],
                "antennas": ["RX"],
            }
        else:
            # For unknown drivers, return None (will trigger 404)
            return None


def check_soapysdr_installation() -> Dict[str, Any]:
    """
    Check if SoapySDR and its dependencies are properly installed.

    Returns:
        Dictionary with installation status and details.
    """
    result = {
        "soapysdr_installed": False,
        "numpy_installed": False,
        "drivers_available": [],
        "total_devices": 0,
        "errors": [],
    }

    # Check SoapySDR
    try:
        import SoapySDR  # type: ignore
        result["soapysdr_installed"] = True
        result["soapysdr_version"] = SoapySDR.getAPIVersion()

        # List available drivers
        try:
            # Get drivers from enumerated devices
            devices = SoapySDR.Device.enumerate()
            # Fix: SoapySDRKwargs objects don't have .get() method - cast to dict first
            drivers = set(dict(device).get("driver", "unknown") for device in devices)
            result["drivers_available"] = sorted(drivers)
            result["total_devices"] = len(devices)
        except Exception as exc:
            result["errors"].append(f"Failed to enumerate devices: {exc}")

    except ImportError as exc:
        result["errors"].append(f"SoapySDR not installed: {exc}")
    except Exception as exc:
        result["errors"].append(f"SoapySDR error: {exc}")

    # Check NumPy
    try:
        import numpy  # type: ignore
        result["numpy_installed"] = True
        result["numpy_version"] = numpy.__version__
    except ImportError as exc:
        result["errors"].append(f"NumPy not installed: {exc}")
    except Exception as exc:
        result["errors"].append(f"NumPy error: {exc}")

    result["ready"] = result["soapysdr_installed"] and result["numpy_installed"]

    return result


def get_recommended_settings(driver: str, use_case: str = "noaa_weather") -> Optional[Dict[str, Any]]:
    """
    Get recommended settings for a specific driver and use case.

    Args:
        driver: SDR driver name (e.g., "rtlsdr", "airspy")
        use_case: Use case identifier (default: "noaa_weather")

    Returns:
        Dictionary with recommended settings, or None if no preset available.
    """
    preset_key = f"{use_case}_{driver}"
    return SDR_PRESETS.get(preset_key, None)


def validate_sample_rate_for_driver(driver: str, sample_rate: int, device_args: Optional[Dict[str, str]] = None) -> tuple[bool, Optional[str]]:
    """
    Validate if a sample rate is compatible with a specific SDR driver.

    Args:
        driver: SDR driver name (e.g., "rtlsdr", "airspy")
        sample_rate: Sample rate in Hz to validate
        device_args: Optional device arguments (e.g., {"serial": "12345"})

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    # Get actual device capabilities
    capabilities = get_device_capabilities(driver, device_args)

    if capabilities is None:
        # Can't query hardware - fall back to known valid rates for common drivers
        return _validate_sample_rate_fallback(driver, sample_rate)

    supported_rates = capabilities.get("sample_rates", [])

    if not supported_rates:
        # Hardware didn't report sample rates - use fallback
        return _validate_sample_rate_fallback(driver, sample_rate)

    # Check if sample rate is in supported list
    if sample_rate in supported_rates:
        return True, None

    # Sample rate not supported - provide helpful error
    sorted_rates = sorted(supported_rates)
    if len(sorted_rates) <= 5:
        rate_list = ", ".join(f"{r/1e6:.3f} MHz" for r in sorted_rates)
    else:
        rate_list = ", ".join(f"{r/1e6:.3f} MHz" for r in sorted_rates[:5]) + f", ... ({len(sorted_rates)} total)"

    return False, f"Sample rate {sample_rate/1e6:.3f} MHz is not supported by {driver}. Supported rates: {rate_list}"


def _validate_sample_rate_fallback(driver: str, sample_rate: int) -> tuple[bool, Optional[str]]:
    """
    Fallback validation using known sample rates for common drivers.
    Used when hardware capabilities cannot be queried.
    """
    driver_lower = driver.lower()

    # AirSpy: Base rates are 2.5 MHz and 10 MHz, with decimation
    if "airspy" in driver_lower:
        airspy_rates = {2500000, 10000000}
        # Add decimated rates
        for base in [2500000, 10000000]:
            for div in [1, 2, 4, 8, 16, 32]:
                airspy_rates.add(base // div)

        if sample_rate in airspy_rates:
            return True, None

        common_rates = sorted([2500000, 1250000, 625000, 312500, 156250], reverse=True)
        rate_list = ", ".join(f"{r/1e6:.3f} MHz" for r in common_rates)
        return False, f"Sample rate {sample_rate/1e6:.3f} MHz is incompatible with AirSpy. Common AirSpy rates: {rate_list}"

    # RTL-SDR: Typically supports 225 kHz to 3.2 MHz
    elif "rtl" in driver_lower:
        if 225000 <= sample_rate <= 3200000:
            return True, None
        return False, f"Sample rate {sample_rate/1e6:.3f} MHz is outside RTL-SDR range (0.225-3.2 MHz). Common: 2.4 MHz, 1.024 MHz"

    # HackRF: 2-20 MHz
    elif "hackrf" in driver_lower:
        if 2000000 <= sample_rate <= 20000000:
            return True, None
        return False, f"Sample rate {sample_rate/1e6:.3f} MHz is outside HackRF range (2-20 MHz)"

    # Unknown driver - allow any rate but warn
    logger.warning(f"Unknown driver '{driver}' - cannot validate sample rate {sample_rate}")
    return True, None


__all__ = [
    "enumerate_devices",
    "get_device_capabilities",
    "check_soapysdr_installation",
    "get_recommended_settings",
    "validate_sample_rate_for_driver",
    "NOAA_WEATHER_FREQUENCIES",
    "SDR_PRESETS",
]
