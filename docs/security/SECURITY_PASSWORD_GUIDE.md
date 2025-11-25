# Security & Password Management Guide

## Overview

EAS Station uses a **single source of truth** for all passwords and credentials: the persistent `.env` file located at `/app-config/.env` inside the containers.

## Architecture

### Single Source of Truth: `/app-config/.env`

Both the application and Icecast containers read from this shared configuration file:

```
┌─────────────────────┐
│  Persistent Volume  │
│   /app-config       │
│                     │
│   ┌─────────────┐   │
│   │   .env      │◄──┼──── Single source of truth
│   └─────────────┘   │
└─────────────────────┘
          ▲      ▲
          │      │
    ┌─────┘      └─────┐
    │                  │
┌───▼─────┐      ┌────▼────┐
│   App   │      │ Icecast │
│Container│      │Container│
└─────────┘      └─────────┘
```

### How It Works

1. **Initial Deployment**: Docker-compose provides default passwords via environment variables
2. **First Run**: These defaults are written to `/app-config/.env` by the app
3. **Subsequent Runs**: Both containers read from `/app-config/.env` (overriding docker-compose defaults)
4. **Password Changes**: Made via the web UI, automatically sync to both containers on next restart

## Changing Passwords Securely

### Method 1: Web UI (Recommended)

1. **Log in** to your EAS Station web interface
2. Navigate to **Settings → Environment Variables**
3. Find the password you want to change:
   - `ICECAST_ADMIN_PASSWORD` - Admin access to Icecast
   - `ICECAST_SOURCE_PASSWORD` - Stream publishing password
   - `SECRET_KEY` - Flask session encryption key
   - `POSTGRES_PASSWORD` - Database password (if using embedded DB)
4. **Enter new password** (see password requirements below)
5. Click **Save**
6. **Restart containers** in Portainer:
   - Go to your stack
   - Click "Stop"
   - Click "Start"

The Icecast container will now load the new password from `/app-config/.env` on startup.

### Method 2: Direct File Edit (Advanced)

If you need to edit the file directly:

```bash
# Access the app container
docker exec -it <container-name> sh

# Edit the persistent .env file
vi /app-config/.env

# Find and update passwords
ICECAST_ADMIN_PASSWORD=your_new_secure_password
ICECAST_SOURCE_PASSWORD=another_secure_password

# Save and exit
# Then restart both containers from Portainer
```

## Password Requirements

### CRITICAL: Icecast Passwords MUST Be ASCII-Only

**Icecast only supports ASCII characters in passwords.** Do NOT use:
- ❌ Emoji (🔒, ✓, etc.)
- ❌ Unicode bullets (••)
- ❌ Non-Latin characters (中文, العربية, etc.)
- ❌ Smart quotes ("" instead of "")

**Valid characters:**
- ✅ Letters: `a-z`, `A-Z`
- ✅ Numbers: `0-9`
- ✅ Symbols: `!@#$%^&*()-_=+[]{}|;:,.<>?/~`

### Recommended Password Strength

For production deployments:

1. **Minimum 16 characters**
2. **Mix of uppercase, lowercase, numbers, and symbols**
3. **Unique for each service** (don't reuse passwords)
4. **Not dictionary words**

Example strong passwords:
```
ICECAST_ADMIN_PASSWORD=X9$mK2#pR5!qL7@nW3
ICECAST_SOURCE_PASSWORD=P4!vT8#zQ2$dN6&jM9
SECRET_KEY=a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456
```

## Default Passwords (CHANGE THESE!)

The system ships with these defaults - **change them immediately after deployment**:

| Variable | Default Value | Purpose |
|----------|---------------|---------|
| `ICECAST_ADMIN_PASSWORD` | `changeme_admin` | Icecast admin interface |
| `ICECAST_SOURCE_PASSWORD` | `eas_station_source_password` | Audio stream publishing |
| `SECRET_KEY` | *(empty)* | Flask session encryption |
| `POSTGRES_PASSWORD` | `postgres` | Database access |

## Security Best Practices

### 1. Change All Default Passwords Immediately

After first deployment:
1. Go to Settings → Environment Variables
2. Change ALL default passwords
3. Restart containers

### 2. Use Strong, Unique Passwords

- Generate passwords using a password manager
- Never reuse passwords between services
- Use maximum length passwords where possible

### 3. Restrict Admin Access

- Set `ICECAST_ADMIN_USER` and `ICECAST_ADMIN_PASSWORD` only if you need metadata updates
- If you don't need live metadata updates, leave these unset to disable admin API access

### 4. Backup Your Configuration

The `/app-config` volume contains all your passwords. **Back it up securely:**

```bash
# Create encrypted backup
docker run --rm -v eas-station_app-config:/data \
  -v $(pwd):/backup alpine tar czf /backup/app-config-backup.tar.gz /data

# Encrypt the backup
gpg --symmetric --cipher-algo AES256 app-config-backup.tar.gz
```

### 5. Regular Password Rotation

For production systems, rotate passwords periodically:
- **Critical systems**: Every 90 days
- **Normal systems**: Every 180 days
- **After any security incident**: Immediately

## Troubleshooting

### "401 Unauthorized" Errors

If you see continuous 401 errors in logs:

1. **Check password format**: Is it ASCII-only? No Unicode characters?
2. **Verify sync**: Did you restart containers after changing the password?
3. **Check logs**: Look for "Loading Icecast configuration from persistent .env file" in Icecast container logs
4. **Verify file**: Check `/app-config/.env` contains the correct password

### Containers Using Different Passwords

This should not happen with the new architecture, but if it does:

1. **Stop all containers**
2. **Delete** the old `.env` file:
   ```bash
   docker run --rm -v eas-station_app-config:/data alpine rm /data/.env
   ```
3. **Restart stack** - it will regenerate with defaults
4. **Change passwords** via web UI
5. **Restart again** to sync

### Password Contains Unicode

If you accidentally set a Unicode password:

```
ERROR: 'latin-1' codec can't encode characters
```

**Solution:**
1. Go to Settings → Environment Variables
2. Change to ASCII-only password
3. Restart containers

## Migration from Old Setup

If you're upgrading from a version that didn't use shared config:

### Before Upgrade

1. Note your current Icecast password from Portainer environment variables
2. Note your current app password from Settings → Environment

### After Upgrade

1. Deploy new version
2. Go to Settings → Environment Variables
3. Verify both passwords match
4. If they don't match, change to a new ASCII password
5. Restart containers

## Security Incident Response

If you suspect a password has been compromised:

1. **Immediately** change the password via Settings → Environment Variables
2. **Restart** all containers
3. **Review** access logs in `/var/log/icecast2/` (access.log)
4. **Check** for unauthorized stream connections
5. **Rotate** all other passwords as a precaution

## Questions?

- Security issues: Report privately to project maintainers
- General questions: Open a GitHub discussion
- Documentation improvements: Submit a pull request

---

**Remember**: Security is a process, not a one-time setup. Regularly review and update your passwords, especially for internet-facing deployments.
