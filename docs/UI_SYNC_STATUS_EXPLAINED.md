# UI Sync Status Explained

## Question
Why is the UI showing that sync is not locked?

## Answer
**This is normal and correct behavior.** The decoder should only show "Synced" when actively receiving a SAME signal.

## Sync Status Meanings

### ⚪ **Listening** (Most Common - 99.99% of time)
```
Status: decoder_synced = False
        decoder_in_message = False
        audio_flowing = True
```

**What it means**: 
- Decoder is running and processing audio
- No SAME signal currently detected
- System is working correctly - waiting for alerts

**This is NORMAL**. EAS alerts are rare (maybe 1-2 per week).

### 🟢 **Synced** (Rare - Only During Alert Preamble)
```
Status: decoder_synced = True
        decoder_in_message = False
```

**What it means**:
- Decoder detected SAME preamble (0xAB repeated)
- About to start decoding header
- Typically lasts 0.1-0.5 seconds

**This is brief** - just the sync phase before message.

### 🔴 **Decoding Message** (Rare - Only During Alert)
```
Status: decoder_in_message = True
```

**What it means**:
- Actively decoding SAME header characters
- Reading event code, location codes, etc.
- Typically lasts 1-2 seconds

**This is the actual alert being received**.

### ⏸️ **Idle** (When Stopped)
```
Status: running = False
```

**What it means**:
- Monitor is stopped
- Not processing audio
- Use "Start Monitoring" button to activate

## Why "Not Synced" Is Normal

### SAME Signal Timeline

A typical EAS alert transmission:

```
Silence (minutes/hours)
    ↓
Preamble (0.3s) ← decoder_synced = True
    ↓
Header 1 (1.5s) ← decoder_in_message = True
    ↓
Preamble (0.3s)
    ↓
Header 2 (1.5s)
    ↓
Preamble (0.3s)
    ↓
Header 3 (1.5s)
    ↓
Attention tone (8s)
    ↓
Voice message (30-120s)
    ↓
EOM markers
    ↓
Silence (minutes/hours) ← decoder_synced = False (BACK TO NORMAL)
```

**Total alert duration**: ~40-130 seconds  
**Time between alerts**: Days to weeks  
**Percentage of time synced**: < 0.01%

### Commercial EAS Decoder Behavior

Real commercial decoders (DASDEC, Sage, etc.) work the same way:
- **Idle LED**: Green (most of time)
- **Sync LED**: Yellow (only during preamble)
- **Decode LED**: Red (only during message)

Our UI matches this professional behavior.

## How To Verify It's Working

### 1. Check Audio Flowing
```
✓ Processing at line rate (16.00 kHz)
```
This means samples are being processed correctly.

### 2. Check Samples Processed
```
Samples: 12.5M
Runtime: 13h 2m
```
If samples are increasing, decoder is working.

### 3. Check Processing Rate
```
16.0k samples/sec
```
Should match your configured sample rate.

### 4. Test With SAME Audio
To see "Synced" status:
1. Download a test SAME audio file
2. Play it through audio source
3. Watch status change: Listening → Synced → Decoding → Listening

## Common Misunderstandings

### ❌ "Sync not locked means it's broken"
**NO** - It means you're not currently receiving an alert (which is normal).

### ❌ "It should always be synced"
**NO** - Only synced during actual SAME bursts (very rare).

### ❌ "Need to restart if not synced"
**NO** - "Listening" is the correct idle state.

## When To Worry

### 🚨 Red Flags (Actual Problems)

**1. No Audio Flowing**
```
Status: ⚠️ No audio flowing
```
**Action**: Check audio sources are started.

**2. Decoder Stopped**
```
Status: ⏸️ Idle
```
**Action**: Click "Start Monitoring" button.

**3. Below Expected Rate**
```
Status: ⚠️ Below expected rate
```
**Action**: Check CPU load, audio source health.

**4. Samples Not Increasing**
```
Samples: 1234 (unchanged for minutes)
```
**Action**: Restart monitor or check audio pipeline.

## Testing Sync Status

### Create Test SAME Audio

```python
# Generate test SAME header
from app_utils.eas_decode import decode_same_audio
from app_utils.eas_fsk import encode_same_bits, generate_fsk_samples, SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ
import wave, struct

header = "ZCZC-WXR-RWT-012345+0015-1231200-NOCALL00-"
bits = encode_same_bits(header, include_preamble=True)
samples = generate_fsk_samples(
    bits, sample_rate=16000, bit_rate=float(SAME_BAUD),
    mark_freq=SAME_MARK_FREQ, space_freq=SAME_SPACE_FREQ, amplitude=20000
)

with wave.open('test_same.wav', 'wb') as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    wav.writeframes(b''.join(struct.pack('<h', s) for s in samples))
```

### Play Test File
1. Configure audio source (e.g., file player or virtual cable)
2. Play `test_same.wav`
3. Watch UI status cycle through: Listening → Synced → Decoding → Listening
4. Check alerts detected increments

### Expected Behavior
- Status should briefly show "🟢 Synced" during preamble
- Then "🔴 Decoding Message" during header
- Alert detected counter should increment
- Status returns to "⚪ Listening" after

## Summary

**"Sync not locked" is the CORRECT and NORMAL state** when not actively receiving an EAS alert.

The decoder is:
- ✅ Running correctly
- ✅ Processing audio samples
- ✅ Listening for SAME bursts
- ✅ Ready to decode alerts instantly

**Think of it like a smoke detector**:
- Not beeping = Normal (equivalent to "Listening")
- Beeping = Alert detected (equivalent to "Synced/Decoding")

You don't want your smoke detector beeping all the time!

## Additional Resources

- [Streaming Decoder Documentation](architecture/STREAMING_DECODER.md)
- [EAS Monitoring Status Guide](monitoring/STATUS_INDICATORS.md)
- [Troubleshooting Guide](TROUBLESHOOTING.md)

## Related Issues

- **Audio not flowing**: Check audio sources started
- **Low confidence alerts**: Check sample rate matches source
- **Missed alerts**: Check scan interval and CPU load
- **False positives**: Check audio noise level
