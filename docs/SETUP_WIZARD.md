# Setup Wizard Documentation

## Overview

The Setup Wizard provides a web-based interface for configuring EAS Station during initial deployment and for updating environment variables after installation. This guide covers the setup wizard functionality, recent fixes, and best practices.

---

## Accessing the Setup Wizard

### Initial Setup Mode
When EAS Station is first deployed or when critical configuration is missing, the application automatically enters "Setup Mode". In this state:
- The setup wizard is accessible at `/setup` without authentication
- Most other routes redirect to the setup wizard
- Setup mode activates when:
  - `SECRET_KEY` is missing or uses a placeholder value
  - Database connection cannot be established

### Normal Access
After initial configuration, administrators can access the wizard at:
- **URL**: `/setup`
- **Requirement**: Must be logged in as an administrator
- **Navigation**: Settings → Environment Settings (or direct URL)

---

## Recent Fixes (January 2025)

### 🐛 Issues Resolved

#### 1. **Binary Input Fields Using Text Inputs**
**Problem**: Boolean configuration fields (true/false) used free-text inputs, allowing users to enter invalid values like "TRUE", "True", "yes", "1", etc., causing validation errors.

**Solution**: All boolean fields now use dropdown menus with fixed options:
- `EAS_BROADCAST_ENABLED`
- `AUDIO_INGEST_ENABLED`
- `AUDIO_ALSA_ENABLED`
- `AUDIO_SDR_ENABLED`

**Before**:
```html
<input type="text" name="EAS_BROADCAST_ENABLED" value="true">
<!-- User could type: "TRUE", "True", "yes", "1", etc. - all invalid! -->
```

**After**:
```html
<select name="EAS_BROADCAST_ENABLED">
  <option value="">-- Select --</option>
  <option value="true">Enabled</option>
  <option value="false">Disabled</option>
</select>
<!-- User must select valid option - no typing errors possible! -->
```

#### 2. **Generate Secret Key Button Not Working**
**Problem**: Clicking "Generate" button for SECRET_KEY failed silently or returned errors.

**Root Cause**: JavaScript fetch URL using `url_for('setup_generate_secret')` which may not resolve correctly in all deployment scenarios.

**Solution**: The route `/setup/generate-secret` is properly registered and tested. The button now:
- Shows spinner during generation
- Fills the SECRET_KEY field with a 64-character hex token
- Removes validation errors on success
- Displays user-friendly error messages on failure

#### 3. **Save Configuration Returns 400 Error**
**Problem**: Submitting the setup form resulted in HTTP 400 Bad Request errors.

**Root Causes**:
- Boolean validator rejected empty strings for optional fields
- Case-sensitive validation failed on "TRUE" vs "true"
- Missing CSRF token validation in some cases

**Solutions**:
- **Boolean Validator Updated**: Now handles empty values gracefully for optional fields
- **Case-Insensitive**: Accepts "true", "TRUE", "True" and normalizes to lowercase
- **CSRF Token**: Properly included in form and validated on submission

---

## Field Reference

### Core Settings (Required)

| Field | Description | Validation | Example |
|-------|-------------|------------|---------|
| **SECRET_KEY** | Flask session encryption key | Min 32 chars, not placeholder | Generated 64-char hex |
| **POSTGRES_HOST** | Database hostname/IP | Required | `db` or `192.168.1.10` |
| **POSTGRES_PORT** | Database port | 1-65535 | `5432` |
| **POSTGRES_DB** | Database name | Required | `eas_station` |
| **POSTGRES_USER** | Database username | Required | `postgres` |
| **POSTGRES_PASSWORD** | Database password | Required | (hidden) |

### Location Settings

| Field | Description | Validation | Example |
|-------|-------------|------------|---------|
| **DEFAULT_TIMEZONE** | System timezone | Region/City format | `America/New_York` |
| **DEFAULT_COUNTY_NAME** | County name | Optional | `Franklin County` |
| **DEFAULT_STATE_CODE** | Two-letter state code | Optional | `OH` |
| **DEFAULT_ZONE_CODES** | NWS zone codes | Comma-separated | `OHZ016,OHC137` |

### EAS Broadcast

| Field | Description | Validation | Options |
|-------|-------------|------------|---------|
| **EAS_BROADCAST_ENABLED** | Enable SAME/EAS | Dropdown | **Enabled** / **Disabled** |
| **EAS_ORIGINATOR** | Originator code | Optional, 3 chars | `WXR`, `EAS`, `CIV` |
| **EAS_STATION_ID** | Station identifier | Optional, 8 chars | `EASNODES` |
| **EAS_MANUAL_FIPS_CODES** | Authorized FIPS | Numeric, comma-sep | `039001,039049` |
| **EAS_GPIO_PIN** | GPIO relay pin | Optional, integer | `17` |

### Audio Ingest

| Field | Description | Validation | Options |
|-------|-------------|------------|---------|
| **AUDIO_INGEST_ENABLED** | Enable audio capture | Dropdown | **Enabled** / **Disabled** |
| **AUDIO_ALSA_ENABLED** | Enable ALSA source | Dropdown | **Enabled** / **Disabled** |
| **AUDIO_ALSA_DEVICE** | ALSA device name | Optional | `default`, `hw:0,0` |
| **AUDIO_SDR_ENABLED** | Enable SDR source | Dropdown | **Enabled** / **Disabled** |

### Text-to-Speech

| Field | Description | Validation | Example |
|-------|-------------|------------|---------|
| **EAS_TTS_PROVIDER** | TTS engine | Optional | `azure`, `pyttsx3`, blank |
| **AZURE_OPENAI_ENDPOINT** | Azure endpoint | Optional URL | `https://...` |
| **AZURE_OPENAI_KEY** | Azure API key | Optional (hidden) | (API key) |

### Hardware Integration

| Field | Description | Validation | Example |
|-------|-------------|------------|---------|
| **DEFAULT_LED_LINES** | LED sign lines | Textarea, multi-line | 4 lines of text |
| **LED_SIGN_IP** | LED sign IP address | Optional | `192.168.1.50` |
| **VFD_PORT** | VFD serial port | Optional | `/dev/ttyUSB0` |
| **OLED_ENABLED** | Enable OLED module | Optional (`true`/`false`) | `true` |
| **OLED_I2C_ADDRESS** | OLED I2C address | Optional | `0x3C` |

---

## Usage Guide

### First-Time Setup

1. **Deploy Stack**
   ```bash
   docker compose up -d
   ```

2. **Access Wizard**
   - Navigate to `http://localhost:5000` (or your server IP)
   - You'll be automatically redirected to `/setup`

3. **Generate Secret Key**
   - Click "Generate" button next to SECRET_KEY field
   - A secure 64-character key will be created automatically
   - **IMPORTANT**: Save this key - you'll need it if you manually edit `.env` later

4. **Configure Database**
   - Use Docker service names (e.g., `db` for Docker Compose setups)
   - Or use actual hostname/IP for external databases
   - Port is typically `5432` for PostgreSQL

5. **Set Location**
   - Choose your timezone using Region/City format (e.g., `America/Chicago`)
   - Enter your county and state for alert filtering
   - Add NWS zone codes if known (optional)

6. **Enable Features**
   - **EAS Broadcast**: Enable if you have audio hardware and want to generate SAME tones
   - **Audio Ingest**: Enable if capturing audio from SDR or line-in sources
   - Select specific audio sources (ALSA, SDR) as needed

7. **Configure Hardware** (Optional)
   - LED sign IP address if using Alpha protocol displays
   - VFD serial port if using Noritake VFD displays
   - OLED I2C address if using the Argon Industria OLED module
   - GPIO pin for relay control

8. **Backup Option**
   - Leave "Create a timestamped backup" checked (recommended)
   - This saves your current `.env` as `.env.backup-YYYYMMDD-HHMMSS`

9. **Save Configuration**
   - Click "Save configuration" button
   - Wait for confirmation message

10. **Download Your Configuration Backup (CRITICAL for Portainer!)**
    - You'll be redirected to the success page
    - **Click the big red "Download Backup Now" button**
    - Save the `.env` backup file securely
    - This backup is essential for Portainer deployments where config resets on redeploy

11. **Restart Docker Services**
    ```bash
    docker compose restart
    ```
    Or in Portainer: Stop → Start (NOT Redeploy)

### Updating Configuration

To modify existing configuration:

1. **Login** as administrator

2. **Navigate** to Settings → Environment Settings (or `/setup`)

3. **Modify Fields**
   - Existing values will be pre-filled
   - **SECRET_KEY** field is hidden for security
     - Leave blank to keep existing key
     - Click "Generate" to rotate the key (forces re-login)

4. **Save and Restart**
   ```bash
   docker compose restart
   ```

### Configuration Backup and Restore

#### Understanding Configuration Persistence

The setup wizard saves configuration to `/app/.env` inside the container:

- **Container Restart** (Stop/Start in Portainer): ✅ Configuration persists
- **Container Redeploy** (Git update/recreate): ❌ Configuration resets to empty

This is by design! The `.env` file in Git is intentionally empty to prevent secrets from being committed.

#### Backup Your Configuration

There are three ways to backup your configuration:

**1. Setup Wizard Success Page (Recommended)**
- After completing the wizard, click "Download Backup Now"
- Saves timestamped file: `eas-station-backup-20250106-143022.env`
- Store this file securely (contains passwords and secret keys!)

**2. Admin Environment Settings Page**
- Navigate to Settings → Environment Settings
- Click "Download .env Backup" button in top-right corner
- Same timestamped backup file is created

**3. Direct Download** (while in setup mode)
- Visit `/setup/view-env` to view current configuration
- Click download button to save

#### Restore Configuration After Redeployment

When you redeploy your stack from Git (e.g., to get updates), the `.env` file resets. To restore your configuration:

**Method 1: Upload Backup File (Fastest)**

1. After redeployment, visit `/setup` (setup wizard)
2. At the top, you'll see "Have a backup? Restore it here"
3. Click "Choose File" and select your backup `.env` file
4. Click "Restore & Skip Wizard"
5. Restart the container (Stop/Start in Portainer)

**Method 2: Paste into Portainer Environment Variables (Permanent)**

This method makes configuration permanent - no restore needed after redeployments:

1. Complete the setup wizard
2. On the success page, scroll to "Portainer Format (Ready to Paste)"
3. Click "Copy Format"
4. In Portainer, go to Stack → Editor tab
5. Scroll to "Environment variables" section
6. Paste the copied values
7. Click "Update the stack"

Now your configuration persists across all future deployments!

#### Download from Admin Panel

After logging in as administrator:

1. Navigate to **Settings → Environment Settings**
2. Click **"Download .env Backup"** button (top-right)
3. Backup file is saved with timestamp
4. Keep this file safe - it contains sensitive credentials

#### Backup Best Practices

- **Download backup immediately** after completing wizard
- **Store securely**: Backups contain SECRET_KEY, database passwords, API keys
- **Keep one backup per deployment**: Delete old backups to avoid confusion
- **Never commit backups to Git**: Add `*.env` to `.gitignore` (already configured)
- **Rotate backups**: When you update config, download a new backup

---

## Validation Rules

### Boolean Fields
- **Must be**: `true` or `false` (case-insensitive)
- **Empty is OK**: For optional fields
- **Invalid Examples**: `yes`, `no`, `1`, `0`, `TRUE`, `FALSE` (now prevented by dropdowns)

### Port Numbers
- **Range**: 1-65535
- **Example**: `5432` ✅, `99999` ❌

### Timezone Format
- **Format**: `Region/City`
- **Example**: `America/New_York` ✅, `EST` ❌

### FIPS Codes
- **Format**: Numeric, comma-separated
- **Example**: `039001,039049` ✅, `OH-FRA` ❌

### Secret Key
- **Min Length**: 32 characters
- **Recommended**: 64 characters (auto-generated)
- **Security**: Never use placeholders like `dev-key-change-in-production`

---

## Troubleshooting

### "Must be 'true' or 'false'" Error
**This should no longer occur** with dropdown menus. If you see this:
- Clear your browser cache (old page may be cached)
- Hard refresh: `Ctrl+F5` (Windows) or `Cmd+Shift+R` (Mac)
- Ensure you're using the latest version of the application

### Generate Secret Button Not Working
1. **Check Browser Console**: `F12` → Console tab
2. **Look for errors**: Network errors, CORS issues, or JavaScript errors
3. **Try Manual Generation**:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   Copy and paste the result into the SECRET_KEY field

### 400 Bad Request on Save
1. **Check Required Fields**: All fields marked with red `*` must be filled
2. **Validate Format**:
   - Timezone: Must contain `/` (e.g., `America/New_York`)
   - Port: Must be a number between 1-65535
   - FIPS: Must be numeric only
3. **Check Error Messages**: Red text below fields indicates specific problems
4. **Check Logs**:
   ```bash
   docker compose logs app | grep ERROR
   ```

### Changes Not Taking Effect
- **Restart Required**: Configuration changes require restart
  ```bash
  docker compose restart
  ```
- **Check .env File**: Verify changes were written
  ```bash
  cat .env | grep SECRET_KEY
  ```
- **Backup Restored?**: If backup checkbox was checked, verify correct file is active

---

## Security Considerations

### Secret Key Management
- **Never commit** `.env` file to version control
- **Rotate keys** periodically (every 90 days recommended)
- **Use generated keys**: Don't create your own - use the generator
- **Backup securely**: Store SECRET_KEY in password manager

### Password Fields
- Database passwords are type=password (hidden)
- API keys are type=password (hidden)
- Values are not displayed when editing existing configuration

### Backup Files
- Backups are created with timestamp: `.env.backup-20250106-143022`
- **Secure these files**: They contain sensitive credentials
- **Clean up old backups**: Don't accumulate dozens of backups
- **Delete before deployment**: Don't ship backup files in Docker images

---

## Development Notes

### Form Input Standards (AGENTS.md Compliance)

As documented in `docs/development/AGENTS.md`, binary choices MUST use proper UI controls:

✅ **CORRECT**: Dropdown menus
```html
<select name="EAS_BROADCAST_ENABLED">
  <option value="true">Enabled</option>
  <option value="false">Disabled</option>
</select>
```

❌ **WRONG**: Free-text input
```html
<input type="text" name="EAS_BROADCAST_ENABLED">
```

### Adding New Fields

When adding new configuration fields:

1. **Define Field** in `app_utils/setup_wizard.py`:
   ```python
   WizardField(
       key="MY_NEW_SETTING",
       label="My New Setting",
       description="What this setting does",
       validator=_validate_bool,  # Use existing validators
       required=False,  # Or True
   )
   ```

2. **Add to Section**: Append to appropriate field list (CORE_FIELDS, EAS_FIELDS, etc.)

3. **Update Template** (if binary): Add key to dropdown check in `templates/setup_wizard.html`:
   ```html
   {% elif field.key in ['EAS_BROADCAST_ENABLED', 'MY_NEW_SETTING'] %}
   ```

4. **Update .env.example**: Add default value

5. **Document** in this file and `NEW_FEATURES.md`

### Custom Validators

Create validator functions following this pattern:

```python
def _validate_my_field(value: str) -> str:
    """Validate my custom field."""
    # Allow empty for optional fields
    if not value or not value.strip():
        return ""

    # Your validation logic
    if not is_valid(value):
        raise ValueError("Helpful error message for user")

    # Return normalized value
    return value.strip().lower()
```

---

## API Reference

### Routes

#### `GET /setup`
- **Purpose**: Display setup wizard form
- **Auth**: Required unless SETUP_MODE=true
- **Returns**: HTML form with current configuration

#### `POST /setup`
- **Purpose**: Save configuration changes
- **Auth**: Required unless SETUP_MODE=true
- **Body**: Form data with field values
- **Returns**: Redirect to `/setup` with flash message

#### `POST /setup/generate-secret`
- **Purpose**: Generate random SECRET_KEY
- **Auth**: Required unless SETUP_MODE=true
- **Returns**: JSON with `secret_key` field
- **Example Response**:
  ```json
  {
    "secret_key": "a1b2c3d4e5f6...64 characters total"
  }
  ```

#### `GET /setup/download-env`
- **Purpose**: Download current .env file as backup
- **Auth**: Required unless SETUP_MODE=true
- **Returns**: File download with timestamped filename
- **Filename Format**: `eas-station-backup-YYYYMMDD-HHMMSS.env`

#### `POST /setup/upload-env`
- **Purpose**: Restore .env file from backup
- **Auth**: Required unless SETUP_MODE=true
- **Body**: Multipart form data with `env_file` field
- **Returns**: JSON with success/error message
- **Example Response**:
  ```json
  {
    "success": true,
    "message": "Configuration restored successfully. Please restart the container for changes to take effect."
  }
  ```
- **Validation**: File must have `.env` extension and contain `SECRET_KEY=`

#### `GET /setup/success`
- **Purpose**: Display configuration success page with backup download
- **Auth**: Required unless SETUP_MODE=true
- **Returns**: HTML page with download button and restore instructions

#### `GET /setup/view-env`
- **Purpose**: View current .env file contents for debugging
- **Auth**: Required unless SETUP_MODE=true
- **Returns**: HTML page showing file metadata and contents

#### `GET /admin/environment/download-env`
- **Purpose**: Download .env backup from admin environment settings page
- **Auth**: Required (admin user with system.view_config permission)
- **Returns**: File download with timestamped filename
- **Access**: Settings → Environment Settings → "Download .env Backup" button

### CSRF Protection

All POST requests require CSRF token:
```html
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
```

JavaScript requests must include token in headers:
```javascript
headers: {
  'Content-Type': 'application/json',
  'X-CSRF-Token': csrfToken
}
```

---

## Testing

### Manual Test Checklist

- [ ] Access `/setup` without .env file (should show wizard)
- [ ] Click "Generate" button - fills SECRET_KEY field
- [ ] Select "Enabled" from boolean dropdowns
- [ ] Fill all required fields with valid data
- [ ] Click "Save configuration" - should succeed
- [ ] Verify `.env` file created with correct values
- [ ] Verify backup file created (if checkbox was checked)
- [ ] Restart services - application should start normally
- [ ] Access `/setup` again - fields pre-filled with saved values
- [ ] Modify a field and save - should update `.env`
- [ ] Leave SECRET_KEY blank when editing - should preserve existing key

### Automated Tests

```python
# Test boolean validator
def test_validate_bool_empty():
    result = _validate_bool("")
    assert result == ""

def test_validate_bool_case_insensitive():
    assert _validate_bool("TRUE") == "true"
    assert _validate_bool("False") == "false"

def test_validate_bool_with_whitespace():
    assert _validate_bool("  true  ") == "true"
```

---

## Migration Guide

If you're upgrading from a version before these fixes:

### For Users
1. **Clear Browser Cache**: Old template may be cached
2. **Re-save Configuration**: Visit `/setup` and re-save to validate
3. **Check Boolean Fields**: Ensure all enabled/disabled settings are lowercase `true`/`false`
4. **Restart Services**: `docker compose restart`

### For Developers
1. **Update Templates**: Add dropdown checks for binary fields
2. **Update Validators**: Use new `_validate_bool` that handles empty strings
3. **Test Edge Cases**: Empty values, whitespace, case variations
4. **Update Documentation**: Add new fields to this guide

---

## FAQ

**Q: Do I need to rotate SECRET_KEY regularly?**
A: Yes, every 90 days is recommended. Click "Generate" and restart services.

**Q: What happens if I delete .env and restart?**
A: Application enters SETUP_MODE and shows the wizard on `/setup`.

**Q: Can I edit .env manually instead of using the wizard?**
A: Yes, but be careful with formatting. Restart services after editing.

**Q: Why do I need to restart after changing config?**
A: Flask loads environment variables at startup. Changes won't apply until restart.

**Q: Can I use environment variables instead of .env file?**
A: Yes, Docker Compose supports `environment:` in docker-compose.yml. Those take precedence over .env.

**Q: What if I lose my SECRET_KEY?**
A: All users will be logged out and need to log in again. Sessions are encrypted with this key.

---

## Related Documentation

- **AGENTS.md**: Development guidelines including form input standards
- **NEW_FEATURES.md**: Overview of all new features including setup wizard
- **.env.example**: Template with all available configuration options
- **README.md**: General deployment and configuration guide

---

**Last Updated**: 2025-01-06 (Added backup/restore functionality)
**Version**: 2.1.0 (Backup/Restore Support)
