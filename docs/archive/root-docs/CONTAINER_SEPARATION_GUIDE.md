# Container Separation Implementation Guide

## Overview
This guide shows how to separate the monolithic `cap_poller.py` into independent containers so `htop` shows accurate CPU usage per component.

## Current Problem

**Before** (Everything in one process):
```bash
$ docker exec noaa-poller htop
PID   %CPU  COMMAND
1     100%  python cap_poller.py    # Which part is using CPU?!
```

**After** (Separated containers):
```bash
$ htop
PID   %CPU  COMMAND
1234  2%    python cap_poller.py          # CAP polling
5678  5%    gunicorn wsgi:app             # Web UI  
9012  10%   python run_radio_manager.py   # SDR
3456  80%   python eas_audio_monitor.py   # AHA! The CPU hog!
```

## Components to Separate

| Component | Current Location | New Container | Purpose |
|-----------|------------------|---------------|---------|
| CAP Poller | `noaa-poller` | `noaa-poller` | Poll CAP APIs, store alerts |
| Flask Web UI | `app` | `app` | Web interface, REST API |
| EAS Broadcaster | Inside `noaa-poller` | `eas-broadcaster` | Trigger audio broadcasts |
| Radio/SDR Manager | Inside `noaa-poller` | `radio-manager` | Manage SDR receivers |
| EAS Audio Monitor | Inside `app` | `eas-audio-monitor` | Scan audio for EAS alerts |

## Implementation Steps

### Step 1: Create Standalone Scripts

Already created:
- ✅ `scripts/run_eas_broadcaster.py` - EAS broadcast service
- ✅ `scripts/run_radio_manager.py` - SDR management service
- ⏳ Need to verify `examples/run_continuous_eas_monitor.py` exists

### Step 2: Update docker-compose.yml

Two options:

**Option A: Use the new separated compose file**
```bash
# Backup current compose
cp docker-compose.yml docker-compose.yml.backup

# Use separated version
cp docker-compose.separated.yml docker-compose.yml

# Update environment variables
nano .env  # Or stack.env
```

**Option B: Manually add services to existing docker-compose.yml**
Add these services to your existing `docker-compose.yml`:

```yaml
  eas-broadcaster:
    image: eas-station:latest
    depends_on:
      - alerts-db
    networks:
      - eas-network
    command: ["python", "scripts/run_eas_broadcaster.py"]
    restart: unless-stopped
    env_file:
      - stack.env
    volumes:
      - app-config:/app-config
    environment:
      POSTGRES_HOST: ${POSTGRES_HOST:-alerts-db}
      EAS_BROADCAST_CHECK_INTERVAL: "5"
    devices:
      - /dev/snd:/dev/snd

  radio-manager:
    image: eas-station:latest
    depends_on:
      - alerts-db
    networks:
      - eas-network
    command: ["python", "scripts/run_radio_manager.py"]
    restart: unless-stopped
    env_file:
      - stack.env
    environment:
      POSTGRES_HOST: ${POSTGRES_HOST:-alerts-db}
      ENABLE_RADIO_MANAGER: "0"  # Set to 1 if using SDR
    devices:
      - /dev/bus/usb:/dev/bus/usb

  eas-audio-monitor:
    image: eas-station:latest
    depends_on:
      - alerts-db
    networks:
      - eas-network
    command: ["python", "examples/run_continuous_eas_monitor.py"]
    restart: unless-stopped
    env_file:
      - stack.env
    environment:
      POSTGRES_HOST: ${POSTGRES_HOST:-alerts-db}
      EAS_SCAN_INTERVAL: "6.0"  # IMPORTANT: Prevent CPU backlog
      MAX_CONCURRENT_EAS_SCANS: "2"
    devices:
      - /dev/snd:/dev/snd
```

### Step 3: Disable Components in noaa-poller

Update the `noaa-poller` service environment:

```yaml
  noaa-poller:
    # ... existing config ...
    environment:
      # ... existing vars ...
      CAP_POLLER_ENABLE_RADIO: "0"  # Radio now in separate container
      # Note: EAS broadcaster needs to be decoupled from poller code
```

### Step 4: Update Environment Variables

Add to `.env` or `stack.env`:

```bash
# EAS Broadcaster
EAS_BROADCAST_CHECK_INTERVAL=5  # Check for new alerts every 5 seconds

# Radio Manager (only if using SDR)
ENABLE_RADIO_MANAGER=0  # Set to 1 to enable SDR
RADIO_CONFIG_REFRESH_INTERVAL=300  # Refresh config every 5 minutes

# EAS Audio Monitor (THE CPU HOG - configure carefully!)
EAS_SCAN_INTERVAL=6.0  # CRITICAL: Increase from 3.0 to prevent backlog
MAX_CONCURRENT_EAS_SCANS=2  # Limit concurrent scans
```

### Step 5: Deploy

```bash
# Stop existing services
docker-compose down

# Rebuild image with new scripts
docker-compose build

# Start with new separated services
docker-compose up -d

# Verify all services started
docker-compose ps
```

### Step 6: Verify Separation

```bash
# Check that all services are running
docker-compose ps

# Should show:
# - app (Flask UI)
# - noaa-poller (CAP polling)
# - eas-broadcaster (EAS broadcast)
# - radio-manager (SDR - if enabled)
# - eas-audio-monitor (Audio scanning)

# Monitor CPU usage per container
docker stats

# Should show individual CPU percentages:
# CONTAINER            CPU %
# eas-audio-monitor    80%      # <-- The culprit is now visible!
# noaa-poller          2%
# app                  5%
# radio-manager        0%
```

## Benefits After Separation

### 1. Clear CPU Attribution
```bash
# Before: 
docker stats noaa-poller  # 100% CPU (but why??)

# After:
docker stats
# noaa-poller:        2%   (correct!)
# eas-audio-monitor: 80%   (AHA! The problem!)
# eas-broadcaster:    5%   (reasonable)
```

### 2. Independent Restarts
```bash
# Restart just the audio monitor without affecting polling
docker-compose restart eas-audio-monitor

# Or stop it entirely to test if CPU drops
docker-compose stop eas-audio-monitor
```

### 3. Independent Scaling
```bash
# Scale EAS monitor to multiple instances (if needed)
docker-compose up -d --scale eas-audio-monitor=2

# Or reduce resources for specific components
docker-compose.yml:
  eas-audio-monitor:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
```

### 4. Better Logging
```bash
# View logs for specific component
docker-compose logs -f eas-audio-monitor  # Just audio monitor logs
docker-compose logs -f noaa-poller        # Just poller logs

# No more mixed logs!
```

### 5. Easier Debugging
```bash
# Profile just the problematic component
docker exec eas-audio-monitor pip install py-spy
docker exec eas-audio-monitor py-spy top --pid 1

# Or attach debugger to specific process
docker exec -it eas-audio-monitor python -m pdb
```

## Troubleshooting

### Services Not Starting

**Check dependencies**:
```bash
docker-compose logs eas-broadcaster
docker-compose logs radio-manager
```

**Common issues**:
- Database not ready (add `wait-for-it.sh` script)
- Missing Python modules (rebuild image)
- Permission denied on /dev/snd (add `--privileged` or proper device permissions)

### High CPU Still Present

**Identify the culprit**:
```bash
docker stats

# If eas-audio-monitor is still high:
docker-compose logs eas-audio-monitor | grep "Skipping EAS scan"

# If still seeing backlog warnings, increase scan interval:
EAS_SCAN_INTERVAL=10.0  # Or even 15.0
```

### Components Not Communicating

**Check network**:
```bash
docker-compose exec noaa-poller ping alerts-db
docker-compose exec eas-broadcaster ping alerts-db
```

**Check database connectivity**:
```bash
docker-compose exec noaa-poller python -c "
from sqlalchemy import create_engine
engine = create_engine('postgresql://postgres:postgres@alerts-db:5432/alerts')
with engine.connect() as conn:
    result = conn.execute('SELECT 1')
    print('DB connected!')
"
```

## Gradual Migration Path

If you want to migrate gradually:

### Phase 1: Just fix the audio monitor (Immediate)
```bash
# Add only eas-audio-monitor service
# Set EAS_SCAN_INTERVAL=6.0
docker-compose up -d eas-audio-monitor
```

### Phase 2: Separate EAS broadcaster (Next)
```bash
# Add eas-broadcaster service
# Disable in cap_poller code
docker-compose up -d eas-broadcaster
```

### Phase 3: Separate radio manager (If using SDR)
```bash
# Add radio-manager service  
# Set CAP_POLLER_ENABLE_RADIO=0 in noaa-poller
docker-compose up -d radio-manager
```

## Rollback Plan

If something goes wrong:

```bash
# Stop new services
docker-compose stop eas-broadcaster radio-manager eas-audio-monitor

# Restore original docker-compose.yml
cp docker-compose.yml.backup docker-compose.yml

# Restart with original configuration
docker-compose up -d
```

## Monitoring After Migration

```bash
# Create a monitoring script
cat > monitor_cpu.sh <<'EOF'
#!/bin/bash
while true; do
    clear
    echo "=== Container CPU Usage ==="
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
    echo ""
    echo "Press Ctrl+C to stop"
    sleep 2
done
EOF

chmod +x monitor_cpu.sh
./monitor_cpu.sh
```

## Success Criteria

After successful migration:

✅ `docker stats` shows accurate CPU per container
✅ No more "Skipping EAS scan" warnings (or very few)
✅ `htop` shows separate processes with clear names
✅ Total CPU usage is lower (no more backlog)
✅ Can restart/debug individual components
✅ Logs are separated and easier to read

## Files Created

1. ✅ `scripts/run_eas_broadcaster.py` - Standalone EAS broadcaster
2. ✅ `scripts/run_radio_manager.py` - Standalone SDR manager
3. ✅ `docker-compose.separated.yml` - Separated services example
4. ✅ This guide

## Next Steps

1. Review the standalone scripts
2. Test in development environment first
3. Update docker-compose.yml
4. Deploy and monitor
5. Verify CPU attribution is correct
6. Adjust EAS_SCAN_INTERVAL as needed
7. Celebrate clear CPU visibility! 🎉
