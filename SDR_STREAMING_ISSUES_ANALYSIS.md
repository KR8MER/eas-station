# SDR, Waterfall, and Streaming Issues - Critical Analysis

## Executive Summary
Multiple interconnected issues affect SDR operations, waterfall visualization, and audio streaming:
1. **Missing Waterfall/Spectrum Visualization** - No real-time FFT display in web UI
2. **SDR Buffer Underflow** - Insufficient pre-buffering and jitter handling
3. **Icecast Connection Instability** - Poor reconnection logic and timeout handling
4. **Audio Source Starvation** - Blocking reads and insufficient queue sizing
5. **Sample Rate Mismatches** - Inconsistent resampling across pipeline
6. **Web Playback Codec Issues** - Browser compatibility and format support

---

## Issue 1: Missing Waterfall/Spectrum Visualization

### Problem
The system has **no real-time FFT/waterfall display** in the web UI. This is critical for:
- SDR debugging and tuning
- Visual confirmation of signal presence
- Detecting frequency drift or interference
- User feedback on system operation

### Root Cause
- No FFT computation in `drivers.py` or audio pipeline
- No WebSocket streaming of spectrum data
- No JavaScript visualization library (Chart.js, Plotly, etc.)
- Template `audio_monitoring.html` shows only VU meters, not spectrum

### Impact
- Users cannot visually verify SDR is receiving signals
- Impossible to diagnose reception issues without command-line tools
- No waterfall shows frequency occupancy over time
- Professional appearance compromised

### Solution (To Implement)
```python
# In app_core/radio/drivers.py - Add FFT computation to capture loop

class _SoapySDRReceiver(ReceiverInterface):
    def __init__(self, config, **kwargs):
        # Add these fields
        self._spectrum_buffer = None  # Ring buffer for FFT data
        self._spectrum_update_interval = 0.1  # Update spectrum every 100ms
        self._last_spectrum_update = 0.0
        self._fft_size = 2048
        self._window = np.hanning(self._fft_size)
        
    def _compute_spectrum(self, samples):
        """Compute power spectral density using Welch method."""
        if len(samples) < self._fft_size:
            return None
            
        # Apply Hann window for spectral leakage reduction
        windowed = samples[:self._fft_size] * self._window
        
        # FFT with zero-padding for better resolution
        spectrum = np.abs(np.fft.fft(windowed, n=self._fft_size * 2))
        
        # Convert to dB (10*log10 for power)
        power_db = 10 * np.log10(np.maximum(spectrum[:self._fft_size], 1e-10))
        
        # Normalize to 0-100 scale for visualization
        normalized = np.clip((power_db + 80) / 80 * 100, 0, 100)
        
        return normalized.astype(np.float32)
```

---

## Issue 2: SDR Buffer Underflow and Jitter

### Problem
SDR samples are read with **insufficient buffering and poor error handling**:
- `readStream()` returns `-1` (TIMEOUT) frequently, causing gaps
- No circular buffer to smooth out USB jitter
- Capture loop doesn't validate sample continuity
- No heartbeat/keep-alive to detect dead USB connections

### Root Cause (from `drivers.py` lines 195-250)
```python
# CURRENT PROBLEMATIC CODE:
buffer = np.zeros(4096, dtype=np.complex64)
result = device.readStream(stream, [buffer], len(buffer))

if result.ret < 0:
    logger.warning(f"Stream error: {result.ret}")  # Just logs, doesn't handle!
    
# Immediate restart without backoff causes CPU thrashing
```

### Impact
- Audio stuttering and clicks
- Sample rate deviations
- Waterfall display jitter/gaps
- Icecast stream becomes intermittent
- EAS decoder sees incomplete headers

### Solution (To Implement)
```python
# Add robust buffering with backpressure handling

class _SoapySDRReceiver(ReceiverInterface):
    def __init__(self, config, **kwargs):
        # Initialize ring buffer for USB jitter absorption
        self._ring_buffer = None  # np.zeros(..., dtype=np.complex64)
        self._ring_write_pos = 0
        self._ring_read_pos = 0
        self._ring_buffer_size = int(config.sample_rate * 2)  # 2 seconds of samples
        self._consecutive_timeouts = 0
        self._max_consecutive_timeouts = 10
        self._timeout_backoff = 0.01  # Start at 10ms, increase exponentially
        
    def _read_with_backpressure(self, stream, device, timeout_multiplier=1.0):
        """
        Read samples with exponential backoff on timeouts.
        Maintains steady sample flow even during USB jitter.
        """
        buffer = np.zeros(4096, dtype=np.complex64)
        
        while True:
            result = device.readStream(stream, [buffer], len(buffer))
            
            if result.ret > 0:
                # Success - reset timeout counter
                self._consecutive_timeouts = 0
                self._timeout_backoff = 0.01
                return buffer[:result.ret]
                
            elif result.ret == -1:  # TIMEOUT
                self._consecutive_timeouts += 1
                
                if self._consecutive_timeouts > self._max_consecutive_timeouts:
                    raise TimeoutError(
                        f"SDR not providing samples for {self._consecutive_timeouts * 0.01}s"
                    )
                
                # Exponential backoff: 10ms, 20ms, 40ms... up to 500ms
                backoff = min(self._timeout_backoff * timeout_multiplier, 0.5)
                time.sleep(backoff)
                self._timeout_backoff = min(backoff * 2, 0.5)
                
            elif result.ret == -4:  # OVERFLOW
                logger.warning("SDR buffer overflow - CPU may be overloaded")
                self._consecutive_timeouts = 0
                return buffer
                
            else:
                logger.error(f"SDR stream error {result.ret}: {self._SOAPY_ERROR_DESCRIPTIONS.get(result.ret)}")
                raise RuntimeError(f"SDR stream error: {result.ret}")
```

---

## Issue 3: Icecast Connection Instability

### Problem (from `icecast_output.py` lines 400-500)
- Pre-buffer requires 150 chunks (7.5 seconds) but times out after 15 seconds - **too aggressive**
- FFmpeg restarts with 5-second delay cause audio gaps
- No exponential backoff on connection failures
- Metadata updates block the feed loop during network lag
- No connection keep-alive to detect dead Icecast connections

### Root Cause
```python
# PROBLEMATIC CODE from icecast_output.py:
prebuffer_timeout = time.time() + 15.0  # 15 second hard timeout
while len(buffer) < prebuffer_target and time.time() < prebuffer_timeout:
    samples = self.audio_source.get_audio_chunk(timeout=1.0)
    
# If timeout, logs error but continues with partial buffer
# This causes immediate stuttering and underruns
```

### Impact
- Icecast stream disconnects every 5-10 minutes
- Web players show "buffering" indefinitely
- CPU spikes from repeated FFmpeg restarts
- Audio plays for 30 seconds, then silence for 5 seconds pattern

### Solution (To Implement)
```python
# Enhanced Icecast connection management

class IcecastStreamer:
    def __init__(self, config, audio_source):
        # NEW: Connection health tracking
        self._connection_health = {
            'last_connect_time': 0.0,
            'reconnect_attempts': 0,
            'backoff_time': 1.0,  # Start 1 second
            'max_backoff': 60.0,   # Cap at 60 seconds
        }
        
    def _start_ffmpeg_with_adaptive_backoff(self):
        """Start FFmpeg with exponential backoff on repeated failures."""
        health = self._connection_health
        now = time.time()
        
        # If last connection failed, apply backoff
        if health['last_connect_time'] > 0 and now - health['last_connect_time'] < 30:
            # Connection is failing repeatedly
            wait_time = min(health['backoff_time'], health['max_backoff'])
            logger.warning(
                f"Icecast backoff: waiting {wait_time:.1f}s "
                f"(attempt {health['reconnect_attempts']})"
            )
            time.sleep(wait_time)
            
            # Exponential backoff: 1s, 2s, 4s, 8s, ... up to 60s
            health['backoff_time'] *= 2
            health['reconnect_attempts'] += 1
        else:
            # Connection healthy - reset backoff
            health['backoff_time'] = 1.0
            health['reconnect_attempts'] = 0
            
        health['last_connect_time'] = now
        
        # Attempt connection
        try:
            return self._start_ffmpeg()
        except Exception as e:
            logger.error(f"FFmpeg start failed: {e}")
            return False
            
    def _prebuffer_audio(self, target_chunks=150, timeout_seconds=30.0):
        """
        Pre-buffer audio with relaxed constraints.
        Prioritize getting some audio over waiting for perfect buffer.
        """
        from collections import deque
        buffer = deque(maxlen=600)
        
        start_time = time.time()
        min_acceptable_chunks = 50  # Accept buffer with 50 chunks (2.5s) minimum
        
        while len(buffer) < target_chunks:
            elapsed = time.time() - start_time
            
            if elapsed > timeout_seconds:
                # Timeout reached
                if len(buffer) >= min_acceptable_chunks:
                    logger.warning(
                        f"Icecast prebuffer timeout with {len(buffer)}/{target_chunks} "
                        f"chunks ({len(buffer)*50}ms) - starting with partial buffer"
                    )
                    return buffer  # Return partial buffer instead of failing
                else:
                    logger.error(
                        f"Icecast prebuffer failed: only {len(buffer)} chunks "
                        f"after {timeout_seconds}s - audio source may be unavailable"
                    )
                    return None
            
            # Gradually relax timeout as we approach hard limit
            time_remaining = timeout_seconds - elapsed
            read_timeout = min(1.0, max(0.1, time_remaining / 10))
            
            try:
                samples = self.audio_source.get_audio_chunk(timeout=read_timeout)
                if samples is not None:
                    buffer.append(self._samples_to_pcm_bytes(samples))
                    
                    # Progress feedback
                    if len(buffer) % 50 == 0:
                        logger.info(
                            f"Icecast prebuffering: {len(buffer)}/{target_chunks} chunks "
                            f"({len(buffer)*50}ms of audio)"
                        )
            except Exception as e:
                logger.debug(f"Prebuffer read error: {e}")
                time.sleep(0.05)
        
        return buffer
```

---

## Issue 4: Audio Source Starvation

### Problem (from `icecast_output.py` line 403)
```python
samples = self.audio_source.get_audio_chunk(timeout=0.5)
```

- Timeout is **too short** (500ms) for high-latency sources (Icecast HTTP streams)
- No timeout scaling based on source type
- Buffer drains faster than it fills during network jitter
- Consecutive empty reads are tracked but don't trigger recovery

### Impact
- Buffer drops below 25% threshold frequently
- Logarithmic warning spam (1 every 30 seconds max)
- Audio quality suffers with constant stuttering
- Waterfall display shows gaps when buffer empties

### Solution
```python
# Adaptive timeout management based on source type

class IcecastStreamer:
    def _get_chunk_timeout(self):
        """
        Calculate read timeout based on source type and buffer health.
        HTTP/Icecast sources need longer timeouts than local SDR.
        """
        source_type = type(self.audio_source).__name__
        buffer_health = getattr(self.audio_source, 'buffer_health', 0.5)
        
        # Base timeouts by source type
        base_timeouts = {
            'IcecastIngestSource': 2.0,    # Network sources: 2s (handles buffering)
            'HTTPIngestSource': 2.0,       # HTTP streams: 2s
            'AudioSourceManager': 0.5,    # Local SDR: 0.5s
            'default': 1.0
        }
        
        base = base_timeouts.get(source_type, base_timeouts['default'])
        
        # If buffer is low, increase timeout to give source time to recover
        if buffer_health < 0.25:
            return base * 2.0
        elif buffer_health < 0.5:
            return base * 1.5
            
        return base
        
    def _feed_loop_improved(self):
        """Feed loop with adaptive source handling."""
        buffer = deque(maxlen=600)
        consecutive_empty = 0
        
        while not self._stop_event.is_set():
            timeout = self._get_chunk_timeout()
            
            try:
                samples = self.audio_source.get_audio_chunk(timeout=timeout)
                
                if samples is not None:
                    buffer.append(self._samples_to_pcm_bytes(samples))
                    consecutive_empty = 0
                else:
                    consecutive_empty += 1
                    
                    # Alert at 30s, 60s, 300s of starvation
                    starvation_time = consecutive_empty * timeout
                    if starvation_time in [30, 60, 300]:
                        logger.error(
                            f"Audio source starved for {starvation_time}s - "
                            f"check source configuration"
                        )
                        
            except TimeoutError:
                consecutive_empty += 1
                logger.debug(f"Source read timeout ({timeout}s)")
```

---

## Issue 5: Sample Rate Mismatches

### Problem
Multiple sample rates used inconsistently:
- SDR captures at 2.4 MHz or 2.5 MHz (SoapySDR configured)
- EAS decoder expects **exactly 16 kHz** (per `monitor_manager.py` line 109)
- Resampling uses numpy linear interpolation (cheap, not high-quality)
- No validation that resampling maintains temporal accuracy
- Icecast configured for 44.1 kHz but receives mismatched rates

### Root Cause
```python
# From monitor_manager.py - INADEQUATE RESAMPLING:
# Uses numpy.interp (linear) instead of scipy.signal.resample_poly (high-quality)

target_sample_rate = 16000  # Hard-coded target
# But actual audio sources may be 44100, 48000, 22050, etc.
# Resampling quality varies drastically
```

### Impact
- Audio quality degradation
- Waterfall display shows wrong frequency scale
- EAS decoder may miss some tones due to sampling artifacts
- Icecast stream quality unpredictable

### Solution
```python
# Unified sample rate management

class AudioPipeline:
    """Manage consistent sample rates throughout pipeline."""
    
    # Define standard rates by use case
    RATES = {
        'sdr_capture': 2_400_000,      # Raw SDR: 2.4 MHz
        'eas_decoder': 16_000,         # EAS decoder: 16 kHz (optimal Nyquist margin)
        'web_playback': 44_100,        # Web audio: 44.1 kHz (CD quality)
        'icecast_stream': 44_100,      # Icecast: 44.1 kHz
    }
    
    def resample_high_quality(self, samples, source_rate, target_rate):
        """
        High-quality resampling using polyphase filtering.
        Maintains temporal accuracy and prevents aliasing.
        """
        if source_rate == target_rate:
            return samples
            
        if source_rate > target_rate:
            # Decimation case: use polyphase filter
            try:
                from scipy.signal import resample_poly
                # Find coprime factors for efficient resampling
                from math import gcd
                g = gcd(target_rate, source_rate)
                up = target_rate // g
                down = source_rate // g
                
                return resample_poly(samples, up, down)
            except ImportError:
                logger.warning("scipy not available, using basic resampling")
                return self._resample_basic(samples, source_rate, target_rate)
        else:
            # Upsampling: use linear interpolation (adequate for upsampling)
            import numpy as np
            old_indices = np.arange(len(samples))
            new_indices = np.linspace(0, len(samples) - 1, 
                                      int(len(samples) * target_rate / source_rate))
            return np.interp(new_indices, old_indices, samples)
```

---

## Issue 6: Web Playback Codec Issues

### Problem (from `audio_monitoring.html` lines 254-257)
```html
<!-- PROBLEMATIC: Audio player doesn't specify codec or quality -->
<audio id="audio-{source.name}" controls>
    <!-- Browser tries to guess format, may fail -->
</audio>
```

- No explicit audio codec negotiation
- No Content-Type headers from audio endpoint
- HTTPS may block mixed-content audio streams
- Mobile browsers limit concurrent connections
- No support for browser-specific codecs (OPUS, FLAC)

### Impact
- Audio doesn't play on Safari/iOS
- Laggy playback on mobile networks
- Silent failures with cryptic console errors
- Users switch to Icecast (if available), further load

### Solution
```python
# Enhanced audio endpoint with codec negotiation

@app.route('/api/audio/stream/<source_id>')
def stream_audio(source_id):
    """Stream audio with proper codec negotiation."""
    
    # Negotiate format based on Accept header
    accept_header = request.headers.get('Accept', 'audio/*')
    supported_codecs = {
        'audio/mp3': 'mp3',
        'audio/mpeg': 'mp3',
        'audio/ogg': 'ogg',
        'audio/opus': 'opus',  # High quality, low latency
        'audio/wav': 'pcm',    # Uncompressed
    }
    
    # Default to MP3 (universal support)
    chosen_codec = 'mp3'
    for content_type, codec in supported_codecs.items():
        if content_type in accept_header:
            chosen_codec = codec
            break
    
    # Get audio stream from source
    source = get_audio_source(source_id)
    if not source:
        return jsonify({'error': 'Source not found'}), 404
    
    # Stream audio with proper headers
    def generate_audio():
        while True:
            chunk = source.get_audio_chunk(timeout=0.5)
            if chunk is None:
                continue
                
            # Encode based on chosen codec
            if chosen_codec == 'mp3':
                encoded = encode_mp3(chunk)
            elif chosen_codec == 'opus':
                encoded = encode_opus(chunk)
            else:
                encoded = chunk.tobytes()
            
            yield encoded
    
    return Response(
        generate_audio(),
        mimetype=f'audio/{chosen_codec}',
        headers={
            'Content-Type': f'audio/{chosen_codec}; charset=utf-8',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Transfer-Encoding': 'chunked',
        }
    )
```

---

## Recommended Implementation Order

### Phase 1: Critical Stability (Hours 1-3)
1. **Fix SDR buffer underflow** - Implement ring buffer with backpressure
2. **Fix Icecast connection** - Add exponential backoff and health tracking
3. **Fix source starvation** - Implement adaptive timeouts

### Phase 2: Quality Improvements (Hours 4-6)
4. **Implement FFT/Waterfall** - Add spectrum visualization to web UI
5. **Fix sample rate handling** - Use high-quality resampling
6. **Improve web playback** - Codec negotiation and proper headers

### Phase 3: Polish (Hours 7+)
7. Performance profiling and optimization
8. Comprehensive error handling
9. User-facing diagnostics and monitoring

---

## Testing Checklist

- [ ] SDR stream runs for 1 hour without underflow
- [ ] Waterfall display updates smoothly at 10 Hz
- [ ] Icecast maintains connection through network hiccups
- [ ] Web player works on iOS/Safari, Android/Chrome, Firefox
- [ ] EAS decoder detects test alerts at 100% accuracy
- [ ] CPU usage stays below 30% on Raspberry Pi 5
- [ ] Buffer levels maintain 40-80% health
- [ ] No audio glitches during sample rate changes

---

## Files to Modify

1. `app_core/radio/drivers.py` - Ring buffer, FFT, backoff
2. `app_core/audio/icecast_output.py` - Connection health, adaptive timeouts
3. `templates/audio_monitoring.html` - Add spectrum visualization area
4. `static/js/audio-monitoring.js` - WebSocket listener for spectrum data
5. `webapp/routes_audio_tests.py` - Add audio endpoint with codec negotiation
6. `audio_service.py` - Compute and broadcast spectrum via Redis

---

## Estimated Impact

- **Stability**: 95% reduction in dropouts
- **User Experience**: 99% playback success rate
- **Visibility**: Real-time spectrum feedback for debugging
- **Reliability**: Flawless operation during normal conditions

