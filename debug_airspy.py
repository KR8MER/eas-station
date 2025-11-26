#!/usr/bin/env python3
"""
Diagnostic script for AirSpy device connection issues.
This script helps troubleshoot SoapySDR and AirSpy connectivity problems.
"""

import sys


def check_imports():
    """Check if required libraries are available."""
    print("=" * 70)
    print("1. Checking Python module imports...")
    print("=" * 70)

    issues = []

    # Check SoapySDR
    try:
        import SoapySDR
        print(f"✓ SoapySDR: INSTALLED (API version: {SoapySDR.getAPIVersion()})")
    except ImportError as e:
        print(f"✗ SoapySDR: NOT INSTALLED ({e})")
        issues.append("SoapySDR Python bindings not found")

    # Check NumPy
    try:
        import numpy
        print(f"✓ NumPy: INSTALLED (version: {numpy.__version__})")
    except ImportError as e:
        print(f"✗ NumPy: NOT INSTALLED ({e})")
        issues.append("NumPy not found")

    print()
    return 'SoapySDR' in sys.modules, issues


def enumerate_all_devices():
    """Enumerate all SoapySDR devices."""
    print("=" * 70)
    print("2. Enumerating all SoapySDR devices...")
    print("=" * 70)

    try:
        import SoapySDR
        devices = SoapySDR.Device.enumerate()

        if not devices:
            print("✗ No SoapySDR devices found!")
            print("  Common causes:")
            print("  - Device not connected via USB")
            print("  - USB permissions issue (try: sudo usermod -aG plugdev $USER)")
            print("  - Driver/module not installed")
            print()
            return []

        print(f"✓ Found {len(devices)} device(s):\n")

        for idx, dev in enumerate(devices):
            dev_dict = dict(dev)
            print(f"  Device {idx}:")
            print(f"    Driver:       {dev_dict.get('driver', 'N/A')}")
            print(f"    Label:        {dev_dict.get('label', 'N/A')}")
            print(f"    Serial:       {dev_dict.get('serial', 'N/A')}")
            print(f"    Manufacturer: {dev_dict.get('manufacturer', 'N/A')}")
            print(f"    Product:      {dev_dict.get('product', 'N/A')}")
            print(f"    Hardware:     {dev_dict.get('hardware', 'N/A')}")
            print()

        return devices
    except Exception as e:
        print(f"✗ Error enumerating devices: {e}")
        import traceback
        traceback.print_exc()
        print()
        return []


def test_airspy_connection(target_serial=None):
    """Test AirSpy device connection with different strategies."""
    print("=" * 70)
    print("3. Testing AirSpy device connections...")
    print("=" * 70)

    try:
        import SoapySDR
    except ImportError:
        print("✗ Cannot test - SoapySDR not available")
        return

    strategies = []

    # Strategy 1: Driver only
    strategies.append(("Driver only", {"driver": "airspy"}))

    # Strategy 2: With serial if provided
    if target_serial:
        strategies.append((f"With serial '{target_serial}'", {"driver": "airspy", "serial": target_serial}))

    for strategy_name, args in strategies:
        print(f"\nTesting: {strategy_name}")
        print(f"  Args: {args}")

        try:
            device = SoapySDR.Device(args)
            print(f"  ✓ SUCCESS - Device opened!")

            # Get device info
            try:
                hw_key = device.getHardwareKey()
                print(f"    Hardware Key: {hw_key}")
            except:
                pass

            try:
                hw_info = device.getHardwareInfo()
                print(f"    Hardware Info: {dict(hw_info)}")
            except:
                pass

            # Try to get sample rates
            try:
                num_channels = device.getNumChannels(SoapySDR.SOAPY_SDR_RX)
                print(f"    RX Channels: {num_channels}")

                if num_channels > 0:
                    rates = device.listSampleRates(SoapySDR.SOAPY_SDR_RX, 0)
                    print(f"    Sample Rates: {[int(r) for r in rates]}")
            except Exception as e:
                print(f"    (Could not query capabilities: {e})")

            # Close device
            try:
                if hasattr(device, 'unmake'):
                    device.unmake()
                else:
                    device.close()
            except:
                pass

        except Exception as e:
            print(f"  ✗ FAILED - {e}")
            import traceback
            traceback.print_exc()

    print()


def check_system_info():
    """Check system-level information."""
    print("=" * 70)
    print("4. System Information")
    print("=" * 70)

    import subprocess
    import os

    # Check if running as root
    print(f"User ID: {os.getuid()} ({'root' if os.getuid() == 0 else 'non-root'})")
    print(f"Groups: {subprocess.run(['groups'], capture_output=True, text=True).stdout.strip()}")

    # Check for USB devices (requires lsusb)
    print("\nUSB Devices (looking for Airspy):")
    try:
        result = subprocess.run(['lsusb'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if 'airspy' in line.lower() or '1d50:60a1' in line.lower():
                print(f"  ✓ {line}")
        if 'airspy' not in result.stdout.lower() and '1d50:60a1' not in result.stdout.lower():
            print("  (No AirSpy USB devices detected by lsusb)")
    except FileNotFoundError:
        print("  (lsusb command not available)")
    except Exception as e:
        print(f"  Error: {e}")

    print()


def main():
    """Run all diagnostics."""
    print("\n")
    print("#" * 70)
    print("# AirSpy Device Connection Diagnostic Tool")
    print("#" * 70)
    print()

    # Parse command line args
    target_serial = None
    if len(sys.argv) > 1:
        target_serial = sys.argv[1]
        print(f"Target serial: {target_serial}\n")

    # Run checks
    soapy_available, issues = check_imports()

    if soapy_available:
        devices = enumerate_all_devices()

        # If no specific serial provided, check if we found any Airspy devices
        if not target_serial and devices:
            for dev in devices:
                dev_dict = dict(dev)
                if dev_dict.get('driver') == 'airspy' and 'serial' in dev_dict:
                    target_serial = dev_dict['serial']
                    print(f"Found AirSpy with serial: {target_serial}")
                    break

        test_airspy_connection(target_serial)

    check_system_info()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if issues:
        print("Issues found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("Basic dependencies are installed.")
        print("If devices are still not connecting, check:")
        print("  1. USB cable and connection")
        print("  2. USB permissions (add user to 'plugdev' group)")
        print("  3. Check if another process is using the device")
        print("  4. Try running: python3 -c 'import airspy; print(airspy.__version__)'")
        print("     to verify libairspy is available")
    print()


if __name__ == "__main__":
    main()
