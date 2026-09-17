# VFD Display Setup (Noritake GU140x32F-7000B)

EAS Station™ supports the **Noritake GU140x32F-7000B** vacuum fluorescent display for showing alert status, system metrics, and scrolling messages. The display connects via RS-232 serial and is managed by the `hardware_service`.

---

## Supported Hardware

| Component | Details |
|-----------|---------|
| Display | Noritake GU140x32F-7000B (140×32 pixel VFD) |
| Interface | RS-232 serial (DB9 or USB-serial adapter) |
| Baud rate | Configurable (default: 38400) |
| Protocol | Noritake Itron command set |
| Brightness | 8 levels (0–7, 7 brightest) |

The GU140x32F uses Noritake's character and graphics display protocol. Other VFD models may work but are not officially supported.

---

## Physical Connection

### Direct RS-232 (DB9 Connector)

Connect the VFD's DB9 female connector to your computer's serial port (or a USB-to-RS232 adapter):

| VFD Pin | Signal | Computer Pin |
|---------|--------|-------------|
| 2 | RXD | TXD (pin 3) |
| 3 | TXD | RXD (pin 2) |
| 5 | GND | GND (pin 5) |

**Note:** This is a null-modem style connection. If using a straight-through cable, you may need a null-modem adapter.

### USB-to-Serial Adapter

For systems without a native serial port (such as Raspberry Pi), use a USB-to-RS232 adapter:

```bash
# Verify the adapter is detected
ls /dev/ttyUSB*

# Check kernel driver
dmesg | grep tty | tail -5
```

Common device paths: `/dev/ttyUSB0`, `/dev/ttyUSB1`, `/dev/ttyS0`.

Grant the `eas-station` user access to the serial port:

```bash
sudo usermod -a -G dialout eas-station
```

A logout/login or service restart is required for group changes to take effect.

---

## Configuration

### Via the Web Interface

1. Navigate to **Admin → Hardware Settings**.
2. Enable the **VFD Display** toggle.
3. Set the **VFD Serial Port** (e.g., `/dev/ttyUSB0`).
4. Set the **VFD Baud Rate** (default: 38400).
5. Click **Save Settings**.
6. Restart the hardware service:
   ```bash
   sudo systemctl restart eas-station-hardware.target
   ```

> **Note:** VFD settings are stored in the database (`hardware_settings` table) and managed through the web UI shown above. The `eas-config` TUI no longer edits hardware settings — its Hardware Integration entry points to the web UI. Legacy `VFD_*` environment variables in `.env` are imported once during the initial migration and are **not** read at runtime afterwards.

---

## VFD Control Dashboard

The VFD control interface is available at `/vfd_control` in the web UI.

### Features

- **Live status** — shows current display content and connection state
- **Send message** — type text to display immediately on the VFD
- **Brightness control** — select a level from 0 (dimmest) to 7 (brightest)
- **Clear display** — blank the VFD
- **Message history** — view the last 10 messages sent to the display
- **Graphics** — draw pixels, lines, rectangles, and progress bars directly

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/vfd/status` | Current VFD status and content |
| `POST` | `/api/vfd/text` | Send text to VFD at a given `(x, y)` |
| `POST` | `/api/vfd/image` | Display an image on the VFD |
| `POST` | `/api/vfd/clear` | Clear the display |
| `POST` | `/api/vfd/brightness` | Set brightness level (`level`, 0–7) |
| `POST` | `/api/vfd/graphics/pixel` | Draw a single pixel |
| `POST` | `/api/vfd/graphics/line` | Draw a line |
| `POST` | `/api/vfd/graphics/rectangle` | Draw a rectangle |
| `POST` | `/api/vfd/graphics/progress` | Draw a progress bar |
| `GET` | `/api/vfd/displays` | List recent display history entries |

There is no dedicated "test pattern" endpoint — use `/api/vfd/text` to
confirm the connection is working.

**Send a message via API:**

> **Note:** API-key authentication (`X-API-Key`) is **planned but not yet implemented** — see [API Key Management](../guides/API_KEY_MANAGEMENT.md). Until it ships, these endpoints require an authenticated browser session (log in first and reuse the session cookie).

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"text": "TORNADO WARNING", "x": 0, "y": 0}' \
  https://your-eas-station.example.com/api/vfd/text
```

---

## Alert Display Integration

When the VFD is enabled, the `hardware_service` automatically displays incoming EAS alerts on the VFD:

- **Alert received** — event code and area description scroll across the display
- **During broadcast** — "ON AIR" indicator shown
- **Idle** — clock, station callsign, or custom message rotates

Alert display behavior is configurable via **Admin → Hardware Settings → VFD Alert Display**.

---

## Brightness Levels

| Level | Enum Name |
|-------|-----------|
| 0 (dimmest) | `LEVEL_0` |
| 1 | `LEVEL_1` |
| 2 | `LEVEL_2` |
| 3 | `LEVEL_3` |
| 4 | `LEVEL_4` |
| 5 | `LEVEL_5` |
| 6 | `LEVEL_6` |
| 7 (brightest) | `LEVEL_7` |

Brightness can be changed at any time from the VFD control dashboard or via the API without disrupting the current display content.

---

## Troubleshooting

### VFD shows no output

1. Confirm the serial port path is correct:
   ```bash
   ls -la /dev/ttyUSB* /dev/ttyS*
   ```
2. Verify the baud rate matches the VFD's DIP switch settings (check the hardware manual).
3. Check the displays service logs (VFD is managed by
   `eas-station-displays.service`, not the GPIO service):
   ```bash
   journalctl -u eas-station-displays.service -f
   ```

### "VFD not available" in the control dashboard

The `app_core.vfd` module requires `pyserial`. Verify it is installed:

```bash
source /opt/eas-station/venv/bin/activate
python -c "import serial; print(serial.VERSION)"
```

Install if missing:

```bash
pip install pyserial
```

### Display shows garbage characters

- Baud rate mismatch is the most common cause. Try 2400, 4800, 9600, and 19200.
- Verify RXD/TXD wiring is not swapped.
- Check for null-modem vs. straight-through cable mismatch.

### Permission denied on serial port

```bash
sudo usermod -a -G dialout eas-station
sudo systemctl restart eas-station-hardware.target
```

### VFD works from command line but not from service

The `eas-station` user may not be in the `dialout` group when running as a systemd service. Check:

```bash
groups eas-station
```

And confirm the systemd unit does not override the user's supplementary groups.

---

## Serial Adapter Recommendations

For Raspberry Pi deployments, the following USB-to-RS232 adapters are known to work well:

- **FTDI-based adapters** (e.g., StarTech ICUSB232FTN) — most reliable driver support on Linux
- **Prolific PL2303** adapters — widely available and well-supported
- **CH340/CH341** adapters — works but requires `ch341` kernel module

Avoid chipsets with known Linux compatibility issues (some Prolific knockoffs may have driver problems on newer kernels).
