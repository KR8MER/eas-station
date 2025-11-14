# EAS Station Backup and Recovery Strategy

**Purpose:** Complete guide to backup procedures, recovery procedures, and retention policies for EAS Station.

**Audience:** System administrators, DevOps engineers

**Last Updated:** 2025-01-11

---

## Table of Contents

1. [Overview](#overview)
2. [Backup Components](#backup-components)
3. [Backup Procedures](#backup-procedures)
4. [Recovery Procedures](#recovery-procedures)
   - [Post-Restore Validation](#post-restore-validation)
5. [Retention Policy](#retention-policy)
6. [Testing](#testing)
7. [Troubleshooting](#troubleshooting)

---

## Overview

### Backup Strategy

EAS Station implements a comprehensive **3-2-1 backup strategy**:

- **3** copies of data (production + 2 backups)
- **2** different storage media types
- **1** copy off-site

### Recovery Objectives

| Metric | Target | Notes |
|--------|--------|-------|
| **RPO** (Recovery Point Objective) | 15 minutes | Max data loss acceptable |
| **RTO** (Recovery Time Objective) | 30 minutes | Max downtime acceptable |
| **Backup Frequency** | Every 6 hours | Automated via scheduler |
| **Backup Retention** | 7d / 4w / 6m | Daily/Weekly/Monthly |
| **Test Frequency** | Monthly | Restore test required |

### Tools and Interfaces

**Primary Interface: Web UI** (No command line required)

| Interface | Purpose | Location |
|-----------|---------|----------|
| **Backup Management** | Create, restore, download, validate, and delete backups | [/admin/backups](/admin/backups) |
| **Quick Backup** | One-click backup creation | [/admin/operations](/admin/operations) |
| **System Health** | Monitor backup directory, database, disk space | [/health/dependencies](/health/dependencies) |

**Command Line Tools** (For automation and advanced users)

| Tool | Purpose | Location |
|------|---------|----------|
| `create_backup.py` | Create backups via CLI | `tools/create_backup.py` |
| `restore_backup.py` | Restore backups via CLI | `tools/restore_backup.py` |
| `validate_restore.py` | Validate system after restore | `tools/validate_restore.py` |
| `backup_scheduler.py` | Automate backups (cron/systemd) | `tools/backup_scheduler.py` |
| `rotate_backups.py` | Apply retention policy | `tools/rotate_backups.py` |

---

## Backup Components

### What Gets Backed Up

#### 1. Configuration Files
- `.env` - Application configuration
- `docker-compose.yml` - Container orchestration
- `stack.env` - Stack defaults

**Why:** Required to recreate exact environment

#### 2. PostgreSQL Database
- Full SQL dump of all tables
- Includes alert history, user data, configurations
- Approximately 10-500 MB depending on alert volume

**Why:** Contains all application state and historical data

#### 3. Media Files
- `static/eas_messages/` - Generated EAS audio files
- `static/uploads/` - User-uploaded files
- `uploads/` - Application uploads

**Why:** Generated content that may be needed for audit/replay

#### 4. Docker Volumes
- `app-config` - Persistent configuration
- `certbot-conf` - SSL certificates
- `alerts-db-data` - Database files (if using embedded DB)

**Why:** Critical persistent data outside containers

### What Does NOT Get Backed Up

- **Log files** - Retained separately, not in backups
- **Temporary files** - Recreated automatically
- **Downloaded/cached data** - Can be re-fetched
- **Docker images** - Rebuilt from source

---

## Backup Procedures

### Method 1: Web Interface (Recommended - No Command Line Required)

The easiest way to create backups is through the web interface at **[/admin/backups](/admin/backups)**.

#### Creating a Manual Backup

1. **Navigate to Backup Management:**
   - Click **Admin** → **Backup & Restore** in the navigation menu
   - Or go directly to: `https://your-station.example.com/admin/backups`

2. **Review System Health:**
   - Check the dashboard at the top showing database, disk space, and backup directory status
   - Ensure all systems are healthy (green checkmarks)

3. **Create Backup:**
   - In the "Create New Backup" card, enter a label (e.g., "before-upgrade", "manual")
   - Select what to include:
     - ✓ **Include media files** (static/eas_messages, uploads) - adds ~2-5 MB
     - ✓ **Include Docker volumes** (app-config, certbot-conf) - adds ~1 MB
   - Click **Create Backup Now**

4. **Monitor Progress:**
   - A progress bar will appear showing backup status
   - Typical completion time: 1-3 minutes
   - You'll see a success message with backup details

5. **Verify Backup:**
   - The new backup appears in the "Existing Backups" table below
   - Check the size, timestamp, and green checkmark for validity

**Quick Backup Option:**
- Uncheck "Include media files" and "Include Docker volumes" for faster backups (30-60 seconds)
- Useful before quick configuration changes

#### Using the Quick Backup from Operations Page

For one-click backups:

1. Go to **[/admin/operations](/admin/operations)**
2. Scroll to the "Backup & Recovery" section
3. Enter a label and click **Create Backup**
4. For full backup management (restore, download, delete), click **Manage Backups**

### Method 2: Automated Backup (Recommended for Production)

#### Using Systemd Timer (Recommended)

1. **Configure the service:**
   ```bash
   sudo nano /etc/systemd/system/eas-backup.service
   ```
   
   Update paths and email:
   ```ini
   ExecStart=/usr/bin/python3 /opt/eas-station/tools/backup_scheduler.py \
       --output-dir /var/backups/eas-station \
       --label scheduled \
       --log-file /var/log/eas-backup.log \
       --notify admin@example.com
   ```

2. **Install and enable:**
   ```bash
   sudo cp examples/systemd/eas-backup.service /etc/systemd/system/
   sudo cp examples/systemd/eas-backup.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable eas-backup.timer
   sudo systemctl start eas-backup.timer
   ```

3. **Verify timer is active:**
   ```bash
   sudo systemctl status eas-backup.timer
   sudo systemctl list-timers | grep eas
   ```

4. **Test manual run:**
   ```bash
   sudo systemctl start eas-backup.service
   sudo journalctl -u eas-backup.service -f
   ```

#### Using Cron

1. **Install cron job:**
   ```bash
   sudo cp examples/cron/eas-backup.cron /etc/cron.d/eas-backup
   sudo nano /etc/cron.d/eas-backup  # Update paths and email
   ```

2. **Verify installation:**
   ```bash
   sudo cat /etc/cron.d/eas-backup
   sudo ls -l /etc/cron.d/eas-backup
   ```

3. **Test immediately:**
   ```bash
   sudo run-parts --test /etc/cron.d
   ```

### Method 3: Docker Volume Backup

For backing up individual Docker volumes:

```bash
# List volumes
docker volume ls

# Backup a specific volume
docker run --rm \
    -v eas-station_app-config:/data:ro \
    -v $(pwd):/backup \
    busybox \
    tar czf /backup/app-config-backup.tar.gz -C /data .

# Verify backup
ls -lh app-config-backup.tar.gz
```

---

## Recovery Procedures

### Full System Restore

**Scenario:** Complete system failure, need to restore everything.

**Time Required:** 15-30 minutes

**Required Role:** Admin only (restore operations are restricted)

#### Prerequisites

- Backup directory accessible
- EAS Station web interface running
- Admin account credentials

#### Web Interface Procedure (Recommended)

1. **Access Backup Management:**
   - Navigate to **[/admin/backups](/admin/backups)**
   - Review the list of available backups
   - Check the "Valid" column to ensure backup integrity

2. **Select Backup to Restore:**
   - Find the backup you want to restore (usually the most recent before the issue)
   - Click the **Restore** button in the Actions column

3. **Review Restore Options:**
   - A modal will appear with restore options:
     - **Full Restore** - Restores database, config, media, and volumes (recommended)
     - **Database Only** - Only restores the database (for database corruption)
     - **Configuration Only** - Only restores .env and docker-compose.yml
   - Read the warning carefully - restore operations will overwrite current data

4. **Create Safety Backup (Recommended):**
   - Before clicking "Restore", create a current backup first
   - This allows rollback if the restore doesn't work as expected
   - Click "Cancel", create a backup labeled "pre-restore", then return

5. **Confirm and Execute:**
   - Select your restore option (usually "Full Restore")
   - Click **Confirm Restore**
   - Monitor the progress bar - typical time is 5-15 minutes
   - Do not close your browser during restoration

6. **Verify Restoration:**
   - After completion, check the System Health dashboard at the top
   - All indicators should be green (Database, Disk Space, Backup Directory)
   - Navigate to **[/health/dependencies](/health/dependencies)** for detailed health check

7. **Functional Testing:**
   - Log in to web interface (you may need to log in again)
   - Check the map at **[/](/)**
   - Verify recent alerts at **[/alerts](/alerts)**
   - Review configuration at **[/admin/settings](/admin/settings)**
   - Test alert generation (if applicable)

### Database-Only Restore

**Scenario:** Database corruption, but configuration is fine.

**Time Required:** 5-10 minutes

#### Web Interface Procedure

1. **Navigate to [/admin/backups](/admin/backups)**
2. **Select the backup** you want to restore
3. **Click Restore** button
4. **In the modal, select "Database Only"** restore mode
5. **Click Confirm Restore**
6. **Monitor progress** - database restore is typically faster (2-5 minutes)
7. **Verify** - check that recent alerts appear correctly

The web interface automatically handles stopping/starting services as needed.

### Advanced: Command Line Procedures

> **Note:** The web interface at /admin/backups is the recommended method for all backup and restore operations. Command line procedures are provided for automation, scripting, and troubleshooting scenarios.

#### CLI: Full System Restore

```bash
# 1. Stop services (if running)
cd /opt/eas-station
docker compose down

# 2. List available backups
ls -lht /var/backups/eas-station/

# 3. Validate backup integrity
python3 tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/backup-20250111-143022 \
    --dry-run

# 4. Create safety backup (if possible)
python3 tools/create_backup.py --label pre-restore

# 5. Restore the backup
python3 tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/backup-20250111-143022

# 6. Start services
docker compose up -d

# 7. Verify restoration
curl http://localhost/health

# 8. Run automated post-restore validation
python3 tools/validate_restore.py
```

**Post-Restore Validation:** After any restore operation, it's recommended to run the automated validation script to verify system health. See [Post-Restore Validation](#post-restore-validation) below.

### Configuration-Only Restore

**Scenario:** Configuration error, need to revert settings.

**Time Required:** 2-5 minutes

```bash
# Restore configuration files only
python3 tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/backup-20250111-143022 \
    --skip-database \
    --skip-media \
    --skip-volumes

# Restart services to apply new configuration
docker compose restart
```

### Individual File Restore

**Scenario:** Need to restore just one file.

```bash
# Extract specific file from backup
BACKUP_DIR="/var/backups/eas-station/backup-20250111-143022"

# Restore .env file
cp "$BACKUP_DIR/.env" .env.restored
diff .env .env.restored

# Restore from media archive
cd /opt/eas-station
tar xzf "$BACKUP_DIR/eas-messages.tar.gz" \
    --wildcards \
    "eas_messages/specific-file.wav"
```

### Point-in-Time Recovery

**Scenario:** Need to restore to a specific date/time.

```bash
# List backups by date
ls -lht /var/backups/eas-station/

# Restore from specific timestamp
python3 tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/backup-20250111-020000-scheduled
```

### Post-Restore Validation

**Purpose:** Automated verification of system health after restore operations.

**Tool:** `tools/validate_restore.py` - Comprehensive validation script that checks:
- Web service availability
- Health endpoint status
- Database connectivity and migrations
- External dependencies
- Configuration file integrity
- GPIO availability (if configured)
- Audio device access (if configured)
- API endpoint accessibility

#### Web Interface Validation

After a restore completes:

1. **Check System Health Dashboard** (at top of any page)
   - Database should show as "connected"
   - All critical indicators should be green

2. **Visit Health Dependencies** at `/health/dependencies`
   - All services should report healthy status
   - Review any warnings or failures

3. **Manual Functional Tests:**
   - Log in (credentials should match the restored backup)
   - View alerts at `/alerts`
   - Check configuration at `/admin/settings`
   - Verify recent data appears correctly

#### Command Line Validation

Run the automated validation script immediately after restore:

```bash
# Basic validation (checks localhost:8080)
python3 tools/validate_restore.py

# Wait for services to fully start
python3 tools/validate_restore.py --wait 30

# Validate remote/custom host
python3 tools/validate_restore.py --host production.example.com --port 443

# From within Docker container
docker compose exec app python3 /app/tools/validate_restore.py
```

**Expected Output:**
```
======================================================================
EAS Station Post-Restore Validation
======================================================================
Target: http://localhost:8080

Checking Web Service... ✓
Checking Health Endpoint... ✓
Checking Database Connection... ✓
Checking Database Migrations... ✓
Checking Dependencies... ✓
Checking Configuration... ✓
Checking API Access... ✓
Checking GPIO Availability... ✓
Checking Audio Devices... ✓

======================================================================
Validation Results
======================================================================

✓ PASS: Web Service - Web service is responding at http://localhost:8080
✓ PASS: Health Endpoint - System reports healthy status
✓ PASS: Database Connection - Database is connected and accessible
✓ PASS: Database Migrations - All database migrations are applied
✓ PASS: Dependencies - All 4 dependencies are healthy
✓ PASS: Configuration - Configuration file found at /app-config/.env with all critical keys
✓ PASS: API Access - All 2 API endpoints are accessible
✓ PASS: GPIO Availability - GPIO hardware is available
✓ PASS: Audio Devices - Audio configuration endpoint accessible

======================================================================
Total: 9 checks | Passed: 9 | Failed: 0
======================================================================

✓ All validation checks PASSED

Next Steps:
1. Access the web UI and verify functionality
2. Check recent logs for any warnings:
   docker compose logs --since 10m | grep -i warning
3. Review system health in the admin dashboard
```

**If Validation Fails:**

The script will exit with code 1 and show failed checks. Common issues:

- **Database Connection Failed**: Check PostgreSQL is running: `docker compose ps alerts-db`
- **Pending Migrations**: Run migrations: `docker compose exec app python -m alembic upgrade head`
- **Dependencies Failed**: Check dependent services: `docker compose ps`
- **Configuration Missing**: Verify .env file was restored: `ls -la .env`

**Exit Codes:**
- `0`: All validations passed
- `1`: One or more validations failed
- `2`: Configuration or runtime error

**Automation Integration:**

Include validation in automated restore workflows:

```bash
#!/bin/bash
# automated_restore.sh

# Restore backup
python3 tools/restore_backup.py --backup-dir "$BACKUP_DIR" || exit 1

# Restart services
docker compose up -d

# Wait for startup
sleep 30

# Validate restore
python3 tools/validate_restore.py --wait 30
VALIDATION_RESULT=$?

if [ $VALIDATION_RESULT -eq 0 ]; then
    echo "✓ Restore validation successful"
    exit 0
else
    echo "✗ Restore validation failed - check logs"
    docker compose logs --tail=50
    exit 1
fi
```

---

## Retention Policy

### Grandfather-Father-Son (GFS) Strategy

| Type | Retention | Description | Storage Location |
|------|-----------|-------------|------------------|
| **Daily** (Son) | 7 days | Most recent 7 backups | Local disk |
| **Weekly** (Father) | 4 weeks | Sunday backups from last 4 weeks | Local + NAS |
| **Monthly** (Grandfather) | 6 months | 1st of month backups | Local + Off-site |

### Automatic Rotation

The `backup_scheduler.py` automatically applies retention policy:

```bash
# Manual rotation
python3 tools/rotate_backups.py \
    --backup-dir /var/backups/eas-station \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 6

# Dry run to preview what would be deleted
python3 tools/rotate_backups.py \
    --backup-dir /var/backups/eas-station \
    --dry-run
```

**Expected output:**
```
Found 42 backup(s) in /var/backups/eas-station
Retention policy: 7 daily, 4 weekly, 6 monthly

Deleting: backup-20241201-020000 (age: 42 days, size: 15.2 MB)
Deleting: backup-20241208-020000 (age: 35 days, size: 16.1 MB)
...

Summary: Kept 17 backup(s), deleted 25 backup(s)
```

### Storage Requirements

**Example sizing** (your actual sizes may vary):

```
Daily backups (7):   7 × 20 MB  = 140 MB
Weekly backups (4):  4 × 20 MB  = 80 MB
Monthly backups (6): 6 × 20 MB  = 120 MB
-------------------------------------------
Total storage:                    340 MB
```

**Recommendation:** Allocate at least 1 GB for backup storage.

### Off-Site Backup

**Option 1: rsync to remote server**

```bash
#!/bin/bash
# /opt/eas-station/sync-to-offsite.sh

LOCAL_DIR="/var/backups/eas-station"
REMOTE_HOST="backup-server.example.com"
REMOTE_DIR="/backups/eas-station"

rsync -avz --delete \
    "$LOCAL_DIR/" \
    "${REMOTE_HOST}:${REMOTE_DIR}/" \
    2>&1 | logger -t eas-offsite-sync
```

Schedule via cron:
```
0 4 * * * /opt/eas-station/sync-to-offsite.sh
```

**Option 2: Cloud storage (AWS S3, Azure Blob, etc.)**

```bash
# AWS S3 example
aws s3 sync /var/backups/eas-station/ \
    s3://my-bucket/eas-station-backups/ \
    --delete \
    --storage-class STANDARD_IA
```

---

## Testing

### Monthly Restore Test

**Required:** Test backup restoration monthly to ensure backups are valid.

#### Test Procedure

1. **Create test environment:**
   ```bash
   # Use a separate directory or VM
   mkdir -p /opt/eas-station-test
   cd /opt/eas-station-test
   git clone https://github.com/KR8MER/eas-station.git .
   ```

2. **Restore from production backup:**
   ```bash
   python3 tools/restore_backup.py \
       --backup-dir /var/backups/eas-station/latest \
       --force
   ```

3. **Verify restoration:**
   ```bash
   docker compose up -d
   sleep 30
   curl http://localhost/health/dependencies
   ```

4. **Functional tests:**
   - Access web interface
   - Check database content
   - Verify configuration
   - Test basic functionality

5. **Document results:**
   ```bash
   # Create test report
   cat > /var/log/restore-test-$(date +%Y%m%d).txt << REPORT
   Restore Test - $(date)
   
   Backup Used: $(ls -ld /var/backups/eas-station/latest)
   Restoration Time: [X minutes]
   Database Records: [count]
   Health Check: [PASS/FAIL]
   Functional Test: [PASS/FAIL]
   
   Issues Found: [None or describe]
   
   Tester: [Your name]
   REPORT
   ```

6. **Clean up:**
   ```bash
   cd /opt/eas-station-test
   docker compose down -v
   cd /opt
   rm -rf eas-station-test
   ```

### Automated Test Script

```bash
#!/bin/bash
# /opt/eas-station/test-restore.sh

set -e

TEST_DIR="/tmp/eas-restore-test-$$"
BACKUP_DIR="/var/backups/eas-station/latest"
LOG_FILE="/var/log/eas-restore-test-$(date +%Y%m%d).log"

{
    echo "=== EAS Station Restore Test ==="
    echo "Started: $(date)"
    echo ""
    
    # Create test environment
    echo "Creating test environment..."
    mkdir -p "$TEST_DIR"
    cd "$TEST_DIR"
    git clone https://github.com/KR8MER/eas-station.git . --quiet
    
    # Restore backup
    echo "Restoring from backup: $BACKUP_DIR"
    python3 tools/restore_backup.py \
        --backup-dir "$BACKUP_DIR" \
        --force
    
    # Start services
    echo "Starting services..."
    docker compose up -d
    sleep 30
    
    # Health check
    echo "Running health check..."
    if curl -f http://localhost/health; then
        echo "✓ Health check PASSED"
    else
        echo "✗ Health check FAILED"
        exit 1
    fi
    
    # Cleanup
    echo "Cleaning up..."
    docker compose down -v
    cd /
    rm -rf "$TEST_DIR"
    
    echo ""
    echo "=== Test PASSED ==="
    echo "Completed: $(date)"
    
} 2>&1 | tee "$LOG_FILE"
```

Schedule monthly:
```
0 3 1 * * /opt/eas-station/test-restore.sh
```

---

## Troubleshooting

### Backup Issues

#### Backup Script Fails

**Problem:** `create_backup.py` exits with error

**Solutions:**

1. Check disk space:
   ```bash
   df -h /var/backups
   ```

2. Check permissions:
   ```bash
   ls -ld /var/backups/eas-station
   sudo chown -R $(whoami) /var/backups/eas-station
   ```

3. Check database connectivity:
   ```bash
   docker compose exec alerts-db pg_isready
   ```

4. Run in verbose mode:
   ```bash
   python3 -u tools/create_backup.py --label debug 2>&1 | tee /tmp/backup-debug.log
   ```

#### Backup Too Large

**Problem:** Backups consuming too much disk space

**Solutions:**

1. Check what's using space:
   ```bash
   du -sh /var/backups/eas-station/*
   ```

2. Adjust retention policy:
   ```bash
   python3 tools/rotate_backups.py \
       --backup-dir /var/backups/eas-station \
       --keep-daily 3 \
       --keep-weekly 2 \
       --keep-monthly 3
   ```

3. Exclude media if not needed:
   ```bash
   python3 tools/create_backup.py --no-media
   ```

4. Compress older backups:
   ```bash
   find /var/backups/eas-station -name "backup-*" -mtime +7 \
       -type d -exec tar czf {}.tar.gz {} \; -exec rm -rf {} \;
   ```

### Restore Issues

#### Database Restore Fails

**Problem:** Error during database restoration

**Solutions:**

1. Check database is accessible:
   ```bash
   docker compose ps alerts-db
   docker compose logs alerts-db
   ```

2. Manually verify backup SQL:
   ```bash
   head -100 /var/backups/eas-station/latest/alerts_database.sql
   tail -100 /var/backups/eas-station/latest/alerts_database.sql
   ```

3. Try restoring manually:
   ```bash
   docker compose exec -T alerts-db psql -U postgres < \
       /var/backups/eas-station/latest/alerts_database.sql
   ```

4. Check PostgreSQL version compatibility:
   ```bash
   # Compare versions
   docker compose exec alerts-db psql -U postgres -c "SELECT version();"
   grep "PostgreSQL" /var/backups/eas-station/latest/alerts_database.sql | head -1
   ```

#### Missing Backup Files

**Problem:** Backup directory empty or missing files

**Solutions:**

1. Check backup actually ran:
   ```bash
   sudo journalctl -u eas-backup.service -n 100
   tail -100 /var/log/eas-backup.log
   ```

2. Check timer is enabled:
   ```bash
   sudo systemctl status eas-backup.timer
   ```

3. Check alternative backup locations:
   ```bash
   find / -type d -name "backup-2025*" 2>/dev/null
   ```

4. Restore from off-site if available:
   ```bash
   rsync -avz backup-server:/backups/eas-station/ /var/backups/eas-station/
   ```

---

## Appendix A: Backup Checklist

### Pre-Upgrade Checklist

- [ ] Create manual backup with label
- [ ] Verify backup completed successfully
- [ ] Test backup can be read
- [ ] Document backup location
- [ ] Document current system state
- [ ] Have rollback plan ready

### Monthly Maintenance Checklist

- [ ] Run restore test
- [ ] Verify automated backups are running
- [ ] Check backup disk space
- [ ] Review retention policy
- [ ] Verify off-site sync working
- [ ] Update documentation if needed

### Quarterly Review Checklist

- [ ] Review backup strategy
- [ ] Test disaster recovery procedure
- [ ] Verify backup restoration times
- [ ] Update RTO/RPO targets if needed
- [ ] Review storage costs
- [ ] Train team on recovery procedures

---

## Appendix B: Backup Metadata

Each backup includes a `metadata.json` file:

```json
{
  "timestamp": "2025-01-11T14:30:22Z",
  "label": "scheduled",
  "git_commit": "abc123def456",
  "git_branch": "main",
  "app_version": "2.1.0",
  "database": {
    "host": "alerts-db",
    "port": "5432",
    "name": "alerts",
    "user": "postgres",
    "command": "pg_dump -U postgres -d alerts"
  },
  "summary": {
    "config": true,
    "database": true,
    "media": ["eas-messages"],
    "volumes": ["app-config", "certbot-conf"],
    "total_size_mb": 18.5
  }
}
```

And a `README.txt` with human-readable information.

---

**Document Version:** 1.0  
**Next Review Date:** [3 months from today]  
**Owner:** [Your team name]
