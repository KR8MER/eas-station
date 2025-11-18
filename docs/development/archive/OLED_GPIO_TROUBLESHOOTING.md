# OLED and GPIO Troubleshooting Guide

## Quick Fix for OLED Not Working

Your OLED screen (pins 1-8) isn't working because Docker doesn't have access to the GPIO hardware. Here's how to fix it:

### Step 1: Stop Current Containers

```bash
cd /path/to/eas-station
docker compose down
```

### Step 2: Start with GPIO Support

Use the provided startup script:

```bash
./start-pi.sh
```

Or manually with the Pi override:

```bash
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d
```

### Step 3: Verify It's Working

```bash
./verify-gpio-oled.sh
```

You should see:
- ✓ GPIO: Hardware backend active
- ✓ OLED: Initialized and operational

## What Was Wrong?

### Problem 1: GPIO Device Not Accessible (FIXED by start-pi.sh)

Your `docker-compose.yml` doesn't mount GPIO devices by default (lines 98-102):

```yaml
# GPIO Device Passthrough (Raspberry Pi)
# GPIO devices are NOT mounted by default to allow deployment on non-Pi hosts.
```

The `docker-compose.pi.yml` override adds:
```yaml
devices:
  - /dev/gpiomem:/dev/gpiomem      # For GPIO access
  - /dev/gpiochip0:/dev/gpiochip0  # For Pi 5 (lgpio)
group_add:
  - gpio  # Required for permissions
```

Without these, the app falls back to `MockFactory` which simulates GPIO without hardware access.

### Problem 2: OLED Already Enabled (Already Fixed in Your .env)

Your `.env` file **already has** the correct settings:
```bash
OLED_ENABLED=true
OLED_I2C_BUS=1
OLED_I2C_ADDRESS=0x3C
OLED_WIDTH=128
OLED_HEIGHT=64
```

So once GPIO access is granted, the OLED should work immediately!

## Your OLED Pin Configuration

Your Argon OLED module uses these pins (physical header pins 1-8):

| Physical Pin | BCM GPIO | Function |
|--------------|----------|----------|
| Pin 1 | - | 3.3V Power |
| Pin 2 | - | 5V Power |
| Pin 3 | GPIO 2 | I2C SDA (data) |
| Pin 4 | - | 5V Power |
| Pin 5 | GPIO 3 | I2C SCL (clock) |
| Pin 6 | - | Ground |
| Pin 7 | GPIO 4 | OLED Button |
| Pin 8 | GPIO 14 | Display Heartbeat |

**These pins are automatically reserved** by the system and cannot be used for other GPIO functions.

## Your GPIO Relay Configuration

From your `.env`:
- **EAS_GPIO_PIN=12** (BCM GPIO 12, physical pin 32)
- **Active State**: HIGH
- **Hold Time**: 5 seconds
- **Behavior**: Activates during alert playout

This is **separate from the OLED pins** and won't conflict.

## Verification Checklist

After running `./start-pi.sh`, verify:

### 1. Check Container Logs

```bash
docker logs eas-station-app-1 2>&1 | grep -i "gpio\|oled"
```

**Good signs:**
- ✓ `GPIO controller initialized using gpiozero OutputDevice`
- ✓ `OLED display initialized` or similar message
- ✓ `OLED button initialized`

**Bad signs:**
- ❌ `gpiozero hardware backends unavailable; using MockFactory fallback`
- ❌ `OLED display disabled via configuration`
- ❌ `OLED dependencies unavailable`

### 2. Physical OLED Screen

The screen should display:
- System status information
- Network information
- Alert status
- Timestamps

If the screen is blank or frozen, check:
- Power connections (pins 1, 2, 4 have power; pin 6 is ground)
- I2C address (should be 0x3C, verify with `i2cdetect -y 1`)
- Contrast setting (try adding `OLED_CONTRAST=255` to .env)

### 3. OLED Button (Pin 7)

The front-panel button (GPIO 4) allows cycling through screens. Test by:
- Short press: Next screen
- Long press (1.25s): Toggle invert mode

### 4. GPIO Relay (Pin 32)

Test relay activation via web UI:
1. Navigate to `http://your-pi-ip/admin/gpio`
2. Click "Activate" on GPIO 12
3. You should hear/see the relay click
4. Check audit log for activation record

Or via API:
```bash
curl -X POST http://localhost:5000/api/gpio/activate/12 \
  -H "Content-Type: application/json" \
  -d '{"reason": "Manual test", "activation_type": "test"}'
```

## Common Issues

### Issue: "MockFactory fallback" in logs

**Cause:** Container doesn't have GPIO device access

**Fix:** Use `./start-pi.sh` instead of plain `docker compose up`

### Issue: OLED screen is blank

**Possible causes:**
1. **I2C not enabled** - Run `sudo raspi-config` → Interface Options → I2C → Enable
2. **Wrong I2C address** - Check with `i2cdetect -y 1` (should show 3c)
3. **Contrast too low** - Add `OLED_CONTRAST=255` to .env
4. **Rotation wrong** - Try `OLED_ROTATE=180` in .env
5. **Hardware not connected** - Check physical connections

### Issue: "Permission denied" on GPIO

**Fix for host system:**
```bash
sudo usermod -a -G gpio $USER
sudo chmod 666 /dev/gpiomem
```

**Fix for Docker:**
- Already handled by `docker-compose.pi.yml` with `group_add: gpio`

### Issue: I2C device not found

**Enable I2C on Raspberry Pi:**
```bash
# Enable via raspi-config
sudo raspi-config
# Navigate to: Interface Options → I2C → Enable

# Verify I2C is loaded
lsmod | grep i2c

# Scan for devices (should show 0x3C)
sudo i2cdetect -y 1
```

### Issue: OLED works but button doesn't

The button uses GPIO 4 (BCM), which requires GPIO access. If you see:
```
gpiozero pin factory unavailable; cannot initialise OLED button
```

This means GPIO devices aren't accessible. Use `./start-pi.sh` to fix.

## Testing Procedure

1. **Start with GPIO support:**
   ```bash
   ./start-pi.sh
   ```

2. **Wait 30 seconds** for initialization

3. **Run verification:**
   ```bash
   ./verify-gpio-oled.sh
   ```

4. **Check OLED screen** - should show system info

5. **Test button** - press button on pin 7 to cycle screens

6. **Test relay** - activate GPIO 12 via web UI

7. **Check audit logs** - verify activation was recorded

## Working Configuration Summary

Your `.env` already has the correct configuration:

```bash
# OLED Settings (✓ Already configured correctly)
OLED_ENABLED=true
OLED_I2C_BUS=1
OLED_I2C_ADDRESS=0x3C
OLED_WIDTH=128
OLED_HEIGHT=64
OLED_ROTATE=0
OLED_DEFAULT_INVERT=false

# GPIO Relay (✓ Already configured correctly)
EAS_GPIO_PIN=12
EAS_GPIO_ACTIVE_STATE=HIGH
EAS_GPIO_HOLD_SECONDS=5
GPIO_PIN_BEHAVIOR_MATRIX={"12":["playout"]}
```

**All you need to do is start with GPIO device access:**
```bash
./start-pi.sh
```

## Advanced Debugging

### Check GPIO device access from inside container

```bash
docker exec -it eas-station-app-1 ls -la /dev/gpiomem /dev/gpiochip0
```

Should show both devices if mounted correctly.

### Check I2C from inside container

```bash
docker exec -it eas-station-app-1 i2cdetect -y 1
```

Should show device at address 0x3C (60 decimal).

### Monitor OLED updates in real-time

```bash
docker logs -f eas-station-app-1 | grep -i oled
```

### Check Python imports

```bash
docker exec -it eas-station-app-1 python3 -c "from luma.oled.device import ssd1306; print('OK')"
docker exec -it eas-station-app-1 python3 -c "from gpiozero import Button; print('OK')"
```

Both should print "OK" if libraries are installed.

## Support

If issues persist after following this guide:

1. Run `./verify-gpio-oled.sh` and save the output
2. Check logs: `docker logs eas-station-app-1 > app.log`
3. Report issue with both files

## Files Created

- `start-pi.sh` - Startup script with GPIO support
- `verify-gpio-oled.sh` - Verification and diagnostic script
- `OLED_GPIO_TROUBLESHOOTING.md` - This guide

## References

- **GPIO Documentation:** `docs/hardware/gpio.md`
- **OLED Code:** `app_core/oled.py`
- **GPIO Code:** `app_utils/gpio.py`
- **Pin Definitions:** `app_utils/pi_pinout.py`
- **Docker Compose:** `docker-compose.yml` + `docker-compose.pi.yml`
