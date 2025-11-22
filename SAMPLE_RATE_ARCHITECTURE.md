# Sample Rate Architecture

## Overview

This document explains how sample rates are handled throughout the EAS Station system.

## Key Principle

**Audio sources/streams can use ANY sample rate they need, but the EAS decoder MUST receive properly resampled 16 kHz audio.**

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AUDIO SOURCES                            │
│  (SDR, Line In, Streams, Files)                            │
│  Sample Rates: 44.1k, 48k, 32k, 24k, etc.                 │
└──────────────────┬──────────────────────────────────────────┘
                   │ Native sample rate audio
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│              AUDIO INGEST CONTROLLER                        │
│  Manages audio sources at their NATIVE rates               │
│  - No resampling here                                      │
│  - Keeps original sample rates for streams/outputs         │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ├─────────────────────┬────────────────────┐
                   │                     │                    │
                   ▼                     ▼                    ▼
┌──────────────────────┐  ┌──────────────────┐  ┌───────────────────┐
│  ICECAST STREAMING   │  │  AUDIO OUTPUTS   │  │   EAS MONITOR     │
│  (Native rate)       │  │  (Native rate)   │  │                   │
│  44.1k/48k/etc.      │  │  44.1k/48k/etc.  │  │  ┌─────────────┐  │
└──────────────────────┘  └──────────────────┘  │  │  RESAMPLE   │  │
                                                 │  │  TO 16 kHz  │  │
                                                 │  └──────┬──────┘  │
                                                 │         │         │
                                                 │         ▼         │
                                                 │  ┌─────────────┐  │
                                                 │  │ SAME DECODER│  │
                                                 │  │   (16 kHz)  │  │
                                                 │  └─────────────┘  │
                                                 └───────────────────┘
```

## Sample Rate Flow

### 1. Audio Sources (Native Rates)

Audio sources use their **native sample rates**:

- **FM Stereo**: 48000 Hz (broadcast quality)
- **FM Mono**: 32000 Hz (standard FM)
- **AM/NFM**: 24000 Hz (narrowband)
- **Line In/Streams**: 44100 Hz (CD quality)
- **Other**: Whatever the source provides

**Files:**
- `app_core/audio/ingest.py` - AudioSourceConfig defaults
- `app_core/audio/source_manager.py` - AudioSourceManager
- `webapp/admin/audio_ingest.py` - Source configuration

### 2. Audio Distribution (Native Rates)

Audio is distributed at its **native sample rate** to:

- **Icecast Streaming**: Keeps native rate for quality
- **Audio Outputs**: Keeps native rate for playback
- **Broadcast Queue**: Distributes native rate samples

**Files:**
- `app_core/audio/icecast_output.py` - Streaming at native rate
- `app_core/audio/broadcast_queue.py` - Pub/sub distribution

### 3. EAS Monitor (RESAMPLES to 16 kHz)

The EAS monitor is the **ONLY** component that resamples audio:

1. Subscribes to broadcast queue
2. Receives audio at **native rate** (44.1k, 48k, etc.)
3. **RESAMPLES to 16 kHz** using `scipy.signal.resample_poly`
4. Feeds **16 kHz audio** to SAME decoder

**Files:**
- `app_core/audio/eas_monitor.py` - Resampling logic in `_resample_if_needed()`
- `app_core/audio/streaming_same_decoder.py` - Decoder expects 16 kHz

### 4. Why 16 kHz for SAME Decoding?

Based on extensive testing documented in `SAMPLE_RATE_OPTIMIZATION_COMPLETE.md`:

- **7.7× Nyquist margin** (well above recommended 4-5×)
- **100% reliability** in testing (vs 90% for 22.05 kHz)
- **39% faster** processing than 22.05 kHz
- **27% less memory** than 22.05 kHz
- **Industry standard** for speech/telephony

## Resampling Implementation

### Proper Resampling (✓ CORRECT)

```python
# In eas_monitor.py
from scipy.signal import resample_poly

def _resample_if_needed(self, samples: np.ndarray) -> np.ndarray:
    """Resample audio from source_sample_rate to decoder target_rate (16 kHz)"""
    if self.source_sample_rate == self.sample_rate:
        return samples  # No resampling needed
    
    # Calculate rational resampling ratio
    up = int(self.sample_rate)      # Target: 16000
    down = int(self.source_sample_rate)  # Source: 44100, 48000, etc.
    
    # Use polyphase filter for high-quality resampling
    resampled = resample_poly(samples, up, down)
    return resampled.astype(np.float32)
```

### FFmpeg Resampling (✓ CORRECT)

```python
# In ffmpeg_source.py
cmd = [
    'ffmpeg',
    '-i', source_url,
    '-ar', str(self.sample_rate),  # Tells FFmpeg to RESAMPLE
    '-ac', '1',
    '-f', 's16le',
    '-'
]
```

The `-ar` flag tells FFmpeg to **actually resample** the audio using its high-quality resampler, not just change metadata.

### WRONG Approaches (✗ DO NOT DO THIS)

```python
# ✗ WRONG: Just changing the sample rate variable
samples.sample_rate = 16000  # Does nothing to the audio data!

# ✗ WRONG: Slicing samples without resampling
target_samples = samples[::3]  # Crude decimation, causes aliasing!

# ✗ WRONG: Using wrong parameter order
resampled = resample_poly(samples, down, up)  # Backwards!
```

## Configuration

### Environment Variables

```bash
# .env file
EAS_SAMPLE_RATE=16000  # Decoder target rate (DO NOT CHANGE)
```

### Code Defaults

All defaults are now correctly set:

| Component | Sample Rate | Purpose |
|-----------|-------------|---------|
| Audio Sources | 44100 Hz | Native stream rate |
| Source Manager | 44100 Hz | Native stream rate |
| Broadcast Adapter | 44100 Hz | Native stream rate |
| Controller Adapter | 44100 Hz | Native stream rate |
| EAS Monitor | 16000 Hz | Decoder target rate |
| Streaming Decoder | 16000 Hz | SAME decoding |

## Testing

### Verify Resampling

```python
# Test that resampling is working
monitor = ContinuousEASMonitor(audio_manager, sample_rate=16000)
print(f"Source rate: {monitor.source_sample_rate} Hz")  # Should show source rate
print(f"Decoder rate: {monitor.sample_rate} Hz")        # Should show 16000

# Feed 44.1 kHz audio
samples_44k = np.random.randn(44100)  # 1 second at 44.1 kHz
resampled = monitor._resample_if_needed(samples_44k)
print(f"Input: {len(samples_44k)} samples")  # 44100
print(f"Output: {len(resampled)} samples")   # ~16000
```

### Expected Sample Counts

| Source Rate | Input Samples (1 sec) | Output Samples (1 sec) | Ratio |
|-------------|----------------------|------------------------|-------|
| 44100 Hz | 44100 | 16000 | 16000/44100 ≈ 0.363 |
| 48000 Hz | 48000 | 16000 | 16000/48000 = 0.333 |
| 32000 Hz | 32000 | 16000 | 16000/32000 = 0.500 |
| 24000 Hz | 24000 | 16000 | 16000/24000 ≈ 0.667 |
| 16000 Hz | 16000 | 16000 | 16000/16000 = 1.000 (no resample) |

## Troubleshooting

### UI Shows Wrong Sample Rate

**Problem:** UI displays 8 kHz or other unexpected rate

**Cause:** Old defaults were using 8 kHz or 22.05 kHz

**Solution:** Changes in this PR fix all defaults to:
- Sources: 44.1 kHz (native)
- Decoder: 16 kHz (target)

### Decoder Not Working

**Problem:** SAME headers not being decoded

**Possible Causes:**
1. Source sample rate is 0 or invalid
2. Resampling is not happening
3. Decoder is not receiving 16 kHz audio

**Debug:**
```python
status = monitor.get_status()
print(f"Source rate: {status['source_sample_rate']} Hz")
print(f"Decoder rate: {status['sample_rate']} Hz")
print(f"Resample ratio: {status['resample_ratio']}")
```

### Audio Quality Issues

**Problem:** Audio sounds distorted or wrong

**Cause:** May be resampling unnecessarily

**Solution:** Audio outputs should use native rates, only EAS decoder resamples

## Summary

✓ **Audio sources**: Native sample rates (44.1k, 48k, etc.)  
✓ **Streaming/outputs**: Native sample rates (no resampling)  
✓ **EAS monitor**: Resamples to 16 kHz using `resample_poly`  
✓ **SAME decoder**: Receives properly resampled 16 kHz audio  
✓ **Result**: Optimal decoding performance with high-quality streams

## References

- [SAMPLE_RATE_OPTIMIZATION_COMPLETE.md](SAMPLE_RATE_OPTIMIZATION_COMPLETE.md) - Testing results
- [SAMPLE_RATE_CHANGE_SUMMARY.md](SAMPLE_RATE_CHANGE_SUMMARY.md) - Quick reference
- [app_core/audio/eas_monitor.py](app_core/audio/eas_monitor.py) - Resampling implementation
