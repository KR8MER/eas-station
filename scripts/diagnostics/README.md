# Diagnostic Scripts

This directory contains diagnostic and troubleshooting scripts for EAS Station™.

## Quick Start

**If your SDR is not working, start here:**

```bash
# Comprehensive SDR diagnostics with automatic report generation
bash scripts/collect_sdr_diagnostics.sh

# Quick SDR hardware and software check
python3 scripts/sdr_diagnostics.py

# Check SDR receiver status in running system
python3 scripts/diagnostics/check_sdr_status.py
```

See also:
- **[SDR Quick Fix Guide](../../docs/troubleshooting/SDR_QUICK_FIX_GUIDE.md)** - Fast solutions for common problems
- **[SDR Master Troubleshooting Guide](../../docs/troubleshooting/SDR_MASTER_TROUBLESHOOTING_GUIDE.md)** - Complete diagnostic procedures

---

## Available Scripts

### `check_sdr_status.py`

Diagnostic tool to check SDR receiver and RadioManager status.

**Usage:**
```bash
python3 scripts/diagnostics/check_sdr_status.py
```

**Purpose:** Verifies SDR audio pipeline health, displays receiver configuration, and checks if receivers are locked to signals.

**Documentation:** See [SDR Waterfall Troubleshooting Guide](../../docs/guides/SDR_WATERFALL_TROUBLESHOOTING.md)

---

### `troubleshoot_connection.sh`

Comprehensive connection troubleshooting for EAS Station™ web interface.

**Usage:**
```bash
bash scripts/diagnostics/troubleshoot_connection.sh
```

**Purpose:** Diagnoses container status, port mappings, network configuration, and firewall issues.

**Documentation:** See [Portainer Deployment Guide](../../docs/deployment/portainer/PORTAINER_QUICK_START.md)

---

### `diagnose_icecast.sh`

Icecast streaming server port 8001 diagnostic tool.

**Usage:**
```bash
bash scripts/diagnostics/diagnose_icecast.sh
```

**Purpose:** Checks Icecast container status, port availability, firewall rules, and provides remediation steps for streaming issues.

---

### `diagnose_portainer.sh`

Quick diagnostic script for EAS Station™ Portainer deployments.

**Usage:**
```bash
bash scripts/diagnostics/diagnose_portainer.sh
```

**Purpose:** Validates container status, port mappings, and network configuration for Portainer-based deployments.

---

## SDR-Specific Diagnostics

### `../collect_sdr_diagnostics.sh`

**⭐ Recommended for SDR troubleshooting**

Comprehensive diagnostic information collector for SDR issues.

**Usage:**
```bash
bash scripts/collect_sdr_diagnostics.sh
bash scripts/collect_sdr_diagnostics.sh /path/to/output.txt
```

**Purpose:** Collects complete diagnostic information including:
- Hardware detection (USB devices)
- SoapySDR device enumeration
- Container status and logs
- Database configuration
- Redis status
- System resources
- Automatic report generation

**Output:** Creates a timestamped text file with all diagnostic information, ready to attach to GitHub issues.

**Documentation:** See [SDR Master Troubleshooting Guide](../../docs/troubleshooting/SDR_MASTER_TROUBLESHOOTING_GUIDE.md)

---

### `../sdr_diagnostics.py`

Python-based SDR hardware and driver diagnostic tool.

**Usage:**
```bash
python3 scripts/sdr_diagnostics.py
python3 scripts/sdr_diagnostics.py --test-capture --driver rtlsdr --frequency 162550000
```

**Purpose:** 
- Checks SoapySDR installation
- Enumerates connected SDR devices
- Tests sample capture
- Displays device capabilities

**Documentation:** Run with `--help` for all options

---

## Running Diagnostics

All diagnostic scripts can be run from the repository root:

```bash
# Check SDR status
python3 scripts/diagnostics/check_sdr_status.py

# Troubleshoot web interface connection
bash scripts/diagnostics/troubleshoot_connection.sh

# Diagnose Icecast streaming issues
bash scripts/diagnostics/diagnose_icecast.sh

# Portainer-specific diagnostics
bash scripts/diagnostics/diagnose_portainer.sh
```

## Capturing Output

To save diagnostic output for sharing:

```bash
# SDR diagnostics (automatically creates timestamped file)
bash scripts/collect_sdr_diagnostics.sh

# Individual scripts
python3 scripts/diagnostics/check_sdr_status.py > sdr_diagnostic.txt
bash scripts/diagnostics/troubleshoot_connection.sh > output.txt 2>&1
bash scripts/diagnostics/diagnose_icecast.sh > icecast_diagnostic.txt 2>&1
```

## Related Documentation

### SDR Troubleshooting
- **[SDR Quick Fix Guide](../../docs/troubleshooting/SDR_QUICK_FIX_GUIDE.md)** - 5-minute checklist for common SDR problems
- **[SDR Master Troubleshooting Guide](../../docs/troubleshooting/SDR_MASTER_TROUBLESHOOTING_GUIDE.md)** - Complete step-by-step diagnostic procedures
- **[SDR Audio Tuning Issues](../../docs/troubleshooting/SDR_AUDIO_TUNING_ISSUES.md)** - Audio-specific troubleshooting
- **[SDR Setup Guide](../../docs/hardware/SDR_SETUP.md)** - Initial SDR configuration

### General Troubleshooting
- [Portainer Deployment](../../docs/deployment/portainer/PORTAINER_QUICK_START.md)
- [All Troubleshooting Guides](../../docs/troubleshooting/)
