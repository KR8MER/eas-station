# EAS Station Repository Documentation

## 📌 Overview

**Project**: EAS Station  
**Version**: 2.12.21  
**License**: AGPL v3 / Commercial  
**Language**: Python 3.11  
**Purpose**: Professional Emergency Alert System (EAS) platform for monitoring, broadcasting, and verifying NOAA and IPAWS alerts

---

## 🎯 Project Summary

EAS Station is a software-defined drop-in replacement for commercial EAS encoder/decoder hardware. It provides comprehensive alert processing with FCC-compliant SAME encoding, multi-source aggregation, PostGIS spatial intelligence, SDR verification, and integrated LED signage.

**⚠️ Status**: Laboratory/Research Use Only - Not FCC-certified for production

---

## 🏗️ Directory Structure

### Core Application Modules

| Directory | Purpose |
|-----------|---------|
| **app_core/** | Core application logic and business layers |
| **app_utils/** | Utility modules for EAS processing and system operations |
| **webapp/** | Flask web application routes and business logic |
| **fastapi_app/** | FastAPI endpoints and schemas (modern API layer) |

### Key Subdirectories

| Path | Purpose |
|------|---------|
| **poller/** | CAP alert polling service |
| **scripts/** | Utility scripts for diagnostics, setup, and operations |
| **tools/** | System management tools (backup, restore, SDR diagnostics) |
| **tests/** | Comprehensive test suite (100+ test files) |
| **docs/** | Complete documentation (architecture, guides, API reference) |
| **templates/** | Jinja2 HTML templates for web UI |
| **static/** | CSS, JavaScript, images, and vendor libraries |
| **examples/** | Docker Compose examples and deployment configurations |
| **samples/** | Sample audio files for testing EAS detection |

---

## 📦 Technology Stack

### Backend
- **Framework**: Flask 3.0.3 with Flask-SocketIO
- **Database**: PostgreSQL 17 + PostGIS 3.4 (spatial queries)
- **ORM**: SQLAlchemy 2.0 + GeoAlchemy2 (PostGIS integration)
- **Caching**: Redis 7 + Flask-Caching
- **Server**: Gunicorn + Gevent (async worker)
- **Async HTTP**: HTTPX with connection pooling

### Audio & SDR
- **Audio Processing**: pydub, scipy, numpy
- **Speech Synthesis**: pyttsx3 (offline TTS)
- **SDR Support**: SoapySDR (RTL-SDR, Airspy)
- **Serialization**: PySerial (for VFD displays)

### Hardware Integration
- **GPIO Control**: gpiozero (Raspberry Pi)
- **OLED Display**: luma.oled (SSD1306/SH1106)
- **VFD Display**: Noritake GU140x32F-7000B

### Web UI
- **Frontend**: Bootstrap 5
- **WebSockets**: Flask-SocketIO + Socket.IO
- **Real-time Updates**: WebSocket push notifications

### Development & Testing
- **Testing**: pytest + pytest-asyncio
- **Code Quality**: Extensive test suite (100+ test files)
- **Documentation**: MkDocs with markdown

---

## 🔑 Key Features

| Feature | Implementation |
|---------|-----------------|
| **Multi-Source Ingestion** | NOAA Weather, IPAWS, custom CAP feeds |
| **FCC-Compliant SAME** | Specific Area Message Encoding per FCC Part 11 |
| **Geographic Intelligence** | PostGIS polygon/county/state filtering |
| **SDR Verification** | RTL-SDR/Airspy broadcast verification |
| **HTTPS/SSL** | Automatic Let's Encrypt integration |
| **Hardware Control** | GPIO relays, LED signs, multiple audio outputs |
| **Real-time Dashboard** | WebSocket push notifications |
| **API Access** | REST API with X-API-Key authentication |

---

## 📂 Project Structure Details

### Application Core (`app_core/`)
Handles business logic and data models:
- `models.py` - Database models (alerts, audio sources, zones)
- `eas_storage.py` - Alert storage and retrieval
- `eas_processing.py` - EAS alert processing pipeline
- `alerts.py` - Alert notification logic
- `redis_client.py` - Redis connection pooling
- `oled.py` / `vfd.py` - Display drivers
- `led.py` - LED signage control
- `websocket_push.py` - Real-time WebSocket updates
- `analytics/`, `audio/`, `auth/`, `radio/` - Feature modules

### Utilities (`app_utils/`)
Core algorithms and utilities:
- `eas_decode.py` - EAS SAME header decoding
- `eas.py` - EAS alert processing
- `eas_tone_detection.py` - Tone detection algorithms
- `eas_tts.py` - Text-to-speech synthesis
- `gpio.py` - GPIO pin management
- `system.py` - System utilities
- `setup_wizard.py` - Configuration wizard
- `fips_codes.py` - FIPS code database (88.56 KB)

### Web Application (`webapp/`)
Flask routes organized by feature:
- `routes_*.py` - Feature-specific route handlers
- `admin/` - Administration interface routes
- `eas/` - EAS-specific routes
- `routes/` - Grouped route modules

### Web Interface (`templates/`)
Jinja2 templates (~30 HTML templates):
- `admin.html` - Administration dashboard (336 KB)
- `audio_monitoring.html` - Audio source monitoring
- `led_control.html` - LED display control
- `system_health.html` - System status monitoring
- Various feature-specific templates

### Test Suite (`tests/`)
Comprehensive test coverage:
- **Unit tests**: Component-level functionality
- **Integration tests**: Service-to-service interactions
- **Audio tests**: Audio pipeline and detection
- **Hardware tests**: GPIO, OLED, VFD control
- **API tests**: WebSocket, REST endpoints
- Sample data included in `test_data/` directory

---

## 🚀 Deployment & Configuration

### Docker Support
- Multi-container architecture (web, audio, database)
- Multiple docker-compose configurations:
  - `docker-compose.yml` - Standard deployment
  - `docker-compose.separated.yml` - Service separation
  - `docker-compose.pi.yml` - Raspberry Pi optimization
  - `docker-compose.icecast.yml` - Icecast streaming

### Environment Configuration
- `.env.example` - Template with all configuration options (15.24 KB)
- `stack.env.example` - Docker stack configuration
- Automated Let's Encrypt SSL certificate provisioning

### Database
- PostgreSQL 17 with PostGIS 3.4
- Alembic migrations for schema management
- PostGIS spatial queries for geographic filtering

---

## 📊 Codebase Statistics

- **Python Modules**: 100+ files across core, utilities, and application
- **Test Files**: 50+ comprehensive test suites
- **HTML Templates**: 30+ Jinja2 templates
- **Documentation Files**: Extensive markdown documentation in `docs/`
- **Lines of Code**: Major files range from 1-60+ KB

### Largest Components
- `fips_codes.py` - 88.56 KB (FIPS code reference database)
- `eas.py` - 64.75 KB (Core EAS processing)
- `system.py` - 85.83 KB (System utilities)
- `admin.html` - 336 KB (Admin dashboard UI)

---

## 🔄 Service Architecture

```
Alert Sources (NOAA/IPAWS)
    ↓
Poller Service (cap_poller.py)
    ↓
PostgreSQL + PostGIS (spatial storage)
    ↓
├── Web Service (Flask) → Web UI
├── Audio Service (SAME Encoder) → Transmission
└── SDR Service (Verification) → RTL-SDR/Airspy
```

---

## 🛠️ Development Workflow

### Testing
- Framework: pytest with async support
- Run tests: `pytest` or `python -m pytest`
- Coverage: 100+ test files with various categories

### Configuration Management
- Environment variables in `.env`
- Alembic migrations for database schema
- Logging and debugging via diagnostic scripts

### Common Tasks
- **Setup wizard**: `python app_utils/setup_wizard.py`
- **Manual alert trigger**: `scripts/manual_eas_event.py`
- **Self-test**: `scripts/run_alert_self_test.py`
- **SDR diagnostics**: `scripts/sdr_diagnostics.py`

---

## 📚 Documentation

Comprehensive documentation available in `docs/` directory:
- **Architecture**: System design and data flow
- **Guides**: Setup, deployment, user, admin
- **Hardware**: SDR setup, audio configuration
- **API**: Endpoint reference and JavaScript SDK
- **Development**: Contributing guidelines, agent protocol
- **Troubleshooting**: Diagnostic tools and runbooks
- **Policies**: Security, privacy, terms

---

## 🔐 Security & Compliance

- **HTTPS/TLS**: Automatic SSL with Let's Encrypt
- **Multi-Factor Authentication**: TOTP-based MFA
- **API Authentication**: X-API-Key header validation
- **Database Security**: PostgreSQL with authentication
- **FCC Compliance**: Laboratory use only (not FCC-certified)

---

## 🎯 Key Statistics

| Metric | Value |
|--------|-------|
| **Version** | 2.12.21 |
| **Python Version** | 3.11+ |
| **Database** | PostgreSQL 17 + PostGIS 3.4 |
| **Main Framework** | Flask 3.0.3 |
| **Docker Compose** | V2 (Docker Engine 24+) |
| **Supported Hardware** | Raspberry Pi 5, RTL-SDR, Airspy, GPIO HATs |
| **Event Codes Supported** | 67 FCC codes |
| **License** | AGPL v3 / Commercial |

---

## 📖 Getting Started

1. **Clone Repository**
   ```bash
   git clone https://github.com/KR8MER/eas-station.git
   cd eas-station
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Deploy with Docker**
   ```bash
   sudo docker compose up -d --build
   ```

4. **Access Web Interface**
   - Open https://localhost in browser
   - Accept self-signed certificate (for local testing)

---

## 🤝 Contributing

- Contributing Guide: [docs/process/CONTRIBUTING](docs/process/CONTRIBUTING)
- Code Standards: [docs/development/AGENTS](docs/development/AGENTS)
- Development Setup: [docs/development/AGENTS](docs/development/AGENTS)

---

## 📞 Support Resources

- **Documentation**: [Complete Index](docs/INDEX)
- **Troubleshooting**: [scripts/diagnostics/](scripts/diagnostics/)
- **GitHub Issues**: Issue tracker
- **GitHub Discussions**: Community forum

---

## ⚖️ Legal Notice

EAS Station is experimental software for research and development purposes only. It is **not FCC-certified** and must only be used in controlled test environments. Never use for production emergency alerting. See LICENSE and LICENSE-COMMERCIAL for full legal terms.

---

*Generated from EAS Station repository structure*  
*Last updated: November 2025*
