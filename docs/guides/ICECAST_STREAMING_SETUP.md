# Icecast Streaming Setup

EAS Station™ integrates with the **Icecast 2** open-source streaming server to distribute audio — both live SDR demodulation output and EAS broadcast audio — over the network. Icecast acts as a relay, accepting a source audio stream from EAS Station™ and distributing it to any number of listeners.

---

## Architecture Overview

```
SDR Hardware Service    →  IQ samples
       ↓
Audio Monitoring Service  →  Demodulated PCM audio
       ↓
Icecast Server           →  HTTP audio stream (listeners)
```

EAS Station™ acts as the **Icecast source client**; Icecast handles distribution. Multiple stream profiles (mount points) can be configured for different audiences or audio formats.

---

## Installing Icecast

Icecast is installed automatically by the main `install.sh` installer. To install manually:

```bash
sudo apt-get install icecast2
```

During the APT installation, you will be prompted for:
- **Icecast hostname** — use `localhost` for local-only or your FQDN for public access
- **Source password** — the password EAS Station™ uses to push audio to Icecast
- **Relay password** — for inter-server relaying (not used in basic setups)
- **Admin password** — for the Icecast admin web interface at `http://<host>:8000/admin`

---

## Configuring Icecast in EAS Station™

EAS Station™ manages Icecast credentials and basic settings from the web interface. The configuration is written to `/etc/icecast2/icecast.xml` automatically.

### Via the Web Interface

1. Navigate to **Admin → Icecast**.
2. Configure the following fields:

| Field | Default | Description |
|-------|---------|-------------|
| Icecast Host | `localhost` | Hostname or IP of the Icecast server |
| Icecast Port | `8000` | Icecast HTTP port |
| Source Password | *(generated)* | Password EAS Station™ uses to push streams |
| Admin User | `admin` | Icecast admin username |
| Admin Password | *(generated)* | Icecast admin web interface password |
| Max Sources | Unlimited | Maximum simultaneous source connections |

3. Click **Save & Apply**. EAS Station™ writes the new credentials to `/etc/icecast2/icecast.xml` and restarts the Icecast service.

### Via eas-config

```bash
sudo eas-config
```

Select **4. Audio Settings → Icecast Configuration**.

### Via .env (Manual)

```
ICECAST_HOST=localhost
ICECAST_PORT=8000
ICECAST_SOURCE_PASSWORD=your-source-password
ICECAST_ADMIN_PASSWORD=your-admin-password
```

---

## Stream Profiles (Mount Points)

Each audio source in EAS Station™ can be assigned to a separate Icecast mount point. Navigate to **Settings → Stream Profiles** (`/settings/stream-profiles`) to manage them.

### Default Mount Points

| Mount Point | Content | Codec |
|------------|---------|-------|
| `/eas-live` | Live SDR demodulated audio | MP3 128kbps or OGG |
| `/eas-broadcast` | EAS broadcast audio (active alerts only) | WAV/PCM |

### Creating a New Stream Profile

1. Go to **Settings → Stream Profiles → Add Profile** (`/settings/stream-profiles`).
2. Configure:
   - **Mount Point** — URL path (e.g., `/my-stream`)
   - **Codec** — MP3, OGG Vorbis, or PCM
   - **Bitrate** — 64, 128, 192, or 320 kbps (for MP3)
   - **Sample Rate** — 8000, 22050, or 44100 Hz
   - **Source** — which audio input device or SDR receiver feeds this stream
3. Click **Save**.

---

## Accessing the Audio Stream

### Listening with a Media Player

```bash
# VLC
vlc http://your-eas-station.example.com:8000/eas-live

# mpv
mpv http://your-eas-station.example.com:8000/eas-live

# ffplay
ffplay http://your-eas-station.example.com:8000/eas-live
```

Or open the URL directly in any Icecast-compatible player (Winamp, foobar2000, etc.).

### Embedding in a Web Page

```html
<audio controls>
  <source src="http://your-eas-station.example.com:8000/eas-live" type="audio/mpeg">
</audio>
```

### EAS Station™ Audio Monitoring Page

The built-in audio monitoring page at `/admin/audio-sources` displays:
- Live VU meters for each mount point
- Stream status (connected/disconnected)
- Listener count
- Incoming audio health metrics

---

## Firewall Configuration

By default, Icecast listens on port 8000. Open this port if you want external access:

```bash
sudo ufw allow 8000/tcp comment "Icecast streaming"
```

For HTTPS streaming, see [SSL Setup](HTTPS_SETUP.md). Icecast itself does not support SSL natively; use an nginx reverse proxy to add TLS.

### nginx Reverse Proxy for HTTPS Streaming

Add to your nginx configuration:

```nginx
location /icecast/ {
    proxy_pass http://localhost:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_buffering off;
    proxy_cache off;
}
```

Listeners can then connect to `https://your-domain.example.com/icecast/eas-live`.

---

## Icecast Admin Interface

The Icecast admin interface at `http://<host>:8000/admin` provides:
- Live listener counts per mount point
- Source connection status
- Server statistics
- Kick/ban listeners

Log in with the admin credentials configured in **Admin → Icecast**.

---

## Audio Health Monitoring

EAS Station™ monitors the health of each Icecast stream. Navigate to **Admin → Audio Sources** to view:

- **Connection state** — is EAS Station™ connected to Icecast as a source?
- **Input level** — real-time audio level from the source device
- **Silence detection** — alerts if the stream has been silent for too long
- **Listener count** — pulled from the Icecast API

Alerts for stream health issues are sent to **Compliance / Health Alert Recipients** (configured in **Admin → Notifications**).

---

## Troubleshooting

### Icecast service not running

```bash
sudo systemctl status icecast2
sudo systemctl start icecast2
sudo journalctl -u icecast2 -f
```

### Source not connecting

- Verify the source password in EAS Station™ matches `/etc/icecast2/icecast.xml`.
- Check Icecast logs: `/var/log/icecast2/error.log`
- Confirm the audio service is running: `sudo systemctl status eas-station-audio`

### Listeners can connect but hear silence

- Check the audio input device in **Admin → Audio Sources**.
- Confirm the SDR receiver is streaming: `sudo systemctl status eas-station-sdr`
- Use the VU meters in **Admin → Audio** to verify signal is present.

### Port 8000 not accessible from outside

- Confirm the host firewall allows port 8000 from **Settings → Firewall** — the Icecast card
  there shows which subnets are currently allowed and lets you add one with no SSH required.
- If behind a router, ensure port 8000 is forwarded to the EAS Station™ host — see [Router Port Forwarding](../troubleshooting/FIREWALL_REQUIREMENTS.md#router-port-forwarding-home--lab-networks) for which ports to forward and which to leave closed. Router forwarding is a separate step from the host-firewall rule above — both are required for WAN access.

### Mount point shows as "404 Not Found"

- The stream profile for that mount point must be active and connected.
- Verify the mount point name matches exactly (case-sensitive, starts with `/`).
- Check the Icecast admin interface at `http://<host>:8000/admin` to see active mounts.

### High CPU from Icecast encoding

- Reduce the number of active stream profiles.
- Lower the bitrate or sample rate for streams that do not require high quality.
- Use a hardware audio device capable of providing pre-encoded audio to reduce software transcoding.
