# SoapySDR Quick Start Guide

## Summary

SoapySDR and all necessary drivers (RTL-SDR, Airspy) are now **automatically installed** as part of the Docker build. You don't need to install anything manually on your host system!

## What Changed

### Before
- Users had to manually install SoapySDR on the host system
- Drivers had to be installed separately
- USB device mapping had to be configured manually

### After (Now)
- ✅ SoapySDR automatically installed in Docker container
- ✅ RTL-SDR and Airspy drivers pre-installed
- ✅ NumPy included for signal processing
- ✅ USB device access pre-configured in docker-compose.yml

## Quick Setup Steps

### 1. Plug in Your SDR Device

Connect your RTL-SDR or Airspy device to a USB port.

Verify on the host:
```bash
# Check that your device is detected
lsusb | grep -i rtl
# Or for Airspy:
lsusb | grep -i airspy
```

### 2. Build the Docker Image

```bash
# Build the image with SoapySDR support
docker compose build app

# Or pull the pre-built image (if available)
docker pull ghcr.io/kr8mer/eas-station:latest
```

### 3. Start the Containers

```bash
# Start all services
docker compose up -d

# Or with embedded database
docker compose -f docker-compose.yml -f docker-compose.embedded-db.yml up -d
```

### 4. Verify SoapySDR Installation

```bash
# Test SoapySDR from inside the container
docker compose exec app SoapySDRUtil --find

# Run the diagnostic script
docker compose exec app python scripts/sdr_diagnostics.py
```

You should see output showing your connected SDR device(s).

### 5. Configure Your SDR in the Web UI

1. Open your browser to http://localhost:5000
2. Navigate to **Settings** → **Radio Receivers**
3. Click **Run Diagnostics** to verify everything is working
4. Click **Discover Devices** to see your connected SDRs
5. Click **Add This Device** and configure with a preset

## Expected Output

When you run `docker compose exec app SoapySDRUtil --find`, you should see something like:

```
######################################################
##     Soapy SDR -- the SDR abstraction library     ##
######################################################

Found device 0
  driver = rtlsdr
  label = Generic RTL2832U OEM :: 00000001
  manufacturer = Realtek
  product = RTL2838UHIDIR
  serial = 00000001
  tuner = Rafael Micro R820T
```

Or for Airspy:

```
Found device 0
  driver = airspy
  label = Airspy Mini
  manufacturer = Airspy
  product = Airspy Mini
  serial = 9123456789
```

## Troubleshooting

### No devices found?

1. **Check USB connection**: `lsusb` on the host should show your device
2. **Restart containers**: `docker compose restart`
3. **Check logs**: `docker compose logs app`
4. **Blacklist kernel drivers** (for RTL-SDR):
   ```bash
   # On the host, create /etc/modprobe.d/blacklist-rtl.conf:
   blacklist dvb_usb_rtl28xxu
   blacklist rtl2832
   blacklist rtl2830

   # Then unload the module:
   sudo modprobe -r dvb_usb_rtl28xxu
   ```

### Still having issues?

Run the full diagnostic tool:
```bash
docker compose exec app python scripts/sdr_diagnostics.py --enumerate
docker compose exec app python scripts/sdr_diagnostics.py --capabilities rtlsdr
# Or for Airspy:
docker compose exec app python scripts/sdr_diagnostics.py --capabilities airspy
```

## Next Steps

Once your SDR is detected:

1. Configure a receiver in the web UI
2. Set the frequency to your local NOAA Weather Radio station
3. Adjust gain settings for optimal signal strength
4. Enable the receiver and watch for the "Locked" status

For detailed configuration instructions, see:
- [Full SDR Setup Guide](docs/guides/sdr_setup_guide.md)
- [Radio USB Passthrough Guide](docs/guides/radio_usb_passthrough.md)

## Technical Details

### What's Installed

The Dockerfile now includes:
- `libusb-1.0-0` and `libusb-1.0-0-dev` - USB device support
- `python3-soapysdr` - SoapySDR Python bindings
- `soapysdr-module-rtlsdr` - RTL-SDR driver
- `soapysdr-module-airspy` - Airspy driver
- `soapysdr-tools` - Command-line utilities (SoapySDRUtil, etc.)
- `numpy` - Signal processing (in requirements.txt)

### Docker Compose Configuration

All services now include:
```yaml
devices:
  - /dev/bus/usb:/dev/bus/usb
privileged: true
```

This provides:
- Full USB device access
- Permission to enumerate and open SDR devices
- Hot-plug support (devices can be added/removed while running)

## Support

If you encounter issues:
1. Check the [SDR Setup Guide](docs/guides/sdr_setup_guide.md)
2. Review the [Troubleshooting section](docs/guides/sdr_setup_guide.md#troubleshooting)
3. Open an issue at https://github.com/KR8MER/eas-station/issues

Include:
- Output of `lsusb` on the host
- Output of `docker compose exec app SoapySDRUtil --find`
- Output of `docker compose exec app python scripts/sdr_diagnostics.py`
- Relevant logs from `docker compose logs app`
