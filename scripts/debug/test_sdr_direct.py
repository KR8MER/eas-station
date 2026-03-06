#!/usr/bin/env python3
"""
Direct SoapySDR test - minimal code to diagnose device detection issues.

Run on the system with SDR hardware:
    sudo -u eas-station /opt/eas-station/venv/bin/python /opt/eas-station/scripts/debug/test_sdr_direct.py
"""

import sys


def main() -> int:
    print("=" * 60)
    print("SoapySDR Direct Test")
    print("=" * 60)

    # Step 1: Import SoapySDR
    print("\n[1] Importing SoapySDR...")
    try:
        import SoapySDR

        print("    ✓ SoapySDR loaded")
        print(f"    API Version: {SoapySDR.getAPIVersion()}")
        print(f"    ABI Version: {SoapySDR.getABIVersion()}")
    except ImportError as e:
        print(f"    ✗ FAILED: {e}")
        return 1

    # Step 2: List available modules
    print("\n[2] Checking loaded modules...")
    try:
        # SoapySDR doesn't have a direct Python API for this,
        # but we can check what drivers are discoverable
        import subprocess

        result = subprocess.run(
            ["SoapySDRUtil", "--info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.split("\n"):
            if line.strip():
                print(f"    {line}")
    except Exception as e:
        print(f"    ✗ Could not get module info: {e}")

    # Step 3: Try airspy-specific enumeration
    print("\n[3] Enumerating airspy devices (driver=airspy)...")
    try:
        airspy_devices = SoapySDR.Device.enumerate("driver=airspy")
        print(f"    Found {len(airspy_devices)} airspy device(s)")
        for i, dev in enumerate(airspy_devices):
            dev_dict = dict(dev)
            print(f"    [{i}] {dev_dict}")
    except Exception as e:
        print(f"    ✗ Airspy enumeration failed: {e}")
        airspy_devices = []

    # Step 4: Try general enumeration
    print("\n[4] Enumerating ALL devices (no filter)...")
    try:
        all_devices = SoapySDR.Device.enumerate()
        print(f"    Found {len(all_devices)} device(s)")
        for i, dev in enumerate(all_devices):
            dev_dict = dict(dev)
            print(f"    [{i}] {dev_dict}")
    except Exception as e:
        print(f"    ✗ General enumeration failed: {e}")
        all_devices = []

    # Step 5: Try to open the first airspy device directly
    print("\n[5] Attempting to open airspy device...")
    if airspy_devices:
        try:
            dev_args = dict(airspy_devices[0])
            print(f"    Opening with args: {dev_args}")
            device = SoapySDR.Device(dev_args)
            print("    ✓ Device opened successfully!")

            # Get device info
            hw_info = device.getHardwareInfo()
            print(f"    Hardware info: {dict(hw_info)}")

            # List sample rates
            sample_rates = device.listSampleRates(SoapySDR.SOAPY_SDR_RX, 0)
            print(f"    Sample rates: {list(sample_rates)}")

            # Try to set up a stream
            print("\n[6] Setting up stream...")
            device.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, 2500000)
            device.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, 162550000)

            stream = device.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32)
            device.activateStream(stream)
            print("    ✓ Stream activated!")

            # Read some samples
            import numpy as np

            buffer = np.zeros(16384, dtype=np.complex64)
            sr = device.readStream(stream, [buffer], len(buffer))
            print(f"    ✓ Read {sr.ret} samples")

            # Cleanup
            device.deactivateStream(stream)
            device.closeStream(stream)
            print("    ✓ Stream closed")

        except Exception as e:
            print(f"    ✗ Failed to open device: {e}")
            import traceback

            traceback.print_exc()
    else:
        print("    (skipped - no airspy devices found)")

        # Try opening with just driver=airspy
        print("\n[5b] Trying to open with driver=airspy args...")
        try:
            device = SoapySDR.Device({"driver": "airspy"})
            print("    ✓ Device opened successfully!")
            hw_info = device.getHardwareInfo()
            print(f"    Hardware info: {dict(hw_info)}")
        except Exception as e:
            print(f"    ✗ Failed: {e}")

    # Step 6: Check USB devices at system level
    print("\n[7] Checking USB devices (lsusb)...")
    try:
        import subprocess

        result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split("\n"):
            if line.strip():
                # Highlight SDR-related devices
                if any(x in line.lower() for x in ["1d50:", "airspy", "0bda:", "rtl"]):
                    print(f"    >>> {line}")
                else:
                    print(f"    {line}")
    except Exception as e:
        print(f"    ✗ lsusb failed: {e}")

    print("\n" + "=" * 60)
    print("Test complete")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
