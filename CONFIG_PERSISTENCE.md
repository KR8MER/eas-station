# Configuration Persistence Guide

## Overview

EAS Station uses a **persistent Docker volume** to store configuration, ensuring your settings survive:
- Container recreation (`docker compose down/up`)
- Git repository updates (`git pull`)
- Fresh deployments (`git clone`)
- Portainer auto-updates

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  Configuration Persistence Architecture             │
└─────────────────────────────────────────────────────┘

  Local Filesystem              Docker Volume
  ════════════════              ═════════════

  .env (editable)     ←sync→    app-config volume
  └─ Your settings              └─ /app-config/.env
     (gitignored)                  (persists across
                                    deployments)
```

**Workflow:**
1. Edit `.env` in your repo directory
2. Run `./start-pi.sh` - syncs .env → volume → starts containers
3. Settings persist in volume even after `git pull` or container recreation

## Configuration Files

### Local `.env` (Your Working Copy)

**Location:** `/path/to/eas-station/.env`

**Purpose:**
- Your editable configuration file
- Gitignored (won't be committed)
- Synced TO volume on startup

**Edit this file** to change settings like `OLED_ENABLED=true`.

### Volume `/app-config/.env` (Persistent Storage)

**Location:** Docker volume `eas-station_app-config`

**Purpose:**
- Source of truth for running containers
- Persists across deployments
- Survives `git pull`, `git clone`, container recreation

**The container reads from here**, not from your local `.env`.

## Typical Workflows

### Workflow 1: Initial Setup

```bash
# Clone repository
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# Copy example config
cp .env.example .env

# Edit settings
nano .env
# Set OLED_ENABLED=true, add SECRET_KEY, etc.

# Start (syncs .env to volume automatically)
sudo ./start-pi.sh
```

Your settings are now in the persistent volume.

### Workflow 2: Change Settings

```bash
# Edit local .env
nano .env
# Change OLED_ROTATE=180 or other settings

# Restart (syncs changes to volume)
sudo ./start-pi.sh
```

Changes are applied and persisted.

### Workflow 3: After Git Pull

```bash
# Update code
git pull origin main

# Your local .env is preserved (gitignored)
# Just restart to apply any new code
sudo ./start-pi.sh
```

Your settings remain intact because `.env` isn't tracked by git.

### Workflow 4: Fresh Clone (Migrating to New System)

```bash
# On new system, clone repo
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# Pull your old settings from the volume
# (if you're mounting the same Docker volumes)
sudo ./pull-config.sh

# Or copy from backup
scp old-pi:~/eas-station/.env .env

# Start with your settings
sudo ./start-pi.sh
```

### Workflow 5: Editing Settings Already in Volume

If you've been using Portainer or the web UI to edit settings, and now want to edit locally:

```bash
# Pull current settings from volume
sudo ./pull-config.sh
# This creates .env from the volume

# Edit the file
nano .env

# Push changes back and restart
sudo ./start-pi.sh
```

## Script Reference

### `start-pi.sh` (Push config → volume)

**What it does:**
1. Checks environment (Pi detection, GPIO devices)
2. Optionally enables OLED if not set
3. Fixes GPIO permissions
4. **Syncs local `.env` → persistent volume**
5. Starts containers with GPIO support

**When to use:**
- Initial deployment
- After changing settings in `.env`
- After `git pull`
- Regular startups

**Command:**
```bash
sudo ./start-pi.sh
```

### `pull-config.sh` (Pull volume → config)

**What it does:**
1. Backs up existing `.env` (if present)
2. **Copies volume → local `.env`**
3. Shows current OLED settings

**When to use:**
- Setting up on a new machine (with existing volume)
- Pulling settings from Portainer/web-managed deployment
- Viewing current production settings

**Command:**
```bash
sudo ./pull-config.sh
nano .env          # Make changes
sudo ./start-pi.sh # Push changes back
```

### `verify-gpio-oled.sh` (Diagnostic)

**What it does:**
- Checks container logs for GPIO/OLED initialization
- Detects MockFactory fallback
- Provides troubleshooting advice

**When to use:**
- After starting containers
- Troubleshooting OLED/GPIO issues

**Command:**
```bash
sudo ./verify-gpio-oled.sh
```

## Volume Management

### Inspect Volume Contents

```bash
# View volume details
docker volume inspect eas-station_app-config

# Read .env from volume
docker run --rm -v eas-station_app-config:/app-config alpine cat /app-config/.env
```

### Backup Volume

```bash
# Backup to file
docker run --rm \
  -v eas-station_app-config:/app-config \
  -v "$(pwd):/backup" \
  alpine tar czf /backup/config-backup.tar.gz -C /app-config .

# Restore from backup
docker run --rm \
  -v eas-station_app-config:/app-config \
  -v "$(pwd):/backup" \
  alpine sh -c "cd /app-config && tar xzf /backup/config-backup.tar.gz"
```

### Migrate to New System

**On old system:**
```bash
# Create backup
docker run --rm \
  -v eas-station_app-config:/app-config \
  -v "$(pwd):/backup" \
  alpine tar czf /backup/config-backup.tar.gz -C /app-config .

# Also backup local .env
cp .env .env.backup
```

**On new system:**
```bash
# Clone repo
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# Copy backup files
scp old-pi:~/eas-station/config-backup.tar.gz .
scp old-pi:~/eas-station/.env.backup .env

# Start (syncs to new volume)
sudo ./start-pi.sh
```

### Delete Volume (Fresh Start)

**WARNING: This deletes all saved settings!**

```bash
# Stop containers
sudo docker compose down

# Delete volume
docker volume rm eas-station_app-config

# Start fresh (will create new volume)
sudo ./start-pi.sh
```

## Portainer Integration

If deploying via Portainer from Git:

1. **Portainer uses the persistent volume** automatically
2. **Git repo's `.env` is ignored** (empty placeholder)
3. **Settings managed via web UI** → stored in volume
4. **To switch to local management:**
   ```bash
   # On the Pi, pull settings from volume
   sudo ./pull-config.sh

   # Edit locally
   nano .env

   # Remove Portainer stack
   # Deploy using start-pi.sh instead
   sudo ./start-pi.sh
   ```

## Environment Variable Precedence

Settings are loaded in this order (last wins):

1. **Defaults** in code (e.g., `OLED_ENABLED=false`)
2. **`stack.env`** (Portainer defaults)
3. **`/app-config/.env`** (persistent volume) ← **Main config**
4. **`docker-compose.yml` environment section** (overrides)

Your `.env` file → synced to `/app-config/.env` → read by app.

## Common Issues

### Issue: "OLED display disabled" but `.env` has `OLED_ENABLED=true`

**Cause:** Local `.env` not synced to volume

**Fix:**
```bash
sudo ./start-pi.sh  # Syncs on every start
```

### Issue: Settings reset after `git pull`

**Cause:** You committed `.env` to git and pulled changes

**Fix:**
```bash
# .env should be gitignored
echo ".env" >> .gitignore
git checkout .env  # Restore your version

# Or pull from volume
sudo ./pull-config.sh
```

### Issue: Changes via web UI don't appear in `.env`

**Cause:** Web UI writes to volume, not local file

**Fix:**
```bash
# Pull volume → .env to see changes
sudo ./pull-config.sh
```

### Issue: Can't find old settings after fresh clone

**Cause:** `.env` is gitignored and wasn't backed up

**Fix:**
- **Prevention:** Always backup `.env` before system changes
- **Recovery:** Use web UI to reconfigure, or restore from backup

## Best Practices

1. **Keep `.env` gitignored** - Don't commit secrets
2. **Backup `.env` before major changes** - Copy to safe location
3. **Use `start-pi.sh` for all startups** - Ensures sync
4. **Document custom settings** - Add comments in `.env`
5. **Test after changes** - Run `verify-gpio-oled.sh`

## See Also

- `QUICKSTART_PI.md` - Quick start guide
- `OLED_GPIO_TROUBLESHOOTING.md` - Detailed troubleshooting
- `OLED_SAMPLE_SCREENS.md` - Sample OLED displays

## Summary

```bash
# The persistence workflow is simple:

# 1. Edit .env locally
nano .env

# 2. Start containers (auto-syncs to volume)
sudo ./start-pi.sh

# 3. Settings persist across deployments!
```

Your configuration is now in the persistent Docker volume and will survive updates, redeployments, and container recreation.
