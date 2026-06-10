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
   5  Hardware Integration    (GPIO, LED Signs, VFD)
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
| Database Host | `DATABASE_HOST` | Hostname or IP of PostgreSQL server |
| Database Port | `DATABASE_PORT` | Port (default: 5432) |
| Database Name | `DATABASE_NAME` | Name of the EAS Station™ database |
| Database Username | `DATABASE_USER` | PostgreSQL user |
| Database Password | `DATABASE_PASSWORD` | PostgreSQL password (input is masked) |
| Test Connection | — | Validates the entered credentials |

---

### 3. Alert Sources

Configure where EAS Station™ fetches CAP alerts from.

| Option | Variable | Description |
|--------|----------|-------------|
| NOAA Weather API URL | `NOAA_FEED_URL` | NOAA CAP atom feed URL |
| IPAWS Feed | `IPAWS_FEED_URL` | FEMA IPAWS CAP feed URL |
| Custom Feed URL | `CUSTOM_FEED_URL` | Additional CAP source |
| Poll Interval | `POLL_INTERVAL` | Seconds between feed polls (default: 60) |

---

### 4. Audio Settings

Configure audio inputs, Icecast streaming, and EAS broadcast parameters.

| Option | Variable | Description |
|--------|----------|-------------|
| Icecast Server Host | `ICECAST_HOST` | Icecast server hostname |
| Icecast Source Password | `ICECAST_SOURCE_PASSWORD` | Icecast source password |
| EAS Audio Output Device | `AUDIO_OUTPUT_DEVICE` | ALSA output device name |
| Audio Input Device | `AUDIO_INPUT_DEVICE` | ALSA input for monitoring |
| TTS Engine | `TTS_ENGINE` | `pyttsx3` or `azure` |
| Azure TTS Region | `AZURE_SPEECH_REGION` | Azure region for TTS (if using Azure) |

---

### 5. Hardware Integration

Configure GPIO relays, LED signs, and VFD displays.

| Option | Variable | Description |
|--------|----------|-------------|
| GPIO Enabled | `GPIO_ENABLED` | Enable/disable GPIO relay control |
| GPIO Chip | `GPIO_CHIP` | GPIO chip device (e.g., `gpiochip0`) |
| Transmit Relay Pin | `GPIO_TRANSMIT_PIN` | BCM pin number for transmitter relay |
| LED Sign Enabled | `LED_SIGN_ENABLED` | Enable/disable Alpha protocol LED sign |
| LED Sign Port | `LED_SIGN_PORT` | Serial port (e.g., `/dev/ttyUSB0`) |
| LED Sign Baud Rate | `LED_SIGN_BAUDRATE` | Serial baud rate (default: 9600) |
| VFD Enabled | `VFD_ENABLED` | Enable/disable Noritake VFD display |
| VFD Port | `VFD_PORT` | Serial port for VFD |

---

### 6. Network Settings

Configure firewall and remote access.

| Option | Description |
|--------|-------------|
| Configure UFW Firewall | Open/close ports for web UI, Icecast, and SSH |
| Enable Tailscale | Install and configure Tailscale VPN |
| Set Static IP | Configure a static IP for the primary network interface |
| View Open Ports | Display current ufw status |

---

### 7. Advanced Options

| Option | Variable | Description |
|--------|----------|-------------|
| Log Level | `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| Max Log Size | `LOG_MAX_BYTES` | Log rotation size threshold |
| Redis Host | `REDIS_URL` | Redis connection URL |
| Secret Key | `SECRET_KEY` | Flask session secret (auto-generates if blank) |
| Debug Mode | `FLASK_DEBUG` | Enable Flask debug mode (development only) |

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
