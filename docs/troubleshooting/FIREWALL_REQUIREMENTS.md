# Firewall Port Requirements

## Overview

EAS Station™ uses several network ports for its services. This document lists all ports that may need to be opened in your firewall for proper operation.

**Note for Bare-Metal Installations**: As of version 2.19.7, the `install.sh` script **automatically configures UFW firewall** during installation. Ports 22 (SSH), 80 (HTTP), and 443 (HTTPS) are opened automatically. See [Automatic Firewall Configuration](#automatic-firewall-configuration-bare-metal) below.

## Required Ports (External Access)

These ports need to be accessible from outside the host for normal operation:

| Port | Protocol | Service | Description |
|------|----------|---------|-------------|
| **443** | TCP | HTTPS (nginx) | Web interface (primary access). Uses SSL/TLS encryption. **Auto-configured in bare-metal install.** |
| **80** | TCP | HTTP (nginx) | Redirects to HTTPS. Also needed for Let's Encrypt certificate renewal. **Auto-configured in bare-metal install.** |
| **22** | TCP | SSH | Remote server access for management. **Auto-configured in bare-metal install.** |
| **8000** | TCP | Icecast | Audio streaming server for public stream access. Icecast listens on `ICECAST_PORT` (default **8000**); `ICECAST_EXTERNAL_PORT` controls the port advertised in stream URLs and should stay equal to it unless a reverse proxy exposes Icecast on a different public port. **Opened from the web UI** — Settings → Firewall — not a manual `ufw` command; see below. |

## Router Port Forwarding (Home / Lab Networks)

The sections above cover the **host's own firewall** (UFW, firewalld, iptables) and cloud
provider security groups. If the server instead sits behind a home or lab router doing NAT —
the common case for a bare-metal install on a residential connection — that router has its
own, separate gate: it drops all unsolicited inbound traffic by default, and the host firewall
being open does nothing until the router is told to forward the port to this machine's LAN IP.
Both layers must allow a port before it is reachable from the internet.

**Before forwarding anything**, give the host a static LAN IP or a DHCP reservation in the
router — a forwarding rule that points at a DHCP-leased address breaks the next time the lease
renews to a different address, and open the matching *host*-firewall rule first from
**Settings → Firewall** — the baseline (22/80/443), LAN NTP server, and Icecast port rules are
all managed from that one page rather than a manual `ufw` command. A router forward only
reaches this host at all once the host's own firewall lets the traffic through.

| Port | Protocol | Forward when... | Notes |
|------|----------|------------------|-------|
| **443** | TCP | You want the web UI reachable from outside the LAN. | Required for any remote (non-VPN) access at all. |
| **80** | TCP | You use a real domain name with automatic Let's Encrypt renewal. | The ACME HTTP-01 challenge is inbound on port 80 from Let's Encrypt's servers. Not needed if you access the UI by IP with a self-signed/manual cert, or renew certs another way. |
| **8000** | TCP | You want Icecast audio streams reachable outside the LAN. | Optional — only forward this if remote listeners need the streams directly. |

**Do not forward anything else.** In particular, never forward:
- **22 (SSH)** — unless you specifically intend to administer the box from outside the LAN, and even then prefer a VPN (see [Tailscale Setup](../guides/TAILSCALE_SETUP.md)) or an SSH bastion over a bare forward, and disable password auth (key-only) first.
- **5000, 5002, 5101–5106** — internal service ports, several trusting a shared-secret header (`X-Hardware-Auth`) rather than real authentication; see the internal-ports table above.
- **5432 (PostgreSQL) / 6379 (Redis)** — no authentication hardening intended for internet exposure.

**Steps (router UI varies by vendor — look for "Port Forwarding," "NAT," or "Virtual Server")**:
1. Assign the EAS Station™ host a static LAN IP or DHCP reservation.
2. Create a forwarding rule for each port above you actually need: external port → the host's LAN IP → same internal port, TCP.
3. If you don't own a domain, skip the port 80 rule and manage certificates manually (see [Setup Instructions](../guides/SETUP_INSTRUCTIONS.md)) or access the UI by IP.
4. Verify from **outside** your LAN — a phone on cellular data, not Wi-Fi — since ports can appear open from inside the LAN (via NAT hairpinning) even when the router hasn't forwarded them at all.

If you only need remote *administrative* access (not public streams or public web access), a
VPN — see [Tailscale Setup](../guides/TAILSCALE_SETUP.md) — avoids exposing any port to the
internet at all and is the safer default for a lab deployment.

These ports are used internally between services and should **not** be exposed to the internet:

| Port | Protocol | Service | Description |
|------|----------|---------|-------------|
| **5000** | TCP | Flask App | Web application backend (nginx proxies to this). |
| **5002** | TCP | SDR/Audio Service | Audio streaming server for internal audio processing. |
| **5101** | TCP | Network Subsystem | nmcli proxy + hostname helpers (Phase 4 split). Requires `X-Hardware-Auth` — see below. |
| **5102** | TCP | Zigbee Subsystem | zigpy-znp coordinator + join window. Requires `X-Hardware-Auth` — see below. |
| **5103** | TCP | GPS Subsystem | GPS manager + PPS trend archive. Requires `X-Hardware-Auth` — see below. |
| **5104** | TCP | Displays Subsystem | OLED / VFD / LED rendering. Requires `X-Hardware-Auth` — see below. |
| **5105** | TCP | GPIO Subsystem | Relays + alert indicators (health endpoint only). |
| **5106** | TCP | Demod Subsystem | FM/AM demodulation, split out of the audio service (health endpoint only — purely Redis-driven, same as GPIO). |
| **5432** | TCP | PostgreSQL | Database (embedded profile or external). |
| **6379** | TCP | Redis | In-memory cache for real-time updates. |
| **8000** | TCP | Icecast (listen port) | Icecast listen port — expose directly or front it with a proxy. |

**Hardware subsystem auth (ports 5101-5104)**: every route on these four
services except `/health` requires an `X-Hardware-Auth` header carrying a
token derived from `SECRET_KEY` (see
`app_core.config.get_hardware_service_token()` /
`services.common.bootstrap.install_service_auth()`). This is a second line
of defense in case one of these ports is ever reachable despite the
firewall rule above — it is **not** a substitute for keeping them off the
LAN. The three webapp modules that call these services (`webapp/admin/
network.py`, `webapp/admin/zigbee.py`, `webapp/routes_screens.py`) already
send this header automatically; no operator configuration is needed.

## Automatic Firewall Configuration (Bare-Metal)

**New in version 2.19.7**: The bare-metal installation script (`install.sh`) automatically configures UFW firewall during Step 11 of the installation process.

### What's Configured Automatically

The installer performs the following firewall configuration:

```bash
# Default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow required ports
sudo ufw allow 22/tcp   # SSH - prevents lockout
sudo ufw allow 80/tcp   # HTTP - for Let's Encrypt and redirects
sudo ufw allow 443/tcp  # HTTPS - web interface

# Enable firewall
sudo ufw enable
```

### Verify Firewall Status

After installation, verify the firewall is configured correctly:

```bash
sudo ufw status verbose
```

Expected output:
```
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
22/tcp (v6)               ALLOW IN    Anywhere (v6)
80/tcp (v6)               ALLOW IN    Anywhere (v6)
443/tcp (v6)              ALLOW IN    Anywhere (v6)
```

### Remote Access Enabled

With these firewall rules in place, you can access your EAS Station™ from any device on your network or the internet (if your router/cloud provider allows it):

- **From this server**: `https://localhost`
- **From local network**: `https://<server-ip-address>`
- **From internet**: `https://<your-domain.com>` (after DNS and router configuration)

## Firewall Configuration Examples

### UFW (Ubuntu/Debian)

**For bare-metal installs using `install.sh`**: Firewall is already configured automatically. Use these commands only if you need to modify the configuration.

#### Add Additional Ports

**Icecast**: on a standard bare-metal install, open this from **Settings → Firewall** in the web UI
instead of running `ufw` by hand — it also lets you scope the rule to specific subnets and keeps
it in sync if the configured Icecast port ever changes. The manual command below is for
non-standard deployments only:

```bash
# Allow Icecast streaming (for public audio streams) -- manual/non-standard deployments only
sudo ufw allow 8000/tcp

# Verify rules
sudo ufw status verbose
```

#### Manual UFW Setup (Non-Bare-Metal Deployments)

If you're not using the `install.sh` script, configure UFW manually:

```bash
# Set default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow required ports
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS

# Optional: Allow Icecast streaming
sudo ufw allow 8000/tcp

# Enable firewall
sudo ufw enable

# Verify rules
sudo ufw status verbose
```

### firewalld (RHEL/CentOS/Fedora)

```bash
# Allow HTTPS (web interface)
sudo firewall-cmd --permanent --add-port=443/tcp

# Allow HTTP redirect (port 80 → 443)
sudo firewall-cmd --permanent --add-service=http

# Allow Icecast streaming (optional, for public audio streams)
sudo firewall-cmd --permanent --add-port=8000/tcp

# Reload and verify
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports
```

### iptables (Manual)

```bash
# Allow HTTPS (web interface)
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# Allow HTTP redirect (port 80 → 443)
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT

# Allow Icecast streaming (optional, for public audio streams)
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT

# Save rules (varies by distribution)
sudo netfilter-persistent save  # Debian/Ubuntu
sudo service iptables save      # RHEL/CentOS
```

## Cloud Provider Firewalls

If running on a cloud provider (AWS, Azure, GCP, DigitalOcean, etc.), you also need to configure the security group or network security rules **in addition to** the UFW firewall on the host.

**Note**: Even if `install.sh` configured UFW on the host, cloud providers have their own firewall layer that must be configured separately.

### Minimum Required Rules

| Direction | Port | Protocol | Source | Description |
|-----------|------|----------|--------|-------------|
| Inbound | 443 | TCP | 0.0.0.0/0 | HTTPS web interface |
| Inbound | 80 | TCP | 0.0.0.0/0 | HTTP redirect to HTTPS and Let's Encrypt |
| Inbound | 22 | TCP | Your IP | SSH access (management) - **Restrict to your IP for security** |

### Optional Rules

| Direction | Port | Protocol | Source | Description |
|-----------|------|----------|--------|-------------|
| Inbound | 8000 | TCP | 0.0.0.0/0 | Icecast audio streaming (if public streams enabled) |

## Troubleshooting Connection Issues

### Symptom: "Connection refused" errors in nginx logs

```
connect() failed (111: Connection refused) while connecting to upstream
```

This error indicates nginx cannot connect to the Flask backend (port 5000). Common causes:

1. **Flask app not running** - Check if the web service is healthy:
   ```bash
   systemctl status eas-station-web
   sudo journalctl -u eas-station-web -n 50 --no-pager
   ```

2. **Database migration errors** - The app may fail to start due to database issues:
   ```bash
   sudo journalctl -u eas-station-web -n 200 --no-pager | grep -iE "alembic|migration|database"
   ```

   ```bash
   # Verify PostgreSQL is up and the database exists
   systemctl status postgresql
   sudo -u postgres psql -d alerts -c 'SELECT 1;'
   ```

### Symptom: Cannot access web interface externally

1. **Check firewall rules** - Ensure ports 443 and 80 are open
2. **Check cloud security groups** - Verify inbound rules allow traffic
3. **Test local connectivity first**:
   ```bash
   curl -k https://localhost
   curl http://localhost
   ```

### Symptom: Icecast streams not accessible

1. **Verify Icecast is running**:
   ```bash
   systemctl status icecast2
   ```

2. **Check the listen port**:
   ```bash
   sudo ss -tlnp | grep 8000
   ```

3. **Test local access**:
   ```bash
   curl http://localhost:8000/status-json.xsl
   ```

4. **Check the host firewall** — the most common cause on a fresh install: Icecast can be
   running perfectly and still be unreachable from other devices because the host firewall
   never had port 8000 opened. Go to **Settings → Firewall** and confirm the Icecast card shows
   at least one subnet under "Allowed subnets"; add one (your LAN's CIDR, e.g.
   `192.168.1.0/24`) and click Apply if it's empty.

## Related Documentation

- [Setup Instructions](../guides/SETUP_INSTRUCTIONS.md) - Initial deployment guide
