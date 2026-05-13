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


# Common SDR presets for direct-USB receivers.  RTL-SDR is marked as the
# default — it's the cheapest hardware that decodes the NOAA WX bands
# adequately and is what most operators reach for first.
SDR_PRESETS = {
    "noaa_weather_rtlsdr": {
        "name": "NOAA Weather Radio (RTL-SDR Direct)",
        "driver": "rtlsdr",
        "frequency_hz": 162_550_000,  # WX7 - adjust based on your area
        "sample_rate": 2_400_000,
        "gain": 49.6,
        "notes": "Direct USB connection for RTL-SDR dongles (requires USB passthrough)",
        "default": True,
    },
    "noaa_weather_airspy": {
        "name": "NOAA Weather Radio (Airspy Direct)",
        "driver": "airspy",
        "frequency_hz": 162_550_000,
        "sample_rate": 2_500_000,
        "gain": 21,
        "notes": "Direct USB connection for Airspy receivers (requires USB passthrough)",
    },
}


def enumerate_devices() -> List[Dict[str, Any]]:
    """
    Enumerate all SoapySDR-compatible devices connected to the system.

    Returns a list of device dictionaries with information about each discovered SDR.

    Returns:
        List of device info dictionaries, or empty list if SoapySDR is unavailable or no devices found.
    """
    # Try Python bindings first
    try:
        import SoapySDR  # type: ignore
        results = _enumerate_devices_python(SoapySDR)
        if results:
            return results
        # Python bindings found nothing, try CLI fallback
        logger.info("SoapySDR Python bindings found no devices, trying CLI fallback")
    except ImportError:
        logger.info("SoapySDR Python bindings not found, falling back to CLI tool")

    # CLI fallback - either Python not available or found nothing
    return _enumerate_devices_cli()


def _enumerate_devices_cli() -> List[Dict[str, Any]]:
    """Enumerate devices using SoapySDRUtil command-line tool as fallback."""
    import subprocess
    import shutil
    import os

    results = []
    known_drivers = ["airspy", "rtlsdr", "hackrf", "sdrplay", "bladerf"]

    # Find SoapySDRUtil - check common paths
    soapy_util = shutil.which("SoapySDRUtil")
    if not soapy_util:
        for path in ["/usr/bin/SoapySDRUtil", "/usr/local/bin/SoapySDRUtil"]:
            if os.path.exists(path):
                soapy_util = path
                break

    if not soapy_util:
        logger.warning("SoapySDRUtil command not found in PATH or common locations")
        return []

    logger.debug(f"Using SoapySDRUtil at: {soapy_util}")

    for driver in known_drivers:
        try:
            proc = subprocess.run(
                [soapy_util, f"--find=driver={driver}"],
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "SOAPY_SDR_LOG_LEVEL": "FATAL"}  # Suppress noisy logs
            )

            # Log for debugging
            if "Found device" in proc.stdout:
                logger.info(f"SoapySDRUtil found {driver} device: {proc.stdout.strip()[:200]}")
            else:
                logger.debug(f"SoapySDRUtil {driver}: returncode={proc.returncode}, stdout_len={len(proc.stdout)}")

            if proc.returncode != 0:
                if proc.stderr:
                    logger.debug(f"SoapySDRUtil {driver} error: {proc.stderr[:200]}")
                continue

            # Parse output - each device block starts with "Found device N"
            current_device = {}
            for line in proc.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Found device'):
                    if current_device and current_device.get('serial'):
                        results.append(current_device)
                    current_device = {
                        'index': len(results),
                        'driver': driver,
                        'raw_info': {}
                    }
                elif '=' in line and current_device is not None:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip()
                    current_device['raw_info'][key] = value
                    if key == 'serial':
                        current_device['serial'] = value
                    elif key == 'label':
                        current_device['label'] = value
                    elif key == 'driver':
                        current_device['driver'] = value

            # Don't forget the last device
            if current_device and current_device.get('serial'):
                if 'label' not in current_device:
                    current_device['label'] = f"{driver.upper()} Device"
                results.append(current_device)

        except subprocess.TimeoutExpired:
            logger.warning(f"SoapySDRUtil timed out for driver {driver}")
        except FileNotFoundError:
            logger.warning("SoapySDRUtil command not found")
            break
        except Exception as e:
            logger.debug(f"CLI enumeration failed for {driver}: {e}")

    logger.info(f"Enumerated {len(results)} SoapySDR device(s) via CLI")
    return results


def _enumerate_devices_python(SoapySDR) -> List[Dict[str, Any]]:
    """Enumerate devices using SoapySDR Python bindings."""
    results = []
    seen_serials = set()

    # Try driver-specific enumeration first to avoid issues with
    # problematic modules (e.g., soapysdr-module-remote failing on avahi)
    known_drivers = ["airspy", "rtlsdr", "hackrf", "sdrplay", "bladerf"]

    for driver in known_drivers:
        try:
            driver_devices = SoapySDR.Device.enumerate(f"driver={driver}")
            for device_info in driver_devices:
                device_dict = dict(device_info)
                serial = device_dict.get("serial")
                # Avoid duplicates by serial
                if serial and serial in seen_serials:
                    continue
                if serial:
                    seen_serials.add(serial)

                parsed = {
                    "index": len(results),
                    "driver": device_dict.get("driver", driver),
                    "label": device_dict.get("label", f"Device {len(results)}"),
                    "serial": serial,
                    "manufacturer": device_dict.get("manufacturer", None),
                    "product": device_dict.get("product", None),
                    "hardware": device_dict.get("hardware", None),
                    "device_id": device_dict.get("device_id", None),
                    "raw_info": device_dict,
                }
                results.append(parsed)
                logger.debug(f"Found {driver} device: serial={serial}")
        except Exception as exc:
            # Driver-specific enumeration can fail if driver module has issues
            logger.debug(f"Driver-specific enumeration for {driver} failed: {exc}")

    # If driver-specific found nothing, try general enumeration as fallback
    if not results:
        try:
            devices = SoapySDR.Device.enumerate()
            for idx, device_info in enumerate(devices):
                device_dict = dict(device_info)
                serial = device_dict.get("serial")
                if serial and serial in seen_serials:
                    continue
                if serial:
                    seen_serials.add(serial)

                parsed = {
                    "index": len(results),
                    "driver": device_dict.get("driver", "unknown"),
                    "label": device_dict.get("label", f"Device {len(results)}"),
                    "serial": serial,
                    "manufacturer": device_dict.get("manufacturer", None),
                    "product": device_dict.get("product", None),
                    "hardware": device_dict.get("hardware", None),
                    "device_id": device_dict.get("device_id", None),
                    "raw_info": device_dict,
                }
                results.append(parsed)
        except Exception as exc:
            # General enumeration can fail if ANY module has issues
            logger.warning(f"General SoapySDR enumeration failed (some modules may have issues): {exc}")

    logger.info(f"Enumerated {len(results)} SoapySDR device(s)")
    return results


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
            except Exception as exc:
                logger.debug("Driver '%s' does not expose sample rates: %s", driver, exc)

            # Bandwidths
            try:
                bandwidths = device.listBandwidths(SoapySDR.SOAPY_SDR_RX, channel)
                capabilities["bandwidths"] = [int(bw) for bw in bandwidths]
            except Exception as exc:
                logger.debug("Driver '%s' does not expose bandwidths: %s", driver, exc)

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
            except Exception as exc:
                logger.debug("Driver '%s' does not expose gain ranges: %s", driver, exc)

            # Frequency ranges
            try:
                freq_ranges = device.getFrequencyRange(SoapySDR.SOAPY_SDR_RX, channel)
                capabilities["frequency_ranges"] = [
                    {"min": fr.minimum(), "max": fr.maximum()}
                    for fr in freq_ranges
                ]
            except Exception as exc:
                logger.debug("Driver '%s' does not expose frequency ranges: %s", driver, exc)

            # Antennas
            try:
                antennas = device.listAntennas(SoapySDR.SOAPY_SDR_RX, channel)
                capabilities["antennas"] = list(antennas)
            except Exception as exc:
                logger.debug("Driver '%s' does not expose antennas: %s", driver, exc)

        # Clean up
        try:
            if hasattr(device, 'unmake'):
                device.unmake()  # type: ignore[attr-defined]
            else:
                device.close()
        except Exception as exc:
            logger.debug("Failed to close device for driver '%s': %s", driver, exc)

        return capabilities

    except Exception as exc:
        logger.error(f"Failed to query device capabilities for driver '{driver}': {exc}")

        # Return fallback default capabilities based on driver type
        # This allows UI to work even if device is busy/in-use
        driver_lower = driver.lower()

        if 'airspy' in driver_lower:
            logger.info(f"Returning fallback Airspy capabilities (device may be in use)")
            # IMPORTANT: Airspy R2 (the most common model) ONLY supports 2.5 MHz and 10 MHz.
            # Other Airspy models have different rates:
            # - Airspy Mini: 3 MSPS and 6 MSPS
            # - Airspy HF+: Various rates
            # This fallback assumes Airspy R2. If using a different model, the hardware
            # query should return the correct rates when the device is available.
            return {
                "driver": driver,
                "hardware_info": {"fallback": "true", "reason": "Device busy or unavailable", "assumed_model": "Airspy R2"},
                "num_channels": 1,
                "sample_rates": [2500000, 10000000],  # Airspy R2: ONLY 2.5 MHz and 10 MHz
                "bandwidths": [],
                "gains": {"LNA": {"min": 0, "max": 15, "step": 1}, "MIX": {"min": 0, "max": 15, "step": 1}, "VGA": {"min": 0, "max": 15, "step": 1}},
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

    # AirSpy R2: ONLY 2.5 MHz and 10 MHz are supported
    # These are the only valid base sample rates for Airspy R2 hardware
    if "airspy" in driver_lower:
        # Airspy R2 ONLY supports 2.5 MHz and 10 MHz - no other rates
        airspy_valid_rates = {2500000, 10000000}

        if sample_rate in airspy_valid_rates:
            return True, None

        # Also accept rates that are close to valid rates (within 1%)
        # This handles slight variations in how rates are reported
        for valid_rate in airspy_valid_rates:
            if abs(sample_rate - valid_rate) / valid_rate < 0.01:
                return True, None

        return False, f"Sample rate {sample_rate/1e6:.3f} MHz is not supported by Airspy R2. ONLY 2.5 MHz and 10 MHz are valid."

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

    # File replay: any positive sample rate is acceptable since we're
    # just paced reading a .npy at that rate. Reject obviously invalid
    # values but otherwise let the operator pick whatever the capture
    # was recorded at.
    elif driver_lower in {"file", "file_replay", "iq_replay"}:
        if sample_rate <= 0:
            return False, "Sample rate must be positive."
        if sample_rate > 100_000_000:
            return False, f"Sample rate {sample_rate} Hz is implausibly high for a file replay."
        return True, None

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
