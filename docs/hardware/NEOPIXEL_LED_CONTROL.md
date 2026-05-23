# NeoPixel LED Strip Control

EAS Station™ supports WS2812B/NeoPixel addressable RGB LED strips for visual alert indication. When an EAS alert is received or broadcast, the LED strip can flash or display color patterns to provide a visible at-a-glance status indicator.

---

## Supported Hardware

| Component | Specification |
|-----------|--------------|
| LED type | WS2812B (NeoPixel), SK6812, or compatible |
| Data signal | Single-wire 5V or 3.3V logic |
| GPIO pin | Configurable (default: BCM 18, PWM0) |
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
   sudo systemctl restart eas-station-hardware
   ```

### Configuration Fields

| Setting | Variable | Default | Description |
|---------|----------|---------|-------------|
| Enabled | `neopixel_enabled` | `false` | Enable NeoPixel support |
| GPIO pin | `neopixel_gpio_pin` | `18` | BCM pin number |
| LED count | `neopixel_num_pixels` | `30` | Number of LEDs in strip |
| Brightness | `neopixel_brightness` | `128` | Global brightness (0–255) |
| Flash on alert | `neopixel_flash_on_alert` | `true` | Flash strip during EAS alerts |
| Flash interval | `neopixel_flash_interval_ms` | `500` | Flash period in milliseconds |

---

## Alert Color Mapping

When `Flash on Alert` is enabled, the LED strip displays colors based on alert severity:

| Severity | Color | Description |
|----------|-------|-------------|
| Extreme | Red (full brightness) | Life-threatening emergency |
| Severe | Orange | Significant threat |
| Moderate | Yellow | Moderate hazard |
| Minor | Blue | Minor hazard |
| Test (RWT/RMT) | Green | Weekly/monthly test |
| Unknown | White | Unclassified event |

During a broadcast, the strip flashes at the configured interval. After the broadcast completes, the strip returns to its idle state (off, or a dim indicator color).

---

## Software Requirements

NeoPixel control requires the `rpi_ws281x` (also known as `rpi-ws281x-python`) library, which in turn requires root-level PWM access or DMA access.

### Installing the Library

```bash
source /opt/eas-station/venv/bin/activate
pip install rpi_ws281x
```

### Permissions

The `rpi_ws281x` library requires access to `/dev/mem` for DMA-based LED control. The `eas-station-hardware` service must run as root or with the `CAP_SYS_RAWIO` capability.

Check the service user:

```bash
grep User /opt/eas-station/systemd/eas-station-gpio.service
```

If the service does not run as root, add the capability or add `AmbientCapabilities=CAP_SYS_RAWIO` to the service unit file.

---

## Testing the LED Strip

From the VFD/hardware control dashboard at `/admin/hardware`, click **Test NeoPixel Strip** to cycle through all alert colors. This verifies that wiring and software are working without waiting for a live alert.

Via command line:

```bash
sudo python scripts/test_neopixel.py --pin 18 --count 30
```

---

## Troubleshooting

### LEDs do not light up

1. Verify power supply is connected and providing 5V.
2. Confirm GPIO pin number matches physical wiring (BCM numbering, not board numbering).
3. Check that `eas-station-hardware` is running:
   ```bash
   sudo systemctl status eas-station-hardware
   ```
4. Look for errors in the hardware log:
   ```bash
   journalctl -u eas-station-hardware -f
   ```

### "Can't open /dev/mem" error

The service needs elevated permissions. Run the hardware service as root or grant the `CAP_SYS_RAWIO` capability.

### First LED lights but rest do not

- Check the data wire connection at the strip's DIN end.
- Confirm you have a common GND between the Pi and the external power supply.
- Try reducing brightness — high currents can cause voltage drop.

### Colors look wrong (e.g., green and red are swapped)

Some LED strips use GRB color order instead of RGB. Adjust the color order in the hardware settings:

```
NEOPIXEL_COLOR_ORDER=GRB
```

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
