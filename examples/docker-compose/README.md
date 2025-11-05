# Docker Compose Override Examples

This directory contains example `docker-compose.override.yml` files for common deployment scenarios. Docker Compose automatically merges `docker-compose.yml` with `docker-compose.override.yml` when present in the project root.

## Overview

The base `docker-compose.yml` provides minimal configuration. Override files customize the deployment for specific audio hardware, development environments, or advanced features without modifying the base file.

## Available Configurations

| File | Use Case | Recommended For |
|------|----------|-----------------|
| `docker-compose.audio-alsa.yml` | Direct ALSA access | **Production deployments** (lowest latency) |
| `docker-compose.audio-pulse.yml` | PulseAudio integration | Desktop environments with existing PulseAudio |
| `docker-compose.audio-multi.yml` | Multiple USB audio interfaces | Monitoring multiple radio receivers |
| `docker-compose.development.yml` | Development and testing | **Development only** (includes debugging tools) |

## Quick Start

### 1. Choose Your Configuration

**Production (Recommended):**
```bash
cp examples/docker-compose/docker-compose.audio-alsa.yml docker-compose.override.yml
```

**Development:**
```bash
cp examples/docker-compose/docker-compose.development.yml docker-compose.override.yml
```

### 2. Customize for Your Hardware

Edit `docker-compose.override.yml` to match your hardware:

```bash
nano docker-compose.override.yml
```

**Key settings to adjust:**
- `AUDIO_ALSA_DEVICE`: Your USB audio interface (find with `arecord -l`)
- `AUDIO_SDR_ENABLED`: Enable if using SDR receivers
- `EAS_GPIO_PIN`: GPIO pin number for relay control

### 3. Start Services

```bash
docker-compose up -d
```

Docker Compose automatically merges base and override configurations.

### 4. Verify

Check that services started correctly:

```bash
docker-compose ps
docker-compose logs -f app
```

## Configuration Details

### ALSA Direct Access (Production)

**File:** `docker-compose.audio-alsa.yml`

**Features:**
- ✅ Lowest latency (<10ms)
- ✅ Best reliability
- ✅ No PulseAudio dependency
- ✅ Real-time priority support
- ⚠️ Requires PulseAudio to be disabled on host

**Setup:**

1. Disable PulseAudio on host:
   ```bash
   systemctl --user stop pulseaudio.socket pulseaudio.service
   systemctl --user disable pulseaudio.socket pulseaudio.service
   ```

2. Configure ALSA (see `docs/deployment/audio_hardware.md`)

3. Identify your USB audio interface:
   ```bash
   arecord -l
   # Example output:
   # card 1: U192k [UMC202HD 192k], device 0: USB Audio [USB Audio]
   ```

4. Update `AUDIO_ALSA_DEVICE` in override file:
   ```yaml
   AUDIO_ALSA_DEVICE: "hw:1,0"  # Card 1, device 0
   ```

### PulseAudio Integration

**File:** `docker-compose.audio-pulse.yml`

**Features:**
- ✅ Works with existing PulseAudio setups
- ✅ Easy desktop integration
- ✅ No system reconfiguration needed
- ⚠️ Higher latency (~20-50ms)
- ⚠️ Less reliable for 24/7 operation

**Setup:**

1. Ensure PulseAudio is running:
   ```bash
   systemctl --user status pulseaudio
   ```

2. Find your audio device:
   ```bash
   pactl list short sources
   pactl list short sinks
   ```

3. Copy override file and start services

### Multiple USB Interfaces

**File:** `docker-compose.audio-multi.yml`

**Features:**
- ✅ Monitor multiple radio receivers
- ✅ Separate audio sources with priorities
- ✅ Automatic failover between sources
- ℹ️ Requires multiple USB audio interfaces

**Setup:**

1. Connect all USB audio interfaces

2. Identify each interface:
   ```bash
   arecord -l
   # Example:
   # card 1: UMC202HD (primary receiver)
   # card 2: Scarlett2i2 (secondary receiver)
   ```

3. Update override file with correct device IDs:
   ```yaml
   AUDIO_ALSA_DEVICE: "hw:1,0"        # Primary
   AUDIO_PULSE_DEVICE_INDEX: "2"      # Secondary
   ```

4. Optionally enable SDR:
   ```yaml
   AUDIO_SDR_ENABLED: "true"
   AUDIO_SDR_RECEIVER_ID: "sdr_primary"
   ```

### Development Mode

**File:** `docker-compose.development.yml`

**Features:**
- ✅ Flask debug mode
- ✅ Live code reloading
- ✅ Python debugger (debugpy) on port 5678
- ✅ Exposed PostgreSQL port (5432)
- ✅ Optional pgAdmin on port 5050
- ✅ Test audio file loopback (no hardware needed)
- ⚠️ **NEVER use in production** (security risks)

**Setup:**

1. Copy override file:
   ```bash
   cp examples/docker-compose/docker-compose.development.yml docker-compose.override.yml
   ```

2. Start services:
   ```bash
   docker-compose up -d
   ```

3. Attach debugger:
   - VS Code: Add configuration to `.vscode/launch.json`
   - PyCharm: Create remote debug configuration
   - Port: 5678

4. Access pgAdmin (optional):
   ```bash
   docker-compose --profile development up -d pgadmin
   ```

   Open: http://localhost:5050
   - Email: admin@localhost
   - Password: admin

## Combining Multiple Overrides

To combine features from multiple override files, merge them manually:

**Example: ALSA + Development**

```yaml
version: '3.8'

services:
  app:
    # ALSA audio settings
    environment:
      AUDIO_ALSA_ENABLED: "true"
      AUDIO_ALSA_DEVICE: "hw:1,0"

      # Development settings
      FLASK_DEBUG: "true"
      LOG_LEVEL: "DEBUG"

    volumes:
      - /etc/asound.conf:/etc/asound.conf:ro
      - ./app.py:/app/app.py:ro  # Live reload

    devices:
      - /dev/snd:/dev/snd

    group_add:
      - audio

    ports:
      - "5000:5000"
```

## Troubleshooting

### Override Not Applied

**Problem:** Changes to override file not taking effect

**Solution:**
```bash
# Recreate containers to pick up new configuration
docker-compose down
docker-compose up -d
```

### Audio Device Not Found

**Problem:** "No such device" errors in logs

**Solution:**

1. Verify device exists on host:
   ```bash
   ls -l /dev/snd/
   arecord -l
   ```

2. Check device name in override file matches output from `arecord -l`

3. Ensure user is in `audio` group:
   ```bash
   groups $USER
   # Should include "audio"
   ```

4. Restart Docker daemon:
   ```bash
   sudo systemctl restart docker
   docker-compose up -d
   ```

### Permission Denied on /dev/snd

**Problem:** Container cannot access audio devices

**Solution:**

1. Add user to audio group:
   ```bash
   sudo usermod -aG audio $USER
   ```

2. Log out and back in (or reboot)

3. Verify group membership:
   ```bash
   groups
   ```

4. Check override file includes `group_add: - audio`

5. Recreate containers:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

### GPIO Not Working

**Problem:** Relay control fails

**Solution:**

1. Verify GPIO permissions:
   ```bash
   ls -l /dev/gpiomem
   # Should be readable by gpio group
   ```

2. Add user to gpio group:
   ```bash
   sudo usermod -aG gpio $USER
   ```

3. Update override file:
   ```yaml
   services:
     app:
       devices:
         - /dev/gpiomem:/dev/gpiomem
       group_add:
         - gpio
   ```

4. See `docs/hardware/gpio.md` for detailed GPIO setup

## Best Practices

1. **Never commit `docker-compose.override.yml` to version control**
   - Contains site-specific configuration
   - May include sensitive information
   - Add to `.gitignore`

2. **Document your configuration**
   - Add comments to override file
   - Keep a backup of working configuration

3. **Test in development first**
   - Use development override to validate changes
   - Switch to production override after testing

4. **Use specific device names, not "default"**
   - Prevents issues when multiple audio devices present
   - Makes troubleshooting easier

5. **Enable health checks**
   - Monitor `/system/health` regularly
   - Check logs for audio warnings

6. **Keep backups**
   - Back up working `docker-compose.override.yml`
   - Document hardware changes in station log

## Additional Resources

- [Audio Hardware Setup Guide](../../docs/deployment/audio_hardware.md)
- [Reference Pi Build](../../docs/hardware/reference_pi_build.md)
- [Post-Install Checklist](../../docs/deployment/post_install.md)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [ALSA Configuration](https://www.alsa-project.org/wiki/Asoundrc)

## Contributing

To add a new example override:

1. Create `docker-compose.YOUR_USE_CASE.yml` in this directory
2. Add documentation header explaining the use case
3. Update this README with a new section
4. Test the configuration on clean installation
5. Submit pull request with example and documentation

---

**Document Version:** 1.0
**Last Updated:** 2025-11-05
**Maintainer:** EAS Station Development Team
