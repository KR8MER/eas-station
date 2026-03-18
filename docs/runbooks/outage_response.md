# Outage Response Runbook

This runbook describes procedures for responding to EAS Station service outages. Follow these steps in order to diagnose and restore service quickly.

---

## Severity Levels

| Level | Description | Target Resolution |
|-------|-------------|-------------------|
| **P1** | Complete service outage — no alerts being processed | 30 minutes |
| **P2** | Partial outage — one or more components down | 2 hours |
| **P3** | Degraded performance — service running but impaired | 4 hours |

---

## Initial Triage

### 1. Check overall system health

```bash
# Web health endpoint (from the EAS Station host)
curl -s http://localhost/health/dependencies | python3 -m json.tool

# Check all systemd services
systemctl status eas-station-web eas-station-poller eas-station-sdr \
    eas-station-audio eas-station-hardware
```

### 2. Review recent logs

```bash
# Web application
journalctl -u eas-station-web -n 100 --no-pager

# Alert poller
journalctl -u eas-station-poller -n 100 --no-pager

# SDR hardware service
journalctl -u eas-station-sdr -n 100 --no-pager

# Combined log tail
journalctl -u eas-station-web -u eas-station-poller \
    -u eas-station-audio --since "1 hour ago" --no-pager
```

### 3. Check database connectivity

```bash
# Attempt a simple PostgreSQL connection
sudo -u eas-station psql -c "SELECT version();" 2>&1

# Check if PostgreSQL service is running
systemctl status postgresql
```

### 4. Check Redis connectivity

```bash
redis-cli ping
redis-cli info server | grep uptime_in_seconds
```

---

## Common Failure Scenarios

### Web Service Down

**Symptoms:** HTTP requests return connection refused or 502 from nginx.

```bash
# Restart the web service
sudo systemctl restart eas-station-web

# If it won't start, check for syntax errors or missing dependencies
sudo journalctl -u eas-station-web -n 50 --no-pager

# Verify nginx is running
sudo systemctl status nginx
sudo systemctl restart nginx
```

### Alert Poller Not Processing Feeds

**Symptoms:** No new alerts appearing; `eas-station-poller` not running.

```bash
# Restart the poller
sudo systemctl restart eas-station-poller

# Check for feed connectivity
curl -I https://alerts.weather.gov/cap/us.php

# Check database write permissions
sudo -u eas-station psql -c "SELECT COUNT(*) FROM cap_alerts;" 2>&1
```

### Database Connection Errors

**Symptoms:** 500 errors in web UI; `OperationalError` in logs.

```bash
# Restart PostgreSQL
sudo systemctl restart postgresql

# Verify database exists
sudo -u postgres psql -l | grep eas_station

# Check connection pool
sudo journalctl -u eas-station-web --since "10 minutes ago" | grep -i "pool\|connection"

# Restart web service after DB recovery
sudo systemctl restart eas-station-web
```

### Redis Unavailable

**Symptoms:** Rate limiting errors; session failures; cache misses in logs.

```bash
# Restart Redis
sudo systemctl restart redis-server

# Verify Redis is accepting connections
redis-cli ping   # Expected: PONG

# Restart web service after Redis recovery
sudo systemctl restart eas-station-web
```

### Disk Space Exhausted

**Symptoms:** Write errors in logs; backup failures; audio recording stops.

```bash
# Check disk usage
df -h
du -sh /var/backups/eas-station/* 2>/dev/null | sort -h | tail -20

# Remove old backups (keep last 10)
ls -t /var/backups/eas-station/backup-* | tail -n +11 | xargs rm -rf

# Remove old audio archives if present
find /opt/eas-station/media -name "*.mp3" -mtime +90 -delete 2>/dev/null

# See disk cleanup guide
# docs/maintenance/DISK_SPACE_CLEANUP.md
```

### SDR Hardware Not Detected

**Symptoms:** `eas-station-sdr` logs show no devices; SDR verification unavailable.

```bash
# Check USB device list
lsusb | grep -i "rtl\|realtek\|airspy"

# Restart SDR service
sudo systemctl restart eas-station-sdr

# Reload USB device rules if needed
sudo udevadm control --reload-rules
sudo udevadm trigger
```

---

## Service Restart Order

When performing a full service restart, follow this order to avoid dependency issues:

1. PostgreSQL
2. Redis
3. nginx
4. `eas-station-hardware`
5. `eas-station-audio`
6. `eas-station-poller`
7. `eas-station-sdr`
8. `eas-station-web` (last — depends on all others)

```bash
# Full restart script
for svc in postgresql redis-server nginx \
    eas-station-hardware eas-station-audio \
    eas-station-poller eas-station-sdr eas-station-web; do
    echo "Restarting $svc..."
    sudo systemctl restart "$svc"
    sleep 2
done

# Verify all services are active
systemctl is-active eas-station-web eas-station-poller \
    eas-station-sdr eas-station-audio eas-station-hardware
```

---

## Post-Recovery Verification

After restoring service, confirm the following:

1. **Web UI accessible**: Open `http://localhost` or the configured domain.
2. **Health endpoint green**: `curl -s http://localhost/health/dependencies`
3. **Alerts processing**: Check **Admin → Dashboard** for recent alert activity.
4. **Backups running**: Verify cron backup ran successfully.
5. **No error logs**: Review journalctl output for unresolved errors.

---

## Escalation

If the outage cannot be resolved within the target resolution time:

1. Create a backup of the current state before making further changes.
2. Review recent commits or updates that may have introduced the issue:
   ```bash
   cd /opt/eas-station && git log --oneline -10
   ```
3. Consider rolling back to the previous version:
   ```bash
   cd /opt/eas-station && git checkout <previous-commit>
   sudo systemctl restart eas-station-web
   ```
4. Consult [backup restore documentation](../guides/DATABASE_BACKUPS.md) for data recovery options.

---

## Related Runbooks

- [Backup Strategy](backup_strategy.md)
- [Disk Space Cleanup](../maintenance/DISK_SPACE_CLEANUP.md)
- [Standby Deployment](../../examples/STANDBY_DEPLOYMENT.md)
