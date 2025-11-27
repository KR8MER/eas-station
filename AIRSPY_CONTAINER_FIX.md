# AirSpy Container USB Stream Error Fix

## Problem Summary

The AirSpy device is being detected and opened successfully, but fails with `SOAPY_SDR_STREAM_ERROR` (-4) when trying to read samples from the USB stream.

**Error Log:**
```
Stream error for cr (failure #1, total stream errors: 24): SoapySDR readStream error -4: Stream reported a driver error (SOAPY_SDR_STREAM_ERROR)
```

## Root Cause

The container configuration is missing USB buffer memory limits (memlock) needed for real-time USB streaming. USB devices require locked memory buffers to prevent kernel from swapping them out during transfers.

## Solutions

### Option 1: Add USB Memory Lock Limits (Recommended)

Add the following to your `docker-compose.yml` under the `sdr-service` section:

```yaml
sdr-service:
  # ... existing configuration ...

  ulimits:
    memlock:
      soft: -1
      hard: -1

  # Optional: Increase shared memory for USB buffers
  shm_size: '256mb'
```

This allows unlimited locked memory for USB DMA transfers.

### Option 2: Reduce Buffer Sizes

If memory limits can't be increased, reduce the buffer sizes in the code (already implemented in this fix):

- Stream buffer: 16384 samples (already optimized)
- Read buffer: 16384 samples (already optimized)
- AirSpy uses internal buffering, so `bufflen` parameter is not needed

### Option 3: Use Host Network Mode (Testing Only)

For testing purposes only, you can use host network mode which bypasses some container USB restrictions:

```yaml
sdr-service:
  network_mode: "host"
  # Remove 'networks' section when using host mode
```

**Warning:** This reduces container isolation and is not recommended for production.

## Additional Optimizations

### 1. USB Device-Specific Passthrough

Instead of passing `/dev/bus/usb` entirely, you can pass the specific device:

```yaml
devices:
  - /dev/bus/usb/001/XXX:/dev/bus/usb/001/XXX  # Replace XXX with actual device number
```

Find your device number with: `lsusb -t` or `lsusb -v | grep -i airspy`

### 2. USB udev Rules (Host Configuration)

Create `/etc/udev/rules.d/52-airspy.rules` on the HOST system:

```bash
# AirSpy
SUBSYSTEMS=="usb", ATTRS{idVendor}=="1d50", ATTRS{idProduct}=="60a1", MODE:="0666", GROUP="plugdev"
```

Then reload udev:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 3. Check USB Power Management

Disable USB autosuspend for AirSpy on the HOST:

```bash
# Find USB device path
lsusb -t | grep -i airspy

# Disable autosuspend (replace bus/device numbers)
echo -1 | sudo tee /sys/bus/usb/devices/1-1/power/autosuspend_delay_ms
echo on | sudo tee /sys/bus/usb/devices/1-1/power/control
```

### 4. Verify USB 2.0/3.0 Compatibility

AirSpy R2 works best on USB 2.0 ports. If using USB 3.0, ensure backward compatibility is enabled.

## Code Changes Made

1. **Removed `bufflen` for AirSpy** - AirSpy driver manages buffers internally
2. **Keep `bufflen` for RTL-SDR** - RTL-SDR driver supports and benefits from explicit buffer sizing
3. **Fixed exception scoping bug** - Resolved variable scope issue in fallback logic
4. **Improved fallback logic** - Avoid redundant connection attempts for AirSpy

## Testing

After applying container configuration changes:

1. Restart the containers:
   ```bash
   docker-compose down
   docker-compose up -d sdr-service
   ```

2. Monitor logs:
   ```bash
   docker-compose logs -f sdr-service
   ```

3. Look for:
   - ✓ "Found 1 SoapySDR device(s): ['AirSpy One [...]']"
   - ✓ "Successfully opened device"
   - ✓ Reduced or eliminated stream errors

## Expected Results

- **Before fix:** Frequent SOAPY_SDR_STREAM_ERROR (-4), 24+ stream errors
- **After fix:** Device opens cleanly, minimal or zero stream errors

## References

- [SoapySDR GitHub](https://github.com/pothosware/SoapySDR)
- [SoapyAirspy GitHub](https://github.com/pothosware/SoapyAirspy)
- [Docker USB Device Best Practices](https://docs.docker.com/engine/reference/run/#runtime-privilege-and-linux-capabilities)
