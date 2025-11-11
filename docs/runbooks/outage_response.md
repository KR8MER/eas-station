# EAS Station Outage Response Runbook

**Purpose:** This runbook provides step-by-step procedures for responding to EAS Station outages and service degradation.

**Audience:** System administrators, on-call engineers, emergency management coordinators

**Last Updated:** 2025-01-11

---

## Quick Reference

### Emergency Contacts

- **Primary On-Call:** [Your contact info]
- **Secondary On-Call:** [Backup contact]
- **Emergency Management:** [EM contact]
- **Vendor Support:** [If applicable]

### Critical URLs

- **Primary Instance:** `https://eas.example.com`
- **Standby Instance:** `https://eas-standby.example.com`
- **Health Check:** `https://eas.example.com/health/dependencies`
- **Monitoring Dashboard:** [URL]

### Critical Commands

```bash
# Quick health check
curl https://eas.example.com/health/dependencies | jq

# Service status
docker compose ps

# Recent logs
docker compose logs --tail=100 --follow

# Restart services
docker compose restart

# Full restore from backup
python3 tools/restore_backup.py --backup-dir /var/backups/eas-station/latest
```

---

## Incident Response Process

### Phase 1: Detection and Assessment (0-5 minutes)

#### 1.1 Confirm the Outage

Check multiple indicators:

```bash
# Test health endpoint
curl -v https://eas.example.com/health
curl -v https://eas.example.com/health/dependencies

# Check from external network
curl -v https://eas.example.com/ping

# Review monitoring alerts
# Check your monitoring system (Nagios, Prometheus, etc.)
```

**Decision Point:** Is the service actually down?
- **YES** → Continue to 1.2
- **NO** → Document false alarm, improve monitoring

#### 1.2 Assess Severity

Determine impact level:

| Severity | Criteria | Response Time | Escalation |
|----------|----------|---------------|------------|
| **P1 - Critical** | Complete outage, no alerts being processed | Immediate | Emergency Management + On-call |
| **P2 - Major** | Degraded service, some alerts delayed | 15 minutes | On-call only |
| **P3 - Minor** | Non-critical features affected | 1 hour | Regular business hours |

**Decision Point:** What is the severity?
- **P1** → Follow Critical Outage procedure (Section 2)
- **P2** → Follow Degraded Service procedure (Section 3)
- **P3** → Follow Minor Issues procedure (Section 4)

#### 1.3 Initial Communication

For P1/P2 incidents:

```bash
# Send initial notification
# Subject: [P1/P2] EAS Station Outage - Investigating

Initial Alert - EAS Station Outage

Status: INVESTIGATING
Severity: [P1/P2]
Impact: [Brief description]
Started: [Timestamp]

We are investigating the issue. Updates every 15 minutes.

Next Update: [Time]
```

### Phase 2: Diagnosis (5-15 minutes)

#### 2.1 Check Infrastructure

**Container Status:**
```bash
cd /opt/eas-station
docker compose ps

# Expected output: All services "Up" and healthy
# If any service is down, note which ones
```

**System Resources:**
```bash
# Check disk space
df -h

# Check memory
free -h

# Check CPU
top -bn1 | head -20

# Check network
ping -c 3 google.com
ping -c 3 [primary database host]
```

**Application Logs:**
```bash
# Check application logs for errors
docker compose logs app --tail=200 | grep -i error

# Check database connectivity
docker compose logs app | grep -i "database\|postgres"

# Check recent activity
docker compose logs --tail=50 --timestamps
```

#### 2.2 Check Dependencies

**Database:**
```bash
# Check database connectivity
docker compose exec app python << 'PYTHON'
from app_core.extensions import db
from sqlalchemy import text
try:
    result = db.session.execute(text("SELECT version()")).fetchone()
    print(f"Database OK: {result[0]}")
except Exception as e:
    print(f"Database FAILED: {e}")
PYTHON
```

**Icecast:**
```bash
# Check Icecast status
docker compose ps icecast
curl http://localhost:8001/status.xsl
```

**Docker Daemon:**
```bash
# Check Docker status
systemctl status docker
docker info
```

**Network Connectivity:**
```bash
# Check external API access
curl -v https://api.weather.gov
curl -v https://alerts.weather.gov/cap/us.php?x=1
```

#### 2.3 Review Recent Changes

Check for recent changes that might have caused the outage:

```bash
# Check recent git commits
git log --oneline -10

# Check recent deployments
docker compose images

# Check configuration changes
ls -lt .env docker-compose.yml

# Check system updates
grep "upgraded" /var/log/dpkg.log | tail -20  # Debian/Ubuntu
grep "Updated" /var/log/yum.log | tail -20     # RHEL/CentOS
```

### Phase 3: Resolution

## Section 2: Critical Outage Response (P1)

### Immediate Actions

**Time: 0-5 minutes**

1. **Activate Standby Node** (if available):
   ```bash
   # If you have a standby node, activate it immediately
   ssh standby-node
   cd /opt/eas-station
   ./activate-primary.sh
   
   # Update DNS or load balancer to point to standby
   # [Your specific procedure here]
   ```

2. **Attempt Service Restart**:
   ```bash
   # On primary node
   cd /opt/eas-station
   docker compose restart
   
   # Wait 30 seconds for startup
   sleep 30
   
   # Check health
   curl http://localhost/health/dependencies
   ```

**Decision Point:** Did restart fix the issue?
- **YES** → Continue monitoring, proceed to Post-Incident Review (Section 5)
- **NO** → Continue with detailed troubleshooting

### Detailed Troubleshooting

**Time: 5-20 minutes**

#### Database Issues

If database is unreachable:

```bash
# Check database container
docker compose ps alerts-db

# If container is down, try restart
docker compose restart alerts-db

# Check database logs
docker compose logs alerts-db --tail=100

# If external database, check connectivity
telnet [database-host] 5432
```

If database is corrupted:

```bash
# Stop application
docker compose stop app

# Restore database from latest backup
cd /opt/eas-station
python3 tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/latest \
    --database-only \
    --force

# Restart application
docker compose start app
```

#### Application Crashes

If application container keeps restarting:

```bash
# Check crash logs
docker compose logs app --tail=500

# Check for out-of-memory
dmesg | grep -i oom

# Check disk space
df -h

# Try increasing memory limits in docker-compose.yml
# Edit deploy.resources.limits.memory

# Restart with clean state
docker compose down
docker compose up -d
```

#### Network Issues

If external connectivity is lost:

```bash
# Check network interfaces
ip addr show
ip route show

# Check DNS resolution
nslookup alerts.weather.gov
nslookup [your-database-host]

# Check firewall
sudo iptables -L -n
sudo ufw status

# Test specific connections
telnet alerts.weather.gov 443
telnet [database-host] 5432
```

#### Full System Restore

As last resort:

```bash
# 1. Stop all services
docker compose down

# 2. Restore from latest backup
python3 tools/restore_backup.py \
    --backup-dir /var/backups/eas-station/latest \
    --force

# 3. Start services
docker compose up -d

# 4. Verify health
sleep 30
curl http://localhost/health/dependencies

# 5. Monitor logs
docker compose logs --follow
```

## Section 3: Degraded Service Response (P2)

### Common Scenarios

#### Slow Performance

```bash
# Check resource usage
docker stats --no-stream

# Check database connections
docker compose exec alerts-db psql -U postgres -d alerts \
    -c "SELECT count(*) FROM pg_stat_activity;"

# Check for stuck processes
docker compose exec app ps aux

# Review slow queries
docker compose exec alerts-db psql -U postgres -d alerts \
    -c "SELECT query, state, wait_event FROM pg_stat_activity WHERE state != 'idle';"

# Restart if needed
docker compose restart app
```

#### Alert Delays

```bash
# Check poller status
docker compose ps noaa-poller ipaws-poller

# Check poller logs
docker compose logs noaa-poller --tail=100
docker compose logs ipaws-poller --tail=100

# Check database for pending alerts
docker compose exec app python << 'PYTHON'
from app_core.models import EASMessage
from app_core.extensions import db
from datetime import datetime, timedelta

recent = datetime.utcnow() - timedelta(hours=1)
count = EASMessage.query.filter(EASMessage.created_at >= recent).count()
print(f"Alerts in last hour: {count}")
PYTHON

# Restart pollers if needed
docker compose restart noaa-poller ipaws-poller
```

#### Icecast Streaming Issues

```bash
# Check Icecast status
docker compose ps icecast
docker compose logs icecast --tail=100

# Try accessing Icecast web interface
curl http://localhost:8001/status.xsl

# Restart Icecast
docker compose restart icecast

# Verify streams are reconnecting
docker compose logs app | grep -i icecast
```

## Section 4: Minor Issues (P3)

### Non-Critical Feature Failures

- Document the issue
- Schedule fix during maintenance window
- Monitor for escalation to P2
- Create ticket/issue in tracking system

## Section 5: Post-Incident Review

### Required Actions

1. **Update Communication**:
   ```
   Incident Resolved - EAS Station

   Status: RESOLVED
   Duration: [X hours Y minutes]
   Root Cause: [Brief description]
   Resolution: [What was done]
   
   Detailed post-mortem will be shared within 48 hours.
   ```

2. **Create Backup**:
   ```bash
   # Create post-incident backup
   python3 tools/create_backup.py --label post-incident
   ```

3. **Document Timeline**:
   - Detection time
   - Response time
   - Resolution time
   - Total downtime
   - Alerts missed (if any)

4. **Schedule Post-Mortem** (within 48 hours):
   - What happened?
   - Why did it happen?
   - How was it detected?
   - How was it resolved?
   - How can we prevent it?
   - Action items

### Post-Mortem Template

```markdown
# EAS Station Incident Post-Mortem

**Incident ID:** [ID]
**Date:** [Date]
**Severity:** [P1/P2/P3]
**Duration:** [Duration]
**Lead:** [Name]

## Summary
[One paragraph summary of the incident]

## Timeline
- [Time]: [Event]
- [Time]: [Event]

## Root Cause
[Detailed explanation of root cause]

## Resolution
[How the incident was resolved]

## Impact
- Downtime: [Duration]
- Alerts affected: [Number/None]
- Users affected: [Number/All/None]

## Lessons Learned

### What Went Well
- [Item]

### What Went Wrong
- [Item]

### What We Got Lucky With
- [Item]

## Action Items
- [ ] [Action item] - [Owner] - [Due date]
- [ ] [Action item] - [Owner] - [Due date]

## Appendix
[Logs, screenshots, additional data]
```

## Section 6: Preventive Measures

### Regular Maintenance Tasks

**Daily:**
- Review monitoring alerts
- Check disk space: `df -h`
- Verify backups ran: `ls -lh /var/backups/eas-station`

**Weekly:**
- Review logs for warnings: `docker compose logs | grep -i warn`
- Test health endpoints: `curl /health/dependencies`
- Verify backup rotation: `ls -lh /var/backups/eas-station | wc -l`

**Monthly:**
- Test backup restoration
- Review and update runbooks
- Security updates: `apt update && apt upgrade`
- Certificate renewal check: `openssl x509 -in /etc/letsencrypt/live/*/cert.pem -noout -dates`

**Quarterly:**
- Disaster recovery drill
- Review monitoring thresholds
- Capacity planning review
- Update emergency contacts

### Monitoring Recommendations

Set up alerts for:
- Service health check failures (2 consecutive failures)
- High disk usage (>80%)
- High memory usage (>85%)
- Database connection failures
- Backup failures
- Certificate expiration (<30 days)
- API timeout increases

---

## Appendix A: Quick Diagnostic Commands

```bash
# Complete health snapshot
{
    echo "=== System Info ==="
    uname -a
    uptime
    
    echo -e "\n=== Disk Space ==="
    df -h
    
    echo -e "\n=== Memory ==="
    free -h
    
    echo -e "\n=== Docker Status ==="
    docker compose ps
    
    echo -e "\n=== Health Check ==="
    curl -s http://localhost/health/dependencies | jq
    
    echo -e "\n=== Recent Logs ==="
    docker compose logs --tail=20 app
    
} > /tmp/eas-diagnostics.txt

cat /tmp/eas-diagnostics.txt
```

## Appendix B: Recovery Time Objectives

| Scenario | RTO Target | RPO Target | Procedure |
|----------|------------|------------|-----------|
| Application crash | 5 minutes | 0 minutes | Container restart |
| Database corruption | 15 minutes | 15 minutes | Restore from backup |
| Complete system failure | 30 minutes | 15 minutes | Restore on new hardware |
| Data center outage | 60 minutes | 15 minutes | Failover to standby site |

---

**Document Version:** 1.0  
**Next Review Date:** [3 months from today]  
**Owner:** [Your team name]
