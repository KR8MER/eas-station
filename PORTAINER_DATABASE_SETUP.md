# Database Setup and Security Guide for Portainer

## Overview

This guide shows you how to configure secure database credentials when deploying EAS Station in Portainer with the embedded PostgreSQL database.

---

## ⚠️ Important Security Warning

**Default credentials are NOT SECURE for production!**

The default configuration uses:
- Username: `postgres`
- Password: `postgres`

**You MUST change the password before deploying to production.**

---

## Quick Setup (Minimal Security)

### Step 1: Generate a SECRET_KEY

On any computer with Python:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Example output: `9d821419d2b70c5a5572cd8e73f1e1d0f7ac4b65b6ac77684c517106c8079498`

### Step 2: Choose a Database Password

Create a strong password (at least 16 characters, mix of letters, numbers, symbols).

Example tools:
```bash
# On Linux/Mac
openssl rand -base64 24

# Or use a password manager (recommended)
```

### Step 3: Configure in Portainer

When creating your stack in Portainer:

1. Go to **Environment variables** section
2. Click **Advanced mode** (easier)
3. Add these variables:

```ini
# REQUIRED: Application security key
SECRET_KEY=your-generated-secret-key-from-step-1

# REQUIRED: Secure database password
POSTGRES_PASSWORD=your-strong-password-from-step-2

# OPTIONAL: Your location details
DEFAULT_COUNTY_NAME=Your County
DEFAULT_STATE_CODE=OH
DEFAULT_TIMEZONE=America/New_York
```

4. Click **Deploy the stack**

**That's it!** The database will automatically:
- Create user: `postgres`
- Create database: `alerts`
- Use your secure password
- All services will connect properly

---

## Advanced Setup (Custom Username and Database Name)

If you want to customize the database name or username:

### In Portainer Environment Variables:

```ini
# Application security
SECRET_KEY=your-generated-secret-key

# Custom database configuration
POSTGRES_DB=my_custom_db_name
POSTGRES_USER=my_custom_user
POSTGRES_PASSWORD=my-strong-password

# Location
DEFAULT_COUNTY_NAME=Your County
DEFAULT_STATE_CODE=OH
```

**Important:** All three services (app, poller, ipaws-poller) will automatically use these same credentials because they're defined in the compose file.

---

## How the Database Configuration Works

### The Compose File Sets Everything Up Automatically

In `docker-compose.embedded-db.yml`, all services share the same environment variables:

```yaml
services:
  app:
    environment:
      POSTGRES_HOST: ${POSTGRES_HOST:-alerts-db}
      POSTGRES_PORT: ${POSTGRES_PORT:-5432}
      POSTGRES_DB: ${POSTGRES_DB:-alerts}
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}

  poller:
    environment:
      # Same variables...

  ipaws-poller:
    environment:
      # Same variables...

  alerts-db:
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-alerts}
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
```

**What this means:**
- Set `POSTGRES_PASSWORD` once in Portainer
- All services automatically use it
- Database creates the user with that password
- App services connect with that same password
- Everything stays in sync!

---

## Changing Credentials After Deployment

### Option 1: Fresh Start (Recommended)

If you need to change credentials and can afford to lose existing data:

1. In Portainer, go to **Stacks**
2. Select your stack → **Stop**
3. Go to **Volumes**
4. Delete the `eas-station_alerts-db-data` volume
5. Go back to **Stacks** → Edit your stack
6. Update environment variables with new credentials:
   ```ini
   POSTGRES_PASSWORD=new-secure-password
   ```
7. **Update the stack**

The database will be recreated with new credentials.

### Option 2: Migrate Existing Data

If you need to preserve data:

#### Step 1: Backup Existing Database

1. In Portainer: **Containers** → `eas-station-app-1` → **Console**
2. Select `/bin/bash` → **Connect**
3. Run backup:
   ```bash
   pg_dump -h alerts-db -U postgres -d alerts > /tmp/backup.sql
   ```
4. Download the backup:
   - **Containers** → `eas-station-app-1`
   - **Copy from container**
   - Path: `/tmp/backup.sql`
   - Save to your computer

#### Step 2: Change Password

1. **Containers** → `eas-station-alerts-db-1` → **Console**
2. Connect with `/bin/bash`
3. Change password:
   ```bash
   psql -U postgres -d alerts -c "ALTER USER postgres WITH PASSWORD 'new-secure-password';"
   ```

#### Step 3: Update Stack Environment Variables

1. **Stacks** → Your stack → **Editor**
2. Update environment variables:
   ```ini
   POSTGRES_PASSWORD=new-secure-password
   ```
3. **Update the stack** (this will restart services with new credentials)

#### Step 4: Verify Connection

Check logs:
```bash
docker logs eas-station-app-1 --tail 20
```

Should see: `INFO:app:Database connection successful`

---

## Security Best Practices

### ✅ Do:

1. **Generate strong passwords:**
   - Minimum 16 characters
   - Mix of letters (upper/lower), numbers, symbols
   - Use a password manager or generator

2. **Generate unique SECRET_KEY:**
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

3. **Keep credentials secure:**
   - Don't commit to Git
   - Don't share in screenshots
   - Store in a password manager

4. **Regular backups:**
   - Use the in-app backup tool: Admin → System Operations → Run Backup
   - Or manual: `pg_dump` command above

5. **Update regularly:**
   - Keep EAS Station updated
   - Keep PostgreSQL image updated
   - Monitor security advisories

### ❌ Don't:

1. **Don't use default passwords in production**
   - `postgres` / `postgres` is NOT secure
   - Always change before going live

2. **Don't reuse passwords**
   - Use unique password for database
   - Different from your Portainer password
   - Different from your server SSH password

3. **Don't expose database port externally**
   - The compose file doesn't expose port 5432 externally (good!)
   - Keep it that way unless you have a specific need

4. **Don't share credentials**
   - Use Portainer's user management instead
   - Create separate accounts for team members

---

## Troubleshooting

### Issue: "Database connection failed"

**Check:**
1. Container logs: `docker logs eas-station-app-1`
2. Is database running? `docker ps | grep alerts-db`
3. Are credentials matching in all services?

**Fix:**
Make sure `POSTGRES_PASSWORD` is set identically for:
- The `alerts-db` service (creates the password)
- All application services (connect with that password)

### Issue: "Authentication failed for user"

**Cause:** Password mismatch between database and application.

**Fix:**
1. Check what password the database was created with
2. Make sure environment variables match:
   ```ini
   POSTGRES_PASSWORD=same-password-everywhere
   ```
3. Restart stack

### Issue: Lost database password

**Fix:**
1. Backup data (if possible)
2. Delete volume: `eas-station_alerts-db-data`
3. Redeploy with new password
4. Restore backup (if you have one)

---

## Example: Complete Portainer Configuration

### For Production Deployment:

```ini
# === REQUIRED SECURITY SETTINGS ===
SECRET_KEY=9d821419d2b70c5a5572cd8e73f1e1d0f7ac4b65b6ac77684c517106c8079498
POSTGRES_PASSWORD=MyS3cur3P@ssw0rd!2024

# === DATABASE CONFIGURATION (optional customization) ===
# POSTGRES_DB=alerts
# POSTGRES_USER=postgres

# === LOCATION SETTINGS ===
DEFAULT_COUNTY_NAME=Hamilton County
DEFAULT_STATE_CODE=OH
DEFAULT_TIMEZONE=America/New_York
DEFAULT_ZONE_CODES=OHZ077,OHC061

# === APPLICATION SETTINGS ===
FLASK_ENV=production
FLASK_DEBUG=false
LOG_LEVEL=INFO

# === EAS BROADCAST (if using hardware) ===
# EAS_BROADCAST_ENABLED=true
# EAS_ORIGINATOR=WXR
# EAS_STATION_ID=WXALERT
```

---

## FAQ

### Q: Do I need to set POSTGRES_HOST?

**A:** No! With `docker-compose.embedded-db.yml`, it defaults to `alerts-db` automatically. Only change it if you know what you're doing.

### Q: Can I use special characters in the password?

**A:** Yes, but be careful with quotes. In Portainer's advanced mode (plain text), don't wrap the password in quotes:

```ini
# Correct:
POSTGRES_PASSWORD=My$ecure!P@ssw0rd

# Incorrect:
POSTGRES_PASSWORD="My$ecure!P@ssw0rd"
```

### Q: What happens to existing data if I change the password?

**A:** If you change `POSTGRES_PASSWORD` and restart:
- The existing database keeps its old password
- App services try to connect with the new password
- Connection fails!

You must either:
- Reset database (delete volume)
- Or change password inside database first (see "Option 2: Migrate Existing Data")

### Q: Can I use an external database instead?

**A:** Yes! Use `docker-compose.yml` instead and set:
```ini
POSTGRES_HOST=your-database-server.example.com
POSTGRES_PASSWORD=your-external-db-password
```

---

## Quick Reference

### Minimum Required Variables:
```ini
SECRET_KEY=<generate-with-python>
POSTGRES_PASSWORD=<strong-password>
```

### Recommended Variables:
```ini
SECRET_KEY=<generate-with-python>
POSTGRES_PASSWORD=<strong-password>
DEFAULT_COUNTY_NAME=<your-county>
DEFAULT_STATE_CODE=<your-state>
DEFAULT_TIMEZONE=<your-timezone>
```

### Generate SECRET_KEY:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Generate Strong Password:
```bash
openssl rand -base64 24
```

---

**Remember:** Change default passwords before production deployment! 🔐

*Last updated: 2025-01-06*
