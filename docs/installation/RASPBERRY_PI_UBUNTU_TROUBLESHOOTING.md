# Raspberry Pi & Ubuntu 24.04 Installation Troubleshooting

This guide addresses common installation issues on Raspberry Pi 4/5 with modern operating systems (Raspberry Pi OS Trixie/Bookworm, Ubuntu 24.04 LTS).

## Verified Compatible Systems

### ✅ Fully Tested & Supported

- **Debian 14 (Trixie)** - Reference platform, fully validated
- **Debian 12 (Bookworm)** - Production ready
- **Ubuntu 22.04 LTS** - Tested and working
- **Ubuntu 24.04 LTS** - Tested with Python 3.12, fully supported
- **Raspberry Pi OS (64-bit)** based on Debian Bookworm/Trixie

### 🔧 Python Version Compatibility

- **Python 3.11** ✅ Recommended for Debian Bookworm
- **Python 3.12** ✅ Default on Ubuntu 24.04, fully supported
- **Python 3.13** ✅ Supported with latest dependencies (Debian Trixie)

All required dependencies including `audioop-lts` (replaces deprecated `audioop` module) are included in `requirements.txt`.

## Common Installation Issues & Solutions

### Issue 1: audioop Module Not Found (Python 3.13+)

**Symptom:**
```
ModuleNotFoundError: No module named 'audioop'
ImportError: No module named 'audioop'
```

**Cause:** The `audioop` module was **deprecated in Python 3.11 and completely removed in Python 3.13**. This is a Python core change, not an EAS Station bug.

**Solution:** ✅ Already Fixed in Repository!

EAS Station uses `audioop-lts==0.2.2` as a drop-in replacement for the removed `audioop` module. This is **already included** in `requirements.txt` and the code automatically falls back:

```python
try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
```

**If you still see this error:**

1. Ensure you're running the latest version of install.sh:
   ```bash
   cd eas-station
   git pull origin main
   sudo bash install.sh
   ```

2. If install fails, manually install in the venv:
   ```bash
   sudo -u eas-station /opt/eas-station/venv/bin/pip install audioop-lts
   ```

### Issue 2: PostgreSQL/SQL Connection Errors

**Symptom:**
```
psycopg2.OperationalError: could not connect to server
FATAL:  password authentication failed for user "eas_station"
```

**Common Causes:**

1. **PostgreSQL not running**
   ```bash
   sudo systemctl status postgresql
   sudo systemctl start postgresql
   ```

2. **Database not created**
   ```bash
   sudo -u postgres psql -c "\l" | grep alerts
   ```
   
   If missing, run:
   ```bash
   sudo -u postgres createdb alerts
   sudo -u postgres createuser eas_station
   ```

3. **Authentication not configured** (pg_hba.conf)
   
   On Ubuntu 24.04/Trixie, PostgreSQL defaults to peer authentication. The installer should fix this, but you can verify:
   
   ```bash
   # Check PostgreSQL version
   psql --version
   
   # For PostgreSQL 16/17 (Ubuntu 24.04, Trixie)
   sudo nano /etc/postgresql/17/main/pg_hba.conf
   
   # Add these lines at the top:
   # local   all             eas_station                             scram-sha-256
   # host    all             eas_station     127.0.0.1/32            scram-sha-256
   ```
   
   Then restart:
   ```bash
   sudo systemctl restart postgresql
   ```

4. **Password mismatch in .env file**
   
   Check that `DATABASE_URL` in `/opt/eas-station/.env` matches the password set in PostgreSQL:
   ```bash
   sudo cat /opt/eas-station/.env | grep DATABASE_URL
   ```

### Issue 3: SoapySDR Python Bindings Not Found

**Symptom:**
```
ModuleNotFoundError: No module named 'SoapySDR'
⚠️  Python 3.13 detected - python3-soapysdr may not be available yet
```

**Cause:** System package `python3-soapysdr` may not be available for Python 3.13 yet on some distributions.

**Solutions:**

**Option 1: Use Python 3.12** (Recommended for Ubuntu 24.04)
```bash
# Ubuntu 24.04 comes with Python 3.12 by default - this should work fine!
python3 --version  # Should show 3.12.x
```

**Option 2: Install from system packages** (if available)
```bash
sudo apt-get update
sudo apt-get install python3-soapysdr soapysdr-tools
python3 -c "import SoapySDR; print(SoapySDR.getAPIVersion())"
```

**Option 3: Build from source** (Python 3.13 only, if needed)
```bash
# Install build dependencies
sudo apt-get install cmake g++ libpython3-dev swig

# Build SoapySDR
cd /tmp
git clone https://github.com/pothosware/SoapySDR.git
cd SoapySDR
mkdir build && cd build
cmake ..
make -j4
sudo make install
sudo ldconfig

# Build Python bindings
cd ../python
python3 setup.py build
sudo python3 setup.py install
```

**Note:** SDR functionality is optional. EAS Station will work without it for IPAWS/NOAA monitoring.

### Issue 4: pip install failures due to missing build tools

**Symptom:**
```
error: command 'gcc' failed with exit status 1
unable to execute 'gcc': No such file or directory
```

**Solution:**
```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    python3-dev \
    libpq-dev \
    libffi-dev \
    libssl-dev
```

Then retry:
```bash
sudo bash install.sh
```

### Issue 5: numpy/scipy build failures on Raspberry Pi

**Symptom:**
```
Failed building wheel for numpy
error: Could not find a version that satisfies the requirement numpy
```

**Solution:** Use pre-compiled system packages first, then install remaining dependencies:

```bash
# Install system numpy (compiled for ARM)
sudo apt-get install python3-numpy python3-scipy

# Then install EAS Station
cd eas-station
sudo bash install.sh
```

**For Raspberry Pi OS Bookworm specifically:**
The installer handles this automatically by detecting ARM architecture and using system packages where appropriate.

## Installation Best Practices

### Recommended Installation Order

1. **Start with a fresh OS install**
   - Raspberry Pi: Use Raspberry Pi Imager with 64-bit OS
   - Ubuntu: Use Ubuntu 24.04 LTS Server or Desktop

2. **Update system first**
   ```bash
   sudo apt-get update
   sudo apt-get upgrade -y
   sudo reboot
   ```

3. **Clone and install**
   ```bash
   git clone https://github.com/KR8MER/eas-station.git
   cd eas-station
   sudo bash install.sh
   ```

4. **Follow the interactive installer**
   - The TUI will guide you through all configuration
   - All settings are saved to `.env` automatically
   - No post-install configuration needed!

### What Gets Installed

The installer handles everything automatically:

- ✅ PostgreSQL 17 with PostGIS
- ✅ Redis 7.x
- ✅ Python 3.11/3.12/3.13 virtual environment
- ✅ All Python dependencies (50+ packages)
- ✅ Nginx with self-signed SSL
- ✅ Systemd services (web, poller, hardware, audio, SDR)
- ✅ Secure password generation
- ✅ Database initialization with Alembic migrations

## Post-Installation Checks

After installation completes, verify everything is running:

```bash
# Check all services
sudo systemctl status eas-station-web
sudo systemctl status eas-station-poller
sudo systemctl status eas-station-redis

# Check database connection
sudo -u eas-station /opt/eas-station/venv/bin/python3 -c "
from sqlalchemy import create_engine
import os, sys
sys.path.insert(0, '/opt/eas-station')
from dotenv import load_dotenv
load_dotenv('/opt/eas-station/.env')
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    print('✅ Database connection successful!')
"

# Check Python environment
sudo -u eas-station /opt/eas-station/venv/bin/pip list | grep -E "audioop|psycopg2|Flask"

# Access web interface
firefox https://localhost  # or your server's IP
```

## Specific OS Guidance

### Ubuntu 24.04 LTS on Raspberry Pi 4

**Known Issue:** Ubuntu 24.04 for Raspberry Pi may have limited ARM-optimized packages.

**Recommended Approach:**
1. Use **Raspberry Pi OS 64-bit** (Debian-based) instead of Ubuntu
2. OR use Ubuntu Server 22.04 LTS which has better ARM support
3. If you must use Ubuntu 24.04:
   ```bash
   # Install system packages for heavy dependencies
   sudo apt-get install python3-numpy python3-scipy
   # Then run install.sh
   ```

### Raspberry Pi OS Trixie (Debian 14)

**Status:** ✅ Fully Supported - This is the reference platform!

```bash
# Use Raspberry Pi Imager
# Choose: Raspberry Pi OS (64-bit) - Latest
# Flash to SD card, boot, then:

sudo apt-get update && sudo apt-get upgrade -y
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
sudo bash install.sh
```

### Raspberry Pi OS Bookworm (Debian 12)

**Status:** ✅ Production Ready

Same as Trixie, fully tested and validated.

## Getting Help

If you encounter issues not covered here:

1. **Check the logs:**
   ```bash
   sudo journalctl -u eas-station-web -n 100 --no-pager
   sudo journalctl -u eas-station-poller -n 100 --no-pager
   ```

2. **Run diagnostics:**
   ```bash
   cd /opt/eas-station
   sudo bash diagnose.sh
   ```

3. **File an issue:**
   - Visit: https://github.com/KR8MER/eas-station/issues
   - Include: OS version, Python version, error messages, logs

## Quick Reference: Tested Configurations

| OS | Version | Python | Status | Notes |
|---|---|---|---|---|
| Debian | 14 (Trixie) | 3.13 | ✅ Excellent | Reference platform |
| Debian | 12 (Bookworm) | 3.11 | ✅ Excellent | Production ready |
| Ubuntu | 24.04 LTS | 3.12 | ✅ Excellent | Fully supported |
| Ubuntu | 22.04 LTS | 3.10/3.11 | ✅ Good | Stable |
| Raspberry Pi OS 64-bit | Bookworm | 3.11 | ✅ Excellent | Recommended |
| Raspberry Pi OS 64-bit | Trixie | 3.13 | ✅ Excellent | Latest |
| Ubuntu for RPi | 24.04 | 3.12 | ⚠️ Caution | Use RPi OS instead |

## Summary

**The installation should "just work" on:**
- ✅ Ubuntu 24.04 LTS (any platform)
- ✅ Debian Trixie/Bookworm (any platform)
- ✅ Raspberry Pi OS 64-bit (Bookworm or Trixie)

**Common problems are usually:**
1. ❌ Running on 32-bit OS (use 64-bit!)
2. ❌ Outdated OS (run `apt-get upgrade`)
3. ❌ Missing internet connection during install
4. ❌ Insufficient RAM (need 2GB+)

**The installer handles:**
- ✅ All Python dependencies (including audioop-lts)
- ✅ PostgreSQL setup and authentication
- ✅ Virtual environment creation
- ✅ Service configuration
- ✅ Password generation

If you're still having issues after following this guide, please file an issue with:
- Exact OS version: `cat /etc/os-release`
- Python version: `python3 --version`
- Installation log/errors
- Output of: `sudo bash diagnose.sh`
