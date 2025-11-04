# Audio Sources

Configure audio ingestion, SAME encoding, and text-to-speech for alert broadcasting.

## Audio Configuration

### SAME Encoding

EAS Station generates FCC-compliant SAME (Specific Area Message Encoding) headers.

**Configuration** (in `.env`):

```bash
EAS_BROADCAST_ENABLED=true
EAS_ORIGINATOR=WXR
EAS_STATION_ID=YOURCALL
EAS_ATTENTION_TONE_SECONDS=8
```

### Text-to-Speech

Configure voice synthesis for alert messages:

```bash
EAS_TTS_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
AZURE_OPENAI_KEY=your-api-key
AZURE_OPENAI_VOICE=alloy
```

**Supported Providers:**
- `azure_openai` - High quality (recommended)
- `azure` - Good quality
- `pyttsx3` - Basic, free

## Audio Output

### Audio Player

Configure audio output device:

```bash
EAS_AUDIO_PLAYER=aplay
EAS_SAMPLE_RATE=44100
```

### Output Directory

Generated audio files stored in:

```bash
EAS_OUTPUT_DIR=static/eas_messages
```

## Audio Generation

### Automatic Generation

When alerts are received, audio is automatically generated including:
1. SAME header (3 bursts)
2. Attention tone (8-25 seconds)
3. Voice message (text-to-speech)
4. SAME trailer (3 bursts)

### Manual Generation

To manually generate audio:
1. Navigate to **Admin → Manual Broadcast**
2. Select or create alert
3. Click **Generate Audio**

## Audio Quality

Monitor audio generation:
- Check logs for TTS errors
- Verify SAME encoding accuracy
- Test audio playback
- Monitor file sizes

!!! warning "Broadcast Warning"
    Never broadcast generated EAS tones without proper FCC authorization. Keep audio output isolated in test environments.

See [Hardware Setup](hardware/index.md) for audio routing configuration.
