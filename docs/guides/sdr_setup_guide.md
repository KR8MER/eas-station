# SDR Setup Guide for EAS Station

This guide will walk you through setting up Software Defined Radio (SDR) receivers with EAS Station to monitor NOAA Weather Radio broadcasts and capture Emergency Alert System (EAS/SAME) transmissions.

## Table of Contents

1. [Overview](#overview)
2. [Hardware Requirements](#hardware-requirements)
3. [Software Installation](#software-installation)
4. [Docker Configuration](#docker-configuration)
5. [Quick Setup Using the Web UI](#quick-setup-using-the-web-ui)
6. [Manual Configuration](#manual-configuration)
7. [Testing Your Setup](#testing-your-setup)
8. [Troubleshooting](#troubleshooting)
9. [Advanced Topics](#advanced-topics)

## Overview

EAS Station supports multiple SDR receivers through SoapySDR, a vendor-neutral SDR library. The most common and affordable option is an RTL-SDR dongle (based on the RTL2832U chip), which typically costs $20-40.

### What You Can Do

- Monitor NOAA Weather Radio frequencies (162.400-162.550 MHz)
- Automatically capture IQ/PCM data when SAME alerts are detected
- Run multiple SDRs simultaneously for redundancy or multi-frequency monitoring
- Analyze signal strength and carrier lock status in real-time

## Hardware Requirements

### Supported SDR Devices

- **RTL-SDR** (RTL2832U chipset) - Most common and affordable
  - Example: NooElec NESDR SMArt, RTL-SDR Blog V3
  - Frequency range: ~24 MHz to 1.7 GHz
  - Sample rates: Up to 2.4 MSPS
  - Cost: $20-40

- **Airspy** - Higher performance option
  - Example: Airspy Mini, Airspy R2
  - Better sensitivity and dynamic range
  - Cost: $100-200+

### Antenna Requirements

For NOAA Weather Radio (162 MHz):
- A simple whip antenna or telescoping antenna works for most locations
- For best results: Outdoor 1/4 wave ground plane antenna (~19 inches)
- Commercial options: Scanner antennas designed for VHF reception

## Software Installation

### Docker Deployments (Recommended)

**Good news!** SoapySDR and all necessary drivers are now **automatically installed** as part of the Docker build process. You don't need to install anything manually!

The Docker image includes:
- SoapySDR core libraries and Python bindings
- RTL-SDR and optional Airspy drivers (controlled by the `SOAPYSDR_DRIVERS`
  build argument)
- NumPy for signal processing
- USB device support

All you need to do is:
1. Build/pull the Docker image
2. Ensure your SDR device is plugged in
3. Start the containers

The docker-compose.yml is already configured to provide USB device access to the containers.

### On Host System (Without Docker)

If running EAS Station directly on your host without Docker:

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3-soapysdr soapysdr-module-rtlsdr soapysdr-module-airspy python3-numpy

# Verify installation
SoapySDRUtil --info
```

> [!TIP]
> When building the Docker image yourself (including via Portainer), set
> `SOAPYSDR_DRIVERS` to a comma-separated list such as `rtlsdr` to skip unused
> hardware modules and dramatically reduce build times. Keep `rtlsdr,airspy` if
> you plan to connect both receiver families.

## Docker Configuration

### USB Device Access (Already Configured!)

The docker-compose.yml file is already configured to provide USB device access to all services. The configuration includes:

```yaml
devices:
  - /dev/bus/usb:/dev/bus/usb
privileged: true
```

This is automatically applied to the app, poller, and ipaws-poller services.

### Verify USB Access

```bash
# On the host, check if your SDR is detected
lsusb | grep -i rtl
# Or for Airspy:
lsusb | grep -i airspy

# Should show something like:
# RTL-SDR: Bus 001 Device 005: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T
# Airspy: Bus 001 Device 006: ID 1d50:60a1 OpenMoko, Inc. Airspy

# After starting the container, verify it can see the device
docker compose exec app ls -la /dev/bus/usb

# Test SoapySDR inside the container
docker compose exec app SoapySDRUtil --find
docker compose exec app python scripts/sdr_diagnostics.py
```

## Quick Setup Using the Web UI

The easiest way to configure SDRs is through the web interface:

### Step 1: Access the Radio Settings Page

1. Log into EAS Station web interface
2. Navigate to **Settings** → **Radio Receivers**

### Step 2: Run Diagnostics

1. Click the **Run Diagnostics** button in the Quick Setup panel
2. Verify that:
   - ✓ SoapySDR is installed
   - ✓ NumPy is installed
   - ✓ Your SDR driver is available (rtlsdr or airspy)
   - ✓ At least 1 device is detected

If diagnostics fail, see the [Troubleshooting](#troubleshooting) section.

### Step 3: Discover Devices

1. Click the **Discover Devices** button
2. Review the list of detected SDRs
3. Click **Add This Device** on the device you want to use
4. The form will be pre-filled with device information

### Step 4: Apply a Preset (Recommended)

1. Click the **Use Preset** button
2. Choose a preset:
   - **NOAA Weather Radio (RTL-SDR)** - For RTL-SDR dongles
   - **NOAA Weather Radio (Airspy)** - For Airspy receivers
3. Click **Use This Preset**
4. Adjust the frequency for your local NOAA station (see below)
5. Click **Save Receiver**

### Step 5: Find Your Local NOAA Weather Radio Station

Visit https://www.weather.gov/nwr/station_listing and find your nearest transmitter.

**NOAA Weather Radio Frequencies:**
- WX1: 162.400 MHz
- WX2: 162.425 MHz
- WX3: 162.450 MHz
- WX4: 162.475 MHz
- WX5: 162.500 MHz
- WX6: 162.525 MHz
- WX7: 162.550 MHz

Update your receiver's frequency to match your local station (frequency in Hz: multiply MHz by 1,000,000).

### Step 6: Enable and Monitor

1. Ensure **Enabled** and **Auto-start** are checked
2. Save the receiver
3. The receiver will automatically start
4. Watch for the **Locked** status badge to turn green
5. Check the signal strength reading

## Manual Configuration

If you prefer to configure receivers manually or via API:

### Example Configuration

| Field | RTL-SDR Example | Airspy Example |
|-------|-----------------|----------------|
| Display Name | `Main NOAA Receiver` | `Backup NOAA Receiver` |
| Identifier | `rtlsdr_main` | `airspy_backup` |
| Driver | `rtlsdr` | `airspy` |
| Frequency (Hz) | `162550000` (162.55 MHz) | `162550000` (162.55 MHz) |
| Sample Rate | `2400000` | `2500000` |
| Gain (dB) | `49.6` | `21` |
| Channel | Leave empty or `0` | Leave empty or `0` |
| Notes | Optional description | Optional description |
| Enabled | ✓ | ✓ |
| Auto-start | ✓ | ✓ |

### Gain Settings

- **RTL-SDR**: Typical range is 0-50 dB. Start with 49.6 dB for maximum sensitivity
- **Airspy**: Typical range is 0-21 dB. Start with 21 dB
- Adjust based on your signal strength and noise floor
- Too much gain can cause overload; too little reduces sensitivity

## Testing Your Setup

### Using the CLI Diagnostic Tool

The project includes a command-line diagnostic tool:

```bash
# Run full diagnostic check
python scripts/sdr_diagnostics.py

# Enumerate devices
python scripts/sdr_diagnostics.py --enumerate

# Query capabilities of a specific driver
python scripts/sdr_diagnostics.py --capabilities rtlsdr

# Test sample capture
python scripts/sdr_diagnostics.py --test-capture --driver rtlsdr --frequency 162550000 --duration 5

# Show preset configurations
python scripts/sdr_diagnostics.py --presets
```

### Using the Web UI

1. Navigate to **Settings** → **Radio Receivers**
2. Check the **Receiver Status** panel:
   - **Locked**: Should show a count > 0 if receivers are working
   - Look for green "Locked" badges in the receiver table
   - Signal strength should be > 0.0 dBFS

3. Check the receiver row for each device:
   - Status badge should be green with "Locked"
   - Signal strength should be displayed
   - No error messages should appear

### Expected Signal Levels

- **Good signal**: 0.1 - 1.0 dBFS with clear lock
- **Weak signal**: 0.01 - 0.1 dBFS (may work but prone to dropouts)
- **Very weak**: < 0.01 dBFS (unlikely to decode properly)
- **Too strong**: > 1.0 dBFS (may indicate overload, reduce gain)

## Troubleshooting

### "No SDR Devices Found"

**Possible causes:**

1. **SDR not plugged in**
   - Check USB connection
   - Try a different USB port (USB 2.0 ports often work better than USB 3.0 for some SDRs)
   - Verify with `lsusb` on the host

2. **Docker container needs restart**
   - After plugging in or unplugging an SDR, restart the containers:
   ```bash
   docker compose restart
   ```

3. **Kernel driver conflict (RTL-SDR specific)**
   - The DVB-T kernel driver may be blocking access
   - On the host, create `/etc/modprobe.d/blacklist-rtl.conf`:
   ```
   blacklist dvb_usb_rtl28xxu
   blacklist rtl2832
   blacklist rtl2830
   ```
   - Then run: `sudo modprobe -r dvb_usb_rtl28xxu`

4. **Docker: Container needs rebuild**
   - If you updated the Dockerfile, rebuild the image:
   ```bash
   docker compose build app
   docker compose up -d
   ```

### "SoapySDR not installed" (Shouldn't happen with Docker)

**For Docker:**
- SoapySDR is automatically installed in the container
- If you see this error, rebuild the image: `docker compose build app`

**For host installations:**
```bash
sudo apt install python3-soapysdr soapysdr-module-rtlsdr soapysdr-module-airspy python3-numpy
```

### "Receiver shows 'No lock' status"

**Possible causes:**

1. **Wrong frequency**
   - Verify you're tuned to the correct NOAA frequency for your area
   - Check https://www.weather.gov/nwr/station_listing

2. **Weak signal**
   - Try a better antenna
   - Move antenna to a window or higher location
   - Increase gain (but watch for overload)

3. **No antenna connected**
   - Ensure antenna is properly connected to the SDR

4. **Interference**
   - Move away from computers, power supplies, USB hubs
   - Use a shielded USB cable
   - Use a powered USB hub if needed

### "Signal strength is 0 or very low"

1. **Check antenna connection** - Ensure it's firmly attached
2. **Verify frequency** - Make sure it matches your local NOAA station
3. **Increase gain** - Try higher gain settings (but watch for overload)
4. **Test with FM radio** - Tune to a known strong FM station (88-108 MHz) to verify hardware

### "Receiver worked then stopped"

1. **Check poller logs** - Look for error messages
2. **USB power issues** - Use a powered USB hub for better power delivery
3. **Device conflict** - Ensure no other software is accessing the SDR
4. **Restart receiver** - Disable and re-enable in the web UI

## Advanced Topics

### Multiple Receivers

You can run multiple SDRs simultaneously:

1. **Multi-frequency monitoring**: Monitor multiple NOAA stations
2. **Redundancy**: Have backup receivers on the same frequency
3. **Device identification**: Use `Channel` or `Serial` to distinguish identical devices

### Capture Modes

Configure via environment variables:

```bash
# IQ mode: Complex 32-bit I/Q samples (for offline analysis/demodulation)
RADIO_CAPTURE_MODE=iq

# PCM mode: Float32 interleaved I/Q (for direct audio decoders)
RADIO_CAPTURE_MODE=pcm
```

### Capture Duration

```bash
# Capture 30 seconds when SAME burst detected
RADIO_CAPTURE_DURATION=30
```

### Custom Frequencies

While designed for NOAA Weather Radio, you can monitor other frequencies:

- **Requirements**: Must be within your SDR's supported frequency range
- **Sample rates**: Adjust based on signal bandwidth
- **Gain**: May need adjustment for different frequencies

### Signal Analysis

Captured IQ files can be analyzed with:
- **GNU Radio**: For signal processing and demodulation
- **inspectrum**: Visual spectrum analyzer
- **Custom Python scripts**: Using NumPy/SciPy

## Getting Help

If you're still having trouble:

1. **Check the logs**: Look in `logs/eas_station.log` for error messages
2. **Run diagnostics**: Use the web UI diagnostics or CLI tool
3. **GitHub Issues**: Report issues at https://github.com/KR8MER/eas-station/issues
4. **Include details**:
   - SDR model and driver
   - Docker or host installation
   - Output of diagnostics
   - Error messages from logs

## Additional Resources

- **SoapySDR Documentation**: https://github.com/pothosware/SoapySDR/wiki
- **RTL-SDR Guide**: https://www.rtl-sdr.com/about-rtl-sdr/
- **NOAA Weather Radio**: https://www.weather.gov/nwr/
- **EAS/SAME Protocol**: https://en.wikipedia.org/wiki/Specific_Area_Message_Encoding
