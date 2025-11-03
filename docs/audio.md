# Audio Ingest Pipeline Documentation

## Overview

The Audio Ingest Pipeline provides a unified interface for capturing audio from multiple sources including SDR receivers, ALSA/PulseAudio devices, and file inputs. It implements real-time monitoring, metering, and health tracking to ensure reliable audio capture for emergency alert systems.

## Architecture

### Core Components

- **AudioSourceAdapter**: Abstract base class for audio sources
- **AudioIngestController**: Main controller managing multiple sources
- **AudioMeter**: Real-time peak/RMS level monitoring
- **SilenceDetector**: Configurable silence detection and alerting
- **AudioHealthMonitor**: Comprehensive health monitoring

### Supported Source Types

1. **SDR Sources**: Audio capture from SDR receivers via the radio manager
2. **ALSA Sources**: Linux ALSA audio devices
3. **PulseAudio Sources**: PulseAudio input devices via PyAudio
4. **File Sources**: Audio file playback (useful for testing)

## Configuration

### Environment Variables

#### Main Audio Ingest Settings

```bash
# Enable/disable the audio ingest pipeline
AUDIO_INGEST_ENABLED=false

# Audio format settings
AUDIO_INGEST_BUFFER_SIZE=4096
AUDIO_INGEST_SAMPLE_RATE=44100
AUDIO_INGEST_CHANNELS=1
```

#### SDR Audio Source

```bash
# Enable SDR audio capture
AUDIO_SDR_ENABLED=false
AUDIO_SDR_RECEIVER_ID=receiver_001
AUDIO_SDR_PRIORITY=100
```

#### ALSA Audio Source

```bash
# Enable ALSA audio capture
AUDIO_ALSA_ENABLED=false
AUDIO_ALSA_DEVICE=default
AUDIO_ALSA_PRIORITY=200
```

#### PulseAudio Source

```bash
# Enable PulseAudio capture
AUDIO_PULSE_ENABLED=false
AUDIO_PULSE_DEVICE_INDEX=
AUDIO_PULSE_PRIORITY=300
```

#### File Source (Testing)

```bash
# Enable file audio source
AUDIO_FILE_ENABLED=false
AUDIO_FILE_PATH=/path/to/test.wav
AUDIO_FILE_LOOP=false
AUDIO_FILE_PRIORITY=999
```

#### Monitoring and Alerting

```bash
# Silence detection settings
AUDIO_SILENCE_THRESHOLD_DB=-60.0
AUDIO_SILENCE_DURATION_SECONDS=5.0

# Clipping detection
AUDIO_CLIPPING_THRESHOLD=0.95

# Audio metering
AUDIO_METER_WINDOW_SIZE=1024

# Health monitoring
AUDIO_HEALTH_CHECK_INTERVAL=10
AUDIO_ALERT_CALLBACK_ENABLED=true
AUDIO_ALERT_EMAIL_ENABLED=false
```

## Usage

### Programmatic Usage

```python
from app_core.audio.ingest import AudioIngestController, AudioSourceConfig, AudioSourceType
from app_core.audio.sources import create_audio_source

# Create controller
controller = AudioIngestController()

# Configure SDR source
sdr_config = AudioSourceConfig(
    source_type=AudioSourceType.SDR,
    name="sdr_main",
    enabled=True,
    priority=100,
    sample_rate=44100,
    channels=1,
    device_params={"receiver_id": "receiver_001"}
)

# Create and add source
sdr_source = create_audio_source(sdr_config)
controller.add_source(sdr_source)

# Start all sources
controller.start_all()

# Get audio chunks
while True:
    chunk = controller.get_audio_chunk(timeout=1.0)
    if chunk is not None:
        # Process audio chunk
        process_audio(chunk)
```

### Health Monitoring

```python
from app_core.audio.metering import AudioHealthMonitor

# Create health monitor for a source
monitor = AudioHealthMonitor("sdr_main")

# Add alert callback
def on_audio_alert(alert):
    print(f"Audio Alert: {alert.level.value} - {alert.message}")

monitor.add_alert_callback(on_audio_alert)

# Process audio samples
health_status = monitor.process_samples(audio_chunk)

# Get current health status
status = monitor.get_health_status()
print(f"Health Score: {status['health_score']:.1f}%")
print(f"Silence Detected: {status['silence_detected']}")
```

## Command Line Tools

### Audio Debug Utility

The `tools/audio_debug.py` script provides comprehensive testing and debugging capabilities.

#### Test All Configured Sources

```bash
python tools/audio_debug.py test-all --duration 15
```

#### Test Specific Source Type

```bash
# Test ALSA source
python tools/audio_debug.py test --type alsa --duration 10

# Test PulseAudio source
python tools/audio_debug.py test --type pulse --duration 10 --device 0

# Test file source
python tools/audio_debug.py test --type file --duration 5 --file /path/to/audio.wav
```

#### List Available Devices

```bash
# List ALSA devices
python tools/audio_debug.py list-devices --type alsa

# List PulseAudio devices
python tools/audio_debug.py list-devices --type pulse

# List SDR devices
python tools/audio_debug.py list-devices --type sdr
```

#### Generate Test Tone

```bash
# Generate 440Hz test tone
python tools/audio_debug.py generate-tone --frequency 440 --duration 5

# Generate custom test tone
python tools/audio_debug.py generate-tone \
    --frequency 1000 \
    --duration 10 \
    --output /tmp/test_tone.wav
```

## API Reference

### AudioSourceConfig

Configuration object for audio sources.

**Parameters:**
- `source_type` (AudioSourceType): Type of audio source
- `name` (str): Human-readable name
- `enabled` (bool): Whether source is enabled
- `priority` (int): Priority (lower numbers = higher priority)
- `sample_rate` (int): Audio sample rate
- `channels` (int): Number of audio channels
- `buffer_size` (int): Audio buffer size
- `silence_threshold_db` (float): Silence detection threshold
- `device_params` (dict): Device-specific parameters

### AudioIngestController

Main controller for managing audio sources.

**Methods:**
- `add_source(source)`: Add an audio source
- `remove_source(name)`: Remove an audio source
- `start_source(name)`: Start a specific source
- `stop_source(name)`: Stop a specific source
- `start_all()`: Start all enabled sources
- `stop_all()`: Stop all sources
- `get_audio_chunk(timeout)`: Get audio from highest priority active source
- `get_source_metrics(name)`: Get metrics for specific source
- `get_all_metrics()`: Get metrics for all sources
- `get_active_source()`: Get currently active source name
- `cleanup()`: Cleanup all sources and threads

### AudioMetrics

Real-time audio metrics.

**Fields:**
- `timestamp` (float): Timestamp of metrics collection
- `peak_level_db` (float): Peak level in dBFS
- `rms_level_db` (float): RMS level in dBFS
- `sample_rate` (int): Current sample rate
- `channels` (int): Number of channels
- `frames_captured` (int): Total frames captured
- `silence_detected` (bool): Whether silence is detected
- `buffer_utilization` (float): Audio buffer utilization (0-1)

### AudioHealthMonitor

Comprehensive health monitoring for audio sources.

**Methods:**
- `process_samples(samples)`: Process audio samples and return health metrics
- `get_health_status()`: Get current health status
- `add_alert_callback(callback)`: Add alert callback
- `reset()`: Reset monitoring state

## Troubleshooting

### Common Issues

#### ALSA Device Not Found

```bash
# List available ALSA devices
python tools/audio_debug.py list-devices --type alsa

# Check device permissions
arecord -l
```

#### PulseAudio Device Issues

```bash
# List PulseAudio devices
python tools/audio_debug.py list-devices --type pulse

# Check PulseAudio status
pactl info
```

#### SDR Receiver Not Available

```bash
# List SDR devices
python tools/audio_debug.py list-devices --type sdr

# Check radio manager
python -c "from app_core.radio.manager import RadioManager; print(RadioManager().discover_devices())"
```

#### Silence Detection Too Sensitive

Adjust the silence threshold and duration:

```bash
AUDIO_SILENCE_THRESHOLD_DB=-70.0  # More sensitive
AUDIO_SILENCE_DURATION_SECONDS=10.0  # Longer duration
```

#### Audio Level Too Low/High

Check the audio metering values and adjust gain or input levels:

```bash
# Monitor audio levels in real-time
python tools/audio_debug.py test-all --duration 30
```

### Debug Logging

Enable debug logging for detailed troubleshooting:

```python
import logging
logging.getLogger('app_core.audio').setLevel(logging.DEBUG)
```

### Performance Monitoring

Monitor CPU and memory usage:

```bash
# Monitor system resources during audio capture
htop

# Check audio thread status
ps aux | grep python
```

## Integration with EAS Station

### System Health Integration

The audio ingest pipeline integrates with the system health monitoring:

- Audio metrics are stored in the database
- Health scores are displayed in the system health dashboard
- Audio alerts are shown in the admin interface

### Alert System Integration

Audio alerts are integrated with the EAS alert system:

- Silence detected alerts trigger notifications
- Clipping detection generates warnings
- Source disconnection triggers error alerts

### Database Storage

Audio metrics and health status are stored in:

- `audio_source_metrics`: Real-time audio metrics
- `audio_health_status`: Health status snapshots
- `audio_alerts`: Audio system alerts and notifications

## Security Considerations

### Device Permissions

Ensure proper permissions for audio devices:

```bash
# Add user to audio group
sudo usermod -a -G audio $USER

# Check device permissions
ls -la /dev/snd/
```

### Network Security

When using network audio sources:

- Use secure connections for remote audio streams
- Validate audio source configurations
- Monitor for unauthorized audio capture attempts

### Data Privacy

Audio data may contain sensitive information:

- Configure appropriate retention policies for audio metrics
- Secure audio file storage
- Audit access to audio recordings

## Performance Optimization

### Buffer Tuning

Adjust buffer sizes based on latency requirements:

```bash
# Low latency (smaller buffers, more CPU)
AUDIO_INGEST_BUFFER_SIZE=1024

# High stability (larger buffers, more latency)
AUDIO_INGEST_BUFFER_SIZE=8192
```

### CPU Usage

Monitor CPU usage and adjust parameters:

- Reduce sample rate if CPU usage is high
- Optimize audio processing threads
- Use appropriate audio formats

### Memory Management

Monitor memory usage for long-running captures:

- Limit audio history storage
- Regular cleanup of old metrics
- Efficient audio buffer management

## Testing

### Unit Tests

Run the audio ingest tests:

```bash
python -m pytest tests/test_audio_ingest.py -v
```

### Integration Tests

Test with actual hardware:

```bash
# Test audio capture end-to-end
python tools/audio_debug.py test-all --duration 60

# Test alert generation
python tools/audio_debug.py test --type file --file /path/to/silent.wav --duration 10
```

### Load Testing

Test system performance under load:

```bash
# Multiple concurrent sources
python -c "
from app_core.audio.ingest import AudioIngestController
# Test with multiple sources
"
```

## Future Enhancements

### Planned Features

- WebRTC audio source support
- Automatic gain control (AGC)
- Audio compression and streaming
- Multi-zone audio routing
- Audio fingerprinting for source identification

### Extension Points

- Custom audio source adapters
- Advanced audio processing plugins
- Integration with external audio monitoring systems
- Custom alerting and notification systems