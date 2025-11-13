# Post-Installation Checklist

## Overview

This document provides a comprehensive checklist for validating and preparing an EAS Station deployment for production use. Complete all items before deploying in a mission-critical broadcast environment.

**⚠️ IMPORTANT:** EAS Station is experimental software and **must not** replace FCC-certified equipment without proper authorization and testing.

## Checklist Categories

- [Initial Setup](#initial-setup)
- [Configuration Validation](#configuration-validation)
- [Hardware Testing](#hardware-testing)
- [Audio Verification](#audio-verification)
- [Security Hardening](#security-hardening)
- [Monitoring and Alerting](#monitoring-and-alerting)
- [Backup Configuration](#backup-configuration)
- [Documentation](#documentation)
- [Burn-In Testing](#burn-in-testing)
- [Go-Live](#go-live)

---

## Initial Setup

### System Prerequisites

- [ ] Raspberry Pi or compatible hardware installed
- [ ] Operating system installed and updated
  ```bash
  sudo apt update && sudo apt upgrade -y
  sudo reboot
  ```
- [ ] Static IP address configured
- [ ] Network connectivity verified (ping google.com, weather.gov)
- [ ] Time zone configured correctly
  ```bash
  sudo timedatectl set-timezone America/New_York  # Adjust for your location
  timedatectl status
  ```
- [ ] NTP time synchronization enabled and working
  ```bash
  timedatectl show-timesync
  ```

### Docker Installation

- [ ] Docker installed and running
  ```bash
  docker --version
  systemctl status docker
  ```
- [ ] Docker Compose installed
  ```bash
  docker-compose --version
  ```
- [ ] Current user added to docker group
  ```bash
  sudo usermod -aG docker $USER
  # Log out and back in
  groups  # Should include "docker"
  ```

### EAS Station Installation

- [ ] Repository cloned
  ```bash
  git clone https://github.com/KR8MER/eas-station.git
  cd eas-station
  ```
- [ ] `.env` file created from `.env.example`
- [ ] Setup wizard completed
  ```bash
  python3 tools/setup_wizard.py
  ```
- [ ] SECRET_KEY generated and configured (64 characters minimum)
- [ ] Docker Compose override configured (if needed)
  ```bash
  cp examples/docker-compose/docker-compose.audio-alsa.yml docker-compose.override.yml
  ```

### Database Setup

- [ ] PostgreSQL connection parameters configured in `.env`
- [ ] Database initialized
  ```bash
  docker-compose up -d alerts-db
  docker-compose run --rm app flask db upgrade
  ```
- [ ] Database connection verified
  ```bash
  docker-compose exec alerts-db psql -U postgres -d alerts -c "\dt"
  ```

### Initial Service Start

- [ ] All services started
  ```bash
  docker-compose up -d
  ```
- [ ] All containers running
  ```bash
  docker-compose ps
  # All services should show "Up"
  ```
- [ ] Web interface accessible
  - Navigate to http://your-pi-ip:5000
- [ ] No errors in logs
  ```bash
  docker-compose logs -f
  ```

---

## Configuration Validation

### Location Settings

- [ ] Timezone configured correctly
- [ ] County name and state code set
- [ ] NWS zone codes configured
- [ ] Geographic coordinates entered
- [ ] Map center and zoom level verified

**Verify in:** `/admin` → Location Settings tab

### Alert Sources

- [ ] NOAA Weather API polling enabled
- [ ] Poll interval configured (180 seconds recommended)
- [ ] NOAA User Agent configured properly
- [ ] IPAWS polling configured (if using)
- [ ] CAP feed URLs verified

**Verify in:** Check logs for successful CAP polls
```bash
docker-compose logs poller | grep -i "poll"
```

### EAS Broadcast Settings

- [ ] Broadcast enabled (if desired): `EAS_BROADCAST_ENABLED=true`
- [ ] Originator code configured (WXR, EAS, CIV)
- [ ] Station ID/callsign configured (8 characters)
- [ ] FIPS codes authorized for manual broadcasts
- [ ] Event codes authorized
- [ ] Attention tone duration set (8 seconds default)

**Verify in:** `/admin` → EAS Broadcast tab

### TTS Configuration (Optional)

- [ ] TTS provider selected (azure_openai, azure, pyttsx3, or none)
- [ ] API credentials configured (if using Azure)
- [ ] Voice and model selected
- [ ] Test TTS generation successful

**Test command:**
```bash
docker-compose exec app python -c "from app_utils.tts import synthesize_text; synthesize_text('Test alert message', 'test.wav')"
```

---

## Hardware Testing

### USB Audio Interface

- [ ] USB audio interface connected to USB 3.0 port
- [ ] Device detected by system
  ```bash
  lsusb | grep -i audio
  arecord -l
  aplay -l
  ```
- [ ] ALSA configuration applied
  ```bash
  cat /etc/asound.conf
  ```
- [ ] Audio device permissions correct
  ```bash
  ls -l /dev/snd/
  ```
- [ ] Device accessible in Docker container
  ```bash
  docker-compose exec app arecord -l
  ```

**Documentation:** See [Audio Hardware Setup](audio_hardware)

### SDR Receivers (Optional)

- [ ] SDR hardware connected
- [ ] SoapySDR drivers installed
- [ ] SDR detected
  ```bash
  SoapySDRUtil --find
  rtl_test -t  # For RTL-SDR
  ```
- [ ] Receiver configured in web UI: `/settings/radio`
- [ ] Frequency and gain settings verified
- [ ] Signal quality good (check /system/health)

### GPIO and Relays (Optional)

- [ ] Relay HAT or module connected to GPIO header
- [ ] GPIO pin numbers configured in `.env`
- [ ] Active state configured (HIGH/LOW)
- [ ] Hold duration configured
- [ ] Manual GPIO test successful: `/admin/gpio`
- [ ] Relay activation logged in database
- [ ] External equipment responds to relay activation

**⚠️ SAFETY:** Test GPIO with non-critical loads first. Never test with live transmitters until fully validated.

**Documentation:** See [GPIO Integration Guide](../hardware/gpio)

### LED Sign (Optional)

- [ ] LED sign IP address configured
- [ ] LED sign port configured (10001 default)
- [ ] Test message sent successfully
- [ ] Default messages configured
- [ ] Sign updates on alert status change

### VFD Display (Optional)

- [ ] VFD serial port configured (`/dev/ttyUSB0`)
- [ ] Baud rate set correctly (38400 default)
- [ ] User added to dialout group
  ```bash
  sudo usermod -aG dialout $USER
  ```
- [ ] Test message displayed
- [ ] Display updates on alert status change

---

## Audio Verification

### Input Testing

- [ ] Audio sources connected (weather radio, line input, etc.)
- [ ] Input levels configured in web UI: `/settings/audio-sources`
- [ ] Real-time metering visible
- [ ] Peak levels between -6dBFS and -3dBFS (ideal range)
- [ ] RMS levels between -18dBFS and -12dBFS
- [ ] No clipping observed (red indicators)
- [ ] No sustained silence detected
- [ ] Signal-to-noise ratio acceptable (>40dB)

**Test procedure:**
1. Play known audio source (weather radio, tone generator)
2. Observe meters in `/settings/audio-sources`
3. Adjust input gain on USB interface as needed
4. Record 30-second sample and analyze

### Output Testing

- [ ] Output device configured
- [ ] Test tone generation successful
- [ ] Output level calibrated (0VU = +4dBu typical)
- [ ] Connected equipment receives audio
- [ ] No distortion or clipping
- [ ] Stereo channels balanced

**Test procedure:**
```bash
# Generate and play test tone
speaker-test -c 2 -t sine -f 1000
```

### SAME Decoder Testing (If Audio Ingest Enabled)

- [ ] Audio ingest pipeline running
- [ ] SAME decoder processing audio
- [ ] Test SAME header decoded successfully
- [ ] Decoded alerts appear in database
- [ ] Alert metadata extracted correctly

**Test with sample file:**
Place test EAS audio file in `test_audio/` and configure file source in `.env`

---

## Security Hardening

### User Access Control

- [ ] Admin account created with strong password
- [ ] Role-based access control configured: `/settings/security`
- [ ] Operator, Analyst, and Viewer roles assigned as needed
- [ ] Multi-factor authentication (MFA) enabled for admins
  - [ ] TOTP setup completed
  - [ ] Backup codes saved securely
- [ ] Default/test accounts removed

### Network Security

- [ ] Firewall configured (UFW or iptables)
  ```bash
  sudo ufw status
  ```
- [ ] Only necessary ports open:
  - [ ] Port 5000 (web interface) - restrict to local network
  - [ ] Port 22 (SSH) - restrict to management network
- [ ] SSH key authentication enabled
- [ ] Password authentication disabled for SSH
- [ ] Fail2ban installed and configured
  ```bash
  sudo systemctl status fail2ban
  ```

### Application Security

- [ ] SECRET_KEY is unique and secure (not default value)
- [ ] Database password is strong and unique
- [ ] API endpoints protected by authentication
- [ ] CSRF protection enabled
- [ ] Session timeout configured (30 minutes default)
- [ ] Audit logging enabled: `/settings/security`
- [ ] Sensitive configuration files have restricted permissions
  ```bash
  chmod 600 .env
  ```

### System Security

- [ ] System packages updated to latest versions
  ```bash
  sudo apt update && sudo apt list --upgradable
  ```
- [ ] Automatic security updates enabled
  ```bash
  sudo apt install unattended-upgrades
  sudo dpkg-reconfigure --priority=low unattended-upgrades
  ```
- [ ] Root login disabled
- [ ] Unused services disabled
- [ ] System logs reviewed for suspicious activity
  ```bash
  sudo journalctl -p err -b
  ```

**Documentation:** See [Security Migration Guide](../MIGRATION_SECURITY)

---

## Monitoring and Alerting

### System Health Monitoring

- [ ] System health endpoint accessible: `/system/health`
- [ ] All health checks passing:
  - [ ] Database connectivity
  - [ ] Audio sources status
  - [ ] Receiver lock status
  - [ ] Disk space available
  - [ ] Memory usage acceptable
  - [ ] CPU temperature normal (<70°C)
- [ ] Health check interval configured (10 seconds default)

### Alert Monitoring

- [ ] Alert verification dashboard accessible: `/admin/alert-verification`
- [ ] Received alerts appear in database
- [ ] Alert timeline displays correctly
- [ ] Alert details complete (event code, FIPS, expiration)
- [ ] Playout queue functioning (if broadcast enabled)

### Email Notifications (Optional)

- [ ] Email server configured in `.env`
- [ ] SMTP credentials verified
- [ ] Test email sent successfully
- [ ] Alert email notifications enabled
- [ ] Recipient addresses configured
- [ ] Email templates reviewed

### Log Management

- [ ] Log level configured (INFO for production)
- [ ] Log rotation enabled
- [ ] Logs accessible via Docker
  ```bash
  docker-compose logs -f app
  ```
- [ ] Log retention policy defined
- [ ] Disk space monitored for log storage

### External Monitoring (Recommended)

- [ ] Uptime monitoring configured (UptimeRobot, Pingdom, etc.)
- [ ] HTTP endpoint check: `http://your-pi-ip:5000/health`
- [ ] Alert on downtime
- [ ] Alert on failed health checks

---

## Backup Configuration

### Automated Backups

- [ ] Backup schedule configured (daily recommended)
- [ ] Backup script tested: `tools/create_backup.py`
  ```bash
  python3 tools/create_backup.py
  ```
- [ ] Backup rotation configured: `tools/rotate_backups.py`
- [ ] Backup location configured (external storage recommended)
- [ ] Backup includes:
  - [ ] Database dump
  - [ ] Configuration files (`.env`)
  - [ ] Audio archives
  - [ ] Station documentation

### Backup Automation

- [ ] Cron job or systemd timer configured
  ```bash
  # Example cron (daily at 2 AM):
  0 2 * * * /usr/bin/python3 /path/to/eas-station/tools/create_backup.py
  ```
- [ ] Backup monitoring in place
- [ ] Failed backup alerts configured

### Backup Testing

- [ ] Test restore performed from backup
- [ ] Restore procedure documented
- [ ] Backup integrity verified
- [ ] Off-site backup copy maintained

**Documentation:** See [Backup Strategy Runbook](../runbooks/backup_strategy)

---

## Documentation

### Station Documentation

- [ ] Station log book created (digital or physical)
- [ ] Hardware inventory documented:
  - [ ] Raspberry Pi model and serial number
  - [ ] USB audio interface make/model
  - [ ] SDR receivers (if used)
  - [ ] Relay modules (if used)
  - [ ] Peripheral devices (LED sign, VFD)
- [ ] Network configuration documented:
  - [ ] Static IP address
  - [ ] Subnet mask and gateway
  - [ ] DNS servers
  - [ ] Firewall rules
- [ ] Audio routing diagram created
- [ ] GPIO pinout diagram created (if used)

### Configuration Documentation

- [ ] `.env` configuration documented
- [ ] Backup of `.env` stored securely
- [ ] Database connection details documented
- [ ] API credentials documented (secure storage)
- [ ] Custom ALSA configuration documented (`/etc/asound.conf`)

### Operational Procedures

- [ ] Daily checklist created
- [ ] Weekly maintenance tasks defined
- [ ] Monthly reporting procedures documented
- [ ] Emergency contact list maintained
- [ ] Escalation procedures defined
- [ ] Incident response plan documented

### Compliance Documentation

- [ ] Required Weekly Test (RWT) schedule documented
- [ ] Required Monthly Test (RMT) schedule documented
- [ ] Alert verification procedures documented
- [ ] FCC compliance checklist maintained
- [ ] Station log retention policy defined (180 days minimum)

---

## Burn-In Testing

### 72-Hour Soak Test

Run the system continuously for 72 hours (3 days) to validate stability:

- [ ] System started and monitored for 72 hours
- [ ] No unexpected restarts or crashes
- [ ] CPU temperature stable (<70°C throughout)
- [ ] Memory usage stable (no memory leaks)
- [ ] Disk I/O acceptable
- [ ] Network connectivity maintained
- [ ] Audio capture functioning continuously
- [ ] Alerts received and processed correctly
- [ ] No errors in logs (review daily)

**Monitor during burn-in:**
```bash
# System health
watch -n 60 'docker-compose exec app curl -s http://localhost:5000/system/health | jq'

# CPU temperature
watch -n 60 'vcgencmd measure_temp'

# Container resource usage
watch -n 60 'docker stats --no-stream'

# Logs
docker-compose logs -f --tail=100
```

### Load Testing

- [ ] Multiple simultaneous alerts processed correctly
- [ ] Database handles high volume (100+ alerts)
- [ ] Web interface responsive under load
- [ ] Audio playout queue handles multiple items
- [ ] GPIO activations handled correctly in rapid succession

### Failover Testing

- [ ] Simulated power failure (UPS test)
  - [ ] System survived power loss
  - [ ] Services recovered automatically
  - [ ] Database integrity maintained
  - [ ] No data loss
- [ ] Simulated network outage
  - [ ] System continued to function locally
  - [ ] Recovered automatically when network restored
  - [ ] Alert backlog processed after recovery
- [ ] Simulated USB device disconnect
  - [ ] Error logged appropriately
  - [ ] System remained stable
  - [ ] Device recovered after reconnection

---

## Go-Live

### Final Pre-Launch Checks

- [ ] All previous checklist items completed
- [ ] Burn-in testing successful
- [ ] Backup and restore procedures tested
- [ ] Contact information updated (email, phone)
- [ ] On-call schedule defined
- [ ] Monitoring and alerting confirmed working
- [ ] Documentation complete and accessible

### Launch Criteria

- [ ] System running stable for 72+ hours
- [ ] Zero critical errors in logs
- [ ] Health checks all passing
- [ ] Test alerts sent and received successfully
- [ ] Audio levels calibrated
- [ ] GPIO control verified (if applicable)
- [ ] Backup confirmed working
- [ ] Team trained on operational procedures

### Launch Day

- [ ] System status verified before cutover
- [ ] Announce maintenance window (if replacing existing system)
- [ ] Switch over to EAS Station
- [ ] Monitor system for 4 hours post-launch
- [ ] Verify alert reception and processing
- [ ] Test manual broadcast functionality (test event only)
- [ ] Confirm external monitoring receiving data
- [ ] Document launch date and time in station log

### Post-Launch

- [ ] Monitor system continuously for first 24 hours
- [ ] Review logs daily for first week
- [ ] Conduct Required Weekly Test (RWT) on schedule
- [ ] Verify compliance reporting working
- [ ] Schedule first backup verification (1 week post-launch)
- [ ] Gather feedback from operators
- [ ] Update documentation based on operational experience

---

## Ongoing Maintenance

### Daily Tasks

- [ ] Check system health dashboard: `/system/health`
- [ ] Review any new alerts
- [ ] Monitor audio levels
- [ ] Check for system errors in logs

### Weekly Tasks

- [ ] Conduct Required Weekly Test (RWT)
- [ ] Review alert verification report
- [ ] Check disk space usage
- [ ] Review backup success/failure
- [ ] Update station log

### Monthly Tasks

- [ ] Conduct Required Monthly Test (RMT)
- [ ] Review compliance reports
- [ ] Update system packages
  ```bash
  sudo apt update && sudo apt upgrade
  ```
- [ ] Review and rotate logs
- [ ] Test backup restore procedure
- [ ] Review security audit logs

### Quarterly Tasks

- [ ] Full system audit
- [ ] Review and update documentation
- [ ] Review and update contact information
- [ ] Test failover procedures
- [ ] Review and update emergency procedures

### Annual Tasks

- [ ] Hardware inspection and cleaning
- [ ] Replace UPS batteries (if applicable)
- [ ] Review and renew API credentials
- [ ] Compliance review
- [ ] Update disaster recovery plan

---

## Troubleshooting Resources

If issues arise during post-install:

- **Audio Issues:** [Audio Hardware Setup](audio_hardware)
- **GPIO Issues:** [GPIO Integration Guide](../hardware/gpio)
- **Security Issues:** [Security Migration Guide](../MIGRATION_SECURITY)
- **Backup Issues:** [Backup Strategy Runbook](../runbooks/backup_strategy)
- **General Issues:** [GitHub Issues](https://github.com/KR8MER/eas-station/issues)

## Support

For assistance with deployment:

- **Documentation:** https://github.com/KR8MER/eas-station/tree/main/docs
- **GitHub Issues:** https://github.com/KR8MER/eas-station/issues
- **Discussions:** https://github.com/KR8MER/eas-station/discussions

---

## Certification Notice

**⚠️ EXPERIMENTAL SOFTWARE:**

EAS Station is experimental laboratory software for research and development purposes. It has **not** been certified by the FCC for use as Primary Entry Point (PEP) equipment or for meeting EAS decoder/encoder requirements under FCC Part 11.

**Before deploying in production:**
1. Consult with legal counsel and broadcast engineering consultants
2. Ensure compliance with all FCC regulations
3. Maintain FCC-certified backup equipment
4. Document all testing and validation procedures
5. Understand that you operate this software at your own risk

**This software is provided "AS IS" without warranty of any kind.**

---

**Document Version:** 1.0
**Last Updated:** 2025-11-05
**Maintainer:** EAS Station Development Team
