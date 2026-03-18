# Backup Strategy

This document describes the backup strategy for EAS Station, covering what is backed up, retention policies, scheduling, and recovery procedures.

---

## What Gets Backed Up

| Component | Included | Notes |
|-----------|----------|-------|
| PostgreSQL database | ✅ Always | Full `pg_dump` of all tables and data |
| Application configuration (`.env`) | ✅ Always | All database-based and environment settings |
| Backup metadata (`metadata.json`) | ✅ Always | Timestamp, version, backup label |
| Audio archives (`media/`) | ⚙️ Optional | Enable with `--include-media`; may be large |
| Static uploaded files | ⚙️ Optional | Enable with `--include-volumes` (see usage below) |

---

## Backup Schedule

EAS Station does not start a background backup scheduler automatically. Configure automated backups using cron or a systemd timer.

### Recommended Cron Schedule

```bash
sudo crontab -u eas-station -e
```

```cron
# Daily backup at 2:00 AM — database and config only
0 2 * * * /opt/eas-station/venv/bin/python /opt/eas-station/tools/create_backup.py \
  --output-dir /var/backups/eas-station \
  --label cron-daily \
  --no-media \
  >> /var/log/eas-station/backup.log 2>&1

# Weekly backup on Sunday at 3:00 AM — full backup including media
0 3 * * 0 /opt/eas-station/venv/bin/python /opt/eas-station/tools/create_backup.py \
  --output-dir /var/backups/eas-station \
  --label cron-weekly \
  >> /var/log/eas-station/backup.log 2>&1

# Delete daily backups older than 14 days
30 3 * * * find /var/backups/eas-station -maxdepth 1 -name "backup-*" \
  -type d -mtime +14 -exec rm -rf {} + 2>/dev/null

# Delete weekly backups older than 60 days
30 4 * * 0 find /var/backups/eas-station -maxdepth 1 -name "backup-*" \
  -type d -mtime +60 -exec rm -rf {} + 2>/dev/null
```

---

## Retention Policy

| Backup Type | Retention Period | Location |
|-------------|-----------------|----------|
| Daily (config + DB) | 14 days | `/var/backups/eas-station/` |
| Weekly (full) | 60 days | `/var/backups/eas-station/` |
| Pre-upgrade manual | Keep indefinitely | `/var/backups/eas-station/pre-upgrade-*/` |

---

## Storage Locations

### Local Storage (Default)

Backups are stored on the same host at `/var/backups/eas-station/`. Each backup is a directory named `backup-YYYY-MM-DDTHH-MM-SS/`.

```
/var/backups/eas-station/
├── backup-2025-01-15T02-00-00/
│   ├── alerts_database.sql
│   ├── .env
│   └── metadata.json
├── backup-2025-01-14T02-00-00/
│   └── ...
```

Override the default location in `.env`:

```
BACKUP_DIR=/mnt/nas/eas-station-backups
```

### Off-Site Storage (Recommended)

For disaster recovery, synchronize backups to off-site storage:

```bash
# Sync to remote server via rsync (run from cron)
rsync -az --delete /var/backups/eas-station/ \
    backup-user@backup-host:/backups/eas-station/

# Or use rclone for cloud storage (S3, Backblaze B2, etc.)
rclone sync /var/backups/eas-station/ remote:eas-station-backups
```

---

## Creating Backups

### Via the Web Interface

1. Navigate to **Admin → Backups**.
2. Click **Create Backup**.
3. Enter an optional label (e.g., `pre-upgrade`, `manual-weekly`).
4. Select whether to include media files.
5. Click **Create** and wait for the confirmation.

### Via the Command Line

```bash
# Activate virtualenv
source /opt/eas-station/venv/bin/activate
cd /opt/eas-station

# Database and config only (fastest)
python tools/create_backup.py \
    --output-dir /var/backups/eas-station \
    --label manual

# Full backup including audio archives
python tools/create_backup.py \
    --output-dir /var/backups/eas-station \
    --label full-backup \
    --include-media

# Full backup including audio archives and uploaded static files
python tools/create_backup.py \
    --output-dir /var/backups/eas-station \
    --label full-backup-with-volumes \
    --include-media \
    --include-volumes

# Pre-upgrade backup (recommended before updates)
python tools/create_backup.py \
    --output-dir /var/backups/eas-station \
    --label pre-upgrade-$(date +%Y%m%d)
```

---

## Restoring from Backup

### Via the Web Interface

1. Navigate to **Admin → Backups**.
2. Click **Restore** next to the desired backup.
3. Confirm the restore operation.
4. Wait for the confirmation. The service will restart automatically.

### Via the Command Line

```bash
# Restore from a specific backup
python tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/backup-2025-01-15T02-00-00

# Verify the backup before restoring
python tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/backup-2025-01-15T02-00-00 \
    --dry-run
```

### Manual PostgreSQL Restore

```bash
# Stop the application first
sudo systemctl stop eas-station-web eas-station-poller

# Drop and recreate the database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS eas_station;"
sudo -u postgres psql -c "CREATE DATABASE eas_station OWNER eas_station;"

# Restore from dump
sudo -u postgres psql eas_station < /var/backups/eas-station/backup-DATE/alerts_database.sql

# Restart services
sudo systemctl start eas-station-web eas-station-poller
```

---

## Backup Verification

Verify backups are healthy on a regular basis (at minimum monthly):

```bash
# List recent backups and their sizes
ls -lh /var/backups/eas-station/ | tail -20

# Check metadata of the most recent backup
cat $(ls -d /var/backups/eas-station/backup-* | sort | tail -1)/metadata.json | python3 -m json.tool

# Test a restore in a dry-run mode
python tools/restore_backup.py \
    --backup-dir $(ls -d /var/backups/eas-station/backup-* | sort | tail -1) \
    --dry-run
```

---

## Monitoring Backup Health

Add a health check to confirm backups are running:

```bash
# Check that a backup was created within the last 25 hours
find /var/backups/eas-station -maxdepth 1 -name "backup-*" \
    -type d -newer /tmp/.backup_check 2>/dev/null | head -1

# Alert if no recent backup exists (add to monitoring script)
LATEST=$(ls -d /var/backups/eas-station/backup-* 2>/dev/null | sort | tail -1)
if [ -z "$LATEST" ]; then
    echo "ERROR: No backups found!"
elif [ $(find "$LATEST" -maxdepth 0 -mtime +1 2>/dev/null | wc -l) -gt 0 ]; then
    echo "WARNING: Most recent backup is older than 24 hours"
else
    echo "OK: Backup is current - $LATEST"
fi
```

---

## Related Documentation

- [Database Backups Guide](../guides/DATABASE_BACKUPS.md)
- [Outage Response Runbook](outage_response.md)
- [Standby Deployment Guide](../../examples/STANDBY_DEPLOYMENT.md)
- [Disk Space Cleanup](../maintenance/DISK_SPACE_CLEANUP.md)
