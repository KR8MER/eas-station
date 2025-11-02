#!/usr/bin/env python3
"""
SDR Diagnostics and Testing Utility

This script helps diagnose SoapySDR installation issues and test connected SDR devices.
Run this script to verify that your SDR hardware is properly configured.

Usage:
    python scripts/sdr_diagnostics.py
    python scripts/sdr_diagnostics.py --test-capture --driver rtlsdr --frequency 162550000
"""

import argparse
import sys
from pathlib import Path

# Add the app root to the Python path
app_root = Path(__file__).parent.parent
sys.path.insert(0, str(app_root))


def print_header(text: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def check_installation() -> bool:
    """Check if SoapySDR and dependencies are installed."""
    print_header("Checking SoapySDR Installation")

    issues = []

    # Check SoapySDR
    try:
        import SoapySDR
        print(f"✓ SoapySDR is installed (API version: {SoapySDR.getAPIVersion()})")
    except ImportError as exc:
        print(f"✗ SoapySDR is NOT installed")
        print(f"  Error: {exc}")
        issues.append("SoapySDR Python bindings missing")
        print("\n  Installation instructions:")
        print("  - Ubuntu/Debian: sudo apt install python3-soapysdr")
        print("  - Or via pip: pip install SoapySDR")

    # Check NumPy
    try:
        import numpy
        print(f"✓ NumPy is installed (version: {numpy.__version__})")
    except ImportError as exc:
        print(f"✗ NumPy is NOT installed")
        print(f"  Error: {exc}")
        issues.append("NumPy missing")
        print("\n  Installation instructions:")
        print("  - pip install numpy")

    if issues:
        print(f"\n⚠ Found {len(issues)} issue(s). Please install missing dependencies.")
        return False

    print("\n✓ All dependencies are installed correctly!")
    return True


def enumerate_devices() -> list:
    """Enumerate and display all connected SDR devices."""
    print_header("Enumerating SDR Devices")

    try:
        import SoapySDR
    except ImportError:
        print("✗ Cannot enumerate devices - SoapySDR not installed")
        return []

    try:
        devices = SoapySDR.Device.enumerate()

        if not devices:
            print("⚠ No SDR devices found!")
            print("\nTroubleshooting tips:")
            print("  1. Ensure your SDR is plugged into a USB port")
            print("  2. Check USB connection with: lsusb")
            print("  3. Verify device permissions (user may need to be in 'plugdev' group)")
            print("  4. Install device-specific SoapySDR modules:")
            print("     - RTL-SDR: sudo apt install soapysdr-module-rtlsdr")
            print("     - Airspy: sudo apt install soapysdr-module-airspy")
            print("  5. In Docker: ensure /dev/bus/usb is mapped to the container")
            return []

        print(f"✓ Found {len(devices)} SDR device(s):\n")

        for idx, device in enumerate(devices, 1):
            print(f"  Device #{idx}:")
            for key, value in sorted(device.items()):
                print(f"    {key:20s}: {value}")
            print()

        return devices

    except Exception as exc:
        print(f"✗ Error enumerating devices: {exc}")
        return []


def query_capabilities(driver: str) -> None:
    """Query and display capabilities of a specific driver."""
    print_header(f"Querying Capabilities for '{driver}' Driver")

    try:
        import SoapySDR
    except ImportError:
        print("✗ Cannot query capabilities - SoapySDR not installed")
        return

    try:
        device = SoapySDR.Device({"driver": driver})

        print(f"Hardware Info: {device.getHardwareInfo()}")
        print(f"Number of RX channels: {device.getNumChannels(SoapySDR.SOAPY_SDR_RX)}")

        if device.getNumChannels(SoapySDR.SOAPY_SDR_RX) > 0:
            channel = 0

            # Sample rates
            try:
                rates = device.listSampleRates(SoapySDR.SOAPY_SDR_RX, channel)
                print(f"\nSupported sample rates:")
                for rate in rates[:10]:  # Show first 10
                    print(f"  - {int(rate):,} samples/sec ({rate/1e6:.2f} MHz)")
                if len(rates) > 10:
                    print(f"  ... and {len(rates) - 10} more")
            except Exception as exc:
                print(f"  Could not list sample rates: {exc}")

            # Frequency ranges
            try:
                freq_ranges = device.getFrequencyRange(SoapySDR.SOAPY_SDR_RX, channel)
                print(f"\nSupported frequency ranges:")
                for fr in freq_ranges:
                    min_mhz = fr.minimum() / 1e6
                    max_mhz = fr.maximum() / 1e6
                    print(f"  - {min_mhz:.2f} MHz to {max_mhz:.2f} MHz")
            except Exception as exc:
                print(f"  Could not list frequency ranges: {exc}")

            # Gains
            try:
                gains = device.listGains(SoapySDR.SOAPY_SDR_RX, channel)
                print(f"\nGain controls:")
                for gain_name in gains:
                    gain_range = device.getGainRange(SoapySDR.SOAPY_SDR_RX, channel, gain_name)
                    print(f"  - {gain_name}: {gain_range.minimum():.1f} to {gain_range.maximum():.1f} dB")
            except Exception as exc:
                print(f"  Could not list gains: {exc}")

        # Clean up
        try:
            if hasattr(device, 'unmake'):
                device.unmake()
            else:
                device.close()
        except Exception:
            pass

        print("\n✓ Successfully queried device capabilities")

    except Exception as exc:
        print(f"✗ Error querying capabilities: {exc}")
        print("\nMake sure:")
        print(f"  1. The '{driver}' driver is installed")
        print(f"  2. A compatible device is connected")
        print(f"  3. You have permissions to access USB devices")


def test_capture(driver: str, frequency: float, duration: float = 1.0, sample_rate: int = 2_400_000) -> None:
    """Test capturing samples from an SDR."""
    print_header(f"Testing Sample Capture")

    print(f"Driver: {driver}")
    print(f"Frequency: {frequency / 1e6:.3f} MHz")
    print(f"Sample Rate: {sample_rate:,} samples/sec")
    print(f"Duration: {duration:.1f} seconds")
    print()

    try:
        import SoapySDR
        import numpy as np
    except ImportError as exc:
        print(f"✗ Missing dependencies: {exc}")
        return

    device = None
    stream = None

    try:
        # Open device
        print("Opening device...")
        device = SoapySDR.Device({"driver": driver})

        # Configure
        print("Configuring device...")
        channel = 0
        device.setSampleRate(SoapySDR.SOAPY_SDR_RX, channel, sample_rate)
        device.setFrequency(SoapySDR.SOAPY_SDR_RX, channel, frequency)

        # Setup stream
        print("Setting up stream...")
        stream = device.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32)
        device.activateStream(stream)

        # Capture samples
        print(f"Capturing samples for {duration} seconds...")
        buffer = np.zeros(4096, dtype=np.complex64)
        total_samples = int(sample_rate * duration)
        samples_captured = 0

        while samples_captured < total_samples:
            result = device.readStream(stream, [buffer], len(buffer))

            if result.ret < 0:
                print(f"✗ Stream error: {result.ret}")
                break

            if result.ret > 0:
                samples_captured += result.ret
                # Calculate signal strength
                magnitude = np.mean(np.abs(buffer[:result.ret]))
                progress = (samples_captured / total_samples) * 100
                print(f"  Progress: {progress:.1f}% | Samples: {samples_captured:,} | Signal: {magnitude:.4f}", end='\r')

        print()  # New line after progress

        if samples_captured >= total_samples:
            print(f"\n✓ Successfully captured {samples_captured:,} samples!")
            avg_magnitude = np.mean(np.abs(buffer))
            print(f"  Average signal magnitude: {avg_magnitude:.4f}")

            if avg_magnitude < 0.0001:
                print("\n⚠ Warning: Signal level is very low. Check:")
                print("  - Antenna is connected")
                print("  - Frequency is correct for your area")
                print("  - Gain settings (try increasing gain)")
        else:
            print(f"\n⚠ Only captured {samples_captured:,} / {total_samples:,} samples")

    except Exception as exc:
        print(f"\n✗ Capture test failed: {exc}")
        print("\nTroubleshooting:")
        print("  - Ensure the device is not in use by another application")
        print("  - Check that the frequency is within the device's supported range")
        print("  - Verify USB connection and permissions")

    finally:
        # Clean up
        if stream and device:
            try:
                device.deactivateStream(stream)
                device.closeStream(stream)
            except Exception:
                pass

        if device:
            try:
                if hasattr(device, 'unmake'):
                    device.unmake()
                else:
                    device.close()
            except Exception:
                pass


def show_presets() -> None:
    """Display common preset configurations."""
    print_header("Common SDR Presets for NOAA Weather Radio")

    print("NOAA Weather Radio Frequencies (United States):")
    print("  WX1: 162.400 MHz")
    print("  WX2: 162.425 MHz")
    print("  WX3: 162.450 MHz")
    print("  WX4: 162.475 MHz")
    print("  WX5: 162.500 MHz")
    print("  WX6: 162.525 MHz")
    print("  WX7: 162.550 MHz")

    print("\nRecommended Settings for RTL-SDR:")
    print("  Driver: rtlsdr")
    print("  Frequency: 162550000 Hz (162.550 MHz - adjust for your area)")
    print("  Sample Rate: 2400000 samples/sec")
    print("  Gain: 49.6 dB")

    print("\nRecommended Settings for Airspy:")
    print("  Driver: airspy")
    print("  Frequency: 162550000 Hz (162.550 MHz - adjust for your area)")
    print("  Sample Rate: 2500000 samples/sec")
    print("  Gain: 21 dB")

    print("\nFind your local NOAA station:")
    print("  https://www.weather.gov/nwr/station_listing")


def main():
    """Main entry point for the diagnostic tool."""
    parser = argparse.ArgumentParser(
        description="SDR Diagnostics and Testing Utility for EAS Station",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--enumerate",
        action="store_true",
        help="Enumerate all connected SDR devices",
    )

    parser.add_argument(
        "--capabilities",
        metavar="DRIVER",
        help="Query capabilities of a specific driver (e.g., rtlsdr, airspy)",
    )

    parser.add_argument(
        "--test-capture",
        action="store_true",
        help="Test capturing samples from an SDR",
    )

    parser.add_argument(
        "--driver",
        default="rtlsdr",
        help="SDR driver to use for testing (default: rtlsdr)",
    )

    parser.add_argument(
        "--frequency",
        type=float,
        default=162_550_000,
        help="Frequency in Hz (default: 162550000 = 162.55 MHz)",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=1.0,
        help="Capture duration in seconds (default: 1.0)",
    )

    parser.add_argument(
        "--sample-rate",
        type=int,
        default=2_400_000,
        help="Sample rate in samples/sec (default: 2400000)",
    )

    parser.add_argument(
        "--presets",
        action="store_true",
        help="Show common preset configurations",
    )

    args = parser.parse_args()

    # Print welcome banner
    print("\n" + "="*70)
    print("  SDR Diagnostics and Testing Utility")
    print("  EAS Station - Emergency Alert System")
    print("="*70)

    # Run installation check first if no specific action is requested
    if not any([args.enumerate, args.capabilities, args.test_capture, args.presets]):
        installation_ok = check_installation()
        if installation_ok:
            enumerate_devices()
            show_presets()
        sys.exit(0 if installation_ok else 1)

    # Run specific requested actions
    if args.enumerate:
        check_installation()
        enumerate_devices()

    if args.capabilities:
        query_capabilities(args.capabilities)

    if args.test_capture:
        test_capture(args.driver, args.frequency, args.duration, args.sample_rate)

    if args.presets:
        show_presets()

    print("\n" + "="*70)
    print("  Diagnostic check complete!")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
