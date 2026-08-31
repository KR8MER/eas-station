# Hardware Configuration Quickstart Guide

This guide will help you quickly configure GPIO, OLED, VFD, and LED hardware components through the EAS Station™ web interface. **No command-line access required!**

## Overview

All hardware configuration can be done through the web interface at:
**Settings → Hardware Settings** (`/admin/hardware`)

Hardware settings are stored in the database — environment variables / `.env` keys are **not** read for GPIO, OLED, VFD, or LED configuration. After making changes, use the **Restart Now** button that appears to apply your changes instantly.

> **Upgrading from an older version?** Hardware configuration moved from `.env` environment variables to database-backed settings managed in the web UI. Legacy `.env` values are imported once during migration and ignored afterwards.

## GPIO Configuration (Relay/Transmitter Control)

### Enable GPIO

1. Navigate to **Settings → Hardware Settings** (`/admin/hardware`)
2. Open the **GPIO** tab
3. Set **Enable GPIO Control** to `true`
4. Configure your GPIO pins:
   - **Primary GPIO Pin**: `17` (BCM pin for main transmitter)
   - **Additional GPIO Pins**: Leave empty unless you have multiple relays
5. Click **Save Changes**
6. Click **Restart Now** when prompted

### GPIO Pin Reference

**BCM Pin Numbering** (Not Physical Pin Numbers):
- Pin 17 (BCM) = Physical Pin 11 (default for transmitter)
- Pin 27 (BCM) = Physical Pin 13 (backup transmitter)
- Pin 22 (BCM) = Physical Pin 15 (relay control)

**Example Configuration for Multiple Pins:**
```
27:Backup_TX:true,22:Warning_Light:true,23:Relay_1:false
```

Format: `PIN:NAME:ACTIVE_HIGH` (comma-separated)

### Verify GPIO is Working

1. Go to **Settings → Hardware → GPIO & Relays**
2. Test individual pins
3. Check **Logs → Hardware Service** for initialization messages

## OLED Display Configuration

### Enable OLED (Argon Industria SSD1306)

1. Navigate to **Settings → Hardware Settings** (`/admin/hardware`)
2. Open the **OLED Display** tab
3. Set **Enable OLED Module** to `true`
4. Configure settings:
   - **I2C Bus**: `1` (for Raspberry Pi 3/4/5)
   - **I2C Address**: `0x3C` (default for SSD1306)
   - **Auto-Start Screen Rotation**: `true`
5. Click **Save Changes**
6. Click **Restart Now** when prompted

### OLED Configuration Options

- **Width/Height**: Usually 128x64 for SSD1306
- **Rotation**: 0, 90, 180, or 270 degrees (match physical orientation)
- **Invert Colours**: Dark text on light background
- **Contrast**: 0-255 (128 is default)

### Verify OLED is Working

1. Check physical display - should show status screens
2. Check **Logs → Hardware Service** for:
   - "✅ OLED display initialized"
   - "✅ Screen manager started"

## VFD Display Configuration

### Option 1: Direct Serial Connection

1. Navigate to **Settings → Hardware Settings** (`/admin/hardware`)
2. Open the **VFD Display** tab
3. Set **Connection** to: `/dev/ttyUSB0` (or your serial port)
4. Set **Baud Rate** to: `38400` (check your VFD model)
5. Click **Save Changes**
6. Click **Restart Now**

### Option 2: Network Connection (Waveshare Adapter)

**Prerequisites:**
- Waveshare RS232/485 WiFi adapter configured
- Adapter has static IP (e.g., 192.168.8.122)
- TCP Server mode on port 10001

**Configuration:**
1. Navigate to **Settings → Hardware Settings** (`/admin/hardware`)
2. Open the **VFD Display** tab
3. Set **Connection** to: `socket://192.168.8.122:10001`
4. Set **Baud Rate** to: `38400`
5. Click **Save Changes**
6. Click **Restart Now**

See [Waveshare Setup Guide](../hardware/WAVESHARE_RS232_WIFI_SETUP.md) for detailed adapter configuration.

### Verify VFD is Working

1. Check physical display - should show text/graphics
2. Check **Logs → Hardware Service** for:
   - "Connected to Noritake VFD on socket://..." (network)
   - "Connected to Noritake VFD on /dev/ttyUSB0..." (serial)

## LED Sign Configuration

### Enable LED Sign (BetaBrite/Alpha)

1. Navigate to **Settings → Hardware Settings** (`/admin/hardware`)
2. Open the **LED Sign** tab
3. Configure connection:
   - **LED Sign IP Address**: `192.168.1.100` (your sign's IP)
   - **LED Sign Port**: `10001`
   - **Default LED Text**: 
     ```
     PUTNAM COUNTY,EMERGENCY MGMT,NO ALERTS,SYSTEM READY
     ```
4. Click **Save Changes**
5. Click **Restart Now**

### LED Sign Options

- **Serial Mode**: RS232 or RS485
- **Lines**: Comma-separated text for each line
- **Colors**: AMBER, RED, GREEN (depends on sign model)

## Zigbee Coordinator Configuration

### Enable Zigbee (Argon Industria V5 or USB Dongle)

#### Argon Industria V5 (Raspberry Pi 5 only)

Before configuring in EAS Station™, make sure the module is detected at the OS level:

1. Add to `/boot/firmware/config.txt` under `[all]`:
   ```ini
   dtoverlay=dwc2,dr_mode=host
   usb_max_current_enable=1
   ```
2. Install the Argon utilities and reboot:
   ```bash
   curl https://download.argon40.com/argon1v5.sh | bash
   sudo systemctl enable --now argononed.service
   sudo reboot
   ```
3. Verify the device appears: `ls /dev/ttyUSB*` (should show `/dev/ttyUSB0`)

> See [Argon40 Zigbee Setup Guide](../hardware/ARGON40_ZIGBEE_SETUP.md) for complete OS setup steps.

#### Configure in EAS Station™

1. Navigate to **Admin → Hardware Settings → Zigbee** tab
2. Check **Enable Zigbee Coordinator**
3. Set **Port** to:
   - `/dev/ttyUSB0` — Argon Industria V5, SONOFF dongle, most USB coordinators
   - `/dev/ttyACM0` — ConBee II and some other USB coordinators
   - `/dev/ttyAMA0` — GPIO-connected coordinators (rare)
4. Set **Baud Rate** to `115200` (correct for CC2652P-based coordinators)
5. Leave **Channel** at `15` (avoids 2.4 GHz Wi-Fi interference)
6. Leave **PAN ID** at `0x1A62` (or pick any unique hex value)
7. Click **Save Changes**
8. Click **Restart Now** when prompted

### Verify Zigbee is Working

1. Check **Logs → Hardware Service** for:
   - `✅ Zigbee coordinator configured on /dev/ttyUSB0 (channel 15, PAN ID 0x1A62)`
2. Visit **Admin → Zigbee** to see coordinator status and paired devices

### Troubleshoot Zigbee

| Symptom | Fix |
|---------|-----|
| `/dev/ttyUSB0` missing | Add `dtoverlay=dwc2,dr_mode=host` to `config.txt` under `[all]` and reboot |
| "port_open_failed" | Add `eas-station` user to `dialout` group: `sudo usermod -aG dialout eas-station` |
| "Zigbee disabled" | Enable in Admin → Hardware Settings → Zigbee tab |
| Wrong port | Check `ls /dev/ttyUSB* /dev/ttyACM*` to find the actual device |

---

## Service Restart Options

When you save changes, you'll see a **Restart Now** button. This restarts only the hardware service.

### Restart Specific Services

Use the browser console or API:

```javascript
// Restart hardware service only
fetch('/api/environment/restart-services', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ service: 'hardware' })
}).then(r => r.json()).then(console.log);

// Restart all services
fetch('/api/environment/restart-services', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ service: 'all' })
}).then(r => r.json()).then(console.log);
```

### Available Service Options

- `all` - Restart entire EAS Station™ stack
- `hardware` - GPIO, OLED, VFD, LED only
- `web` - Web interface only
- `poller` - Alert polling service
- `sdr` - SDR radio service
- `audio` - Audio monitoring service

## Troubleshooting

### GPIO Not Working

**Symptom**: No GPIO control, pins not responding

**Solutions**:
1. ✅ Check **Enable GPIO Control** is set to `true`
2. ✅ Verify pin numbers (BCM not physical!)
3. ✅ Check **Logs → Hardware Service** for errors
4. ✅ Ensure user has GPIO permissions (usually automatic)
5. ✅ Restart hardware service

**Check Logs:**
- "GPIO controller disabled (GPIO_ENABLED=false)" → Enable in settings
- "No GPIO pins configured" → Add EAS_GPIO_PIN
- "Failed to add GPIO pin X" → Check pin number/permissions

### OLED Not Working

**Symptom**: Blank OLED display, no initialization

**Solutions**:
1. ✅ Check **Enable OLED Module** is set to `true`
2. ✅ Verify I2C is enabled on Raspberry Pi
3. ✅ Check I2C address with `i2cdetect -y 1`
4. ✅ Verify physical connections (SDA, SCL, VCC, GND)
5. ✅ Check **Auto-Start Screen Rotation** is `true`

**Check Logs:**
- "OLED hardware not available" → Check I2C connection
- "OLED display disabled or unavailable" → Enable in settings
- I2C errors → Check wiring and I2C configuration

### VFD Shows Garbage

**Symptom**: Random characters, corrupted display

**Solutions**:
1. ✅ Check baud rate matches VFD (usually 38400)
2. ✅ Verify serial wiring (TX ↔ RX crossed)
3. ✅ Test with direct serial first, then network
4. ✅ For network: verify Waveshare adapter settings

### LED Sign Not Responding

**Symptom**: LED sign blank or not updating

**Solutions**:
1. ✅ Verify IP address is correct
2. ✅ Test connection: `ping 192.168.1.100`
3. ✅ Check port number (usually 10001)
4. ✅ Verify sign is in network mode (not serial)

### Restart Button Not Appearing

**Symptom**: Save works but no restart button

**Solutions**:
1. ✅ Refresh the page
2. ✅ Check browser console for JavaScript errors
3. ✅ Ensure you have system.configure permission
4. ✅ Use manual restart from CLI if needed (temporary)

## Hardware Compatibility

### Tested Hardware

| Component | Model | Status |
|-----------|-------|--------|
| GPIO | Raspberry Pi 3/4/5 GPIO | ✅ Supported |
| OLED | Argon Industria SSD1306 | ✅ Supported |
| VFD | Noritake GU140x32F-7000B | ✅ Supported |
| LED | BetaBrite Protocol | ✅ Supported |
| Network Serial | Waveshare RS232/485 WiFi | ✅ Supported |
| Zigbee | Argon Industria V5 (CC2652P) | ✅ Supported |
| Zigbee | SONOFF Zigbee 3.0 USB Dongle Plus | ✅ Supported |
| Zigbee | SMLIGHT SLZB-06 | ✅ Supported |

### Requirements

- **Raspberry Pi 3, 4, or 5** (for GPIO/I2C)
- **Python 3.13** with required packages
- **I2C enabled** for OLED (raspi-config → Interface Options → I2C)
- **Network access** for network-based devices

For how much board/RAM/thermal headroom a given number of SDR receivers
and EAS monitor sources actually needs, see
[Capacity and Sizing](../hardware/CAPACITY_AND_SIZING.md) — this section
only covers peripheral compatibility, not CPU/RAM planning.

## Quick Reference

### Default Settings

All values below are managed in **Settings → Hardware Settings** and stored in the `hardware_settings` database table:

| Setting | Default |
|---------|---------|
| GPIO enabled | `false` |
| Primary GPIO pin | `17` (BCM) |
| OLED enabled | `false` |
| OLED I2C bus / address | `1` / `0x3C` |
| Screen auto-start | `true` |
| VFD port (serial) | `/dev/ttyUSB0` |
| VFD port (network) | `socket://192.168.8.122:10001` |
| VFD baud rate | `38400` |
| LED sign IP / port | `192.168.1.100` / `10001` |

### Common I2C Addresses

- `0x3C` - SSD1306 OLED (most common)
- `0x3D` - SSD1306 OLED (alternate)
- `0x27` - PCF8574 I2C backpack
- `0x20-0x27` - Various I2C devices

Check with: `i2cdetect -y 1`

## Next Steps

After hardware is configured:

1. **Configure Screens**: Logs & Monitoring → Screen Management
2. **Test GPIO**: Settings → Hardware → GPIO & Relays
3. **Set Up Alerts**: Configure → Alert Sources
4. **Monitor Status**: Dashboard → System Health

## Related Documentation

- [Argon40 Zigbee Setup Guide](../hardware/ARGON40_ZIGBEE_SETUP.md)
- [Waveshare WiFi Adapter Setup](../hardware/WAVESHARE_RS232_WIFI_SETUP.md)
- [GPIO Pin Reference](https://github.com/KR8MER/eas-station/blob/main/app_utils/pi_pinout.py)
- [Environment Variables Reference](https://github.com/KR8MER/eas-station/blob/main/.env.example) — canonical list with descriptions
- [GPIO Guide](../hardware/GPIO_GUIDE.md) — pinout, wiring, and relay behaviour
- [Hardware Setup Helper](../hardware/HWSETUP_HELPER.md) — boot-time hardware probe

---

**Need Help?**
- Check **Logs → Hardware Service** for diagnostic messages
- GitHub Discussions: https://github.com/KR8MER/eas-station/discussions
- Report Issues: https://github.com/KR8MER/eas-station/issues
