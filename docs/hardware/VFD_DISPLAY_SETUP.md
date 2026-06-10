# VFD Display Setup (Noritake GU140x32F-7000B)

EAS Station™ supports the **Noritake GU140x32F-7000B** vacuum fluorescent display for showing alert status, system metrics, and scrolling messages. The display connects via RS-232 serial and is managed by the `hardware_service`.

---

## Supported Hardware

| Component | Details |
|-----------|---------|
| Display | Noritake GU140x32F-7000B (140×32 pixel VFD) |
| Interface | RS-232 serial (DB9 or USB-serial adapter) |
| Baud rate | Configurable (default: 9600) |
| Protocol | Noritake Itron command set |
| Brightness | 4 levels (25%, 50%, 75%, 100%) |

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
4. Set the **VFD Baud Rate** (default: 9600).
5. Click **Save Settings**.
6. Restart the hardware service:
   ```bash
   sudo systemctl restart eas-station-hardware
   ```

### Via eas-config

```bash
sudo eas-config
```

Select **5. Hardware Integration → VFD Display Settings**.

> **Note:** VFD settings are stored in the database (`hardware_settings` table) and managed through the web UI. Legacy `VFD_*` environment variables in `.env` are imported once during the initial migration and are **not** read at runtime afterwards.

---

## VFD Control Dashboard

The VFD control interface is available at `/vfd_control` in the web UI.

### Features

- **Live status** — shows current display content and connection state
- **Send message** — type text to display immediately on the VFD
- **Brightness control** — select 25%, 50%, 75%, or 100% brightness
- **Clear display** — blank the VFD
- **Message history** — view the last 10 messages sent to the display
- **Display test** — sends a test pattern to verify the connection

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/vfd/status` | Current VFD status and content |
| `POST` | `/api/vfd/send` | Send text to VFD |
| `POST` | `/api/vfd/clear` | Clear the display |
| `POST` | `/api/vfd/brightness` | Set brightness level |
| `POST` | `/api/vfd/test` | Send test pattern |

**Send a message via API:**

> **Note:** API-key authentication (`X-API-Key`) is **planned but not yet implemented** — see [API Key Management](../guides/API_KEY_MANAGEMENT.md). Until it ships, these endpoints require an authenticated browser session (log in first and reuse the session cookie).

```bash
curl -X POST \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"text": "TORNADO WARNING\nShelter in place now", "scroll": true}' \
  https://your-eas-station.example.com/api/vfd/send
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

| Level | Enum Name | Duty Cycle |
|-------|-----------|-----------|
| 25% | `DIM` | Low |
| 50% | `MEDIUM` | Medium-low |
| 75% | `BRIGHT` | Medium-high |
| 100% | `FULL` | Maximum |

Brightness can be changed at any time from the VFD control dashboard or via the API without disrupting the current display content.

---

## Troubleshooting

### VFD shows no output

1. Confirm the serial port path is correct:
   ```bash
   ls -la /dev/ttyUSB* /dev/ttyS*
   ```
2. Verify the baud rate matches the VFD's DIP switch settings (check the hardware manual).
3. Check `eas-station-hardware` logs:
   ```bash
   journalctl -u eas-station-hardware -f
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
sudo systemctl restart eas-station-hardware
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
