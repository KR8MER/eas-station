# Portainer Deployment Guide for EAS Station

> Complete instructions for deploying, maintaining, and upgrading EAS Station using Portainer

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
  - [Preparing the Environment File](#preparing-the-environment-file)
  - [Creating the Stack in Portainer](#creating-the-stack-in-portainer)
- [Stack Configuration](#stack-configuration)
  - [Using External PostgreSQL Database](#using-external-postgresql-database)
  - [Using Embedded PostgreSQL Database](#using-embedded-postgresql-database)
- [Deploying the Stack](#deploying-the-stack)
- [Post-Deployment Configuration](#post-deployment-configuration)
- [Updating to Latest Build](#updating-to-latest-build)
  - [Method 1: Pull and Redeploy (Recommended)](#method-1-pull-and-redeploy-recommended)
  - [Method 2: Using Watchtower](#method-2-using-watchtower)
  - [Method 3: In-App Upgrade Tool](#method-3-in-app-upgrade-tool)
- [Maintenance Tasks](#maintenance-tasks)
- [Backup and Restore](#backup-and-restore)
- [Monitoring and Health Checks](#monitoring-and-health-checks)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

---

## Overview

This guide provides complete instructions for deploying and maintaining EAS Station using **Portainer**, a popular Docker management UI. Portainer simplifies Docker operations through a web interface, making it ideal for managing emergency alerting infrastructure.

**What you'll learn:**
- How to deploy EAS Station as a Portainer stack
- How to configure environment variables through Portainer
- How to update to the latest builds
- How to monitor and maintain your deployment
- How to backup and restore your data

---

## Prerequisites

Before deploying EAS Station in Portainer, ensure you have:

### Required
- **Portainer installed and running** (Community Edition or Business Edition)
  - Portainer CE 2.19+ recommended
  - Access to the Portainer web interface
- **Docker Engine 24+** on the host system
- **Sufficient resources:**
  - 4GB RAM minimum (8GB recommended for heavy workloads)
  - 20GB free disk space (more if storing many audio files)
  - Network access for pulling Docker images and NOAA/IPAWS feeds

### Database Options (Choose One)
- **Option A (Recommended):** External PostgreSQL 15+ with PostGIS 3.x extension
  - Can be a managed database service (AWS RDS, Azure Database, etc.)
  - Can be a separate PostgreSQL container
  - Provides better data persistence and backup options
- **Option B:** Embedded PostgreSQL using the `embedded-db` profile
  - Simpler setup, database runs in the same stack
  - Requires configuring volume backups

### Optional Hardware (for full functionality)
- **SDR devices** for alert verification (RTL-SDR, Airspy, etc.)
- **Raspberry Pi GPIO** for relay control (if using hardware transmitter keying)
- **Alpha Protocol LED sign** for display integration

---

## Initial Setup

### Preparing the Environment File

Before creating the stack in Portainer, you need to prepare your environment variables:

1. **Download or view the `.env.example` file** from the repository:
   ```
   https://github.com/KR8MER/eas-station/blob/main/.env.example
   ```

2. **Generate a secure SECRET_KEY:**
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   Save this value - you'll need it for the Portainer environment configuration.

3. **Prepare your database credentials:**
   - If using external PostgreSQL: note your host, port, database name, user, and password
   - If using embedded PostgreSQL: decide on a strong password for the database

4. **Note your deployment preferences:**
   - Timezone (e.g., `America/New_York`)
   - Default location (county, state, SAME codes)
   - Whether you want EAS broadcasting enabled
   - LED sign IP (if applicable)

---

## Creating the Stack in Portainer

### Step 1: Access Portainer Stacks

1. Log in to your Portainer instance
2. Select your **Environment** (usually "local" or the name of your Docker host)
3. Navigate to **Stacks** in the left sidebar
4. Click **+ Add stack**

### Step 2: Name Your Stack

1. Enter a stack name: `eas-station`
2. Choose **Git Repository** as the build method (recommended) or **Web editor**

### Step 3: Configure Git Repository (Recommended Method)

If using Git Repository:

1. **Repository URL:** `https://github.com/KR8MER/eas-station`
2. **Repository reference:**
   - Leave blank for `main` branch (latest stable)
   - Or specify a tag like `v2.3.12` for a specific version
3. **Compose path:**
   - For external database: `docker-compose.yml`
   - For embedded database: `docker-compose.embedded-db.yml`
4. **Authentication:** None required (public repository)
5. Enable **Automatic updates** (optional):
   - Check "Enable webhook" to allow automatic redeployment
   - Set a poll interval (e.g., 5 minutes) to check for updates

### Step 4: Alternative - Web Editor Method

If you prefer to paste the compose file directly:

1. Copy the contents of `docker-compose.yml` from the repository
2. Paste into the **Web editor** in Portainer
3. Modify as needed for your environment

---

## Stack Configuration

### Environment Variables

In the Portainer stack configuration, scroll down to **Environment variables**. You have two options:

#### Option A: Advanced Mode (Recommended)

Click "Advanced mode" and paste your environment variables in `.env` format:

```ini
# CORE APPLICATION SETTINGS
SECRET_KEY=your-generated-secret-key-here
APP_BUILD_VERSION=2.3.12
NOAA_USER_AGENT=Your-Organization Emergency Alert Hub/2.1
FLASK_DEBUG=false
FLASK_ENV=production

# DATABASE CONNECTION
POSTGRES_HOST=your-database-host
POSTGRES_PORT=5432
POSTGRES_DB=alerts
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-secure-database-password

# CAP POLLER SETTINGS
POLL_INTERVAL_SEC=180
CAP_TIMEOUT=30

# LOGGING
LOG_LEVEL=INFO

# LOCATION DEFAULTS
DEFAULT_TIMEZONE=America/New_York
DEFAULT_COUNTY_NAME=Your County
DEFAULT_STATE_CODE=OH
DEFAULT_ZONE_CODES=OHZ016,OHC137

# SAME/EAS BROADCAST (if enabled)
EAS_BROADCAST_ENABLED=false
EAS_ORIGINATOR=WXR
EAS_STATION_ID=EASNODES
EAS_ATTENTION_TONE_SECONDS=8

# DOCKER/INFRASTRUCTURE
TZ=America/New_York
WATCHTOWER_LABEL_ENABLE=true
```

#### Option B: Simple Mode

Click "+ Add environment variable" for each setting and enter them individually.

### Critical Variables to Set

**Must configure:**
- `SECRET_KEY` - Generated secure random string
- `POSTGRES_HOST` - Database hostname
- `POSTGRES_PASSWORD` - Secure database password

**Should configure:**
- `DEFAULT_TIMEZONE` - Your local timezone
- `DEFAULT_COUNTY_NAME` - Your county name
- `DEFAULT_STATE_CODE` - Your state abbreviation
- `DEFAULT_ZONE_CODES` - Your NOAA zone codes

**Optional but recommended:**
- `EAS_BROADCAST_ENABLED` - Set to `true` if you want audio generation
- `LED_SIGN_IP` - If you have an LED sign
- `IPAWS_CAP_FEED_URLS` - If using IPAWS feeds

---

## Using External PostgreSQL Database

If you're using an external PostgreSQL database:

### Database Setup

1. **Create the database:**
   ```sql
   CREATE DATABASE alerts;
   ```

2. **Enable PostGIS:**
   ```sql
   \c alerts
   CREATE EXTENSION IF NOT EXISTS postgis;
   CREATE EXTENSION IF NOT EXISTS postgis_topology;
   ```

3. **Verify PostGIS installation:**
   ```sql
   SELECT PostGIS_Version();
   ```

### Environment Configuration

Set these variables in Portainer:

```ini
POSTGRES_HOST=your-db-host.example.com
POSTGRES_PORT=5432
POSTGRES_DB=alerts
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-database-password
```

**For Docker Desktop users:** If the database is on your host machine, use:
```ini
POSTGRES_HOST=host.docker.internal
```

---

## Using Embedded PostgreSQL Database

To use the embedded PostgreSQL database that runs within the stack:

### Step 1: Use the Embedded Compose File

When creating the stack, use:
- **Compose path:** `docker-compose.embedded-db.yml`

Or if using web editor, copy the embedded compose file from:
```
https://github.com/KR8MER/eas-station/blob/main/docker-compose.embedded-db.yml
```

### Step 2: Configure Database Variables

```ini
POSTGRES_HOST=alerts-db
POSTGRES_PORT=5432
POSTGRES_DB=alerts
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change-this-to-secure-password
```

### Step 3: Enable the Profile (if needed)

If using the standard `docker-compose.yml` with profiles:

1. Scroll to **Advanced deployment settings**
2. Find **Profiles**
3. Add: `embedded-db`

This activates the `alerts-db` service defined in the compose file.

---

## Deploying the Stack

### Step 1: Review Configuration

Before deploying:

1. ✅ Verify all required environment variables are set
2. ✅ Confirm `SECRET_KEY` is a secure random value
3. ✅ Verify database connection details are correct
4. ✅ Check compose file path is correct
5. ✅ Review resource limits if you added any

### Step 2: Deploy

1. Click **Deploy the stack** at the bottom of the page
2. Portainer will:
   - Pull the repository (if using Git method)
   - Build the Docker image (first time only)
   - Create and start all containers
   - Set up networking and volumes

### Step 3: Monitor Deployment

1. Watch the **Logs** tab to see the deployment progress
2. Look for these success indicators:
   - `Successfully built eas-station:latest`
   - `Database connection successful`
   - `Starting Gunicorn workers`
   - `Listening at: http://0.0.0.0:5000`

### Step 4: Verify Containers

Navigate to **Containers** and verify all services are running:

- ✅ `eas-station_app` - Status: Running
- ✅ `eas-station_poller` - Status: Running
- ✅ `eas-station_ipaws-poller` - Status: Running
- ✅ `eas-station_alerts-db` - Status: Running (if using embedded DB)

---

## Post-Deployment Configuration

### Step 1: Access the Application

1. Open your web browser
2. Navigate to: `http://your-server-ip:5000`
3. You should see the EAS Station dashboard

### Step 2: Complete First-Time Setup

If `SECRET_KEY` wasn't configured, you'll be redirected to the setup wizard:

1. Follow the on-screen prompts
2. Set a secure `SECRET_KEY`
3. Configure database connection
4. Save configuration
5. Restart the stack in Portainer

### Step 3: Create Admin Account

1. Navigate to: `http://your-server-ip:5000/admin`
2. Complete the **First-Time Administrator Setup**:
   - Enter a username (letters, numbers, `.`, `_`, `-` only)
   - Create a strong password (minimum 8 characters)
   - Confirm password
3. Click **Create Account**
4. Sign in with your new credentials

### Step 4: Configure Location Settings

1. Go to **Admin** → **Location Settings**
2. Set your:
   - County name and state code
   - NOAA zone codes
   - Area search terms
   - Map center coordinates
   - SAME location codes for broadcasting

### Step 5: Upload Geographic Boundaries (Optional)

If you have GeoJSON boundary files:

1. Go to **Admin** → **Boundaries**
2. Select boundary type (county, district, etc.)
3. Upload your GeoJSON file
4. Verify boundaries appear on the map

### Step 6: Configure SDR Receivers (Optional)

If you have SDR hardware:

1. Go to **Settings** → **Radio Receivers**
2. Click **Auto-Detect Devices**
3. Add detected receivers or create manual configurations
4. Test each receiver
5. Enable auto-start for automatic monitoring

---

## Updating to Latest Build

### Method 1: Pull and Redeploy (Recommended)

This is the safest method for Portainer-managed stacks:

#### Step 1: Pull Latest Changes

1. In Portainer, navigate to **Stacks**
2. Select your `eas-station` stack
3. Click **Pull and redeploy** (if using Git repository method)
4. Or click **Editor** → **Pull latest changes**

#### Step 2: Review Changes

1. Review any changes to the compose file
2. Check for new environment variables in `.env.example`
3. Add any new required variables to your stack environment

#### Step 3: Redeploy

1. Click **Update the stack**
2. Portainer will:
   - Pull the latest code from Git
   - Rebuild the Docker image if needed
   - Recreate containers with updated code
   - Preserve volumes and data

#### Step 4: Verify Update

1. Check container logs for successful startup
2. Visit the web interface
3. Check **Admin** → **System Operations** for the new version number
4. Run a test poll: **Admin** → **Manual Trigger Poll**

### Method 2: Using Watchtower

Watchtower can automatically update your containers:

#### Setup Watchtower (One-Time)

Add Watchtower to your stack or as a separate container:

```yaml
watchtower:
  image: containrrr/watchtower:latest
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
  environment:
    - WATCHTOWER_POLL_INTERVAL=86400  # Check daily
    - WATCHTOWER_CLEANUP=true
    - WATCHTOWER_LABEL_ENABLE=true
  command: --label-enable --cleanup
```

#### Enable Auto-Update Labels

Ensure your stack environment has:
```ini
WATCHTOWER_LABEL_ENABLE=true
```

Watchtower will automatically check for and apply updates daily.

### Method 3: In-App Upgrade Tool

For advanced users with terminal access:

1. Access the app container through Portainer:
   - **Containers** → `eas-station_app` → **Console**
   - Select `/bin/bash` and click **Connect**

2. Run the upgrade tool:
   ```bash
   python tools/inplace_upgrade.py
   ```

3. The tool will:
   - Fetch the latest code from Git
   - Rebuild the Docker image
   - Apply database migrations
   - Restart services
   - Preserve your data

---

## Maintenance Tasks

### Regular Maintenance Schedule

#### Daily
- **Check Health Dashboard:** `http://your-server:5000/system_health`
- **Review Latest Alerts:** Verify poller is fetching new alerts
- **Monitor Container Status:** Ensure all containers are running in Portainer

#### Weekly
- **Review Logs:** Check for any errors or warnings
  - In Portainer: **Containers** → Select container → **Logs**
- **Test Manual Broadcast:** If using EAS features
- **Check Disk Space:** Verify sufficient space for database and audio files
- **Review Compliance Dashboard:** `http://your-server:5000/admin/compliance`

#### Monthly
- **Backup Database:** See [Backup and Restore](#backup-and-restore)
- **Update Stack:** Pull latest changes and redeploy
- **Review User Accounts:** Remove unused accounts
- **Check SDR Health:** Verify receiver functionality
- **Required Monthly Test (RMT):** If operating as certified station

#### Quarterly
- **Review Documentation:** Check for updated guides
- **Security Audit:** Review passwords, update credentials
- **Performance Review:** Check resource usage trends
- **Disaster Recovery Test:** Verify backup restoration process

### Routine Operations via Portainer

#### Restarting Services

To restart a specific service:

1. **Containers** → Select container
2. Click **Restart**
3. Monitor logs for successful restart

To restart the entire stack:

1. **Stacks** → Select `eas-station`
2. Click **Stop**
3. Wait for all containers to stop
4. Click **Start**

#### Viewing Logs

1. **Containers** → Select container
2. Click **Logs**
3. Use search/filter to find specific events
4. Adjust lines (50, 100, 500, 1000)
5. Toggle **Auto-refresh** to monitor in real-time

#### Checking Resource Usage

1. **Containers** → Select container
2. View **Quick stats** panel:
   - CPU usage percentage
   - Memory usage
   - Network I/O
   - Block I/O

Or use **Stats** page for all containers:
- **Dashboard** → **Stats**

---

## Backup and Restore

### Automated Backup via Web UI

1. Navigate to **Admin** → **System Operations**
2. Click **Run Backup**
3. Enter an optional label (e.g., "pre-upgrade")
4. Click **Start Backup**
5. Download the backup files when complete

### Manual Database Backup

#### Using Portainer Console

1. **Containers** → Select `eas-station_alerts-db` (or your database container)
2. Click **Console**
3. Select `/bin/bash` → **Connect**
4. Run backup command:
   ```bash
   pg_dump -U postgres alerts > /tmp/backup_$(date +%Y%m%d_%H%M%S).sql
   ```

5. Copy backup file from container:
   - **Containers** → Select database container
   - Click **Copy from container**
   - Path: `/tmp/backup_*.sql`
   - Download to your local machine

#### Using Portainer Exec Feature

1. **Containers** → `eas-station_app`
2. **Console** → `/bin/bash`
3. Run backup script:
   ```bash
   python tools/create_backup.py --label portainer-backup
   ```

### Scheduling Automated Backups

#### Method 1: Portainer Webhooks + External Cron

1. In your stack, click **Webhooks**
2. Create a webhook for backup operations
3. Use external cron or scheduled task to call webhook

#### Method 2: Add Backup Container to Stack

Add to your `docker-compose.yml`:

```yaml
backup:
  image: eas-station:latest
  command:
    - /bin/bash
    - -c
    - |
      while true; do
        sleep 86400  # Daily backups
        python tools/create_backup.py --label daily-auto
      done
  volumes:
    - ./backups:/app/backups
  env_file:
    - .env
```

### Restoring from Backup

#### Via Portainer Console

1. Upload backup file to container:
   - **Containers** → Select database container
   - **Copy to container**
   - Upload your `.sql` backup file to `/tmp/`

2. Access database console:
   - **Containers** → Select `eas-station_alerts-db`
   - **Console** → `/bin/bash`

3. Restore database:
   ```bash
   psql -U postgres -d alerts < /tmp/your_backup.sql
   ```

#### Full Stack Restore

1. **Stop the stack:**
   - **Stacks** → `eas-station` → **Stop**

2. **Remove old volumes (if needed):**
   - **Volumes** → Select `eas-station_alerts-db-data`
   - **Remove volume** (⚠️ This deletes all data!)

3. **Restore .env file:**
   - Update stack environment variables from backup

4. **Restart stack:**
   - **Stacks** → `eas-station` → **Start**

5. **Restore database:**
   - Follow database restore steps above

---

## Monitoring and Health Checks

### Built-in Health Endpoints

EAS Station provides several monitoring endpoints:

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `/health` | Basic health check | `{"status": "ok"}` |
| `/ping` | Simple ping test | `{"status": "pong"}` |
| `/api/system_status` | System status summary | JSON with stats |
| `/api/system_health` | Detailed health metrics | JSON with all metrics |

### Portainer Health Monitoring

#### Container Health Status

Portainer shows health status for each container:

1. **Containers** → View list
2. Look for health indicator icons:
   - 🟢 Green: Healthy
   - 🟡 Yellow: Starting/Unhealthy
   - 🔴 Red: Failed/Stopped

#### Setting Up Alerts (Portainer Business)

If using Portainer Business Edition:

1. **Settings** → **Notifications**
2. Create notification webhook (Slack, email, etc.)
3. Set alerts for:
   - Container stopped
   - Container health check failed
   - High resource usage
   - Stack update failures

### External Monitoring Integration

#### Prometheus Metrics (Future Enhancement)

Add Prometheus exporter to stack:

```yaml
prometheus:
  image: prom/prometheus:latest
  volumes:
    - ./prometheus.yml:/etc/prometheus/prometheus.yml
  ports:
    - "9090:9090"
```

#### Uptime Monitoring

Use external services to monitor:
- HTTP endpoint: `http://your-server:5000/health`
- Expected response: `200 OK`
- Alert if down for > 2 minutes

### Log Aggregation

For production deployments, consider:

- **Portainer Logs:** View directly in Portainer interface
- **Docker Logging Drivers:** Configure JSON file, syslog, or other drivers
- **External Tools:** ELK Stack, Grafana Loki, Papertrail, etc.

---

## Troubleshooting

### Common Issues in Portainer

#### Issue: Stack fails to deploy

**Symptoms:**
- Red error message in Portainer
- Containers won't start
- "Failed to create network" errors

**Solutions:**

1. **Check compose syntax:**
   - Use **Validate** button in web editor
   - Ensure YAML indentation is correct

2. **Review environment variables:**
   - Verify all required variables are set
   - Check for typos in variable names
   - Ensure no special characters cause parsing issues

3. **Check port conflicts:**
   - In **Containers**, verify port 5000 isn't already in use
   - Change port mapping if needed: `8080:5000`

4. **Review logs:**
   - **Stacks** → `eas-station` → **Logs**
   - Look for specific error messages

#### Issue: Containers restart loop

**Symptoms:**
- Container status shows "Restarting"
- Logs show repeated startup attempts
- Services never become healthy

**Solutions:**

1. **Check database connection:**
   ```bash
   # In Portainer console for app container
   python -c "import psycopg2; print('Testing...')"
   ```

2. **Verify SECRET_KEY is set:**
   - Check environment variables in Portainer
   - Ensure SECRET_KEY exists and is not empty

3. **Review startup logs:**
   - Look for Python tracebacks
   - Check for missing dependencies

4. **Disable restart policy temporarily:**
   - Edit stack, change `restart: unless-stopped` to `restart: "no"`
   - Redeploy to see full error output

#### Issue: Can't pull latest updates

**Symptoms:**
- "Pull and redeploy" fails
- "Authentication required" errors
- "Repository not found" errors

**Solutions:**

1. **Verify Git repository URL:**
   - Correct: `https://github.com/KR8MER/eas-station`
   - Check for typos

2. **Check network connectivity:**
   - Portainer server must have internet access
   - Test: **Containers** → Any container → **Console** → `ping github.com`

3. **Try manual method:**
   - Use **Editor** mode
   - Copy updated compose file manually
   - Click **Update the stack**

#### Issue: Database connection fails

**Symptoms:**
- Errors: "could not connect to server"
- Database unavailable warnings in logs
- Admin panel shows database offline

**Solutions:**

1. **Verify database container is running:**
   - **Containers** → Check `alerts-db` status
   - If stopped, click **Start**

2. **Check POSTGRES_HOST setting:**
   - External DB: Use hostname or `host.docker.internal`
   - Embedded DB: Use `alerts-db` or `postgres`

3. **Test database connection:**
   ```bash
   # In app container console
   pg_isready -h $POSTGRES_HOST -U $POSTGRES_USER -d $POSTGRES_DB
   ```

4. **Review database logs:**
   - **Containers** → `alerts-db` → **Logs**
   - Look for connection rejections or authentication errors

5. **Verify PostGIS extension:**
   ```bash
   # In database container console
   psql -U postgres -d alerts -c "SELECT PostGIS_Version();"
   ```

#### Issue: Environment variables not applied

**Symptoms:**
- Changes to `.env` don't take effect
- Application uses old/default values
- Features remain disabled after enabling

**Solutions:**

1. **Redeploy the stack:**
   - Environment changes require redeployment
   - **Stacks** → `eas-station` → **Update the stack**

2. **Verify variables are saved:**
   - **Stacks** → `eas-station` → **Editor**
   - Scroll to environment variables section
   - Confirm your changes are present

3. **Check variable syntax:**
   - No quotes needed in Portainer advanced mode
   - Use `=` not `:` (`.env` format, not YAML)
   - No comments allowed in advanced mode

4. **Force recreation:**
   - Enable **Re-pull image and redeploy**
   - Enable **Force re-deployment**
   - Click **Update the stack**

### Getting Help

If you encounter issues not covered here:

1. **Check container logs in Portainer:**
   - **Containers** → Select container → **Logs**
   - Look for error messages and stack traces

2. **Review main documentation:**
   - [README.md](../../README.md)
   - [HELP.md](HELP.md)

3. **Check system health:**
   - Access: `http://your-server:5000/system_health`
   - Look for red indicators

4. **Search GitHub Issues:**
   - Visit: https://github.com/KR8MER/eas-station/issues
   - Search for similar problems

5. **Open a new issue:**
   - Include Portainer version
   - Include relevant logs (redact secrets!)
   - Describe steps to reproduce
   - Include environment details

---

## Advanced Configuration

### Custom Docker Networks

If you need to connect EAS Station to other stacks:

1. Create a custom network in Portainer:
   - **Networks** → **Add network**
   - Name: `eas-network`
   - Driver: `bridge`

2. Modify stack to use custom network:
   ```yaml
   networks:
     default:
       external: true
       name: eas-network
   ```

### Resource Limits

To prevent resource exhaustion:

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

### Volume Mounting for Persistence

To persist generated EAS audio files:

```yaml
services:
  app:
    volumes:
      - eas-messages:/app/static/eas_messages
      - eas-backups:/app/backups

volumes:
  eas-messages:
  eas-backups:
```

### Using Docker Secrets (Portainer Business)

For enhanced security with Portainer Business:

1. **Secrets** → **Add secret**
2. Create secrets for sensitive values:
   - `db_password`
   - `secret_key`
   - `azure_speech_key`

3. Reference in compose file:
   ```yaml
   services:
     app:
       secrets:
         - db_password
         - secret_key
       environment:
         POSTGRES_PASSWORD_FILE: /run/secrets/db_password
         SECRET_KEY_FILE: /run/secrets/secret_key

   secrets:
     db_password:
       external: true
     secret_key:
       external: true
   ```

### Multi-Stack Deployments

For redundancy, deploy multiple instances:

1. Create separate stacks:
   - `eas-station-primary`
   - `eas-station-backup`

2. Use different ports:
   ```yaml
   # Primary
   ports:
     - "5000:5000"

   # Backup
   ports:
     - "5001:5000"
   ```

3. Configure load balancer (nginx, HAProxy, etc.)

### Webhook Integration

To trigger stack updates via webhook:

1. **Stacks** → `eas-station` → **Webhooks**
2. Copy webhook URL
3. Configure GitHub webhook (optional):
   - Repository: `https://github.com/KR8MER/eas-station`
   - **Settings** → **Webhooks** → **Add webhook**
   - Payload URL: Your Portainer webhook URL
   - Content type: `application/json`
   - Events: Push events on `main` branch

4. Stack auto-updates on new commits

---

## Best Practices Summary

✅ **Do:**
- Use Git repository method for easy updates
- Set strong `SECRET_KEY` and database passwords
- Enable automatic backups
- Monitor container health regularly
- Review logs weekly
- Test updates in non-production first
- Document your configuration changes
- Keep Portainer itself updated

❌ **Don't:**
- Use default passwords in production
- Skip backups before updates
- Ignore container restart loops
- Delete volumes without backups
- Expose sensitive ports to internet
- Run with `FLASK_DEBUG=true` in production
- Commit secrets to version control

---

## Quick Reference

### Essential Portainer Paths

| Task | Navigation |
|------|------------|
| View stack | Stacks → eas-station |
| Update stack | Stacks → eas-station → Editor → Update |
| View containers | Containers |
| View logs | Containers → Select → Logs |
| Access console | Containers → Select → Console |
| Manage volumes | Volumes |
| Create backup | Containers → app → Console → `python tools/create_backup.py` |

### Key Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `SECRET_KEY` | Session security | Yes |
| `POSTGRES_HOST` | Database hostname | Yes |
| `POSTGRES_PASSWORD` | Database password | Yes |
| `EAS_BROADCAST_ENABLED` | Enable audio generation | No |
| `DEFAULT_TIMEZONE` | Local timezone | Recommended |
| `LED_SIGN_IP` | LED sign address | Optional |

### Useful Commands (via Console)

```bash
# Check Python version
python --version

# Test database connection
python -c "from app_core import db; db.session.execute('SELECT 1')"

# Run backup
python tools/create_backup.py

# Check app version
cat VERSION

# List environment variables
env | grep EAS

# View disk usage
df -h

# Check memory
free -h
```

---

**Made with ☕ and 📻 for Amateur Radio Emergency Communications**

**73 de KR8MER** 📡

---

*Last updated: 2025-11-02*
*Version: 2.3.12*
