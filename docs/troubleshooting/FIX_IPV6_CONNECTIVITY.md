# Fix IPv6 Connectivity for easstation.com

**Issue:** SSLLabs and other external services cannot connect to easstation.com over IPv6, even though:
- The AAAA DNS record exists (2001:19f0:5c00:2aeb:5400:5ff:febe:5432)
- nginx is configured to listen on IPv6
- Docker Compose is publishing ports on IPv6

**Root Cause:** The issue is at the server/infrastructure level, not in the application configuration.

---

## Diagnosis Steps

Run these commands on your Vultr server to identify the issue:

### 1. Check if IPv6 is enabled on the server

```bash
# Check if IPv6 is enabled
sysctl net.ipv6.conf.all.disable_ipv6
# Should return: net.ipv6.conf.all.disable_ipv6 = 0 (0 = enabled)

# List IPv6 addresses assigned to interfaces
ip -6 addr show

# Check if your IPv6 address is assigned
ip -6 addr show | grep 2001:19f0:5c00:2aeb:5400:5ff:febe:5432
```

**Expected:** You should see your IPv6 address (2001:19f0:5c00:2aeb:5400:5ff:febe:5432) assigned to an interface (usually eth0 or ens3).

**If not present:** Your Vultr server doesn't have IPv6 enabled or the address isn't assigned.

### 2. Check Docker IPv6 configuration

```bash
# Check Docker daemon configuration
cat /etc/docker/daemon.json

# Check if Docker containers have IPv6
docker network inspect bridge | grep -i ipv6

# Check what IP addresses nginx container is listening on
docker ps -q | xargs docker inspect --format='{{.Name}}: {{range .NetworkSettings.Networks}}{{.IPAddress}} {{.GlobalIPv6Address}}{{end}}'
```

**Expected:** Docker daemon should have IPv6 enabled, and containers should have IPv6 addresses.

### 3. Check firewall rules

```bash
# Check UFW status
sudo ufw status verbose

# Check if UFW is blocking IPv6
sudo ufw show raw | grep -i v6

# Check ip6tables rules
sudo ip6tables -L -n -v

# Specifically check port 443 for IPv6
sudo ip6tables -L INPUT -n -v | grep 443
```

### 4. Test IPv6 connectivity from the server

```bash
# Ping an IPv6 host from your server
ping6 -c 4 2001:4860:4860::8888  # Google DNS

# Test if you can reach the internet over IPv6
curl -6 https://ipv6.google.com

# Check your server's public IPv6 address
curl -6 https://api64.ipify.org
```

---

## Fix #1: Enable IPv6 on Vultr Server

If IPv6 is not enabled or the address is not assigned:

### Step 1: Enable IPv6 in Vultr dashboard

1. Log into [Vultr dashboard](https://my.vultr.com)
2. Go to your server
3. Click **Settings** → **IPv6**
4. Click **Enable IPv6** (if not already enabled)
5. Note the assigned IPv6 address

### Step 2: Configure IPv6 on Ubuntu

Edit the network configuration:

```bash
# For Ubuntu 22.04+ using netplan
sudo nano /etc/netplan/01-netcfg.yaml
```

Add IPv6 configuration:

```yaml
network:
  version: 2
  ethernets:
    ens3:  # Your interface name - check with 'ip link'
      dhcp4: true
      dhcp6: true
      accept-ra: true
```

Apply the configuration:

```bash
sudo netplan apply

# Verify IPv6 is assigned
ip -6 addr show
```

### Step 3: Ensure IPv6 is not disabled

```bash
# Check current setting
sysctl net.ipv6.conf.all.disable_ipv6

# If it returns 1, enable IPv6:
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0
sudo sysctl -w net.ipv6.conf.default.disable_ipv6=0

# Make it persistent
echo "net.ipv6.conf.all.disable_ipv6 = 0" | sudo tee -a /etc/sysctl.conf
echo "net.ipv6.conf.default.disable_ipv6 = 0" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

---

## Fix #2: Configure Docker for IPv6

Docker requires explicit IPv6 configuration.

### Step 1: Create or edit Docker daemon configuration

```bash
sudo nano /etc/docker/daemon.json
```

Add IPv6 configuration:

```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00::/80",
  "experimental": true,
  "ip6tables": true
}
```

**Note:** If you already have content in daemon.json, merge the settings.

### Step 2: Restart Docker

```bash
sudo systemctl restart docker

# Verify Docker has IPv6 enabled
docker network inspect bridge | grep -i ipv6
```

### Step 3: Recreate containers

After enabling IPv6 in Docker, you need to recreate the containers:

```bash
cd /opt/eas-station  # Or wherever your deployment is

# Stop and remove containers
docker-compose down

# Recreate with IPv6 support
docker-compose up -d

# Verify containers have IPv6 addresses
docker ps -q | xargs docker inspect --format='{{.Name}}: IPv6={{.NetworkSettings.Networks.bridge.GlobalIPv6Address}}'
```

---

## Fix #3: Configure Firewall for IPv6

If you're using UFW (Ubuntu Firewall):

### Step 1: Enable IPv6 in UFW

```bash
sudo nano /etc/default/ufw
```

Ensure this line is present:
```
IPV6=yes
```

### Step 2: Allow HTTP and HTTPS on IPv6

```bash
# Allow ports 80 and 443 for both IPv4 and IPv6
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Reload firewall
sudo ufw reload

# Check status
sudo ufw status verbose
```

### Step 3: Verify ip6tables rules

```bash
# List all IPv6 rules
sudo ip6tables -L -n -v

# Check if ports 80 and 443 are allowed
sudo ip6tables -L INPUT -n -v | grep -E '(80|443)'
```

If ports are blocked, manually allow them:

```bash
sudo ip6tables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo ip6tables -A INPUT -p tcp --dport 443 -j ACCEPT

# Save rules (Ubuntu)
sudo netfilter-persistent save
```

---

## Verification

After applying fixes, verify IPv6 connectivity:

### 1. Test from the server itself

```bash
# Test local IPv6 connectivity
curl -6 -I https://[2001:19f0:5c00:2aeb:5400:5ff:febe:5432]/

# Should return HTTP 301 or 200
```

### 2. Test from an external IPv6 host

From a machine with IPv6 connectivity (not your server):

```bash
# Test DNS resolution
dig easstation.com AAAA +short

# Test HTTP connection
curl -6 -I https://easstation.com/

# Test with explicit IPv6 address
curl -6 -I https://[2001:19f0:5c00:2aeb:5400:5ff:febe:5432]/
```

### 3. Test with online tools

- **SSL Labs:** https://www.ssllabs.com/ssltest/analyze.html?d=easstation.com
- **IPv6 Test:** https://ipv6-test.com/validate.php?url=easstation.com
- **DNS Checker:** https://dnschecker.org/#AAAA/easstation.com

---

## Debugging if Still Not Working

### Check nginx logs

```bash
# Check nginx error logs
docker-compose logs nginx | grep -i error

# Check if nginx is actually listening on IPv6
docker-compose exec nginx netstat -tlnp | grep -E ':(80|443)'
# Should show :::80 and :::443 (IPv6)
```

### Check application logs

```bash
# Check for any IPv6-related errors
docker-compose logs | grep -i ipv6

# Check nginx access logs
docker-compose exec nginx tail -f /var/log/nginx/access.log
```

### Test with netcat from external host

From another machine with IPv6:

```bash
# Test if port 443 is reachable
nc -6 -zv easstation.com 443

# Test if port 80 is reachable
nc -6 -zv easstation.com 80
```

### Packet capture

On the server, capture IPv6 traffic to see if packets are arriving:

```bash
# Capture IPv6 traffic on port 443
sudo tcpdump -i any -n 'ip6 and port 443'

# Then try connecting from external IPv6 host
```

---

## Common Issues and Solutions

### Issue: "Cannot assign requested address" in Docker logs

**Solution:** Docker IPv6 configuration is incorrect. Verify `/etc/docker/daemon.json` has `"ipv6": true` and restart Docker.

### Issue: nginx shows ":::80" but still not reachable

**Solution:** Firewall is likely blocking IPv6. Check UFW and ip6tables rules.

### Issue: IPv6 works from server but not externally

**Solution:** Vultr firewall or security group may be blocking IPv6. Check Vultr dashboard → Server → Firewall.

### Issue: AAAA record resolves but connection times out

**Solution:** The IPv6 address is not actually assigned to the server interface. Check `ip -6 addr show`.

---

## Quick Fix Script

If you want to automate the fixes, here's a script:

```bash
#!/bin/bash
# fix-ipv6.sh - Automated IPv6 fixes for EAS Station

set -e

echo "=== Fixing IPv6 Connectivity ==="

# 1. Enable IPv6 system-wide
echo "1. Enabling IPv6 system-wide..."
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=0
sudo sysctl -w net.ipv6.conf.default.disable_ipv6=0
echo "net.ipv6.conf.all.disable_ipv6 = 0" | sudo tee -a /etc/sysctl.conf
echo "net.ipv6.conf.default.disable_ipv6 = 0" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# 2. Configure Docker for IPv6
echo "2. Configuring Docker for IPv6..."
if [ ! -f /etc/docker/daemon.json ]; then
    echo '{"ipv6": true, "fixed-cidr-v6": "fd00::/80", "experimental": true, "ip6tables": true}' | sudo tee /etc/docker/daemon.json
else
    echo "WARNING: /etc/docker/daemon.json exists. Please manually add IPv6 configuration."
fi

sudo systemctl restart docker

# 3. Configure UFW for IPv6
echo "3. Configuring UFW for IPv6..."
sudo sed -i 's/IPV6=no/IPV6=yes/' /etc/default/ufw
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload

# 4. Recreate containers
echo "4. Recreating containers with IPv6 support..."
docker-compose down
docker-compose up -d

echo "=== IPv6 Fixes Applied ==="
echo ""
echo "Verification steps:"
echo "1. Check IPv6 address: ip -6 addr show"
echo "2. Test externally: curl -6 -I https://easstation.com/"
echo "3. Run SSLLabs test: https://www.ssllabs.com/ssltest/analyze.html?d=easstation.com"
```

Make it executable and run:

```bash
chmod +x fix-ipv6.sh
./fix-ipv6.sh
```

---

## Next Steps

After fixing IPv6 connectivity:

1. **Verify SSLLabs can connect:**
   - Go to https://www.ssllabs.com/ssltest/
   - Enter: easstation.com
   - Should show grades for both IPv4 and IPv6

2. **Monitor for issues:**
   - Check `/system/health` endpoint
   - Review nginx logs for IPv6 connections
   - Monitor with uptime services

3. **Update documentation:**
   - Document your IPv6 configuration
   - Note any Vultr-specific settings

---

## Support

If you're still experiencing issues after following this guide:

1. Share the output of the diagnostic commands
2. Check Vultr support documentation
3. Open a GitHub issue with diagnostics

**Document Version:** 1.0
**Created:** 2025-11-21
**Last Updated:** 2025-11-21
