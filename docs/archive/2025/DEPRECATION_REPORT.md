# Environment Variables Deprecation Report

## Summary

This report identifies deprecated and unused environment variables in your `.env` file that can be safely removed.

---

## ✅ Deprecated Variables - Safe to Delete

### Docker Python Image Variables
These are automatically set by the Python Docker image and should not be in your `.env` file:

```bash
PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LANG=C.UTF-8
GPG_KEY=
PYTHON_VERSION=3.11.14
PYTHON_SHA256=
PYTHONDONTWRITEBYTECODE=1
PYTHONUNBUFFERED=1
```

**Why:** These are inherited from the `python:3.11` base image and don't need to be explicitly set.

---

### Application Internal Variables

```bash
SKIP_DB_INIT=1
```

**Why:** This is an internal flag set automatically by migration scripts. It should not be in the user `.env` file.

```bash
EAS_OUTPUT_WEB_SUBDIR=eas_messages
```

**Why:** This variable is not used by `configure.py`. Only `EAS_OUTPUT_DIR` is used for output directory configuration.

---

## ⚠️ Empty Variables - Consider Removing

### Azure Speech (Legacy)
Since you're using `EAS_TTS_PROVIDER=azure_openai`, these legacy Azure Speech variables are not needed:

```bash
AZURE_SPEECH_REGION=
AZURE_SPEECH_KEY=
```

**Action:** Remove these unless you plan to switch back to the legacy Azure Speech service.

---

### Email Notification Settings
Since `ENABLE_EMAIL_NOTIFICATIONS=false`, these can be removed:

```bash
MAIL_PASSWORD=
MAIL_SERVER=
MAIL_USERNAME=
```

**Action:** Remove these or populate them if you plan to enable email notifications.

---

### LED Sign Settings
No LED sign IP is configured:

```bash
LED_SIGN_IP=
```

**Action:** Remove this or set it if you have an LED sign to configure.

---

### GPIO Settings
No GPIO pin is configured:

```bash
EAS_GPIO_PIN=
```

**Action:** Remove this or set it if you have GPIO relay hardware to configure.

---

## 📊 Statistics

- **Total variables in your .env:** 71
- **Docker image variables (deprecated):** 7
- **Application deprecated:** 2
- **Empty/unused:** 6
- **Variables to keep:** 56

---

## 🎯 Recommended Actions

### Step 1: Backup Your Current .env
```bash
cp .env .env.backup
```

### Step 2: Review the Cleaned Version
A cleaned `.env.recommended` file has been created for you with:
- All deprecated variables removed
- Comments explaining what was removed
- Your current values preserved

### Step 3: Use the New Environment Settings UI

Visit the **Environment Settings** page in your EAS Station web interface:

1. Go to **Settings → Environment Settings**
2. Review all configuration categories
3. Update values directly through the web UI
4. Changes will be saved to your `.env` file automatically

**Location:** `http://your-eas-station/settings/environment`

---

## 🆕 New Features

### Environment Settings Management UI

A comprehensive web-based environment settings manager has been added with:

- **11 configuration categories**
  - Core Settings
  - Database
  - Alert Polling
  - Location
  - EAS Broadcast
  - GPIO Control
  - Text-to-Speech
  - LED Display
  - VFD Display
  - Notifications
  - Performance
  - Docker/System

- **Features:**
  - Live editing of all environment variables
  - Validation and error checking
  - Sensitive value masking for passwords/keys
  - Change tracking (unsaved changes indicator)
  - Category-based organization
  - Built-in help text for each variable

- **API Endpoints:**
  - `GET /api/environment/categories` - List all categories
  - `GET /api/environment/variables` - Get all variables with values
  - `PUT /api/environment/variables` - Update variables
  - `GET /api/environment/validate` - Validate configuration

---

## 🔧 Configuration Best Practices

### Required Variables
Make sure these are always set:
- `SECRET_KEY` - Must be a long random string
- `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `NOAA_USER_AGENT` - Required for NOAA API compliance

### Security
- Never commit `.env` to version control
- Use strong passwords for `SECRET_KEY` and `POSTGRES_PASSWORD`
- Keep API keys like `AZURE_OPENAI_KEY` secure
- Generate a new `SECRET_KEY` with:
  ```bash
  python -c 'import secrets; print(secrets.token_hex(32))'
  ```

### Environment-Specific Settings
- Use `FLASK_ENV=production` in production
- Set `FLASK_DEBUG=false` in production
- Use `LOG_LEVEL=INFO` in production (DEBUG for troubleshooting)

---

## 📝 Migration Guide

### Before (71 variables with deprecated entries)
```bash
# Your current .env has many Docker image variables
PATH=/usr/local/bin:...
PYTHON_VERSION=3.11.14
SKIP_DB_INIT=1
# etc.
```

### After (56 variables, all actively used)
```bash
# Clean .env with only application variables
SECRET_KEY=your-secret-key
POSTGRES_HOST=host.docker.internal
EAS_BROADCAST_ENABLED=true
# etc.
```

---

## Need Help?

- **Documentation:** Visit Settings → Documentation in the web UI
- **Validation:** Use the `/api/environment/validate` endpoint
- **Web UI:** Settings → Environment Settings for visual editing

**Note:** After making changes to `.env`, restart the application for changes to take effect.
