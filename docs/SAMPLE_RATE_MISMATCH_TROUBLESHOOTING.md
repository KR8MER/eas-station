# Sample Rate Mismatch Troubleshooting

## Symptom

Monitor shows < 100% health and "warming up" even after running for >10 minutes:

```
Decoder Health: 91.7%
Status: ⚪ Warming up...
Sample Rate: 8.0 kHz
Processing Rate: 7.3k samples/sec  ← Should match sample rate!
Runtime: 11m
```

## Root Cause

**Sample rate mismatch** between Audio Manager and EAS Monitor.

The monitor is configured for one sample rate (e.g., 8kHz) but the audio source is providing samples at a different rate (e.g., 16kHz), causing underruns or slowdowns.

## Diagnosis

### Check Configuration Mismatch

1. **Check Monitor Sample Rate**:
   ```python
   # In code or logs
   ContinuousEASMonitor(sample_rate=8000, ...)
   ```

2. **Check Audio Manager Sample Rate**:
   ```python
   # In code or logs  
   AudioSourceManager(sample_rate=16000, ...)
   ```

3. **Check Environment Variable**:
   ```bash
   echo $EAS_SAMPLE_RATE
   # or in .env file
   grep EAS_SAMPLE_RATE .env
   ```

### Expected vs Actual

**Healthy system**:
```
Sample Rate: 16.0 kHz
Processing Rate: 16.0k samples/sec
Health: 100%
Status: ✓ Processing at line rate
```

**Mismatched system**:
```
Sample Rate: 8.0 kHz       ← Monitor expects 8kHz
Processing Rate: 7.3k samples/sec  ← Getting ~91% of expected
Health: 91.7%              ← Not reaching line rate
Status: ⚪ Warming up...   ← Never reaches 95% threshold
```

## Solutions

### Solution 1: Match Sample Rates (Recommended)

Ensure **both** Audio Manager and EAS Monitor use the **same sample rate**.

**For 16kHz (recommended)**:
```python
# Audio Manager
manager = AudioSourceManager(
    sample_rate=16000,  # ← Set here
    ...
)

# EAS Monitor
monitor = ContinuousEASMonitor(
    audio_manager=manager,
    sample_rate=16000,  # ← Must match
    ...
)
```

**For 8kHz (constrained devices)**:
```python
# Audio Manager
manager = AudioSourceManager(
    sample_rate=8000,   # ← Set here
    ...
)

# EAS Monitor
monitor = ContinuousEASMonitor(
    audio_manager=manager,
    sample_rate=8000,   # ← Must match
    ...
)
```

### Solution 2: Use Environment Variable

Set `EAS_SAMPLE_RATE` once and use it everywhere:

**.env file**:
```bash
EAS_SAMPLE_RATE=16000
```

**Python code**:
```python
import os

sample_rate = int(os.getenv('EAS_SAMPLE_RATE', '16000'))

manager = AudioSourceManager(
    sample_rate=sample_rate,
    ...
)

monitor = ContinuousEASMonitor(
    audio_manager=manager,
    sample_rate=sample_rate,
    ...
)
```

### Solution 3: Check Audio Source Configuration

If using audio sources (radio, file, stream), ensure they match:

```python
# Bad - Mismatch
manager = AudioSourceManager(sample_rate=16000)
source_config = AudioSourceConfig(
    name="radio1",
    sample_rate=8000,  # ← Mismatch!
    ...
)

# Good - Matched
manager = AudioSourceManager(sample_rate=16000)
source_config = AudioSourceConfig(
    name="radio1",
    sample_rate=16000,  # ← Matches manager
    ...
)
```

## Why 91.7% Specifically?

If you see exactly **91.7%** or close to it:

```
91.7% = 7.3k / 8.0k = 0.9125
```

This suggests:
- Monitor configured for 8000 Hz
- Audio actually at ~16000 Hz with some resampling/buffering loss
- Effective rate: 16000 × 0.458 ≈ 7333 Hz

The audio subsystem is trying to provide samples but there's a rate conversion bottleneck.

## How Resampling Affects This

If Audio Manager is at 16kHz but Monitor expects 8kHz:

1. Audio Manager produces 16,000 samples/sec
2. EAS Monitor requests at 8,000 samples/sec rate
3. Buffering/resampling happens
4. Timing gets slightly off
5. Effective rate drops below expected

**Solution**: Don't rely on automatic resampling - **match rates explicitly**.

## Verification Steps

After fixing:

1. **Restart both services**:
   ```python
   manager.stop()
   monitor.stop()
   # Apply configuration changes
   manager.start()
   monitor.start()
   ```

2. **Wait 30 seconds** (not 10+ minutes - should stabilize quickly)

3. **Check status**:
   ```
   Sample Rate: 16.0 kHz
   Processing Rate: 16.0k samples/sec  ← Should match exactly!
   Health: 100%
   Status: ✓ Processing at line rate (16.00 kHz)
   ```

4. **Verify samples increase correctly**:
   ```
   At T+0s:  Samples: 0
   At T+10s: Samples: 160,000  (16k × 10)
   At T+60s: Samples: 960,000  (16k × 60)
   ```

## Common Mistakes

### ❌ Different Rates in Code
```python
manager = AudioSourceManager(sample_rate=16000)
monitor = ContinuousEASMonitor(
    audio_manager=manager,
    sample_rate=8000,  # ← WRONG - doesn't match manager
)
```

### ❌ Forgetting Audio Source Rate
```python
manager = AudioSourceManager(sample_rate=16000)
# ... later ...
source = AudioSourceConfig(
    name="radio",
    sample_rate=22050,  # ← WRONG - doesn't match manager
)
manager.add_source(source)
```

### ❌ Environment Variable Not Used
```python
# .env has EAS_SAMPLE_RATE=16000
# But code doesn't read it:
manager = AudioSourceManager(sample_rate=8000)  # ← Ignores .env
```

## Best Practices

### 1. Single Source of Truth
```python
# config.py
SAMPLE_RATE = int(os.getenv('EAS_SAMPLE_RATE', '16000'))

# Use everywhere
manager = AudioSourceManager(sample_rate=SAMPLE_RATE)
monitor = ContinuousEASMonitor(sample_rate=SAMPLE_RATE, ...)
```

### 2. Validation on Startup
```python
if manager.sample_rate != monitor.sample_rate:
    raise ValueError(
        f"Sample rate mismatch: Manager={manager.sample_rate}, "
        f"Monitor={monitor.sample_rate}. These must match!"
    )
```

### 3. Log Rates on Startup
```python
logger.info(f"Audio Manager sample rate: {manager.sample_rate} Hz")
logger.info(f"EAS Monitor sample rate: {monitor.sample_rate} Hz")
if manager.sample_rate != monitor.sample_rate:
    logger.error("⚠️ SAMPLE RATE MISMATCH DETECTED!")
```

### 4. Use Recommended Defaults
```python
# Don't specify if you don't need to
manager = AudioSourceManager()  # Uses 16000 Hz default
monitor = ContinuousEASMonitor(audio_manager=manager)  # Uses 16000 Hz default
```

## Why Health Never Reaches 100%

The "warming up" threshold is **95%**:

```python
if status.health_percentage >= 0.95:  # 95% threshold
    bufferStatus.innerHTML = '✓ Processing at line rate';
else if (status.health_percentage >= 0.5):
    bufferStatus.innerHTML = '⚪ Warming up...';
```

If health is stuck at 91.7%:
- 91.7% < 95% threshold
- Never shows "Processing at line rate"
- Always shows "Warming up..."

**Solution**: Fix sample rate mismatch → health reaches 100% → shows correct status.

## Related Issues

- Low confidence alerts → Check sample rate matches audio
- Missed alerts → Check health is 100%
- High CPU → Check no unnecessary resampling
- Buffer underruns → Check rates match

## Quick Fix Commands

### Check Current Rates
```bash
# In Docker
docker exec eas-station grep EAS_SAMPLE_RATE /app/.env

# In logs
docker logs eas-station | grep "sample rate"
```

### Fix in Docker
```bash
# Edit .env
nano .env
# Set: EAS_SAMPLE_RATE=16000

# Restart
docker-compose restart
```

### Fix in Systemd
```bash
# Edit service
sudo systemctl edit eas-station
# Add: Environment="EAS_SAMPLE_RATE=16000"

# Restart
sudo systemctl restart eas-station
```

## Summary

**Problem**: Sample rate mismatch between Audio Manager and EAS Monitor  
**Symptom**: Health stuck at ~91%, "warming up" forever  
**Solution**: Ensure both use the same sample rate (recommended: 16000 Hz)  
**Verification**: Health reaches 100%, status shows "Processing at line rate"
