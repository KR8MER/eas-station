# Troubleshooting 502/504 Gateway Errors

## Quick Diagnostic

If you're seeing 502 or 504 errors, run this diagnostic script first:

```bash
sudo bash /opt/eas-station/scripts/diagnose_502_504.sh
```

This will check all common causes and tell you exactly what's wrong.

## Problem Description

### 502 Bad Gateway
The web service is not responding at all. This means:
- Gunicorn workers are crashing on startup, OR
- Workers cannot be reached by nginx, OR
- Workers fail to import app.py

### 504 Gateway Timeout  
The web service starts but takes too long to respond. This means:
- Database initialization is hanging, OR
- Workers are stuck during startup, OR
- First request triggers long-running operation

## Common Causes (In Order of Likelihood)

### 1. App Import Failure (MOST COMMON for immediate 502)

**Symptom**: Service fails immediately after installing SoapySDR or other system Python packages

**Root Cause**: The venv is created with `--system-site-packages`, which allows system packages (python3-numpy, python3-scipy, python3-soapysdr) to be visible inside the venv. These system packages have C extensions that may conflict with gevent's greenlet C extensions, causing immediate segfaults or import errors.

**Check**:
```bash
# Run the gevent compatibility check
/opt/eas-station/venv/bin/python3 /opt/eas-station/scripts/check_gevent_compat.py
```

Look for warnings about numpy loaded from `/usr/lib` or `/usr/local/lib`.

**Fix - Reinstall Conflicting Packages in Venv**:
```bash
cd /opt/eas-station
source venv/bin/activate

# Force reinstall gevent and greenlet to rebuild C extensions
pip install --force-reinstall 'gevent>=25.9.1' greenlet

# If numpy conflict detected, reinstall in venv to override system version
pip install --force-reinstall numpy

# Reinstall any other packages showing conflicts
pip install --force-reinstall scipy

deactivate
sudo systemctl restart eas-station-web.service
```

**Alternative Fix - Rebuild Venv Without System Packages** (more drastic):
```bash
# Backup current requirements
pip freeze > /tmp/eas-requirements-backup.txt

# Remove old venv
sudo rm -rf /opt/eas-station/venv

# Create new venv WITHOUT system packages
sudo -u eas-station python3 -m venv /opt/eas-station/venv

# Reinstall packages
cd /opt/eas-station
source venv/bin/activate
pip install -r requirements.txt
deactivate

# Restart services
sudo systemctl restart eas-station.target
```

**Note**: The SDR service needs SoapySDR from system packages, but the web service does NOT. Future versions may use separate venvs for each service.

### 2. Missing Dependencies

**Check**:
```bash
/opt/eas-station/venv/bin/python3 /opt/eas-station/scripts/check_dependencies.py
```

**Specific Check for gevent** (REQUIRED for WebSockets):
```bash
/opt/eas-station/venv/bin/python3 -c "import gevent; print('gevent version:', gevent.__version__)"
```

If this fails with `ModuleNotFoundError: No module named 'gevent'`, install it:
```bash
cd /opt/eas-station
source venv/bin/activate
pip install 'gevent>=25.9.1'
deactivate
sudo systemctl restart eas-station-web.service
```

**Fix All Missing Dependencies**:
```bash
cd /opt/eas-station
source venv/bin/activate
pip install -r requirements.txt
deactivate
sudo systemctl restart eas-station-web.service
```

### 3. Permission Issues

**Symptom**: Service starts but worker crashes during initialization

**Check Permissions**:
```bash
# Check if venv is owned by correct user
ls -la /opt/eas-station/venv

# Check if log directory exists and has correct permissions
ls -ld /var/log/eas-station

# Check if project directory has correct permissions
ls -ld /opt/eas-station
```

**Fix Permissions**:
```bash
# Fix project directory ownership
sudo chown -R eas-station:eas-station /opt/eas-station

# Create and fix log directory
sudo mkdir -p /var/log/eas-station
sudo chown eas-station:eas-station /var/log/eas-station
sudo chmod 755 /var/log/eas-station

# Restart service
sudo systemctl restart eas-station-web.service
```

### 4. Database Connection Issues

**Symptom**: Service starts but hangs during database initialization

**Check Database**:
```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql

# Test database connection
sudo -u eas-station psql -d eas_station -c "SELECT version();"
```

**Fix Database**:
```bash
# Start PostgreSQL if not running
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Verify database exists
sudo -u postgres psql -l | grep eas_station

# If database doesn't exist, create it
sudo -u postgres createdb eas_station
sudo -u postgres psql -d eas_station -c "CREATE EXTENSION IF NOT EXISTS postgis;"

# Restart web service
sudo systemctl restart eas-station-web.service
```

### 5. Database Initialization Timeout

**Symptom**: Service times out after 90-300 seconds

**Check Timeout Settings**:
```bash
grep TimeoutStartSec /etc/systemd/system/eas-station-web.service
```

Should show `TimeoutStartSec=300` (5 minutes). If it shows less, the service file needs updating.

**Fix**: Update service file and reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart eas-station-web.service
```

### 6. Port Already in Use

**Symptom**: Service fails with "Address already in use"

**Check**:
```bash
sudo netstat -tlnp | grep :5000
# or
sudo lsof -i :5000
```

**Fix**:
```bash
# Kill process using port 5000
sudo kill <PID>

# Or if it's an old gunicorn process
sudo pkill -f gunicorn

# Restart service
sudo systemctl restart eas-station-web.service
```

## Diagnostic Commands

### View Recent Service Logs
```bash
# Last 50 lines
sudo journalctl -u eas-station-web.service -n 50

# Follow logs in real-time
sudo journalctl -u eas-station-web.service -f

# Logs since last boot
sudo journalctl -u eas-station-web.service -b
```

### Check Service Status
```bash
sudo systemctl status eas-station-web.service
```

### Test Manual Startup
```bash
# Stop the service
sudo systemctl stop eas-station-web.service

# Try running gunicorn manually as the service user
sudo -u eas-station bash -c '
cd /opt/eas-station
source venv/bin/activate
export $(cat .env | grep -v "^#" | xargs)
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 300 --worker-class gevent --log-level debug app:app
'
```

This will show detailed error messages that might not appear in the systemd journal.

### Check Python Import
```bash
# Test if app.py imports successfully
cd /opt/eas-station
/opt/eas-station/venv/bin/python3 -c "from app import app; print('✓ Import successful')"
```

## Quick Fix Checklist

Run these commands in order:

```bash
# 1. Check dependencies
/opt/eas-station/venv/bin/python3 /opt/eas-station/scripts/check_dependencies.py

# 2. Fix permissions
sudo chown -R eas-station:eas-station /opt/eas-station
sudo mkdir -p /var/log/eas-station
sudo chown eas-station:eas-station /var/log/eas-station

# 3. Verify database is running
sudo systemctl status postgresql

# 4. Reload systemd and restart service
sudo systemctl daemon-reload
sudo systemctl restart eas-station-web.service

# 5. Check if it worked
sudo systemctl status eas-station-web.service
```

## Still Not Working?

If the service still fails after trying the above:

1. **Collect full diagnostic information**:
```bash
# Save this output to share with support
{
  echo "=== Service Status ==="
  sudo systemctl status eas-station-web.service
  
  echo -e "\n=== Recent Logs ==="
  sudo journalctl -u eas-station-web.service -n 100 --no-pager
  
  echo -e "\n=== Dependency Check ==="
  /opt/eas-station/venv/bin/python3 /opt/eas-station/scripts/check_dependencies.py
  
  echo -e "\n=== Database Status ==="
  sudo systemctl status postgresql
  
  echo -e "\n=== Port 5000 Status ==="
  sudo netstat -tlnp | grep :5000
  
  echo -e "\n=== Permissions ==="
  ls -la /opt/eas-station/ | head -20
  ls -ld /var/log/eas-station
} > ~/eas-station-diagnostics.txt

cat ~/eas-station-diagnostics.txt
```

2. **Review the diagnostic output** for obvious issues

3. **Try manual startup** (see "Test Manual Startup" above) to see detailed errors

4. **Check for recent changes**:
   - Did you recently update the system or Python?
   - Did you modify the .env file?
   - Did you run any database migrations?

## Prevention

To prevent this issue in the future:

1. **Always test after updates**:
```bash
sudo ./update.sh
sudo systemctl status eas-station-web.service
```

2. **Monitor service health**:
```bash
# Add to cron to check hourly
0 * * * * systemctl is-active --quiet eas-station-web.service || systemctl restart eas-station-web.service
```

3. **Keep dependencies updated**:
```bash
cd /opt/eas-station
source venv/bin/activate
pip install --upgrade -r requirements.txt
deactivate
```
