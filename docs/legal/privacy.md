# Privacy Policy

**Effective Date**: January 2025

## Overview

EAS Station is self-hosted software. All data remains on your infrastructure.

## Data Collection

### Data EAS Station Collects

**Locally stored:**

- Emergency alert data (from NOAA/IPAWS)
- System configuration
- User preferences
- Application logs
- Audio files (if broadcast enabled)

**NOT collected:**

- Personal information (unless you configure it)
- Usage telemetry
- Analytics data

### Third-Party Services

If you enable optional integrations:

**NOAA Weather Service:**
- Your server IP address is logged by NOAA
- User agent string sent per API requirements

**IPAWS:**
- Your server IP address may be logged
- No personal information transmitted

**Azure OpenAI (Optional TTS):**
- Alert text sent for speech synthesis
- Subject to Microsoft privacy policy
- Only if you configure and enable

## Data Storage

All data stored locally in:

- PostgreSQL database (on your infrastructure)
- File system (audio files, logs)
- No cloud storage by default

## Data Sharing

EAS Station does **not** share data with third parties except:

- NOAA API (to fetch alerts)
- IPAWS API (to fetch federal alerts)
- Azure OpenAI (if configured for TTS)

## Data Security

### Your Responsibilities

- Secure database with strong passwords
- Use HTTPS for web access
- Restrict network access
- Regular security updates
- Proper backup procedures

### Software Security

EAS Station includes:

- Password hashing (if authentication enabled)
- SQL injection prevention
- XSS protection
- CSRF tokens
- Secure session handling

## Data Retention

You control data retention:

- Configure alert retention in admin panel
- Manage log rotation
- Database cleanup tools available

## User Rights

As self-hosted software:

- You own all data
- You control retention
- You can delete data anytime
- No third-party data access

## Cookies

EAS Station uses cookies for:

- Session management
- User preferences
- CSRF protection

No tracking or advertising cookies.

## Children's Privacy

EAS Station is not directed at children. No age restriction enforced.

## Changes to Privacy Policy

Privacy policy may be updated. Check this page for changes.

## Contact

Questions: [GitHub Issues](https://github.com/KR8MER/eas-station/issues)

---

**Last Updated**: 2025-01-28
