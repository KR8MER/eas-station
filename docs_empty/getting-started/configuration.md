# Configuration Guide

This guide covers all environment variables and configuration options for EAS Station.

## Configuration File

EAS Station uses environment variables defined in `.env` file. Never commit this file to version control.

```bash
# Create from example
cp .env.example .env

# Edit configuration
nano .env  # or your preferred editor
```

## Core Settings

### Application Basics

```bash
# Secret key for session encryption (REQUIRED)
# Generate with: python3 -c 'import secrets; print(secrets.token_hex(32))'
SECRET_KEY=your-64-character-hex-key-here

# Application version
APP_BUILD_VERSION=2.3.12

# Flask environment
FLASK_ENV=production
FLASK_DEBUG=false
```

!!! danger "Security Critical"
    **Never use the default SECRET_KEY!** Generate a unique key:
    ```bash
    python3 -c 'import secrets; print(secrets.token_hex(32))'
    ```

### Database Configuration

```bash
# Database host (use 'alerts-db' for embedded container)
POSTGRES_HOST=alerts-db

# Database connection details
POSTGRES_PORT=5432
POSTGRES_DB=alerts
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change-me-to-secure-password
```

**Database Host Options:**

| Value | Use Case |
|-------|----------|
| `alerts-db` | Embedded PostgreSQL container (default) |
| `host.docker.internal` | Database on Docker host |
| `192.168.1.100` | External database server |
| `db.example.com` | Managed database service |

## Location Settings

Configure your geographic location for alert filtering:

```bash
# Timezone (see: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
DEFAULT_TIMEZONE=America/New_York

# County and state
DEFAULT_COUNTY_NAME=Putnam County
DEFAULT_STATE_CODE=OH

# SAME zone codes (comma-separated)
DEFAULT_ZONE_CODES=OHZ016,OHC137

# Area search terms (comma-separated)
DEFAULT_AREA_TERMS=PUTNAM COUNTY,PUTNAM CO,OTTAWA,LEIPSIC

# Map display center (latitude, longitude, zoom)
DEFAULT_MAP_CENTER_LAT=41.0195
DEFAULT_MAP_CENTER_LNG=-84.1190
DEFAULT_MAP_ZOOM=9
```

### Finding Your Zone Codes

1. Visit [NWS Zone Map](https://www.weather.gov/gis/ZoneCounty)
2. Find your county on the map
3. Note the zone code (e.g., OHZ016)
4. Add both zone and county SAME codes

## Alert Polling

```bash
# Polling interval in seconds (180 = 3 minutes)
POLL_INTERVAL_SEC=180

# HTTP timeout for CAP feeds
CAP_TIMEOUT=30

# User agent for NOAA API (REQUIRED for compliance)
NOAA_USER_AGENT=YourOrganization EAS/1.0 (+https://example.com; email@example.com)
```

!!! warning "NOAA User Agent Required"
    NOAA requires a descriptive user agent. Include:

    - Organization/project name
    - Version number
    - Contact URL or email

### Custom Alert Sources

```bash
# Override default CAP endpoints (comma-separated URLs)
CAP_ENDPOINTS=

# Additional IPAWS feeds (comma-separated URLs)
IPAWS_CAP_FEED_URLS=

# IPAWS lookback period in hours
IPAWS_DEFAULT_LOOKBACK_HOURS=12
```

## EAS Broadcast Settings

Configure SAME encoding and audio generation:

```bash
# Enable/disable EAS broadcast features
EAS_BROADCAST_ENABLED=false

# EAS identification
EAS_ORIGINATOR=WXR          # WXR for weather, EAS for government
EAS_STATION_ID=EASNODES     # 8 characters, alphanumeric

# Audio output
EAS_OUTPUT_DIR=static/eas_messages
EAS_SAMPLE_RATE=44100
EAS_AUDIO_PLAYER=aplay
EAS_ATTENTION_TONE_SECONDS=8

# Manual broadcast authorization
EAS_MANUAL_FIPS_CODES=039137    # County FIPS codes
EAS_MANUAL_EVENT_CODES=TESTS    # Allowed event codes
```

### Originator Codes

| Code | Meaning | Use |
|------|---------|-----|
| `WXR` | Weather Service | NOAA/NWS alerts |
| `PEP` | Primary Entry Point | National alerts |
| `CIV` | Civil Authority | Local government |
| `EAS` | EAS Participant | General use |

### GPIO Relay Control

For transmitter keying via GPIO:

```bash
# GPIO pin number (leave blank to disable)
EAS_GPIO_PIN=17

# Active state (HIGH or LOW)
EAS_GPIO_ACTIVE_STATE=HIGH

# Hold time in seconds
EAS_GPIO_HOLD_SECONDS=5
```

!!! info "Raspberry Pi GPIO"
    Use BCM pin numbering. Common pins: 17, 18, 27, 22. Requires `RPi.GPIO` library.

## Text-to-Speech

Configure voice synthesis for alert messages:

```bash
# Provider: azure, azure_openai, pyttsx3, or blank to disable
EAS_TTS_PROVIDER=

# Azure OpenAI TTS (recommended)
AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
AZURE_OPENAI_KEY=your-api-key-here
AZURE_OPENAI_VOICE=alloy
AZURE_OPENAI_MODEL=tts-1-hd
AZURE_OPENAI_SPEED=1.0
```

### TTS Providers

| Provider | Quality | Cost | Setup |
|----------|---------|------|-------|
| `azure_openai` | Excellent | Pay-per-use | API key required |
| `azure` | Good | Pay-per-use | API key required |
| `pyttsx3` | Basic | Free | Built-in |

### Voice Options (Azure OpenAI)

- `alloy` - Neutral, clear
- `echo` - Male, authoritative
- `fable` - Warm, expressive
- `onyx` - Deep, male
- `nova` - Female, friendly
- `shimmer` - Soft, female

## LED Display

Configure Alpha Protocol LED signs:

```bash
# LED sign IP and port
LED_SIGN_IP=192.168.1.100
LED_SIGN_PORT=10001

# Default display lines (comma-separated)
DEFAULT_LED_LINES=PUTNAM COUNTY,EMERGENCY MGMT,NO ALERTS,SYSTEM READY
```

## Notifications

### Email Notifications

```bash
# Enable email alerts
ENABLE_EMAIL_NOTIFICATIONS=false

# SMTP configuration
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-app-password
```

### SMS Notifications

```bash
# Enable SMS alerts
ENABLE_SMS_NOTIFICATIONS=false
```

!!! tip "Gmail SMTP"
    For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833) instead of your regular password.

## Logging & Performance

```bash
# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO

# Log file location
LOG_FILE=logs/eas_station.log

# Cache timeout (seconds)
CACHE_TIMEOUT=300

# Worker processes
MAX_WORKERS=2

# Upload directory
UPLOAD_FOLDER=/app/uploads
```

## Docker Infrastructure

```bash
# Container timezone
TZ=America/New_York

# Watchtower auto-updates
WATCHTOWER_LABEL_ENABLE=true
WATCHTOWER_MONITOR_ONLY=false

# Database image
ALERTS_DB_IMAGE=postgis/postgis:17-3.4
```

## Environment Validation

Validate your configuration:

```bash
# Check for required variables
docker compose config

# Test database connection
docker compose exec eas-station python -c "
from app_core.models import db
print('Database connection successful!')
"
```

## Security Best Practices

### Production Checklist

- [x] Generate unique `SECRET_KEY`
- [x] Use strong database password
- [x] Disable `FLASK_DEBUG`
- [x] Set `FLASK_ENV=production`
- [x] Use HTTPS for web access
- [x] Restrict database access
- [x] Regular backups configured
- [x] Log rotation enabled

### Sensitive Data

Never commit these to version control:

- `SECRET_KEY`
- Database passwords
- API keys (Azure, email, etc.)
- IP addresses or hostnames

## Configuration Templates

### Minimal Configuration (Testing)

```bash
SECRET_KEY=replace-with-generated-key
POSTGRES_HOST=alerts-db
POSTGRES_PASSWORD=secure-password
DEFAULT_COUNTY_NAME=Your County
DEFAULT_STATE_CODE=XX
```

### Full Production Configuration

```bash
# Core
SECRET_KEY=your-64-char-key
FLASK_ENV=production
FLASK_DEBUG=false

# Database (external)
POSTGRES_HOST=db.example.com
POSTGRES_DB=alerts
POSTGRES_USER=eas_admin
POSTGRES_PASSWORD=very-secure-password

# Location
DEFAULT_TIMEZONE=America/New_York
DEFAULT_COUNTY_NAME=Example County
DEFAULT_STATE_CODE=NY
DEFAULT_ZONE_CODES=NYZ001,NYC001

# Broadcast
EAS_BROADCAST_ENABLED=true
EAS_ORIGINATOR=WXR
EAS_STATION_ID=KEXAMPLE

# TTS
EAS_TTS_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_OPENAI_KEY=your-key

# LED
LED_SIGN_IP=192.168.1.50
```

## Next Steps

After configuration:

- [Set Up First Alert](first-alert.md)
- [Configure Hardware](../user-guide/hardware/index.md)
- [Tune Performance](../admin-guide/configuration/performance.md)

---

For complete reference, see [Configuration Reference](../reference/configuration.md).
