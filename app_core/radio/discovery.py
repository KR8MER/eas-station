"""Device discovery and diagnostic utilities for SoapySDR-based receivers."""

from __future__ import annotations

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
            parsed = {
                "index": idx,
                "driver": device_info.get("driver", "unknown"),
                "label": device_info.get("label", f"Device {idx}"),
                "serial": device_info.get("serial", None),
                "manufacturer": device_info.get("manufacturer", None),
                "product": device_info.get("product", None),
                "hardware": device_info.get("hardware", None),
                "device_id": device_info.get("device_id", None),
                "raw_info": dict(device_info),
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
        args = device_args or {}
        args["driver"] = driver

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


__all__ = [
    "enumerate_devices",
    "get_device_capabilities",
    "check_soapysdr_installation",
    "get_recommended_settings",
    "NOAA_WEATHER_FREQUENCIES",
    "SDR_PRESETS",
]
