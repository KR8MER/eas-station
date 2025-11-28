# Audio Squeal Fix - Comprehensive Guide

## Problem

All Icecast streams producing high-pitched squeal instead of normal audio. This affects:
- **SDR streams** (FM/AM radio from RTL-SDR, etc.)
- **HTTP streams** (iHeart, other internet radio)

Issue appeared after moving audio service to separate container.

## Root Cause

After containerization, **two separate sample rate configuration errors** occurred:

### 1. SDR Receivers - IQ Sample Rate Issue
- `RadioReceiver.sample_rate` was set to audio rates (~16-44 kHz)
- Should be SDR IQ rates (~2.4 MHz for most SDR hardware)
- **Effect**: Demodulator misinterprets IQ data → distorted/squealing audio

### 2. HTTP Streams - Audio Sample Rate Issue
- `AudioSourceConfig.sample_rate` was set to 16 kHz (EAS decoding rate)
- Should be native stream rate (varies: 32kHz, 44.1kHz, 48kHz, etc.)
- **Effect**: FFmpeg resamples to wrong rate → pitch-shifted squealing audio

## Fix Tools

### Quick Fix (Recommended)
```bash
./fix-audio-squeal.sh
```

Interactive script that:
1. Runs diagnostic to show issues
2. Fixes SDR IQ sample rates → 2.4 MHz
3. Fixes HTTP streams → safe default (48 kHz)
4. **Optionally** auto-detects precise HTTP stream rates
5. Restarts audio service

### Individual Tools

#### 1. `diagnose_all_streams.sql` - Diagnostic Only
```bash
docker-compose exec -T alerts-db psql -U postgres -d alerts < diagnose_all_streams.sql
```

Shows current configuration with ❌ markers for issues. No changes made.

#### 2. `fix_all_stream_sample_rates.sql` - Apply Basic Fixes
```bash
docker-compose exec -T alerts-db psql -U postgres -d alerts < fix_all_stream_sample_rates.sql
```

Fixes:
- SDR IQ rates: < 100 kHz → 2.4 MHz
- HTTP audio rates: < 32 kHz → **48 kHz (safe default)**
- SDR audio output: Based on modulation (24-48 kHz)

**Note**: Uses 48 kHz default for HTTP streams. For precise rates, use auto-detection.

#### 3. `detect_stream_sample_rates.sh` - Auto-Detect HTTP Streams
```bash
./detect_stream_sample_rates.sh
```

Uses `ffprobe` to query each HTTP stream's actual native sample rate:
- Probes each stream URL
- Detects actual audio format
- Updates database with precise rates
- **Recommended for optimal quality**

Can be run standalone or as part of `fix-audio-squeal.sh`.

#### 4. `fix_audio_squeal.py` - Python Diagnostic Tool
```bash
python3 fix_audio_squeal.py
```

Comprehensive Python-based diagnostic with detailed recommendations.

## Usage Scenarios

### Scenario 1: Quick Fix (Most Users)
```bash
./fix-audio-squeal.sh
# Answer 'y' to all prompts including auto-detection
```

### Scenario 2: Manual Step-by-Step
```bash
# 1. Diagnose
docker-compose exec -T alerts-db psql -U postgres -d alerts < diagnose_all_streams.sql

# 2. Apply basic fixes
docker-compose exec -T alerts-db psql -U postgres -d alerts < fix_all_stream_sample_rates.sql

# 3. Auto-detect HTTP stream rates (optional but recommended)
./detect_stream_sample_rates.sh

# 4. Restart
docker-compose restart sdr-service
```

### Scenario 3: Only Fix HTTP Streams
```bash
./detect_stream_sample_rates.sh
docker-compose restart sdr-service
```

## Technical Details

### Correct Sample Rates

#### SDR Receivers (IQ Sample Rate)
- **RTL-SDR**: 2.4 MHz typical (range: 225 kHz - 3.2 MHz)
- **AirSpy**: 2.5-10 MHz
- **HackRF**: 2-20 MHz
- **SDRplay**: 2-10 MHz

**Rule**: Always > 100 kHz (typically in MHz range)

#### SDR Audio Output (After Demodulation)
- **WFM stereo**: 48 kHz, 2 channels
- **WFM mono**: 32 kHz, 1 channel
- **NFM/AM**: 24 kHz, 1 channel
- **IQ/unknown**: 44.1 kHz, 1 channel

#### HTTP Streams (Native from Source)
**Varies by stream!** Common rates:
- **48 kHz**: High quality streams
- **44.1 kHz**: CD quality (very common)
- **32 kHz**: Medium quality
- **22.05 kHz**: Low bandwidth streams

**Important**: Each stream has its own native rate. Use auto-detection for best results.

## Why Auto-Detection Matters

### Without Auto-Detection (Safe Default: 48 kHz)
- Stream is actually 44.1 kHz
- FFmpeg resamples: 44.1 kHz → 48 kHz → 44.1 kHz (for Icecast)
- Result: Works, but unnecessary resampling = quality loss

### With Auto-Detection
- Stream is detected as 44.1 kHz
- FFmpeg uses: 44.1 kHz → 44.1 kHz (pass-through)
- Result: Optimal quality, no unnecessary resampling

## Verification

After running the fix:

1. **Check Icecast Streams**
   ```
   http://localhost:8001/
   ```
   Audio should be clear, no squeal

2. **Check Logs**
   ```bash
   docker-compose logs -f sdr-service
   ```
   Look for sample rate info in startup logs

3. **Verify Database**
   ```bash
   docker-compose exec -T alerts-db psql -U postgres -d alerts < diagnose_all_streams.sql
   ```
   Should show ✅ for all entries

## Troubleshooting

### Squeal Persists After Fix

1. **Verify fix was applied**:
   ```bash
   docker-compose exec -T alerts-db psql -U postgres -d alerts < diagnose_all_streams.sql
   ```

2. **Check if service restarted**:
   ```bash
   docker-compose ps sdr-service
   # Should show recent restart time
   ```

3. **Force restart**:
   ```bash
   docker-compose restart sdr-service
   ```

4. **Check logs for errors**:
   ```bash
   docker-compose logs sdr-service | grep -i error
   ```

### Auto-Detection Fails for HTTP Stream

Possible causes:
- Stream is offline
- Stream requires authentication
- Network/firewall blocking probe

**Solution**: Manually set rate in database:
```sql
UPDATE audio_source_configs
SET config = jsonb_set(config, '{sample_rate}', '48000'::jsonb)
WHERE name = 'stream-name-here';
```

### SDR Stream Still Squealing

Check receiver sample rate directly:
```sql
SELECT identifier, sample_rate, modulation_type, audio_output
FROM radio_receivers WHERE enabled = true;
```

Should show:
- `sample_rate`: > 1000000 (e.g., 2400000)
- `audio_output`: true (if streaming audio)

## Contributing

If you discover additional sample rate issues or have improvements to the detection logic, please submit a PR!

## Related Files

- `fix-audio-squeal.sh` - Main interactive fix script
- `diagnose_all_streams.sql` - Diagnostic query
- `fix_all_stream_sample_rates.sql` - SQL fix with safe defaults
- `detect_stream_sample_rates.sh` - Auto-detect HTTP stream rates
- `fix_audio_squeal.py` - Python diagnostic tool
- `fix_sample_rates.sql` - Legacy SDR-only fix (deprecated)
