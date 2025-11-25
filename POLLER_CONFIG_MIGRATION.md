# Poller Configuration Migration Guide

## Overview

As of this update, the NOAA and IPAWS pollers now use **separate configuration files** instead of sharing a single `/app-config/.env` file.

### Why This Change?

- **Configuration Conflicts**: Both pollers were reading the same config file, causing NOAA to inherit IPAWS settings and vice versa
- **Independent Control**: Each poller can now be configured independently without affecting the other
- **Cleaner Architecture**: Service-specific configs follow Docker best practices

## New Configuration Structure

```
/app-config/
├── .env          # Main app configuration (web UI, database, etc.)
├── noaa.env      # NOAA Weather poller configuration
└── ipaws.env     # IPAWS (FEMA) poller configuration
```

## Migration Steps

### Step 1: Initialize Config Files

Run the initialization script to create separate poller configs:

```bash
docker exec eas-station-app bash /app/init_poller_configs.sh
```

This script will:
- Create `/app-config/noaa.env` with NOAA defaults
- Create `/app-config/ipaws.env` and migrate existing IPAWS settings from `/app-config/.env`
- Preserve existing files (won't overwrite)

### Step 2: Fix Empty FIPS Codes (If Needed)

If your location has empty FIPS codes (logs show `🔢 SAME/FIPS codes: []`):

```bash
cat fix_fips_codes.sql | docker-compose exec -T alerts-db psql -U postgres -d alerts
```

### Step 3: Rebuild Containers

```bash
docker-compose down
docker-compose up -d --build
```

### Step 4: Verify Configuration

Check the logs to confirm proper configuration:

```bash
docker-compose logs -f noaa-poller ipaws-poller
```

**Expected NOAA poller logs:**
```
INFO:__main__:Starting CAP Alert Poller with LED Integration - Mode: NOAA
INFO:__main__:Polling: https://api.weather.gov/alerts/active?zone=OHZ016
INFO:__main__:🔢 SAME/FIPS codes: ['039137']
```

**Expected IPAWS poller logs:**
```
INFO:__main__:Starting CAP Alert Poller with LED Integration - Mode: IPAWS
INFO:__main__:Polling: https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/...
INFO:__main__:🔢 SAME/FIPS codes: ['039137']
```

## Configuration File Details

### noaa.env

```bash
# NOAA Weather Alert Poller Configuration
CAP_POLLER_MODE=NOAA

# NOAA automatically builds endpoints from zone codes in location_settings
# No need to specify CAP_ENDPOINTS or IPAWS_CAP_FEED_URLS

# Optional: Enable debug logging
# CAP_POLLER_DEBUG_RECORDS=1

# Optional: Enable radio captures
# CAP_POLLER_ENABLE_RADIO=1
```

### ipaws.env

```bash
# IPAWS (FEMA) Alert Poller Configuration
CAP_POLLER_MODE=IPAWS

# IPAWS Feed URL with timestamp
IPAWS_CAP_FEED_URLS=https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/2024-01-01T00:00:00Z

# Optional: Use staging/test environment
# IPAWS_CAP_FEED_URLS=https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/2024-01-01T00:00:00Z

# Optional: Disable SSL verification (NOT recommended for production)
# SSL_VERIFY_DISABLE=1

# Optional: Enable debug logging
# CAP_POLLER_DEBUG_RECORDS=1
```

## Troubleshooting

### NOAA Still Polling IPAWS

If NOAA poller is still fetching from `apps.fema.gov`:

1. Check `/app-config/noaa.env` exists:
   ```bash
   docker exec eas-station-noaa-poller cat /app-config/noaa.env
   ```

2. Verify CAP_POLLER_MODE is set:
   ```bash
   docker exec eas-station-noaa-poller env | grep CAP_POLLER_MODE
   ```

3. Re-run init script and rebuild containers

### Empty FIPS Codes

If logs show `🔢 SAME/FIPS codes: []`:

1. Run the FIPS code fix script (Step 2 above)
2. Restart pollers:
   ```bash
   docker-compose restart noaa-poller ipaws-poller
   ```

### Redis Connection Errors

If seeing "Error 111 connecting to localhost:6379":

- This should be fixed with the latest code
- Rebuild containers to get the fix

## Rolling Back

If you need to revert to the old single-config behavior:

1. Edit `docker-compose.yml`:
   ```yaml
   # Change both pollers back to:
   CONFIG_PATH: /app-config/.env
   ```

2. Rebuild containers:
   ```bash
   docker-compose down
   docker-compose up -d --build
   ```

Note: This will bring back the configuration conflicts!
