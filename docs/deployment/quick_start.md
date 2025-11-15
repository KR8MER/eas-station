# Quick Start Deployment Guide

**Purpose:** Get EAS Station running in under 15 minutes for lab evaluation and testing.

**Audience:** First-time users, system evaluators, developers

**Last Updated:** 2025-11-15

---

## Prerequisites

Before starting, ensure you have:

- **Hardware:**
  - Raspberry Pi 5 (8GB recommended) or x86 Linux system
  - 50GB+ storage (SSD strongly recommended)
  - Network connection
  - Optional: USB audio interface, SDR receiver (RTL-SDR or Airspy)

- **Software:**
  - Docker Engine 24+ with Compose V2
  - Git (for cloning repository)
  - Basic command-line familiarity

## Quick Installation (5 minutes)

### Step 1: Clone and Configure

```bash
# Clone the repository
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# Copy example environment file
cp .env.example .env

# Edit configuration with your location (optional but recommended)
nano .env
```

**Minimum required settings** in `.env`:
```bash
# Location Settings (improve alert relevancy)
DEFAULT_COUNTY_NAME=Your County
DEFAULT_STATE_CODE=OH  # Your state abbreviation
DEFAULT_ZONE_CODES=OHZ001  # Your NOAA zone code(s)

# Security (generate random key in production)
SECRET_KEY=your-random-secret-key-here

# Database password
POSTGRES_PASSWORD=change-me-in-production
```

### Step 2: Start Services

```bash
# Start all services
sudo docker compose up -d --build

# Wait for services to initialize (30-60 seconds)
sleep 45

# Check service status
sudo docker compose ps
```

All services should show "running" or "Up" status.

### Step 3: Access Web Interface

Open your browser to:
- **HTTP:** http://localhost (redirects to HTTPS)
- **HTTPS:** https://localhost

**First-time HTTPS access:**
1. Browser will show security warning (self-signed certificate)
2. Click "Advanced" → "Proceed to localhost" (safe for testing)
3. For production, configure `DOMAIN_NAME` in `.env` for Let's Encrypt

### Step 4: Complete Setup Wizard

1. **Initial login** uses default credentials (change immediately):
   - Username: `admin`
   - Password: `changeme`

2. **Setup wizard** will guide you through:
   - Location configuration
   - Audio settings
   - Alert source preferences
   - Radio receiver setup (if hardware connected)

3. **Change default password** immediately in Settings → Security

## Verification Checklist

After installation, verify these items:

- [ ] Web interface loads at https://localhost
- [ ] Dashboard shows system status
- [ ] Database connection is healthy (check `/health/dependencies`)
- [ ] Alert sources are polling (check Dashboard → Alert Sources)
- [ ] No critical errors in logs: `sudo docker compose logs --tail=50`

## Common Deployment Scenarios

### Scenario 1: Lab/Testing System (No Hardware)

**Goal:** Evaluate software features without specialized hardware

**Configuration:**
```bash
# In .env file
EAS_BROADCAST_ENABLED=false
AUDIO_OUTPUT_ENABLED=false
SDR_ENABLED=false
```

**Use Cases:**
- Alert monitoring and display
- Web interface evaluation
- Database and API testing
- Documentation review

### Scenario 2: Audio Monitoring (USB Sound Card)

**Goal:** Monitor and play EAS audio alerts

**Hardware:** USB audio interface or Raspberry Pi HAT

**Configuration:**
```bash
# In .env file
EAS_BROADCAST_ENABLED=true
AUDIO_OUTPUT_ENABLED=true
AUDIO_OUTPUT_DEVICE=plughw:1,0  # Adjust for your device
```

**Setup Steps:**
1. Connect USB audio device
2. Find device: `docker compose exec app aplay -l`
3. Update `AUDIO_OUTPUT_DEVICE` in `.env`
4. Restart: `docker compose restart app`

### Scenario 3: Full SDR Monitoring

**Goal:** Complete alert monitoring with radio verification

**Hardware:** RTL-SDR Blog V3/V4 or Airspy Mini

**Configuration:**
```bash
# In .env file
EAS_BROADCAST_ENABLED=true
SDR_ENABLED=true
SDR_DEVICE_TYPE=rtlsdr  # or 'airspy'
```

**Setup Steps:**
1. Connect SDR to USB
2. Pass USB to container (see [SDR Setup Guide](../SDR_SETUP))
3. Configure receivers in Settings → Radio
4. Monitor status on Dashboard

### Scenario 4: Production Broadcaster

**Goal:** FCC-compliant alert relay station

**Configuration:**
```bash
# In .env file
DOMAIN_NAME=eas.example.com
EAS_BROADCAST_ENABLED=true
EAS_ORIGINATOR=WXYZ  # Your station callsign
EAS_STATION_ID=WXYZ
AUDIO_OUTPUT_ENABLED=true
SDR_ENABLED=true
```

**Additional Requirements:**
- SSL certificate (Let's Encrypt automatic)
- GPIO relay control (see [GPIO Guide](../hardware/gpio))
- Regular backups (see [Backup Strategy](../runbooks/backup_strategy))
- Compliance monitoring (see [Help Guide](../guides/HELP))

## Troubleshooting Quick Fixes

### Services won't start

```bash
# Check Docker status
sudo systemctl status docker

# Verify Docker Compose version
docker compose version

# Check for port conflicts
sudo netstat -tulpn | grep -E ':(80|443|5432|8000)'

# View detailed logs
sudo docker compose logs
```

### Database connection failed

```bash
# Ensure database is running
sudo docker compose ps alerts-db

# Check database logs
sudo docker compose logs alerts-db

# Verify credentials in .env match docker-compose.yml
grep POSTGRES docker-compose.yml .env
```

### Web interface not loading

```bash
# Check nginx logs
sudo docker compose logs nginx

# Verify app is running
sudo docker compose ps app

# Check app logs for errors
sudo docker compose logs app --tail=100
```

### No alerts appearing

```bash
# Verify alert poller is running
sudo docker compose logs alert-poller

# Check zone codes are correct
docker compose exec app python -c "from app_utils import get_env; print(get_env('DEFAULT_ZONE_CODES'))"

# Test NOAA API connectivity
curl -I https://api.weather.gov
```

## Next Steps

After successful installation:

1. **Configure Location**
   - Settings → Location → Update zone codes
   - See [Zone Code Finder](https://www.weather.gov/gis/ZoneCounty)

2. **Review Settings**
   - Settings → General → Verify all options
   - Settings → Audio → Configure outputs
   - Settings → Radio → Add receivers

3. **Enable Features**
   - Settings → Features → Enable desired modules
   - Admin → Compliance → Set up monitoring
   - Admin → Backup → Configure automated backups

4. **Read Documentation**
   - [User Guide](../guides/HELP) - Daily operations
   - [Admin Guide](../guides/PORTAINER_DEPLOYMENT) - Advanced deployment
   - [Post-Install Guide](post_install.md) - Validation procedures

5. **Test Alert Flow**
   - Wait for next NOAA test (typically weekly)
   - Or create manual test alert
   - Verify audio playback
   - Check GPIO relay operation (if configured)

## Production Deployment Considerations

⚠️ **Before using in production:**

1. **Security Hardening**
   - Generate strong `SECRET_KEY`
   - Change all default passwords
   - Enable MFA (Settings → Security)
   - Configure firewall rules
   - Review [Security Guide](../SECURITY)

2. **Backup Strategy**
   - Configure automated backups
   - Test restore procedures
   - Set up off-site storage
   - See [Backup Strategy](../runbooks/backup_strategy)

3. **Monitoring**
   - Set up health check monitoring
   - Configure alert notifications
   - Enable audit logging
   - See [System Health](../../app_core/system_health.py)

4. **Hardware Reliability**
   - UPS for power protection
   - Redundant network connections
   - External SSD for database
   - Cooling solution for Raspberry Pi
   - See [Reference Pi Build](../hardware/reference_pi_build)

5. **Compliance**
   - Review FCC Part 11 requirements
   - Configure Required Weekly Tests
   - Set up compliance logging
   - Document operational procedures
   - See [Compliance Dashboard](../../templates/eas/compliance.html)

## Resources

- **Documentation Index:** [docs/INDEX.md](../INDEX)
- **Troubleshooting:** [scripts/diagnostics/README.md](../../scripts/diagnostics/README)
- **GitHub Issues:** https://github.com/KR8MER/eas-station/issues
- **GitHub Discussions:** https://github.com/KR8MER/eas-station/discussions

## Support

Need help? Try these resources:

1. Run diagnostic script: `bash scripts/diagnostics/troubleshoot_connection.sh`
2. Check health endpoint: `curl https://localhost/health/dependencies`
3. Review logs: `sudo docker compose logs --tail=100`
4. Search [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
5. Post in [GitHub Discussions](https://github.com/KR8MER/eas-station/discussions)

---

**Legal Notice:** EAS Station is experimental software for research and testing only. It is not FCC-certified and must not be used for production emergency alerting. See [Terms of Use](../policies/TERMS_OF_USE) for details.
