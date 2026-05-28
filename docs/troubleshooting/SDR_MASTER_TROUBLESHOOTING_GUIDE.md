# SDR Master Troubleshooting Guide

**Complete diagnostic and troubleshooting guide for SDR issues in EAS Station™**

## Quick Start Diagnostic

If your SDR is not working, start here:

```bash
# Run the automated diagnostic script
python3 scripts/sdr_diagnostics.py

```

This will check:
- ✅ SoapySDR installation
- ✅ Connected SDR devices
- ✅ Driver availability
- ✅ Common configuration issues

---

## Table of Contents

1. [Quick Diagnostic Checklist](#quick-diagnostic-checklist)
2. [Common Issues & Solutions](#common-issues--solutions)
3. [Step-by-Step Troubleshooting](#step-by-step-troubleshooting)
4. [Collecting Diagnostic Information](#collecting-diagnostic-information)
5. [Hardware-Specific Issues](#hardware-specific-issues)
6. [Advanced Diagnostics](#advanced-diagnostics)
7. [Getting Help](#getting-help)

---

## Quick Diagnostic Checklist

Run through this checklist before proceeding with detailed troubleshooting:

### ✅ Hardware Checks

- [ ] SDR is plugged into a working USB port (try different ports)
- [ ] USB cable is not damaged (try a different cable)
- [ ] LED on SDR is lit (if equipped)
- [ ] Antenna is connected properly
- [ ] Device appears in `lsusb` output

### ✅ Software Checks

- [ ] SoapySDR is installed (`python3 -c "import SoapySDR"`)
- [ ] Device drivers are installed (rtlsdr/airspy modules)
- [ ] No permission errors in logs
- [ ] Configuration is correct (frequency in Hz, not MHz)

### ✅ Configuration Checks

- [ ] Receiver is enabled in database
- [ ] Auto-start is enabled
- [ ] Frequency is in Hz (multiply MHz by 1,000,000)
- [ ] Sample rate is valid for your hardware
- [ ] Gain is set (not NULL or 0)
- [ ] Modulation type matches signal (NFM for NOAA)

---

## Common Issues & Solutions

### Issue: "No SDR Devices Found"

**Symptoms:**
- `SoapySDRUtil --find` returns empty list
- "No radio receivers configured" in logs
- Web UI shows no devices in discovery

**Solutions:**

1. **Check USB connection:**
   ```bash
   lsusb | grep -E "RTL|Airspy|Realtek"
   ```
   - If nothing appears, try a different USB port or cable
   - Avoid unpowered USB hubs

   ```bash
   ```

3. **Check driver installation (Native):**
   ```bash
   # Ubuntu/Debian
   sudo apt install soapysdr-module-rtlsdr soapysdr-module-airspy
   
   # Verify installation
   SoapySDRUtil --info
   ```

4. **Check USB permissions (Linux):**
   ```bash
   # Add user to plugdev group
   sudo usermod -aG plugdev $USER
   
   # Copy udev rules for RTL-SDR
   sudo wget -O /etc/udev/rules.d/20-rtlsdr.rules https://raw.githubusercontent.com/osmocom/rtl-sdr/master/rtl-sdr.rules
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   
   # Replug the device
   ```

---

### Issue: "No Audio from SDR"

**Symptoms:**
- SDR shows "Locked" status
- IQ samples are being captured
- No audio output from speakers

**Solutions:**

1. **Check gain settings:**
   ```sql
   -- Query current gain
   SELECT identifier, gain FROM radio_receivers;
   
   -- Set appropriate gain
   UPDATE radio_receivers SET gain = 40.0 WHERE driver = 'rtlsdr';
   UPDATE radio_receivers SET gain = 21.0 WHERE driver = 'airspy';
   ```

2. **Check audio output is enabled:**
   ```sql
   UPDATE radio_receivers SET audio_output = true WHERE identifier = 'your-receiver';
   ```

3. **Check modulation type:**
   - NOAA Weather: Use `NFM` (Narrow FM)
   - Broadcast FM: Use `WFM` (Wide FM)
   - AM stations: Use `AM`
   
   ```sql
   UPDATE radio_receivers SET modulation_type = 'NFM' WHERE identifier = 'your-receiver';
   ```

4. **Check audio source configuration:**
   ```sql
   SELECT * FROM audio_source_configs WHERE source_type = 'redis_sdr';
   ```
   - Ensure `enabled = true` and `auto_start = true`

5. **Check audio service logs:**
   ```bash
   ```

---

### Issue: "SDR Stream Stalls After 5-6 Seconds"

**Symptoms:**
- Audio plays for 5-6 seconds then stops
- Web player shows "Buffering..." and never recovers
- Icecast mount point not visible or shows as disconnected
- No errors in logs until timeout

**Root Cause:**
This was caused by incorrect use of FFmpeg `-re` flag for live hardware capture. The `-re` flag throttles stdin reads to real-time rate, which creates fatal backpressure when used with live SDR audio that's already real-time.

**How the Bug Manifested:**
1. SDR demodulates audio in real-time → PCM chunks
2. Feed loop writes chunks to FFmpeg stdin
3. FFmpeg with `-re` throttles stdin reads to exactly real-time rate
4. Pipe buffer (64KB) fills in <1 second
5. `stdin.write()` blocks, feed loop freezes
6. Audio queue fills, stream dies after 5-6 seconds

**Solutions:**

1. **Verify `-re` flag is NOT used for SDR sources:**
   ```bash
   # Check audio-service logs during startup
   grep "Using -re flag\|NOT using -re" /var/log/eas-station/audio-service.log
   
   # Should see for SDR sources:
   # "NOT using -re flag for RedisSDRSourceAdapter (live hardware)"
   ```

2. **Check version** (fixed in current development version):
   ```bash
   cat /opt/eas-station/VERSION
   # Should be >= 2.42.6
   ```
   
   If using older version, update:
   ```bash
   cd /opt/eas-station
   git pull
   sudo ./update.sh
   ```

3. **Manual verification** of conditional logic:
   ```python
   # In app_core/audio/icecast_output.py, _start_ffmpeg() method
   # Should have conditional logic to detect source type:
   
   use_re_flag = False
   source_type_name = type(self.audio_source).__name__
   
   # SDR sources should NOT use -re
   if 'SDR' in source_type_name or 'sdr' in source_type_name.lower():
       use_re_flag = False
       logger.debug(f"NOT using -re flag for {source_type_name}")
   
   # HTTP/Stream sources SHOULD use -re
   elif source_type_name in ('StreamSourceAdapter', 'IcecastIngestSource'):
       use_re_flag = True
       logger.debug(f"Using -re flag for {source_type_name}")
   ```

4. **Test streaming duration:**
   ```bash
   # Play stream for 60+ seconds
   mpv http://localhost:8000/sdr-{receiver-id}.mp3
   
   # Monitor for continuous playback without stalling
   ```

5. **Check Icecast mount status:**
   ```bash
   # Access Icecast admin page
   http://localhost:8000/admin/
   
   # Verify mount point appears and shows "Connected"
   # Should see: /sdr-{receiver-id}.mp3
   ```

**Why `-re` is Needed for HTTP Streams:**
- HTTP/Icecast ingest sources need `-re` for correct resampling
- Without `-re`, FFmpeg processes network streams too fast
- Timing relationships are lost, causing incorrect audio resampling
- This is CORRECT behavior for network sources, WRONG for SDR

**Prevention:**
- Always test SDR streams for >60 seconds after any FFmpeg changes
- Monitor logs for `-re` flag usage during startup
- Check Icecast mount points appear within 10 seconds of starting

**Related Documentation:**
- `docs/architecture/SDR_SERVICE_ARCHITECTURE.md` - Section "Icecast Streaming Architecture"
- `docs/reference/CHANGELOG.md` - Version 2.42.5 and 2.42.6 entries

---

### Issue: "Wrong Frequency / Not Tuning Correctly"

**Symptoms:**
- Noise instead of expected signal
- Web UI shows wrong frequency
- Can't hear the station you're trying to receive

**Solutions:**

1. **Verify frequency is in Hz, not MHz:**
   ```sql
   -- Check current frequency
   SELECT identifier, frequency_hz, frequency_hz / 1000000.0 AS frequency_mhz 
   FROM radio_receivers;
   
   -- Correct example for NOAA WX7 (162.55 MHz)
   UPDATE radio_receivers SET frequency_hz = 162550000 WHERE identifier = 'noaa-wx7';
   ```

2. **Verify you have the correct frequency for your area:**
   - NOAA Weather: https://www.weather.gov/nwr/station_listing
   - FM Radio: Check local station listings
   - Use online resources like radio-locator.com

3. **Check for frequency offset (RTL-SDR):**
   - RTL-SDR dongles may have frequency drift
   - Typical offset: ±50 ppm (parts per million)
   - Set `ppm_correction` in receiver config if needed

4. **Test with known-strong station:**
   - Try a local FM broadcast station first
   - If that works, issue is likely weak signal or wrong frequency

---

### Issue: "SDR Service Crashes or Restarts"

**Symptoms:**
- "Device or resource busy" errors
- "Permission denied" errors

**Solutions:**

1. **Check if device is in use:**
   ```bash
   # Linux: Check for other processes using the device
   lsof /dev/bus/usb/*/*
   
   # Stop other SDR software (GQRX, CubicSDR, etc.)
   ```

   ```yaml
   services:
     sdr-service:
       devices:
         - /dev/bus/usb:/dev/bus/usb  # Should be present
       privileged: true  # May be needed for some devices
   ```

3. **Check for sample rate overflow:**
   ```bash
   ```
   - If present, try lower sample rate (e.g., 2.0 MHz instead of 2.4 MHz)

4. **Check power issues:**
   - Use powered USB hub for better stability
   - Some SDRs draw significant power
   - Try different USB ports (USB 3.0 ports often have more power)

---

### Issue: "Airspy Not Working"

**Symptoms:**
- Airspy detected but configuration fails
- Sample rate errors
- "Invalid sample rate" warnings

**Solutions:**

1. **Use only supported sample rates:**
   - Airspy R2: **2,500,000 or 10,000,000 Hz ONLY**
   - Airspy Mini: Check device specifications
   
   ```sql
   -- Correct for Airspy R2
   UPDATE radio_receivers 
   SET sample_rate = 2500000  -- or 10000000
   WHERE driver = 'airspy';
   ```

2. **Check linearity mode vs sensitivity mode:**
   - Linearity mode: Better for strong signals (default)
   - Sensitivity mode: Better for weak signals
   - EAS Station™ uses linearity mode by default

3. **Check firmware version:**
   ```bash
   # Check Airspy firmware
   ```

---

### Issue: "Configuration Not Saving"

**Symptoms:**
- Changes in web UI don't persist
- Database updates don't take effect
- Receiver keeps reverting to old settings

**Solutions:**

1. **Restart services after configuration changes:**
   ```bash
   ```

2. **Check database connection:**
   ```bash
   ```

3. **Verify changes were saved:**
   ```bash
   ```

---

## Step-by-Step Troubleshooting

Use this systematic approach when the quick fixes don't work:

### Step 1: Verify Hardware Detection

```bash
# On host system
lsusb | grep -E "RTL|Airspy|Realtek"

# Expected output for RTL-SDR:
# Bus 001 Device 005: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T

# Expected output for Airspy:
# Bus 001 Device 006: ID 1d50:60a1 OpenMoko, Inc. Airspy
```

**If device not found:**
- Try different USB port
- Try different USB cable
- Check if device works on another computer
- Device may be faulty

### Step 2: Verify SoapySDR Detection

```bash

# Expected output for RTL-SDR:
# [
#   {
#     "driver": "rtlsdr",
#     "label": "Generic RTL2832U :: 00000001",
#     "serial": "00000001"
#   }
# ]
```

**If no devices found:**
- Check driver installation
- Check USB permissions

### Step 3: Test Basic Capture

```bash
# Test with diagnostic script

# Should show:
# ✓ Successfully captured X samples!
# Average signal magnitude: X.XXXX
```

**If capture fails:**
- Device may be in use by another process
- Driver issue
- Hardware fault

### Step 4: Check Service Status

```bash
# Check all services

# All should show "Up" status
# If sdr-service is restarting, check logs:
```

### Step 5: Verify Database Configuration

```bash
\x on
SELECT 
  id,
  identifier,
  display_name,
  driver,
  frequency_hz,
  frequency_hz / 1000000.0 AS frequency_mhz,
  sample_rate,
  gain,
  modulation_type,
  audio_output,
  enabled,
  auto_start
FROM radio_receivers;
EOF
```

**Verify:**
- `enabled = t` (true)
- `auto_start = t` (true)
- `frequency_hz` is a large number (> 1,000,000)
- `sample_rate` is appropriate (2,400,000 typical)
- `gain` is set (not null)
- `audio_output = t` if you want to hear audio

### Step 6: Check IQ Sample Flow

```bash
# Monitor Redis pub/sub channel

# In Redis CLI:
SUBSCRIBE sdr:samples:*

# You should see periodic messages if SDR is working
# Press Ctrl+C to exit
```

**If no messages:**
- SDR service not publishing
- Receiver not started
- Check sdr-service logs

### Step 7: Check Audio Processing

```bash
# Check audio service is processing

# Expected:
# Creating NFM demodulator: 2400000Hz IQ → 44100Hz audio
# ✅ First audio chunk decoded for receiver-1: 4096 samples
```

---

## Collecting Diagnostic Information

If you need to report an issue or ask for help, collect this information:

### Automated Collection Script

Save this as `collect_sdr_diagnostics.sh`:

```bash
#!/bin/bash
# SDR Diagnostic Information Collection Script

OUTPUT_FILE="sdr_diagnostics_$(date +%Y%m%d_%H%M%S).txt"

echo "Collecting SDR diagnostic information..."
echo "Output will be saved to: $OUTPUT_FILE"
echo ""

{
  echo "============================================"
  echo "EAS Station™ SDR Diagnostics"
  echo "Date: $(date)"
  echo "============================================"
  echo ""
  
  echo "### HOST SYSTEM INFO ###"
  echo "Hostname: $(hostname)"
  echo "OS: $(uname -a)"
  echo ""
  
  echo "### USB DEVICES ###"
  lsusb
  echo ""
  
  echo "### SDR DEVICE ENUMERATION ###"
  echo ""
  
  echo "### CONTAINER STATUS ###"
  echo ""
  
  echo "### SDR SERVICE LOGS (last 50 lines) ###"
  echo ""
  
  echo "### AUDIO SERVICE LOGS (last 50 lines) ###"
  echo ""
  
  echo "### DATABASE: RADIO RECEIVERS ###"
    SELECT 
      id, identifier, driver, frequency_hz, 
      sample_rate, gain, modulation_type, 
      audio_output, enabled, auto_start 
    FROM radio_receivers;
  " 2>&1 || echo "Failed to query database"
  echo ""
  
  echo "### DATABASE: AUDIO SOURCES ###"
    SELECT id, name, source_type, config_params, enabled, auto_start 
    FROM audio_source_configs;
  " 2>&1 || echo "Failed to query database"
  echo ""
  
  echo "### REDIS CONNECTION TEST ###"
  echo ""
  
  echo "### SDR DIAGNOSTICS SCRIPT ###"
  echo ""
  
  echo "============================================"
  echo "Diagnostic collection complete"
  echo "============================================"
  
} | tee "$OUTPUT_FILE"

echo ""
echo "✓ Diagnostics saved to: $OUTPUT_FILE"
echo ""
echo "Please provide this file when reporting SDR issues."
```

Make it executable and run:

```bash
chmod +x collect_sdr_diagnostics.sh
./collect_sdr_diagnostics.sh
```

### Manual Collection

If you can't run the script, collect this information manually:

1. **Hardware Information:**
   ```bash
   lsusb | grep -E "RTL|Airspy|Realtek"
   ```

2. **SoapySDR Device Detection:**
   ```bash
   ```

3. **Container Status:**
   ```bash
   ```

4. **Service Logs:**
   ```bash
   ```

5. **Database Configuration:**
   ```bash
   ```

6. **Diagnostic Script Output:**
   ```bash
   ```

---

## Hardware-Specific Issues

### RTL-SDR

**Common Issues:**

1. **Frequency Drift:**
   - RTL-SDR dongles have varying crystal accuracy
   - Use `ppm_correction` setting to compensate
   - Typical range: -50 to +50 ppm

2. **Overload:**
   - Strong nearby signals can overload receiver
   - Symptoms: Distortion, false signals
   - Solution: Reduce gain, use bandpass filter

3. **USB Power:**
   - Some dongles are power-hungry
   - Symptoms: Disconnects, unstable operation
   - Solution: Use powered USB hub

**Recommended Settings:**
```sql
-- NOAA Weather (RTL-SDR v3)
INSERT INTO radio_receivers (
  identifier, driver, frequency_hz, sample_rate, 
  gain, modulation_type, audio_output, enabled, auto_start
) VALUES (
  'noaa-wx7', 'rtlsdr', 162550000, 2400000,
  40.0, 'NFM', true, true, true
);
```

### Airspy

**Common Issues:**

1. **Sample Rate Restrictions:**
   - Airspy R2 only supports 2.5 MHz or 10 MHz
   - Using any other rate will fail
   - No partial rates (e.g., 2.4 MHz won't work)

2. **Gain Settings:**
   - Use linearity mode (21 dB) for strong signals
   - Use sensitivity mode for weak signals
   - EAS Station™ defaults to linearity mode

3. **Firmware:**
   - Ensure latest firmware is installed
   - Check with `airspy_info` command

**Recommended Settings:**
```sql
-- NOAA Weather (Airspy R2)
INSERT INTO radio_receivers (
  identifier, driver, frequency_hz, sample_rate,
  gain, modulation_type, audio_output, enabled, auto_start
) VALUES (
  'noaa-wx7', 'airspy', 162550000, 2500000,
  21.0, 'NFM', true, true, true
);
```

### SDRplay

**Note:** SDRplay support requires additional configuration:

1. **Install SDRplay API:**
   - Download from SDRplay website
   - Install API on host system

2. **SoapySDR Module:**
   - Install `soapysdr-module-sdrplay`
   - May require building from source

---

## Advanced Diagnostics

### Low-Level Hardware Test

Test SDR at the lowest level:

```bash
# For RTL-SDR

# For Airspy
```

### Stream Performance Test

Check if system can handle sample rate:

```bash
# Capture samples to /dev/null (discard)

# Check for overruns in dmesg
dmesg | grep -i usb | tail -20
```

### Signal Strength Analysis

Measure actual signal strength:

```bash
import SoapySDR
import numpy as np
import time

# Open device
sdr = SoapySDR.Device({'driver': 'rtlsdr'})
sdr.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, 2400000)
sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, 162550000)
sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, 40.0)

# Setup stream
stream = sdr.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32)
sdr.activateStream(stream)
time.sleep(0.1)

# Capture samples
buffer = np.zeros(4096, dtype=np.complex64)
result = sdr.readStream(stream, [buffer], len(buffer))

if result.ret > 0:
    magnitude = np.mean(np.abs(buffer[:result.ret]))
    power_db = 20 * np.log10(magnitude) if magnitude > 0 else -100
    print(f"Signal magnitude: {magnitude:.6f}")
    print(f"Signal power: {power_db:.1f} dB")
    
    if magnitude < 0.001:
        print("⚠ Very weak signal - check antenna and frequency")
    elif magnitude > 0.5:
        print("⚠ Very strong signal - may be overloading, reduce gain")
    else:
        print("✓ Signal level looks reasonable")
else:
    print(f"✗ Read failed: {result.ret}")

# Cleanup
sdr.deactivateStream(stream)
sdr.closeStream(stream)
EOF
```

### Network Performance Check

For Redis-based IQ sample streaming:

```bash
# Monitor Redis performance

# Monitor Redis memory usage

# Monitor Redis pub/sub
```

---

## Getting Help

### Before Asking for Help

1. ✅ Run the diagnostic collection script
2. ✅ Check all items in Quick Diagnostic Checklist
3. ✅ Read through Common Issues & Solutions
4. ✅ Check existing documentation:
   - [SDR Setup Guide](../hardware/SDR_SETUP.md)
   - [SDR Service Architecture](../architecture/SDR_SERVICE_ARCHITECTURE.md)
   - [Frequency Validation](../frontend/SDR_FREQUENCY_VALIDATION.md)

### Providing Information

When asking for help, include:

1. **Hardware:**
   - SDR model (e.g., "RTL-SDR v3", "Airspy R2")
   - Antenna type
   - USB connection (direct, hub, powered/unpowered)
   - Operating system and version

2. **Software:**

3. **Configuration:**
   - Receiver configuration from database
   - Frequency you're trying to receive
   - Expected vs actual behavior

4. **Diagnostic Outputs:**
   - Output from `collect_sdr_diagnostics.sh` script
   - Relevant log excerpts
   - Error messages (complete, not truncated)

5. **What You've Tried:**
   - Steps already taken
   - Results of each step
   - Any workarounds that partially worked

### Where to Get Help

- **GitHub Issues:** https://github.com/KR8MER/eas-station/issues
- **GitHub Discussions:** https://github.com/KR8MER/eas-station/discussions
- **Documentation:** [docs/README.md](../README.md)

---

## Related Documentation

- **[SDR Setup Guide](../hardware/SDR_SETUP.md)** - Initial SDR configuration
- **[SDR Service Architecture](../architecture/SDR_SERVICE_ARCHITECTURE.md)** - How SDR service works
- **[SDR Frequency Validation](../frontend/SDR_FREQUENCY_VALIDATION.md)** - Frequency/sample-rate constraints
- **[Diagnostic Scripts README](../../scripts/diagnostics/README.md)** - Available diagnostic tools

---

## Quick Reference

### Most Common Fixes

1. **Frequency in MHz instead of Hz:**
   ```sql
   UPDATE radio_receivers SET frequency_hz = 162550000 WHERE identifier = 'your-receiver';
   ```

2. **Gain not set:**
   ```sql
   UPDATE radio_receivers SET gain = 40.0 WHERE driver = 'rtlsdr';
   ```

3. **Audio output disabled:**
   ```sql
   UPDATE radio_receivers SET audio_output = true WHERE identifier = 'your-receiver';
   ```

4. **Service not restarted after config change:**
   ```bash
   ```

5. **Device permissions:**
   ```bash
   sudo usermod -aG plugdev $USER
   # Then log out and back in
   ```

### Diagnostic Commands

```bash
# Quick status check

# Device detection
lsusb | grep -E "RTL|Airspy|Realtek"

# Full diagnostics

# Check logs

# Database check

# Test capture
```

---

**Last Updated:** May 2026  
**Tracks:** EAS Station™ 2.8x release line
