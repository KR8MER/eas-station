# Hardware Setup Guide

This guide explains how to enable and configure hardware peripherals in EAS Station, including GPIO pins, displays (OLED, LED signs, VFD), and Zigbee coordinators.

## ⚠️ Important: Hardware is Disabled by Default

**All hardware features are disabled by default** for safety and compatibility. You must explicitly enable each feature you want to use via the web UI at **Admin → Hardware Settings**.

## Quick Start

1. Navigate to **Admin → Hardware Settings** in the web UI
2. Click on the tab for the hardware you want to configure (GPIO, OLED, LED, VFD, Zigbee)
3. Check the **"Enable"** checkbox for that hardware
4. Configure the specific settings (pins, ports, addresses, etc.)
5. Click **"Save Settings"**
6. Restart the hardware service: `sudo systemctl restart eas-hardware-service`
7. Check logs: `sudo journalctl -u eas-hardware-service -f`

## GPIO Configuration

### Overview
GPIO (General Purpose Input/Output) pins allow EAS Station to control external hardware like transmitter PTT (Push-To-Talk), relays, sirens, and other devices.

### Requirements
- Raspberry Pi (any model with GPIO header)
- Python packages: `gpiozero`, `lgpio` (installed by default)
- User permissions: `sudo usermod -a -G gpio eas-station`

### Enabling GPIO

1. Open **Admin → Hardware Settings → GPIO Tab**
2. Check **"Enable GPIO"**
3. Configure pin mappings in the JSON editor:

```json
{
  "17": {
    "name": "EAS Transmitter PTT",
    "active_high": true,
    "hold_seconds": 5.0,
    "watchdog_seconds": 300.0
  },
  "27": {
    "name": "Backup Relay",
    "active_high": true,
    "hold_seconds": 2.0,
    "watchdog_seconds": 60.0
  }
}
```

4. (Optional) Configure behavior matrix to specify when pins activate:

```json
{
  "17": ["PLAYOUT", "DURATION_OF_ALERT"],
  "27": ["INCOMING_ALERT"]
}
```

5. Click **"Save Settings"**

### Pin Numbering
- Use **BCM (Broadcom)** pin numbers (not physical pin numbers)
- Valid range: GPIO 2-27 (BCM numbering)
- **Reserved pins (when OLED enabled)**: GPIO 2, 3, 4, 14
  - These pins are in the valid range but **unavailable when OLED is enabled**
  - GPIO 2 (SDA) and 3 (SCL): I2C communication
  - GPIO 4: OLED button input
  - GPIO 14: OLED power/control
  - If OLED is disabled, these pins become available for general GPIO use

### Troubleshooting GPIO

**"GPIO controller DISABLED"**
- Enable in Admin → Hardware Settings → GPIO tab

**"No GPIO pins configured"**
- Add pin mappings in the GPIO pin map JSON field

**"GPIO libraries not installed"**
```bash
sudo apt-get install python3-lgpio python3-gpiozero
pip3 install gpiozero lgpio
```

**"Insufficient permissions"**
```bash
sudo usermod -a -G gpio eas-station
sudo reboot
```

**"Failed to add GPIO pin"**
- Check pin is not already in use
- Check pin is not reserved (2, 3, 4, 14 when OLED enabled)
- Verify pin number is valid (2-27)

## OLED Display Configuration

### Overview
OLED displays show real-time alert information, system status, and scrolling messages on a small screen attached to the Argon Industria case.

### Requirements
- SSD1306 OLED display (128x64 or compatible)
- I2C connection (default: bus 1, address 0x3C)
- Python packages: `luma.oled`, `Pillow` (installed by default)
- Button: GPIO 4 (optional, for manual control)

### Enabling OLED

1. Open **Admin → Hardware Settings → OLED Display Tab**
2. Check **"Enable OLED Display"**
3. Configure I2C settings:
   - **I2C Bus**: Usually `1` (use `i2cdetect -l` to verify)
   - **I2C Address**: Usually `0x3C` (use `i2cdetect -y 1` to scan)
   - **Width**: 128 pixels (default)
   - **Height**: 64 pixels (default)
4. Configure button (optional):
   - **Button GPIO**: 4 (default)
   - **Button Active High**: No (button pulls to ground)
   - **Hold Seconds**: 1.25 (how long to press for action)
5. Click **"Save Settings"**

### Troubleshooting OLED

**"OLED display DISABLED"**
- Enable in Admin → Hardware Settings → OLED Display tab

**"OLED dependencies unavailable"**
```bash
sudo apt-get install python3-pil
pip3 install luma.oled Pillow
```

**"Failed to initialise OLED display"**
- Check I2C is enabled: `sudo raspi-config` → Interface Options → I2C → Enable
- Scan for device: `i2cdetect -y 1` (should show address like 3c)
- Check wiring: SDA → GPIO 2, SCL → GPIO 3, VCC → 3.3V, GND → GND

**"OLED button disabled or unavailable"**
- Button is optional, OLED will work without it
- Check button is connected to GPIO 4
- Verify button wiring (button pulls GPIO 4 to ground when pressed)

## LED Sign Configuration

### Overview
LED signs (BetaBrite, Alpha, and compatible models) display scrolling alert messages and system information on large programmable signs.

### Requirements
- BetaBrite/Alpha LED sign
- Network connection (TCP/IP) OR serial connection (RS-232)
- For network: Sign must have IP address on same network
- For serial: USB-to-RS232 adapter or direct serial connection

### Enabling LED Sign

1. Open **Admin → Hardware Settings → LED Sign Tab**
2. Check **"Enable LED Sign"**
3. Configure connection:
   - **Connection Type**: Network (recommended) or Serial
   - For **Network**:
     - **IP Address**: Sign's IP (e.g., 192.168.1.100)
     - **Port**: Usually 10001
   - For **Serial** (⚠️ partial support - basic text only, no advanced features):
     - **Serial Port**: e.g., /dev/ttyUSB1
     - **Baudrate**: Usually 9600
     - **Mode**: RS232 or RS485
     - **Limitations**: Serial mode supports basic text display but not all LED sign features (colors, effects, memory files) are available yet
4. Click **"Save Settings"**

### Troubleshooting LED Sign

**"LED sign DISABLED"**
- Enable in Admin → Hardware Settings → LED Sign tab

**"LED controller module not found"**
```bash
# LED sign library should be included
# Check if scripts/led_sign_controller.py exists
```

**"LED sign not connected (may be offline or unreachable)"**
- For network signs:
  - Ping the sign: `ping 192.168.1.100`
  - Check sign is powered on
  - Verify IP address is correct
  - Check firewall: `sudo ufw allow 10001/tcp`
  - Try connecting with telnet: `telnet 192.168.1.100 10001`
- For serial signs:
  - Check port exists: `ls -l /dev/ttyUSB*`
  - Check permissions: `sudo usermod -a -G dialout eas-station`
  - Verify baudrate matches sign configuration

## VFD Display Configuration

### Overview
VFD (Vacuum Fluorescent Display) displays like the Noritake GU140x32F-7000B provide bright, high-contrast text display for alerts and status.

### Requirements
- Noritake GU140x32F-7000B VFD or compatible
- USB-to-serial adapter or direct serial connection
- Serial port (e.g., /dev/ttyUSB0)
- Baudrate: Usually 38400 or 115200

### Enabling VFD Display

1. Open **Admin → Hardware Settings → VFD Display Tab**
2. Check **"Enable VFD Display"**
3. Configure serial settings:
   - **Serial Port**: e.g., /dev/ttyUSB0
   - **Baudrate**: 38400 (check VFD manual)
4. Click **"Save Settings"**

### Troubleshooting VFD

**"VFD display DISABLED"**
- Enable in Admin → Hardware Settings → VFD Display tab

**"VFD controller module not found"**
```bash
# VFD controller library should be included
# Check if scripts/vfd_controller.py exists
```

**"VFD display not connected (may be offline or unplugged)"**
- Check port exists: `ls -l /dev/ttyUSB* /dev/ttyACM*`
- Check permissions: `sudo usermod -a -G dialout eas-station`
- Verify USB cable is connected
- Try different USB port
- Check VFD is powered (may need external power supply)
- Verify baudrate matches VFD DIP switch settings

## Zigbee Coordinator Configuration

### ⚠️ Warning: Not Yet Implemented

The Zigbee coordinator feature is **currently incomplete**. The database schema, web UI, and API endpoints exist, but the actual coordinator implementation is missing.

**Do not enable Zigbee** until the implementation is complete in a future release.

If you need Zigbee functionality, please:
1. Open an issue on GitHub requesting this feature
2. Specify your Zigbee coordinator hardware model
3. Describe your use case

### When Implemented (Future)

The Zigbee coordinator will support:
- Zigbee device discovery and pairing
- Relay control via Zigbee modules
- Wireless GPIO extension
- Smart home integration

Configuration will include:
- Serial port for coordinator
- Channel selection (11-26)
- PAN ID configuration
- Device management

## Service Management

After changing hardware settings, restart the hardware service:

```bash
# Restart hardware service
sudo systemctl restart eas-hardware-service

# Check status
sudo systemctl status eas-hardware-service

# View logs
sudo journalctl -u eas-hardware-service -f

# Check hardware metrics in Redis
redis-cli GET hardware:metrics | jq
```

## Hardware Settings Location

All hardware settings are stored in the **database** (PostgreSQL) in the `hardware_settings` table. Environment variables are **not used** for hardware configuration.

To view current settings:
```bash
psql -U eas_station_user eas_station_db -c "SELECT * FROM hardware_settings;"
```

## Startup Sequence

When the hardware service starts:
1. Connects to Redis
2. Connects to database
3. Initializes LED controller (if enabled)
4. Initializes VFD controller (if enabled)
5. Initializes OLED display (if enabled)
6. Initializes screen manager (coordinates displays)
7. Initializes GPIO controller (if enabled)
8. Initializes Zigbee coordinator (if enabled - not yet implemented)
9. Starts hardware API server on port 5001
10. Begins health check loop

## Common Issues

### "Hardware service not starting"
```bash
# Check logs for specific error
sudo journalctl -u eas-hardware-service -n 50

# Check if database is accessible
sudo -u eas-station psql -U eas_station_user -d eas_station_db -c "SELECT 1;"

# Check if Redis is running
redis-cli PING
```

### "All hardware shows as unavailable"
- Check that you've **enabled** each feature in Admin → Hardware Settings
- Each hardware type (GPIO, OLED, LED, VFD) has its own enable checkbox
- Hardware is **disabled by default** for safety

### "Permission denied" errors
```bash
# Add user to required groups
sudo usermod -a -G gpio,dialout,i2c eas-station

# Reboot for changes to take effect
sudo reboot
```

### "Module not found" errors
```bash
# Install hardware dependencies
pip3 install gpiozero lgpio luma.oled Pillow

# Or reinstall all dependencies
cd /opt/eas-station
pip3 install -r requirements.txt
```

## Best Practices

1. **Test in stages**: Enable one hardware feature at a time
2. **Check logs**: Always monitor logs when testing hardware
3. **Backup settings**: Export hardware settings before major changes
4. **Use mock mode**: Test GPIO logic without real hardware using mock factory
5. **Document pin usage**: Keep a physical map of which GPIO pins control what
6. **Label connections**: Label all cables and connectors for easy troubleshooting
7. **Power budget**: Ensure adequate power supply for all peripherals
8. **Isolation**: Use optoisolators for high-voltage or sensitive equipment

## Support

For hardware-related issues:
- Check logs: `sudo journalctl -u eas-hardware-service -f`
- Check GitHub Issues: https://github.com/KR8MER/eas-station/issues
- Review hardware docs: `/opt/eas-station/docs/hardware/`
- Test with diagnostics: Navigate to Admin → Diagnostics in web UI

## Related Documentation

- [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md)
- [SDR Setup](SDR_SETUP.md)
- [Serial Adapters](SERIAL_TO_ETHERNET_ADAPTERS.md)
- [LED Communication](BIDIRECTIONAL_LED_COMMUNICATION.md)
