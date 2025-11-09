# Audio Monitoring Feature

## Overview
The Audio Monitoring feature allows users to listen to live audio from configured audio sources (SDR receivers, web streams, ALSA devices, etc.) directly through the web interface. This is invaluable for monitoring signal quality, debugging audio issues, and verifying that sources are receiving audio correctly.

---

## Features

### Live Audio Streaming
- **Real-time playback** - Listen to audio sources as they capture
- **WAV format streaming** - Browser-compatible PCM audio
- **Multiple sources** - Monitor SDR, web streams, ALSA, PulseAudio, and file sources
- **Auto-reconnect** - Streams automatically refresh

### Visual Monitoring
- **Live waveform display** - Real-time oscilloscope view of audio
- **Audio level meters** - Peak and RMS level monitoring
- **Status indicators** - Running, stopped, error states
- **Health metrics** - Sample rate, channels, buffer utilization

### Source Control
- **Start/Stop sources** - Control audio sources from the monitoring page
- **Auto-refresh** - Page updates every 5 seconds
- **Manual refresh** - Refresh button for immediate updates

---

## Architecture

### Backend (`webapp/admin/audio_ingest.py`)

#### New Endpoint: `/api/audio/stream/<source_name>`

**Purpose**: Stream live audio in WAV format

**How it works**:
1. Accepts source name as URL parameter
2. Validates source exists and is running
3. Generates WAV header with proper format info
4. Continuously pulls audio chunks from source queue
5. Converts float32 audio to int16 PCM
6. Yields PCM data as streaming response
7. Auto-terminates after ~2 minutes to prevent resource exhaustion

**Stream Format**:
- **Container**: WAV (RIFF)
- **Codec**: PCM (uncompressed)
- **Bit depth**: 16-bit
- **Sample rate**: Matches source (typically 44.1kHz)
- **Channels**: Matches source (typically mono)
- **Duration**: ~2 minutes max per stream session

**Technical Details**:
```python
# WAV header structure
RIFF header (12 bytes)
  - 'RIFF' magic
  - File size (0xFFFFFFFF for streaming)
  - 'WAVE' magic

fmt chunk (24 bytes)
  - 'fmt ' magic
  - Chunk size (16)
  - Audio format (1 = PCM)
  - Channels
  - Sample rate
  - Byte rate
  - Block align
  - Bits per sample

data chunk header (8 bytes)
  - 'data' magic
  - Data size (0xFFFFFFFF for streaming)

PCM audio data (continuous stream)
```

### Frontend (`templates/audio_monitoring.html`)

#### Components

**1. Source Cards**
- Display one card per configured audio source
- Color-coded border by status (green=running, gray=stopped, red=error)
- Shows source type, name, description
- Includes HTML5 audio player when running
- Live waveform canvas visualization
- Real-time metrics display

**2. Audio Player**
- Native HTML5 `<audio>` element
- Points to `/api/audio/stream/<source_name>`
- Browser handles all buffering and playback
- Standard play/pause/volume controls

**3. Waveform Visualization**
- Canvas-based real-time oscilloscope
- Updates every 100ms via `/api/audio/waveform/<source_name>`
- Displays last 2048 samples
- Green waveform on black background
- Center line for zero reference

**4. Metrics Display**
- Grid layout with key metrics
- Peak level (dB)
- RMS level (dB)
- Sample rate (kHz)
- Channel count
- Updates every 5 seconds with source data

---

## Usage

### Accessing the Audio Monitor

1. Navigate to **Monitoring** → **Audio Monitoring** in the main menu
2. The page will load all configured audio sources
3. Sources will be displayed as cards with their current status

### Listening to a Source

**If source is running:**
1. Simply click the Play button on the HTML5 audio player
2. Adjust volume as needed
3. Watch the waveform for visual feedback

**If source is stopped:**
1. Click the **Start** button on the source card
2. Wait ~1 second for source to start
3. Page will automatically refresh
4. Click Play on the audio player

### Stopping a Source

1. Click the **Stop** button on the source card
2. Audio playback will stop
3. Waveform updates will cease
4. Source status will update to "stopped"

### Understanding the Display

**Status Badges:**
- **RUNNING** (green) - Source is capturing audio
- **STOPPED** (gray) - Source is not active
- **STARTING** (yellow) - Source is initializing
- **ERROR** (red) - Source encountered an error
- **DISCONNECTED** (yellow) - Source lost connection

**Metrics:**
- **Peak**: Maximum audio level (should be below 0 dB)
- **RMS**: Average audio level (typical range: -40 to -10 dB)
- **Sample Rate**: Audio quality (44.1 kHz = CD quality)
- **Channels**: Mono (1) or Stereo (2)

---

## Configuration

### Audio Source Requirements

For a source to appear in the audio monitor:
1. Must be configured in Audio Settings
2. Must have a valid configuration
3. Source adapter must be initialized

### Starting Sources Automatically

To have sources auto-start on application boot:
1. Go to Admin → Audio Settings
2. Edit the source configuration
3. Enable **Auto Start** option
4. Save configuration
5. Restart application

---

## Technical Limitations

### Stream Duration
Streams automatically terminate after ~2 minutes (6000 chunks at 20ms per chunk). This prevents:
- Memory leaks from abandoned connections
- Resource exhaustion from stale streams
- Bandwidth waste from forgotten tabs

**To continue listening**: Simply click Play again

### Browser Compatibility
- **Chrome/Edge**: Full support
- **Firefox**: Full support
- **Safari**: Full support (may have buffering quirks)
- **Mobile browsers**: Supported but may have autoplay restrictions

### Network Requirements
- **Bandwidth**: ~700 Kbps per stream (44.1kHz mono 16-bit)
- **Latency**: ~2-5 seconds typical (buffering delay)
- **Concurrent streams**: No hard limit (limited by server resources)

---

## Troubleshooting

### "Source not found" Error
**Cause**: Source doesn't exist or hasn't been configured
**Solution**: Go to Audio Settings and configure the source

### "Source not running" Error
**Cause**: Source is stopped or in error state
**Solution**: Click the Start button to start the source

### No Audio / Silence
**Possible causes**:
1. Source not receiving signal (check antenna/connection)
2. Volume level too low (check browser volume and player volume)
3. Source frequency/settings incorrect
4. Hardware issue (SDR disconnected, etc.)

**Debugging**:
1. Check waveform - if flat line, no signal
2. Check metrics - if RMS < -60 dB, very weak signal
3. Check System Logs for error messages
4. Check Audio Health page for source status

### Choppy/Stuttering Audio
**Possible causes**:
1. Network latency/bandwidth issues
2. Server overload
3. Too many concurrent streams

**Solutions**:
1. Reduce number of active streams
2. Check server CPU/memory usage
3. Check network connection quality

### Waveform Not Updating
**Possible causes**:
1. Source stopped
2. JavaScript error
3. API endpoint not responding

**Solutions**:
1. Check browser console for errors
2. Click Refresh button
3. Restart source

---

## API Reference

### GET `/api/audio/sources`
**Description**: List all configured audio sources
**Response**: JSON with array of source objects
```json
{
  "sources": [
    {
      "id": "sdr-primary",
      "name": "sdr-primary",
      "type": "sdr",
      "status": "running",
      "enabled": true,
      "metrics": {
        "peak_level_db": -12.5,
        "rms_level_db": -25.3,
        "sample_rate": 44100,
        "channels": 1
      }
    }
  ],
  "total": 1,
  "active_count": 1
}
```

### GET `/api/audio/stream/<source_name>`
**Description**: Stream live audio in WAV format
**Parameters**:
- `source_name` (path) - Name of audio source
**Response**: Binary WAV stream
**Content-Type**: `audio/wav`
**Headers**:
- `Cache-Control: no-cache, no-store, must-revalidate`
- `X-Content-Type-Options: nosniff`

### GET `/api/audio/waveform/<source_name>`
**Description**: Get current waveform data for visualization
**Parameters**:
- `source_name` (path) - Name of audio source
**Response**: JSON with waveform array
```json
{
  "source_name": "sdr-primary",
  "waveform": [-0.01, 0.02, -0.03, ...],
  "sample_count": 2048,
  "timestamp": 1699384567.123,
  "status": "running"
}
```

### POST `/api/audio/sources/<source_name>/start`
**Description**: Start an audio source
**Response**: `{"success": true}`

### POST `/api/audio/sources/<source_name>/stop`
**Description**: Stop an audio source
**Response**: `{"success": true}`

---

## Security Considerations

### Access Control
- Audio monitoring is publicly accessible (no auth required currently)
- Consider adding authentication if dealing with sensitive audio
- Stream URLs are predictable (based on source name)

### Resource Protection
- Automatic stream termination after 2 minutes
- Queue size limits prevent memory exhaustion
- Rate limiting could be added for production deployments

### Data Privacy
- Audio is streamed in real-time (not recorded)
- No server-side storage of audio data
- Streams are per-client (not broadcast to all)

---

## Future Enhancements

### Potential Features
1. **Recording capability** - Save audio streams to files
2. **Spectral analysis** - Add FFT waterfall display
3. **Audio alerts** - Notify on signal loss/clipping
4. **Multi-channel support** - Stereo waveform display
5. **Bandwidth optimization** - Lower bitrate options
6. **Authentication** - Role-based access control
7. **Annotations** - Mark interesting audio events
8. **Playback history** - Review past audio segments

### Performance Improvements
1. **WebSocket streaming** - Lower latency alternative to HTTP
2. **Opus codec** - Better compression than PCM
3. **Adaptive bitrate** - Adjust quality based on connection
4. **Client-side buffering** - Reduce stream interruptions

---

## Files Modified

### New Files
- `templates/audio_monitoring.html` - Frontend UI
- `AUDIO_MONITORING.md` - This documentation

### Modified Files
- `webapp/admin/audio_ingest.py` - Added `/api/audio/stream/<source_name>` endpoint
- `webapp/routes_public.py` - Added `/audio-monitor` route
- `components/navbar.html` - Added "Audio Monitoring" menu item

---

## Credits
- **WAV streaming**: Standard RIFF/WAV format specification
- **HTML5 Audio**: Native browser audio support
- **Canvas waveform**: Real-time 2D visualization
- **Flask streaming**: Flask's `stream_with_context()` generator support

---

## Support
For issues or questions about audio monitoring:
1. Check this documentation
2. Review System Logs for errors
3. Check browser console for JavaScript errors
4. Verify source configuration in Audio Settings
5. Test with simple file source before SDR/stream sources

---

**Last Updated**: November 7, 2025
