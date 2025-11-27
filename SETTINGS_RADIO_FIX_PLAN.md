# Settings/Radio Page Fix Plan

## Current Issues

The `/settings/radio` page is broken because it tries to get receiver status from multiple incompatible sources:

1. **Database** (`RadioReceiver.query`) - Has receiver config but NO live status
2. **Redis** - Should have live status from sdr-service, but connection may be failing
3. **RadioManager** - Only exists in sdr-service container, not accessible from web app

Result: Receivers show as "stopped" or with no status, even though they're running fine in sdr-service.

## Root Cause

**Architectural mismatch**: The page was designed for monolithic deployment where RadioManager runs in the same process as the web app. In Docker separated architecture:
- Web app runs in `app` container
- RadioManager runs in `sdr-service` container
- Status needs to flow: sdr-service → Redis → web app

## The Fix

### Option 1: Use Diagnostics API (Recommended)

Make `/settings/radio` use the same data source as `/settings/radio/diagnostics`:

```javascript
// Instead of initialReceivers from Flask template
async function loadReceivers() {
    const response = await fetch('/api/radio/diagnostics/status');
    const data = await response.json();

    // Merge database config with live status from RadioManager
    const receivers = Object.entries(data.radio_manager?.receivers || {}).map(([id, receiver]) => ({
        ...receiver.config,
        ...receiver,  // Live status from sdr-service
        id: receiver.receiver_id
    }));

    renderReceivers(receivers);
}
```

### Option 2: Fix Redis Publishing (Harder)

Make sdr-service reliably publish status to Redis:
1. Check Redis connection in sdr-service
2. Ensure periodic status updates are published
3. Web app reads from Redis via `get_redis_client()`

### Option 3: Create Unified Status API

New endpoint: `/api/radio/receivers/with-status`
- Queries database for config
- Fetches live status from sdr-service via Redis
- Returns merged data

## Recommendation

**Use Option 1** - it's the simplest and most reliable. The diagnostics page already works correctly, so just use the same data source.

## Implementation Steps

1. ✅ Fix RSSI bars (committed)
2. Update `/settings/radio` template to fetch from diagnostics API
3. Remove broken Redis/RadioManager status fetching
4. Test with actual receivers running in sdr-service
5. Update auto-refresh to use diagnostics endpoint

## Files to Modify

- `templates/settings/radio.html` - Change data source to diagnostics API
- `webapp/routes_settings_radio.py` - Simplify or remove status fetching
- Document the change in RELEASE_NOTES
