# eas-config: Interactive Configuration Tool

`eas-config` is a terminal-based configuration utility for EAS Station™, similar in style to Raspberry Pi's `raspi-config`. It provides a menu-driven interface for changing common settings without requiring manual `.env` file edits, and automatically restarts services after changes are saved.

---

## Starting eas-config

The tool must be run as root:

```bash
sudo eas-config
```

If installed via the standard installer, `eas-config` is placed at `/usr/local/bin/eas-config` and available system-wide.

**Requirements:** `whiptail` must be installed (included by default on Debian/Ubuntu/Raspberry Pi OS).

```bash
# Install whiptail if missing
sudo apt-get install whiptail
```

---

## Main Menu

When you launch `eas-config`, the main menu appears:

```
 EAS Station™ Configuration Tool
 -------------------------------------------------------------------
 Configure your EAS Station™ (similar to raspi-config)

 Select an option:

   1  System Settings         (Hostname, Location, Callsign)
   2  Database Configuration  (PostgreSQL settings)
   3  Alert Sources           (NOAA, IPAWS, Manual)
   4  Audio Settings          (Receivers, Icecast, Broadcasts)
   5  Hardware Integration    (managed in the web UI)
   6  Network Settings        (Firewall, Remote Access)
   7  Advanced Options        (Logging, Performance)
   8  View Current Configuration
   9  Restart Services
   0  Exit
```

Use the arrow keys to navigate and **Enter** or **Space** to select. Press **Tab** to move between buttons in dialog boxes.

---

## Menu Reference

### 1. System Settings

Configures core station identity settings stored in `.env`.

| Option | Environment Variable | Description |
|--------|---------------------|-------------|
| Change Hostname | `HOSTNAME` | System hostname (also updates `/etc/hostname`) |
| EAS Callsign/Identifier | `EAS_CALLSIGN` | Your station ID (e.g., `KR8MER`) |
| Station Location | `EAS_LOCATION` | Human-readable location string |
| County/Region | `COUNTY_NAME` | County name for display purposes |
| Configure FIPS Codes | `FIPS_CODES` | State + county SAME codes for alert filtering |

**FIPS code configuration** presents a state selector followed by a county checklist. Selected counties are written as a comma-separated list of 6-digit FIPS codes.

---

### 2. Database Configuration

Configure the PostgreSQL connection.

| Option | Variable | Description |
|--------|----------|-------------|
| Change Database Host | `POSTGRES_HOST` | Hostname or IP of PostgreSQL server |
| Change Database Port | `POSTGRES_PORT` | Port (current value shown, not defaulted to 5432 in the prompt) |
| Change Database Name | `POSTGRES_DB` | Name of the EAS Station™ database |
| Change Database User | `POSTGRES_USER` | PostgreSQL user |
| Change Database Password | `POSTGRES_PASSWORD` | PostgreSQL password (input is masked) |

**There is no "Test Connection" option** — each change just writes the value
and reminds you a service restart may be needed; nothing validates
connectivity from within `eas-config`.

---

### 3. Alert Sources

Toggles and the shared poll interval for the two CAP feed sources. **There is
no feed-URL field here** — the actual feed URLs are configured elsewhere (see
[IPAWS Feed Integration](ipaws_feed_integration.md)'s `/admin/poller` page);
this menu only flips feeds on/off and sets timing.

| Option | Variable | Description |
|--------|----------|-------------|
| Toggle NOAA Weather Alerts | `NOAA_ALERTS_ENABLED` | Enable/disable the NOAA CAP feed |
| Toggle IPAWS Integration | `IPAWS_ENABLED` | Enable/disable the FEMA IPAWS feed |
| Configure NOAA Poll Interval | `CAP_POLL_INTERVAL` | Seconds between feed polls (default: **300**) |
| Configure IPAWS Settings | — | Informational only — points you at `IPAWS_URL` / `IPAWS_API_KEY` in `.env` for manual editing; no inline field |

---

### 4. Audio Settings

Only two of the four options actually edit a value here; the other two are
informational pointers to the web UI / manual `.env` editing.

| Option | Variable | Description |
|--------|----------|-------------|
| Toggle Icecast Streaming | `ICECAST_ENABLED` | Enable/disable Icecast output |
| Configure Icecast Port | `ICECAST_PORT` | Icecast server port |
| Configure Receivers | — | Informational only — points to the web UI (`Settings → Radio`) and `/opt/eas-station/config/`; no inline field |
| Configure Broadcast Settings | — | Informational only — names `BROADCAST_ENABLED` / `BROADCAST_VOLUME` / `AUDIO_OUTPUT_DEVICE` as things to edit manually in `.env`; no inline field |

Receivers, TTS provider/region, Icecast host/source-password, and the ALSA
input device are all configured through the **web UI** (Settings → Radio /
Settings → TTS / Settings → Icecast), not through `eas-config`.

---

### 5. Hardware Integration

Hardware settings (GPIO, relays, OLED, LED signs, VFD, NeoPixel, Zigbee) are configured in the **web UI** and stored in the database — this menu entry simply points you there:

- Navigate to **Settings → Hardware Settings** (`/admin/hardware`).
- Environment variables in `.env` are no longer read for hardware configuration; legacy values were imported once during the database migration.

---

### 6. Network Settings

| Option | Description |
|--------|-------------|
| Change Web Interface Port | Sets the port the web UI listens on |
| View Firewall Status | Read-only — runs `ufw status numbered` |
| Configure Remote Access | Informational only — lists the default open ports (22/80/443/8000) and suggests `ufw allow PORT/tcp` manually; does not open ports itself |

**There is no Tailscale toggle or static-IP option in `eas-config`.** For
Tailscale, see [Tailscale Setup](TAILSCALE_SETUP.md); for opening firewall
ports, run `ufw` directly or use the web UI's own firewall admin page.

---

### 7. Advanced Options

| Option | Variable | Description |
|--------|----------|-------------|
| Change Log Level | `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| Toggle Debug Mode | `DEBUG` | Enable/disable debug mode |
| Performance Tuning | — | Informational only — names `WORKER_PROCESSES` / `MAX_CONNECTIONS` / `CACHE_SIZE` / `POOL_SIZE` as things to edit manually in `.env`; no inline field |
| View System Logs | — | Lists the 5 most recently modified files under `/var/log/eas-station/*.log` and suggests `tail -f` |

There is no `LOG_MAX_BYTES`, `REDIS_URL`, or `SECRET_KEY` field anywhere in
this menu — those aren't configurable through `eas-config`.

---

### 8. View Current Configuration

Displays the current `.env` file contents with sensitive values masked. Use this to confirm your changes were saved correctly.

---

### 9. Restart Services

Presents a confirmation dialog, then runs:

```bash
systemctl restart eas-station.target
```

This restarts all EAS Station™ services in the correct order.

---

## How Changes Are Applied

1. `eas-config` reads the current value from `/opt/eas-station/.env`.
2. When you confirm a change, it updates the matching key in `.env` using a safe `awk`-based replacement.
3. New keys are appended if they do not already exist.
4. After saving, you are offered the option to restart services immediately.

Changes to database or secret key settings always require a service restart to take effect.

---

## Running Without a Terminal (SSH)

`eas-config` works over SSH with any terminal emulator that supports ncurses. Ensure your SSH client is configured to forward the terminal type:

```bash
ssh -t user@eas-station sudo eas-config
```

The `-t` flag allocates a pseudo-TTY, which is required for the whiptail interface.

---

## Troubleshooting

### "This script must be run as root"

Run with `sudo`:

```bash
sudo eas-config
```

### "whiptail is required but not installed"

```bash
sudo apt-get install whiptail
```

### Display is garbled or menus are misaligned

Set the `TERM` variable before running:

```bash
TERM=xterm sudo eas-config
```

### Changes are not taking effect

Ensure services were restarted after making changes (option 9 in the main menu, or manually):

```bash
sudo systemctl restart eas-station.target
```

### Configuration file not found

The tool expects `.env` at `/opt/eas-station/.env`. If your installation uses a different path, set the `CONFIG_FILE` variable:

```bash
CONFIG_FILE=/path/to/.env sudo eas-config
```
