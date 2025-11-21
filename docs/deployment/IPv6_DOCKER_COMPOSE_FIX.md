# Docker Compose IPv6 Configuration Fix

**Date:** 2025-11-21
**Issue:** IPv6 connectivity not working for easstation.com
**Root Cause:** Incorrect docker-compose.yml IPv6 configuration

---

## The Problem

The original `docker-compose.yml` had two IPv6 configuration issues:

### Issue 1: Redundant Port Bindings

**Original Configuration:**
```yaml
ports:
  - "0.0.0.0:80:80"   # IPv4
  - "[::]:80:80"      # IPv6
  - "0.0.0.0:443:443" # IPv4
  - "[::]:443:443"    # IPv6
```

**Problem:** This attempts to bind the same host ports (80, 443) twice - once for IPv4 and once for IPv6. While this syntax might work in some cases, it's:
- Redundant (Docker handles both automatically when IPv6 is enabled)
- Potentially conflicting
- Not the recommended approach per Docker documentation

**Docker Documentation Says:**
> "Port binding automatically works for both IPv6 and IPv4. Using `docker run --rm -p 80:80 traefik/whoami` publishes port 80 on both IPv6 and IPv4."

### Issue 2: No IPv6-Enabled Network

The docker-compose.yml was using the default bridge network without any IPv6 configuration. For Docker containers to have IPv6 connectivity, you need EITHER:

1. Docker daemon configured with IPv6 enabled globally in `/etc/docker/daemon.json`, OR
2. A custom Docker network with `enable_ipv6: true` defined in the compose file

The file had neither.

---

## The Solution

### 1. Simplified Port Bindings

**New Configuration:**
```yaml
ports:
  - "80:80"    # Binds to both IPv4 and IPv6 automatically
  - "443:443"  # Binds to both IPv4 and IPv6 automatically
```

When Docker has IPv6 enabled (either globally or on a network), simple port mappings like `"80:80"` automatically bind to both IPv4 and IPv6.

### 2. Added IPv6-Enabled Network

**New Network Configuration:**
```yaml
networks:
  eas-network:
    enable_ipv6: true
    driver: bridge
    ipam:
      driver: default
      config:
        - subnet: 172.20.0.0/16      # IPv4 subnet
          gateway: 172.20.0.1
        - subnet: fd00:eas:station::/64  # IPv6 subnet (ULA)
          gateway: fd00:eas:station::1
```

This creates a custom bridge network with:
- **IPv6 enabled** (`enable_ipv6: true`)
- **IPv4 subnet**: 172.20.0.0/16 for internal container communication
- **IPv6 subnet**: fd00:eas:station::/64 (Unique Local Address for internal use)

### 3. Connected All Services to the Network

All services now include:
```yaml
networks:
  - eas-network
```

This ensures all containers can communicate with each other and have IPv6 support.

---

## How IPv6 Works Now

### Internal IPv6 (Container-to-Container)

Containers now have IPv6 addresses in the `fd00:eas:station::/64` subnet and can communicate with each other over IPv6:
- `nginx` → `app` (reverse proxy communication)
- `app` → `alerts-db` (database queries)
- All pollers → `app` (service communication)

### External IPv6 (Host-to-Internet)

For the server to be reachable from the internet over IPv6, you STILL need:

1. **IPv6 enabled on the host server**
   ```bash
   sysctl net.ipv6.conf.all.disable_ipv6=0
   ```

2. **IPv6 address assigned to the server interface**
   ```bash
   ip -6 addr show  # Should show: 2001:19f0:5c00:2aeb:5400:5ff:febe:5432
   ```

3. **Docker daemon with IPv6 forwarding** (add to `/etc/docker/daemon.json`):
   ```json
   {
     "ipv6": true,
     "fixed-cidr-v6": "fd00::/80",
     "experimental": true,
     "ip6tables": true
   }
   ```

4. **Firewall allowing IPv6 traffic**
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   ```

---

## Changes Made

### Files Modified:

1. **docker-compose.yml**
   - Simplified nginx port bindings from 4 entries to 2
   - Added `networks: - eas-network` to all services
   - Added custom `eas-network` with IPv6 enabled
   - Changed `alerts-db` network from `default` to `eas-network`

2. **docker-compose.embedded-db.yml**
   - Simplified nginx port bindings from 4 entries to 2
   - (Note: This file should also have network configuration added in future update)

3. **docs/troubleshooting/FIX_IPV6_CONNECTIVITY.md**
   - Created comprehensive IPv6 troubleshooting guide

4. **docs/deployment/IPv6_DOCKER_COMPOSE_FIX.md** (this file)
   - Documents the configuration changes

---

## Deployment Instructions

### For New Deployments:

Simply use the updated docker-compose.yml:
```bash
docker-compose up -d
```

The IPv6-enabled network will be created automatically.

### For Existing Deployments:

1. **Pull the updated configuration:**
   ```bash
   git pull origin main
   ```

2. **Recreate the containers with the new network:**
   ```bash
   docker-compose down
   docker-compose up -d
   ```

   This will:
   - Remove the old containers
   - Create the new `eas-network` with IPv6
   - Recreate all containers connected to the new network

3. **Verify IPv6 is working:**
   ```bash
   # Check if containers have IPv6 addresses
   docker network inspect eas-station_eas-network | grep IPv6

   # Test from inside a container
   docker-compose exec app curl -6 https://ipv6.google.com
   ```

### Server-Side Configuration (Required for Internet IPv6):

Even with the docker-compose.yml fixes, you must configure the host server. Follow the guide in `docs/troubleshooting/FIX_IPV6_CONNECTIVITY.md`.

---

## Why This Fix Works

### Before:
```
Internet (IPv6) → Server → ??? → Docker (no IPv6) → nginx (IPv6 bindings fail)
                                                       ↓
                                                    Connection Timeout
```

### After:
```
Internet (IPv6) → Server (IPv6 enabled) → Docker (IPv6 forwarding) → eas-network (IPv6)
                                                                         ↓
                                                                      nginx (bound to ::)
                                                                         ↓
                                                                      Your application
```

With the network properly configured, Docker can forward IPv6 traffic from the host to the containers.

---

## Testing

### Test Internal IPv6:

```bash
# Get nginx container IPv6 address
docker inspect eas-station-nginx-1 | grep IPv6Address

# Test from another container
docker-compose exec app curl -6 http://[ipv6-address-from-above]/
```

### Test External IPv6:

From a machine with IPv6 connectivity:
```bash
# Test DNS
dig easstation.com AAAA +short

# Test HTTP connection
curl -6 -I https://easstation.com/

# Test with explicit IPv6 address
curl -6 -I https://[2001:19f0:5c00:2aeb:5400:5ff:febe:5432]/
```

### Verify with SSL Labs:

https://www.ssllabs.com/ssltest/analyze.html?d=easstation.com

Should now show results for both IPv4 and IPv6.

---

## Troubleshooting

### Issue: Containers don't have IPv6 addresses

**Solution:** Docker daemon may not have IPv6 enabled. Add to `/etc/docker/daemon.json`:
```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00::/80"
}
```
Then restart Docker: `sudo systemctl restart docker`

### Issue: IPv6 works internally but not from internet

**Solution:** Host server configuration issue. See `docs/troubleshooting/FIX_IPV6_CONNECTIVITY.md`.

### Issue: "Error creating network: invalid IPAM config"

**Solution:** The IPv6 subnet may conflict with existing networks. Change the subnet:
```yaml
- subnet: fd00:eas:other::/64  # Change "station" to something else
```

---

## References

- [Docker IPv6 Documentation](https://docs.docker.com/engine/daemon/ipv6/)
- [Docker Compose Networks](https://docs.docker.com/compose/networking/)
- [RFC 4193: Unique Local IPv6 Addresses](https://datatracker.ietf.org/doc/html/rfc4193)

---

## Version History

- **v1.0** (2025-11-21): Initial fix for IPv6 connectivity issue
  - Simplified port bindings
  - Added IPv6-enabled custom network
  - Connected all services to new network

---

**Next Steps:**

1. Deploy these changes to your server
2. Configure Docker daemon for IPv6 (see troubleshooting guide)
3. Verify external IPv6 connectivity
4. Test with SSL Labs
