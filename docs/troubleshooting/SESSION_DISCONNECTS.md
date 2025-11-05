# Session Disconnection Troubleshooting Guide

## Overview

Session disconnections in the EAS Station web interface can be caused by several factors. This document explains the common causes and how to resolve them.

## Common Causes

### 1. Session Timeout (Most Common)

**Configuration Location:** `app.py:184-187`

The application uses a configurable session lifetime:

```python
session_hours = int(os.environ.get('SESSION_LIFETIME_HOURS', '12'))
app.permanent_session_lifetime = timedelta(hours=session_hours)
```

**Default Behavior:**
- Sessions expire after **12 hours** of inactivity by default
- Can be configured via `SESSION_LIFETIME_HOURS` environment variable

**Solution:**
Edit your `.env` file to increase session lifetime:

```env
# Increase session lifetime to 24 hours (or any value you prefer)
SESSION_LIFETIME_HOURS=24

# For longer sessions (48 hours)
SESSION_LIFETIME_HOURS=48
```

**Trade-offs:**
- ✅ Longer sessions = fewer login prompts
- ⚠️ Longer sessions = potential security risk if device is left unattended
- 💡 Recommended: Keep at 12-24 hours for operator workstations

### 2. Browser Cookie Issues

**Symptoms:**
- Disconnects immediately after login
- Works in one browser but not another
- Works in incognito/private mode

**Causes:**
- Browser cookie blocking
- Third-party cookie restrictions
- Browser extensions interfering

**Solution:**
1. Clear browser cookies for the EAS Station domain
2. Disable cookie-blocking extensions temporarily
3. Check browser privacy settings
4. Try a different browser

### 3. Network Connectivity Issues

**Symptoms:**
- Random disconnects
- "Connection lost" messages
- Long page load times

**Causes:**
- Unstable network connection
- WiFi signal issues
- VPN/proxy problems
- Firewall interference

**Solution:**
1. Switch to wired Ethernet connection
2. Check network stability with ping tests
3. Verify firewall rules allow persistent connections
4. Disable VPN if not required for access

### 4. Docker Container Restarts

**Symptoms:**
- All users disconnected simultaneously
- Occurs after system updates or high load

**Causes:**
- Docker container restart (sessions are in-memory)
- System resource exhaustion
- Manual container restart

**Solution:**

Check container uptime:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Check container logs for restarts:
```bash
docker logs eas-station-app --tail 100
```

**Long-term Solution:**
Consider implementing Redis-based session storage for persistence across restarts. This would require:
- Adding Redis container to `docker-compose.yml`
- Installing Flask-Session extension
- Configuring session storage backend

### 5. CSRF Token Expiration

**Symptoms:**
- "Your session has expired" message
- Kicked out after form submission

**Configuration Location:** `app.py:238, 270-273`

**Causes:**
- CSRF token mismatch (usually from stale browser tabs)
- Multiple tabs with different session states

**Solution:**
- Close duplicate tabs
- Refresh the page and log in again
- Clear browser cache

### 6. Session Cookie Security Settings

**Configuration Location:** `app.py:159-182`

**Settings:**
```python
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = <varies by deployment>
SESSION_COOKIE_SAMESITE = 'Lax'
```

**Issue:**
If `SESSION_COOKIE_SECURE=true` is set but you're accessing via HTTP (not HTTPS), sessions won't persist.

**Solution:**
For local development/testing over HTTP:
```env
SESSION_COOKIE_SECURE=false
```

For production over HTTPS (recommended):
```env
SESSION_COOKIE_SECURE=true
```

## Diagnostic Steps

### Step 1: Check Current Session Lifetime

```bash
# Check if SESSION_LIFETIME_HOURS is set
grep SESSION_LIFETIME_HOURS .env

# If not set, default is 12 hours
```

### Step 2: Monitor Session Behavior

Open browser developer tools (F12) and check:
1. **Application/Storage tab** → Cookies
2. Look for session cookie
3. Note the "Expires" timestamp
4. Check if "Secure" and "HttpOnly" flags match your deployment

### Step 3: Check Docker Container Health

```bash
# Check container uptime
docker ps

# Check for restart events
docker logs eas-station-app | grep -i "restart\|shutdown\|started"

# Check resource usage
docker stats eas-station-app --no-stream
```

### Step 4: Review Application Logs

```bash
# Check for session-related errors
docker logs eas-station-app | grep -i "session\|csrf"

# Check for database connection issues
docker logs eas-station-app | grep -i "database\|connection"
```

## Recommended Configuration

### For 24/7 Operations Centers

```env
# .env configuration for operator workstations
SESSION_LIFETIME_HOURS=24
SESSION_COOKIE_SECURE=true  # If using HTTPS
```

### For Personal/Development Use

```env
# .env configuration for testing/development
SESSION_LIFETIME_HOURS=48
SESSION_COOKIE_SECURE=false  # If using HTTP locally
```

### For High-Security Environments

```env
# .env configuration for strict security
SESSION_LIFETIME_HOURS=4
SESSION_COOKIE_SECURE=true
```

## Implementing Persistent Sessions with Redis (Advanced)

For production deployments where session persistence across container restarts is critical:

### 1. Add Redis to docker-compose.yml

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: eas-station-redis
    restart: unless-stopped
    volumes:
      - redis-data:/data
    networks:
      - eas-network

volumes:
  redis-data:
```

### 2. Install Flask-Session

Add to `requirements.txt`:
```
Flask-Session==0.5.0
redis==4.5.5
```

### 3. Configure Session Storage

Add to `app.py`:
```python
from flask_session import Session
import redis

# Configure session storage
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'))
app.config['SESSION_PERMANENT'] = True
Session(app)
```

### 4. Add to .env

```env
REDIS_URL=redis://redis:6379/0
```

## Monitoring Session Health

Add these endpoints to monitor session behavior (proposed feature):

```
GET /api/session/info - Returns current session details
GET /api/session/health - Returns session storage health
```

## Summary

**Most Common Issue:** Sessions timing out after 12 hours (default)

**Quick Fix:** Add `SESSION_LIFETIME_HOURS=24` to `.env` file

**Best Practice:**
- Use HTTPS with `SESSION_COOKIE_SECURE=true` in production
- Implement Redis-backed sessions for critical deployments
- Monitor session lifetime vs. typical operator shift length
- Balance security (shorter sessions) with usability (longer sessions)

## Related Files

- `app.py:159-187` - Session configuration
- `app.py:638-648` - User session loading
- `app.py:658-674` - CSRF validation
- `.env` - Environment configuration

## Support

For persistent disconnection issues not resolved by this guide:
1. Check GitHub issues: https://github.com/KR8MER/eas-station/issues
2. Review Docker logs for errors
3. Verify network connectivity
4. Consider implementing Redis-backed sessions
