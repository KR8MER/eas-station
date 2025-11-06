# EAS Station Setup Instructions

## Quick Start

### Portainer Deployment (Recommended)

The repository now includes an empty `.env` file, making Portainer deployments seamless:

1. **Deploy the stack in Portainer**
   - Add the Git repository
   - Deploy using `docker-compose.yml` or `docker-compose.embedded-db.yml`
   - No pre-configuration needed!

2. **Access the setup wizard**
   - Navigate to: `http://your-server/setup`
   - Complete the configuration using the web interface

3. **Restart the stack** in Portainer after saving configuration

That's it! The `.env` file is now included in the repository and will persist your configuration.

### Docker Compose (Command Line)

For command-line deployments:

```bash
# 1. Clone the repository
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# 2. Start the Docker stack
docker-compose up -d

# 3. Access the setup wizard
# Navigate to: http://localhost/setup

# 4. After configuration, restart
docker-compose restart
```

The `.env` file is already included in the repository, so no initialization script is needed.

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

This should no longer occur with the latest repository version (which includes .env).

If you deployed from an older version and see this error:

**Portainer:**
1. Stop and remove the stack in Portainer
2. Redeploy from the latest Git repository
3. The .env file is now included automatically

**Docker Compose:**
```bash
docker-compose down
rm -rf .env
git pull
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
