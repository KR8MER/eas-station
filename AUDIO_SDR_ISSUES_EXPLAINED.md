# Complete Analysis: Audio & SDR Issues

## Executive Summary

You're experiencing **THREE interconnected issues** that all stem from the **same root cause**:

1. ❌ MP3 audio streams don't show up as mount points in Icecast
2. ❌ Waterfall display doesn't look right (frequency scale is wrong)
3. ❌ Audio from SDR sounds like a high-pitched, steady tone/squeal

**Root Cause:** `RadioReceiver.sample_rate` is configured with **audio sample rate (16-44 kHz)** instead of **IQ sample rate (~2.4 MHz)**

---

## Issue #1: MP3 Streams Not Appearing in Icecast

### What's Happening

When you check Icecast at `http://localhost:8001/`, the expected mount points (e.g., `/WNCI.mp3`, `/WIMT.mp3`) don't appear.

### Root Cause

**Location:** `app_core/audio/icecast_output.py:395-462`

The Icecast streaming process has this flow:
1. Audio source starts generating data
2. FFmpeg **pre-buffers 7.5 seconds** of audio (150 chunks)
3. Once buffer is full → FFmpeg **connects to Icecast**
4. **Only after connection** → Mount point appears in Icecast

**The Problem:**
```python
# Pre-buffer with 30-second timeout
prebuffer_timeout = time.time() + 30.0

while len(buffer) < prebuffer_target and time.time() < prebuffer_timeout:
    samples = self.audio_source.get_audio_chunk(timeout=read_timeout)
    if samples is not None:
        buffer.append(samples)

# If timeout expires without enough data...
if len(buffer) < min_acceptable_chunks:
    logger.error(
        f"Pre-buffer failed for mount {self.config.mount}: only {len(buffer)} chunks "
        f"after {prebuffer_attempts} attempts. Audio source may not be providing data."
    )
    # FFmpeg NEVER CONNECTS → No mount point!
```

**Why Audio Source Fails:**
- SDR demodulation is broken (due to wrong sample rate)
- Produces garbage/squeal instead of valid audio
- Or produces no audio at all
- Pre-buffer timeout expires → FFmpeg never connects

### The Connection Chain

```
Audio Source (SDR) → Demodulation → Audio Samples → Pre-buffer → FFmpeg → Icecast
     ❌                  ❌              ❌           ❌         NEVER     NEVER
   (broken)           (broken)        (garbage)    (timeout) CONNECTS  REGISTERS
```

---

## Issue #2: Waterfall Display Doesn't Look Right

### What You're Seeing

The waterfall display in the web UI (http://localhost:5000/settings/radio) shows:
- **Wrong frequency scale** (shows kHz range instead of MHz range)
- **Tiny bandwidth** (a few kHz instead of 2+ MHz)
- Doesn't look like a proper RF waterfall (like SDR# displays)

### Root Cause

**Location:** `audio_service.py:747-861` (waterfall generation)

The waterfall is generated from IQ samples and published to Redis every 5 seconds:

```python
# Get receiver config for frequency info
config = receiver_instance.config if hasattr(receiver_instance, 'config') else None
frequency_hz = config.frequency_hz if config else 0
sample_rate = config.sample_rate if config else 0  # ⚠️ WRONG VALUE!

spectrum_payload = {
    'identifier': identifier,
    'spectrum': normalized.tolist(),
    'fft_size': 2048,
    'sample_rate': sample_rate,  # ⚠️ If this is 16000 instead of 2400000...
    'center_frequency': frequency_hz,
    'freq_min': frequency_hz - (sample_rate / 2),  # ⚠️ Wrong!
    'freq_max': frequency_hz + (sample_rate / 2),  # ⚠️ Wrong!
}
```

### The Math Breakdown

**If `sample_rate = 16000` Hz (WRONG):**
- Nyquist frequency = 8 kHz
- Frequency range displayed = center ± 8 kHz
- Example: 97.9 MHz FM station shows as **97,892 to 97,908 kHz** (16 kHz total width)
- **This is MICROSCOPIC for FM!** (FM needs ~200 kHz bandwidth)

**What it SHOULD be with `sample_rate = 2400000` Hz (CORRECT):**
- Nyquist frequency = 1.2 MHz
- Frequency range displayed = center ± 1.2 MHz
- Example: 97.9 MHz FM station shows as **96.7 to 99.1 MHz** (2.4 MHz width)
- **Now you can see the entire FM station and adjacent channels**

### Frontend Rendering

**Location:** `static/js/audio_monitoring.js:649-723`

```javascript
function drawWaterfall(sourceId, spectrogramData, sampleRate, fftSize) {
    // ...

    // Frequency axis labels
    const nyquist = sampleRate / 2;  // If sampleRate=16000, nyquist=8000 Hz
    const freqStep = nyquist / 4;

    for (let i = 0; i <= 4; i++) {
        const freq = (i * freqStep) / 1000; // Convert to kHz
        const x = (i / 4) * width;
        ctx.fillText(freq.toFixed(1) + ' kHz', x + 2, height - 4);
    }
}
```

**With wrong sample rate (16 kHz):**
- Displays: `0.0 kHz`, `2.0 kHz`, `4.0 kHz`, `6.0 kHz`, `8.0 kHz`
- **This is audio frequency range, not RF!**

**With correct sample rate (2.4 MHz):**
- Displays: `0.0 kHz`, `300.0 kHz`, `600.0 kHz`, `900.0 kHz`, `1200.0 kHz`
- **This shows proper RF bandwidth** (though labels should probably be in MHz)

### Comparison: Wrong vs. Right

| Aspect | Wrong (16 kHz IQ rate) | Correct (2.4 MHz IQ rate) |
|--------|----------------------|---------------------------|
| **Bandwidth shown** | 16 kHz total | 2.4 MHz total |
| **For 97.9 MHz FM** | 97,892 - 97,908 kHz | 96.7 - 99.1 MHz |
| **Can see FM station?** | No, way too narrow | Yes, full station + neighbors |
| **Can see stereo pilot?** | No (38 kHz outside range) | Yes (within range) |
| **Looks like SDR# waterfall?** | ❌ No, looks broken | ✅ Yes, proper RF display |

---

## Issue #3: High-Pitched Squeal from SDR Audio

### What You're Hearing

When you listen to the Icecast stream, instead of clear FM radio audio, you hear:
- High-pitched, steady tone/squeal
- Or distorted, garbled audio
- Or silence

### Root Cause #1: Broken FM Demodulation

**Location:** `app_core/radio/demodulation.py:102-147` (FM demodulator)

FM demodulation uses **phase discrimination** on IQ samples:

```python
def demodulate(self, iq_samples: np.ndarray) -> Tuple[np.ndarray, Optional[RBDSData]]:
    iq_array = np.asarray(iq_samples, dtype=np.complex64)
    if self._prev_sample is not None:
        iq_array = np.concatenate(([self._prev_sample], iq_array))
    self._prev_sample = iq_array[-1]

    # Phase discrimination (requires MHz-rate IQ samples!)
    discriminator = np.angle(iq_array[1:] * np.conj(iq_array[:-1]))
    multiplex = discriminator / np.pi  # FM multiplex signal

    # Extract L+R audio (0-15 kHz)
    audio_signal = self._lpr_filter_signal(multiplex)

    if self._stereo_enabled:
        # Decode L-R from 38 kHz subcarrier (needs 76+ kHz Nyquist!)
        stereo_audio = self._decode_stereo(multiplex, sample_indices)

    if self._rbds_enabled:
        # Decode RBDS from 57 kHz subcarrier (needs 114+ kHz Nyquist!)
        rbds_data = self._extract_rbds(multiplex, sample_indices)
```

**The Math Requirements:**

| Component | Frequency | Required Nyquist | Required Sample Rate |
|-----------|-----------|------------------|---------------------|
| **FM Audio (L+R)** | 0-15 kHz | 30 kHz | 60+ kHz |
| **Stereo Pilot** | 19 kHz | 38 kHz | 76+ kHz |
| **Stereo Subcarrier (L-R)** | 23-53 kHz (DSB-SC) | 106 kHz | 212+ kHz |
| **RBDS Subcarrier** | 57 kHz ± 2.4 kHz | 120 kHz | 240+ kHz |
| **Typical RTL-SDR** | Full FM multiplex | **1.2 MHz** | **2.4 MHz** |

**When `sample_rate = 16000` Hz (WRONG):**
- Nyquist = **8 kHz** (way too low!)
- Can't capture stereo pilot (19 kHz) ❌
- Can't decode stereo subcarrier (38 kHz) ❌
- Can't decode RBDS (57 kHz) ❌
- Phase discrimination math breaks down
- Produces **garbage output → high-pitched squeal**

**When `sample_rate = 2400000` Hz (CORRECT):**
- Nyquist = **1.2 MHz** ✅
- Can capture entire FM multiplex ✅
- Stereo decoding works ✅
- RBDS decoding works ✅
- Phase discrimination produces clean audio ✅

### Root Cause #2: Wrong Demodulator Configuration

**Location:** `app_core/audio/sources.py:200-214` (SDR source adapter)

```python
# Create demodulator if audio output is enabled
if self._receiver_config.audio_output and self._receiver_config.modulation_type != 'IQ':
    demod_config = DemodulatorConfig(
        modulation_type=self._receiver_config.modulation_type,
        sample_rate=self._receiver_config.sample_rate,  # ⚠️ Should be 2.4MHz!
        audio_sample_rate=self.config.sample_rate,      # ⚠️ Should be 24-48kHz!
        stereo_enabled=self._receiver_config.stereo_enabled,
        deemphasis_us=self._receiver_config.deemphasis_us,
        enable_rbds=self._receiver_config.enable_rbds
    )
    self._demodulator = create_demodulator(demod_config)
```

**The cascading failure:**
1. `RadioReceiver.sample_rate` = 16000 (should be 2400000)
2. Demodulator configured with wrong IQ rate
3. FM demodulation fails → produces squeal
4. Resampling to audio rate makes it worse
5. FFmpeg encodes the garbage
6. Icecast streams the squeal

### Root Cause #3: FFmpeg Sample Rate Mismatch

**Location:** `app_core/audio/icecast_output.py:285-291`

Even if demodulation worked, there's another issue:

```python
cmd = [
    'ffmpeg',
    '-f', 's16le',  # Input: 16-bit PCM
    '-ar', str(self.config.sample_rate),  # ⚠️ If this doesn't match actual audio...
    '-ac', str(max(1, int(self.config.channels))),
    '-i', 'pipe:0',
    # ...
]
```

**The mismatch:**
- `AudioSourceConfig.sample_rate` = 16000 (configured for EAS decoding)
- Actual audio from demodulator = 48000 (WFM stereo output)
- FFmpeg thinks input is 16 kHz → resamples to output rate
- **Pitch shift!** Audio plays too fast → **high-pitched squeal**

### The Complete Failure Chain

```
RTL-SDR Hardware
    ↓ (produces IQ samples at 2.4 MHz)
Wrong config: sample_rate = 16000 Hz
    ↓
FM Demodulator
    ↓ (expects 2.4 MHz, gets told it's 16 kHz)
Broken phase discrimination
    ↓ (produces garbage/squeal)
Resampling to audio rate
    ↓ (makes it worse)
FFmpeg with wrong sample rate
    ↓ (pitch shift)
Icecast stream
    ↓
🔊 HIGH-PITCHED SQUEAL
```

---

## The Configuration Tables

### Current (Broken) Configuration

| Parameter | Current Value | Correct Value | Impact |
|-----------|--------------|---------------|--------|
| `RadioReceiver.sample_rate` | 16000 Hz | 2400000 Hz | ❌ Waterfall wrong, demod broken |
| `DemodulatorConfig.sample_rate` | 16000 Hz | 2400000 Hz | ❌ FM demod produces squeal |
| `DemodulatorConfig.audio_sample_rate` | 16000 Hz | 48000 Hz | ❌ Wrong output rate |
| `AudioSourceConfig.sample_rate` | 16000 Hz | 48000 Hz | ❌ FFmpeg pitch shift |
| `IcecastConfig.sample_rate` | 16000 Hz | 48000 Hz | ❌ Wrong encoding rate |

### Correct Configuration

| Stream Type | IQ Sample Rate | Audio Output Rate | Notes |
|-------------|----------------|-------------------|-------|
| **RTL-SDR WFM Stereo** | 2400000 Hz | 48000 Hz | Full bandwidth, stereo |
| **RTL-SDR WFM Mono** | 2400000 Hz | 32000 Hz | Full bandwidth, mono |
| **RTL-SDR NFM** | 2400000 Hz | 24000 Hz | Narrowband FM |
| **RTL-SDR AM** | 2400000 Hz | 24000 Hz | AM broadcast |
| **HTTP Stream** | N/A (no IQ) | 44100 or 48000 Hz | Match native stream rate |

---

## How to Fix

### Quick Fix (Recommended)

```bash
cd /home/user/eas-station
./fix_all_audio_issues.sh
```

This script will:
1. Diagnose current configuration
2. Fix SDR IQ sample rates (→ 2.4 MHz)
3. Fix audio output rates (→ 24-48 kHz based on modulation)
4. Fix HTTP stream rates (→ safe default or auto-detect)
5. Restart services
6. Verify fixes

### Manual Fix

If you prefer to fix manually:

```bash
# 1. Diagnose
docker compose exec -T alerts-db psql -U postgres -d alerts < diagnose_all_streams.sql

# 2. Apply fixes
docker compose exec -T alerts-db psql -U postgres -d alerts < fix_all_stream_sample_rates.sql

# 3. Auto-detect HTTP stream rates (optional but recommended)
./detect_stream_sample_rates.sh

# 4. Restart services
docker compose restart sdr-service

# 5. Verify
docker compose exec -T alerts-db psql -U postgres -d alerts < diagnose_all_streams.sql
```

---

## Verification Steps

After running the fix, verify each issue is resolved:

### 1. Check Icecast Mount Points

```bash
# Open in browser
http://localhost:8001/

# Should see mount points like:
# /WNCI.mp3
# /WIMT.mp3
# etc.
```

### 2. Check Waterfall Display

```bash
# Open in browser
http://localhost:5000/settings/radio

# Should see:
# - Frequency axis in MHz range (e.g., "96.7 MHz" to "99.1 MHz")
# - Colorful scrolling waterfall
# - Strong signals appearing as bright colors
# - Looks like a proper RF spectrum display (like SDR#)
```

### 3. Check Audio Quality

```bash
# Listen to Icecast stream in VLC/browser
http://localhost:8001/WNCI.mp3

# Should hear:
# ✅ Clear FM radio audio
# ✅ Stereo separation (if stereo enabled)
# ✅ No squeal or high-pitched tones
# ✅ Normal speaking/music speed
```

### 4. Check Logs

```bash
docker compose logs -f sdr-service | grep -i "sample.*rate\|demod\|icecast"

# Should see lines like:
# "Created WFM demodulator for receiver: rtlsdr0"
# "IQ sample rate: 2400000 Hz"
# "Audio output rate: 48000 Hz"
# "Started Icecast stream for WNCI"
```

---

## Technical Background

### Why 2.4 MHz for RTL-SDR?

RTL-SDR dongles typically support IQ sample rates from 225 kHz to 3.2 MHz. The sweet spot is **2.4 MHz** because:

1. **Captures full FM broadcast channel** (200 kHz bandwidth)
2. **Includes adjacent channels** (for scanning/monitoring)
3. **Supports all FM subcarriers:**
   - Main audio (L+R): 0-15 kHz
   - Stereo pilot: 19 kHz
   - Stereo difference (L-R): 23-53 kHz (DSB-SC around 38 kHz)
   - RDS/RBDS: 57 kHz ± 2.4 kHz
4. **Good balance** between quality and USB bandwidth

### FM Multiplex Signal Structure

```
Frequency Range     Component           Purpose
-----------------------------------------------------------------
0 - 15 kHz          L+R (mono audio)    Main program audio
19 kHz              Pilot tone          Stereo synchronization
23 - 53 kHz         L-R (DSB-SC)        Stereo difference signal
57 kHz ± 2.4 kHz    RBDS/RDS            Digital data (PS, RT, etc.)
```

**To demodulate this properly:**
- Need at least 120 kHz Nyquist frequency (240 kHz sample rate)
- **Typical/optimal: 2.4 MHz** (gives plenty of headroom)

### Why Audio Output is 24-48 kHz

After FM demodulation, the audio signal is:
- **Mono (L+R):** 0-15 kHz → needs 30+ kHz sample rate → use **32 kHz**
- **Stereo (L+R and L-R):** 0-15 kHz per channel → use **48 kHz** (CD quality)

Higher quality = higher sample rate:
- **24 kHz:** Minimum for NFM/AM
- **32 kHz:** Good for WFM mono
- **44.1 kHz:** CD quality (HTTP streams often use this)
- **48 kHz:** Professional quality (WFM stereo, recommended)

---

## Summary

All three issues stem from one root cause: **wrong sample rate configuration**.

| Issue | Symptom | Cause | Fix |
|-------|---------|-------|-----|
| **No Icecast mounts** | Mount points missing | Audio source broken → FFmpeg never connects | Fix sample rates → demod works → FFmpeg connects |
| **Waterfall wrong** | kHz scale instead of MHz, tiny bandwidth | IQ rate is 16kHz not 2.4MHz | Set `RadioReceiver.sample_rate = 2400000` |
| **Audio squeal** | High-pitched tone, distorted | FM demod can't work at 16kHz Nyquist | Set IQ rate to 2.4MHz, audio output to 48kHz |

**One fix solves all three problems!**

Run: `./fix_all_audio_issues.sh`
