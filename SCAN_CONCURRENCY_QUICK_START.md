# EAS Scan Concurrency - Quick Start Guide

## What Changed?

The EAS monitoring system now has **configurable concurrent scan limits** and **performance metrics** to help you optimize alert detection.

---

## Quick Answer to Your Questions

### Q1: "Only 2 scans simultaneously... Is this correct?"

**✅ Yes, by default** - but now you can change it!

- **Default**: 2 concurrent scans
- **Why**: Balances CPU usage with detection reliability
- **Can be changed**: Set `MAX_CONCURRENT_EAS_SCANS` to any value

### Q2: "Is there a way to measure how long a scan takes?"

**✅ Yes!** Check the new metrics:

```bash
curl http://localhost:5000/api/eas-monitor/status | jq
```

You'll see:
```json
{
  "avg_scan_duration_seconds": 1.2,
  "min_scan_duration_seconds": 0.8,
  "max_scan_duration_seconds": 2.5,
  "scans_performed": 1234,
  "scans_skipped": 5
}
```

### Q3: "There are 3 simultaneous streams... is the limit across all 3?"

**No** - There's only ONE stream being scanned:
- Your 3 audio sources are **mixed into ONE stream**
- EAS Monitor scans **that one stream**
- The limit applies to threads scanning **the same buffer**
- **Not** 2 scans per stream (that would be 6 total)

### Q4: "Does increasing this require more workers?"

**No** - Scan threads are separate from Gunicorn workers:
- Scans run in **daemon threads**
- Workers run in **processes**
- They're independent
- Just change `MAX_CONCURRENT_EAS_SCANS`, not `--workers`

---

## How to Check If You Need to Increase the Limit

### Step 1: Check Current Performance

```bash
curl http://localhost:5000/api/eas-monitor/status | jq '{
  avg_scan_duration_seconds,
  scans_performed,
  scans_skipped,
  active_scans,
  max_concurrent_scans
}'
```

### Step 2: Look for Warning Signs

🚨 **You should increase the limit if:**
- `scans_skipped` > 0 (scans are being dropped)
- `avg_scan_duration_seconds` > 3.0 (scans take too long)
- You see warnings in logs: `"Skipping EAS scan: X scans already active"`

✅ **You're fine if:**
- `scans_skipped` = 0
- `avg_scan_duration_seconds` < 3.0
- No warnings in logs

### Step 3: Increase If Needed

**Add to `.env` file:**
```bash
MAX_CONCURRENT_EAS_SCANS=4
```

**Restart:**
```bash
docker compose restart eas_core
```

**Verify:**
```bash
curl http://localhost:5000/api/eas-monitor/status | jq .max_concurrent_scans
# Should show: 4
```

---

## Recommended Values

| Hardware | Recommended Value |
|----------|-------------------|
| Raspberry Pi 4/5 | 2 (default) |
| Desktop (4 cores) | 3-4 |
| Server (8+ cores) | 4-6 |
| High-performance | 6-8 |

**Start with default (2)** and only increase if you see `scans_skipped` > 0.

---

## Monitoring Commands

### Real-time Status
```bash
watch -n 5 'curl -s http://localhost:5000/api/eas-monitor/status | jq "{scans_performed, scans_skipped, avg_duration: .avg_scan_duration_seconds, active: .active_scans}"'
```

### Check Logs for Warnings
```bash
docker logs eas_core | grep "Skipping EAS scan"
```

### Full Status with All Metrics
```bash
curl http://localhost:5000/api/eas-monitor/status | jq
```

---

## Understanding the Numbers

### `avg_scan_duration_seconds`
- **What it means**: How long each scan takes on average
- **Good**: < 1.5 seconds
- **OK**: 1.5-3.0 seconds
- **Bad**: > 3.0 seconds (scans can't keep up)

### `scans_skipped`
- **What it means**: How many scans were skipped due to concurrency limit
- **Good**: 0
- **OK**: 1-5 (occasional)
- **Bad**: > 10 (frequent, increase limit)

### `active_scans`
- **What it means**: How many scans are running right now
- **Good**: 0-1 (scans complete quickly)
- **OK**: 1-2 (normal load)
- **Bad**: Always at `max_concurrent_scans` (scans piling up)

---

## Example Scenarios

### Scenario 1: Everything is Fine ✅

```json
{
  "avg_scan_duration_seconds": 1.2,
  "scans_performed": 1000,
  "scans_skipped": 0,
  "active_scans": 0,
  "max_concurrent_scans": 2
}
```

**Action**: None needed! System is working optimally.

### Scenario 2: Scans Taking Too Long ⚠️

```json
{
  "avg_scan_duration_seconds": 4.5,
  "scans_performed": 500,
  "scans_skipped": 45,
  "active_scans": 2,
  "max_concurrent_scans": 2
}
```

**Action**: Increase limit to 4-5
```bash
# Add to .env
MAX_CONCURRENT_EAS_SCANS=5

# Restart
docker compose restart eas_core
```

### Scenario 3: Hardware Too Slow 🐌

```json
{
  "avg_scan_duration_seconds": 8.0,
  "scans_performed": 200,
  "scans_skipped": 150,
  "active_scans": 2,
  "max_concurrent_scans": 2
}
```

**Action**: Either:
1. Increase limit to 6-8 (if you have spare CPU)
2. Consider upgrading hardware (scans are very slow)

---

## FAQ

### Will increasing the limit slow down the web interface?

**Maybe slightly**, but probably not noticeably:
- Each scan uses 5-15% CPU
- With `max_concurrent_scans=4`, expect 20-60% CPU during scanning
- Web interface runs in separate threads
- On modern multi-core CPUs, impact is minimal

### What's the maximum safe value?

**Depends on your CPU**:
- Raspberry Pi: 2-3
- Desktop (4 cores): 4-6
- Server (8+ cores): 6-10

**Rule of thumb**: Don't exceed your CPU core count.

### Will this use more memory?

**Yes, but minimally**:
- Each scan holds a 12-second audio buffer (~1MB)
- `max_concurrent_scans=4` = ~4MB extra memory
- Negligible on modern systems

### Can I set it too high?

**Yes**:
- Too many scans = high CPU usage
- Web interface may become slow
- System may become unresponsive
- **Start conservative**, increase only if needed

---

## Troubleshooting

### "I increased the limit but still see skipped scans"

**Possible causes**:
1. Scans take > 3 seconds each (check `avg_scan_duration_seconds`)
2. CPU is maxed out (check with `top` or `htop`)
3. Need to increase limit more

**Solution**: Keep increasing until `scans_skipped` stops growing.

### "Web interface is slow after increasing limit"

**Possible causes**:
1. Limit set too high for your CPU
2. CPU is overloaded

**Solution**: Reduce `MAX_CONCURRENT_EAS_SCANS` back to 2-3.

### "The metrics aren't updating"

**Check**:
1. EAS monitor is running: `curl http://localhost:5000/api/eas-monitor/status | jq .running`
2. Should show: `true`
3. If `false`, check logs: `docker logs eas_core | grep EAS`

---

## Need More Details?

See the full architecture documentation:
```bash
cat /app/docs/EAS_SCAN_CONCURRENCY_ARCHITECTURE.md
```

Or online: [EAS_SCAN_CONCURRENCY_ARCHITECTURE.md](docs/EAS_SCAN_CONCURRENCY_ARCHITECTURE.md)

---

**Last Updated**: 2025-11-21  
**Version**: 1.0  
**Related**: See `.env.example` for configuration details
