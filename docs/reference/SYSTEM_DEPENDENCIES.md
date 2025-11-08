# System Dependencies Guide

This guide documents all system-level dependencies required to run EAS Station. These packages must be installed via your operating system's package manager (e.g., `apt`, `yum`, `brew`) before running the application.

> **Note for Docker Users**: If you're using the provided Docker containers, all system dependencies are pre-installed automatically. This guide is primarily for users installing from source or running the application natively.

---

## Table of Contents

- [Required Dependencies](#required-dependencies)
- [Optional Dependencies](#optional-dependencies)
- [Installation Instructions](#installation-instructions)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)

---

## Required Dependencies

These packages are **absolutely required** for core functionality.

### PostgreSQL with PostGIS

**Required for**: Database storage and spatial queries

- **Package**: `postgresql-14` or higher, `postgis-3` or higher
- **Purpose**: Stores alerts, locations, boundaries, and system configuration
- **Why required**: The application cannot function without a database backend

**Installation**:
```bash
# Debian/Ubuntu
sudo apt-get install postgresql-14 postgis postgresql-14-postgis-3

# Note: EAS Station typically uses PostgreSQL in a separate container/service
# See docker-compose.yml for the recommended deployment approach
```

### Python 3.11+

**Required for**: Running the application

- **Package**: `python3.11` or higher
- **Purpose**: Application runtime environment
- **Why required**: EAS Station is written in Python 3.11+

**Installation**:
```bash
# Debian/Ubuntu
sudo apt-get install python3.11 python3.11-venv python3-pip

# Verify installation
python3.11 --version
```

### Build Tools

**Required for**: Compiling Python extensions

- **Package**: `build-essential`
- **Purpose**: C/C++ compiler toolchain (gcc, g++, make)
- **Why required**: Many Python packages have native extensions that must be compiled

**Installation**:
```bash
# Debian/Ubuntu
sudo apt-get install build-essential
```

### PostgreSQL Client Libraries

**Required for**: Database connectivity

- **Package**: `libpq-dev`
- **Purpose**: PostgreSQL client library development headers
- **Why required**: Required for building psycopg2 from source

**Installation**:
```bash
# Debian/Ubuntu
sudo apt-get install libpq-dev
```

### SSL/TLS Certificates

**Required for**: HTTPS connections

- **Package**: `ca-certificates`
- **Purpose**: Common CA certificates for SSL/TLS validation
- **Why required**: Required for secure HTTPS connections to CAP feeds and APIs

**Installation**:
```bash
# Debian/Ubuntu
sudo apt-get install ca-certificates
sudo update-ca-certificates
```

---

## Optional Dependencies

These packages enable specific features but are not required for basic operation.

### FFmpeg (Highly Recommended)

**Required for**: Audio stream decoding from HTTP/Icecast sources

- **Package**: `ffmpeg`
- **Purpose**: Audio codec library with libavcodec and libavformat
- **Why important**: Required by pydub for decoding MP3, AAC, and OGG audio streams
- **Without it**: Audio ingest from streaming sources will not work

**Installation**:
```bash
# Debian/Ubuntu
sudo apt-get install ffmpeg

# Verify installation
ffmpeg -version
```

**Impact if missing**:
- Audio sources using HTTP or Icecast streams will fail
- SciPy fallback provides basic resampling but NOT format decoding
- **Recommendation**: Always install ffmpeg for production deployments

### SoapySDR (For SDR Receivers)

**Required for**: Software Defined Radio support

- **Packages**:
  - `python3-soapysdr` - Python bindings
  - `soapysdr-tools` - CLI utilities
  - `soapysdr-module-rtlsdr` - RTL-SDR hardware driver
  - `soapysdr-module-airspy` - Airspy hardware driver
  - `libusb-1.0-0` / `libusb-1.0-0-dev` - USB device access

- **Purpose**: Enables reception of EAS alerts via SDR hardware
- **Why important**: Allows monitoring live broadcast radio for EAS alerts

**Installation**:
```bash
# Debian/Ubuntu - Install all SDR components
sudo apt-get install \
    python3-soapysdr \
    soapysdr-tools \
    soapysdr-module-rtlsdr \
    soapysdr-module-airspy \
    libusb-1.0-0 \
    libusb-1.0-0-dev

# Verify installation
SoapySDRUtil --info
```

**Impact if missing**:
- SDR audio sources will not function
- Radio monitoring features disabled
- USB SDR devices will not be detected

**Hardware compatibility**:
- RTL-SDR USB dongles (RTL2832U chipset)
- Airspy SDR receivers
- Other SoapySDR-compatible hardware

### eSpeak (For Text-to-Speech)

**Required for**: Offline voice synthesis with pyttsx3

- **Packages**: `espeak`, `libespeak-ng1`
- **Purpose**: Text-to-speech synthesis engine backend
- **Why important**: Generates audio narration for alerts when voice provider is enabled

**Installation**:
```bash
# Debian/Ubuntu
sudo apt-get install espeak libespeak-ng1

# Test installation
espeak "Test message"
```

**Impact if missing**:
- pyttsx3 text-to-speech will not work
- Azure TTS (if configured) still works as cloud alternative
- Alert audio generation requires external TTS service

### Icecast2 (For Audio Streaming)

**Required for**: Broadcasting audio streams

- **Package**: `icecast2`
- **Purpose**: Streaming media server for audio broadcasting
- **Why important**: Enables professional-quality audio streaming output

**Installation**:
```bash
# Debian/Ubuntu
sudo apt-get install icecast2

# Configure and start
sudo systemctl enable icecast2
sudo systemctl start icecast2
```

**Impact if missing**:
- Audio streaming outputs will not function
- Cannot broadcast EAS alerts to multiple clients
- See docs/guides/ICECAST_STREAMING.md for setup guide

**Docker users**: Use the provided `Dockerfile.icecast` container instead of installing locally.

---

## Installation Instructions

### Quick Install (Debian/Ubuntu)

Install **all dependencies** (required + optional):

```bash
# Update package list
sudo apt-get update

# Install all dependencies in one command
sudo apt-get install -y \
    build-essential \
    ca-certificates \
    python3.11 \
    python3.11-venv \
    python3-pip \
    libpq-dev \
    ffmpeg \
    espeak \
    libespeak-ng1 \
    python3-soapysdr \
    soapysdr-tools \
    soapysdr-module-rtlsdr \
    soapysdr-module-airspy \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    icecast2

# Update CA certificates
sudo update-ca-certificates
```

### Minimal Install (Required Only)

Install only **required dependencies**:

```bash
# Update package list
sudo apt-get update

# Install minimal required packages
sudo apt-get install -y \
    build-essential \
    ca-certificates \
    python3.11 \
    python3.11-venv \
    python3-pip \
    libpq-dev

# Update CA certificates
sudo update-ca-certificates
```

> **Note**: With minimal install, audio streaming and SDR features will be disabled.

### Feature-Specific Install

Install dependencies for specific features:

**Audio Streaming Only**:
```bash
sudo apt-get install -y ffmpeg icecast2
```

**SDR Support Only**:
```bash
sudo apt-get install -y \
    python3-soapysdr \
    soapysdr-tools \
    soapysdr-module-rtlsdr \
    soapysdr-module-airspy \
    libusb-1.0-0 \
    libusb-1.0-0-dev
```

**Text-to-Speech Only**:
```bash
sudo apt-get install -y espeak libespeak-ng1
```

---

## Verification

After installation, verify that all dependencies are correctly installed:

### Python Version

```bash
python3.11 --version
# Expected: Python 3.11.0 or higher
```

### FFmpeg

```bash
ffmpeg -version
# Expected: ffmpeg version 4.x or 5.x with libavcodec, libavformat
```

### SoapySDR

```bash
SoapySDRUtil --info
# Expected: SoapySDR library version info

# List detected SDR devices
SoapySDRUtil --find
# Expected: List of connected SDR hardware (or empty if none connected)
```

### eSpeak

```bash
espeak --version
# Expected: eSpeak NG version info

# Test synthesis
espeak "This is a test"
# Expected: Audio output of spoken text
```

### Icecast2

```bash
systemctl status icecast2
# Expected: active (running)

# Check listening port
netstat -tuln | grep 8000
# Expected: Icecast listening on port 8000
```

### PostgreSQL

```bash
psql --version
# Expected: psql (PostgreSQL) 14.x or higher

# Check PostGIS extension (in psql session)
psql -U postgres -c "SELECT PostGIS_Version();"
# Expected: PostGIS version string
```

---

## Troubleshooting

### "FFmpeg not found" errors

**Symptom**: Audio streams fail with "ffmpeg not found" or codec errors

**Solution**:
```bash
# Verify ffmpeg is installed
which ffmpeg
ffmpeg -version

# If not found, install
sudo apt-get install ffmpeg

# Verify codecs are available
ffmpeg -codecs | grep -E "mp3|aac|ogg"
```

### SoapySDR Python bindings not found

**Symptom**: `ModuleNotFoundError: No module named 'SoapySDR'`

**Solution**:
```bash
# Install system package (not pip!)
sudo apt-get install python3-soapysdr

# Verify installation
python3 -c "import SoapySDR; print(SoapySDR.getAPIVersion())"
```

**Important**: SoapySDR Python bindings MUST be installed via system packages, not pip. The Dockerfile handles this automatically.

### USB SDR devices not detected

**Symptom**: `SoapySDRUtil --find` shows no devices

**Solution**:
```bash
# Check if device is recognized by kernel
lsusb | grep -i realtek  # For RTL-SDR
lsusb | grep -i airspy   # For Airspy

# Verify driver modules are installed
dpkg -l | grep soapysdr-module

# If missing, install
sudo apt-get install soapysdr-module-rtlsdr soapysdr-module-airspy

# Check permissions (you may need to add user to plugdev group)
sudo usermod -a -G plugdev $USER
# Log out and back in for group changes to take effect
```

### eSpeak synthesis fails

**Symptom**: pyttsx3 initialization fails or produces no audio

**Solution**:
```bash
# Verify espeak is installed
which espeak
espeak --version

# Test directly
espeak "test"

# If no audio, check ALSA/PulseAudio
aplay -l  # List audio devices

# Install missing audio libraries if needed
sudo apt-get install alsa-utils pulseaudio
```

### Icecast configuration issues

**Symptom**: Icecast fails to start or clients cannot connect

**Solution**:
```bash
# Check Icecast configuration
sudo cat /etc/icecast2/icecast.xml

# Check logs
sudo journalctl -u icecast2 -n 50

# Verify port is not in use
sudo netstat -tuln | grep 8000

# Restart service
sudo systemctl restart icecast2
```

See `docs/guides/ICECAST_STREAMING.md` for comprehensive Icecast setup instructions.

### PostgreSQL connection issues

**Symptom**: `psycopg2.OperationalError: could not connect to server`

**Solution**:
```bash
# Verify PostgreSQL is running
sudo systemctl status postgresql

# Check if PostGIS extension is installed
sudo -u postgres psql -c "SELECT * FROM pg_available_extensions WHERE name='postgis';"

# Install PostGIS if missing
sudo apt-get install postgresql-14-postgis-3

# Enable extension in your database
sudo -u postgres psql -d eas_station -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

---

## Docker Users

If you're using the provided Docker containers, all system dependencies are handled automatically:

**Main application** (`Dockerfile`):
- Installs all required and optional dependencies
- Configures SoapySDR Python bindings
- Sets up ffmpeg, espeak, and SDR drivers

**Icecast streaming** (`Dockerfile.icecast`):
- Installs Icecast2 and helper utilities
- Configured for container deployment

**To use Docker** (recommended):
```bash
# Build and run using docker-compose
docker-compose up -d

# All system dependencies are pre-installed in containers
```

No manual system package installation required when using Docker.

---

## License Information

All system packages listed in this document are open-source software. See `dependency_attribution.md` for detailed license information for each package.

---

## Related Documentation

- [dependency_attribution.md](dependency_attribution.md) - Complete dependency licensing information
- [ICECAST_STREAMING.md](../guides/ICECAST_STREAMING.md) - Icecast setup and configuration
- [SDR_QUICKSTART.md](../guides/SDR_QUICKSTART.md) - Software Defined Radio setup
- [audio_hardware.md](../deployment/audio_hardware.md) - USB audio interface configuration

---

**Last Updated**: 2025-11-08
