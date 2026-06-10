# EAS Station™ Installation Details

## Installation Process

### How install.sh Works

The `install.sh` script uses an **interactive TUI (Text User Interface)** similar to raspi-config. Here's what happens when you run it:

```bash
git clone https://github.com/KR8MER/eas-station.git && \
cd eas-station && \
sudo bash install.sh
```

### Interactive Configuration (New!)

The installer now collects **all configuration during installation** using blue/gray dialog boxes (whiptail):

**You'll be asked to configure:**
1. **Administrator Account** - Username, password, email
2. **System Settings** - Hostname, domain, EAS originator, station callsign
3. **Location & Timezone** - Timezone, state, county, optional FIPS codes
4. **Alert Sources** - Enable/disable NOAA and IPAWS, set poll intervals
5. **Audio & Streaming** - Icecast streaming with auto-generated passwords
6. **Hardware Integration** - GPIO, LED signs, VFD displays

**Benefits:**
- ✅ Core configuration collected upfront — hardware, Icecast, and advanced options can be refined later in the web UI
- ✅ Input validation with helpful error messages
- ✅ Default values provided for quick setup
- ✅ Can cancel and restart anytime
- ✅ Settings saved to `/opt/eas-station/.env`

### Installation Flow

#### 1. **Pre-Installation Checks & Welcome** (10-30 seconds)
- ✓ Verifies script is run as root (sudo)
- ✓ Detects system architecture (x86_64, ARM, etc.)
- ✓ Detects OS (Debian, Ubuntu, Raspberry Pi OS)
- ⚠️ If OS is not Debian/Ubuntu, asks for confirmation to continue
- 🎨 **Displays welcome screen** with installation overview
- 📝 **Collects administrator account** - username, password, email (TUI dialogs)
- ⚙️ **Collects system configuration** - hostname, domain, originator, callsign (TUI dialogs)
- 📍 **Collects location settings** - timezone, state, county, FIPS codes (TUI dialogs)
- 📡 **Collects alert sources** - NOAA, IPAWS settings (TUI dialogs)
- 🎵 **Collects audio settings** - Icecast configuration (TUI dialogs)
- 🔌 **Collects hardware settings** - GPIO, LED, VFD (TUI dialogs)
- ✅ **Shows configuration summary** for confirmation

#### 2. **System Dependencies** (2-5 minutes)
- Updates package lists (`apt-get update`)
- Installs system packages:
  - Python 3, pip, venv
  - PostgreSQL 17 + PostGIS 3
  - Redis server
  - Nginx web server
  - FFmpeg, espeak (audio processing)
  - SDR libraries (SoapySDR, RTL-SDR, Airspy)
  - Build tools (gcc, g++, make)
  - SSL tools (certbot)

#### 3. **User and Directory Setup** (5-10 seconds)
- Creates `eas-station` system user and group
- Creates `/opt/eas-station` directory
- Creates `/var/log/eas-station` directory
- Adds user to hardware access groups (dialout, plugdev, gpio, audio)

#### 4. **Application Installation** (30-60 seconds)
- Copies entire repository to `/opt/eas-station`
- Excludes: .git, __pycache__, .pyc files
- Preserves: All application code, scripts, templates, static files
- Sets ownership to `eas-station:eas-station`

#### 5. **Python Environment** (2-5 minutes)
- Creates Python virtual environment in `/opt/eas-station/venv`
- Upgrades pip, setuptools, wheel
- Installs all Python dependencies from `requirements.txt`

#### 6. **Database Setup** (10-30 seconds)
- Starts PostgreSQL service
- Creates `alerts` database
- Creates `eas_station` database user with password
- Grants all privileges to user
- Installs PostGIS and PostGIS Topology extensions
- Optionally installs pgAdmin 4 for database management

#### 7. **Redis Setup** (5 seconds)
- Enables and starts Redis server
- Default configuration on localhost:6379

#### 8. **Configuration File Generation** (1 second)
- **Automatically generates** `/opt/eas-station/.env` with all settings collected during TUI
- **Auto-generates secure SECRET_KEY** using Python's secrets module (64 character hex)
- **Auto-generates secure database password** (43 character urlsafe)
- **Auto-generates Icecast passwords** if streaming enabled (16 characters each)
- **Includes all user-provided configuration:**
  - Administrator email
  - Hostname and domain
  - EAS originator and station callsign
  - Timezone, state, county, FIPS codes
  - Alert source settings (NOAA, IPAWS)
  - Icecast streaming configuration
  - Hardware integration settings (GPIO, LED, VFD)
- Sets file permissions to 600 (owner read/write only)

#### 9. **Database Initialization** (10-30 seconds)
- Runs Alembic migrations if any exist
- Creates all database tables
- Initializes schema with proper indexes and constraints
- Sets up RBAC roles and permissions
- Initializes NWS zone catalog

#### 10. **Hardware Configuration** (5 seconds)
- Creates udev rules for SDR devices (RTL-SDR, Airspy, HackRF)
- Grants proper USB device permissions

#### 11. **Systemd Services** (5 seconds)
- Copies service files to `/etc/systemd/system/`
- Services installed:
  - `eas-station.target` - Master service (controls all)
  - `eas-station-web.service` - Web UI (Flask/Gunicorn)
  - `eas-station-sdr.service` - SDR hardware service
  - `eas-station-audio.service` - Audio processing
  - `eas-station-eas.service` - EAS monitoring
  - `eas-station-hardware.target` - bundles the five Phase 4 per-subsystem units below
    - `eas-station-network.service` - nmcli proxy (port 5101)
    - `eas-station-zigbee.service` - zigpy coordinator (port 5102)
    - `eas-station-gps.service` - GPS manager + trends (port 5103)
    - `eas-station-displays.service` - OLED / VFD / LED rendering (port 5104)
    - `eas-station-gpio.service` - relays + alert indicators (port 5105)
  - `eas-station-poller.service` - Unified alert poller (NOAA + IPAWS)
  - `eas-station-hwsetup.service` - Hardware setup helper (oneshot, runs at boot)
  - `eas-station-postal.service` - Optional local Postfix mail server
- Reloads systemd daemon
- Enables services for auto-start on boot

#### 12. **Nginx Configuration** (5-10 seconds)
- Copies nginx configuration to `/etc/nginx/sites-available/eas-station`
- Generates self-signed SSL certificate for immediate HTTPS
- Enables site by symlinking to sites-enabled
- Removes default site
- Tests and reloads nginx

#### 13. **Service Startup** (5-10 seconds)
- **Automatically starts** all EAS Station™ services
- Waits 3 seconds for startup
- Checks if services are running
- Reports status

#### 14. **Completion** (immediate)
- Displays comprehensive summary
- Shows access URLs (localhost and detected IP)
- Lists next steps
- Shows useful commands

### Total Installation Time
- **Configuration**: 2-5 minutes (TUI dialogs)
- **Package Installation**: 5-7 minutes (fast hardware, good internet)
- **Total Minimal**: 7-12 minutes
- **Total Typical**: 12-20 minutes
- **Total Maximum**: 25-35 minutes (slower hardware/internet)

### What's Interactive vs Automated

**Interactive Configuration (TUI Dialogs):**
- ✅ Administrator account (username, password, email)
- ✅ System settings (hostname, domain, originator, callsign)
- ✅ Location & timezone (state, county, FIPS codes)
- ✅ Alert sources (NOAA, IPAWS, poll intervals)
- ✅ Audio settings (Icecast streaming)
- ✅ Hardware integration (GPIO, LED signs, VFD)

**Fully Automated (No User Input):**
- ✅ All package installation
- ✅ User and directory creation
- ✅ Application file copying
- ✅ Python dependency installation
- ✅ Database creation and configuration
- ✅ SECRET_KEY generation
- ✅ Database password generation
- ✅ Icecast password generation
- ✅ Configuration file creation with collected settings
- ✅ SSL certificate generation
- ✅ Service installation and startup

**Optional Post-Installation:**
1. **Fine-tune settings** via web interface at `/setup`
   - Advanced features like FIPS code lookup/builder
   - Zone code derivation from FIPS codes
2. **Reconfigure anytime** using `sudo eas-config` command
   - Provides same raspi-config style TUI
   - Update any setting without reinstalling
3. **Manual editing** of `/opt/eas-station/.env` for advanced users

**No Post-Install Wizard Required!** All essential boot-time configuration is collected during installation. Hardware integration, Icecast streaming, and advanced features can be fine-tuned afterwards in the web UI (`/admin/hardware`, `/admin/icecast`, `/setup`).

## Configuration File: Why .env?

### Why .env and Not .cfg?

The application uses `.env` because:

1. **Industry Standard** - `.env` files are the de facto standard for 12-factor app configuration
2. **Python-Dotenv Library** - The application uses `python-dotenv==1.0.1` which specifically reads `.env` files
3. **Environment Variables** - `.env` files are designed to export environment variables, which is how Flask and other Python frameworks read configuration
4. **Wide Support** - Most deployment tools, IDEs, and frameworks recognize `.env` files automatically
5. **Git-Friendly** - `.env` is in `.gitignore` by convention, preventing accidental commits of secrets

### .env vs .cfg Comparison

| Feature | .env | .cfg |
|---------|------|------|
| Flask/Django support | ✅ Native | ❌ Custom parser needed |
| Environment variables | ✅ Automatic | ❌ Manual loading |
| Systemd integration | ✅ Native | ⚠️ Requires conversion |
| IDE support | ✅ Built-in | ⚠️ Generic |
| Industry standard | ✅ Yes | ⚠️ For INI files |
| Secret management | ✅ Common | ⚠️ Less common |

### Configuration File Location

```
/opt/eas-station/.env
```

**Permissions**: 600 (owner read/write only)  
**Owner**: eas-station:eas-station

### How Configuration is Loaded

```python
# In app.py
from dotenv import load_dotenv

# Load from custom path or default .env
_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    load_dotenv(_config_path, override=True)
else:
    load_dotenv(override=True)  # Loads .env from current directory
```

### Configuration Priority

1. **Environment Variables** - Highest priority (system environment)
2. **.env File** - Middle priority (file in /opt/eas-station/)
3. **Application Defaults** - Lowest priority (hardcoded defaults)

This allows:
- Production: Use environment variables for secrets
- Development: Use .env for local overrides
- Testing: Use in-memory configuration

### Alternative: CONFIG_PATH Environment Variable

You can specify an alternate configuration file location:

```bash
# In systemd service file
Environment="CONFIG_PATH=/etc/eas-station/config.env"
```

But the file should still use `.env` format:
```bash
KEY=value
SECRET_KEY=abc123
DATABASE_URL=postgresql://...
```

## Post-Installation

### Verify Installation

```bash
# Check services
sudo systemctl status eas-station.target

# Check web service specifically
sudo systemctl status eas-station-web.service

# View logs
sudo journalctl -u eas-station-web.service -f

# Check database
sudo -u postgres psql -l | grep alerts

# Check configuration
sudo ls -lh /opt/eas-station/.env
```

### First-Time Access

1. Open browser to `https://your-server-ip`
2. Accept self-signed certificate (click "Advanced" → "Proceed")
3. Create admin account
4. Complete setup wizard

### No Manual Configuration Files to Edit!

Unlike traditional installations that require:
- ❌ Editing configuration files with nano/vi
- ❌ Manually generating secret keys
- ❌ Running database migrations
- ❌ Starting services manually

EAS Station™ does **everything automatically** and provides a **web-based setup wizard** for all configuration.

## Troubleshooting Installation

### Installation Fails

```bash
# Check where it failed
sudo journalctl -xe

# Re-run with verbose output
sudo bash -x install.sh 2>&1 | tee install.log
```

### Services Won't Start

```bash
# Check status
sudo systemctl status eas-station.target

# Check individual service
sudo systemctl status eas-station-web.service

# View detailed logs
sudo journalctl -u eas-station-web.service -n 100 --no-pager
```

### Database Issues

```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql

# Test connection
sudo -u postgres psql -d alerts -c "SELECT version();"

# Check if user exists
sudo -u postgres psql -c "\du" | grep eas_station
```

### Permission Issues

```bash
# Fix ownership
sudo chown -R eas-station:eas-station /opt/eas-station
sudo chown -R eas-station:eas-station /var/log/eas-station

# Fix permissions
sudo chmod -R 755 /opt/eas-station
sudo chmod 600 /opt/eas-station/.env
```

## Summary

**Installation is:**
- ✅ **Guided** - Interactive whiptail TUI collects all required configuration up front
- ✅ **Automated** - After the prompts, installation runs to completion without manual steps
- ✅ **Complete** - Installs and configures everything
- ✅ **Idempotent** - Safe to re-run if it fails
- ✅ **Fast** - 10-15 minutes on typical hardware

**Configuration is:**
- ✅ **Auto-Generated** - `.env` file created automatically
- ✅ **Secure by Default** - Random SECRET_KEY, proper permissions
- ✅ **Web-Based** - All user settings configured via UI
- ✅ **Standard Format** - Uses industry-standard `.env` format

**User Experience:**
1. Run one command
2. Wait 10-15 minutes
3. Open web browser
4. Create account and configure
5. Done!

No command-line configuration, no editing files with nano, no manual service management.

---

## Alternative Installation Methods

> **Status: design discussion, not shipped.** The sections below compare possible future installation methods. Today, the interactive `install.sh` bash script is the **only** supported installation method — the repository does not ship Ansible playbooks, Docker Compose files, or a `.deb` package, and `install.sh` does not yet support `--silent`/`--config` flags.

### Current Method: Bash Shell Script

The current `install.sh` provides an **interactive TUI-based installation** that:
- ✅ Works on any Debian/Ubuntu system without additional tools
- ✅ Provides visual feedback and progress indicators  
- ✅ Handles all configuration in one session
- ✅ Requires only `bash` and `whiptail` (auto-installed)
- ✅ Easy to debug and modify
- ⚠️ Must be run as root/sudo
- ⚠️ Not idempotent (can't safely re-run)

### 1. Ansible Playbook (Recommended for Production)

**Pros:**
- ✅ Idempotent - can safely re-run
- ✅ Version controlled configuration
- ✅ Multi-system deployment
- ✅ Role-based installation
- ✅ Better secret management (Ansible Vault)
- ✅ Built-in error handling and rollback

**Cons:**
- ❌ Requires Ansible to be installed first
- ❌ Steeper learning curve
- ❌ More complex for single-system installs

**Implementation:**
```yaml
# playbook.yml
- hosts: eas_stations
  roles:
    - postgresql
    - redis
    - eas-station
  vars:
    eas_admin_user: admin
    eas_state_code: OH
```

### 2. Docker / Docker Compose (Recommended for Development)

**Pros:**
- ✅ Isolated environment
- ✅ Easy to reset/rebuild
- ✅ No host system modifications
- ✅ Portable across platforms
- ✅ Built-in dependency management

**Cons:**
- ❌ SDR hardware access is complex
- ❌ GPIO access requires privileged mode
- ❌ Performance overhead
- ❌ Not suitable for production EAS

**Implementation:**
```dockerfile
# Dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y postgresql postgis redis
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["gunicorn", "app:app"]
```

### 3. Debian Package (.deb)

**Pros:**
- ✅ Native package management
- ✅ Automatic dependency resolution
- ✅ Clean uninstall
- ✅ Version tracking
- ✅ Signed packages

**Cons:**
- ❌ Complex to create and maintain
- ❌ Still requires post-install configuration
- ❌ Debian/Ubuntu only
- ❌ Package repository hosting

**Implementation:**
```bash
# Build .deb package
dpkg-deb --build eas-station_1.0.0_amd64

# Install
sudo dpkg -i eas-station_1.0.0_amd64.deb
sudo apt-get install -f  # Fix dependencies
```

### 4. Snap Package

**Pros:**
- ✅ Auto-updates
- ✅ Sandboxed
- ✅ Cross-distro (Ubuntu, Fedora, etc.)
- ✅ Centralized distribution

**Cons:**
- ❌ Hardware access restrictions
- ❌ Not suitable for SDR/GPIO
- ❌ Snapd overhead

### 5. Python Package (pip/PyPI)

**Pros:**
- ✅ Easy Python-based installation
- ✅ Virtual environment friendly
- ✅ Standard Python tooling

**Cons:**
- ❌ Doesn't handle system dependencies (PostgreSQL, Redis, nginx)
- ❌ No systemd service setup
- ❌ User must handle configuration

**Implementation:**
```bash
pip install eas-station
eas-station-setup  # Interactive config wizard
```

### 6. Makefile-based Installation

**Pros:**
- ✅ Standard Unix tool
- ✅ Fine-grained control
- ✅ Parallel execution
- ✅ Dependency tracking

**Cons:**
- ❌ Less user-friendly than bash script
- ❌ No built-in prompting/TUI
- ❌ Makefiles can be complex

### Recommendation Matrix

| Use Case | Best Method | Why |
|----------|-------------|-----|
| **First-time user / single Pi** | Current bash script | Interactive, simple, works immediately |
| **Multiple stations** | Ansible | Consistent deployment, centralized config |
| **Development / testing** | Docker Compose | Easy reset, isolated |
| **Production (single)** | Ansible or .deb | Professional, maintainable |
| **Air-gapped systems** | Bash script or .deb | No internet dependency |
| **CI/CD pipeline** | Docker | Automated testing |

### Improving the Current Bash Script

Instead of replacing the bash script, we can improve it:

1. **Add idempotency checks** - detect existing installation
2. **Configuration file support** - accept pre-configured values
3. **Silent mode** - non-interactive for automation
4. **Modular structure** - separate functions for each component
5. **Better error recovery** - rollback on failure

Example:
```bash
# Support pre-configured installation
sudo ./install.sh --config /path/to/config.env --silent

# Or interactive mode (current behavior)
sudo ./install.sh
```

### Hybrid Approach (Recommended)

Keep the current bash script as the **primary method** but add:

1. **Ansible roles** for multi-system deployment
2. **Docker Compose** for development
3. **Configuration templates** for automation
4. **--silent mode** to the bash script for CI/CD

This gives users flexibility while maintaining simplicity for the common case.

### Conclusion

The current bash script installation is **appropriate and efficient** for EAS Station™'s target audience because:

- Target users are familiar with command-line tools
- Single-system installation is the primary use case  
- Hardware integration (SDR, GPIO) requires host access
- Real-time audio processing benefits from native installation

**Recommendation:** Keep the bash script, add silent/config mode for automation.
