# Audio Ingest System Frontend UI - Implementation Plan

## Overview

The audio ingest system has a **fully functional backend** but lacks a user-facing interface. This document outlines the implementation plan for exposing the audio ingest functionality through the web UI.

## Current State

### ✅ Backend (Complete)
- **Core Files:**
  - `app_core/audio/ingest.py` - AudioIngestController with multi-source management
  - `app_core/audio/sources.py` - Four audio source adapters (SDR, ALSA, PulseAudio, File)
  - `app_core/audio/metering.py` - AudioMeter, SilenceDetector, AudioHealthMonitor

- **Database Models:**
  - `AudioSourceMetrics` - Real-time audio metrics (peak, RMS, sample rate, channels, silence status)
  - `AudioHealthStatus` - Health scores (0-100), uptime, silence duration

- **Features:**
  - Multi-source audio ingestion
  - Real-time metering and analysis
  - Silence detection with configurable thresholds
  - Health monitoring with scoring
  - Alert callbacks for critical events

### ❌ Frontend (Missing)
- No real-time audio source monitoring dashboard
- No live peak/RMS metering visualization
- No silence detection alerts in UI
- No health status dashboard
- No audio ingest pipeline control UI
- No audio device discovery/configuration UI
- No API endpoints for metrics retrieval

## Implementation Plan

### Phase 1: API Endpoints (Priority: High)

Create REST API endpoints in `webapp/admin/api.py`:

#### 1.1 Audio Sources Management
```python
@app.route('/api/audio/sources', methods=['GET'])
def api_get_audio_sources():
    """List all configured audio sources"""
    # Return list of audio sources with their configurations

@app.route('/api/audio/sources', methods=['POST'])
def api_create_audio_source():
    """Create a new audio source"""
    # Accept: type (sdr/alsa/pulseaudio/file), configuration params
    # Return: source ID and status

@app.route('/api/audio/sources/<source_id>', methods=['PATCH'])
def api_update_audio_source(source_id):
    """Update audio source configuration"""

@app.route('/api/audio/sources/<source_id>', methods=['DELETE'])
def api_delete_audio_source(source_id):
    """Delete an audio source"""

@app.route('/api/audio/sources/<source_id>/start', methods=['POST'])
def api_start_audio_source(source_id):
    """Start audio ingestion from a source"""

@app.route('/api/audio/sources/<source_id>/stop', methods=['POST'])
def api_stop_audio_source(source_id):
    """Stop audio ingestion from a source"""
```

#### 1.2 Audio Metrics & Monitoring
```python
@app.route('/api/audio/metrics', methods=['GET'])
def api_get_audio_metrics():
    """Get real-time metrics for all audio sources"""
    # Query AudioSourceMetrics table
    # Return: peak, RMS, sample rate, channels, silence status per source

@app.route('/api/audio/health', methods=['GET'])
def api_get_audio_health():
    """Get audio system health status"""
    # Query AudioHealthStatus table
    # Return: health scores, uptime, silence duration, active sources

@app.route('/api/audio/devices', methods=['GET'])
def api_discover_audio_devices():
    """Discover available audio input devices"""
    # Use ALSA/PulseAudio to enumerate devices
    # Return: list of available devices with names and IDs
```

### Phase 2: Frontend Templates (Priority: High)

Create audio ingestion management page at `templates/settings/audio.html`:

#### 2.1 Page Structure
```html
{% extends "base.html" %}

Sections:
1. Audio Health Overview Cards
   - Overall health score (0-100)
   - Active sources count
   - Total uptime
   - Silence alerts count

2. Active Audio Sources Table
   - Source name and type
   - Status (running/stopped/error)
   - Live metering (peak/RMS bars)
   - Signal strength indicator
   - Controls (start/stop/edit/delete)

3. Audio Device Discovery
   - "Discover Devices" button
   - List of detected ALSA/PulseAudio devices
   - Quick "Add Source" action per device

4. Add/Edit Audio Source Modal
   - Source type selector (SDR/ALSA/PulseAudio/File)
   - Configuration form (device ID, sample rate, etc.)
   - Test/preview functionality
```

#### 2.2 Real-time Monitoring JavaScript
Create `static/js/audio_monitoring.js`:

```javascript
// Auto-refresh metrics every 1 second
setInterval(async () => {
    const metrics = await fetch('/api/audio/metrics').then(r => r.json());
    updateMeteringBars(metrics);
    updateHealthIndicators(metrics);
}, 1000);

// Functions:
- updateMeteringBars() - Update peak/RMS progress bars
- updateHealthIndicators() - Update health scores and status badges
- handleSilenceAlert() - Show toast notification for silence detection
- renderAudioDevices() - Populate device discovery list
- startAudioSource() - API call to start ingestion
- stopAudioSource() - API call to stop ingestion
```

#### 2.3 Visualization Components
- **Peak/RMS Meters**: Horizontal progress bars with color gradients
  - Green: Normal level (-40 to -10 dBFS)
  - Yellow: High level (-10 to -3 dBFS)
  - Red: Clipping risk (> -3 dBFS)
- **Health Score**: Circular progress indicator (0-100%)
- **Silence Detection**: Warning badge with duration counter
- **Waveform Preview**: Optional real-time waveform display (using Canvas API)

### Phase 3: Integration (Priority: Medium)

#### 3.1 Admin Navigation
Add "Audio Sources" link in admin panel:
```html
<a href="/settings/audio" class="nav-link">
    <i class="fas fa-microphone"></i> Audio Sources
</a>
```

#### 3.2 Dashboard Widget
Add audio health summary to main dashboard (`templates/index.html`):
```html
<div class="metric-card">
    <div class="metric-label">Audio System</div>
    <div class="metric-value" id="audio-health">
        98<span class="metric-unit">%</span>
    </div>
    <div class="status-indicator">
        <span class="status-dot status-dot-success"></span>
        <span>3 sources active</span>
    </div>
</div>
```

### Phase 4: Advanced Features (Priority: Low)

#### 4.1 Audio Recording Management
- View recorded audio segments
- Playback interface
- Export functionality

#### 4.2 Alert Configuration
- Configure silence detection thresholds
- Set up notifications for audio issues
- Define health score alert levels

#### 4.3 Audio Analysis
- Spectrum analyzer visualization
- SNR (Signal-to-Noise Ratio) measurements
- Audio quality metrics

## Database Schema (Already Exists)

### AudioSourceMetrics Table
- `id`: Primary key
- `source_id`: Audio source identifier
- `timestamp`: Metric timestamp
- `peak_level`: Peak audio level (dBFS)
- `rms_level`: RMS level (dBFS)
- `sample_rate`: Current sample rate
- `channels`: Number of channels
- `silence_detected`: Boolean flag
- `silence_duration`: Duration of silence (seconds)

### AudioHealthStatus Table
- `id`: Primary key
- `source_id`: Audio source identifier
- `health_score`: 0-100 score
- `uptime_seconds`: Source uptime
- `last_error`: Last error message
- `error_count`: Number of errors
- `updated_at`: Timestamp

## UI/UX Mockup

### Audio Sources Page Layout:
```
┌────────────────────────────────────────────────────────────┐
│ Audio Ingestion Management                      [+ Add]    │
├────────────────────────────────────────────────────────────┤
│ ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│ │ Health   │  │ Active   │  │ Uptime   │  │ Silence  │   │
│ │   98%    │  │ 3 Sources│  │ 24h 15m  │  │ 0 Alerts │   │
│ └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
├────────────────────────────────────────────────────────────┤
│ Active Audio Sources                                       │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ Name: Main SDR Receiver              Status: ● Running │ │
│ │ Type: SDR (rtlsdr)          Sample Rate: 24000 Hz      │ │
│ │ Peak: [████████████─────] -12 dBFS                     │ │
│ │ RMS:  [██████──────────] -18 dBFS                      │ │
│ │ [Stop] [Edit] [Delete]                                  │ │
│ └────────────────────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ Name: Backup ALSA Input              Status: ● Running │ │
│ │ Type: ALSA (hw:0,0)         Sample Rate: 48000 Hz      │ │
│ │ Peak: [██████████──────] -14 dBFS                      │ │
│ │ RMS:  [████████────────] -20 dBFS                      │ │
│ │ [Stop] [Edit] [Delete]                                  │ │
│ └────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│ [🔍 Discover Audio Devices]                                │
└────────────────────────────────────────────────────────────┘
```

## Testing Plan

### Backend Tests
- Test audio source CRUD operations via API
- Verify metrics are being recorded to database
- Test silence detection thresholds
- Validate health score calculations

### Frontend Tests
- Test real-time metric updates
- Verify start/stop controls work correctly
- Test device discovery functionality
- Validate form validation and error handling

### Integration Tests
- End-to-end test: Add source → Start → Monitor → Stop → Delete
- Test with multiple simultaneous sources
- Verify database cleanup on source deletion

## Estimated Implementation Time

- **Phase 1 (API Endpoints)**: 4-6 hours
- **Phase 2 (Frontend UI)**: 8-10 hours
- **Phase 3 (Integration)**: 2-3 hours
- **Phase 4 (Advanced Features)**: 8-12 hours (optional)
- **Testing & Refinement**: 4-6 hours

**Total Core Implementation**: ~18-22 hours

## Dependencies

- Backend audio system already implemented (no changes needed)
- Database models already exist (no migrations needed)
- Requires JavaScript for real-time updates (fetch API, async/await)
- Bootstrap 5 for UI components (already included)
- Font Awesome icons (already included)

## Notes

- The audio ingest backend is production-ready and well-documented
- All database tables exist and are properly indexed
- Focus on clean, responsive UI with real-time updates
- Prioritize usability - make it easy to add and monitor sources
- Consider accessibility (screen readers, keyboard navigation)

## References

- Backend Implementation: `app_core/audio/`
- Documentation: `docs/audio.md`
- Testing Tool: `tools/audio_debug.py`
- Unit Tests: `tests/test_audio_ingest.py`

---

**Status**: Ready for implementation
**Created**: 2025-11-04
**Last Updated**: 2025-11-04
