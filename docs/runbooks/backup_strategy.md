# EAS Station Backup Strategy

## Overview

This document describes the backup and recovery strategy for EAS Station deployments. A comprehensive backup strategy protects against data loss, enables disaster recovery, and ensures compliance with audit trail requirements.

## What Gets Backed Up

The `tools/create_backup.py` utility creates snapshots containing:

1. **Configuration Files**
   - `.env` - Environment variables and secrets
   - `docker-compose.yml` - Container orchestration configuration
   - `docker-compose.embedded-db.yml` - Optional embedded database configuration

2. **Database Dump**
   - Complete PostgreSQL database export (`.sql` format)
   - Includes all tables: alerts, boundaries, users, audit logs, GPIO logs, etc.
   - Preserves PostGIS spatial data and indexes

3. **Metadata**
   - Timestamp of backup creation
   - Git commit hash and branch
   - Application version
   - Database connection details (sanitized)
   - Backup command used for restore reference

## Backup Frequency Recommendations

### Production Deployments

| Backup Type | Frequency | Retention | Purpose |
|-------------|-----------|-----------|---------|
| **Scheduled** | Daily at 2:00 AM | 7 daily, 4 weekly, 6 monthly | Regular protection |
| **Pre-Upgrade** | Before each upgrade | Keep all | Rollback capability |
| **Pre-Configuration** | Before major config changes | 30 days | Recovery from mistakes |

### Lab/Testing Environments

| Backup Type | Frequency | Retention | Purpose |
|-------------|-----------|-----------|---------|
| **Scheduled** | Weekly | 4 weekly | Basic protection |
| **Manual** | As needed | 30 days | Experimental snapshots |

## Automated Backup Setup

### Option 1: Systemd Timer (Recommended for Linux)

**1. Copy systemd unit files:**
```bash
sudo cp examples/systemd/eas-backup.service /etc/systemd/system/
sudo cp examples/systemd/eas-backup.timer /etc/systemd/system/
```

**2. Edit the service file if your installation path differs:**
```bash
sudo nano /etc/systemd/system/eas-backup.service
```

Update the `WorkingDirectory` and `ExecStart` paths to match your installation.

**3. Enable and start the timer:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable eas-backup.timer
sudo systemctl start eas-backup.timer
```

**4. Verify the timer is active:**
```bash
sudo systemctl status eas-backup.timer
sudo systemctl list-timers | grep eas-backup
```

**5. Test the backup manually:**
```bash
sudo systemctl start eas-backup.service
sudo journalctl -u eas-backup.service -f
```

### Option 2: Cron (Alternative)

**1. Copy the cron example:**
```bash
cp examples/cron/eas-backup.cron /tmp/eas-backup.cron
```

**2. Edit paths if needed:**
```bash
nano /tmp/eas-backup.cron
```

**3. Install to root crontab:**
```bash
sudo crontab -e
# Paste the contents of /tmp/eas-backup.cron
```

**4. Verify cron job:**
```bash
sudo crontab -l | grep eas-backup
```

## Manual Backup Creation

### Standard Backup
```bash
cd /opt/eas-station
python3 tools/create_backup.py
```

### Pre-Upgrade Backup
```bash
cd /opt/eas-station
python3 tools/create_backup.py --label pre-upgrade
```

### Custom Output Directory
```bash
cd /opt/eas-station
python3 tools/create_backup.py --output-dir /mnt/external/eas-backups
```

## Backup Retention and Rotation

The `tools/rotate_backups.py` utility implements a grandfather-father-son retention policy:

- **Daily backups**: Keep the 7 most recent
- **Weekly backups**: Keep 4 most recent Sunday backups
- **Monthly backups**: Keep 6 most recent backups from the 1st of the month

### Manual Rotation

**Dry run (preview what would be deleted):**
```bash
python3 tools/rotate_backups.py --dry-run
```

**Apply default retention policy:**
```bash
python3 tools/rotate_backups.py
```

**Custom retention policy:**
```bash
python3 tools/rotate_backups.py \
  --keep-daily 14 \
  --keep-weekly 8 \
  --keep-monthly 12
```

### Automated Rotation

Add rotation to the backup systemd service by editing `/etc/systemd/system/eas-backup.service`:

```ini
[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/eas-station
ExecStart=/usr/bin/python3 /opt/eas-station/tools/create_backup.py --output-dir /var/backups/eas-station --label scheduled
ExecStartPost=/usr/bin/python3 /opt/eas-station/tools/rotate_backups.py --backup-dir /var/backups/eas-station
```

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart eas-backup.service
```

For cron, add a second job:
```cron
# Rotate backups daily at 3:00 AM (after backup completes)
0 3 * * * cd /opt/eas-station && /usr/bin/python3 tools/rotate_backups.py --backup-dir /var/backups/eas-station >> /var/log/eas-backup.log 2>&1
```

## Restore Procedures

### Full System Restore

**1. Stop running services:**
```bash
cd /opt/eas-station
docker compose down
```

**2. Restore configuration files:**
```bash
BACKUP_DIR=/var/backups/eas-station/backup-20250305-143022
cp $BACKUP_DIR/.env .env
cp $BACKUP_DIR/docker-compose.yml docker-compose.yml
```

**3. Restore database:**
```bash
# Option A: Using docker compose (if alerts-db service exists)
docker compose up -d alerts-db
docker compose exec -T alerts-db psql -U postgres -d alerts < $BACKUP_DIR/alerts_database.sql

# Option B: Using psql directly
PGPASSWORD=$(grep POSTGRES_PASSWORD .env | cut -d= -f2 | tr -d '"') \
  psql -h localhost -U postgres -d alerts < $BACKUP_DIR/alerts_database.sql
```

**4. Restart services:**
```bash
docker compose up -d
```

**5. Verify restore:**
```bash
docker compose logs -f
curl http://localhost:8080/health
curl http://localhost:8080/api/release-manifest
```

### Partial Restore (Configuration Only)

If you only need to restore configuration:
```bash
BACKUP_DIR=/var/backups/eas-station/backup-20250305-143022
cp $BACKUP_DIR/.env .env
docker compose restart
```

### Database Only Restore

To restore only the database without touching configuration:
```bash
BACKUP_DIR=/var/backups/eas-station/backup-20250305-143022
docker compose exec -T alerts-db psql -U postgres -d alerts < $BACKUP_DIR/alerts_database.sql
docker compose restart app poller ipaws-poller
```

## Off-Site Backup Storage

For disaster recovery, store backups off-site:

### Option 1: rsync to Remote Server
```bash
#!/bin/bash
# /opt/eas-station/tools/sync_backups_offsite.sh
rsync -avz --delete \
  /var/backups/eas-station/ \
  backup-server:/backups/eas-station/ \
  --exclude='*.tmp'
```

Run after each backup via systemd `ExecStartPost` or as a separate cron job.

### Option 2: Cloud Storage (S3, Azure Blob, etc.)

Use AWS CLI, Azure CLI, or rclone:
```bash
# AWS S3 example
aws s3 sync /var/backups/eas-station/ s3://my-bucket/eas-station-backups/

# rclone example (works with many cloud providers)
rclone sync /var/backups/eas-station/ remote:eas-station-backups/
```

## Backup Verification

### Automatic Verification

The backup script stores metadata that can be used for verification:
```bash
cat /var/backups/eas-station/backup-20250305-143022/metadata.json
```

### Manual Verification

Test restore in a separate environment:
```bash
# 1. Spin up a test database
docker run -d --name test-postgres \
  -e POSTGRES_PASSWORD=testpass \
  -p 5433:5432 \
  postgis/postgis:15-3.3

# 2. Restore backup
docker exec -i test-postgres psql -U postgres -d postgres \
  < /var/backups/eas-station/backup-20250305-143022/alerts_database.sql

# 3. Verify data
docker exec test-postgres psql -U postgres -d alerts -c "SELECT COUNT(*) FROM cap_alerts;"

# 4. Clean up
docker stop test-postgres
docker rm test-postgres
```

## Monitoring Backup Status

### Check Backup Logs (systemd)
```bash
sudo journalctl -u eas-backup.service -n 50
sudo journalctl -u eas-backup.service --since today
```

### Check Backup Logs (cron)
```bash
tail -f /var/log/eas-backup.log
```

### Alert on Backup Failures

Add to systemd service:
```ini
[Service]
OnFailure=backup-failure-notification@%n.service
```

Or monitor cron via email:
```cron
MAILTO=admin@example.com
0 2 * * * cd /opt/eas-station && python3 tools/create_backup.py --output-dir /var/backups/eas-station 2>&1
```

## Storage Requirements

### Estimate Backup Size

Database size varies based on:
- Number of received alerts (typically 100-500 per day)
- Number of boundary polygons (1,000-10,000 depending on configuration)
- Audit log retention (grows over time)

**Typical sizes:**
- Fresh install: ~50 MB
- 1 month operation: ~200-500 MB
- 1 year operation: ~2-5 GB

**Configuration files:** ~1 MB total

### Storage Recommendations

| Deployment | Daily Backups | Weekly/Monthly | Total Storage |
|------------|---------------|----------------|---------------|
| **Lab** | 50 MB × 7 = 350 MB | 50 MB × 4 = 200 MB | ~600 MB |
| **Production** | 500 MB × 7 = 3.5 GB | 500 MB × 10 = 5 GB | ~10 GB |

Add 50% margin for growth: **15-20 GB recommended for production**

## Security Considerations

### Backup Encryption

For sensitive deployments, encrypt backups at rest:

```bash
#!/bin/bash
# Encrypt backup after creation
BACKUP_DIR=$(ls -td /var/backups/eas-station/backup-* | head -1)
tar czf - "$BACKUP_DIR" | \
  openssl enc -aes-256-cbc -salt -pbkdf2 -out "${BACKUP_DIR}.tar.gz.enc"
rm -rf "$BACKUP_DIR"
```

### Access Control

Restrict backup directory permissions:
```bash
sudo chown -R root:root /var/backups/eas-station
sudo chmod 700 /var/backups/eas-station
```

### Credential Protection

The `.env` file contains sensitive credentials. Consider:
1. Encrypting backups (see above)
2. Using separate secret management (e.g., HashiCorp Vault)
3. Restricting access to backup storage

## Troubleshooting

### Backup Script Fails

**Check logs:**
```bash
sudo journalctl -u eas-backup.service -n 100
```

**Common issues:**
1. **PostgreSQL not accessible**: Verify `POSTGRES_*` variables in `.env`
2. **Disk full**: Check storage with `df -h`
3. **Permissions**: Ensure script runs as root or user with database access

### Restore Fails

**Database restore errors:**
```bash
# Check PostgreSQL version compatibility
docker compose exec alerts-db psql --version

# Check for conflicting data
docker compose exec alerts-db psql -U postgres -d alerts -c "\dt"
```

**Configuration issues:**
```bash
# Validate .env syntax
grep -v '^#' .env | grep -v '^$' | grep '='

# Check Docker Compose syntax
docker compose config
```

## Related Documentation

- [Upgrade Procedures](upgrade_checklist.md) - Pre-upgrade backup workflow
- [Disaster Recovery](outage_response.md) - Emergency restore procedures
- [Security Hardening](../MIGRATION_SECURITY.md) - Backup encryption and access control

## Audit Trail

All backups include metadata for audit purposes:
- Timestamp (UTC)
- Git commit hash and branch
- Application version
- Database connection details

Access metadata:
```bash
cat /var/backups/eas-station/backup-20250305-143022/metadata.json | jq
```

Query backup history:
```bash
ls -lth /var/backups/eas-station/
```
