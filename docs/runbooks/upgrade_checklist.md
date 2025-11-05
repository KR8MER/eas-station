# EAS Station Upgrade Checklist

## Overview

This checklist ensures safe, auditable upgrades of EAS Station deployments. The `tools/inplace_upgrade.py` utility automates the upgrade process while preserving data and configuration.

## Pre-Upgrade Checklist

### 1. Review Release Notes

**Check CHANGELOG and GitHub releases:**
```bash
# View unreleased changes
cat docs/reference/CHANGELOG.md | less

# Check specific version
cat docs/reference/CHANGELOG.md | grep -A 20 "\[2.3.14\]"
```

**Review breaking changes, new dependencies, and migration notes.**

### 2. Verify Current System State

**Check running version:**
```bash
curl http://localhost:8080/api/release-manifest | jq
```

Expected output:
```json
{
  "version": "2.3.13",
  "git": {
    "commit": "abc123...",
    "branch": "main",
    "clean": true
  },
  "database": {
    "current_revision": "20251105_add_rbac_and_mfa",
    "revision_description": "Add RBAC and MFA support",
    "pending_migrations": [],
    "pending_count": 0
  }
}
```

**Verify system health:**
```bash
curl http://localhost:8080/health | jq
docker compose ps
docker compose logs --tail=50
```

### 3. Create Pre-Upgrade Backup

**CRITICAL: Always create a labeled backup before upgrading**

```bash
cd /opt/eas-station
python3 tools/create_backup.py --label pre-upgrade-$(date +%Y%m%d)
```

**Verify backup succeeded:**
```bash
ls -lh backups/ | tail -1
cat backups/backup-*/metadata.json | jq
```

**Expected metadata:**
- Timestamp: Recent
- Git commit: Matches current deployment
- App version: Matches VERSION file
- Database dump: Non-empty `.sql` file

### 4. Review Disk Space

**Check available storage:**
```bash
df -h /
df -h /var/lib/docker
```

**Requirements:**
- Application: 2 GB free for image build
- Database: 500 MB free for migration operations
- Backups: Sufficient space for backup retention policy

### 5. Notify Operators

**For production systems:**
1. Schedule maintenance window
2. Notify users of planned downtime
3. Document expected upgrade duration (typically 5-15 minutes)

## Automated Upgrade Procedure

### Option 1: Standard Upgrade (Recommended)

**Run the automated upgrade script:**
```bash
cd /opt/eas-station
python3 tools/inplace_upgrade.py
```

**What this does:**
1. Fetches latest git tags and refs
2. Fast-forwards current branch
3. Pulls updated Docker images
4. Rebuilds application container
5. Runs database migrations (`alembic upgrade head`)
6. Restarts poller services

**Monitor progress:**
```bash
# In a separate terminal
docker compose logs -f
```

### Option 2: Upgrade to Specific Version

**Checkout a specific release tag:**
```bash
cd /opt/eas-station
python3 tools/inplace_upgrade.py --checkout v2.3.14
```

**Or upgrade to a specific branch:**
```bash
cd /opt/eas-station
python3 tools/inplace_upgrade.py --checkout experimental
```

### Option 3: Manual Upgrade (Advanced)

**If you need more control:**
```bash
cd /opt/eas-station

# 1. Create backup
python3 tools/create_backup.py --label pre-upgrade-manual

# 2. Pull latest code
git fetch --tags --prune
git pull --ff-only

# 3. Rebuild and restart services
docker compose up -d --build

# 4. Run migrations
docker compose exec app python -m alembic upgrade head

# 5. Restart pollers
docker compose restart poller ipaws-poller
```

## Post-Upgrade Verification

### 1. Verify Version Update

**Check new version:**
```bash
curl http://localhost:8080/api/release-manifest | jq .version
```

**Should show the new version number.**

### 2. Verify Database Migrations

**Check migration status:**
```bash
curl http://localhost:8080/api/release-manifest | jq .database
```

**Expected:**
- `pending_migrations`: Empty array `[]`
- `pending_count`: `0`

**Manual check:**
```bash
docker compose exec app python -m alembic current
docker compose exec app python -m alembic history | head -20
```

### 3. Verify Service Health

**Check health endpoint:**
```bash
curl http://localhost:8080/health | jq
```

**All services should report as healthy:**
```json
{
  "status": "healthy",
  "database": "connected",
  "led_available": true,
  "radio_receivers": 2
}
```

### 4. Verify Container Status

**Check all containers are running:**
```bash
docker compose ps
```

**Expected: All services in "Up" state**

### 5. Spot-Check Functionality

**Test key features:**
```bash
# Check recent alerts
curl http://localhost:8080/api/recent_alerts | jq '.[] | .identifier'

# Check radio receivers (if configured)
curl http://localhost:8080/api/monitoring/radio | jq '.receivers | length'

# Access web UI
curl -I http://localhost:8080/
```

**Manual UI checks:**
1. Login to web interface
2. View Dashboard
3. Check System Health tab
4. Verify Settings pages load

### 6. Review Logs

**Check for errors:**
```bash
docker compose logs --since 10m | grep -i error
docker compose logs --since 10m | grep -i exception
```

**No critical errors should be present.**

### 7. Verify Scheduled Tasks

**For systemd deployments:**
```bash
sudo systemctl status eas-backup.timer
sudo systemctl list-timers | grep eas
```

**For cron deployments:**
```bash
sudo crontab -l | grep eas
```

## Rollback Procedures

### When to Rollback

Roll back if you encounter:
- Critical functionality broken
- Database migration failures
- Service stability issues
- Data integrity problems

### Rollback Steps

**1. Stop services:**
```bash
cd /opt/eas-station
docker compose down
```

**2. Restore from pre-upgrade backup:**
```bash
# Identify backup
BACKUP_DIR=$(ls -td backups/backup-*-pre-upgrade* | head -1)
echo "Restoring from: $BACKUP_DIR"

# Restore configuration
cp $BACKUP_DIR/.env .env
cp $BACKUP_DIR/docker-compose.yml docker-compose.yml 2>/dev/null || true

# Restore database
docker compose up -d alerts-db
sleep 5
docker compose exec -T alerts-db psql -U postgres -d alerts < $BACKUP_DIR/alerts_database.sql
```

**3. Restore previous git version:**
```bash
# Find commit from backup metadata
PREV_COMMIT=$(cat $BACKUP_DIR/metadata.json | jq -r .git_commit)
echo "Rolling back to commit: $PREV_COMMIT"

git checkout $PREV_COMMIT
```

**4. Rebuild and restart:**
```bash
docker compose up -d --build
```

**5. Verify rollback:**
```bash
curl http://localhost:8080/api/release-manifest | jq
curl http://localhost:8080/health | jq
docker compose logs --tail=100
```

### Rollback Verification

After rollback, verify:
- Version matches pre-upgrade state
- Database query succeeds
- Web UI accessible
- No error logs

## Common Upgrade Issues

### Issue: Migration Fails

**Symptom:**
```
alembic.util.exc.CommandError: Can't locate revision identified by 'abc123'
```

**Solution:**
```bash
# Check migration history
docker compose exec app python -m alembic history

# Stamp database to known good state
docker compose exec app python -m alembic stamp head

# Retry upgrade
docker compose exec app python -m alembic upgrade head
```

### Issue: Container Won't Start

**Symptom:**
```
Error: Container exits immediately after start
```

**Solution:**
```bash
# Check logs for errors
docker compose logs app

# Common fixes:
# 1. Invalid .env syntax
grep -v '^#' .env | grep -v '^$' | grep '='

# 2. Database not accessible
docker compose exec app ping alerts-db

# 3. Port conflict
sudo netstat -tlnp | grep 8080
```

### Issue: Database Connection Errors

**Symptom:**
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**Solution:**
```bash
# Verify database is running
docker compose ps alerts-db

# Check database logs
docker compose logs alerts-db

# Restart database
docker compose restart alerts-db

# Wait for database to be ready
docker compose exec alerts-db pg_isready -U postgres
```

### Issue: Disk Space Full

**Symptom:**
```
no space left on device
```

**Solution:**
```bash
# Check disk usage
df -h

# Clean up Docker images
docker image prune -a

# Clean up old backups
python3 tools/rotate_backups.py

# Remove old containers
docker container prune
```

## Upgrade Frequency

### Recommended Schedule

| Environment | Upgrade Frequency | Notes |
|-------------|------------------|-------|
| **Production** | Every 2-4 weeks | Test in lab first |
| **Lab/Testing** | Weekly | Track experimental branch |
| **Development** | Daily | Bleeding edge |

### Security Updates

Apply security patches immediately:
```bash
# Check for security advisories
cat docs/reference/CHANGELOG.md | grep -i security

# Apply critical updates within 24-48 hours
python3 tools/inplace_upgrade.py --checkout v2.3.14
```

## Upgrade Windows

### Production Systems

**Best practices:**
1. **Timing**: Schedule during low-traffic periods (2-4 AM local time)
2. **Duration**: Allocate 30-minute window for upgrades
3. **Backup**: Always create pre-upgrade backup
4. **Testing**: Verify upgrade in lab environment first
5. **Communication**: Notify operators 24-48 hours in advance

### Lab Systems

Less stringent requirements:
- Can upgrade during business hours
- Shorter notification period
- Can experiment with experimental branches

## Testing Upgrades

### Lab Environment Setup

**Create isolated test environment:**
```bash
# Clone to separate directory
git clone https://github.com/KR8MER/eas-station.git /opt/eas-station-test
cd /opt/eas-station-test

# Copy .env with modified ports
cp /opt/eas-station/.env .env
sed -i 's/8080/8081/g' .env
sed -i 's/5432/5433/g' docker-compose.yml

# Start test environment
docker compose up -d
```

**Test upgrade in lab:**
```bash
cd /opt/eas-station-test
python3 tools/inplace_upgrade.py --checkout v2.3.14
```

**If successful, apply to production:**
```bash
cd /opt/eas-station
python3 tools/inplace_upgrade.py --checkout v2.3.14
```

## Maintenance Mode

### Enable Maintenance Mode

**Before upgrading, optionally enable maintenance mode:**
```bash
# Add to .env
echo "MAINTENANCE_MODE=true" >> .env
docker compose restart app
```

**Users will see:** "System under maintenance - please check back shortly"

### Disable Maintenance Mode

**After upgrade completes:**
```bash
# Remove from .env
sed -i '/MAINTENANCE_MODE/d' .env
docker compose restart app
```

## Audit Trail

### Document Upgrades

**Record upgrade details:**
```bash
# After successful upgrade
cat > upgrade_log_$(date +%Y%m%d).txt <<EOF
Date: $(date -I)
Operator: $(whoami)
Previous Version: $(curl -s http://localhost:8080/api/release-manifest | jq -r .version)
New Version: $(cat VERSION)
Backup: $(ls -td backups/backup-*-pre-upgrade* | head -1)
Duration: 8 minutes
Issues: None
Notes: Routine upgrade per monthly schedule
EOF
```

**Store in `docs/upgrades/` for compliance audits.**

## Related Documentation

- [Backup Strategy](backup_strategy.md) - Pre-upgrade backup procedures
- [Disaster Recovery](outage_response.md) - Emergency rollback procedures
- [Release Governance](../../roadmap/master_todo.md) - Version policy and testing requirements
- [CHANGELOG](../reference/CHANGELOG.md) - Detailed release notes

## Emergency Contacts

**Maintain contacts for upgrade issues:**
- **System Administrator**: [Contact info]
- **Database Administrator**: [Contact info]
- **On-Call Engineer**: [Contact info]
- **GitHub Issues**: https://github.com/KR8MER/eas-station/issues
