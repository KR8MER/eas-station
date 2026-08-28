# Database Backups and Restore

EAS Station™ includes a built-in backup and restore system accessible from the web interface. Backups capture the full state of the system — database, configuration, and optionally audio archives — in a single timestamped directory.

---

## What Is Included in a Backup

| Component | File in backup | Notes |
|-----------|---------------|-------|
| PostgreSQL database | `alerts_database.sql` | Full pg_dump of all tables |
| Environment configuration | `.env` | All application settings |
| Backup metadata | `metadata.json` | Timestamp, version, summary |
| Audio archives | `media/` | Optional; may be large |

---

## Creating a Backup

### Via the Web Interface

1. Navigate to **Admin → Backups**.
2. Click **Create Backup**.
3. Enter an optional **label** to identify the backup (e.g., `pre-upgrade`, `weekly`).
4. Choose whether to include media files and volume data.
5. Click **Create**. A progress indicator appears while the backup runs.
6. The new backup appears in the backup list when complete, showing its size and timestamp.

### Via the Command Line

```bash
# Full backup (database + config + media)
python tools/create_backup.py --output-dir /var/backups/eas-station --label manual

# Database and config only (faster, no media)
python tools/create_backup.py --output-dir /var/backups/eas-station --label config-only --no-media
```

---

## Backup Storage Location

By default, backups are stored at `/var/backups/eas-station/`. Each backup is a directory named `backup-YYYY-MM-DDTHH-MM-SS/`.

Override the location via the `BACKUP_DIR` environment variable in `.env`:

```
BACKUP_DIR=/mnt/nas/eas-station-backups
```

---

## Scheduling Automatic Backups

EAS Station™ does not include a built-in scheduler for backups. Use a cron job or systemd timer to automate them.

**Daily backup via cron (runs as the `eas-station` user):**

```bash
sudo crontab -u eas-station -e
```

Add:

```cron
# Daily backup at 2:00 AM
0 2 * * * /opt/eas-station/venv/bin/python /opt/eas-station/tools/create_backup.py \
  --output-dir /var/backups/eas-station \
  --label cron-daily \
  --no-media \
  >> /var/log/eas-station/backup.log 2>&1
```

**Retention — delete backups older than 30 days:**

```cron
0 3 * * * find /var/backups/eas-station -maxdepth 1 -name "backup-*" -type d -mtime +30 -exec rm -rf {} +
```

---

## Validating a Backup

Before relying on a backup for restore, verify its integrity:

### Via the Web Interface

1. Go to **Admin → Backups**.
2. Click the **Validate** button next to a backup.
3. The system checks for required files (`metadata.json`, `.env`, `alerts_database.sql`) and reports the database dump size.

### Via the API

> **Note:** API-key authentication (`X-API-Key`) is **planned but not yet implemented** — see [API Key Management](API_KEY_MANAGEMENT.md). Until it ships, these endpoints require an authenticated browser session (log in first and reuse the session cookie).

```bash
curl -H "X-API-Key: <key>" \
     https://your-eas-station.example.com/api/backups/validate/backup-2025-02-20T02-00-00
```

Response:

```json
{
  "valid": true,
  "checks": {
    "metadata": true,
    "config": true,
    "database": true,
    "database_size_mb": 12.4
  }
}
```

---

## Restoring a Backup

!!! danger "Restore overwrites current data"
    Restoring a backup replaces the current database and configuration. This action cannot be undone. Create a fresh backup of the current state before restoring an older one.

### Via the Web Interface

1. Navigate to **Admin → Backups**.
2. Find the backup you want to restore and click **Restore**.
3. Choose restore options:
   - **Full restore** — database + config + media
   - **Database only** — restore only the PostgreSQL dump
   - **Skip database** — restore config and media without touching the database
   - **Skip media** — restore database and config but not audio archives
4. Confirm the dialog. The restore operation may take several minutes for large databases.
5. After the restore completes, click **Validate System** to run post-restore health checks.

### Via the Command Line

```bash
# Full restore
python tools/restore_backup.py \
  --backup-dir /var/backups/eas-station/backup-2025-02-20T02-00-00 \
  --force

# Database only
python tools/restore_backup.py \
  --backup-dir /var/backups/eas-station/backup-2025-02-20T02-00-00 \
  --database-only \
  --force

# Skip media (faster)
python tools/restore_backup.py \
  --backup-dir /var/backups/eas-station/backup-2025-02-20T02-00-00 \
  --skip-media \
  --force
```

After a command-line restore, run database migrations to ensure the schema is current:

```bash
cd /opt/eas-station
source venv/bin/activate
alembic upgrade head
```

Then restart all services:

```bash
sudo systemctl restart eas-station.target
```

---

## Post-Restore Validation

After any restore operation, verify the system is healthy:

```bash
# API-based validation
curl -X POST -H "X-API-Key: <key>" \
     https://your-eas-station.example.com/api/backups/validate-system
```

Or via the web UI: **Admin → Backups → Validate System**.

The validation checks:
- Web service availability
- Database connectivity and migration state
- External dependencies (Redis, Icecast)
- Configuration file integrity
- GPIO and audio device availability

---

## Downloading a Backup

To transfer a backup off-site:

1. Go to **Admin → Backups**.
2. Click **Download** next to a backup.
3. A `.tar.gz` archive of the backup directory is downloaded.

Via the API:

```bash
curl -H "X-API-Key: <key>" \
     -o backup-2025-02-20.tar.gz \
     https://your-eas-station.example.com/api/backups/download/backup-2025-02-20T02-00-00
```

---

## Deleting Old Backups

1. Go to **Admin → Backups**.
2. Click **Delete** next to the backup you want to remove.
3. Confirm the dialog.

Only **Admin** role users can delete backups. Deletion is permanent.

---

## Off-Site Backup Recommendations

For a production deployment, copy backups to a remote location:

```bash
# Sync to a remote server via rsync
rsync -avz --delete \
  /var/backups/eas-station/ \
  backup-user@remote-server:/backups/eas-station/

# Or upload to S3-compatible storage
aws s3 sync /var/backups/eas-station/ s3://your-bucket/eas-station-backups/
```

---

## Troubleshooting

### Backup fails immediately

- Check that the backup directory exists and is writable:
  ```bash
  ls -la /var/backups/eas-station
  sudo chown -R eas-station:eas-station /var/backups/eas-station
  ```
- Verify `pg_dump` is available:
  ```bash
  which pg_dump
  ```

### Backup is very slow

Large audio archives (`media/`) are the usual cause. Use `--no-media` for routine backups and include media only for full-system snapshots.

### Restore fails with migration error

Run `alembic upgrade head` manually after the restore. A version mismatch between the backup and the installed code is the most common cause.

### "Script not found" error

Ensure the backup scripts are present at `tools/create_backup.py` and `tools/restore_backup.py`. If not, pull the latest code:

```bash
git pull origin main
```
