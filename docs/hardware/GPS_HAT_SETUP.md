# GPS HAT Setup

EAS Station™ supports two NMEA-0183 GPS HATs out of the box:

- **Uputronics Raspberry Pi GPS/RTC Expansion Board** *(recommended default)* — u-blox MAX-M8Q multi-GNSS receiver with PPS on **BCM 18**, battery-backed RTC (DS3231 on older revisions, RV-3028-C7 on current revisions), and a low-profile stacking GPIO header.
- **Adafruit Ultimate GPS HAT (#2324)** *(legacy / alternative)* — MTK3339 GPS-only receiver with PPS on **BCM 4** and a tall non-stacking GPIO header.

When enabled, the GPS module provides:

- **Station coordinates** — automatic lat/lon for location-based alert filtering
- **Precision time** — PPS (Pulse Per Second) output for sub-millisecond NTP synchronization
- **Satellite status** — live fix quality, satellite count, and HDOP display in the web UI

Any other UART GPS module that emits standard NMEA at 9600 baud will also work; just point the **Serial Port** and **PPS GPIO Pin** at the right values for your board.

---

## Quick setup via the admin UI (recommended)

Since EAS Station™ 2.74 you do **not** need a terminal to install or configure the GPS HAT. Everything below — package installs, `dtoverlay` lines in `config.txt`, `/etc/default/gpsd`, the chrony refclock block, and seeding the RTC after replacing the coin cell — is one click each in the admin UI. The terminal sections later in this document describe what those buttons do under the hood for operators who prefer to see the machinery, or for diagnosing a system where the UI itself isn't reachable.

### 1. Install the HAT and reboot

Power off the Pi, seat the HAT, attach the antenna, power back on. Nothing software-side yet.

### 2. Open the GPS HAT Setup Status panel

**Admin → Hardware Settings → GPS** — the second card from the top is **GPS HAT Setup Status**. It probes every prerequisite (RTC chip vs overlay, PPS device, gpsd / chrony / `util-linux-extra` package state, `/boot/firmware/config.txt` overlays, chrony's currently-selected source) and shows you a checklist:

- ✅ items are healthy
- ⚠ items have a **Run** button next to them when the privileged setup helper is reachable, or a copy-paste shell command otherwise
- The status badge at the top of the card tells you the overall posture: *All good* / *Suggestions* / *Needs attention* / *Action required*

**Click each ⚠ card's Run button in the order they appear**, watching the result modal until it reports success. The panel re-polls itself after every action so the list shrinks as you fix things. Reboot when an action says *"Requires reboot to take effect"* — typically only the `dtoverlay` actions need that.

### 3. Pick a source mode

This is the only judgement call. Above the **GPS HAT Setup Status** card, the **Source** card has a dropdown labelled **NMEA Source**:

| Mode | Use when | Trade-off |
|---|---|---|
| **Auto** *(default)* | You want it to "just work" — gpsd if available, direct serial otherwise | None practical; this is the recommended default |
| **gpsd** | You want chrony to discipline the system clock from PPS for stratum-1 time | Requires `gpsd` installed and running; the HAT will go offline if gpsd dies |
| **Serial port** | You don't want to run gpsd, or you have a non-standard NMEA tap | The Live GPS card works, but chrony can't share the GPS so you stay at stratum ≥ 2 |

Save & Restart after changing the mode.

### 4. (Uputronics, brand-new HAT or fresh coin cell) Seed the RTC

If the **Detected state** block under the diagnostic panel shows the chip with `seq=0` or the RTC drift status is *Unreadable*, the chip's Power-On Reset Flag is set — normal for a new HAT or one whose coin cell was just replaced. The diagnostic panel will offer a **Seed RTC** action card; click *Run*, leave the *Force unsynced* checkbox **unchecked** (the helper will refuse to seed unsynchronised time, which is the safe behaviour), and let it complete. After that the Hardware Clock card on the System Health page will report the chip in sync.

### 5. Verify

You're done when:

- The **GPS HAT Setup Status** badge reads **All good**
- The **Live GPS Status** card shows mode `3D Fix` with several satellites used, and the **PPS** pill is lit
- In **gpsd** or **auto** mode: `chronyc tracking` (or the chrony status row in the diagnostic panel's *Detected state*) reports **stratum 1** and the offset is sub-millisecond

That's the end-to-end happy path. The rest of this document covers manual operation, board-specific quirks, and what each piece does — useful when something doesn't go to plan, or for builders who want to reproduce the setup outside the admin UI.

---

## NMEA source modes (Tier 3)

EAS Station™ 2.74+ can read NMEA from one of two sources. The choice does **not** affect what the Live GPS Status card displays — the same fix data, satellite list, and per-talker counts populate both ways. It only affects whether `chrony` can use the same GPS for time discipline.

### Why two modes exist

GPS receivers expose NMEA over a single serial port. Two userspace processes cannot share one open serial device, so:

- If EAS Station™ opens `/dev/serial0` directly, chrony's `refclock SHM` gets nothing because gpsd can't read the port either.
- If gpsd opens `/dev/serial0`, the legacy direct-serial path inside EAS Station™ fails.

The Tier 3 mode resolves this by letting EAS Station™ consume NMEA from gpsd over the localhost TCP JSON socket (`127.0.0.1:2947`) instead of opening the serial port directly. gpsd becomes the single owner of the port; chrony reads the same data via SHM segment 0; PPS locks to the GPS via `lock GPS` in chrony.conf; everyone is happy.

### How each mode behaves

| Setting | Where the Live GPS data comes from | Where chrony's GPS samples come from | What happens if gpsd is down |
|---|---|---|---|
| **`auto`** *(default)* | gpsd if reachable, else `/dev/serial0` directly | gpsd's SHM segment if it's running | Falls back to direct serial; Live GPS keeps working; chrony loses GPS |
| **`gpsd`** | gpsd's TCP JSON stream | gpsd's SHM segment | GPS goes offline (start fails fast); chrony loses GPS |
| **`serial`** | `/dev/serial0` directly | nothing (port contention; not used) | n/a — gpsd is irrelevant in this mode |

### Where the existing form fields apply

In the GPS form under *Hardware Settings → GPS*:

- **Serial Port** and **Baud Rate** apply when the runtime ends up on the direct-serial path: **serial** mode always, and **auto** mode when gpsd isn't running. In **gpsd** mode they are ignored by EAS Station™ — gpsd has its own copy in `/etc/default/gpsd`. The GPS HAT Setup Status panel's *Write gpsd config* / *Fix gpsd config* actions write the gpsd-side equivalents.
- **PPS GPIO Pin** is independent of source mode. It's used to detect kernel pulses via `/sys/class/pps/pps0` regardless of who's reading the serial port.
- **Use GPS for station location** and **Use GPS for time sync** apply in every mode.

### Recommended pairings

- **Single-purpose station, no chrony**: leave on **auto**. Even if gpsd isn't installed, things just work via the legacy serial path.
- **Anywhere you want stratum-1 PPS time**: switch to **gpsd**. Run the GPS HAT Setup Status panel's Run buttons until everything is green; you get sub-microsecond UTC discipline for free.
- **Custom NMEA source / non-standard pinout / debugging**: switch to **serial**. The HAT runs on whatever path you point it at, no gpsd dependency.

### Verifying gpsd mode is actually active

Hardware service log line on startup should read:

```
✅ GPS reader started via gpsd at 127.0.0.1:2947 (PPS GPIO 18, source=gpsd)
```

If it reads `source=serial` instead, gpsd wasn't reachable when the manager started — either gpsd isn't running (`systemctl status gpsd.service`), the port is wrong, or `gpsd.socket` is masking the always-running daemon. The diagnostic panel calls these out as separate actions you can fix in one click.

---

## What the GPS HAT Setup Status panel actually does

Each Run button in the panel calls a privileged setup helper (`eas-station-hwsetup`, runs as root, listens on a Unix socket only the `eas-station` group can connect to) which executes one of a hardcoded set of allowlisted actions. The full list:

| Action card / button | Calls | Effect |
|---|---|---|
| *Install missing packages* | `apt-get update && apt-get install -y` | Installs from a 6-package allowlist (`chrony`, `gpsd`, `gpsd-clients`, `pps-tools`, `util-linux-extra`, `i2c-tools`); rejects anything else |
| *Add overlay* / *Replace overlay* (RTC) | edits `/boot/firmware/config.txt` | Idempotent `dtoverlay=i2c-rtc,<chip>`. Replaces an existing line, or appends; deduplicates if you have stale duplicates from earlier hand-edits. Sets *Requires reboot*. |
| *Add PPS overlay* | same | Idempotent `dtoverlay=pps-gpio,gpiopin=N`. Same dedup behaviour. Sets *Requires reboot*. |
| *Seed RTC* | `hwclock -w -u --rtc /dev/rtc0` then `hwclock -r` | Refuses unless `timedatectl` says NTP-synchronized, unless you check the *Force unsynced* override. |
| *Write gpsd config* / *Fix gpsd config* | rewrites `/etc/default/gpsd` | Uses tight allowlists for device paths and option flags; rejects shell-injection attempts. |
| *Enable rtcsync* / *Configure refclocks* | appends to `/etc/chrony/chrony.conf` | Uses sentinel-bracketed managed block; never duplicates `rtcsync` or `refclock` lines you've added by hand outside the block. |
| *Enable + start* | `systemctl enable --now <unit>` | Restricted to `chrony.service`, `gpsd.service`, `gpsd.socket`. |

Every action takes a `.bak.<timestamp>` of any file it edits before writing. Backups live next to the original. The helper logs every request (with peer pid/uid/gid via `SO_PEERCRED`) to the systemd journal as `eas-station-hwsetup` for audit.

The architecture and the rules for adding a new action are documented in [HWSETUP_HELPER.md](HWSETUP_HELPER.md).

---

## Why the Uputronics board is the default

The Uputronics board solves two mechanical / electrical problems that the Adafruit #2324 has:

| Pain point | Adafruit #2324 | Uputronics GPS/RTC |
|---|---|---|
| GPIO header | Tall, non-stacking — Pi case lid will not close | Low-profile stacking header — Pi case closes; OLED / other HATs stack on top |
| OLED coexistence | Covers entire 40-pin header; PPS on BCM 4 (GPCLK0) crowds I²C OLED wiring | Stacking passthrough leaves I²C (BCM 2/3) free; PPS on BCM 18 |
| GNSS constellations | GPS only (MTK3339, 22 channels) | GPS + GLONASS + Galileo + BeiDou concurrent (u-blox MAX-M8Q, 72 channels) |
| Sensitivity / TTFF | −165 dBm tracking, ~34 s cold TTFF | −167 dBm tracking, ~26 s cold TTFF |
| Battery-backed RTC | None (coin cell only seeds GPS warm-start) | DS3231-SN at I²C `0x68` (older boards) or RV-3028-C7 at I²C `0x52` (current boards) — both ±2 ppm, accurate time at boot before GPS lock or NTP |
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
| Hardware RTC | DS3231 (`0x68`) or RV-3028-C7 (`0x52`), battery-backed | none |
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

The EAS Station™ service user needs access to the serial port:

```bash
sudo usermod -aG dialout eas-station
```

### 3. Install Python dependencies

```bash
pip install pyserial pynmea2
```

### 4. (Uputronics only) Enable the on-board RTC

The Uputronics board exposes a battery-backed RTC on the I²C bus. Linux ships kernel drivers for both variants, so no application code is required to seed the system clock at boot — just enable the matching overlay.

**Identify your RTC chip first** so you pick the right overlay:

```bash
sudo apt install -y i2c-tools
sudo i2cdetect -y 1
```

- An entry at address `68` → **DS3231** (older Uputronics revisions)
- An entry at address `52` → **RV-3028-C7** (current Uputronics revisions)

Then add the matching line to `/boot/firmware/config.txt` (or `/boot/config.txt` on older Pi OS):

```ini
# Common to both
dtparam=i2c_arm=on

# Pick ONE of these to match your board:
dtoverlay=i2c-rtc,ds3231       # DS3231 at 0x68
# dtoverlay=i2c-rtc,rv3028      # RV-3028-C7 at 0x52
```

Reboot, then verify the kernel registered the RTC:

```bash
ls /dev/rtc*                   # should list /dev/rtc0
cat /sys/class/rtc/rtc0/name   # e.g. "rtc-ds3231 1-0068" or "rtc-rv3028 1-0052"
```

#### `hwclock` on Raspberry Pi OS Bookworm and newer

On Raspberry Pi OS / Debian 12 (Bookworm) and later, `hwclock` was split out of `util-linux` into a separate package and is **not installed by default** on Pi OS Lite images. If `sudo hwclock -r` reports `command not found`, install:

```bash
sudo apt install -y util-linux-extra
```

Then read and write the RTC:

```bash
sudo hwclock -r        # read RTC time
sudo hwclock -w        # write current system time to RTC (do this once after NTP/GPS sync)
```

You do not strictly need `hwclock` for boot-time time-of-day — the kernel `i2c-rtc` overlay already seeds the system clock from the RTC at boot via `rtc-hctosys`. `hwclock -w` is only needed to **save** the current system time back to the RTC after NTP or GPS gets a fix (and after replacing the coin cell).

This gives the Pi correct timestamps the moment the kernel mounts the I²C bus, well before `gpsd`/`chrony` come up. Combined with PPS, the system clock is then disciplined to sub-millisecond precision after fix.

---

## EAS Station™ Configuration

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
#   precision 1e-7  : weight the edge as ~100 ns class (true at the GPIO pin)
#   filter 16       : median-of-16 cuts the IRQ-latency tail you get with
#                     pps-gpio on a Pi (single biggest knob for peak jitter)
#   prefer          : pick PPS over any pool/server time sources
#   maxlockage 2    : ignore PPS if the NMEA seconds reference goes stale
refclock PPS /dev/pps0 lock GPS refid PPS precision 1e-7 filter 16 prefer maxlockage 2
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

If you previously configured EAS Station™ for the Adafruit #2324 and are swapping in the Uputronics board:

1. Power off the Pi and replace the HAT.
2. Edit `/boot/firmware/config.txt` (or `/boot/config.txt` on older Pi OS):
   - Change `dtoverlay=pps-gpio,gpiopin=4` to `dtoverlay=pps-gpio,gpiopin=18`.
   - Add the RTC overlay matching your board — run `sudo i2cdetect -y 1` to check: `dtoverlay=i2c-rtc,ds3231` if `0x68` is present, or `dtoverlay=i2c-rtc,rv3028` if `0x52` is present.
3. Reboot. Verify `/dev/pps0` and `/dev/rtc0` both exist.
4. In **Admin → Hardware Settings → GPS**, change the **PPS GPIO Pin** from `4` to `18` and **Save Settings**.
5. (Optional) On Pi OS Bookworm or newer, install `hwclock` if missing (`sudo apt install -y util-linux-extra`), then run `sudo hwclock -w` once after a confirmed NTP/GPS sync to seed the RTC from system time.

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

### RTC not detected (Uputronics only)

- Confirm I²C is enabled: `sudo raspi-config` → **Interface Options → I2C → Yes**.
- Confirm the device responds: `sudo i2cdetect -y 1`. You should see `68` (DS3231) **or** `52` (RV-3028-C7) on the bus, depending on board revision.
- Confirm the overlay is loaded for the chip you actually have: `dmesg | grep rtc`. The expected lines are `rtc-ds3231 1-0068: registered as rtc0` or `rtc-rv3028 1-0052: registered as rtc0`. If they don't match, fix the `dtoverlay=i2c-rtc,...` line in `/boot/firmware/config.txt` and reboot.

### `hwclock: command not found`

On Raspberry Pi OS / Debian 12 (Bookworm) and newer, `hwclock` was moved to the `util-linux-extra` package, which is not preinstalled on Pi OS Lite. Install it:

```bash
sudo apt install -y util-linux-extra
hwclock --version    # confirm it's now on PATH
```

Note that you generally do **not** need `hwclock` for the system clock to be correct at boot — the kernel `i2c-rtc` overlay already seeds time-of-day from the RTC via `rtc-hctosys` before userspace starts. `hwclock -w` is only required to push the *current* system time back to the RTC after NTP/GPS sync, or after replacing an exhausted coin cell.

### Hardware Clock card shows "Drift vs system: Unknown" or large drift after a power cycle

The driver could not read a sane epoch from the RTC. The two common causes are:

1. **Backup coin cell is exhausted** — the chip lost time entirely (the RV-3028 / DS3231 sets its Power-On Reset / Oscillator Stop flag in this case). Replace the CR1225 (Uputronics) coin cell, then once the Pi has a confirmed NTP or GPS fix run:
   ```bash
   sudo apt install -y util-linux-extra   # only if hwclock is missing
   sudo hwclock -w                        # write system time → RTC
   sudo hwclock -r                        # confirm RTC reads back the same time
   ```
2. **Wrong overlay loaded** — e.g. `i2c-rtc,ds3231` selected but the board is actually an RV-3028. The kernel will still register *something* on rtc0 but reads come back as zero. Fix per the detection steps above.

### `hwclock -r` fails with `RTC_RD_TIME ... Invalid argument` (RV-3028 only)

Symptom — typically seen on a brand-new board, after a long unpowered storage period, or after replacing the coin cell:

```
hwclock: ioctl(RTC_RD_TIME) to /dev/rtc0 to read the time failed: Invalid argument
...synchronization failed
```

(The earlier `ioctl(4, RTC_UIE_ON, 0): Invalid argument` line in `-v` output is unrelated — the RV-3028 simply does not implement the update-interrupt; hwclock automatically falls back to polling.)

This is **not** an I²C wiring or overlay problem. The Linux `rv3028` driver returns `-EINVAL` from `RTC_RD_TIME` whenever the chip's status register has the **PORF** (Power-On Reset Flag) bit set — its way of signalling "the time I have is unreliable, do not use it." PORF latches on whenever the RV-3028 has lost both VDD and the backup coin cell, and is only cleared by *writing* a new time.

**Resolution:** write the RTC (this clears PORF in the same operation), do not read it first.

```bash
# 1. Confirm system time is actually correct
timedatectl                 # look for "System clock synchronized: yes"
chronyc tracking            # or check that the offset is small

# 2. Write current system time to the RTC (clears PORF)
sudo hwclock -w

# 3. Reads should now succeed
sudo hwclock -r
cat /sys/class/rtc/rtc0/since_epoch
```

If PORF re-appears after the next power cycle, the backup coin cell is exhausted — replace it (CR1225 on the Uputronics board) and run `sudo hwclock -w` once more.

---

## Hardware Documentation

- [Uputronics Raspberry Pi GPS/RTC Expansion Board](https://store.uputronics.com/index.php?route=product/product&product_id=81)
- [u-blox MAX-M8Q product page](https://www.u-blox.com/en/product/max-m8-series)
- [Adafruit Ultimate GPS HAT product page (#2324)](https://www.adafruit.com/product/2324)
- [Adafruit GPS HAT guide](https://learn.adafruit.com/adafruit-ultimate-gps-hat-for-raspberry-pi)
- [pps-gpio kernel module](https://www.kernel.org/doc/html/latest/driver-api/pps.html)
- [Linux RTC driver (DS3231)](https://www.kernel.org/doc/html/latest/admin-guide/rtc.html)
