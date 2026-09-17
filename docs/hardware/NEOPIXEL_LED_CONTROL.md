# NeoPixel LED Strip Control

EAS Station™ supports WS2812B/NeoPixel addressable RGB LED strips for visual alert indication. When an EAS alert is received or broadcast, the LED strip can flash or display color patterns to provide a visible at-a-glance status indicator.

---

## Supported Hardware

| Component | Specification |
|-----------|--------------|
| LED type | WS2812B (NeoPixel), SK6812, or compatible |
| Data signal | Single-wire 5V or 3.3V logic |
| GPIO pin | Configurable (default: BCM 18, PWM0 — see PPS conflict note below) |
| Power | External 5V supply recommended for strips >30 LEDs |
| Maximum LEDs | Software configurable (tested up to 300) |

---

## Physical Wiring

### Signal Connection (Raspberry Pi)

| LED Strip Wire | Raspberry Pi Connection |
|---------------|------------------------|
| Data In (DIN) | GPIO BCM 18 (Pin 12) — recommended |
| Ground | GND (Pin 6 or any GND pin) |
| +5V | External 5V supply (do NOT use Pi's 5V for strips >10 LEDs) |

!!! warning "Pin conflict with the GPS HAT"
    The Uputronics GPS/RTC HAT uses **BCM 18 for its PPS signal** (see [GPS HAT Setup](GPS_HAT_SETUP.md)). If your station has the GPS HAT installed, move the NeoPixel data line to another PWM-capable pin (e.g., **BCM 12, PWM0** or **BCM 13, PWM1**) and update the pin in Hardware Settings.

!!! warning "Power requirements"
    Each WS2812B LED draws up to 60mA at full white. A 60-LED strip at full brightness requires ~3.6A at 5V. Always use an external 5V power supply rated for your strip length. Connect the supply's GND to the Raspberry Pi's GND to establish a common ground.

### Level Shifting

The Raspberry Pi's GPIO outputs 3.3V logic while WS2812B LEDs expect 5V data signals. In most cases, 3.3V data signals drive WS2812B LEDs reliably, but for longer strips or if you experience data corruption, add a level shifter (e.g., 74AHCT125).

---

## Configuration

### Via the Web Interface

1. Navigate to **Admin → Hardware Settings**.
2. Enable the **NeoPixel LED Strip** toggle.
3. Set the **GPIO Pin** (BCM numbering, default: 18).
4. Set the **Number of LEDs** to match your strip length.
5. Set **Brightness** (0–255, default: 128).
6. Enable **Flash on Alert** to trigger the strip when an EAS alert is received.
7. Set **Flash Interval (ms)** — how rapidly the strip flashes during an alert (default: 500ms).
8. Click **Save Settings**.
9. Restart the hardware service:
   ```bash
   sudo systemctl restart eas-station-hardware.target
   ```

### Configuration Fields

| Setting | Variable | Default | Description |
|---------|----------|---------|-------------|
| Enabled | `neopixel_enabled` | `false` | Enable NeoPixel support |
| GPIO pin | `neopixel_gpio_pin` | `18` | BCM pin number |
| LED count | `neopixel_num_pixels` | `1` | Number of LEDs in strip — set to your actual strip length |
| LED order | `neopixel_led_order` | `GRB` | Byte order of the strip: `GRB`, `RGB`, `GRBW`, or `RGBW` — set via a dropdown in the web UI, not an environment variable |
| Brightness | `neopixel_brightness` | `128` | Global brightness (0–255) |
| Standby color | `neopixel_standby_color` | `(0, 10, 0)` — dim green | Shown when no alert is active |
| Alert color | `neopixel_alert_color` | `(255, 0, 0)` — red | Shown during an active EAS alert |
| Flash on alert | `neopixel_flash_on_alert` | `true` | Flash strip during EAS alerts |
| Flash interval | `neopixel_flash_interval_ms` | `500` | Flash period in milliseconds |

All fields live on the **Admin → Hardware Settings → NeoPixel** tab; there is no
`.env` equivalent for any of them.

---

## Alert Colors

There is one configurable **standby color** (shown when idle, default dim
green) and one configurable **alert color** (shown during an active EAS
broadcast, default red) — set as color pickers on the NeoPixel settings tab.
The strip does not currently map different colors to different alert
severities; every active alert uses the same configured alert color.

When `Flash on Alert` is enabled, the strip flashes between the alert color
and off at the configured interval for the duration of the broadcast. After
the broadcast completes, the strip returns to its standby color.

---

## Software Requirements

NeoPixel control requires the `rpi_ws281x` (also known as `rpi-ws281x-python`) library, which in turn requires root-level PWM access or DMA access.

### Installing the Library

`rpi-ws281x` is already declared in `requirements.txt` (ARM builds only) and
installed automatically by `install.sh` / `update.sh` on Raspberry Pi
hardware. Only install it manually if you're troubleshooting a missing
import outside that normal flow:

```bash
source /opt/eas-station/venv/bin/activate
pip install rpi_ws281x
```

### Permissions

`eas-station-gpio.service` runs as the unprivileged `eas-station` user (not
root), and does not request `CAP_SYS_RAWIO` or any other capability. GPIO
access goes through `/dev/gpiomem`, which on Raspberry Pi OS is owned by the
`gpio` group — the service user needs to be a member of it:

```bash
sudo usermod -a -G gpio eas-station
sudo systemctl restart eas-station-hardware.target
```

Check the service user:

```bash
grep User /opt/eas-station/systemd/eas-station-gpio.service
```

---

## Testing the LED Strip

There is no dedicated "test strip" action for NeoPixel today. To confirm
wiring and software are working without waiting for a live alert:

- Save the NeoPixel settings on **Admin → Hardware Settings** — the strip
  should immediately switch to the configured standby color.
- Trigger a Required Weekly Test (RWT) broadcast (**Broadcast → Weekly
  Tests → Run Test Now**) and confirm the strip switches to the alert color
  and flashes for the duration.

---

## Troubleshooting

### LEDs do not light up

1. Verify power supply is connected and providing 5V.
2. Confirm GPIO pin number matches physical wiring (BCM numbering, not board numbering).
3. Check that `eas-station-hardware.target` is running:
   ```bash
   sudo systemctl status eas-station-hardware.target
   ```
4. Look for errors in the hardware log:
   ```bash
   journalctl -u eas-station-gpio.service -f
   ```

### "Can't open /dev/gpiomem" error

The service user needs to be in the `gpio` group — see [Permissions](#permissions) above. Running as root also works but is not required or recommended.

### First LED lights but rest do not

- Check the data wire connection at the strip's DIN end.
- Confirm you have a common GND between the Pi and the external power supply.
- Try reducing brightness — high currents can cause voltage drop.

### Colors look wrong (e.g., green and red are swapped)

Some LED strips use a different byte order than the default. Change the
**LED Order** dropdown on **Admin → Hardware Settings → NeoPixel** to match
your strip (`GRB` — most WS2812B — `RGB`, `GRBW`, or `RGBW` for SK6812
RGBW strips), then save and restart the hardware service.

### LEDs flicker randomly

Usually caused by insufficient power supply current or a missing common ground between the Pi and the power supply. Add decoupling capacitors (470µF, 25V) across the power supply leads near the strip.

### rpi_ws281x not available error

The library is only available on Raspberry Pi hardware. On non-Pi systems, NeoPixel support is disabled automatically. Check whether `rpi_ws281x` imported successfully:

```bash
python -c "import rpi_ws281x; print('OK')"
```

---

## Integration with Tower Lights

EAS Station™ also supports industrial-grade tower lights (e.g., Patlite or similar serial-controlled units) via a separate hardware integration. Tower lights and NeoPixel strips can be used simultaneously. See **Admin → Hardware Settings → Tower Light** for tower light configuration.
