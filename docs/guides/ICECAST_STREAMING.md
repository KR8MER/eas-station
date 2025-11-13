# Icecast Streaming for Audio Monitoring

## Problem Statement

The default Flask-based WAV streaming in the Audio Monitoring page has limitations:
- **Frame Drops**: Direct streaming can drop frames under network load
- **Buffer Issues**: Poor buffering leads to playback stuttering
- **Single Connection**: Each browser connection puts load on Flask
- **No Caching**: Every client requests full bandwidth from server

## Solution: Icecast Streaming

Icecast is an industry-standard streaming media server that provides:
- ✅ **Professional Buffering**: Proper audio buffering prevents dropouts
- ✅ **Multiple Clients**: Supports hundreds of simultaneous listeners
- ✅ **Low Latency**: ~2-5 second latency (configurable)
- ✅ **Format Support**: MP3, OGG Vorbis, AAC, Opus
- ✅ **Metadata**: Stream titles, station info, now playing
- ✅ **Monitoring**: Built-in statistics and admin interface

---

## Quick Start (Docker - Recommended)

### Step 1: Start Icecast

```bash
cd /home/user/eas-station

# Start Icecast server
docker-compose -f docker-compose.icecast.yml up -d

# Check it's running
docker ps | grep icecast
```

### Step 2: Configure EAS Station

1. Visit: `http://localhost:5000/settings/audio`
2. Scroll to "Icecast Streaming Output" section
3. Configure:
   - **Server**: `localhost` (or `icecast` if EAS Station in Docker)
   - **Port**: `8000`
   - **Source Password**: `changeme_source_pass` (from docker-compose)
   - **Mount Point**: `/eas-monitor`
   - **Stream Name**: `EAS Monitoring Station`
   - **Bitrate**: `128` kbps
   - **Format**: `MP3`
4. Click "Save Configuration"

### Step 3: Start Streaming

**Option A: Via Example Script**
```bash
python3 examples/run_with_icecast_streaming.py
```

**Option B: Integrated Service (Future)**
Once implemented, streams will automatically start when audio sources are running.

### Step 4: Listen

- **Direct Stream**: `http://localhost:8000/eas-monitor`
- **Web Interface**: `http://localhost:8000` (shows all active streams)
- **Admin Panel**: `http://localhost:8000/admin/` (user: `admin`, pass from docker-compose)

---

## Alternative: Native Installation

If Docker is not available, install Icecast natively:

### Ubuntu/Debian

```bash
# Install Icecast
sudo apt-get update
sudo apt-get install icecast2

# During installation, it will ask:
# - Configure Icecast2? → Yes
# - Hostname → localhost
# - Source password → (choose a strong password)
# - Relay password → (choose a strong password)
# - Admin password → (choose a strong password)

# Start Icecast
sudo systemctl enable icecast2
sudo systemctl start icecast2

# Check status
sudo systemctl status icecast2
```

### Configuration File

Edit `/etc/icecast2/icecast.xml`:

```xml
<icecast>
    <limits>
        <clients>100</clients>
        <sources>15</sources>
        <queue-size>524288</queue-size>
        <burst-on-connect>1</burst-on-connect>
        <burst-size>65535</burst-size>
    </limits>

    <authentication>
        <!-- Change these passwords! -->
        <source-password>YOUR_SOURCE_PASSWORD</source-password>
        <relay-password>YOUR_RELAY_PASSWORD</relay-password>
        <admin-user>admin</admin-user>
        <admin-password>YOUR_ADMIN_PASSWORD</admin-password>
    </authentication>

    <hostname>localhost</hostname>
    <listen-socket>
        <port>8000</port>
    </listen-socket>

    <paths>
        <basedir>/usr/share/icecast2</basedir>
        <logdir>/var/log/icecast2</logdir>
        <webroot>/usr/share/icecast2/web</webroot>
        <adminroot>/usr/share/icecast2/admin</adminroot>
        <pidfile>/var/run/icecast2/icecast.pid</pidfile>
    </paths>
</icecast>
```

After editing, restart:
```bash
sudo systemctl restart icecast2
```

---

## Architecture

### Data Flow with Icecast

```
┌─────────────────┐
│  Audio Source   │ (SDR, Stream, ALSA, etc.)
└────────┬────────┘
         │
         │ PCM Audio (22050 Hz, Mono)
         │
         ▼
┌─────────────────┐
│ Source Manager  │ (Priority selection, failover)
└────────┬────────┘
         │
         ├──────────────────────────────┐
         │                              │
         │ PCM                          │ PCM
         ▼                              ▼
┌─────────────────┐          ┌─────────────────┐
│   EAS Monitor   │          │ Icecast Streamer│
│                 │          │                 │
│ (Alert Detection)│         │ (FFmpeg Encode) │
└─────────────────┘          └────────┬────────┘
                                      │
                                      │ MP3 @ 128kbps
                                      ▼
                             ┌─────────────────┐
                             │ Icecast Server  │
                             │   (Port 8000)   │
                             └────────┬────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
            ┌────────────┐    ┌────────────┐   ┌────────────┐
            │  Browser 1 │    │  Browser 2 │   │  VLC/etc   │
            └────────────┘    └────────────┘   └────────────┘
```

### Benefits

1. **Server Load Reduction**
   - EAS Station only sends audio once to Icecast
   - Icecast handles distribution to multiple clients
   - Server load doesn't increase with client count

2. **Better Buffering**
   - Icecast uses proper audio buffering
   - Configurable burst-on-connect
   - Handles slow clients gracefully

3. **Professional Quality**
   - Industry-standard MP3 encoding
   - Proper metadata support
   - Statistics and monitoring

---

## Per-Source Streaming

Each audio source can have its own Icecast mount point:

```python
from app_core.audio.icecast_output import IcecastStreamer, IcecastConfig

# Create streamer for a specific source
config = IcecastConfig(
    server="localhost",
    port=8000,
    password="source_password",
    mount="source-name",  # Unique per source
    name="WXYZ-FM Monitor",
    description="iHeartMedia station WXYZ-FM",
    bitrate=128,
    format=StreamFormat.MP3
)

streamer = IcecastStreamer(config, audio_source)
streamer.start()
```

Then streams are available at:
- `http://localhost:8000/source-name` (direct MP3)
- `http://localhost:8000/source-name.m3u` (playlist)

---

## Monitoring Page Integration

### Current (Flask WAV Streaming)

```html
<audio controls>
    <source src="/api/audio/stream/source-name" type="audio/wav">
</audio>
```

**Problems**: Frame drops, poor buffering, high server load

### Future (Icecast Streaming)

```html
<audio controls>
    <source src="http://localhost:8000/source-name" type="audio/mpeg">
</audio>
```

**Benefits**: Professional buffering, low latency, scalable

### Implementation Plan

1. **Auto-Stream Service** (Future Enhancement)
   - Automatically creates Icecast stream for each running audio source
   - Mount point = source name
   - Starts/stops with source

2. **Monitoring Page Update**
   - Detect if Icecast is available
   - Use Icecast URL if available, fall back to Flask streaming
   - Show connection info (bitrate, listeners, uptime)

3. **Admin Interface**
   - Show Icecast status
   - Control streaming per-source
   - View listener statistics

---

## Configuration Reference

### Icecast Config Object

```python
@dataclass
class IcecastConfig:
    server: str           # Hostname/IP of Icecast server
    port: int            # Port (typically 8000)
    password: str        # Source password from Icecast config
    mount: str           # Mount point (e.g., "eas-monitor")
    name: str            # Stream name (shown to listeners)
    description: str     # Stream description
    genre: str          # Genre (default: "Emergency")
    bitrate: int        # Bitrate in kbps (default: 128)
    format: StreamFormat # MP3 or OGG
    public: bool        # List in Icecast directory (default: False)
```

### Recommended Settings

| Use Case | Bitrate | Format | Latency |
|----------|---------|--------|---------|
| **Voice Only (NOAA)** | 64 kbps | MP3 | ~3s |
| **Music Radio** | 128 kbps | MP3 | ~4s |
| **High Quality** | 192 kbps | MP3 | ~5s |
| **Low Bandwidth** | 48 kbps | OGG | ~2s |

---

## Troubleshooting

### Icecast Won't Start

**Check if port is in use:**
```bash
sudo netstat -tlnp | grep :8000
```

**Check Icecast logs:**
```bash
# Docker
docker logs eas-icecast

# Native
sudo tail -f /var/log/icecast2/error.log
```

### Can't Connect to Icecast

**Verify Icecast is running:**
```bash
curl -I http://localhost:8000
# Should return HTTP 200
```

**Check firewall:**
```bash
sudo ufw status
sudo ufw allow 8000/tcp
```

### Stream Won't Publish

**Test FFmpeg encoding:**
```bash
ffmpeg -f s16le -ar 22050 -ac 1 -i /dev/zero \
  -acodec libmp3lame -b:a 128k -f mp3 \
  icecast://source:PASSWORD@localhost:8000/test
```

**Check source password:**
- Must match password in Icecast configuration
- Case-sensitive

### No Audio in Browser

**Try different players:**
```bash
# VLC
vlc http://localhost:8000/eas-monitor

# mpv
mpv http://localhost:8000/eas-monitor

# curl (should show MP3 data)
curl http://localhost:8000/eas-monitor | head -c 1000
```

**Check browser console** (F12) for errors

### High Latency

**Reduce buffer size** in Icecast config:
```xml
<burst-size>32768</burst-size>  <!-- Lower = less latency -->
<queue-size>262144</queue-size>  <!-- Smaller queue -->
```

**Use lower bitrate:**
```python
bitrate=64  # Lower bitrate = less buffering needed
```

---

## Security Considerations

### Production Deployment

1. **Change ALL Default Passwords**
   ```xml
   <source-password>STRONG_RANDOM_PASSWORD</source-password>
   <admin-password>DIFFERENT_STRONG_PASSWORD</admin-password>
   ```

2. **Restrict Access**
   ```bash
   # Only allow local connections
   sudo ufw deny 8000/tcp
   sudo ufw allow from 192.168.1.0/24 to any port 8000
   ```

3. **Use Reverse Proxy**
   ```nginx
   # nginx config
   location /stream/ {
       proxy_pass http://localhost:8000/;
       proxy_set_header Host $host;
   }
   ```

4. **SSL/TLS**
   - Use nginx with Let's Encrypt for HTTPS
   - Modern browsers require HTTPS for audio playback

5. **Authentication**
   - Configure listener authentication in Icecast
   - Use nginx basic auth as additional layer

---

## Performance Tuning

### Server Settings

```xml
<limits>
    <clients>100</clients>          <!-- Max simultaneous listeners -->
    <sources>15</sources>           <!-- Max simultaneous sources -->
    <workers>4</workers>            <!-- Thread count -->
    <queue-size>524288</queue-size> <!-- Client buffer size -->
    <burst-size>65535</burst-size>  <!-- Initial burst -->
</limits>
```

### FFmpeg Encoding

**Lower CPU usage:**
```python
bitrate=96  # Reduce bitrate
# Or use OGG (more efficient than MP3)
format=StreamFormat.OGG
```

**Better quality:**
```python
bitrate=192
format=StreamFormat.MP3
```

---

## Monitoring and Statistics

### Icecast Admin Interface

Access at: `http://localhost:8000/admin/`

Shows:
- Active streams and mount points
- Listener count per stream
- Bitrate and format
- Uptime and total bytes sent
- Peak concurrent listeners

### API Access

```bash
# Get server stats
curl http://localhost:8000/admin/stats

# Specific mount stats
curl http://localhost:8000/admin/stats?mount=/eas-monitor
```

### Python Monitoring

```python
streamer = IcecastStreamer(config, source)
streamer.start()

# Get statistics
stats = streamer.get_stats()
print(f"Uptime: {stats['uptime_seconds']}s")
print(f"Bitrate: {stats['bitrate_kbps']} kbps")
print(f"Reconnections: {stats['reconnect_count']}")
```

---

## Related Documentation

- [Audio Monitoring](../audio/AUDIO_MONITORING)
- [iHeartMedia Streams](./IHEARTMEDIA_STREAMS)
- [Professional Audio Subsystem](../PROFESSIONAL_AUDIO_SUBSYSTEM)

---

## Future Enhancements

### Planned Features

1. **Auto-Streaming Service**
   - Automatically stream each audio source to Icecast
   - No manual script execution needed
   - Integrated with source start/stop

2. **Web UI Integration**
   - One-click enable/disable per source
   - Show listener count in monitoring page
   - Display Icecast status in dashboard

3. **Multi-Bitrate Streaming**
   - High quality: 192 kbps
   - Standard: 128 kbps
   - Mobile: 64 kbps
   - Automatic quality selection

4. **Recording Integration**
   - Record from Icecast streams
   - Time-shift playback
   - Archive management

---

## Support

For issues:
1. Check Icecast logs
2. Verify network connectivity
3. Test with VLC or mpv
4. Review this documentation
5. Open GitHub issue with logs and configuration
