# Quick Start: Raspberry Pi with OLED and GPIO

## TL;DR - Fix OLED and GPIO in 3 Steps

Your configuration is already correct! You just need to give Docker access to GPIO hardware.

```bash
# 1. Stop current containers
docker compose down

# 2. Start with GPIO support
./start-pi.sh

# 3. Verify everything works
./verify-gpio-oled.sh
```

That's it! Your OLED screen and GPIO relay should now work.

## What This Does

The `start-pi.sh` script:
1. ✓ Checks you're on a Raspberry Pi
2. ✓ Verifies `/dev/gpiomem` and `/dev/gpiochip0` exist
3. ✓ Starts Docker with Pi-specific GPIO device mappings
4. ✓ Uses your existing `.env` configuration (already correct!)

## Your Current Configuration

From your `.env` file:

**OLED Display (pins 1-8):**
- Enabled: ✓ `OLED_ENABLED=true`
- I2C Bus: 1 (GPIO 2/3 on physical pins 3/5)
- Address: 0x3C
- Resolution: 128x64
- Button: GPIO 4 (physical pin 7)

**GPIO Relay:**
- Pin: 12 (BCM) = physical pin 32
- Active State: HIGH
- Behavior: Activates during alert playout

## What Was Wrong

**Problem 1:** Docker couldn't access GPIO hardware
- App used `MockFactory` (fake GPIO)
- OLED couldn't initialize (needs I2C on GPIO 2/3)
- Logs showed: `"gpiozero hardware backends unavailable; using MockFactory fallback"`

**Problem 2:** Container read config from wrong location
- docker-compose.yml uses `/app-config/.env` (volume for Portainer)
- Your local `.env` file wasn't being used
- Logs showed: `"OLED display disabled via configuration"`

**After:** docker-compose.pi.yml fixes both issues
- Mounts GPIO devices (`/dev/gpiomem`, `/dev/gpiochip0`)
- Mounts local `.env` file directly into container
- App uses real GPIO hardware and your configuration
- Logs show: `"GPIO controller initialized using gpiozero OutputDevice"`

## Differences Between Startup Methods

### ❌ Wrong Way (what you were using):
```bash
docker compose up -d
```
Uses only `docker-compose.yml` which doesn't mount GPIO devices.

### ✅ Correct Way (use this):
```bash
./start-pi.sh
# OR
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d
```
Combines `docker-compose.yml` + `docker-compose.pi.yml` to enable GPIO.

## Files Included

| File | Purpose |
|------|---------|
| `start-pi.sh` | Startup script with GPIO support + pre-flight checks |
| `verify-gpio-oled.sh` | Diagnostic script to verify GPIO/OLED working |
| `OLED_GPIO_TROUBLESHOOTING.md` | Detailed troubleshooting guide |
| `QUICKSTART_PI.md` | This quick reference |

## Make It Permanent

### Option 1: Always Use start-pi.sh (Recommended)

```bash
# Add alias to your shell
echo "alias eas='cd /path/to/eas-station && ./start-pi.sh'" >> ~/.bashrc
source ~/.bashrc

# Now just run:
eas
```

### Option 2: Create systemd Service

```bash
sudo nano /etc/systemd/system/eas-station.service
```

```ini
[Unit]
Description=EAS Station with GPIO Support
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/path/to/eas-station
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable eas-station
sudo systemctl start eas-station
```

### Option 3: Modify Existing Compose File

If you don't want to use two files, uncomment these lines in `docker-compose.yml`:

```yaml
# Around line 120 in the "devices:" section:
devices:
  - /dev/bus/usb:/dev/bus/usb
  - /dev/gpiomem:/dev/gpiomem        # Uncomment this
  - /dev/gpiochip0:/dev/gpiochip0    # Uncomment this
```

But this breaks compatibility with non-Pi hosts. Using the override file is cleaner.

## Expected Results

### OLED Screen Should Show:
- Line 1: System hostname or status
- Line 2: IP address or network info
- Line 3: Alert status
- Line 4: Timestamp

### GPIO Pin 12 Should:
- Activate when alert is played
- Hold for 5 seconds minimum
- Show in audit logs at `/admin/gpio`

### Logs Should Show:
```
GPIO controller initialized using gpiozero OutputDevice
OLED display initialized
OLED button initialized (GPIO 4)
```

## Still Having Issues?

Run the verification script:
```bash
./verify-gpio-oled.sh
```

It will tell you exactly what's wrong and how to fix it.

For detailed troubleshooting, see `OLED_GPIO_TROUBLESHOOTING.md`.

## Support

- **Full GPIO docs:** `docs/hardware/gpio.md`
- **Issues:** https://github.com/KR8MER/eas-station/issues
- **Pin reference:** https://pinout.xyz

---

**Ready to start?**
```bash
./start-pi.sh
```
