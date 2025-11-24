# EAS Monitor CPU Usage Fix

## Problem
The EAS audio monitor was consuming constant 100%+ CPU due to scan backlog. Logs showed:
```
WARNING: Skipping EAS scan #145: 2 scans already active (max=2)
WARNING: Skipping EAS scan #146: 2 scans already active (max=2)
... hundreds more ...
```

## Root Cause
1. EAS monitor scans every 3 seconds for emergency audio alerts
2. Each scan does CPU-intensive FFT/audio processing
3. **Scans were taking LONGER than 3 seconds** to complete
4. New scans queued up before old ones finished
5. Hit max concurrent limit (2), creating constant backlog
6. **Result: 100% CPU trying to keep up**

## Solution Implemented

### 1. Made scan_interval Configurable
Added `EAS_SCAN_INTERVAL` environment variable to allow tuning.

**Default**: 3.0 seconds (75% overlap)
**Recommended for high CPU**: 6.0-10.0 seconds

### 2. How to Apply Fix

**Option A: Environment Variable (Recommended)**
Add to your `.env` or `docker-compose.yml`:
```bash
EAS_SCAN_INTERVAL=6.0  # Double the interval to reduce CPU
```

**Option B: Increase Max Concurrent Scans**
```bash
MAX_CONCURRENT_EAS_SCANS=4  # Allow more parallel scans
```

**Option C: Disable EAS Monitoring (if not needed)**
If you're not monitoring radio audio for EAS alerts:
```bash
# In your configuration, disable audio monitoring
# (depends on your setup - check with maintainer)
```

### 3. Restart After Configuration
```bash
docker-compose down
docker-compose up -d
# OR
docker restart eas-station-noaa-poller-1
```

## How to Verify Fix

### Check if Scans Complete Within Interval
```bash
# Watch logs in real-time
docker logs -f eas-station-noaa-poller-1 | grep "EAS scan"

# Should see:
# - Fewer or no "Skipping" warnings
# - Lower scan numbers (not rapidly incrementing)
```

### Monitor CPU
```bash
# Should drop from 100% to 10-30%
docker stats eas-station-noaa-poller-1
```

### Check Scan Stats
```bash
# Look for scan performance in logs
docker logs eas-station-noaa-poller-1 | grep -i "scan"
```

## Expected Results

| Configuration | Scans/min | CPU Usage | Alert Detection |
|---------------|-----------|-----------|-----------------|
| 3s interval | 20 | 100% (backlog) | Excellent (75% overlap) |
| 6s interval | 10 | 20-30% | Good (50% overlap) |
| 10s interval | 6 | 10-15% | Adequate (20% overlap) |

**Note**: EAS alerts repeat 3 times over ~9 seconds, so even a 10s interval should catch them.

## Understanding the Trade-offs

### Scan Interval
- **Lower (3s)**: Better overlap, catches alerts faster, **higher CPU**
- **Higher (6-10s)**: Less overlap, may miss very brief alerts, **much lower CPU**

### Why 3s Default?
- SAME header repeats 3 times at 3-second intervals
- 3s scan with 12s buffer = 75% overlap ensures at least 2 captures per alert
- Conservative default to never miss alerts

### Why Increase?
- If your system can't complete scans in 3s, they pile up
- Better to scan less frequently and complete each scan
- EAS alerts are long enough (9+ seconds) that 6-10s interval still catches them

## Troubleshooting

### Still High CPU After Fix?

1. **Check if setting applied**:
   ```bash
   docker exec eas-station-noaa-poller-1 env | grep EAS_SCAN_INTERVAL
   ```

2. **Check for other issues**:
   - N+1 query problem (fixed in this PR)
   - Radio SDR busy-wait (check if radio is enabled)
   - Database connection issues

3. **Try higher interval**:
   ```bash
   EAS_SCAN_INTERVAL=10.0  # Or even 15.0
   ```

### Scans Still Skipping?

If you still see "Skipping" warnings with 6s+ interval:
- Your system may be very slow
- Consider increasing `MAX_CONCURRENT_EAS_SCANS` to 4 or 6
- Or check what's making scans slow (disk I/O, CPU throttling, etc.)

### Missing Alerts?

If you miss alerts with higher intervals:
- Lower the interval back to 5-6 seconds
- Check that buffer_duration is adequate (12s default)
- Verify alerts are actually being broadcast (test with known alert)

## Files Changed

1. `app_core/audio/monitor_manager.py` - Added EAS_SCAN_INTERVAL config
2. `poller/cap_poller.py` - Fixed N+1 query problem (unrelated but also CPU fix)
3. This document - Fix instructions

## Performance Improvements Already in Code

The EAS monitor already has these optimizations:
1. **Fast pre-check** (line 865): FFT signature detection to skip decoding non-EAS audio
2. **Background threads**: Scans run in separate threads to avoid blocking
3. **Concurrent limit**: Prevents resource exhaustion
4. **Circular buffer**: Efficient audio storage

The issue was simply that scans took longer than the interval, not a bug in the code.

## Recommended Settings

### For Production (Reliability Priority)
```bash
EAS_SCAN_INTERVAL=5.0  # Good balance
MAX_CONCURRENT_EAS_SCANS=3  # Allow some buffer
```

### For Resource-Constrained Systems
```bash
EAS_SCAN_INTERVAL=10.0  # Lower CPU
MAX_CONCURRENT_EAS_SCANS=2  # Standard limit
```

### For Test/Development
```bash
EAS_SCAN_INTERVAL=3.0  # Maximum sensitivity
MAX_CONCURRENT_EAS_SCANS=4  # More parallelism
```

## Long-term Optimizations (Future)

Potential areas for further improvement:
1. Optimize FFT calculations (use smaller windows)
2. Cache frequency analysis results
3. Use GPU acceleration for FFT
4. Implement adaptive scan intervals based on load
5. Add metrics/monitoring for scan duration
