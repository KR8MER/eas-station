# Response to K6CRS Installation Issue

**To:** Carl, K6CRS  
**From:** EAS Station Development Team  
**Date:** January 28, 2026  
**Re:** Raspberry Pi 4 Installation Issues (SQL and audioop errors)

---

## Summary

Hi Carl,

Thank you for reaching out about your installation issues on Raspberry Pi 4! The good news is that **EAS Station should work on all the systems you tried** (Raspberry Pi OS Trixie, Bookworm, and Ubuntu 24.04 LTS). The errors you're encountering are known compatibility issues that have been addressed in the codebase, but let me help you troubleshoot.

## What's Causing Your Issues

### 1. audioop Errors (Python 3.13+)

**Issue:** The `audioop` module was **deprecated in Python 3.11 and completely removed in Python 3.13**. If you're seeing this error, you're likely on a system with Python 3.13 (like Raspberry Pi OS Trixie).

**Symptoms you might see:**
```
ModuleNotFoundError: No module named 'audioop'
ImportError: cannot import name 'audioop'
```

**Fix:** ✅ Already included in the repository!

The `requirements.txt` file includes `audioop-lts==0.2.2` which is a **drop-in replacement** for the removed `audioop` module. The code automatically detects and uses it:

```python
# From app_utils/eas_tts.py
try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
```

**If you're still seeing this error**, it means the Python dependencies didn't install completely. This usually happens if:
- The installation script encountered an error before reaching the `pip install` step
- There were missing build dependencies (gcc, python3-dev)
- The virtual environment wasn't created properly

### 2. SQL Errors

**Issue:** PostgreSQL authentication or connection failures.

**Common causes:**
1. PostgreSQL service not running
2. Database not created
3. pg_hba.conf not configured for password authentication (Ubuntu 24.04 defaults to "peer" auth)
4. Password mismatch in `.env` file

On modern systems (Ubuntu 24.04, Debian Trixie), PostgreSQL 16/17 requires explicit configuration for password-based authentication. The installer should handle this automatically, but sometimes it needs manual intervention.

## Recommended Solution

### Option 1: Try Raspberry Pi OS 64-bit (Bookworm or Trixie) - RECOMMENDED

**This is the known-good configuration:**

1. **Flash a fresh SD card** with Raspberry Pi OS 64-bit using Raspberry Pi Imager
   - Choose: "Raspberry Pi OS (64-bit)" - Latest version
   - This will be based on Debian Bookworm or Trixie

2. **Boot and update:**
   ```bash
   sudo apt-get update
   sudo apt-get upgrade -y
   sudo reboot
   ```

3. **Install EAS Station:**
   ```bash
   git clone https://github.com/KR8MER/eas-station.git
   cd eas-station
   sudo bash install.sh
   ```

4. **Follow the interactive installer** (blue TUI dialogs)
   - It will guide you through all configuration
   - All settings are saved automatically to `.env`
   - Database passwords are auto-generated securely

**This should work without any issues!** The installer is specifically tested on this platform.

### Option 2: Fix Your Current Installation

If you want to stick with your current OS, here's how to troubleshoot:

#### Step 1: Ensure build dependencies are installed

```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-venv \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    postgresql \
    postgresql-contrib \
    redis-server
```

#### Step 2: Check PostgreSQL is running

```bash
sudo systemctl status postgresql
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### Step 3: Manually create database and user (if needed)

```bash
# Check if database exists
sudo -u postgres psql -c "\l" | grep alerts

# If not, create it:
sudo -u postgres createdb alerts
sudo -u postgres psql -c "CREATE USER eas_station WITH PASSWORD 'your-secure-password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE alerts TO eas_station;"
sudo -u postgres psql -d alerts -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

#### Step 4: Configure PostgreSQL authentication

For Ubuntu 24.04 / Debian Trixie (PostgreSQL 16/17):

```bash
# Find your pg_hba.conf
sudo find /etc/postgresql -name pg_hba.conf

# Edit it (adjust version number as needed)
sudo nano /etc/postgresql/17/main/pg_hba.conf
```

Add these lines at the **top** of the file (before other entries):
```
local   all             eas_station                             scram-sha-256
host    all             eas_station     127.0.0.1/32            scram-sha-256
host    all             eas_station     ::1/128                 scram-sha-256
```

Then restart:
```bash
sudo systemctl restart postgresql
```

#### Step 5: Re-run the installer

```bash
cd eas-station
git pull origin main  # Get latest updates
sudo bash install.sh
```

## Known Good Configurations

Here are the tested and verified configurations:

| Platform | OS Version | Python Version | Status |
|----------|------------|----------------|--------|
| Raspberry Pi 4/5 | Raspberry Pi OS 64-bit (Bookworm) | 3.11 | ✅ **Recommended** |
| Raspberry Pi 4/5 | Raspberry Pi OS 64-bit (Trixie) | 3.13 | ✅ Excellent |
| Raspberry Pi 4 | Ubuntu 22.04 LTS | 3.10/3.11 | ✅ Good |
| Raspberry Pi 4 | Ubuntu 24.04 LTS | 3.12 | ⚠️ Works, but needs care |
| x86_64 PC | Debian 12 (Bookworm) | 3.11 | ✅ Production Ready |
| x86_64 PC | Debian 14 (Trixie) | 3.13 | ✅ Reference Platform |
| x86_64 PC | Ubuntu 24.04 LTS | 3.12 | ✅ Excellent |

### Why Raspberry Pi OS is Recommended Over Ubuntu for RPi

1. **Better ARM optimization** - Pre-compiled packages for Raspberry Pi hardware
2. **Simpler setup** - No conflicts with ARM-specific dependencies
3. **Better hardware support** - GPIO, I2C, SPI work out of the box
4. **Official support** - Tested and validated by the development team

Ubuntu on Raspberry Pi works, but requires more manual intervention for ARM-specific packages.

## For Your Confidence Monitor Use Case

Since you're using this as a **confidence monitor for your Sage Endecs**, you have a few options:

### Setup 1: Basic Monitoring (No SDR)
- **Minimum requirements:** Raspberry Pi 4 (2GB RAM)
- **OS:** Raspberry Pi OS 64-bit (Bookworm)
- **Features:** IPAWS/NOAA monitoring, web dashboard, alert logging
- **SDR:** Not needed if you're just monitoring the alert feeds

### Setup 2: Full Verification (With SDR)
- **Recommended:** Raspberry Pi 5 (4GB+ RAM)
- **OS:** Raspberry Pi OS 64-bit (Bookworm or Trixie)
- **Hardware:** RTL-SDR or Airspy for 162 MHz monitoring
- **Features:** Everything + broadcast verification via SDR

For a confidence monitor, **Setup 1 is probably what you want** - it will show you all the alerts being received and processed, without needing the SDR verification component.

## Next Steps

1. **If starting fresh:** Use Raspberry Pi OS 64-bit (Bookworm) - this is the path of least resistance
2. **If fixing current install:** Follow the troubleshooting steps above for your specific errors
3. **Join the community:** File issues on GitHub if you encounter specific errors with full logs

## Getting Detailed Logs

If you're still stuck, run these commands and share the output:

```bash
# System info
cat /etc/os-release
python3 --version
uname -a

# Check services
sudo systemctl status postgresql
sudo systemctl status redis-server

# Check Python environment
ls -la /opt/eas-station/venv/
/opt/eas-station/venv/bin/pip list | grep -E "audioop|psycopg2"

# Check database
sudo -u postgres psql -c "\l"
sudo -u postgres psql -c "\du"

# Installation diagnostic
cd /opt/eas-station
sudo bash diagnose.sh
```

## Additional Resources

I've created a comprehensive troubleshooting guide here:
- **File:** `docs/installation/RASPBERRY_PI_UBUNTU_TROUBLESHOOTING.md`
- **Covers:** All common installation issues, OS-specific fixes, and verified configurations

## Final Thoughts

The fact that you're seeing **different failures on different OSes** (SQL on some, audioop on others) suggests the installation process is partially working but hitting environment-specific issues. The good news is:

✅ The code **is** compatible with Python 3.11, 3.12, and 3.13  
✅ The `audioop-lts` dependency **is** already in requirements.txt  
✅ All three OSes you tried **are** supported  
✅ The installer **should** handle everything automatically

My recommendation: **Start fresh with Raspberry Pi OS 64-bit (Bookworm)** and let the installer do its thing. This is the most tested path and should work flawlessly.

73,  
EAS Station Development Team

---

**P.S.:** Once you're up and running, you'll love using this as a confidence monitor! The web dashboard gives you real-time visibility into what your Endecs are processing, with full alert history, spatial filtering, and detailed CAP message inspection.
