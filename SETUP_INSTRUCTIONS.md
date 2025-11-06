# EAS Station Setup Instructions

## Quick Start

### First-Time Setup

**Important:** Before starting the Docker containers, you must initialize the environment:

```bash
# 1. Initialize the environment (creates empty .env file)
./init-env.sh

# 2. Start the Docker stack
docker-compose up -d

# 3. Access the setup wizard in your browser
# Navigate to: http://localhost/setup
```

The setup wizard will guide you through configuring your `.env` file without needing to edit it manually.

### Why the init-env.sh Script?

Docker creates the `.env` file as a directory if it doesn't exist on the host before mounting it. This causes the setup wizard to fail when trying to write configuration. The `init-env.sh` script ensures `.env` exists as a file before Docker starts.

## Setup Wizard Features

The web-based setup wizard provides:

### Core Configuration
- **SECRET_KEY** - One-click generation of secure 64-character token
- **Database Connection** - PostgreSQL host, port, credentials
- **Timezone** - Dropdown selection of US timezones
- **Location** - State code dropdown, county name

### EAS Broadcast Settings
- **EAS Originator** - Dropdown of FCC-authorized codes (WXR, EAS, CIV, PEP)
- **Station ID** - Validated to 8 characters, no dashes
- **FIPS Codes** - Authorized county codes for manual broadcasts
- **Zone Codes** - Auto-derive from FIPS codes with one click

### Audio & TTS
- **Audio Ingest** - Enable/disable SDR and ALSA sources
- **TTS Provider** - Dropdown selection (pyttsx3, Azure, Azure OpenAI)

### Hardware Integration
- **LED Sign** - IP address configuration
- **VFD Display** - Serial port configuration

## Troubleshooting

### Error: ".env was created as a directory by Docker"

If you see this error in the logs:

```bash
# 1. Stop the containers
docker-compose down

# 2. Remove the .env directory
rm -rf .env

# 3. Run the initialization script
./init-env.sh

# 4. Start the containers again
docker-compose up -d
```

### Configuration Not Persisting

If changes in the setup wizard don't persist after restarting:

1. Verify `.env` is a file, not a directory:
   ```bash
   ls -la .env
   # Should show: -rw-r--r-- (file), not drwxr-xr-x (directory)
   ```

2. Check that the volume mount is working:
   ```bash
   docker-compose exec app ls -la /app/.env
   # Should show a file, not a directory
   ```

3. After saving configuration, restart the stack:
   ```bash
   docker-compose restart
   ```

## Manual Configuration (Advanced)

If you prefer to configure manually instead of using the web wizard:

```bash
# 1. Copy the example file
cp .env.example .env

# 2. Generate a secret key
python3 -c "import secrets; print(secrets.token_hex(32))"

# 3. Edit .env with your values
nano .env

# 4. Start the stack
docker-compose up -d
```

## After Configuration

Once configured, the `.env` file will contain your settings. To modify:

1. **Using the Setup Wizard** (Recommended):
   - Navigate to: http://localhost/setup
   - Make changes
   - Click "Save configuration"
   - Restart: `docker-compose restart`

2. **Manually Editing .env**:
   - Edit the file: `nano .env`
   - Restart: `docker-compose restart`

## Auto-Derive Zone Codes

The setup wizard can automatically derive NWS zone codes from FIPS county codes:

1. Enter FIPS codes in "Authorized FIPS Codes" field (e.g., `039001,039003`)
2. Click "Auto-Derive" button next to "Default Zone Codes"
3. Zone codes will be populated automatically (e.g., `OHZ001,OHC001`)

This uses the existing county-to-zone mapping logic to save you from manual lookup.

## Validation Features

The setup wizard validates your input:

- **SECRET_KEY**: Minimum 32 characters
- **EAS_STATION_ID**: Maximum 8 characters, no dashes
- **DEFAULT_STATE_CODE**: Must be valid 2-letter state abbreviation
- **Timezone**: Must be valid IANA timezone
- **Port Numbers**: Must be 1-65535

Clear error messages guide you to correct any issues.

## Getting Help

- **GitHub Issues**: https://github.com/KR8MER/eas-station/issues
- **Documentation**: See `docs/` directory
- **Setup Wizard Docs**: See `docs/SETUP_WIZARD.md`
