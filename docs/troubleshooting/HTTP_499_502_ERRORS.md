# Troubleshooting HTTP 499 and 502 Errors

This guide helps diagnose and fix HTTP 499 and 502 errors that can appear in nginx logs when accessing EAS Station.

## Table of Contents

- [Understanding the Errors](#understanding-the-errors)
- [Quick Diagnosis](#quick-diagnosis)
- [Common Causes](#common-causes)
- [Solutions](#solutions)
- [Prevention](#prevention)

---

## Understanding the Errors

### HTTP 502 Bad Gateway

A **502 error** means nginx received an invalid response from the backend application (or couldn't connect at all).

Typical nginx log entry:
```
connect() failed (111: Connection refused) while connecting to upstream, 
client: 192.168.8.196, server: localhost, request: "GET / HTTP/2.0", 
upstream: "http://172.20.0.3:5000/"
```

**Root cause:** The Flask/Gunicorn application on port 5000 is not accepting connections.

### HTTP 499 Client Closed Request

A **499 error** is nginx-specific (not a standard HTTP status code). It means the client (browser) closed the connection before nginx could send a response.

Typical nginx log entry:
```
192.168.8.196 - - [26/Nov/2025:00:21:23 +0000] "GET / HTTP/2.0" 499 0 "-" "Mozilla/5.0 ..."
```

**Root cause:** The user got tired of waiting and closed their browser tab, navigated away, or hit refresh before the page loaded.

### The Connection Between 499 and 502

These errors often appear together in a predictable pattern:

1. User visits the site
2. nginx tries to connect to the backend app
3. Backend is down → nginx logs **502** error
4. User waits for page to load
5. User gives up and closes tab → nginx logs **499** error

**Key insight:** The **499 errors are a symptom, not the cause.** Focus on fixing the 502 errors first.

---

## Quick Diagnosis

### Step 1: Check Container Status

```bash
docker compose ps
```

Look for the `app` container. Is it running and healthy?

```
NAME                COMMAND                  SERVICE   STATUS                   PORTS
eas-station-app-1   "docker-entrypoint.s…"   app       Up 2 minutes (healthy)   5000/tcp
eas-station-nginx-1 "/docker-entrypoint.…"   nginx     Up 2 minutes             0.0.0.0:443->443/tcp
```

If the app shows `(unhealthy)` or is restarting, that's your problem.

### Step 2: Check App Logs

```bash
docker compose logs app --tail=100
```

Look for:
- Database connection errors
- Python exceptions
- Migration failures
- Missing dependencies

### Step 3: Test Health Endpoint Directly

```bash
docker compose exec app curl -s http://localhost:5000/health
```

If this fails, the app isn't running properly.

### Step 4: Check nginx Logs

```bash
docker compose logs nginx --tail=50 | grep -E "(502|499|connect.*failed)"
```

---

## Common Causes

### Cause 1: App Container Not Ready

**Symptom:** 502 errors immediately after startup, then 499s as users give up.

**Reason:** nginx started before the app finished initializing (database migrations, etc.).

**Solution:** The docker-compose files now include health checks that prevent nginx from starting until the app is ready.

### Cause 2: Database Connection Failed

**Symptom:** App container starts but immediately becomes unhealthy.

**Check:**
```bash
docker compose logs app | grep -i "database\|postgres\|connection"
```

**Solution:** Verify database settings in your `.env` file:
```bash
POSTGRES_HOST=alerts-db  # or your external database host
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-password
```

### Cause 3: Redis Not Ready

**Symptom:** App fails with Redis connection errors.

**Check:**
```bash
docker compose logs redis
docker compose exec redis redis-cli ping
```

Should return: `PONG`

### Cause 4: Resource Exhaustion

**Symptom:** App works initially, then becomes slow and eventually unresponsive.

**Check:**
```bash
docker stats --no-stream
```

Look for containers using 100% CPU or near memory limits.

### Cause 5: Long-Running Requests

**Symptom:** Some requests work, but audio processing or large uploads fail with 499.

**Reason:** Audio decoding can take 60-180 seconds. Users may cancel long requests.

**Solution:** The nginx configuration already has 300-second timeouts. Consider:
- Showing progress indicators in the UI
- Using async job processing for long operations

---

## Solutions

### Solution 1: Wait for Containers to Become Healthy

After running `docker compose up -d`, wait for all containers to be healthy:

```bash
# Watch container health status
watch -n 2 docker compose ps
```

nginx will only start accepting traffic once the app container passes its health checks.

### Solution 2: Restart Services

```bash
# Restart all services
docker compose restart

# Or restart specific services
docker compose restart app nginx
```

### Solution 3: Rebuild After Configuration Changes

```bash
docker compose down
docker compose up -d --build
```

### Solution 4: Check Network Connectivity

```bash
# Test DNS resolution inside nginx
docker compose exec nginx nslookup app

# Test HTTP connectivity
docker compose exec nginx curl -v http://app:5000/health
```

### Solution 5: Review Logs for Specific Errors

```bash
# All logs with error level
docker compose logs --tail=200 2>&1 | grep -i "error\|exception\|failed"

# App-specific errors
docker compose logs app --tail=200 | grep -i "error"
```

---

## Prevention

### Health Checks Are Now Enabled

The docker-compose files now include health checks for the app container:

```yaml
app:
  healthcheck:
    test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=5)"]
    interval: 10s
    timeout: 10s
    retries: 5
    start_period: 60s
```

nginx will wait for the app to be healthy before accepting traffic:

```yaml
nginx:
  depends_on:
    app:
      condition: service_healthy
```

This prevents 502 errors during startup.

### Monitor Container Health

Set up monitoring for container health:

```bash
# Check health status
docker compose ps --format "table {{.Name}}\t{{.Status}}"

# View health check logs
docker inspect --format='{{json .State.Health}}' eas-station-app-1 | jq
```

### Use the Diagnostics Page

EAS Station includes a built-in diagnostics page at `/diagnostics` that checks:
- Container health
- Database connectivity
- Redis status
- Configuration validity

---

## Related Documentation

- [FIX_IPV6_CONNECTIVITY.md](FIX_IPV6_CONNECTIVITY.md) - IPv6-related 499/502 errors
- [DATABASE_CONSISTENCY_FIXES.md](DATABASE_CONSISTENCY_FIXES.md) - Database issues
- [SETUP_INSTRUCTIONS.md](../guides/SETUP_INSTRUCTIONS.md) - Initial setup guide

---

**Last Updated:** 2025-11-26
