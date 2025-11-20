# New Features Guide

This document describes recently added features and enhancements to EAS Station.

## System Diagnostics Tool

**Location:** `/diagnostics`

**Purpose:** Web-based system validation and health checking tool that verifies your EAS Station installation.

### Features

- **Docker Service Status**: Verifies all required Docker containers are running
- **Database Connectivity**: Tests PostgreSQL connection and schema
- **Environment Configuration**: Validates `.env` file settings
- **Health Endpoints**: Checks system health API responses
- **Audio Devices**: Detects available audio hardware
- **Log Analysis**: Scans recent logs for errors and warnings
- **Export Results**: Download validation results as JSON

### Using the Diagnostics Tool

1. Navigate to **Admin** → **Diagnostics** or visit `/diagnostics`
2. Click **"Run Diagnostics"** button
3. Wait for all checks to complete (usually 10-15 seconds)
4. Review results organized by category:
   - ✓ **Passed** - All checks successful
   - ⚠ **Warnings** - Non-critical issues that should be reviewed
   - ✗ **Failed** - Critical issues requiring attention
   - ℹ **Information** - Additional details about your system

### When to Use

- **After installation** - Verify all components are configured correctly
- **Before production** - Ensure system is ready for live operation
- **Troubleshooting** - Diagnose configuration or connectivity issues
- **Regular maintenance** - Periodic health checks
- **After upgrades** - Validate system after software updates

### Export and Documentation

Click **"Export Results"** to download a JSON file containing:
- Timestamp of diagnostics run
- Summary counts (passed/warnings/failed)
- Detailed results for each check
- Useful for:
  - Sharing with support/developers
  - Documenting system state
  - Compliance records
  - Troubleshooting history

---

## Stream Profile Management

**Location:** `/settings/stream-profiles`

**Purpose:** Configure multiple Icecast streaming profiles with different bitrates, formats, and quality settings.

### Features

- **Multiple Profiles**: Create unlimited stream configurations
- **Quality Presets**: Quick setup with low/medium/high/premium templates
- **Format Support**: MP3, OGG Vorbis, Opus, and AAC encoding
- **Bandwidth Estimation**: Real-time calculation of data usage
- **Enable/Disable**: Toggle profiles without deletion
- **Visual Management**: Card-based interface with status indicators

### Stream Quality Presets

| Preset | Bitrate | Channels | Use Case |
|--------|---------|----------|----------|
| **Low** | 64 kbps | Mono | Remote monitoring, low bandwidth |
| **Medium** | 128 kbps | Stereo | Standard quality streaming |
| **High** | 192 kbps | Stereo | High quality monitoring |
| **Premium** | 320 kbps | Stereo | Maximum quality, archive |

### Creating a Stream Profile

#### Quick Method (Using Presets)

1. Navigate to **Settings** → **Stream Profiles**
2. Click **"Create Profile"**
3. Select a quality preset (Low/Medium/High/Premium)
4. Enter a profile name (e.g., "Low Bandwidth Monitor")
5. The mount point, bitrate, and channels are auto-configured
6. Optionally customize other settings
7. Click **"Create Profile"**

#### Custom Method

1. Navigate to **Settings** → **Stream Profiles**
2. Click **"Create Profile"**
3. Select **"Custom"** preset
4. Configure all settings manually:
   - **Name**: Descriptive identifier
   - **Mount Point**: URL path (e.g., `/high.mp3`)
   - **Format**: MP3, OGG, Opus, or AAC
   - **Bitrate**: 32-320 kbps
   - **Channels**: Mono (1) or Stereo (2)
   - **Sample Rate**: 16000-48000 Hz
   - **Description**: Optional notes
   - **Genre**: Metadata field
5. Toggle **"Enable this profile"** as needed
6. Click **"Create Profile"**

### Managing Profiles

Each profile card displays:
- Profile name and status (Enabled/Disabled)
- Description
- Mount point and format
- Bitrate and audio settings
- Estimated bandwidth usage per hour

**Available Actions:**
- **Edit**: Modify profile settings
- **Enable/Disable**: Toggle profile without deletion
- **Delete**: Permanently remove profile

### Use Cases

#### Scenario 1: Multiple Quality Levels

Create profiles for different listener needs:

```
Standard Stream (/stream.mp3) - 128 kbps stereo
  → For general web browser listening

Mobile Stream (/mobile.mp3) - 64 kbps mono
  → For mobile devices on cellular

Archive Stream (/archive.mp3) - 192 kbps stereo
  → For recording and documentation
```

#### Scenario 2: Format Diversity

Support different client capabilities:

```
MP3 Stream (/stream.mp3) - 128 kbps
  → Universal compatibility

OGG Stream (/stream.ogg) - 128 kbps
  → Modern browsers, open format

Opus Stream (/stream.opus) - 96 kbps
  → Best quality per bitrate, modern clients
```

#### Scenario 3: Bandwidth Management

When bandwidth is limited, create targeted profiles:

```
Internal Monitor (/internal.mp3) - 192 kbps
  → High quality for local network

Remote Monitor (/remote.mp3) - 48 kbps mono
  → Low bandwidth for remote sites
```

### Bandwidth Estimation

The dashboard shows estimated bandwidth usage:
- **Per Profile**: Individual stream data usage
- **Total**: Combined usage for all active streams
- Calculated per hour of continuous streaming
- Useful for:
  - Capacity planning
  - ISP bandwidth limits
  - Cost estimation (metered connections)

**Formula**: `Bitrate (kbps) × 3600 seconds ÷ 8 ÷ 1024 = MB per hour`

**Example**: 128 kbps stream ≈ 55 MB per hour

### Technical Details

#### FFmpeg Integration

Stream profiles generate optimized FFmpeg encoding parameters:

**MP3 Profile:**
```bash
-codec:a libmp3lame -b:a 128k -q:a 2 -ar 44100 -ac 2
```

**OGG Vorbis Profile:**
```bash
-codec:a libvorbis -b:a 128k -ar 44100 -ac 2
```

**Opus Profile:**
```bash
-codec:a libopus -b:a 96k -vbr on -ar 48000 -ac 2
```

#### Storage Location

Profiles are stored in: `/app-config/stream-profiles/profiles.json`

This ensures persistence across container restarts.

#### Applying Changes

**Important:** After creating or modifying stream profiles:

1. Profile changes are saved immediately
2. Icecast service must be restarted to activate new streams
3. Restart command: `docker compose restart icecast`
4. Active streams may be briefly interrupted during restart

### Troubleshooting

**Profile not appearing in Icecast:**
- Ensure profile is enabled
- Restart Icecast service
- Check Icecast logs: `docker compose logs icecast`

**Mount point conflicts:**
- Each profile must have a unique mount point
- System prevents duplicate mount points
- Edit or delete conflicting profile

**Poor audio quality:**
- Increase bitrate setting
- Use stereo instead of mono
- Use higher sample rate (48000 Hz)

**High bandwidth usage:**
- Reduce bitrate for active profiles
- Disable unused profiles
- Use mono instead of stereo for monitoring

---

## Integration with Existing Features

### Relationship to Audio Settings

Stream profiles complement the audio settings page (`/settings/audio`):

- **Audio Settings**: Configure input sources and monitoring
- **Stream Profiles**: Configure output streaming to Icecast

Both pages work together for complete audio pipeline management.

### Relationship to System Health

System diagnostics integrates with existing monitoring:

- **Health Endpoint** (`/health/dependencies`): JSON API for automation
- **Diagnostics Page** (`/diagnostics`): Human-friendly web interface
- **Admin Dashboard** (`/admin`): Summary of system status

Use diagnostics for detailed troubleshooting and validation.

---

## API Access

Both features provide programmatic access:

### Diagnostics API

```bash
# Run validation checks
POST /api/diagnostics/validate

# Returns:
{
  "success": true,
  "passed": ["Check 1 passed", ...],
  "warnings": ["Warning 1", ...],
  "failed": ["Check 1 failed", ...],
  "info": ["Info 1", ...]
}
```

### Stream Profiles API

```bash
# List all profiles
GET /api/stream-profiles

# Get specific profile
GET /api/stream-profiles/{name}

# Create profile
POST /api/stream-profiles
Content-Type: application/json
{
  "name": "my-stream",
  "mount": "/my-stream.mp3",
  "format": "mp3",
  "bitrate": 128,
  ...
}

# Update profile
PUT /api/stream-profiles/{name}

# Delete profile
DELETE /api/stream-profiles/{name}

# Enable/disable profile
POST /api/stream-profiles/{name}/enable
POST /api/stream-profiles/{name}/disable

# Get bandwidth estimate
GET /api/stream-profiles/bandwidth-estimate?duration=3600
```

---

## Future Enhancements

Planned improvements for these features:

### Diagnostics
- [ ] Automated scheduling (run diagnostics on cron)
- [ ] Email alerts for failed checks
- [ ] Historical trend analysis
- [ ] Performance benchmarking
- [ ] Integration with monitoring tools (Prometheus, etc.)

### Stream Profiles
- [ ] Live preview of stream quality
- [ ] Automatic bitrate adjustment
- [ ] Multi-language support for metadata
- [ ] Stream statistics and listener counts
- [ ] Hot reload without Icecast restart

---

## References

- [Quick Start Guide](deployment/quick_start.md) - Initial setup
- [Admin Guide](guides/PORTAINER_DEPLOYMENT.md) - Administration
- [Audio Setup](../PROFESSIONAL_AUDIO_SUBSYSTEM.md) - Audio configuration
- [System Health](../SYSTEM_HEALTH_ENHANCEMENTS.md) - Health monitoring
- [API Documentation](frontend/JAVASCRIPT_API.md) - API reference

---

**Questions or Issues?**

- Check [Troubleshooting Scripts](../../scripts/diagnostics/README.md)
- Review [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
- Join [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)
