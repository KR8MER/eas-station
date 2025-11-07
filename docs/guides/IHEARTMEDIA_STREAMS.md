# iHeartMedia Radio Stream Integration Guide

## Overview

This guide documents how to add iHeartMedia radio stations to the EAS Station for monitoring. iHeartMedia operates thousands of radio stations across the United States, and many broadcast their streams via the Revma CDN, making them accessible for EAS monitoring purposes.

---

## Stream URL Format

iHeartMedia streams use the following URL pattern:

```
https://stream.revma.ihrhls.com/zc####
```

Where `####` is a 4-digit station identifier.

### Examples

```
https://stream.revma.ihrhls.com/zc1753  # Example station
https://stream.revma.ihrhls.com/zc5678  # Another station
```

### Technical Details

- **Protocol**: HTTPS
- **Format**: MP3 (MPEG Audio Layer 3)
- **Typical Bitrate**: 128 kbps (variable by station)
- **CDN**: Revma/CloudFront
- **Reliability**: Enterprise-grade with automatic failover

---

## How to Add a Station

### Via Web Interface (Recommended)

1. **Navigate to Audio Settings**
   - Go to: `/settings/audio`
   - Click: **"Add Audio Source"** button (top right)

2. **Fill in the Form**

   | Field | Value | Notes |
   |-------|-------|-------|
   | **Source Name** | `WXYZ-FM` | Any descriptive name you want |
   | **Source Type** | `Stream (HTTP/M3U)` | Select from dropdown |
   | **Stream URL** | `https://stream.revma.ihrhls.com/zc####` | Replace #### with station code |
   | **Stream Format** | `MP3 (auto-detect)` | Leave as default |
   | **Sample Rate** | `22050 Hz` | Pre-filled, recommended for radio |
   | **Channels** | `Mono (1)` | Pre-filled, standard for radio |
   | **Silence Threshold** | `-60 dBFS` | Default is fine |
   | **Silence Duration** | `5 seconds` | Default is fine |

3. **Add and Start**
   - Click: **"Add Source"**
   - Click: **"Start"** on the newly created source
   - Visit: `/audio-monitor` to verify it's working

### Via API

```bash
curl -X POST http://localhost:5000/api/audio/sources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "WXYZ-FM",
    "type": "stream",
    "description": "iHeartMedia station WXYZ-FM",
    "enabled": true,
    "auto_start": false,
    "priority": 100,
    "sample_rate": 22050,
    "channels": 1,
    "device_params": {
      "stream_url": "https://stream.revma.ihrhls.com/zc1753",
      "format": "mp3"
    }
  }'
```

---

## Finding Station Stream IDs

### Method 1: Network Inspection (Browser)

1. Visit the iHeartRadio website
2. Find and play your desired station
3. Open browser DevTools (F12)
4. Go to Network tab
5. Look for requests to `stream.revma.ihrhls.com`
6. The URL will contain the `zc####` identifier

### Method 2: Mobile App Inspection

iHeartRadio mobile apps also use these URLs. Use a network monitoring tool to capture the stream URL when playing a station.

### Method 3: Community Resources

Check radio monitoring forums and communities that may maintain lists of station IDs.

---

## Features and Capabilities

### Automatic Features

Once added, iHeartMedia streams benefit from:

- ✅ **Continuous Streaming** - No arbitrary time limits
- ✅ **Auto-Reconnection** - Automatically reconnects on network hiccups
- ✅ **Format Detection** - Automatically detects MP3 format from headers
- ✅ **Buffer Monitoring** - Real-time visibility into data flow
- ✅ **Waveform Visualization** - Live oscilloscope display
- ✅ **EAS Detection** - Continuous monitoring for emergency alerts
- ✅ **Silence Detection** - Alerts on stream dropouts
- ✅ **Metadata Extraction** - Captures station name, bitrate, codec info

### Monitoring Indicators

On the `/audio-monitor` page, you'll see:

- **Status Badge**: RUNNING (green) when active
- **Monitoring Badge**: Shows background EAS detection is active
- **Buffer Utilization**: Shows data flowing (should be 1-80%)
- **Frames Captured**: Incrementing count proves audio processing
- **Peak/RMS Levels**: Real-time audio levels in dBFS
- **Stream Information**: Codec, bitrate, station metadata

---

## Troubleshooting

### Stream Won't Start

**Symptom**: Source shows "STOPPED" or "ERROR"

**Possible Causes**:
1. **Invalid Station ID** - The `zc####` code may be incorrect
2. **Network/Firewall** - HTTPS access to `stream.revma.ihrhls.com` may be blocked
3. **Geo-Restrictions** - Some streams may be geo-locked

**Solutions**:
```bash
# Test stream manually
curl -I https://stream.revma.ihrhls.com/zc1753

# Should return HTTP 200 and Content-Type: audio/mpeg
# If you get 400/403/404, the stream ID is invalid or restricted
```

### "No Data Flowing" Warning

**Symptom**: Buffer utilization shows < 1%

**Possible Causes**:
1. **Stream Temporarily Down** - Station may be offline for maintenance
2. **Network Issues** - Intermittent connectivity
3. **FFmpeg Issue** - Decoder may have crashed

**Solutions**:
1. Check stream manually (see above)
2. Click "Stop" then "Start" to restart the source
3. Check `/var/log/eas-station/` for FFmpeg errors

### Audio Plays But Stops After Time

**Symptom**: Web player stops after a few seconds/minutes

**Note**: This was fixed in recent updates. If you still see this:

1. Ensure you're running the latest version
2. Check that `max_chunks` in `webapp/admin/audio_ingest.py` is set to a high value
3. Verify `max_consecutive_silence` allows sufficient buffer time

### Poor Audio Quality

**Symptom**: Choppy, distorted, or low-quality audio

**Solutions**:
1. **Check Sample Rate** - Ensure it's set to 22050 Hz (not higher)
2. **Network Bandwidth** - Verify stable internet connection
3. **CPU Load** - Check server isn't overloaded

---

## Best Practices

### Sample Rate Selection

| Use Case | Recommended Rate | Notes |
|----------|-----------------|-------|
| **Radio/Weather Monitoring** | 22050 Hz | Optimal for voice/music, low bandwidth |
| **High-Fidelity Monitoring** | 44100 Hz | CD quality, higher CPU/bandwidth |
| **Emergency Use Only** | 16000 Hz | Minimum for voice intelligibility |

### Priority Configuration

Set priorities to control failover order:

```
Priority 10  = Primary station (main market)
Priority 20  = Backup station (adjacent market)
Priority 30  = Remote backup
```

Lower numbers = higher priority.

### Naming Conventions

Recommended naming patterns:

```
WXYZ-FM              # Call sign
WXYZ-FM-Chicago      # Call sign + market
iHeart-Chicago-News  # Network + market + format
Chicago-WX-Primary   # Market + purpose + priority
```

---

## Integration with EAS Monitoring

### Automatic Alert Detection

Once a stream is running, the system automatically:

1. **Scans Audio** - Continuously analyzes for EAS SAME headers
2. **Decodes Alerts** - Extracts alert messages from detected tones
3. **Logs Events** - Records all detected alerts with metadata
4. **Archives Audio** - Saves audio clips of alert events
5. **Triggers Actions** - Can activate relays, send notifications, etc.

### Monitoring Multiple Markets

You can monitor multiple stations simultaneously:

```
Priority 10: New York primary
Priority 11: New York backup
Priority 20: Philadelphia primary
Priority 21: Philadelphia backup
```

The system will:
- Use highest priority source that's running
- Automatically fail over if primary drops
- Continue background monitoring on all sources

---

## Technical Reference

### Stream Characteristics

| Property | Value |
|----------|-------|
| Protocol | HTTPS/1.1 or HTTP/2 |
| Container | MPEG Audio |
| Codec | MP3 (MPEG-1 Layer 3) |
| Bitrate | 48-320 kbps (typically 128 kbps) |
| Sample Rate | 44100 Hz (source) |
| Channels | 2 (stereo) or 1 (mono) |
| Encoding | Variable Bit Rate (VBR) or Constant (CBR) |

### CDN Infrastructure

- **Provider**: Amazon CloudFront
- **Origin**: Revma Media streaming infrastructure
- **Edge Locations**: Global CDN for low latency
- **Redundancy**: Automatic failover across edge servers
- **Cache**: Short-lived, optimized for live streaming

### FFmpeg Decoding Pipeline

The system uses FFmpeg to decode streams:

```
HTTPS Stream → FFmpeg → PCM Audio → EAS Decoder
                ↓
            Metadata Extraction
            - Bitrate
            - Codec
            - Station info
```

### Buffer Management

- **Input Buffer**: Receives encoded MP3 data from stream
- **Decode Buffer**: Holds raw PCM after FFmpeg decode
- **Ring Buffer**: 5-second circular buffer for EAS scanning
- **Output Buffer**: Serves data to web interface and monitors

---

## Compliance Notes

### FCC Regulations

When monitoring iHeartMedia or any broadcast stations:

1. **EAS Compliance** (47 CFR Part 11)
   - Required for broadcast stations
   - Monitoring helps ensure compliance
   - Record-keeping aids in regulatory reports

2. **Copyright** (17 U.S.C. § 107)
   - Monitoring for EAS/emergency purposes is generally permitted
   - Do not redistribute streams
   - Do not use for commercial purposes

3. **Unauthorized Access** (18 U.S.C. § 1030)
   - Only use publicly available streams
   - Respect any geo-restrictions
   - Do not attempt to circumvent access controls

### Best Practices

- **Primary Purpose**: Emergency alert monitoring
- **Record Keeping**: Maintain logs of monitored content
- **Access Control**: Restrict access to authorized personnel
- **Data Retention**: Follow station retention policies

---

## Related Documentation

- [AUDIO_MONITORING.md](../../AUDIO_MONITORING.md) - Main audio monitoring guide
- [PROFESSIONAL_AUDIO_SUBSYSTEM.md](../PROFESSIONAL_AUDIO_SUBSYSTEM.md) - Architecture details
- [AUDIO_SYSTEM_ACCESS_GUIDE.md](../AUDIO_SYSTEM_ACCESS_GUIDE.md) - API reference

---

## Appendix: Example Configurations

### Configuration 1: Single Market Monitoring

```json
{
  "name": "WXYZ-FM-Primary",
  "type": "stream",
  "description": "Primary EAS monitoring - WXYZ-FM Chicago",
  "priority": 10,
  "enabled": true,
  "auto_start": true,
  "sample_rate": 22050,
  "channels": 1,
  "device_params": {
    "stream_url": "https://stream.revma.ihrhls.com/zc1753",
    "format": "mp3"
  }
}
```

### Configuration 2: Multi-Market with Failover

```json
[
  {
    "name": "Chicago-Primary",
    "priority": 10,
    "device_params": {
      "stream_url": "https://stream.revma.ihrhls.com/zc1753"
    }
  },
  {
    "name": "Chicago-Backup",
    "priority": 20,
    "device_params": {
      "stream_url": "https://stream.revma.ihrhls.com/zc2468"
    }
  },
  {
    "name": "Milwaukee-Regional",
    "priority": 30,
    "device_params": {
      "stream_url": "https://stream.revma.ihrhls.com/zc3579"
    }
  }
]
```

### Configuration 3: Combined SDR and Streaming

```json
[
  {
    "name": "Local-162.55-SDR",
    "type": "sdr",
    "priority": 10,
    "device_params": {
      "receiver_id": "rtl_sdr_0"
    }
  },
  {
    "name": "Regional-iHeart-Backup",
    "type": "stream",
    "priority": 20,
    "device_params": {
      "stream_url": "https://stream.revma.ihrhls.com/zc1753"
    }
  }
]
```

---

## Changelog

| Date | Change |
|------|--------|
| 2025-11-07 | Initial documentation - UI fixes for iHeartMedia stream support |
| 2025-11-07 | Added troubleshooting section and technical reference |

---

## Support

For issues or questions:
1. Check this documentation first
2. Review system logs: `/var/log/eas-station/`
3. Test stream manually with `curl` or `ffprobe`
4. Open an issue on GitHub with stream URL and error details

---

**Note**: Stream IDs (`zc####`) are not publicly documented by iHeartMedia. Users must discover these through legitimate means (network inspection while using official apps/websites) for their monitoring purposes.
