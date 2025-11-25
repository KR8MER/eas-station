# SDR Quick Start Guide (RTL-SDR & Airspy)

## ⚡ One-Click Setup

SoapySDR, RTL-SDR, and Airspy drivers are **pre-installed** in the Docker image. No manual installation, no .env configuration needed - just plug in your device and start the container!

## ✨ What's Included

- ✅ **SoapySDR** - Automatically installed
- ✅ **RTL-SDR drivers** - Pre-compiled and ready
- ✅ **Airspy drivers** - Pre-compiled and ready
- ✅ **USB access** - Pre-configured in docker-compose.yml
- ✅ **NumPy** - For signal processing
- ✅ **No .env variables** - No paths to configure!

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

### 2. Build or Pull the Image

```bash
# Option A: Build locally (includes RTL-SDR + Airspy by default)
sudo docker compose build app

# Option B: Pull pre-built image (if available)
sudo docker pull ghcr.io/kr8mer/eas-station:latest
```

**Note**: Both RTL-SDR and Airspy are included by default. No build args needed!

> **Non-root users**: Docker commands typically require `sudo`. If you've added your user to the `docker` group, you can omit `sudo`.

### 3. Start the Containers

```bash
# Start all services
sudo docker compose up -d

# Or with embedded database
sudo docker compose -f docker-compose.yml -f docker-compose.embedded-db.yml up -d
```

### 4. Verify SoapySDR Installation

```bash
# Test SoapySDR from inside the container
sudo docker compose exec app SoapySDRUtil --find

# Run the diagnostic script
sudo docker compose exec app python scripts/sdr_diagnostics.py
```

You should see output showing your connected SDR device(s).

### 5. Configure Your SDR in the Web UI

1. Open your browser to http://localhost:5000
2. Navigate to **Settings** → **Radio Receivers**
3. Click **Run Diagnostics** to verify everything is working
4. Click **Discover Devices** to see your connected SDRs
5. Click **Add This Device** and configure with a preset

## Expected Output

When you run `sudo docker compose exec app SoapySDRUtil --find`, you should see something like:

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
2. **Restart containers**: `sudo docker compose restart`
3. **Check logs**: `sudo docker compose logs app`
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
sudo docker compose exec app python scripts/sdr_diagnostics.py --enumerate
sudo docker compose exec app python scripts/sdr_diagnostics.py --capabilities rtlsdr
# Or for Airspy:
sudo docker compose exec app python scripts/sdr_diagnostics.py --capabilities airspy
```

## Next Steps

Once your SDR is detected:

1. Configure a receiver in the web UI
2. Set the frequency to your local NOAA Weather Radio station
3. Adjust gain settings for optimal signal strength
4. Enable the receiver and watch for the "Locked" status

For detailed configuration instructions, see:
- [Full SDR Setup Guide](sdr_setup_guide)
- [Radio USB Passthrough Guide](radio_usb_passthrough)

## Technical Details

### What's Installed

The Dockerfile now includes:
- `libusb-1.0-0` and `libusb-1.0-0-dev` - USB device support
- `python3-soapysdr` - SoapySDR Python bindings
- `soapysdr-module-*` drivers defined by the `SOAPYSDR_DRIVERS` build argument
  (defaults to `rtlsdr,airspy`)
- `soapysdr-tools` - Command-line utilities (SoapySDRUtil, etc.)
- `numpy` - Signal processing (in requirements.txt)

#### Optional: Speeding up Docker builds

If you only use RTL-SDR (not Airspy), you can speed up builds by adding to `.env`:

```env
SOAPYSDR_DRIVERS=rtlsdr
```

**Default** (both drivers): `SOAPYSDR_DRIVERS=rtlsdr,airspy`

This only affects build time - runtime performance is identical.

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
1. Check the [SDR Setup Guide](sdr_setup_guide)
2. Review the [Troubleshooting section](sdr_setup_guide#troubleshooting)
3. Open an issue at https://github.com/KR8MER/eas-station/issues

Include:
- Output of `lsusb` on the host
- Output of `sudo docker compose exec app SoapySDRUtil --find`
- Output of `sudo docker compose exec app python scripts/sdr_diagnostics.py`
- Relevant logs from `sudo docker compose logs app`
