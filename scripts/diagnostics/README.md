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
- **[SDR Master Troubleshooting Guide](../../docs/troubleshooting/SDR_MASTER_TROUBLESHOOTING_GUIDE.md)** - Complete diagnostic procedures
- **[SDR Setup Guide](../../docs/hardware/SDR_SETUP.md)** - Initial SDR configuration

---

## Available Scripts

### `check_sdr_status.py`

Diagnostic tool to check SDR receiver and pipeline status. A thin CLI
wrapper around `app_core/radio/diagnostics_report.py` -- the same
checklist the web UI's "Run Full Diagnostics" button runs (SDR Diagnostics
page, `POST /api/radio/diagnostics/run-check`), so the two surfaces can't
drift apart.

**Usage:**
```bash
python3 scripts/diagnostics/check_sdr_status.py
```

**Purpose:** Verifies SDR audio pipeline health via the Redis state the
`eas-station-sdr.service` process publishes (heartbeat, per-receiver
metrics, ring-buffer overflow/underflow, spectrum cache freshness) and
checks database receiver configuration for sanity.

---

### `check_receiver_config.py`

Checks radio receiver configuration in the database for common audio output issues.

**Usage:**
```bash
python3 scripts/diagnostics/check_receiver_config.py
```

**Purpose:** Inspects `RadioReceiver` and audio source configuration rows and flags settings that commonly break audio output. Requires `DATABASE_URL` to be set (loaded from `.env`).

---

### `diagnose_audio_chain.py`

End-to-end audio chain diagnostic for SDR sources.

**Usage:**
```bash
python3 scripts/diagnostics/diagnose_audio_chain.py
```

**Purpose:** Checks the complete audio chain:
1. Radio receivers in the database (LP1, LP2, SP1)
2. Audio source configs for each receiver
3. Redis connectivity and published IQ samples
4. Audio service metrics
5. EAS monitor status

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
- Service status and logs
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

## Capturing Output

To save diagnostic output for sharing:

```bash
# SDR diagnostics (automatically creates timestamped file)
bash scripts/collect_sdr_diagnostics.sh

# Individual scripts
python3 scripts/diagnostics/check_sdr_status.py > sdr_diagnostic.txt
python3 scripts/diagnostics/diagnose_audio_chain.py > audio_chain.txt 2>&1
```

## Related Documentation

- **[SDR Master Troubleshooting Guide](../../docs/troubleshooting/SDR_MASTER_TROUBLESHOOTING_GUIDE.md)** - Complete step-by-step diagnostic procedures
- **[SDR Setup Guide](../../docs/hardware/SDR_SETUP.md)** - Initial SDR configuration
- [All Troubleshooting Guides](../../docs/troubleshooting/)
