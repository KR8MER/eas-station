# Argon Industria V5 Zigbee Module Setup

This guide covers setting up the [Argon Industria V5 Zigbee Module](https://argon40.com/products/argon-industria-v5-zigbee-module)
with EAS Station™.

## Hardware Overview

| Spec | Value |
|------|-------|
| Zigbee Chip | CC2652P |
| USB Bridge | Silicon Labs CP210x |
| Zigbee Standard | Zigbee 3.0 |
| Device Path | `/dev/ttyUSB0` |
| Baud Rate | 115200 |
| Case | Argon ONE V5 (Pi 5 only) |

The Zigbee module installs inside the Argon ONE V5 enclosure and connects to the
Raspberry Pi 5 via an internal USB hub. It **does not** use the GPIO header or
the UART pins — it's entirely USB-based.

---

## Step 1 — Raspberry Pi 5 Boot Configuration

The Argon ONE V5's internal USB hub is **not powered by default** on Raspberry Pi 5.
You must add two lines to `/boot/firmware/config.txt` under the `[all]` section:

```ini
[all]
dtoverlay=dwc2,dr_mode=host
usb_max_current_enable=1
```

> **Important:** These lines must be under `[all]`. Anything placed under `[cm4]`
> or `[pi5]` is ignored on Pi 5 and the Zigbee module will not appear.

After editing `config.txt`, reboot:

```bash
sudo reboot
```

---

## Step 2 — Install Argon Utilities

The Argon daemon manages fan control and powers up the internal USB hub on boot:

```bash
curl https://download.argon40.com/argon1v5.sh | bash
sudo systemctl enable --now argononed.service
```

Reboot again after installation:

```bash
sudo reboot
```

---

## Step 3 — Verify the Device Appears

After rebooting, confirm the Zigbee coordinator is detected:

```bash
# Should list a Silicon Labs CP210x device
lsusb | grep -i "silicon"

# Should show /dev/ttyUSB0
ls -l /dev/ttyUSB*
```

Expected output:
```
Bus 001 Device 003: ID 10c4:ea60 Silicon Labs CP210x UART Bridge
crw-rw---- 1 root dialout 188, 0 ... /dev/ttyUSB0
```

If `/dev/ttyUSB0` does not appear, check:
1. `config.txt` edits are under `[all]` (not `[cm4]`)
2. Argon daemon is running: `systemctl status argononed.service`
3. The Zigbee module is fully seated in its connector inside the case

---

## Step 4 — Configure EAS Station™

### Add User to dialout Group

The `eas-station` service user must be in the `dialout` group to access serial ports:

```bash
sudo usermod -aG dialout eas-station
```

### Configure Zigbee in the Web UI

1. Navigate to **Admin → Hardware Settings → Zigbee** tab
2. Check **Enable Zigbee Coordinator**
3. Set **Port** to `/dev/ttyUSB0`
4. Set **Baud Rate** to `115200`
5. Leave **Channel** at `15` (good default, avoid channels 11/25/26 to minimize Wi-Fi 2.4GHz interference)
6. Leave **PAN ID** at `0x1A62` (or choose any unique hex value)
7. Click **Save Changes**
8. Restart the hardware service when prompted

### Verify in EAS Station™

1. Navigate to **Admin → Zigbee** to view the coordinator status page
2. The coordinator status should show `configured` with your port settings
3. Check **Logs → Hardware Service** for:
   ```
   ✅ Zigbee coordinator configured on /dev/ttyUSB0 (channel 15, PAN ID 0x1A62)
   ```

---

## Troubleshooting

### `/dev/ttyUSB0` not appearing

| Symptom | Cause | Fix |
|---------|-------|-----|
| No `/dev/ttyUSB*` devices | USB hub not powered | Add `dtoverlay=dwc2,dr_mode=host` to `config.txt` under `[all]` |
| USB hub present but no CP210x | Module not seated | Check physical connector inside the case |
| Device appears then disappears | Power issue | Add `usb_max_current_enable=1` to `config.txt` |

### Permission denied on `/dev/ttyUSB0`

```bash
# Add user to dialout group
sudo usermod -aG dialout eas-station

# Restart hardware service
sudo systemctl restart eas-station-hardware.target
```

### Zigbee status shows "port_open_failed"

Another process may be holding the port open. Check:

```bash
# Find what is using the port
sudo fuser /dev/ttyUSB0

# Check if another service (e.g. VFD) is using ttyUSB0
sudo systemctl status eas-station-hardware.target
```

If the VFD display is also configured to use `/dev/ttyUSB0`, move one device
to a different port or use a USB hub to assign stable device paths.

### Zigbee coordinator shows as disabled in the UI

Zigbee is disabled by default. Enable it at **Admin → Hardware Settings → Zigbee**.

### Checking hardware service logs

```bash
sudo journalctl -u eas-station-hardware.target -f
```

Look for:
- `✅ Zigbee coordinator configured` — working
- `⚠️ Zigbee serial port /dev/ttyUSB0 does not exist` — USB not detected
- `Zigbee serial port exists but cannot be opened` — permission issue

---

## Channel Selection Guide

The Zigbee radio operates in the 2.4 GHz band, the same as Wi-Fi. Choosing a
channel that avoids Wi-Fi overlap reduces interference:

| Zigbee Channel | Frequency | Wi-Fi Overlap |
|---------------|-----------|---------------|
| 11 | 2405 MHz | Wi-Fi ch 1 — avoid |
| 15 | 2425 MHz | Between ch 1 and 6 — good |
| 20 | 2450 MHz | Wi-Fi ch 6 — avoid |
| 25 | 2475 MHz | Near Wi-Fi ch 11 — use with care |
| 26 | 2480 MHz | Wi-Fi ch 11 — avoid |

**Recommended:** Channel 15 or 20 in most home/office environments.

---

## Hardware Compatibility Notes

The Argon Industria V5 Zigbee module is **only compatible with Argon ONE V5** (Pi 5).
It does **not** fit into earlier Argon cases (ONE V2, ONE M.2).

If you are using a Raspberry Pi 4 or earlier, consider a USB Zigbee dongle instead:
- **SONOFF Zigbee 3.0 USB Dongle Plus** (CC2652P, `/dev/ttyUSB0`, 115200 baud)
- **SMLIGHT SLZB-06** (network or USB, CC2652P)
- **ConBee II** (Deconz, `/dev/ttyACM0`, 38400 baud)

---

## Related Documentation

- [Hardware Quickstart Guide](../guides/HARDWARE_QUICKSTART.md)
- [Argon ONE V5 resources](https://argon40.com/blogs/argon-resources)
- [Zigbee channel planner](https://www.metageek.com/training/resources/zigbee-wifi-coexistence.html)
