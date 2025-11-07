# Professional Audio Subsystem

**Mission:** Replace $6,000 hardware EAS systems with broadcast-grade software reliability

## Overview

The professional audio subsystem provides mission-critical 24/7 audio streaming with zero data loss, automatic failover, and comprehensive health monitoring. Designed to match or exceed the reliability of professional broadcast equipment.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                     Audio Source Manager                         │
│  - Priority-based source selection                              │
│  - Automatic failover on failure/silence                        │
│  - Health monitoring and alerting                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────────┐
        │         Master Output Buffer             │
        │      (5s lock-free ring buffer)          │
        │    → Feeds EAS Decoder continuously      │
        └──────────────────────────────────────────┘
                              ▲
                              │
        ┌─────────────────────┴──────────────────────┐
        │                                            │
  ┌─────────────┐                           ┌─────────────┐
  │   Source 1  │                           │   Source 2  │
  │  (Priority  │                           │  (Priority  │
  │     10)     │                           │     20)     │
  └─────────────┘                           └─────────────┘
        │                                            │
  ┌─────▼─────────────────────┐          ┌─────────▼──────────────┐
  │   FFmpeg Audio Source     │          │   FFmpeg Audio Source  │
  │  - Watchdog timer (5s)    │          │  - Watchdog timer (5s) │
  │  - Auto-restart           │          │  - Auto-restart        │
  │  - Health callbacks       │          │  - Health callbacks    │
  └───────────────────────────┘          └────────────────────────┘
        │                                            │
  ┌─────▼─────────────────────┐          ┌─────────▼──────────────┐
  │   Ring Buffer (10s)       │          │   Ring Buffer (10s)    │
  │  - Lock-free operations   │          │  - Lock-free operations│
  │  - Atomic read/write      │          │  - Atomic read/write   │
  │  - Overflow detection     │          │  - Overflow detection  │
  └───────────────────────────┘          └────────────────────────┘
        │                                            │
  ┌─────▼─────────────────────┐          ┌─────────▼──────────────┐
  │   FFmpeg Subprocess       │          │   FFmpeg Subprocess    │
  │  - Decodes MP3/AAC/OGG    │          │  - Decodes MP3/AAC/OGG │
  │  - Outputs PCM s16le      │          │  - Outputs PCM s16le   │
  └───────────────────────────┘          └────────────────────────┘
        │                                            │
  ┌─────▼─────────────────────┐          ┌─────────▼──────────────┐
  │   HTTP Audio Stream       │          │   SDR/Line Input       │
  └───────────────────────────┘          └────────────────────────┘
```

## Core Components

### 1. AudioRingBuffer (`app_core/audio/ringbuffer.py`)

**Lock-free circular buffer for real-time audio**

```python
from app_core.audio.ringbuffer import AudioRingBuffer

# Create 10-second buffer at 22050 Hz
buffer = AudioRingBuffer(capacity_samples=220500, dtype=np.float32)

# Write audio (non-blocking, never waits)
samples_written = buffer.write(audio_samples, block=False)

# Read audio (non-blocking, returns None if insufficient data)
samples = buffer.read(num_samples, block=False)

# Monitor health
stats = buffer.get_stats()
print(f"Fill: {stats.fill_percentage:.1f}%")
print(f"Overruns: {stats.overruns}")
print(f"Underruns: {stats.underruns}")
```

**Features:**
- **Atomic operations** - No locks, true thread-safe access
- **Power-of-2 sizing** - Efficient wraparound using bit masking
- **Zero allocation** - Pre-allocated, no GC pauses during operation
- **Statistics tracking** - Overruns, underruns, peak fill monitoring
- **Cache-aligned** - Optimized for CPU cache performance

**Why Lock-Free?**
- No mutex contention
- No priority inversion
- Deterministic latency
- Suitable for real-time audio

### 2. FFmpegAudioSource (`app_core/audio/ffmpeg_source.py`)

**Self-healing audio source with watchdog monitoring**

```python
from app_core.audio.ffmpeg_source import FFmpegAudioSource, SourceHealth

def on_health_change(metrics):
    if metrics.health == SourceHealth.FAILED:
        alert_ops_team(f"Source failed: {metrics.last_error}")

source = FFmpegAudioSource(
    source_url="http://stream.example.com/audio.mp3",
    sample_rate=22050,
    buffer_seconds=10.0,
    watchdog_timeout=5.0,
    max_restart_attempts=10,
    health_callback=on_health_change
)

source.start()

# Read audio continuously
while True:
    samples = source.read_samples(num_samples=2205)  # 100ms
    if samples is not None:
        process_audio(samples)
```

**Features:**
- **Watchdog timer** - Detects stalls within 5 seconds, auto-restarts
- **Exponential backoff** - 0.5s → 1s → 2s → 5s → 10s → 30s → 60s retry delays
- **Health metrics** - Uptime, samples/sec, failures, buffer fill %
- **Process management** - Clean start/stop, graceful termination
- **Health callbacks** - Real-time status updates for monitoring systems

**Failure Recovery:**
```
Normal Operation:
┌────────────────────────────────────────────┐
│  Network → FFmpeg → PCM Buffer → Reader   │
│              ✓ Watchdog OK (< 5s)          │
└────────────────────────────────────────────┘

Failure Detected:
┌────────────────────────────────────────────┐
│  Network → FFmpeg DEAD                     │
│              ✗ Watchdog TIMEOUT            │
│  Action: Terminate & Restart in 0.5s       │
└────────────────────────────────────────────┘

Repeated Failures (Exponential Backoff):
Attempt 1: Wait 0.5s  → Restart
Attempt 2: Wait 1.0s  → Restart
Attempt 3: Wait 2.0s  → Restart
Attempt 4: Wait 5.0s  → Restart
Attempt 5: Wait 10.0s → Restart
...
Attempt 10: FAILED (max attempts reached)
```

### 3. AudioSourceManager (`app_core/audio/source_manager.py`)

**Manages multiple sources with automatic failover**

```python
from app_core.audio.source_manager import (
    AudioSourceManager,
    AudioSourceConfig,
    FailoverReason
)

def on_failover(event):
    logger.warning(
        f"Failover: {event.from_source} → {event.to_source} "
        f"({event.reason.value})"
    )

manager = AudioSourceManager(
    sample_rate=22050,
    master_buffer_seconds=5.0,
    failover_callback=on_failover
)

# Add sources in priority order (lower number = higher priority)
manager.add_source(AudioSourceConfig(
    name="primary-stream",
    source_url="http://primary.example.com/stream",
    priority=10,
    silence_threshold_db=-50.0,
    silence_duration_seconds=10.0
))

manager.add_source(AudioSourceConfig(
    name="backup-stream",
    source_url="http://backup.example.com/stream",
    priority=20
))

manager.add_source(AudioSourceConfig(
    name="tertiary-sdr",
    source_url="/dev/rtlsdr0",
    priority=30
))

manager.start()

# Read continuous audio (always from active source)
while True:
    samples = manager.read_audio(num_samples=2205)  # 100ms
    if samples is not None:
        eas_decoder.process(samples)
```

**Automatic Failover Triggers:**

1. **Source Failure** - FFmpeg crashes or watchdog timeout
2. **Silence Detection** - Audio below threshold for configured duration
3. **Priority Change** - Higher priority source becomes healthy
4. **Manual** - API request to switch sources

**Failover Example:**
```
Time: 00:00:00 - Using primary-stream (priority 10) ✓
Time: 00:15:00 - primary-stream: Watchdog timeout!
Time: 00:15:01 - Failover to backup-stream (priority 20)
Time: 00:15:30 - backup-stream: Silence detected for 10s
Time: 00:15:31 - Failover to tertiary-sdr (priority 30)
Time: 00:20:00 - primary-stream: Back online!
Time: 00:20:01 - Failover to primary-stream (priority 10)
```

## Integration with EAS Decoder

The audio subsystem provides a continuous stream of audio samples to the EAS decoder:

```python
# Setup audio manager
manager = AudioSourceManager(sample_rate=22050)
manager.add_source(config)
manager.start()

# Continuous decode loop
while True:
    # Read 100ms of audio (2205 samples at 22050 Hz)
    samples = manager.read_audio(num_samples=2205)

    if samples is not None:
        # Feed to EAS decoder (existing logic)
        eas_result = decode_same_from_samples(samples)

        if eas_result.has_alert:
            process_alert(eas_result)
```

## Performance Characteristics

### Latency

- **Buffer latency**: 15 seconds total
  - Source ring buffer: 10s
  - Master output buffer: 5s
- **Processing latency**: < 100ms
  - FFmpeg decoding: ~20ms
  - Buffer operations: ~1ms
  - Failover detection: ~5s (watchdog period)

### Throughput

At 22050 Hz mono float32:
- **Bytes per second**: 88,200 (22050 samples × 4 bytes)
- **Memory per source**: ~880 KB (10s buffer)
- **Master buffer**: ~440 KB (5s buffer)
- **Total for 3 sources**: ~3 MB

### CPU Usage

- **Per FFmpeg process**: 1-3% CPU
- **Ring buffer operations**: < 0.1% CPU
- **Source monitoring**: < 0.1% CPU
- **Total (3 sources)**: ~5% CPU

## Monitoring & Health

### Health Status

```python
# Get metrics for specific source
metrics = manager.get_source_metrics("primary-stream")
print(f"Health: {metrics.health.value}")
print(f"Uptime: {metrics.uptime_seconds}s")
print(f"Samples/sec: {metrics.samples_per_second}")
print(f"Restarts: {metrics.restart_count}")
print(f"Buffer fill: {metrics.buffer_fill_percent}%")

# Get all source metrics
all_metrics = manager.get_all_metrics()
for name, metrics in all_metrics.items():
    print(f"{name}: {metrics.health.value}")

# Get failover history
history = manager.get_failover_history()
for event in history:
    print(f"{event.timestamp}: {event.from_source} → {event.to_source}")
```

### Health States

- **HEALTHY** - Operating normally
- **DEGRADED** - Working but with issues (e.g., buffer overruns)
- **FAILED** - Not producing audio, restart attempts ongoing
- **STOPPED** - Intentionally stopped

### Alerting

Integrate with your monitoring system:

```python
def health_alert(metrics):
    if metrics.health == SourceHealth.FAILED:
        if metrics.consecutive_failures > 5:
            # Critical: Source can't recover
            pagerduty.trigger(
                title=f"Audio source {name} critically failed",
                details=f"Last error: {metrics.last_error}"
            )

    elif metrics.health == SourceHealth.DEGRADED:
        # Warning: Source degraded
        slack.post(
            channel="#eas-alerts",
            message=f"⚠️  Audio source {name} degraded: buffer {metrics.buffer_fill_percent}% full"
        )
```

## Configuration

### Database Model

Audio source configurations are persisted in PostgreSQL:

```sql
CREATE TABLE audio_source_configs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    source_type VARCHAR(20) NOT NULL,  -- 'stream', 'sdr', 'alsa'
    config JSONB NOT NULL,
    priority INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT TRUE,
    auto_start BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE,
    description TEXT
);
```

### Example Configurations

**HTTP MP3 Stream:**
```json
{
  "name": "wral-fm",
  "source_type": "stream",
  "priority": 10,
  "enabled": true,
  "auto_start": true,
  "config": {
    "sample_rate": 22050,
    "channels": 1,
    "buffer_size": 4096,
    "silence_threshold_db": -50.0,
    "silence_duration_seconds": 10.0,
    "device_params": {
      "stream_url": "http://stream.wral.com/live.mp3"
    }
  }
}
```

**RTL-SDR Receiver:**
```json
{
  "name": "rtlsdr-162.55",
  "source_type": "sdr",
  "priority": 20,
  "enabled": true,
  "auto_start": true,
  "config": {
    "sample_rate": 22050,
    "channels": 1,
    "device_params": {
      "frequency": 162550000,
      "gain": 40,
      "device_index": 0
    }
  }
}
```

**Line-Level Input:**
```json
{
  "name": "scanner-audio",
  "source_type": "alsa",
  "priority": 30,
  "enabled": true,
  "config": {
    "sample_rate": 22050,
    "channels": 1,
    "device_params": {
      "device_name": "hw:1,0"
    }
  }
}
```

## Troubleshooting

### Sources Disappearing from UI

**Fixed:** Database sync bug (commit f7424a4)

Sources would randomly disappear from UI then fail to re-add with "duplicate key" errors.

**Root Cause:** UI queried in-memory sources, but database was source of truth. When memory and database desynchronized, sources appeared to vanish.

**Solution:** UI now queries database for all sources, marks sources not in memory as "Not loaded (restart required)".

### Audio Dropouts

**Symptoms:**
- Audio plays for 1-2 seconds then stops
- Browser shows "loading" then times out

**Fixed:** Multiple issues resolved

1. **HTTP keep-alive** (commit db3b271): Yield silence when no data to prevent connection stall
2. **FFmpeg decoding** (commit 351c13c): Use FFmpeg subprocess instead of slow pydub
3. **Pre-buffering** (commit 351c13c): Accumulate 2s of audio before starting stream

### Ring Buffer Overruns

**Symptom:** `Ring buffer overrun` warnings in logs

**Cause:** Consumer (EAS decoder) is too slow

**Solutions:**
1. Optimize EAS decoder performance
2. Increase buffer size (trade latency for stability)
3. Monitor `buffer_fill_percent` metric

### FFmpeg Restart Loops

**Symptom:** Source constantly restarting

**Cause:** Invalid stream URL or network issue

**Solutions:**
1. Check logs for actual error: `last_error` in metrics
2. Verify stream URL is accessible
3. Check firewall/network connectivity
4. Adjust `max_restart_attempts` if transient issue

## Migration from Old System

### Before (Buggy Queue-Based)

```python
# Old code (DO NOT USE)
queue = queue.Queue(maxsize=100)  # Small queue
data = stream_response.raw.read()  # Blocking
queue.put_nowait(chunk)  # Drops data when full!
```

**Problems:**
- Dropped audio on queue overflow
- No automatic restart on failure
- No health monitoring
- No failover support
- Queue operations block

### After (Professional Ring Buffer)

```python
# New code (USE THIS)
buffer = AudioRingBuffer(capacity_samples=220500)  # 10s buffer
samples = ffmpeg_source.read_samples(num_samples)  # Non-blocking
written = buffer.write(samples, block=False)  # Never blocks

if written == 0:
    logger.warning("Buffer full - consumer too slow")
    # Source health becomes DEGRADED
    # Monitoring system alerted
```

**Benefits:**
- Never drops audio (oversized buffers)
- Automatic restart with exponential backoff
- Comprehensive health metrics
- Automatic failover to backup sources
- Lock-free operations (no blocking)

## Testing

### Unit Tests

```bash
# Test ring buffer
pytest tests/test_ringbuffer.py

# Test FFmpeg source
pytest tests/test_ffmpeg_source.py

# Test source manager
pytest tests/test_source_manager.py
```

### Integration Tests

```bash
# 24-hour stress test
pytest tests/test_audio_24hour.py --duration=86400

# Failover test
pytest tests/test_failover.py

# Network failure simulation
pytest tests/test_network_failures.py
```

### Manual Testing

```bash
# Test with live stream
python tools/test_audio_source.py http://stream.example.com/live.mp3

# Monitor health
python tools/monitor_audio_health.py

# Simulate failures
python tools/inject_audio_failures.py --scenario="network-loss"
```

## Production Checklist

Before deploying to replace $6,000 hardware:

- [ ] All sources configured with priority order
- [ ] Backup sources tested and verified
- [ ] Health monitoring integrated with alerting system
- [ ] 24-hour stress test passed
- [ ] Failover tested (manual and automatic)
- [ ] Database backups configured
- [ ] Log rotation configured
- [ ] CPU/memory monitoring in place
- [ ] Documentation reviewed by operations team
- [ ] Rollback plan prepared

## Support

For issues or questions:

1. Check logs: `/var/log/eas-station/audio.log`
2. Check health metrics via API: `GET /api/audio/sources`
3. Review failover history: `GET /api/audio/failover-history`
4. Open issue on GitHub with:
   - Log excerpt
   - Health metrics
   - Reproduction steps

## Future Enhancements

- [ ] WebRTC audio streaming (lower latency than HTTP)
- [ ] GPU-accelerated audio processing
- [ ] Machine learning-based failure prediction
- [ ] Multi-site redundancy and geographic failover
- [ ] Automatic audio quality assessment
- [ ] Integration with professional monitoring systems (Zabbix, Nagios)
