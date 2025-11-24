# Migration Guide: Redis & Audio Separation Completion

**Date:** 2025-11-24
**Scope:** Complete Redis migration and audio containerization fixes
**Status:** ✅ COMPLETED

---

## Executive Summary

This migration completes two major architectural improvements that were partially implemented:

1. **Redis Migration**: Make Redis required (not optional) for production deployments
2. **Audio Separation**: Complete the audio-service container separation

### What Changed

- ✅ Redis is now the default cache backend (was: in-memory)
- ✅ App container no longer initializes audio (was: trying to run audio locally)
- ✅ Redis Pub/Sub command channel implemented for inter-container communication
- ✅ Dead code removed (226 lines from audio_ingest.py, 87 lines from startup_integration.py)
- ✅ File-based fallbacks removed from worker_coordinator.py
- ✅ Docker-compose app container cleaned up (removed USB/device passthrough, privileged mode)
- ✅ .env.example updated with correct Redis defaults

---

## Breaking Changes

### 1. Redis is Now Required

**Before:**
```env
CACHE_TYPE=simple  # Default was in-memory
```

**After:**
```env
CACHE_TYPE=redis  # Default is now Redis (REQUIRED)
```

**Action Required:**
- Ensure Redis container is running
- Update `.env` file if you overrode `CACHE_TYPE=simple`
- Set `CACHE_REDIS_URL` if using external Redis

### 2. App Container No Longer Runs Audio

**Before:**
- App container initialized audio controller on startup
- Control endpoints executed audio commands locally

**After:**
- App container serves UI only
- Control endpoints publish commands to Redis Pub/Sub
- Audio-service container subscribes and executes commands

**Action Required:**
- If running audio processing, use `docker-compose.separated.yml` or add audio-service container
- Update any custom scripts that assume app container runs audio

### 3. File-Based Fallbacks Removed

**Before:**
- Worker coordinator fell back to `/tmp/eas-station-metrics.json`
- Metrics written to temp files if Redis unavailable

**After:**
- Worker coordinator requires Redis
- Fails explicitly if Redis unavailable

**Action Required:**
- Ensure Redis is always available
- Monitor Redis connection health
- Add Redis to monitoring/alerting

---

## New Features

### Redis Pub/Sub Command Channel

Inter-container audio control via Redis:

```python
from app_core.audio.redis_commands import get_audio_command_publisher

# In app container
publisher = get_audio_command_publisher()
result = publisher.start_source('my-stream')
# Command sent via Redis Pub/Sub to audio-service

# In audio-service container (automatic)
subscriber = AudioCommandSubscriber(audio_controller)
subscriber.start()  # Listens for commands
```

**Commands Supported:**
- `source_start` - Start an audio source
- `source_stop` - Stop an audio source
- `source_add` - Add new audio source
- `source_update` - Update source configuration
- `source_delete` - Delete audio source
- `streaming_start` - Start auto-streaming
- `streaming_stop` - Stop auto-streaming

---

## Migration Steps

### Step 1: Update Environment Variables

```bash
# Edit .env or stack.env
nano .env

# Set Redis as cache backend
CACHE_TYPE=redis

# Verify Redis connection
CACHE_REDIS_URL=redis://redis:6379/0
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
```

### Step 2: Update Docker Compose

No changes needed if using default `docker-compose.yml`. The app container has been updated to:
- ❌ Remove USB device passthrough
- ❌ Remove privileged mode
- ❌ Remove Icecast environment variables
- ✅ Keep Redis connection (required)

### Step 3: Restart Services

```bash
# Pull latest changes
git pull origin main

# Rebuild containers
docker compose down
docker compose build --no-cache

# Start with new configuration
docker compose up -d

# Verify Redis connection
docker compose logs app | grep -i redis
# Should see: "✅ Redis-based worker coordinator available"
```

### Step 4: Verify Audio Service (if applicable)

If using audio processing:

```bash
# Check audio-service logs
docker compose -f docker-compose.separated.yml logs audio-service

# Verify metrics publishing
docker compose exec redis redis-cli
> GET eas:metrics
# Should return JSON with audio metrics
```

### Step 5: Test Control Endpoints

```bash
# Test start command (from app container to audio-service)
curl -X POST http://localhost/api/audio/sources/my-stream/start

# Check logs for Pub/Sub activity
docker compose logs app | grep "Published.*command"
docker compose logs audio-service | grep "Received command"
```

---

## Rollback Procedure

If issues occur:

```bash
# 1. Stop services
docker compose down

# 2. Check out previous version
git checkout <previous-commit>

# 3. Rebuild
docker compose build --no-cache

# 4. Start services
docker compose up -d
```

**Note:** Previous versions had incomplete migrations. You may encounter:
- File-based fallbacks that don't work in containers
- App trying to run audio locally
- Inconsistent cache behavior

---

## Verification Checklist

After migration, verify:

- [ ] Redis container is healthy: `docker compose ps redis`
- [ ] App container starts without audio init: `docker compose logs app | grep "🌐 App container"`
- [ ] Cache backend is Redis: Check logs for cache type
- [ ] No file-based fallback warnings: `docker compose logs | grep "/tmp/eas-station"`
- [ ] Audio commands work (if using audio-service): Test start/stop endpoints
- [ ] Metrics available in Redis: `docker exec redis redis-cli GET eas:metrics`

---

## Troubleshooting

### Error: "Redis is required for worker coordination"

**Cause:** Redis not available or not configured
**Fix:**
```bash
# Check Redis status
docker compose ps redis

# Check Redis logs
docker compose logs redis

# Verify connection from app
docker compose exec app ping redis
```

### Error: "Audio service communication unavailable"

**Cause:** Redis Pub/Sub not working or audio-service not running
**Fix:**
```bash
# Check if audio-service is running
docker compose -f docker-compose.separated.yml ps audio-service

# Check Redis Pub/Sub
docker compose exec redis redis-cli
> PSUBSCRIBE eas:audio:*
# Try sending a command from another terminal
```

### Cache Misses After Migration

**Cause:** Cache key format may have changed
**Fix:**
```bash
# Flush Redis cache (safe, will rebuild)
docker compose exec redis redis-cli FLUSHDB
```

### App Container Trying to Access USB Devices

**Cause:** Old docker-compose.yml still mounted
**Fix:**
```bash
# Ensure using latest docker-compose.yml
docker compose config | grep -A 5 "app:"
# Should NOT show device mounts
```

---

## Architecture Diagrams

### Before Migration

```
┌─────────────────────────────────────────┐
│ App Container (Integrated Mode)         │
│ ┌─────────────────────────────────────┐ │
│ │ Flask Web UI                        │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ Audio Controller (initialized!)     │ │  ❌ WRONG
│ │ - Tries to run audio locally        │ │
│ │ - Uses file-based metrics fallback  │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ Cache: in-memory (not shared)       │ │  ❌ WRONG
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### After Migration

```
┌──────────────────────┐         ┌──────────────────────┐
│ App Container        │         │ Audio-Service        │
│ ┌──────────────────┐ │         │ ┌──────────────────┐ │
│ │ Flask Web UI     │ │         │ │ Audio Controller │ │
│ │                  │ │         │ │ - FFmpeg sources │ │
│ │ Pub/Sub Client  │◄├─────────┤►│ - EAS Monitor    │ │
│ │ (commands)       │ │  Redis  │ │ - Streaming      │ │
│ └──────────────────┘ │         │ └──────────────────┘ │
│ ┌──────────────────┐ │         │ ┌──────────────────┐ │
│ │ Cache: Redis     │◄├─────────┤►│ Metrics Writer   │ │
│ │ (shared state)   │ │         │ │ (to Redis)       │ │
│ └──────────────────┘ │         │ └──────────────────┘ │
└──────────────────────┘         └──────────────────────┘
           │                                  │
           └──────────────┬───────────────────┘
                          ▼
                   ┌─────────────┐
                   │   Redis     │
                   │  - Cache    │
                   │  - Metrics  │
                   │  - Pub/Sub  │
                   └─────────────┘
```

---

## Performance Impact

### Expected Improvements

1. **Reduced CPU Usage in App Container**
   - No longer running audio processing threads
   - No longer attempting to decode streams
   - Smaller memory footprint

2. **Better Cache Hit Rates**
   - Redis shared across all app workers
   - Cache survives container restarts
   - Consistent state across instances

3. **Clearer Resource Attribution**
   - `docker stats` shows accurate per-container CPU
   - Audio processing isolated to audio-service
   - Easier to identify performance bottlenecks

### Metrics to Monitor

```bash
# Before migration - check CPU usage
docker stats --no-stream | grep "app\|audio"

# After migration - should see:
# - app: Lower CPU (5-10%)
# - audio-service: Higher CPU (audio processing)
```

---

## Related Documentation

- [System Architecture](architecture/SYSTEM_ARCHITECTURE.md) - Updated architecture diagrams
- [Redis Commands API](../app_core/audio/redis_commands.py) - Pub/Sub implementation
- [Container Separation Guide](archive/root-docs/CONTAINER_SEPARATION_GUIDE.md) - Historical context
- [Audio System Access Guide](audio/AUDIO_SYSTEM_ACCESS_GUIDE.md) - Audio APIs

---

## Support

If you encounter issues after migration:

1. Check logs: `docker compose logs --tail=100`
2. Verify Redis: `docker compose exec redis redis-cli PING`
3. Check GitHub Issues: https://github.com/KR8MER/eas-station/issues
4. Review audit findings: This migration addresses all issues in 2025-11-24 audit

---

## Credits

**Audit Date:** 2025-11-24
**Migrated By:** Claude Code
**Issues Found:** 10 critical, 8 high priority
**Issues Fixed:** All 18 issues resolved
**Lines Removed:** 313 lines of dead/unreachable code
**Lines Added:** 356 lines of new functionality (Redis Pub/Sub, documentation)

---

**Migration Status: ✅ COMPLETE**

All systems migrated successfully. Redis is now required. Audio separation complete.
