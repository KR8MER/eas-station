# Fixing IPv6 Connectivity Issues

This guide helps troubleshoot and fix IPv6 connectivity problems that can affect SSL Labs testing and external IPv6 access to EAS Station.

## Table of Contents

- [Overview](#overview)
- [Common Symptoms](#common-symptoms)
- [Root Cause Analysis](#root-cause-analysis)
- [Diagnostic Steps](#diagnostic-steps)
- [Solutions](#solutions)
- [Verification](#verification)

---

## Overview

EAS Station uses Docker Compose with an IPv6-enabled network (`fd00:ea:1::/64`). While this enables modern dual-stack networking, it can cause issues when:

1. **SSL Labs cannot reach your IPv6 site** - The AAAA DNS record points to an IPv6 address, but the server isn't responding on that address
2. **nginx fails to connect to the backend** - Docker DNS returns IPv6 addresses that the Flask backend doesn't bind to
3. **Intermittent connection failures** - nginx tries IPv6 first, fails, then retries on IPv4

---

## Common Symptoms

### Symptom 1: SSL Labs IPv6 Test Fails

SSL Labs reports "Unable to connect to the server" for IPv6 but IPv4 works fine.

**Cause:** Your DNS has an AAAA record, but nginx isn't properly publishing on IPv6, OR external IPv6 traffic isn't reaching Docker.

### Symptom 2: nginx Upstream Connection Refused

```
connect() failed (111: Connection refused) while connecting to upstream, 
upstream: "http://[fd00:ea:1::3]:5000/"
```

**Cause:** nginx resolved the backend hostname to an IPv6 address, but the Flask/Gunicorn app only binds to IPv4 (`0.0.0.0:5000`).

### Symptom 3: Intermittent 499/502 Errors

Requests randomly fail with 499 (client closed connection) or 502 (bad gateway).

**Cause:** nginx tries the IPv6 address first, times out, and the client gives up before the IPv4 fallback succeeds.

> **Note:** If you're seeing 499/502 errors that are NOT IPv6-related (e.g., after startup or when the app container is unhealthy), see [HTTP_499_502_ERRORS.md](HTTP_499_502_ERRORS.md) for general troubleshooting.

---

## Root Cause Analysis

### The Technical Issue

Docker Compose creates an IPv6-enabled network with both IPv4 and IPv6 subnets:

```yaml
networks:
  eas-network:
    enable_ipv6: true
    ipam:
      config:
        - subnet: 172.20.0.0/16      # IPv4
        - subnet: fd00:ea:1::/64     # IPv6
```

When nginx resolves `app:5000` using Docker's embedded DNS (127.0.0.11), it gets **both** IPv4 and IPv6 addresses. The `resolver 127.0.0.11 ipv6=off;` directive only affects runtime variable resolution—**not** statically configured `upstream` blocks.

Since Gunicorn binds to `0.0.0.0:5000` (IPv4 only), connections to the IPv6 address fail with "Connection refused."

### The Fix (Already Applied)

The nginx configuration uses variable-based `proxy_pass` directives that force runtime DNS resolution, which **does** respect the `ipv6=off` setting:

```nginx
# Force IPv4-only resolution for backend connections
resolver 127.0.0.11 ipv6=off valid=30s;

map $host $backend_server {
    default "app:5000";
}

location / {
    set $backend http://$backend_server;
    proxy_pass $backend;  # Resolved at runtime, respects ipv6=off
}
```

---

## Diagnostic Steps

### Step 1: Run the IPv6 Diagnostics Script

```bash
./debug-ipv6-server.sh
```

This script checks:
- IPv6 system status
- IPv6 addresses on interfaces
- IPv6 routes
- Docker IPv6 configuration
- Firewall rules
- Listening ports

### Step 2: Check nginx Logs for IPv6 Errors

```bash
docker compose logs nginx | grep -i "connect() failed"
```

Look for errors mentioning IPv6 addresses like `[fd00:ea:1::X]`.

### Step 3: Verify Backend Binding

```bash
docker compose exec app netstat -tlnp | grep 5000
```

Should show:
```
tcp    0    0 0.0.0.0:5000    0.0.0.0:*    LISTEN
```

If it shows `:::5000`, the backend is listening on IPv6 (good). If only `0.0.0.0:5000`, it's IPv4 only.

### Step 4: Test DNS Resolution Inside nginx

```bash
docker compose exec nginx nslookup app
```

Check if it returns both IPv4 and IPv6 addresses.

---

## Solutions

### Solution 1: Use Variable-Based Proxy Pass (Recommended)

This is already implemented in the current nginx.conf. The configuration uses:

```nginx
resolver 127.0.0.11 ipv6=off valid=30s;

map $host $backend_server {
    default "app:5000";
}

location / {
    set $backend http://$backend_server;
    proxy_pass $backend;
}
```

**Why it works:** Using a variable in `proxy_pass` forces nginx to resolve the hostname at request time using the configured resolver, which has `ipv6=off`.

### Solution 2: Disable IPv6 on the Docker Network

If you don't need IPv6 at all, disable it in docker-compose.yml:

```yaml
networks:
  eas-network:
    enable_ipv6: false  # Changed from true
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
        # Remove IPv6 subnet
```

**Pros:** Simplest solution
**Cons:** Breaks IPv6 connectivity for external clients

### Solution 3: Make Gunicorn Listen on IPv6

Modify the Dockerfile CMD to bind to both IPv4 and IPv6:

```dockerfile
CMD ["sh", "-c", "gunicorn --bind [::]:5000 --workers ${MAX_WORKERS:-2} ..."]
```

**Note:** Binding to `[::]` on Linux typically also accepts IPv4 connections (dual-stack).

**Pros:** Full IPv6 support internally
**Cons:** May require additional testing

### Solution 4: Fix External IPv6 Connectivity

If SSL Labs can't reach your IPv6 address:

1. **Verify your server has a public IPv6 address:**
   ```bash
   ip -6 addr show scope global
   ```

2. **Check IPv6 routing:**
   ```bash
   ip -6 route show default
   ```

3. **Verify firewall allows IPv6 traffic:**
   ```bash
   sudo ip6tables -L INPUT -n | grep -E "(80|443)"
   ```

4. **Test from an external IPv6 host:**
   ```bash
   curl -6 -v https://yourdomain.com/
   ```

5. **Ensure Docker publishes ports on IPv6:**
   The docker-compose.yml should have ports that bind to both protocols:
   ```yaml
   ports:
     - "80:80"    # Binds to both IPv4 and IPv6 by default
     - "443:443"
   ```

---

## Verification

### Test 1: Internal Backend Connectivity

```bash
docker compose exec nginx curl -v http://app:5000/health
```

Should connect without IPv6 errors.

### Test 2: External IPv4 Access

```bash
curl -4 -v https://yourdomain.com/health
```

### Test 3: External IPv6 Access

```bash
curl -6 -v https://yourdomain.com/health
```

### Test 4: SSL Labs

Visit https://www.ssllabs.com/ssltest/ and test your domain. Both IPv4 and IPv6 should pass.

---

## Related Documentation

- [HTTPS_SETUP.md](../guides/HTTPS_SETUP.md) - SSL certificate configuration
- [debug-ipv6-server.sh](../../debug-ipv6-server.sh) - IPv6 diagnostics script

---

**Last Updated:** 2025-11-26
