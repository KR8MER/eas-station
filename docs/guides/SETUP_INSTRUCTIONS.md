# EAS Station™ Setup Instructions

## Quick Start

### Installer (Recommended)

The interactive installer collects all required configuration up front and writes `/opt/eas-station/.env` for you:

```bash
# 1. Clone the repository
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# 2. Run the interactive installer
sudo bash install.sh
```

When the installer finishes, all services are running. Open `https://your-server-ip` and log in with the administrator account you created during installation.

### Setup Wizard (Fine-Tuning)

After installation, the web-based setup wizard at `https://your-server/setup` lets you review and adjust configuration:

1. Navigate to: `https://your-server/setup`
2. Complete or adjust the configuration using the web interface
3. After saving, restart the affected services:

```bash
sudo systemctl restart eas-station-web eas-station-poller
```

## Setup Wizard Features

The web-based setup wizard organizes configuration into seven collapsible
sections instead of one long form. **Location Settings** and **EAS
Broadcast** — the two every install needs — are open by default; everything
else starts collapsed so hardware and streaming options you're not using
don't get in the way. A section auto-expands if one of its fields fails
validation, so an error is never hidden behind a collapsed header. A
"Before you start" panel at the top explains what information to have
ready before you begin.

### Core Settings (collapsed by default)
- **SECRET_KEY** and the four **PostgreSQL** connection fields — install.sh
  already configures these. Whenever a field already holds a valid value,
  the wizard blanks the input and shows *"Already configured — leave blank
  to keep the current value"* instead of re-displaying (or re-prompting
  for) something you never chose. Leaving it blank on save keeps the
  existing value; typing a new one replaces it.

### Location Settings (open by default)
- **Timezone** - Dropdown selection of US timezones
- **County / State** - State code dropdown, county name
- **Zone Codes** - Auto-derive from FIPS codes with one click

### EAS Broadcast (open by default)
- **EAS Originator** - Dropdown of FCC-authorized codes (WXR, EAS, CIV, PEP)
- **Station ID** - Validated to 8 characters, no dashes
- **FIPS Codes** - Authorized county codes for manual broadcasts, via an
  interactive state/county picker

### Audio Ingest (collapsed by default)
- Enable/disable SDR and ALSA capture sources

### Icecast Streaming (collapsed by default)
- Public hostname, ports, listener limits, and source/relay/admin passwords
  for streaming audio to remote listeners

### Text-to-Speech (collapsed by default)
- **TTS Provider** - Dropdown selection (pyttsx3, Azure, Azure OpenAI) and
  provider credentials

### Hardware Integration (collapsed by default)
- **LED Sign** - IP address configuration
- **VFD Display** - Serial port configuration
- **OLED Module** - I2C bus/address, panel size, and rotation

## Troubleshooting

### Configuration Not Persisting

If changes in the setup wizard don't persist after restarting:

1. Verify `.env` is a file, not a directory:
   ```bash
   ls -la .env
   # Should show: -rw-r--r-- (file), not drwxr-xr-x (directory)
   ```

2. Verify the application user can write to it:
   ```bash
   ls -la /opt/eas-station/.env
   sudo -u eas-station test -w /opt/eas-station/.env && echo writable
   ```

3. After saving configuration, restart the services:
   ```bash
   sudo systemctl restart eas-station-web eas-station-poller
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

# 4. Restart the services
sudo systemctl restart eas-station-web eas-station-poller
```

## After Configuration

Once configured, the `.env` file will contain your settings. To modify:

1. **Using the Setup Wizard** (Recommended):
   - Navigate to: http://localhost/setup
   - Make changes
   - Click "Save configuration"

2. **Manually Editing .env**:
   - Edit the file: `nano .env`

## Auto-Derive Zone Codes

The setup wizard can automatically derive NWS zone codes from FIPS county codes:

1. Enter FIPS codes in "Authorized FIPS Codes" field (e.g., `039001,039003`)
2. Click "Auto-Derive" button next to "Default Zone Codes"
3. Zone codes will be populated automatically (e.g., `OHZ001,OHC001`)

This uses the existing county-to-zone mapping logic to save you from manual lookup.

## Validation Features

The setup wizard validates your input:

- **SECRET_KEY**: Minimum 32 characters
- **Station ID** (configured at the Broadcast admin tab, persisted in `eas_settings.station_id`): Maximum 8 characters, no dashes
- **DEFAULT_STATE_CODE**: Must be valid 2-letter state abbreviation
- **Timezone**: Must be valid IANA timezone
- **Port Numbers**: Must be 1-65535

Clear error messages guide you to correct any issues.

## Getting Help

- **GitHub Issues**: https://github.com/KR8MER/eas-station/issues
- **Documentation**: See the `docs/` directory (start with [`docs/README.md`](../README.md))
