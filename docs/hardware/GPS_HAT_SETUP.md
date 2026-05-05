# GPS HAT Setup

EAS Station supports two NMEA-0183 GPS HATs out of the box:

- **Uputronics Raspberry Pi GPS/RTC Expansion Board** *(recommended default)* — u-blox MAX-M8Q multi-GNSS receiver with PPS on **BCM 18**, battery-backed DS3231 RTC, and a low-profile stacking GPIO header.
- **Adafruit Ultimate GPS HAT (#2324)** *(legacy / alternative)* — MTK3339 GPS-only receiver with PPS on **BCM 4** and a tall non-stacking GPIO header.

When enabled, the GPS module provides:

- **Station coordinates** — automatic lat/lon for location-based alert filtering
- **Precision time** — PPS (Pulse Per Second) output for sub-millisecond NTP synchronization
- **Satellite status** — live fix quality, satellite count, and HDOP display in the web UI

Any other UART GPS module that emits standard NMEA at 9600 baud will also work; just point the **Serial Port** and **PPS GPIO Pin** at the right values for your board.

---

## Why the Uputronics board is the default

The Uputronics board solves two mechanical / electrical problems that the Adafruit #2324 has:

| Pain point | Adafruit #2324 | Uputronics GPS/RTC |
|---|---|---|
| GPIO header | Tall, non-stacking — Pi case lid will not close | Low-profile stacking header — Pi case closes; OLED / other HATs stack on top |
| OLED coexistence | Covers entire 40-pin header; PPS on BCM 4 (GPCLK0) crowds I²C OLED wiring | Stacking passthrough leaves I²C (BCM 2/3) free; PPS on BCM 18 |
| GNSS constellations | GPS only (MTK3339, 22 channels) | GPS + GLONASS + Galileo + BeiDou concurrent (u-blox MAX-M8Q, 72 channels) |
| Sensitivity / TTFF | −165 dBm tracking, ~34 s cold TTFF | −167 dBm tracking, ~26 s cold TTFF |
| Battery-backed RTC | None (coin cell only seeds GPS warm-start) | DS3231-SN (±2 ppm, I²C `0x68`) — accurate time at boot before GPS lock or NTP |
| Antenna bias | 3.0 V fixed, no detect | 3.3 V with short-/open-circuit detection |
| Configuration tooling | Proprietary PMTK commands | u-blox u-center over USB-serial bridge or UART |

Multi-GNSS in particular is something `app_core/gps/gps_manager.py` already handles — it accumulates per-talker GSA records (`GP`, `GL`, `GA`, `GB`) and de-duplicates PRNs across constellations, so a Uputronics board will typically report 12–20 used satellites where the Adafruit reports 4–8.

---

## Hardware Overview

| Feature | Uputronics GPS/RTC | Adafruit #2324 |
|---|---|---|
| GNSS chip | u-blox MAX-M8Q | MediaTek MT3339 |
| Interface | UART via `/dev/serial0` | UART via `/dev/serial0` |
| Default baud rate | 9600 | 9600 |
| PPS output | **GPIO BCM 18** | **GPIO BCM 4** |
| Hardware RTC | DS3231 on I²C `0x68` (battery-backed) | none |
| Fix indicator LED | 1 Hz blink with fix | 1 Hz blink no fix; 15 s pulse with fix |
| Supported NMEA sentences | GGA, RMC, GSA, GSV (multi-GNSS) | GGA, RMC, GSV (GPS only) |
| Update rate | 1 Hz default (configurable) | 1 Hz default (configurable) |

---

## Hardware Installation

1. **Power off the Raspberry Pi** before installing the HAT.
2. Align the HAT's 40-pin header with the Pi's GPIO header and press firmly. With the Uputronics board, additional HATs (e.g. an I²C OLED) can stack on the passthrough header.
3. Attach the included antenna to the SMA/u.FL connector (or connect an external active antenna for better sky view). The Uputronics board supplies 3.3 V with overcurrent / open-antenna detection; the Adafruit board supplies 3.0 V.
4. Power on the Pi. The fix LED will begin blinking.

---

## Software Prerequisites

### 1. Enable UART on the Raspberry Pi

Both HATs use the primary UART (`/dev/serial0`). By default the Pi uses this port for the Linux console. You must disable the serial console and enable the UART hardware:

```bash
sudo raspi-config
```

Navigate to: **Interface Options → Serial Port**

- **Would you like a login shell to be accessible over the serial?** → **No**
- **Would you like the serial port hardware to be enabled?** → **Yes**

Reboot after making changes:

```bash
sudo reboot
```

Verify the port appears:

```bash
ls -la /dev/serial0
# Should show: /dev/serial0 -> ttyAMA0  (or ttyS0 on Pi 3/4)
```

### 2. Add user to dialout group

The EAS Station service user needs access to the serial port:

```bash
sudo usermod -aG dialout eas-station
```

### 3. Install Python dependencies

```bash
pip install pyserial pynmea2
```

### 4. (Uputronics only) Enable the on-board DS3231 RTC

The Uputronics board exposes a battery-backed DS3231 at I²C address `0x68`. Linux already has a kernel driver for it, so no application code is required to seed the system clock at boot — just enable the overlay:

```ini
# /boot/config.txt  (or /boot/firmware/config.txt on newer Pi OS)
dtparam=i2c_arm=on
dtoverlay=i2c-rtc,ds3231
```

After rebooting, verify:

```bash
ls /dev/rtc*           # should list /dev/rtc0
sudo hwclock -r        # should print the RTC time
```

This gives the Pi correct timestamps the moment the kernel mounts the I²C bus, well before `gpsd`/`chrony` come up. Combined with PPS, the system clock is then disciplined to sub-millisecond precision after fix.

---

## EAS Station Configuration

1. Navigate to **Admin → Hardware Settings → GPS**.
2. Check **Enable GPS Receiver**.
3. Set the serial port (default: `/dev/serial0`).
4. Set the baud rate (default: **9600** for both supported HATs).
5. Set the **PPS GPIO Pin**:
   - **18** for the Uputronics GPS/RTC HAT *(default)*
   - **4** for the Adafruit Ultimate GPS HAT #2324
6. Optionally enable:
   - **Use GPS for station location** — populates lat/lon in location settings after first fix
   - **Use GPS for time sync** — requires the `pps-gpio` kernel overlay (see below)
7. Set **Minimum Satellites for Fix** (default: 4). With a multi-GNSS receiver you can comfortably raise this.
8. Click **Save Settings**.

The hardware service will restart the GPS reader with the new configuration. Click **Refresh** in the Live GPS Status card to see current fix data.

---

## PPS Time Synchronization (Optional)

Both HATs output a 1 Hz PPS pulse — the Uputronics on BCM 18 and the Adafruit on BCM 4. This pulse can discipline the system clock to within microseconds of UTC when combined with `gpsd` and `chrony`.

### Install required packages

```bash
sudo apt install gpsd gpsd-clients chrony
```

### Enable the pps-gpio kernel module

Add the matching line to `/boot/config.txt` (or `/boot/firmware/config.txt` on newer Pi OS):

```ini
# Uputronics GPS/RTC Expansion Board (default)
dtoverlay=pps-gpio,gpiopin=18

# Adafruit Ultimate GPS HAT #2324 (alternative)
# dtoverlay=pps-gpio,gpiopin=4
```

Reboot, then verify:

```bash
ls /dev/pps0
```

### Configure gpsd

Edit `/etc/default/gpsd`:

```bash
DEVICES="/dev/serial0 /dev/pps0"
GPSD_OPTIONS="-n"
START_DAEMON="true"
```

Restart gpsd:

```bash
sudo systemctl restart gpsd
sudo systemctl enable gpsd
```

Verify gpsd can see the GPS fix:

```bash
gpsmon /dev/serial0
# or
cgps -s
```

### Configure chrony for GPS/PPS

Edit `/etc/chrony/chrony.conf`, adding:

```
# GPS via gpsd (NMEA time, low precision)
refclock SHM 0 offset 0.5 delay 0.2 refid GPS

# GPS PPS (high precision — requires NMEA fix from above)
refclock PPS /dev/pps0 lock GPS refid PPS
```

Restart chrony:

```bash
sudo systemctl restart chrony
```

Verify time sources:

```bash
chronyc sources -v
```

A `*` next to PPS indicates it is selected as the primary reference. Offset should be sub-millisecond.

---

## Verifying GPS Operation

### Live status in the web UI

**Admin → Hardware Settings → GPS → Refresh**

The status card shows:
- Fix status (No Fix / Acquiring / Fix Acquired)
- Serial port and baud rate
- Satellite count (multi-GNSS on the Uputronics board)
- Latitude, longitude, altitude
- UTC time from GPS
- HDOP (horizontal dilution of precision)

### Command-line verification

```bash
# Read raw NMEA sentences
stty -F /dev/serial0 9600 raw && cat /dev/serial0

# Example output (multi-GNSS — note the $GL, $GA, $GB talkers from Uputronics):
# $GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
# $GPGGA,123519,4807.038,N,01131.000,E,1,12,0.7,545.4,M,46.9,M,,*4B
# $GLGSV,...
# $GAGSV,...
# $GBGSV,...
```

A sentence starting with `$GPGGA` (or `$GNGGA` on multi-GNSS receivers) with a non-zero fix quality (field 6) indicates a valid fix.

### Redis status key

The hardware service publishes GPS data to Redis:

```bash
redis-cli GET gps:status | python3 -m json.tool
```

---

## Migrating from the Adafruit HAT to the Uputronics Board

If you previously configured EAS Station for the Adafruit #2324 and are swapping in the Uputronics board:

1. Power off the Pi and replace the HAT.
2. Edit `/boot/config.txt` (or `/boot/firmware/config.txt`):
   - Change `dtoverlay=pps-gpio,gpiopin=4` to `dtoverlay=pps-gpio,gpiopin=18`.
   - Add `dtoverlay=i2c-rtc,ds3231` to enable the DS3231 RTC.
3. Reboot. Verify `/dev/pps0` and `/dev/rtc0` both exist.
4. In **Admin → Hardware Settings → GPS**, change the **PPS GPIO Pin** from `4` to `18` and **Save Settings**.
5. (Optional) Run `sudo hwclock -w` once after a confirmed NTP/GPS sync to seed the DS3231 from system time.

No application data needs to be rebuilt; the GPS manager and chrony pick up the new pin/overlay on next start.

---

## Troubleshooting

### No NMEA data on serial port

- Verify `raspi-config` disabled the serial console and enabled UART hardware.
- Check for conflicting Bluetooth usage: on Pi 3/4/5, Bluetooth also uses UART. Some configurations require disabling Bluetooth to free the primary UART:
  ```bash
  # In /boot/config.txt:
  dtoverlay=disable-bt
  ```
  Then reboot and run `sudo systemctl disable hciuart`.
- Confirm the port path: `ls -la /dev/serial*`

### Fix LED blinks but no fix reported

- Move to a location with clear sky view. The first cold start can take 30–60 seconds outdoors (typically faster on the multi-GNSS Uputronics receiver).
- Verify the antenna is connected and, on the Uputronics board, that the antenna-detect status is healthy.

### PPS device not found (`/dev/pps0` missing)

- Confirm the `dtoverlay=pps-gpio,gpiopin=…` line in `/boot/config.txt` matches your HAT (18 for Uputronics, 4 for Adafruit) and reboot.
- Verify the module is loaded: `lsmod | grep pps_gpio`
- Load manually to test: `sudo modprobe pps-gpio gpiopin=18`  (or `gpiopin=4` for the Adafruit)

### chrony not using PPS

- PPS requires an active NMEA fix (the `lock GPS` directive). Run `cgps -s` to confirm gpsd has a fix before expecting PPS to be selected.
- Check chrony sources: `chronyc sources -v`

### DS3231 RTC not detected (Uputronics only)

- Confirm I²C is enabled: `sudo raspi-config` → **Interface Options → I2C → Yes**.
- Confirm the device responds: `sudo i2cdetect -y 1` should show `68` on the bus.
- Confirm the overlay is loaded: `dmesg | grep rtc`.

---

## Hardware Documentation

- [Uputronics Raspberry Pi GPS/RTC Expansion Board](https://store.uputronics.com/index.php?route=product/product&product_id=81)
- [u-blox MAX-M8Q product page](https://www.u-blox.com/en/product/max-m8-series)
- [Adafruit Ultimate GPS HAT product page (#2324)](https://www.adafruit.com/product/2324)
- [Adafruit GPS HAT guide](https://learn.adafruit.com/adafruit-ultimate-gps-hat-for-raspberry-pi)
- [pps-gpio kernel module](https://www.kernel.org/doc/html/latest/driver-api/pps.html)
- [Linux RTC driver (DS3231)](https://www.kernel.org/doc/html/latest/admin-guide/rtc.html)
