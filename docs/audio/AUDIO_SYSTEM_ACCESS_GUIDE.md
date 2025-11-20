# Audio System Access Guide

## Quick Navigation Reference

This guide provides direct links to all audio system components created in the professional audio subsystem build.

---

## 🎯 User Interface Pages

### 1. **Audio Health Dashboard**
**URL:** `/audio/health/dashboard`

**Navigation:** Monitoring → Audio Health Dashboard

**Features:**
- Real-time health score (0-100) with color indicators
- Source-by-source health status
- Buffer fill level charts
- Restart count monitoring
- Auto-refresh every 5 seconds

**What it shows:**
- Healthy sources (green) - running and producing audio
- Degraded sources (yellow) - running but silent or intermittent
- Failed sources (red) - stopped or crashed

---

### 2. **Audio Monitoring** (Existing)
**URL:** `/audio-monitor`

**Navigation:** Monitoring → Audio Monitoring

**Features:**
- Live waveform/waterfall visualization
- Real-time audio playback
- Source switching
- Audio levels

---

### 3. **Audio Archive** (Existing)
**URL:** `/audio-history` (via `url_for('audio_history')`)

**Navigation:** Monitoring → Audio Archive

**Features:**
- Historical audio recordings
- Alert audio files
- Playback and download

---

## 🔧 API Endpoints

### Health Monitoring APIs

#### `/api/audio/health/dashboard` [GET]
Returns comprehensive health dashboard data:
```json
{
  "overall_health_score": 85.5,
  "active_source": "primary-stream",
  "categorized_sources": {
    "healthy": ["primary-stream"],
    "degraded": [],
    "failed": []
  },
  "source_health": {
    "primary-stream": {
      "status": "healthy",
      "uptime_seconds": 3600,
      "buffer_fill_percentage": 45.2,
      "restart_count": 0,
      "is_silent": false,
      "error_message": null
    }
  }
}
```

#### `/api/audio/health/metrics` [GET]
Returns real-time metrics for all sources with detailed statistics.

---

### Audio Source Management APIs

#### `/api/audio/sources` [GET]
List all audio sources with status

#### `/api/audio/sources` [POST]
Add new audio source
```json
{
  "name": "my-stream",
  "source_url": "http://example.com/stream.mp3",
  "priority": 10,
  "enabled": true,
  "sample_rate": 22050
}
```

#### `/api/audio/sources/<source_name>` [GET]
Get specific source details

#### `/api/audio/sources/<source_name>` [PATCH]
Update source configuration

#### `/api/audio/sources/<source_name>` [DELETE]
Remove audio source

#### `/api/audio/sources/<source_name>/start` [POST]
Start an audio source

#### `/api/audio/sources/<source_name>/stop` [POST]
Stop an audio source

---

### Audio Data APIs

#### `/api/audio/stream/<source_name>` [GET]
Live audio stream (PCM, 22050 Hz mono)
- Returns continuous audio data
- Keeps HTTP connection alive
- VLC-style pre-buffering

#### `/api/audio/waveform/<source_name>` [GET]
Get waveform data for visualization

#### `/api/audio/spectrogram/<source_name>` [GET]
Get waterfall spectrogram data

---

### Icecast Configuration APIs

#### `/api/audio/icecast/config` [GET]
Get current Icecast configuration

#### `/api/audio/icecast/config` [POST]
Update Icecast configuration
```json
{
  "server": "localhost",
  "port": 8000,
  "password": "hackme",
  "mount": "eas-monitor.mp3",
  "name": "EAS Monitor",
  "bitrate": 128
}
```

---

## 📁 Code Components

### Core Modules

#### `app_core/audio/ringbuffer.py`
Lock-free circular buffer for zero-loss audio transfer
- Thread-safe without locks
- Atomic operations
- Overflow/underrun detection

#### `app_core/audio/ffmpeg_source.py`
Self-healing audio source with watchdog monitoring
- 5-second watchdog timeout
- Automatic restart with exponential backoff
- Health callbacks

#### `app_core/audio/source_manager.py`
Multi-source manager with priority-based failover
- Automatic source selection
- Silence detection
- Failover events
- Master buffer

#### `app_core/audio/eas_monitor.py`
Continuous EAS monitoring service
- 120-second rolling buffer
- 2-second scan interval
- Alert detection and callbacks
- Audio archiving

#### `app_core/audio/icecast_output.py`
Icecast streaming output
- FFmpeg-based encoding
- MP3/OGG support
- Automatic reconnection
- Metadata updates

---

## 🚀 Example Scripts

### `examples/run_continuous_eas_monitor.py`
Complete working example showing:
- AudioSourceManager setup
- Multiple sources with failover
- Continuous EAS monitoring
- Alert callbacks
- Status reporting

**Usage:**
```bash
cd /home/user/eas-station
python3 examples/run_continuous_eas_monitor.py
```

### `examples/run_with_icecast_streaming.py`
Complete integration example showing:
- AudioSourceManager
- EAS monitoring
- Icecast streaming
- All three systems working together

**Usage:**
```bash
cd /home/user/eas-station
python3 examples/run_with_icecast_streaming.py
```

**Note:** Update the stream URLs and Icecast credentials in the examples before running.

---

## 🧪 Test Suites

### `tests/test_audio_ringbuffer.py`
21 comprehensive tests for ring buffer:
- Basic read/write operations
- Wraparound handling
- Overflow/underflow behavior
- Thread safety
- Statistics tracking

**Run tests:**
```bash
cd /home/user/eas-station
pytest tests/test_audio_ringbuffer.py -v
```

### `tests/test_audio_source_manager.py`
12 integration tests for source manager:
- Multi-source management
- Priority-based selection
- Automatic failover
- Concurrent readers
- Health monitoring

**Run tests:**
```bash
cd /home/user/eas-station
pytest tests/test_audio_source_manager.py -v
```

**Run all audio tests:**
```bash
cd /home/user/eas-station
pytest tests/test_audio*.py -v
```

---

## 📖 Documentation

### Main Documentation Files

1. **`docs/PROFESSIONAL_AUDIO_SUBSYSTEM.md`**
   - Complete architecture overview
   - Component descriptions
   - Performance benchmarks
   - Troubleshooting guide

2. **`docs/CHANGELOG_2025-11-07.md`**
   - Detailed changelog of all work done
   - Before/after comparisons
   - File-by-file changes

3. **`docs/AUDIO_SYSTEM_ACCESS_GUIDE.md`** (this file)
   - Quick navigation reference
   - All URLs and endpoints
   - Example usage

---

## 🎛️ How to Use

### Starting the System

1. **Start the web application:**
   ```bash
   cd /home/user/eas-station
   python3 main.py
   ```

2. **Access the Health Dashboard:**
   - Navigate to: http://localhost:5000/audio/health/dashboard
   - Or use: Monitoring → Audio Health Dashboard

3. **Add Audio Sources:**
   - Via API: POST to `/api/audio/sources`
   - Or programmatically using `AudioSourceManager.add_source()`

4. **Monitor System Health:**
   - Watch the dashboard for real-time updates
   - Check buffer fill levels
   - Monitor restart counts
   - Verify active source

---

## 🔍 Key Features Summary

### What Makes This Professional-Grade

1. **Lock-Free Ring Buffers**
   - Zero mutex locks
   - Atomic operations only
   - No blocking on audio thread

2. **Self-Healing Sources**
   - Watchdog monitoring (5s timeout)
   - Automatic restart
   - Exponential backoff (0.5s → 60s)

3. **Intelligent Failover**
   - Priority-based (lower number = higher priority)
   - Health monitoring
   - Automatic source switching
   - Failover event callbacks

4. **VLC-Style Streaming**
   - 2-second pre-buffering
   - HTTP keep-alive
   - Smooth playback start

5. **24/7 Operation**
   - Designed for continuous operation
   - No manual intervention required
   - Automatic recovery from failures

---

## 🆘 Troubleshooting

### Health Dashboard Shows "Failed" Sources

1. Check source URL is accessible
2. Verify FFmpeg is installed: `ffmpeg -version`
3. Check logs: `/logs` page or console output
4. Try restarting the source via API

### No Audio in Stream

1. Check active source: dashboard or `/api/audio/health/metrics`
2. Verify buffer fill > 0%
3. Check if source is silent (silence detection)
4. Test stream URL manually: `ffplay <url>`

### Icecast Not Streaming

1. Verify Icecast server is running
2. Check credentials in config
3. Test connection: `curl http://server:port/mount`
4. Check Icecast logs

---

## 📞 Support

For issues or questions:
1. Check `docs/PROFESSIONAL_AUDIO_SUBSYSTEM.md` troubleshooting section
2. Review logs via `/logs` page
3. Check GitHub issues: https://github.com/KR8MER/eas-station/issues
