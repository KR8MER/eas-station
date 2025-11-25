# EAS Scan Concurrency Architecture

## Executive Summary

**Question**: "Only 2 scans of EAS data are being done simultaneously... Is this correct?"

**Answer**: Yes, by default 2 concurrent scans per Flask worker is correct, but this limit is now **configurable** to suit your hardware and requirements.

---

## Understanding the Architecture

### Multi-Layered System

```
┌─────────────────────────────────────────────────────────────┐
│ System Layer: Gunicorn (Process-based parallelism)         │
│                                                             │
│  Worker 1 (PID 123)          Worker 2 (PID 456)           │
│  ├─ Flask App                ├─ Flask App                  │
│  ├─ EAS Monitor              ├─ EAS Monitor                │
│  │  ├─ Scan Thread 1         │  ├─ Scan Thread 1          │
│  │  └─ Scan Thread 2         │  └─ Scan Thread 2          │
│  └─ Request Handler Threads  └─ Request Handler Threads    │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

1. **Gunicorn Workers** (Default: 1 worker)
   - Separate OS processes
   - Each worker runs a complete copy of the Flask application
   - Default configuration: `--workers 1 --threads 2`
   - Each worker is independent

2. **EAS Monitor** (One per worker)
   - Singleton instance within each worker process
   - Continuously buffers audio from configured sources
   - Spawns daemon threads to scan buffered audio for SAME headers

3. **Scan Threads** (Default: 2 concurrent per worker)
   - Independent daemon threads spawned by EAS Monitor
   - Process 12-second audio buffers
   - CPU-intensive operations:
     - FFT-based SAME tone detection (pre-filter)
     - FSK correlation decoding (full decode)
   - Typical duration: 0.5-3 seconds per scan (hardware dependent)

4. **Request Handler Threads** (Default: 2 per worker)
   - Handle HTTP requests from nginx
   - Independent from EAS scan threads
   - Not blocked by scanning activity

---

## Audio Stream Architecture

### Single Audio Pipeline

**Important**: The system processes **ONE aggregated audio stream**, not separate streams per source.

```
┌──────────────────┐
│  Audio Sources   │
│  ┌────────────┐  │
│  │ Stream 1   │  │
│  │ (WNCI)     │──┼──┐
│  └────────────┘  │  │
│  ┌────────────┐  │  │     ┌─────────────────────┐
│  │ Stream 2   │  │  ├────►│ AudioIngestController│
│  │ (WIMT)     │──┼──┤     │  (Priority Mixer)   │
│  └────────────┘  │  │     └──────────┬──────────┘
│  ┌────────────┐  │  │                │
│  │ Stream 3   │  │  │                │ Single mixed PCM stream
│  │ (Other)    │──┼──┘                │
│  └────────────┘  │                   ▼
└──────────────────┘         ┌─────────────────────┐
                             │  BroadcastQueue     │
                             │  (Non-blocking)     │
                             └──────────┬──────────┘
                                        │
                                        ▼
                             ┌─────────────────────┐
                             │  ContinuousEASMonitor│
                             │  (12s buffer)       │
                             │                     │
                             │  Scans every 3s:    │
                             │  ┌─────────────┐   │
                             │  │ Scan Thread │   │
                             │  │ (max 2)     │   │
                             │  └─────────────┘   │
                             └─────────────────────┘
```

**Key Points**:
- Multiple audio sources are **mixed into ONE stream** by AudioIngestController
- Priority-based selection: Stream 1 > Stream 2 > Stream 3
- EAS Monitor receives **one aggregated audio feed**
- Scan threads process **one 12-second buffer** from the aggregated stream
- `max_concurrent_scans=2` means 2 threads scanning **the same buffer** from **one stream**

---

## Concurrency Limits Explained

### `MAX_CONCURRENT_EAS_SCANS` (Default: 2)

**What it controls**: Maximum scan threads per EAS Monitor instance

**Scope**: Per Flask worker (NOT system-wide)

#### Calculation

```
Total Active Scan Threads = 
    Gunicorn Workers × MAX_CONCURRENT_EAS_SCANS
```

**Examples**:
- 1 worker, max_concurrent_scans=2 → **2 total scan threads**
- 2 workers, max_concurrent_scans=2 → **4 total scan threads**
- 1 worker, max_concurrent_scans=4 → **4 total scan threads**

### Why Limit Concurrent Scans?

1. **CPU Protection**: Each scan uses 5-15% CPU
2. **Memory Management**: Each scan holds a 12s audio buffer copy (~1MB)
3. **Decode Queue Prevention**: Prevents runaway thread creation
4. **Responsiveness**: Keeps web interface responsive

### What Happens When Limit is Reached?

```python
# In _scan_for_alerts():
if self._active_scans >= self.max_concurrent_scans:
    self._scans_skipped += 1
    logger.warning(
        f"Skipping EAS scan #{self._scans_skipped}: "
        f"{self._active_scans} scans already active (max={self.max_concurrent_scans})"
    )
    return  # Skip this scan cycle
```

**Impact**:
- Current scan request is skipped
- Next scan will happen at next interval (3 seconds later)
- If scans complete quickly, no alerts are missed
- If scans consistently pile up, time windows may be missed

---

## Scan Timing Analysis

### Measuring Scan Performance

The EAS monitor now tracks scan timing metrics:

```bash
# Check scan performance via API
curl http://localhost:5000/api/eas-monitor/status

# Key metrics:
{
  "avg_scan_duration_seconds": 1.2,
  "min_scan_duration_seconds": 0.8,
  "max_scan_duration_seconds": 2.5,
  "last_scan_duration_seconds": 1.1,
  "scans_performed": 1234,
  "scans_skipped": 5,
  "active_scans": 1,
  "max_concurrent_scans": 2
}
```

### Performance Guidelines

**Healthy System**:
- `avg_scan_duration_seconds` < `scan_interval` (3.0s)
- `scans_skipped` = 0 or very low
- `active_scans` usually 0-1

**Unhealthy System**:
- `avg_scan_duration_seconds` > `scan_interval` (3.0s)
- `scans_skipped` increasing rapidly
- `active_scans` consistently at `max_concurrent_scans`

### Decision Matrix

| Avg Scan Duration | Scans Skipped | Action |
|-------------------|---------------|--------|
| < 1.5s | 0 | ✅ Optimal - no changes needed |
| 1.5-3.0s | 0-5 | ✅ Good - monitor occasionally |
| 3.0-6.0s | > 10 | ⚠️ Warning - increase `max_concurrent_scans` to 3-4 |
| > 6.0s | > 50 | ❌ Critical - increase to 4-8 or upgrade hardware |

---

## Relationship to Gunicorn Workers

### Do EAS Scans Use Gunicorn Workers?

**No.** EAS scan threads are **independent daemon threads** within the Flask application.

```
┌─────────────────────────────────────────────┐
│ Gunicorn Worker Process (PID 123)          │
│                                             │
│ ┌─────────────────────────────────────┐   │
│ │ Flask Application                   │   │
│ │                                     │   │
│ │ ┌───────────────┐  ┌─────────────┐ │   │
│ │ │ Request       │  │ EAS Monitor │ │   │
│ │ │ Handler       │  │ (Daemon     │ │   │
│ │ │ Threads (2)   │  │ Threads)    │ │   │
│ │ │               │  │             │ │   │
│ │ │ /alerts       │  │ Scan 1 ─────┼─┼───┼─► Runs in parallel
│ │ │ /settings     │  │ Scan 2 ─────┼─┼───┼─► Independent
│ │ └───────────────┘  └─────────────┘ │   │
│ │                                     │   │
│ │ BOTH RUN IN PARALLEL               │   │
│ └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### Key Differences

| Aspect | Request Handler Threads | EAS Scan Threads |
|--------|------------------------|------------------|
| Purpose | Handle HTTP requests | Decode SAME audio |
| Count | `--threads` (default: 2) | `MAX_CONCURRENT_EAS_SCANS` (default: 2) |
| Type | GThread pool threads | Daemon threads |
| Blocking | Block on I/O | CPU-intensive |
| Lifespan | Per-request | Long-running |
| Management | Gunicorn | ContinuousEASMonitor |

### Do I Need More Gunicorn Workers?

**Generally, NO.**

Increase Gunicorn workers (`--workers`) if:
- ✅ High HTTP request volume (many users)
- ✅ Request handler threads are saturated
- ✅ Web interface is slow to respond

**Do NOT increase workers for**:
- ❌ Improving EAS scan performance
- ❌ Reducing `scans_skipped`
- ❌ CPU utilization during scans

**Instead, increase** `MAX_CONCURRENT_EAS_SCANS`.

---

## Configuration Examples

### Example 1: Single Gunicorn Worker (Default)

```bash
# .env
MAX_CONCURRENT_EAS_SCANS=2

# Dockerfile
CMD ["gunicorn", "--workers", "1", "--threads", "2", ...]
```

**Result**:
- 1 Flask application instance
- 1 EAS Monitor instance
- 2 concurrent scan threads (max)
- 2 request handler threads

**Total threads**: ~4-6 (2 scans + 2 handlers + overhead)

### Example 2: High-Performance System

```bash
# .env
MAX_CONCURRENT_EAS_SCANS=5

# Dockerfile (unchanged)
CMD ["gunicorn", "--workers", "1", "--threads", "2", ...]
```

**Result**:
- 1 Flask application instance
- 1 EAS Monitor instance
- 5 concurrent scan threads (max)
- 2 request handler threads

**Total threads**: ~7-9 (5 scans + 2 handlers + overhead)

### Example 3: Multi-Worker (NOT Recommended for EAS)

```bash
# .env
MAX_CONCURRENT_EAS_SCANS=2

# Dockerfile
CMD ["gunicorn", "--workers", "2", "--threads", "2", ...]
```

**Result**:
- 2 Flask application instances (separate processes)
- 2 EAS Monitor instances (one per worker)
- 4 concurrent scan threads (2 per worker)
- 4 request handler threads (2 per worker)

**Problems**:
- ❌ Duplicate audio processing (same stream decoded twice)
- ❌ Double CPU usage
- ❌ No benefit for EAS monitoring
- ❌ Complexity in coordination

**Use multi-worker ONLY for**:
- High HTTP request volume (many concurrent users)
- NOT for improving EAS scan performance

---

## Troubleshooting

### "Both my workers are being used for scanning"

**This is a misunderstanding.** 

If you have 2 Gunicorn workers:
- Each worker has its own EAS Monitor
- Each monitor scans the same audio stream independently
- This is **redundant** and wastes resources

**Solution**: Use 1 Gunicorn worker for EAS applications.

### "Scans are skipped frequently"

**Symptoms**:
```
WARNING: Skipping EAS scan #42: 2 scans already active (max=2)
```

**Diagnosis**:
```bash
curl http://localhost:5000/api/eas-monitor/status
# Check: avg_scan_duration_seconds > 3.0
```

**Solutions**:
1. Increase `MAX_CONCURRENT_EAS_SCANS=3` or higher
2. Verify scans complete within 3 seconds
3. Check CPU usage isn't maxed out
4. Consider upgrading hardware

### "Web interface is slow during scans"

**Diagnosis**: EAS scans are CPU-intensive

**Solutions**:
1. Reduce `MAX_CONCURRENT_EAS_SCANS` to free CPU
2. Nice the Flask process: `nice -n 10 gunicorn ...`
3. Limit CPU usage with cgroups (Docker)
4. Upgrade to faster CPU

### "How do I monitor scan performance?"

**API Endpoint**:
```bash
# Real-time status
curl http://localhost:5000/api/eas-monitor/status | jq

# Key metrics
{
  "scans_performed": 1000,
  "scans_skipped": 0,
  "avg_scan_duration_seconds": 1.2,
  "max_scan_duration_seconds": 2.8,
  "active_scans": 1,
  "max_concurrent_scans": 2
}
```

**Logs**:
```bash
docker logs eas_core | grep "EAS scan"
# Look for: "Skipping EAS scan" warnings
```

---

## Recommendations

### Raspberry Pi 4/5

```bash
MAX_CONCURRENT_EAS_SCANS=2
# Gunicorn: --workers 1 --threads 2
```

**Rationale**: Limited CPU, keep it simple

### Desktop/Server (4-8 cores)

```bash
MAX_CONCURRENT_EAS_SCANS=4
# Gunicorn: --workers 1 --threads 4
```

**Rationale**: More CPU available, improve reliability

### High-Performance Server (8+ cores)

```bash
MAX_CONCURRENT_EAS_SCANS=6
# Gunicorn: --workers 1 --threads 4
```

**Rationale**: Maximum reliability, low risk of missed alerts

---

## Summary

1. **`MAX_CONCURRENT_EAS_SCANS`** controls scan threads **per Flask worker**
2. Default: 2 concurrent scans per worker
3. **Does NOT require more Gunicorn workers**
4. Scan threads are daemon threads, not worker processes
5. **One audio stream** is scanned, not three separate streams
6. Monitor scan performance with `/api/eas-monitor/status`
7. Increase limit if `scans_skipped` is high or `avg_scan_duration` > 3s
8. For most systems, `MAX_CONCURRENT_EAS_SCANS=2-4` is sufficient

---

**Last Updated**: 2025-11-21  
**Related Files**:
- `app_core/audio/eas_monitor.py` - Monitor implementation
- `app_core/audio/monitor_manager.py` - Initialization logic
- `.env.example` - Configuration documentation
