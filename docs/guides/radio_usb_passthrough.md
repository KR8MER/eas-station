# USB Passthrough for SDR Receivers

This guide explains how to configure USB passthrough so that SoapySDR can access RTL-SDR, Airspy, and other SDR hardware from within the Docker container. Without USB passthrough, the container cannot detect your SDR devices, and you'll see "No SoapySDR-compatible devices were detected" errors.

## Why USB Passthrough is Required

Docker containers are isolated from the host system by default. Your SDR hardware (RTL-SDR dongle, Airspy, HackRF, etc.) is plugged into the **host** machine's USB ports, but the **container** cannot see it unless you explicitly grant access via USB passthrough.

## Configuration Methods

### Method 1: Docker Compose (Recommended)

Add the `devices` section to your `docker-compose.yml` file:

```yaml
services:
  app:
    image: ghcr.io/kr8mer/noaa-alerts:latest

    # USB passthrough for SDR devices
    devices:
      - /dev/bus/usb:/dev/bus/usb

    # Optional: Add privileged mode if you encounter permission issues
    # privileged: true

    environment:
      - RADIO_CAPTURE_DIR=/var/lib/noaa/radio
      - RADIO_CAPTURE_DURATION=30
      - RADIO_CAPTURE_MODE=iq

    volumes:
      - ./radio_captures:/var/lib/noaa/radio
```

**What this does:**
- Maps the entire USB bus from the host into the container
- Allows SoapySDR drivers inside the container to access any USB SDR device
- Maintains a reasonable security profile (better than `--privileged` alone)

### Method 2: Docker Run Command

If using `docker run` instead of Docker Compose:

```bash
docker run -d \
  --name eas-station \
  --device=/dev/bus/usb:/dev/bus/usb \
  -e RADIO_CAPTURE_DIR=/var/lib/noaa/radio \
  -e RADIO_CAPTURE_DURATION=30 \
  -e RADIO_CAPTURE_MODE=iq \
  -v ./radio_captures:/var/lib/noaa/radio \
  ghcr.io/kr8mer/noaa-alerts:latest
```

### Method 3: Specific Device Passthrough

For better security, you can pass through only a specific USB device instead of the entire bus:

```yaml
devices:
  - /dev/bus/usb/001/004:/dev/bus/usb/001/004  # Specific RTL-SDR device
```

To find the specific device path, run `lsusb` on the host and note the bus and device numbers.

## Complete Setup Guide

### Step 1: Verify SDR Hardware on Host

On your **host machine** (not in the container), verify your SDR is detected:

```bash
# List all USB devices
lsusb

# Look for your SDR device, examples:
#   Bus 001 Device 004: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T
#   Bus 001 Device 005: ID 1d50:60a1 OpenMoko, Inc. Airspy
```

If your device doesn't appear here, check:
- Is it plugged in securely?
- Does it work on the host (try `rtl_test` or `airspy_info` if drivers are installed)?
- Try a different USB port or cable

### Step 2: Configure Docker Compose

Edit your `docker-compose.yml` to add USB passthrough (see Method 1 above).

### Step 3: Restart Container

```bash
# Stop the current container
docker compose down

# Start with new configuration
docker compose up -d

# Check logs to verify startup
docker compose logs -f app
```

### Step 4: Verify USB Access Inside Container

```bash
# Enter the running container
docker compose exec app bash

# Check if USB devices are visible
ls -la /dev/bus/usb

# Expected output should show bus directories:
# drwxr-xr-x 2 root root  60 Jan  1 12:00 001
# drwxr-xr-x 2 root root  60 Jan  1 12:00 002
```

### Step 5: Test SoapySDR Device Detection

Inside the container, test if SoapySDR can detect your devices:

```bash
# List all SoapySDR-compatible devices
SoapySDRUtil --find

# Expected output for RTL-SDR:
# Found device 0
#   driver = rtlsdr
#   hardware = R820T
#   serial = 00000001

# Expected output for Airspy:
# Found device 0
#   driver = airspy
#   serial = 0x123456789ABCDEF0
```

If you see your device listed, USB passthrough is working correctly!

### Step 6: Configure in Web UI

1. Navigate to `/settings/radio` in the web interface
2. Click "Discover Devices" - your SDR should appear
3. Click "Add This Device" to auto-fill the form with device details
4. **Important**: Note the **Serial** field is now auto-filled - this ensures precise device identification
5. Configure frequency, sample rate, and gain as needed
6. Save the receiver configuration

## Troubleshooting

### "No SoapySDR-compatible devices were detected"

**Cause**: USB passthrough not configured, or device not visible to container.

**Fix**:
1. Verify `devices: - /dev/bus/usb:/dev/bus/usb` is in docker-compose.yml
2. Restart the container: `docker compose down && docker compose up -d`
3. Check USB visibility: `docker compose exec app ls /dev/bus/usb`
4. If still not working, try adding `privileged: true` temporarily to diagnose

### Permission Denied Errors

**Cause**: The container user doesn't have permission to access USB devices.

**Fix 1** - Add privileged mode:
```yaml
privileged: true
```

**Fix 2** - Add user to plugdev group (on host):
```bash
sudo usermod -aG plugdev $USER
# Log out and back in
```

**Fix 3** - Set udev rules (on host):
```bash
# Create /etc/udev/rules.d/99-sdr.rules
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="60a1", MODE="0666"

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Wrong Driver Selected

**Symptom**: Device found but fails to initialize.

**Fix**: Ensure the `driver` field matches your hardware:
- RTL-SDR dongles: Use `rtlsdr`
- Airspy devices: Use `airspy`
- HackRF: Use `hackrf`
- BladeRF: Use `bladerf`

### Multiple SDR Devices Not Distinguished

**Symptom**: Multiple identical dongles get confused or bind to wrong device.

**Fix**: Use the **Serial** field for each receiver:
1. Run `SoapySDRUtil --find` to get each device's serial number
2. In the web UI, set the **Serial** field for each receiver
3. This ensures each receiver binds to the correct hardware

### Device Already In Use

**Symptom**: "Failed to open device" or "Device busy" errors.

**Fix**:
1. Only one application can use an SDR at a time
2. Stop any other SDR software (SDR++, GQRX, etc.)
3. In the web UI, ensure only one receiver is configured per physical device
4. Use the **Serial** field to prevent binding conflicts

## Supported SDR Hardware

The following SDR devices are supported via SoapySDR modules installed in the container:

| Hardware | Driver Name | SoapySDR Module |
|----------|-------------|-----------------|
| RTL-SDR (RTL2832U) | `rtlsdr` | soapysdr-module-rtlsdr |
| Airspy R2 / Mini | `airspy` | soapysdr-module-airspy |
| HackRF One | `hackrf` | soapysdr-module-hackrf |
| BladeRF | `bladerf` | soapysdr-module-bladerf |
| LimeSDR | `lime` | soapysdr-module-lms7 |

All modules are pre-installed in the Docker image via the Dockerfile.

## Environment Variables

Configure radio capture behavior with these environment variables:

```yaml
environment:
  # Directory where IQ/PCM captures are saved
  - RADIO_CAPTURE_DIR=/var/lib/noaa/radio

  # Duration of each capture in seconds (default: 30)
  - RADIO_CAPTURE_DURATION=30

  # Capture mode: "iq" for raw IQ data, "pcm" for audio (default: iq)
  - RADIO_CAPTURE_MODE=iq
```

## Security Considerations

**USB Passthrough Security**:
- Passing through `/dev/bus/usb` gives the container access to **all** USB devices
- This is safer than `privileged: true` but still grants broad USB access
- For production deployments, consider passing through only specific devices

**Privileged Mode**:
- Only use `privileged: true` if you encounter permission issues
- Privileged containers have full access to the host system
- Not recommended for production environments

## Testing Your Setup

After configuring USB passthrough:

```bash
# 1. Verify container can see USB bus
docker compose exec app ls /dev/bus/usb

# 2. Test SoapySDR detection
docker compose exec app SoapySDRUtil --find

# 3. Check application logs for radio initialization
docker compose logs -f app | grep -i radio

# 4. Use the web UI to discover and configure devices
# Navigate to http://your-server:5000/settings/radio
```

## Next Steps

Once USB passthrough is working:

1. **Discover Devices**: Use the "Discover Devices" button in `/settings/radio`
2. **Add Receivers**: Configure each SDR with its serial number for reliable identification
3. **Test Captures**: Trigger a test alert to verify radio captures are working
4. **Monitor Status**: Check the radio status page to see receiver signal locks

For additional help, see:
- [Radio Configuration Guide](sdr_setup_guide)
- [Troubleshooting Guide](HELP#troubleshooting)
- [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
