# EAS Station™ Bare Metal - Quick Start Guide

Get EAS Station™ running on bare metal in 15 minutes!

## Choose Your Installation Method

### 🚀 Fast: Interactive Install on Existing System

Already have Debian/Ubuntu/Raspberry Pi OS? Start here!

```bash
# 1. Clone and run interactive installer (takes 10-15 minutes)
git clone https://github.com/KR8MER/eas-station.git && \
cd eas-station && \
sudo bash install.sh

# The installer will guide you through:
# - Administrator account creation
# - System configuration (hostname, domain, callsign)
# - Location setup (timezone, state, county)
# - Alert sources (NOAA, IPAWS)
# - Audio/streaming settings
# - Hardware integration (GPIO, LED signs)

# 2. Access the web interface
# Open browser to https://localhost (accept self-signed cert)

# 3. Start monitoring alerts!
# All configuration is done during installation - no post-install setup needed!
```

**What's Interactive:** The installer uses a raspi-config style TUI (text user interface) to collect all configuration during installation:
- ✓ **All settings configured upfront** - no post-install wizard needed
- ✓ **Blue/gray dialog boxes** - familiar raspi-config interface
- ✓ **Input validation** - helpful error messages and defaults
- ✓ **Secure by default** - auto-generates passwords and keys
- ✓ **Optional reconfiguration** - use `sudo eas-config` anytime

### 💿 Clean: Bootable ISO Image

Want a dedicated system? Build an ISO!

```bash
# 1. Build ISO (takes 30-60 minutes)
cd eas-station/bare-metal
sudo bash scripts/build-iso.sh

# 2. Burn to USB
sudo dd if=eas-station-*.iso of=/dev/sdX bs=4M status=progress

# 3. Boot and follow setup wizard
```

## Post-Installation

### Accessing Your Station

After installation completes, your EAS Station™ is **fully configured and ready to use**!

1. **Navigate to** https://localhost (or your configured domain)
   - Accept the self-signed certificate warning (normal for self-signed certs)
   
2. **Log in** with the administrator account you created during installation

3. **Start monitoring!** Your station is already configured with:
   - ✓ Administrator account
   - ✓ System settings (hostname, domain, callsign)
   - ✓ Location (timezone, state, county)
   - ✓ Alert sources (NOAA, IPAWS as configured)
   - ✓ Hardware integration (as configured)

### Optional: Additional Configuration

While all essential configuration is done during installation, you can:

- **Fine-tune settings** via the web interface at `/setup`
- **Reconfigure anytime** using `sudo eas-config` (raspi-config style TUI)
- **Advanced settings** can be edited in `/opt/eas-station/.env`

**Note:** For advanced features like FIPS code lookup and zone code derivation, use the web-based setup wizard at `/setup` which provides interactive builders.

### Check Status

```bash
# All services
sudo systemctl status eas-station.target

# Individual services
sudo systemctl status eas-station-web.service
sudo systemctl status eas-station-sdr.service

# View logs
sudo journalctl -u eas-station-web.service -f
```

### Access Web Interface

- **Local:** https://localhost
- **Network:** https://your-ip-address
- Accept self-signed certificate (safe for testing)

## Common Tasks

### Start/Stop Services

```bash
# Start all
sudo systemctl start eas-station.target

# Stop all
sudo systemctl stop eas-station.target

# Restart all
sudo systemctl restart eas-station.target
```

### Enable Auto-Start on Boot

```bash
sudo systemctl enable eas-station.target
```

### View Logs

```bash
# Follow logs
sudo journalctl -u eas-station-web.service -f

# Last 100 lines
sudo journalctl -u eas-station-web.service -n 100

# All services
sudo journalctl -u eas-station-*.service -f
```

### Upgrade to Latest Version

```bash
# Automatic update (recommended)
cd /opt/eas-station
sudo bash update.sh
```

The update script automatically:
- Backs up your installation
- Pulls latest code
- Preserves your configuration
- Updates dependencies
- Runs database migrations
- Restarts services

### Configure SSL (Production)

```bash
# Install Let's Encrypt certificate
sudo certbot --nginx -d your-domain.com

# Certificate auto-renews
```

## Troubleshooting

### Service Won't Start

```bash
# Check status
sudo systemctl status eas-station-web.service

# Check logs
sudo journalctl -u eas-station-web.service -n 50

# Check database
sudo systemctl status postgresql
sudo systemctl status redis-server
```

### Can't Access Web Interface

```bash
# Check nginx
sudo systemctl status nginx
sudo nginx -t

# Check if port is open
sudo netstat -tlnp | grep :443
```

### SDR Not Found

```bash
# Check USB device
lsusb | grep -i rtl

# Check SoapySDR
SoapySDRUtil --find

# Check service
sudo systemctl status eas-station-sdr.service
```

## Next Steps

- 📖 Read [Installation Details](INSTALLATION_DETAILS.md) for the full bare-metal walkthrough
- 🔧 Configure hardware (SDR, GPIO, displays)
- 📡 Set up your location and FIPS codes
- 🔔 Enable alert broadcasting
- 🌐 Configure remote access

## Getting Help

- **Documentation:** `/opt/eas-station/docs/`
- **GitHub Issues:** https://github.com/KR8MER/eas-station/issues
- **Discussions:** https://github.com/KR8MER/eas-station/discussions

---

**73 de KR8MER** 📡
