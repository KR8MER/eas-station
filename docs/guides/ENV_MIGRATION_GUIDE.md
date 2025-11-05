# Environment Variable Migration Guide

This guide helps you update your `.env` file to the new consolidated format.

## Summary of Changes

### ✅ Improvements
1. **Removed duplicate database variables** - Use only `POSTGRES_*` (removed `ALERTS_DB_*` duplicates)
2. **Added missing IPAWS configuration** - `IPAWS_CAP_FEED_URLS`, `IPAWS_DEFAULT_LOOKBACK_HOURS`
3. **Added location defaults** - `DEFAULT_TIMEZONE`, `DEFAULT_COUNTY_NAME`, etc.
4. **Better organization** - Grouped by functionality with clear comments
5. **Complete documentation** - Every variable explained

### 🔄 Variables Changed

| Old Variable | New Variable | Action |
|--------------|--------------|--------|
| `ALERTS_DB_HOST` | `POSTGRES_HOST` | **REMOVE** - Use POSTGRES_HOST only |
| `ALERTS_DB_PORT` | `POSTGRES_PORT` | **REMOVE** - Use POSTGRES_PORT only |
| `ALERTS_DB_NAME` | `POSTGRES_DB` | **REMOVE** - Use POSTGRES_DB only |
| `ALERTS_DB_USER` | `POSTGRES_USER` | **REMOVE** - Use POSTGRES_USER only |
| `ALERTS_DB_PASS` | `POSTGRES_PASSWORD` | **REMOVE** - Use POSTGRES_PASSWORD only |
| N/A | `IPAWS_CAP_FEED_URLS` | **ADD** - Leave empty for auto-fallback |
| N/A | `IPAWS_DEFAULT_LOOKBACK_HOURS` | **ADD** - Set to 12 |
| N/A | `DEFAULT_TIMEZONE` | **ADD** - Your timezone |
| N/A | `DEFAULT_COUNTY_NAME` | **ADD** - Your county |
| N/A | `EAS_TTS_PROVIDER` | **ADD** - Set if using TTS |
| N/A | `FLASK_DEBUG` | **ADD** - Set to false |

## Migration Steps

### Option 1: Quick Fix (Update Existing .env)

Open your `.env` file and make these changes:

```bash
# 1. REMOVE these duplicate lines (keep POSTGRES_* versions):
# ALERTS_DB_HOST=alerts-db
# ALERTS_DB_PORT=5432
# ALERTS_DB_NAME=alerts
# ALERTS_DB_USER=postgres
# ALERTS_DB_PASS=postgres
# ALERTS_DB_CONTAINER=alerts-db
# ALERTS_DB_VOLUME=eas-station_alerts-db
# ALERTS_DB_VERSION=16.2

# 2. ADD these new lines after POLL_INTERVAL_SEC:
CAP_ENDPOINTS=
IPAWS_CAP_FEED_URLS=
IPAWS_DEFAULT_LOOKBACK_HOURS=12

# 3. ADD these location defaults:
DEFAULT_TIMEZONE=America/New_York
DEFAULT_COUNTY_NAME=Putnam County
DEFAULT_STATE_CODE=OH
DEFAULT_ZONE_CODES=OHZ016,OHC137
DEFAULT_AREA_TERMS=PUTNAM COUNTY,PUTNAM CO
DEFAULT_MAP_CENTER_LAT=41.0195
DEFAULT_MAP_CENTER_LNG=-84.1190
DEFAULT_MAP_ZOOM=9
DEFAULT_LED_LINES=PUTNAM COUNTY,EMERGENCY MGMT,NO ALERTS,SYSTEM READY

# 4. ADD TTS provider setting:
EAS_TTS_PROVIDER=

# 5. ADD Flask debug setting:
FLASK_DEBUG=false
```

### Option 2: Fresh Start (Recommended)

1. **Backup your current .env:**
   ```bash
   cp .env .env.backup
   ```

2. **Copy the new template:**
   ```bash
   cp .env.example .env
   ```

3. **Update these REQUIRED values in your new .env:**
   ```bash
   SECRET_KEY=<your-existing-secret-key-from-backup>
   POSTGRES_PASSWORD=<your-db-password-from-backup>
   POSTGRES_HOST=alerts-db  # Or your database host
   ```

4. **Optional: Restore your custom settings from backup:**
   - Azure OpenAI endpoint/key (if you use TTS)
   - Location settings (county, zones, coordinates)
   - LED sign IP (if you have one)
   - Any custom EAS settings

## Validation

After migration, verify your .env has:

```bash
# Required
✓ SECRET_KEY=<64-character-hex-string>
✓ POSTGRES_PASSWORD=<not-'change-me'>
✓ POSTGRES_HOST=<your-db-host>
✓ POSTGRES_DB=alerts
✓ POSTGRES_USER=postgres

# IPAWS Configuration
✓ IPAWS_CAP_FEED_URLS=  # Empty is OK (uses auto-fallback)
✓ IPAWS_DEFAULT_LOOKBACK_HOURS=12

# No duplicates
✗ No ALERTS_DB_* variables
```

## Testing

After migration:

```bash
# Restart containers to pick up changes
cd ~/eas-station
sudo docker compose down
sudo docker compose up -d

# Check logs
sudo docker compose logs -f ipaws-poller

# Should see:
# INFO:__main__:Starting CAP Alert Poller with LED Integration - Mode: IPAWS
```

## Rollback

If you have issues:

```bash
# Restore backup
cp .env.backup .env

# Restart
sudo docker compose restart
```

## Questions?

- **Do I need to update DATABASE_URL?** No, it's auto-constructed from POSTGRES_* variables
- **What if I'm using external monitoring tools?** Comment out `ALERTS_DB_*` instead of deleting
- **Do I need all DEFAULT_* variables?** No, they're optional defaults for the admin UI
- **What about my custom Azure endpoints?** Keep them - they're still supported

## Summary

✅ **Benefits:**
- Cleaner configuration
- No duplicate values
- Better documented
- All features accessible
- Future-proof

⚠️ **Breaking Changes:**
- Must have `SECRET_KEY` set (can't be empty or default)
- Must have `POSTGRES_*` credentials explicitly set
- ALERTS_DB_* variables ignored (use POSTGRES_* instead)
