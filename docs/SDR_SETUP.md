# SDR Device Setup for Docker Deployment

This guide explains how to configure USB SDR device passthrough for the EAS Station Docker containers.

## Quick Start

### 1. Detect Your SDR Devices

Run the detection script on your **host machine** (not in the container):

```bash
sudo ./scripts/detect-sdr-devices.sh
```

This will:
- Detect all connected SDR devices (RTL-SDR, Airspy, HackRF, etc.)
- Show their USB bus/device paths
- Generate ready-to-use docker-compose.yml configuration
- Provide udev rules for permanent access

### 2. Configure Docker Compose

The script will output configuration like this:

```yaml
# Option 1: Passthrough all USB devices (RECOMMENDED for dedicated hardware)
devices:
  - /dev/bus/usb:/dev/bus/usb  # All USB devices

# Option 2: Specific device passthrough (more secure, but device IDs change)
devices:
  - /dev/bus/usb/001/004:/dev/bus/usb/001/004  # Your Airspy device
```

**For a dedicated SDR station**, use **Option 1** - it's simpler and handles device reconnections automatically.

### 3. Apply Configuration

Your `docker-compose.yml` already includes USB device passthrough. If you need to modify it:

```yaml
services:
  app:
    devices:
      - /dev/bus/usb:/dev/bus/usb  # Already configured!
    # ... rest of configuration
```

This configuration is already present on lines 51, 89, and 135 of your docker-compose.yml.

### 4. Restart Containers

```bash
docker-compose down
docker-compose up -d
```

### 5. Test SDR Detection

1. Open the EAS Station web interface (http://localhost or your server IP)
2. Navigate to **Settings → Radio**
3. Click **"Discover Devices"**
4. You should see your SDR device(s) listed
5. Click **"Add This Device"** to configure

## Troubleshooting

### Problem: No devices found when clicking "Discover Devices"

**Solutions:**

1. **Check USB device passthrough:**
   ```bash
   # On host machine
   ls -la /dev/bus/usb/
   ```

2. **Verify Docker has USB access:**
   ```bash
   # Inside container
   docker exec -it eas-station-app-1 ls -la /dev/bus/usb/
   ```

3. **Check for conflicting kernel drivers:**
   ```bash
   # On host machine
   lsmod | grep -E "rtl28|dvb_usb"
   ```

   If you see `dvb_usb_rtl28xxu` or similar, blacklist them:
   ```bash
   echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-sdr.conf
   echo 'blacklist rtl2832' | sudo tee -a /etc/modprobe.d/blacklist-sdr.conf
   echo 'blacklist rtl2830' | sudo tee -a /etc/modprobe.d/blacklist-sdr.conf
   sudo update-initramfs -u
   sudo reboot
   ```

4. **Check USB permissions:**
   ```bash
   # On host machine - device should be accessible
   ls -la /dev/bus/usb/001/004  # Replace with your device path
   ```

### Problem: "Unable to open SoapySDR device" error

This was a bug that has been fixed. Make sure you're running the latest code:

```bash
cd /home/user/eas-station
git pull origin main
docker-compose build
docker-compose up -d
```

### Problem: Device disappears after unplugging/replugging

**Cause:** Specific device paths (e.g., `/dev/bus/usb/001/004`) change when devices are reconnected.

**Solutions:**

1. **Use broad USB passthrough (recommended):**
   ```yaml
   devices:
     - /dev/bus/usb:/dev/bus/usb
   ```

2. **Create udev rules for stable device names:**

   Run the detection script to get udev rules:
   ```bash
   sudo ./scripts/detect-sdr-devices.sh
   ```

   It will generate rules like:
   ```bash
   # For Airspy
   SUBSYSTEM=="usb", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="60a1", MODE="0666", GROUP="plugdev"
   ```

   Save to `/etc/udev/rules.d/52-sdr.rules` and reload:
   ```bash
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

### Problem: Permission denied errors

**Solution 1: Run container with proper USB permissions (current setup)**

Your docker-compose.yml already includes necessary capabilities:
```yaml
cap_add:
  - SYS_RAWIO  # Required for device access
```

**Solution 2: Create udev rules (see above)**

**Solution 3: Add user to plugdev group:**
```bash
sudo usermod -a -G plugdev $USER
# Log out and back in
```

## Advanced Configuration

### Multiple SDR Devices

If you have multiple SDRs (e.g., one for NOAA weather, one for FM broadcast):

1. The current configuration passes through ALL USB devices
2. Each SDR will be detected separately in Settings → Radio
3. Add each device with a descriptive name
4. Configure different frequencies for each

Example:
- **Airspy #1:** NOAA Weather (162.550 MHz)
- **RTL-SDR #1:** FM Broadcast (95.5 MHz)

### Container Privileges

The current setup uses:
- `devices: /dev/bus/usb:/dev/bus/usb` - USB device access
- `cap_add: SYS_RAWIO` - Raw I/O capability for direct hardware access
- `security_opt: no-new-privileges:true` - Security hardening

This is the recommended configuration for SDR devices.

### Monitoring SDR Status

Check if SoapySDR can see your devices inside the container:

```bash
# Enter the container
docker exec -it eas-station-app-1 bash

# Check SoapySDR
python3 -c "import SoapySDR; print(SoapySDR.Device.enumerate())"
```

Expected output:
```python
[{'driver': 'airspy', 'serial': 'a74068c82f341893', 'label': 'Airspy ...', ...}]
```

## Supported SDR Devices

The Docker image includes drivers for:

- **RTL-SDR** (RTL2832U based dongles)
- **Airspy** (Airspy R2, Mini, HF+)
- **HackRF** (HackRF One)

Additional drivers can be added by modifying `SOAPYSDR_DRIVERS` in docker-compose.yml:

```yaml
build:
  args:
    SOAPYSDR_DRIVERS: ${SOAPYSDR_DRIVERS:-rtlsdr,airspy,hackrf}
```

Then rebuild:
```bash
docker-compose build
```

## Performance Tips

1. **Use USB 3.0 ports** when available for higher sample rates
2. **Avoid USB hubs** - connect SDRs directly to motherboard USB ports
3. **Check for USB dropouts:**
   ```bash
   dmesg | grep -i usb
   ```

4. **Monitor CPU usage** - high sample rates (>2.5 MHz) require more processing

## Security Considerations

**For dedicated SDR hardware:**
- Using `/dev/bus/usb:/dev/bus/usb` is safe and recommended
- The container only runs SDR software
- No other sensitive USB devices are connected

**For shared systems:**
- Consider specific device passthrough instead of broad USB access
- Use udev rules to restrict access by vendor/product ID
- Monitor container logs for suspicious activity

## Need Help?

1. Check Settings → Radio → Diagnostics for SoapySDR status
2. Review container logs: `docker-compose logs app`
3. Run the detection script: `sudo ./scripts/detect-sdr-devices.sh`
4. Check GitHub issues: https://github.com/KR8MER/eas-station/issues

## Reference

- SoapySDR Wiki: https://github.com/pothosware/SoapySDR/wiki
- RTL-SDR Guide: https://www.rtl-sdr.com/
- Airspy Documentation: https://airspy.com/
