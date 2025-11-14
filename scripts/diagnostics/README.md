# Diagnostic Scripts

This directory contains diagnostic and troubleshooting scripts for EAS Station.

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

Comprehensive connection troubleshooting for EAS Station web interface.

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

Quick diagnostic script for EAS Station Portainer deployments.

**Usage:**
```bash
bash scripts/diagnostics/diagnose_portainer.sh
```

**Purpose:** Validates container status, port mappings, and network configuration for Portainer-based deployments.

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
python3 scripts/diagnostics/check_sdr_status.py > sdr_diagnostic.txt
bash scripts/diagnostics/troubleshoot_connection.sh > output.txt 2>&1
```

## Related Documentation

- [SDR Setup Guide](../../docs/SDR_SETUP.md)
- [Portainer Deployment](../../docs/deployment/portainer/PORTAINER_QUICK_START.md)
- [Troubleshooting Guides](../../docs/guides/)
