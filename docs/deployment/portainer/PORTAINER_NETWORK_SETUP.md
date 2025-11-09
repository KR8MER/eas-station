# Portainer Network Configuration Guide

## Quick Setup: Use Portainer's Network

To make EAS Station accessible via external IP on Vultr (or any cloud provider), you can connect it to Portainer's network.

### Option 1: Use Portainer's Default Bridge Network

In Portainer, when creating/updating your stack, add these environment variables:

```ini
DOCKER_NETWORK=bridge
DOCKER_NETWORK_EXTERNAL=false
```

This uses Docker's default bridge network (same as Portainer typically uses).

### Option 2: Use a Custom Shared Network

#### Step 1: Find Portainer's Network Name

1. In Portainer, go to **Networks**
2. Look for the network Portainer is using (usually `bridge` or `portainer_default`)
3. Note the exact network name

#### Step 2: Configure Stack to Use That Network

In Portainer stack environment variables, add:

```ini
DOCKER_NETWORK=portainer_default
DOCKER_NETWORK_EXTERNAL=true
```

Replace `portainer_default` with the actual network name from Step 1.

### Option 3: Create a New Shared Network

#### Step 1: Create Network in Portainer

1. Go to **Networks** → **Add network**
2. **Name:** `shared-network` (or your preferred name)
3. **Driver:** `bridge`
4. **IPv4 Subnet:** `172.20.0.0/16` (or leave default)
5. Click **Create the network**

#### Step 2: Connect Portainer to This Network (Optional)

1. Go to **Containers**
2. Find your Portainer container
3. Click on it → **Duplicate/Edit**
4. Add the network under **Network** section
5. Restart Portainer

#### Step 3: Configure EAS Station Stack

In Portainer stack environment variables:

```ini
DOCKER_NETWORK=shared-network
DOCKER_NETWORK_EXTERNAL=true
```

---

## Vultr-Specific Troubleshooting

### Check Firewall Rules

#### Vultr Firewall (Cloud-Level)

1. Log into Vultr dashboard
2. Go to **Firewall** section
3. Check if port 80 (HTTP) is allowed:
   - **Protocol:** TCP
   - **Port:** 80
   - **Source:** 0.0.0.0/0 (or your specific IPs)
4. Add rule if missing

#### Server Firewall (UFW on Ubuntu/Debian)

```bash
# Check if UFW is active
sudo ufw status

# If active, allow port 80
sudo ufw allow 80/tcp

# Reload
sudo ufw reload
```

#### Server Firewall (firewalld on CentOS/RHEL)

```bash
# Check status
sudo firewall-cmd --state

# If active, allow HTTP
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

### Check if Port is Actually Listening

```bash
# Check if something is listening on port 80
sudo netstat -tlnp | grep :80

# Or using ss
sudo ss -tlnp | grep :80
```

Expected output should show Docker proxy or the container.

### Test Port Binding

```bash
# From inside the Vultr server
curl http://localhost:80

# Should return the EAS Station HTML or API response
```

If this works but external IP doesn't, it's a firewall issue.

---

## Common Network Issues & Solutions

### Issue: Port 80 Already in Use

**Error:** "port is already allocated"

**Solutions:**

1. **Find what's using port 80:**
   ```bash
   sudo lsof -i :80
   ```

2. **Common culprits:**
   - Apache: `sudo systemctl stop apache2`
   - Nginx: `sudo systemctl stop nginx`
   - Another container: Check Portainer containers

3. **Alternative:** Use a different port like 8080:
   ```ini
   # In environment variables, override the port
   # Or edit the compose file ports to "8080:5000"
   ```

### Issue: Can't Reach External IP

**Symptoms:** Works on localhost, but not from external IP

**Checklist:**

1. ✅ Port 80 open in Vultr firewall
2. ✅ Port 80 open in server firewall (UFW/firewalld)
3. ✅ Container is running: `docker ps | grep eas-station`
4. ✅ Port binding is correct: `0.0.0.0:80` not `127.0.0.1:80`
5. ✅ No NAT/routing issues on Vultr network

**Test external access:**
```bash
# From your local machine
curl http://YOUR_VULTR_IP

# Or
telnet YOUR_VULTR_IP 80
```

### Issue: Container Starts Then Stops

**Symptoms:** Container exits immediately after starting

**Check logs in Portainer:**
1. **Containers** → Select `eas-station_app`
2. Click **Logs**
3. Look for error messages

**Common causes:**
- Missing SECRET_KEY environment variable
- Database connection failed
- Port already in use inside container

### Issue: Works in One Stack, Not Another

**Cause:** Network isolation between stacks

**Solution:** Both stacks need to be on the same network (see options above)

---

## Verification Checklist

After configuration, verify everything works:

### 1. Check Container Status
```bash
docker ps | grep eas-station
```
All containers should show "Up" status.

### 2. Check Network Connectivity
```bash
# List networks
docker network ls

# Inspect the network your stack is using
docker network inspect bridge
# or
docker network inspect portainer_default
```

Your EAS Station containers should appear in the network's container list.

### 3. Check Port Binding
```bash
docker ps --format "table {{.Names}}\t{{.Ports}}"
```
Should show: `0.0.0.0:80->5000/tcp`

### 4. Test Local Access
```bash
curl http://localhost:80
```

### 5. Test External Access
From another machine:
```bash
curl http://YOUR_VULTR_IP
```

---

## Example: Complete Portainer Configuration

When creating the stack in Portainer:

**Repository URL:** `https://github.com/KR8MER/eas-station`
**Compose path:** `docker-compose.embedded-db.yml`
**Environment variables:**

```ini
# Core Settings
SECRET_KEY=your-generated-secret-key-here

# Database (for embedded DB)
POSTGRES_HOST=alerts-db
POSTGRES_DB=alerts
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-secure-password

# Network Configuration - CHOOSE ONE:

# Option A: Default bridge (usually works)
DOCKER_NETWORK=bridge
DOCKER_NETWORK_EXTERNAL=false

# Option B: Custom shared network (if you created one)
# DOCKER_NETWORK=shared-network
# DOCKER_NETWORK_EXTERNAL=true

# Option C: Portainer's network (if you found the name)
# DOCKER_NETWORK=portainer_default
# DOCKER_NETWORK_EXTERNAL=true

# Location
DEFAULT_COUNTY_NAME=Your County
DEFAULT_STATE_CODE=OH
DEFAULT_TIMEZONE=America/New_York
```

---

## Still Having Issues?

### Enable Debug Logging

Add to environment variables:
```ini
FLASK_DEBUG=true
LOG_LEVEL=DEBUG
```

### Check Docker Logs Directly

```bash
# Via Portainer Console
docker logs eas-station_app

# Or on the server
docker logs -f eas-station_app
```

### Network Diagnostics from Inside Container

1. In Portainer: **Containers** → `eas-station_app` → **Console**
2. Select `/bin/bash` → **Connect**
3. Run diagnostics:
   ```bash
   # Check network interfaces
   ip addr show

   # Check if app is listening
   netstat -tlnp

   # Test outbound connectivity
   ping -c 3 8.8.8.8

   # Check DNS
   nslookup google.com
   ```

---

## Summary

**For most Vultr deployments:**

1. Use default bridge network (add `DOCKER_NETWORK=bridge` and `DOCKER_NETWORK_EXTERNAL=false`)
2. Open port 80 in Vultr firewall
3. Check server firewall (UFW/firewalld)
4. Verify port binding shows `0.0.0.0:80`

This should resolve 95% of network accessibility issues.
