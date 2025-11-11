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

### Tools

| Tool | Purpose | Location |
|------|---------|----------|
| `create_backup.py` | Create backups | `tools/create_backup.py` |
| `restore_backup.py` | Restore backups | `tools/restore_backup.py` |
| `backup_scheduler.py` | Automate backups | `tools/backup_scheduler.py` |
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

### Method 1: Manual Backup (Recommended for Pre-Upgrade)

#### Full Backup

```bash
cd /opt/eas-station

# Create comprehensive backup
python3 tools/create_backup.py \
    --output-dir /var/backups/eas-station \
    --label manual

# Verify backup was created
ls -lh /var/backups/eas-station/backup-*
```

**Expected Output:**
```
Creating backup: /var/backups/eas-station/backup-20250111-143022-manual

Backing up configuration files...
  ✓ Configuration files backed up

Backing up PostgreSQL database...
  ✓ Database backed up (15.3 MB)

Backing up media directories...
  ✓ static/eas_messages backed up (2.1 MB)

Backing up Docker volumes...
  ✓ Volume 'app-config' backed up (0.5 MB)
  ✓ Volume 'certbot-conf' backed up (0.1 MB)

============================================================
Backup completed successfully!
Location: /var/backups/eas-station/backup-20250111-143022-manual
Total size: 18.0 MB
Database: ✓
Media directories: 1
Docker volumes: 2
============================================================
```

#### Quick Backup (Config + Database Only)

For faster backups before quick changes:

```bash
python3 tools/create_backup.py \
    --output-dir /var/backups/eas-station \
    --label quick \
    --no-media \
    --no-volumes
```

This typically completes in 30-60 seconds.

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

#### Prerequisites

- Backup directory accessible
- Fresh EAS Station installation (git cloned)
- Docker and Docker Compose installed

#### Procedure

1. **Stop services** (if running):
   ```bash
   cd /opt/eas-station
   docker compose down
   ```

2. **Identify backup to restore:**
   ```bash
   ls -lht /var/backups/eas-station/
   
   # Or if using remote backups
   ls -lht /mnt/remote-backups/eas-station/
   ```

3. **Validate backup integrity:**
   ```bash
   python3 tools/restore_backup.py \
       --backup-dir /var/backups/eas-station/backup-20250111-143022 \
       --dry-run
   ```
   
   **Expected output:**
   ```
   Backup validation for: backup-20250111-143022
     Created: 2025-01-11T14:30:22Z
     Version: 2.1.0
     Database: ✓
     Config: ✓
     Media archives: 1
     Docker volumes: 2
   
   ✓ Backup validation passed
   ```

4. **Create safety backup** (if possible):
   ```bash
   # Backup current state before restoring
   python3 tools/create_backup.py --label pre-restore
   ```

5. **Restore the backup:**
   ```bash
   python3 tools/restore_backup.py \
       --backup-dir /var/backups/eas-station/backup-20250111-143022
   
   # You will be prompted to confirm each step
   # Review carefully before confirming
   ```

6. **Start services:**
   ```bash
   docker compose up -d
   ```

7. **Verify restoration:**
   ```bash
   # Wait for services to start
   sleep 30
   
   # Check health
   curl http://localhost/health/dependencies | jq
   
   # Check logs
   docker compose logs --tail=50
   
   # Access web interface
   curl -I http://localhost/
   ```

8. **Functional testing:**
   - Log in to web interface
   - Check recent alerts
   - Verify configuration settings
   - Test alert generation (if applicable)

### Database-Only Restore

**Scenario:** Database corruption, but configuration is fine.

**Time Required:** 5-10 minutes

```bash
# Stop application (keep database running if possible)
docker compose stop app noaa-poller ipaws-poller

# Restore database only
python3 tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/latest \
    --database-only \
    --force

# Restart application
docker compose start app noaa-poller ipaws-poller

# Verify
curl http://localhost/health
```

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
