# Warm-Standby Deployment Guide

This guide explains how to configure and deploy a warm-standby EAS Station instance for high availability and disaster recovery.

## Overview

A warm-standby deployment consists of:

1. **Primary Node**: Active instance handling all EAS operations
2. **Standby Node**: Secondary instance that syncs data and can take over if primary fails
3. **Shared Storage or Sync**: Mechanism to keep standby synchronized with primary

## Architecture Options

### Option 1: Shared Database (Recommended)

```
┌─────────────────┐         ┌─────────────────┐
│  Primary Node   │         │  Standby Node   │
│  (Active)       │         │  (Passive)      │
├─────────────────┤         ├─────────────────┤
│  App Services   │         │  App Services   │
│  Pollers       │         │  (Monitoring)   │
│  Broadcasting   │         │                 │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │                           │
         └───────────┬───────────────┘
                     │
            ┌────────▼────────┐
            │   PostgreSQL    │
            │   (Primary)     │
            │   with Replica  │
            └─────────────────┘
```

**Advantages:**
- Real-time data synchronization
- Fastest failover time
- Consistent state

**Disadvantages:**
- Requires PostgreSQL replication setup
- More complex configuration
- Network dependency

### Option 2: Backup Synchronization (Simpler)

```
┌─────────────────┐
│  Primary Node   │
│  (Active)       │
├─────────────────┤
│  App + DB       │
│  Auto Backup    │
└────────┬────────┘
         │
         │ rsync/NFS
         │
┌────────▼────────┐
│  Standby Node   │
│  (Monitoring)   │
├─────────────────┤
│  Synced Backups │
│  Ready to       │
│  Restore        │
└─────────────────┘
```

**Advantages:**
- Simple to set up
- No database replication needed
- Works with existing backups

**Disadvantages:**
- Longer failover time (requires restore)
- Potential data loss (time since last backup)
- Recovery Point Objective (RPO): 5-15 minutes

## Setup Instructions

### Prerequisites

- Two physical/virtual machines (primary and standby)
- Network connectivity between nodes
- Shared storage (NFS) or rsync access
- SSH key-based authentication

### Step 1: Deploy Primary Node

Set up the primary node normally:

```bash
# On primary node
cd /opt/eas-station
docker compose up -d

# Enable automated backups
sudo cp examples/systemd/eas-backup.service /etc/systemd/system/
sudo cp examples/systemd/eas-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable eas-backup.timer
sudo systemctl start eas-backup.timer
```

### Step 2: Configure Backup Synchronization

#### Option A: Using NFS Shared Storage

On primary node:
```bash
# Install NFS server
sudo apt-get install nfs-kernel-server

# Create NFS export
sudo mkdir -p /var/backups/eas-station
echo "/var/backups/eas-station standby-ip(ro,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -a
sudo systemctl restart nfs-kernel-server
```

On standby node:
```bash
# Install NFS client
sudo apt-get install nfs-common

# Mount NFS share
sudo mkdir -p /mnt/primary-backups
sudo mount primary-ip:/var/backups/eas-station /mnt/primary-backups

# Add to /etc/fstab for persistent mount
echo "primary-ip:/var/backups/eas-station /mnt/primary-backups nfs ro,auto 0 0" | sudo tee -a /etc/fstab
```

#### Option B: Using rsync over SSH

Create sync script on standby node:

```bash
#!/bin/bash
# /opt/eas-station/sync-from-primary.sh

PRIMARY_HOST="primary.example.com"
PRIMARY_PATH="/var/backups/eas-station"
LOCAL_PATH="/var/backups/eas-station-primary"

mkdir -p "$LOCAL_PATH"

# Sync backups from primary
rsync -avz --delete \
    "${PRIMARY_HOST}:${PRIMARY_PATH}/" \
    "${LOCAL_PATH}/" \
    2>&1 | logger -t eas-sync

# Keep latest backup easily accessible
LATEST=$(ls -td ${LOCAL_PATH}/backup-* 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    ln -snf "$LATEST" "${LOCAL_PATH}/latest"
fi
```

Set up cron job:
```bash
# Run every 5 minutes
echo "*/5 * * * * /opt/eas-station/sync-from-primary.sh" | sudo crontab -
```

### Step 3: Deploy Standby Node

On standby node:

```bash
# Clone repository
cd /opt
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# Copy configuration from primary or latest backup
cp /mnt/primary-backups/latest/.env .env

# Edit .env to mark as standby
echo "DEPLOYMENT_MODE=standby" >> .env
echo "EAS_BROADCAST_ENABLED=false" >> .env

# Deploy with standby configuration
docker compose -f docker-compose.yml -f examples/docker-compose.standby.yml up -d
```

### Step 4: Configure Health Monitoring

Set up monitoring to check primary health:

```bash
#!/bin/bash
# /opt/eas-station/check-primary-health.sh

PRIMARY_URL="https://primary.example.com"
ALERT_EMAIL="admin@example.com"

# Check primary health
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${PRIMARY_URL}/health" --max-time 10)

if [ "$HTTP_CODE" != "200" ]; then
    echo "PRIMARY ALERT: Health check failed (HTTP $HTTP_CODE)" | \
        mail -s "EAS Station Primary Down!" "$ALERT_EMAIL"
    logger -t eas-failover "Primary health check failed: HTTP $HTTP_CODE"
else
    logger -t eas-failover "Primary health check OK"
fi
```

Add to cron:
```bash
# Check every minute
echo "* * * * * /opt/eas-station/check-primary-health.sh" | sudo crontab -
```

## Failover Procedures

### Manual Failover

When primary node fails, activate standby:

```bash
# On standby node

# 1. Stop standby mode services
docker compose down

# 2. Restore latest backup
cd /opt/eas-station
python3 tools/restore_backup.py \
    --backup-dir /mnt/primary-backups/latest \
    --force

# 3. Update configuration for active mode
sed -i 's/DEPLOYMENT_MODE=standby/DEPLOYMENT_MODE=primary/' .env
sed -i 's/EAS_BROADCAST_ENABLED=false/EAS_BROADCAST_ENABLED=true/' .env
sed -i 's/STANDBY_MODE=true/STANDBY_MODE=false/' .env

# 4. Start in active mode
docker compose up -d

# 5. Verify services
docker compose ps
curl http://localhost/health/dependencies

# 6. Update DNS/load balancer to point to standby
```

### Automated Failover

For automatic failover, consider using:

- **Keepalived**: Virtual IP failover
- **Pacemaker/Corosync**: Cluster management
- **Consul**: Service discovery and health checking
- **External Load Balancer**: AWS ELB, HAProxy, etc.

Example keepalived configuration:
```bash
# Install keepalived
sudo apt-get install keepalived

# Configure on both nodes
# /etc/keepalived/keepalived.conf
vrrp_script check_eas {
    script "/opt/eas-station/check-local-health.sh"
    interval 5
    weight -20
}

vrrp_instance EAS_STATION {
    state MASTER        # BACKUP on standby node
    interface eth0
    virtual_router_id 51
    priority 100        # 90 on standby node
    advert_int 1

    virtual_ipaddress {
        192.168.1.100/24
    }

    track_script {
        check_eas
    }

    notify_master "/opt/eas-station/activate-primary.sh"
    notify_backup "/opt/eas-station/activate-standby.sh"
}
```

## Failback to Primary

After primary node is restored:

```bash
# On primary node

# 1. Ensure latest data is restored
# Get backup from standby if needed

# 2. Verify primary is healthy
curl http://localhost/health/dependencies

# 3. On standby, switch back to standby mode
docker compose down
sed -i 's/DEPLOYMENT_MODE=primary/DEPLOYMENT_MODE=standby/' .env
sed -i 's/EAS_BROADCAST_ENABLED=true/EAS_BROADCAST_ENABLED=false/' .env
docker compose -f docker-compose.yml -f examples/docker-compose.standby.yml up -d

# 4. Update DNS/load balancer back to primary
```

## Testing Failover

Regularly test failover procedures:

```bash
# Test plan (quarterly recommended)

1. Schedule maintenance window
2. Create backup on primary
3. Verify backup sync to standby
4. Perform test failover
5. Verify all services on standby
6. Run operational tests
7. Fail back to primary
8. Document any issues
9. Update runbooks as needed
```

## Monitoring and Alerts

Monitor these metrics on both nodes:

- Primary health endpoint: `/health/dependencies`
- Backup synchronization lag
- Disk space on both nodes
- Network connectivity between nodes
- Database replication lag (if using shared DB)

Set up alerts for:
- Primary node unreachable for >2 minutes
- Backup sync failure
- Standby node unreachable
- Disk space >80%
- Database connection failures

## Troubleshooting

### Backup sync not working

```bash
# Check NFS mount
df -h | grep primary-backups

# Check rsync connectivity
ssh primary-host 'ls -la /var/backups/eas-station'

# Check logs
journalctl -u eas-backup-sync -f
```

### Failover incomplete

```bash
# Check service status
docker compose ps

# Check application logs
docker compose logs app

# Verify database connectivity
docker compose exec app python -c "from app_core.extensions import db; db.session.execute('SELECT 1')"
```

### Data inconsistency after failback

```bash
# Compare databases
pg_dump -h primary > primary.sql
pg_dump -h standby > standby.sql
diff primary.sql standby.sql

# If needed, restore from known good backup
python3 tools/restore_backup.py --backup-dir /path/to/backup
```

## Best Practices

1. **Test regularly**: Failover at least quarterly
2. **Monitor continuously**: Set up alerts for all critical paths
3. **Document everything**: Keep runbooks up to date
4. **Automate where possible**: Reduce human error
5. **Maintain sync**: Ensure backups are always current
6. **Verify restores**: Test backup restoration monthly
7. **Keep standby ready**: Minimize activation time
8. **Plan communications**: Have notification procedures
9. **Review logs**: Regular audit of failover readiness
10. **Train staff**: Ensure multiple people can perform failover

## Further Reading

- [Backup Strategy Documentation](../docs/runbooks/backup_strategy.md)
- [Outage Response Runbook](../docs/runbooks/outage_response.md)
- [PostgreSQL Replication](https://www.postgresql.org/docs/current/high-availability.html)
- [Docker Swarm for HA](https://docs.docker.com/engine/swarm/)
