# GPIO Control & Hardware Integration

## Overview

EAS Station provides comprehensive GPIO (General Purpose Input/Output) control for managing transmitter relays, peripheral devices, and hardware integration. The system includes audit logging, watchdog timers, and operator control interfaces for compliance and reliability.

## Features

- **Unified GPIO Control**: Centralized management of multiple GPIO pins
- **Audit Trail**: Complete history of all GPIO activations with timestamps and operators
- **Watchdog Timers**: Automatic deactivation after timeout to prevent stuck relays
- **Debounce Protection**: Configurable debounce delays for reliable switching
- **Active High/Low Support**: Compatible with various relay modules
- **Web UI Control**: Operator interface for manual GPIO activation
- **API Access**: RESTful API for programmatic control

## Hardware Requirements

### Raspberry Pi GPIO

EAS Station uses BCM (Broadcom) pin numbering. Common GPIO pins:

- **Physical pins 1-40** map to **BCM GPIO 0-27** (varies by model)
- Most relay modules use **3.3V logic** (compatible with RPi)
- Some relay modules require **5V logic** (use level shifter)

### Recommended Hardware

| Component | Specification | Purpose |
|-----------|--------------|---------|
| **Relay Module** | 5V/10A SPDT relay | Transmitter PTT control |
| **GPIO HAT** | 4-8 channel relay HAT | Multiple device control |
| **Level Shifter** | 3.3V to 5V bidirectional | Interface with 5V devices |
| **Optocoupler** | PC817 or similar | Electrical isolation |

## Configuration

### Environment Variables

Configure GPIO pins via `.env` file:

```bash
# Primary EAS transmitter control
EAS_GPIO_PIN=17                      # BCM pin number
EAS_GPIO_ACTIVE_STATE=HIGH           # HIGH or LOW (relay activation level)
EAS_GPIO_HOLD_SECONDS=5.0            # Minimum hold time before release
EAS_GPIO_WATCHDOG_SECONDS=300        # Maximum activation time (safety timeout)

# Additional GPIO pins (comma-separated)
# Format: PIN:NAME:ACTIVE_STATE:HOLD_SECONDS:WATCHDOG_SECONDS
GPIO_ADDITIONAL_PINS="27:Emergency Relay:HIGH:3.0:600,22:LED Sign:HIGH:0.5:120"
```

These same fields are available in the web UI under **Settings → Environment → GPIO Control**
for deployments using the persistent environment editor. Update the values there and restart
the services to apply the new relay mapping.

### Interactive Pin Map (Web UI)

For a visual overview of every Raspberry Pi header pin and its alert behaviors, open
**System → GPIO Pin Map** in the navigation bar. The pin map displays the 40-pin header in
its physical layout with the following capabilities:

- Highlight whether a pin is configured, its BCM number, and active-high/low state.
- Assign one alert behavior per GPIO-capable pin using radio button selection.
- Persist selections to the `GPIO_PIN_BEHAVIOR_MATRIX` environment variable so they are
  applied automatically during alert playout.

Available behaviors include:

- **None** – No automatic behavior (manual control only).
- **Duration of Alert** – Hold the pin active until the alert audio and EOM finish.
- **Audio Playout** – Activate only while tones and audio files are being played.
- **Flash Beacon** – Blink the pin repeatedly at the start of the alert (for strobes or stack lights).
- **5 Second Pulse** – Drive the pin active for five seconds when playout begins.
- **Incoming Alert** – Pulse the pin when a new alert is ingested or queued.
- **Forwarding Alert** – Pulse the pin when an alert is forwarded from monitoring inputs.

The pin map is the recommended way to manage behavior profiles—manual edits to
`GPIO_PIN_BEHAVIOR_MATRIX` should only be performed for scripted deployments.

### Pin Configuration Details

- **PIN**: BCM GPIO pin number (0-27 depending on Pi model)
- **NAME**: Descriptive name for the pin (shown in web UI)
- **ACTIVE_STATE**: `HIGH` or `LOW` (depends on relay module)
- **HOLD_SECONDS**: Minimum time relay stays active (prevents rapid cycling)
- **WATCHDOG_SECONDS**: Maximum time before automatic deactivation (safety feature)

### Common Pin Assignments

**Raspberry Pi 4B / 5 (recommended pins):**

| BCM Pin | Physical Pin | Typical Use |
|---------|-------------|-------------|
| GPIO 17 | Pin 11 | EAS Transmitter PTT |
| GPIO 27 | Pin 13 | Emergency Override Relay |
| GPIO 22 | Pin 15 | LED Sign Control |
| GPIO 23 | Pin 16 | Auxiliary Output 1 |
| GPIO 24 | Pin 18 | Auxiliary Output 2 |

**Avoid using:** GPIO 0-1 (I2C), GPIO 14-15 (UART), GPIO 2-3 (pulled up)

### Docker Configuration (Raspberry Pi)

When running EAS Station in Docker on a Raspberry Pi, the container needs explicit access to the host's GPIO hardware. By default, Docker containers are isolated from hardware devices for security.

**To enable GPIO access:**

1. Edit your `docker-compose.yml` or `docker-compose.embedded-db.yml` file
2. Locate the `app` service section (this is where the web application runs)
3. In the `devices:` section, uncomment the GPIO device mapping line:

```yaml
devices:
  - /dev/bus/usb:/dev/bus/usb
  
  # GPIO Device Passthrough (Raspberry Pi)
  # Uncomment the following line to enable GPIO access on Raspberry Pi:
  - /dev/gpiomem:/dev/gpiomem  # GPIO memory access for Raspberry Pi
```

4. Restart the Docker containers:

```bash
sudo docker compose down
sudo docker compose up -d
```

**Important Notes:**

- The `SYS_RAWIO` capability is already configured in the compose file and is required for GPIO access
- Only the `app` service needs GPIO access; the poller services do not use GPIO
- On Raspberry Pi 5, the system uses the `lgpio` backend automatically
- On older models, the system falls back to `gpiozero` or sysfs backends
- If GPIO access fails, check that `/dev/gpiomem` exists on your host system with `ls -la /dev/gpiomem`

**Verifying GPIO Access:**

After restarting, check the application logs. You should see:
- `GPIO controller initialized using gpiozero OutputDevice` (success)
- Or `GPIO controller initialized using LGPIO backend` (success on Pi 5)

Instead of:
- `WARNING: gpiozero hardware backends unavailable; using MockFactory fallback` (no access)

**Alternative: Privileged Mode (Not Recommended)**

If device mapping doesn't work, you can use privileged mode, but this reduces container security:

```yaml
app:
  privileged: true
  # ... rest of configuration
```

This is not recommended for production deployments. Always prefer specific device mapping.

## Wiring Guidelines

### Safety First

⚠️ **WARNING**: Incorrect wiring can damage your Raspberry Pi and connected equipment.

- Always power off before connecting hardware
- Use appropriate current-limiting resistors
- Ensure common ground between Pi and relay module
- Test with LED before connecting to real equipment
- Use electrical isolation (optocouplers) for high-voltage circuits

### Basic Relay Wiring

**Active-High Relay Module:**

```
Raspberry Pi          Relay Module          Transmitter
-----------          ------------          -----------
GPIO 17 ────────────> IN
3.3V ───────────────> VCC
GND ────────────────> GND
                      COM ──────────────> PTT INPUT
                      NO ───────────────> GROUND
```

**Active-Low Relay Module:**

```
Raspberry Pi          Relay Module          Transmitter
-----------          ------------          -----------
GPIO 17 ────────────> IN
5V ─────────────────> VCC (if 5V module)
GND ────────────────> GND
                      COM ──────────────> PTT INPUT
                      NO ───────────────> GROUND
```

Set `EAS_GPIO_ACTIVE_STATE=LOW` for active-low modules.

### Optocoupler Isolation (Recommended)

For electrical isolation and protection:

```
Raspberry Pi       PC817 Optocoupler      Relay Module
-----------        -----------------      ------------
GPIO 17 ─────┬───> 1 (Anode)
             │
        [330Ω]
             │
GND ─────────┴───> 2 (Cathode)

External 5V ────── 4 (Collector) ────> IN (Relay)
External GND ───── 3 (Emitter) ──────> GND (Relay)
```

This provides complete electrical isolation between Pi and relay circuits.

## Usage

### Programmatic Control

**In Python code:**

```python
from app_utils.gpio import GPIOController, GPIOPinConfig, GPIOActivationType
from app_core.extensions import db

# Initialize controller
controller = GPIOController(db_session=db.session, logger=app.logger)

# Configure a pin
config = GPIOPinConfig(
    pin=17,
    name="EAS Transmitter PTT",
    active_high=True,
    hold_seconds=5.0,
    watchdog_seconds=300.0,
    enabled=True
)
controller.add_pin(config)

# Activate for an alert
controller.activate(
    pin=17,
    activation_type=GPIOActivationType.AUTOMATIC,
    alert_id="CAP-v1.2-12345",
    reason="Tornado Warning broadcast"
)

# Deactivate (respects hold time)
controller.deactivate(pin=17)

# Force deactivate (ignores hold time - emergency only)
controller.deactivate(pin=17, force=True)

# Get current status
states = controller.get_all_states()
for pin, info in states.items():
    print(f"Pin {pin}: {info['state']}")

# Cleanup on shutdown
controller.cleanup()
```

### Web UI Control

Access the GPIO control panel at: **http://your-station:5000/admin/gpio**

**Features:**
- View all configured pins and their current states
- Manually activate/deactivate pins with reason logging
- View 24-hour activation history timeline
- See real-time status updates

**To activate a pin:**
1. Click "Activate" button on the desired pin
2. Select activation type (Manual, Test, or Override)
3. Enter reason for activation (required for audit trail)
4. Click "Activate" to confirm

All manual activations are logged with your username and reason.

### API Endpoints

**Get GPIO Status:**
```bash
curl http://localhost:5000/api/gpio/status
```

**Activate Pin:**
```bash
curl -X POST http://localhost:5000/api/gpio/activate/17 \
  -H "Content-Type: application/json" \
  -d '{"reason": "Manual test", "activation_type": "test"}'
```

**Deactivate Pin:**
```bash
curl -X POST http://localhost:5000/api/gpio/deactivate/17 \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

**Get Activation History:**
```bash
curl http://localhost:5000/api/gpio/history?pin=17&hours=24
```

**Get Statistics:**
```bash
curl http://localhost:5000/api/gpio/statistics?days=7
```

## Audit Trail

All GPIO activations are logged to the `gpio_activation_logs` database table with:

- **Pin number** and configured name
- **Activation type** (manual, automatic, test, override)
- **Timestamps** (activated and deactivated)
- **Duration** in seconds
- **Operator** username (for manual activations)
- **Alert ID** (for automatic activations)
- **Reason** text
- **Success/failure** status and error messages

**Query logs:**

```sql
SELECT
    pin,
    activation_type,
    activated_at,
    duration_seconds,
    operator,
    reason
FROM gpio_activation_logs
WHERE activated_at > NOW() - INTERVAL '7 days'
ORDER BY activated_at DESC;
```

## Safety Features

### Watchdog Timers

Watchdog timers prevent "stuck" relays that could keep transmitters keyed indefinitely:

- Default: 300 seconds (5 minutes)
- Automatically deactivates pin after timeout
- Logs watchdog timeout events
- Configurable per-pin

**When watchdog triggers:**
1. Pin is immediately deactivated
2. State changes to `WATCHDOG_TIMEOUT`
3. Error is logged with alert level
4. Operator notification (if configured)

### Debounce Protection

Debounce delays prevent relay chatter and false triggers:

- Default: 50 milliseconds
- Applied before activation
- Configurable per-pin
- Helps with noisy signals

### Hold Time Enforcement

Hold time prevents premature deactivation:

- Ensures relay stays active for minimum duration
- Important for transmitter PTT (needs settling time)
- Default: 5 seconds for EAS broadcast
- Can be bypassed with `force=True` (emergency only)

## Integration with EAS Broadcasting

GPIO pins are automatically activated during EAS broadcasts:

1. Alert triggers broadcast
2. GPIO relay activates (transmitter PTT)
3. SAME headers, attention tone, and voice play
4. GPIO relay holds for configured duration
5. GPIO relay deactivates automatically
6. Activation logged with alert identifier

**Configuration:**

```python
# In app_utils/eas.py
broadcaster = EASBroadcaster(
    db_session=db.session,
    model_cls=CAPAlert,
    config=eas_config,
    logger=app.logger
)

# GPIO controller automatically integrates
# based on EAS_GPIO_PIN environment variable
```

## Troubleshooting

### Common Issues

**Problem: "gpiozero not available"**

**Solution:**
```bash
# Install gpiozero
pip install gpiozero

# Or on Raspberry Pi OS
sudo apt install python3-gpiozero

# When using Docker, ensure the image installs the library
RUN pip install gpiozero
```

**Problem: "Permission denied" accessing GPIO**

**Solution:**

For native installations:
```bash
# Add user to gpio group
sudo usermod -a -G gpio $USER

# Or run application as root (not recommended)
sudo python app.py
```

For Docker installations:
```bash
# 1. Ensure /dev/gpiomem is accessible on the host
ls -la /dev/gpiomem

# 2. Uncomment the GPIO device mapping in docker-compose.yml:
#    - /dev/gpiomem:/dev/gpiomem

# 3. Restart the containers
sudo docker compose restart app
```

If the error persists in Docker, see the "Docker Configuration (Raspberry Pi)" section above.

**Problem: Relay doesn't activate**

**Check:**
1. Correct BCM pin number in config
2. Active-high vs active-low setting
3. Relay module power (VCC connection)
4. Common ground between Pi and relay
5. Use `gpio readall` to verify pin state

**Problem: Watchdog keeps triggering**

**Solution:**
- Increase `EAS_GPIO_WATCHDOG_SECONDS`
- Check if application is hanging during broadcast
- Review logs for underlying issues

### Testing GPIO

**Test with LED (safe method):**

1. Connect LED + resistor (330Ω) to GPIO pin and ground
2. Access GPIO control panel
3. Activate pin and verify LED lights up
4. Deactivate pin and verify LED turns off

**Test with multimeter:**

```bash
# Set pin to output
gpio mode 17 out

# Activate (set high)
gpio write 17 1

# Measure voltage (should be ~3.3V)

# Deactivate (set low)
gpio write 17 0

# Measure voltage (should be ~0V)
```

### Debug Logging

Enable GPIO debug logging in `.env`:

```bash
LOG_LEVEL=DEBUG
```

Check logs for GPIO events:

```bash
docker logs eas-station | grep -i gpio
```

Or in web UI: **Admin → System Logs** filtered by "gpio"

## Best Practices

1. **Test thoroughly** before connecting to real transmitters
2. **Use optocoupler isolation** for high-reliability systems
3. **Set reasonable watchdog timeouts** (5-10 minutes typical)
4. **Always provide activation reasons** for audit compliance
5. **Review activation logs** weekly for anomalies
6. **Use override sparingly** - indicates configuration issue
7. **Label physical wiring** clearly (pin numbers + purpose)
8. **Document pin assignments** in station operations manual
9. **Test watchdog functionality** periodically
10. **Keep audit trail** for FCC compliance (if broadcasting)

## FCC Compliance Notes

For FCC Part 11 certified operations:

- **Maintain complete audit trail** of all transmitter activations
- **Document all manual overrides** with operator and reason
- **Review logs monthly** as part of compliance checks
- **Test watchdog timers** during monthly EAS tests
- **Archive logs** for minimum 2 years
- **Include GPIO configuration** in station technical documentation

## Hardware Specifications

### Pin Ratings (Raspberry Pi)

- **Voltage:** 3.3V logic levels
- **Current:** Maximum 16mA per pin, 50mA total
- **Always use current-limiting resistors** when driving LEDs directly
- **Never connect 5V directly** to GPIO pins (will damage Pi)

### Recommended Relay Specifications

- **Coil voltage:** 5V DC (with separate power supply)
- **Contact rating:** 10A @ 250VAC or 10A @ 30VDC (minimum)
- **Contact type:** SPDT (Single Pole Double Throw) or SPST-NO
- **Isolation:** Optocoupler isolated modules preferred

## Support & References

- **Hardware:** See Pi pinout at https://pinout.xyz
- **GPIO Library:** https://sourceforge.net/projects/raspberry-gpio-python/
- **Wiring Guide:** https://www.raspberrypi.com/documentation/computers/raspberry-pi.html
- **Support Forum:** GitHub Issues at https://github.com/KR8MER/eas-station/issues

## See Also

- [System Health Monitoring](../guides/HELP#monitoring-live-alerts)
- [Admin Panel Guide](../guides/HELP#routine-operations)
- [EAS Broadcasting](../guides/HELP#reviewing-compliance-weekly-tests)
- [API Documentation](../frontend/JAVASCRIPT_API)
