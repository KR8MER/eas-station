# SoapySDR Audio Integration Fixes

## Summary

This document describes the fixes applied to resolve issues with SoapySDR audio demodulation and streaming.

## Problems Identified

### 1. Inconsistent Demodulator Return Types

**Symptom**: Application crashes with unpacking errors when using AM demodulation
**Root Cause**: FM demodulator returned `(audio, rbds_data)` tuple, but AM demodulator only returned `audio` array
**Fix**: Modified `AMDemodulator.demodulate()` to return `(audio, None)` tuple for consistency

```python
# Before:
def demodulate(self, iq_samples: np.ndarray) -> np.ndarray:
    ...
    return audio.astype(np.float32)

# After:
def demodulate(self, iq_samples: np.ndarray) -> Tuple[np.ndarray, None]:
    ...
    return audio.astype(np.float32), None
```

### 2. Missing IQ Mode Handling

**Symptom**: No audio output when `modulation_type='IQ'` or `audio_output=False`
**Root Cause**: When no demodulator is configured, SDRSourceAdapter still receives IQ samples but tried to treat them as PCM
**Fix**: Added proper IQ sample handling with envelope detection (magnitude) for raw IQ conversion to audio

```python
# Added handling for raw IQ samples when no demodulator exists:
if isinstance(audio_data, bytes):
    iq_array = np.frombuffer(audio_data, dtype=np.float32)
    iq_complex = iq_array[0::2] + 1j * iq_array[1::2]
    audio_array = np.abs(iq_complex).astype(np.float32)
else:
    iq_complex = np.array(audio_data, dtype=np.complex64)
    audio_array = np.abs(iq_complex).astype(np.float32)
```

### 3. Device Serial Number Conflict

**Symptom**: "Unable to open AirSpy device with serial a74068c82f341893" error
**Root Cause**: Code was setting `serial` parameter to channel number when channel was provided, conflicting with actual hardware serial numbers
**Fix**: Only use `serial` for actual hardware serial numbers, not channel IDs

```python
# Before:
elif self.config.channel is not None:
    args["device_id"] = str(self.config.channel)
    args["serial"] = str(self.config.channel)  # WRONG!

# After:
elif self.config.channel is not None:
    args["device_id"] = str(self.config.channel)
    # Don't set serial - it's for hardware serial numbers only
```

## Files Modified

1. **app_core/radio/demodulation.py**
   - Modified `AMDemodulator.demodulate()` to return tuple `(audio, None)` (3 changes)
   - Updated docstring and return type annotation

2. **app_core/audio/sources.py**
   - Fixed `SDRSourceAdapter._read_audio_chunk()` to handle raw IQ samples when no demodulator exists
   - Added envelope detection for IQ to audio conversion
   - Improved error logging with `exc_info=True`

3. **app_core/radio/drivers.py**
   - Fixed `_SoapySDRReceiver._open_handle()` to not set serial parameter when using channel ID
   - Cleaned up device identification logic

## Testing Recommendations

### 1. Test with FM Demodulation
```bash
# Configure a receiver with FM modulation
# Check that audio is properly demodulated and streamed to Icecast
```

### 2. Test with AM Demodulation
```bash
# Configure a receiver with AM modulation
# Verify no unpacking errors and audio is demodulated
```

### 3. Test with IQ Mode
```bash
# Configure a receiver with modulation_type='IQ' or audio_output=False
# Verify envelope detection converts IQ to audio
```

### 4. Test Device Identification
```bash
# Test with device that has serial number
# Verify it opens correctly without conflicts

# Test with device using channel ID
# Verify it opens correctly using device_id
```

### 5. Run Diagnostic Script
```bash
# Check SDR status and audio pipeline
python scripts/diagnostics/check_sdr_status.py

# Run comprehensive diagnostics
python scripts/sdr_diagnostics.py
```

## Audio Flow

The complete audio flow for SDR sources:

1. **SDR Hardware** → Captures RF signal
2. **SoapySDR Driver** → Reads IQ samples from hardware
3. **RadioManager** → Manages receiver lifecycle, provides `get_samples()` interface
4. **SDRSourceAdapter** → Receives IQ samples via RadioManager.get_audio_data()
5. **Demodulator** (optional) → Converts IQ to audio (FM/AM/etc)
6. **AudioIngestController** → Manages multiple audio sources
7. **IcecastStreamer** → Encodes and streams audio to Icecast
8. **Audio Monitoring Page** → Displays waterfall and audio visualization

## Waterfall Display

The waterfall display should show:
- Real-time spectrum (FFT of IQ samples)
- Center frequency and bandwidth
- Signal strength indication

API endpoint: `/api/radio/spectrum/<receiver_id>`

## Icecast Streaming

SDR audio sources are automatically streamed to Icecast when:
1. Receiver has `audio_output=True`
2. Receiver is `enabled=True`
3. Receiver has `auto_start=True` (optional)
4. Icecast configuration is valid

Mount point: `/<source-name>` (e.g., `/sdr-wx42`)

## Debugging Tips

### No Audio Output

1. Check receiver status:
```bash
python scripts/diagnostics/check_sdr_status.py
```

2. Check if demodulator is created:
```python
# In logs, look for:
"Created FM demodulator for receiver: <id>"
```

3. Check audio source metrics:
```bash
# Access /api/audio/sources endpoint
# Look for rms_level_db and peak_level_db values
```

### Device Not Opening

1. Check device enumeration:
```bash
python scripts/sdr_diagnostics.py --enumerate
```

2. Check device capabilities:
```bash
python scripts/sdr_diagnostics.py --capabilities rtlsdr
```

3. Verify USB connection and permissions

### Waterfall Not Showing

1. Verify receiver is running (status: locked=True)
2. Check that IQ samples are available via `/api/radio/spectrum/<id>`
3. Verify NumPy is installed for FFT calculations

## Additional Notes

- **Stereo FM**: When `stereo_enabled=True`, demodulator outputs 2D array with shape `(samples, 2)`
- **RBDS**: FM demodulator can extract RBDS/RDS metadata (station name, radio text, etc)
- **Sample Rates**: Demodulator resamples from SDR sample rate to audio sample rate
- **De-emphasis**: FM demodulator applies de-emphasis filter (75μs for NA, 50μs for EU)
