# Troubleshooting: Polling Not Working

## Symptom

The system shows a warning message:
```
No poll activity has been recorded yet; verify the poller service is running and configured.
```

This means the poller service hasn't successfully written any poll records to the database.

---

## Quick Diagnostic Steps

Run these commands to quickly identify the issue:

```bash
# 1. Check if poller service is running
sudo systemctl status eas-station-poller.service

# 2. Check recent logs
sudo journalctl -u eas-station-poller.service -n 100 --no-pager

# 3. Check if service is enabled
sudo systemctl is-enabled eas-station-poller.service

# 4. Verify database connection
sudo -u easstation psql -h localhost -U eas_station -d alerts -c "SELECT COUNT(*) FROM poll_history;"
```

---

## Common Issues and Solutions

### Issue 1: Service Not Running

**Symptoms:**
```bash
$ sudo systemctl status eas-station-poller.service
● eas-station-poller.service - EAS Station Alert Poller
   Loaded: loaded (/etc/systemd/system/eas-station-poller.service; enabled)
   Active: inactive (dead)
```

**Solution:**
```bash
# Start the service
sudo systemctl start eas-station-poller.service

# Enable it to start on boot
sudo systemctl enable eas-station-poller.service

# Check status again
sudo systemctl status eas-station-poller.service
```

---

### Issue 2: Service Failing to Start

**Symptoms:**
```bash
$ sudo systemctl status eas-station-poller.service
● eas-station-poller.service - EAS Station Alert Poller
   Loaded: loaded (/etc/systemd/system/eas-station-poller.service; enabled)
   Active: failed (Result: exit-code)
```

**Diagnosis:**
```bash
# Check recent logs for errors
sudo journalctl -u eas-station-poller.service -n 200 --no-pager

# Look for these common errors:
# - "could not connect to server" → Database connection issue
# - "Permission denied" → File/directory permissions
# - "No module named" → Python dependency missing
# - "No endpoints configured" → Configuration missing
```

**Common Fixes:**

**A. Database Connection Failed**
```bash
# Error: "could not connect to server: Connection refused"
# Cause: PostgreSQL not running or wrong credentials

# Check PostgreSQL is running
sudo systemctl status postgresql

# Start PostgreSQL if needed
sudo systemctl start postgresql

# Verify database credentials in .env
sudo nano /opt/eas-station/.env
# Check: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD

# Test connection manually
sudo -u easstation psql -h localhost -U eas_station -d alerts -c "\dt"
```

**B. Python Module Missing**
```bash
# Error: "No module named 'requests'" (or other module)
# Cause: Python dependencies not installed

# Reinstall requirements
sudo -u easstation pip3 install -r /opt/eas-station/requirements.txt

# Restart service
sudo systemctl restart eas-station-poller.service
```

**C. No Endpoints Configured**
```
Error: "No endpoints configured"
Cause: Missing IPAWS feed URLs and/or zone codes
```

Polling endpoints, the NOAA user-agent string, and location/zone codes are now
configured through the admin UI, not `.env`:

- **Poll interval, CAP timeout, NOAA user-agent, IPAWS feed URLs, lookback hours** —
  Settings → **Poller** (`/admin/poller`, persisted in the `poller_settings` table).
- **County, state, FIPS codes, NWS zone codes** —
  Settings → **Location** and Settings → **Alert Filtering**
  (`/admin/location_settings` and `/admin/alert_filtering`).

After saving, restart the poller so it picks up the new values:

```bash
sudo systemctl restart eas-station-poller.service
```

---

### Issue 3: Database Permission Denied

**Symptoms:**
```
ERROR: permission denied for table poll_history
```

**Solution:**
```bash
# Grant permissions to eas_station user
sudo -u postgres psql -d alerts << EOF
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO eas_station;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO eas_station;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO eas_station;
EOF

# Restart poller
sudo systemctl restart eas-station-poller.service
```

---

### Issue 4: Service Running But Not Polling

**Symptoms:**
- Service status shows "active (running)"
- But no poll records appear in database
- No errors in logs

**Diagnosis:**
```bash
# Check if poller is actually making requests
sudo journalctl -u eas-station-poller.service -f

# You should see lines like:
# "Polling: https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/..."
# "NOAA endpoint: https://api.weather.gov/alerts/active?zone=..."

# If you see nothing, the poller might be stuck or waiting
```

**Solutions:**

**A. Check the poll interval**
```
Default is 120 seconds (2 minutes).
If set too high, you'll wait a long time to see activity.
```

The poll interval is now stored in the database (`poller_settings.poll_interval_sec`)
and configured at Settings → **Poller** (`/admin/poller`). To inspect it from the
command line:

```bash
sudo -u easstation psql -h localhost -U eas_station -d alerts \
  -c "SELECT poll_interval_sec FROM poller_settings;"
# Should show 120 (or your configured value)
```

If the value is something like `3600` (1 hour), that's why you're not seeing
polls — lower it via the Poller settings page.

**B. Force Manual Poll**
```bash
# Run poller once manually to test
sudo -u easstation /usr/bin/python3 /opt/eas-station/poller/cap_poller.py \
  --database-url "postgresql://eas_station:YOUR_PASSWORD@localhost:5432/alerts" \
  --once

# Check for errors in output
```

**C. Check Network Connectivity**
```bash
# Test IPAWS feed access
curl -I "https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/2025-01-01T00:00:00-00:00"

# Should return: HTTP/2 200

# Test NOAA API access
curl -I "https://api.weather.gov/alerts/active?zone=OHZ016"

# Should return: HTTP/2 200

# If these fail, check firewall/network
```

---

### Issue 5: Wrong Database Credentials in Service File

**Symptoms:**
```
FATAL: password authentication failed for user "postgres"
```

**Root Cause:**
The systemd service file uses environment variables from `.env`, but if `POSTGRES_USER` is set differently in `.env` vs what the service expects, authentication fails.

**Diagnosis:**
```bash
# Check what the service file expects
grep "ExecStart" /etc/systemd/system/eas-station-poller.service

# Should show:
# ExecStart=/usr/bin/python3 /opt/eas-station/poller/cap_poller.py --continuous --database-url postgresql://postgres:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}

# Note: It hardcodes "postgres" as the user!
# But your .env might have POSTGRES_USER=eas_station
```

**Solution:**

**Option A: Update service file to use correct user**
```bash
# Edit service file
sudo nano /etc/systemd/system/eas-station-poller.service

# Change line 18 from:
ExecStart=/usr/bin/python3 /opt/eas-station/poller/cap_poller.py --continuous --database-url postgresql://postgres:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}

# To:
ExecStart=/usr/bin/python3 /opt/eas-station/poller/cap_poller.py --continuous --database-url postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}

# Reload systemd
sudo systemctl daemon-reload

# Restart service
sudo systemctl restart eas-station-poller.service
```

**Option B: Change .env to match service file**
```bash
# Edit .env
sudo nano /opt/eas-station/.env

# Change:
POSTGRES_USER=eas_station

# To:
POSTGRES_USER=postgres

# And grant permissions to postgres user
sudo -u postgres psql -d alerts << EOF
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;
EOF

# Restart service
sudo systemctl restart eas-station-poller.service
```

---

## Verification

After fixing the issue, verify polling is working:

```bash
# 1. Check service is running and healthy
sudo systemctl status eas-station-poller.service

# 2. Watch logs in real-time (wait at least one poll interval; default 120s)
sudo journalctl -u eas-station-poller.service -f

# You should see:
# "[CAP_POLLER] Starting continuous polling..."
# "Polling: https://apps.fema.gov/..."
# "Processed 0-X alerts from IPAWS"
# "Poll completed successfully"

# 3. Check database for poll records
sudo -u easstation psql -h localhost -U eas_station -d alerts -c "SELECT timestamp, status, data_source, alerts_fetched FROM poll_history ORDER BY timestamp DESC LIMIT 5;"

# Should show recent poll records with timestamps
```

---

## Prevention

### Enable Service on Boot

```bash
# Ensure poller starts automatically
sudo systemctl enable eas-station-poller.service

# Verify
sudo systemctl is-enabled eas-station-poller.service
# Should show: enabled
```

### Monitor Poller Health

Add to cron to check poller health:

```bash
# Edit crontab
crontab -e

# Add (checks every 15 minutes):
*/15 * * * * systemctl is-active --quiet eas-station-poller.service || systemctl start eas-station-poller.service
```

### Check Logs Regularly

```bash
# Add alias to .bashrc for easy log checking
echo 'alias poller-logs="sudo journalctl -u eas-station-poller.service -n 100 --no-pager"' >> ~/.bashrc
source ~/.bashrc

# Now you can just run:
poller-logs
```

---

## Related Documentation

- [IPAWS Feed Integration Guide](../guides/ipaws_feed_integration.md)
- [Installation Details](../installation/INSTALLATION_DETAILS.md)

---

## Still Not Working?

If none of these solutions work, gather diagnostic information:

```bash
# Create diagnostics bundle
mkdir -p /tmp/eas-diagnostics

# Service status
sudo systemctl status eas-station-poller.service > /tmp/eas-diagnostics/service-status.txt

# Recent logs
sudo journalctl -u eas-station-poller.service -n 500 --no-pager > /tmp/eas-diagnostics/poller-logs.txt

# Configuration (with passwords redacted)
grep -v "PASSWORD\|SECRET\|KEY" /opt/eas-station/.env > /tmp/eas-diagnostics/config.txt

# Database check
sudo -u easstation psql -h localhost -U eas_station -d alerts -c "\dt" > /tmp/eas-diagnostics/db-tables.txt 2>&1

# Manual test run
sudo -u easstation /usr/bin/python3 /opt/eas-station/poller/cap_poller.py --once --database-url "postgresql://eas_station:REDACTED@localhost:5432/alerts" > /tmp/eas-diagnostics/manual-run.txt 2>&1

# Package everything
tar -czf /tmp/eas-diagnostics.tar.gz -C /tmp eas-diagnostics/

echo "Diagnostics saved to /tmp/eas-diagnostics.tar.gz"
echo "Share this file when requesting support"
```
