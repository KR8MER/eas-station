# CLAUDE.md - AI Assistant Guide for EAS Station

> **Purpose:** This document provides comprehensive guidance for AI assistants (like Claude) working on the EAS Station codebase. It contains essential information about project structure, conventions, workflows, and critical requirements.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Critical Information](#critical-information)
3. [Codebase Structure](#codebase-structure)
4. [Technology Stack](#technology-stack)
5. [Development Workflows](#development-workflows)
6. [Key Conventions](#key-conventions)
7. [Common Tasks](#common-tasks)
8. [Testing Requirements](#testing-requirements)
9. [Important Files Reference](#important-files-reference)
10. [Database Models](#database-models)
11. [Security & Compliance](#security--compliance)
12. [AI Assistant Guidelines](#ai-assistant-guidelines)

---

## Project Overview

**EAS Station** is a professional Emergency Alert System (EAS) platform for monitoring, broadcasting, and verifying NOAA and IPAWS alerts. It's a software-defined drop-in replacement for commercial EAS encoder/decoder hardware (which typically cost $5,000-$7,000), built on commodity hardware like Raspberry Pi.

### Key Capabilities
- **Multi-source alert ingestion:** NOAA Weather, IPAWS federal alerts, custom CAP feeds
- **FCC-compliant SAME encoding:** Specific Area Message Encoding per FCC Part 11
- **PostGIS spatial intelligence:** Geographic filtering with county/state/polygon support
- **SDR verification:** Automated broadcast verification with RTL-SDR/Airspy
- **Hardware integration:** GPIO relay control, LED signs, VFD displays, OLED displays, audio outputs
- **Built-in HTTPS:** Automatic SSL/TLS with Let's Encrypt, nginx reverse proxy

### Project Metadata
- **Version:** 2.7.2 (see `/home/user/eas-station/VERSION`)
- **License:** GNU Affero General Public License v3 (AGPL-3.0) / Commercial License (dual-licensed)
- **Author:** KR8MER Amateur Radio Emergency Communications
- **Repository:** https://github.com/KR8MER/eas-station
- **Primary Branch:** `main`
- **Python Version:** 3.11+
- **Database:** PostgreSQL 17 with PostGIS 3.4

---

## Critical Information

### ⚠️ FCC Compliance & Safety

**EXTREMELY IMPORTANT:** This software generates valid EAS SAME headers and attention tones. Unauthorized broadcast violates FCC regulations and can result in substantial fines:

- 2015 iHeartMedia: $1M settlement
- 2014 Multiple Networks: $1.9M settlement

**Before making ANY changes to EAS encoding, broadcasting, or SAME generation:**
1. Understand FCC Part 11 requirements
2. Never remove safety guards or test mode restrictions
3. Always work in shielded test environments
4. Never enable production broadcasts without explicit user authorization

### 🔐 Security Requirements

1. **Never commit secrets** to the repository (.env files, API keys, passwords)
2. **CSRF protection required** on all state-changing requests
3. **Password hashing** must use Werkzeug's secure methods
4. **MFA support** via TOTP must not be weakened
5. **API key authentication** for programmatic access

### 🎨 Frontend UI Requirements (CRITICAL)

**Every backend feature MUST have a frontend UI.** This is a hard requirement:

1. **No backend-only features** - If it doesn't have UI, it doesn't exist for users
2. **Binary choices only** - Use dropdowns/radio buttons/toggles, NEVER free-text inputs for selections
3. **Navigation accessibility** - All pages must be accessible from the navigation menu
4. **Documentation required** - Document UI access path in help files (`/templates/help.html` and `/docs/guides/HELP.md`)

### 📦 Version Management

- **Version file:** `/home/user/eas-station/VERSION`
- **Format:** Semantic versioning (e.g., `2.7.2`)
- **Increment rules:**
  - Bug fixes: +0.0.1
  - New features: +0.1.0
  - Breaking changes: +1.0.0 (document in CHANGELOG)

---

## Codebase Structure

```
/home/user/eas-station/
├── app.py                          # Main Flask application entry point (1,264 lines)
├── wsgi.py                         # WSGI entry for production (Gunicorn)
├── requirements.txt                # Python dependencies
├── pytest.ini                      # Test configuration
├── .env.example                    # Environment configuration template
├── VERSION                         # Current version number
│
├── app_core/                       # Core business logic (11 modules)
│   ├── models.py                   # Database models (1,167 lines, 30+ models)
│   ├── extensions.py               # Flask extensions initialization
│   ├── alerts.py                   # Alert processing logic
│   ├── eas_storage.py              # EAS message storage
│   ├── boundaries.py               # Geographic boundary processing
│   ├── system_health.py            # System monitoring
│   ├── led.py, oled.py, vfd.py     # Display drivers
│   ├── analytics/                  # Analytics subsystem
│   ├── audio/                      # Audio processing
│   ├── auth/                       # Authentication/authorization
│   └── radio/                      # SDR radio management
│
├── app_utils/                      # Utility functions (23 modules, 249+ functions)
│   ├── eas.py                      # EAS/SAME encoding (50KB, CRITICAL)
│   ├── eas_decode.py               # SAME decoder (66KB)
│   ├── event_codes.py              # EAS event code registry
│   ├── fips_codes.py               # FIPS county/state codes (86KB)
│   ├── gpio.py                     # GPIO control (63KB)
│   ├── system.py                   # System utilities (83KB)
│   ├── setup_wizard.py             # First-run setup wizard
│   └── ... (20 more utility modules)
│
├── webapp/                         # Web application routes (234 files)
│   ├── __init__.py                 # Route registration system
│   ├── routes_public.py            # Public routes (dashboard, alerts)
│   ├── routes_admin.py             # Admin panel routes
│   ├── routes_analytics.py         # Analytics dashboard
│   ├── routes_settings_*.py        # Settings pages (audio, radio, etc.)
│   ├── routes_led.py, routes_vfd.py # Display control routes
│   ├── routes_diagnostics.py       # System diagnostics
│   └── ... (60+ route modules)
│
├── templates/                      # Jinja2 HTML templates (60+ files)
│   ├── base.html                   # Base layout with navigation
│   ├── index.html                  # Main dashboard
│   ├── admin.html                  # Admin panel (289KB)
│   ├── system_health.html          # Health monitoring dashboard (162KB)
│   ├── help.html                   # User documentation
│   └── ... (organized by feature)
│
├── static/                         # Frontend assets
│   ├── css/                        # Stylesheets (8 files)
│   │   ├── base.css                # Core styles (23KB)
│   │   ├── design-system.css       # Design tokens
│   │   └── accessibility.css       # A11y enhancements
│   ├── js/                         # JavaScript modules
│   │   ├── core/                   # Core modules (api.js, utils.js, etc.)
│   │   └── ... (feature-specific JS)
│   └── img/                        # Images and logos
│
├── docs/                           # Documentation (100+ Markdown files)
│   ├── INDEX.md                    # Documentation index
│   ├── architecture/               # System architecture docs
│   ├── development/                # Developer guides
│   │   └── AGENTS.md               # AI agent coding guidelines
│   ├── guides/                     # User guides
│   ├── frontend/                   # Frontend documentation
│   └── ... (organized by topic)
│
├── scripts/                        # Utility scripts
│   ├── configure.py                # Configuration helper
│   ├── manual_eas_event.py         # Manual alert generation
│   ├── led_sign_controller.py      # LED sign controller (51KB)
│   ├── screen_manager.py           # Screen rotation manager (43KB)
│   ├── sdr_diagnostics.py          # SDR testing tool
│   └── diagnostics/                # Diagnostic tools
│
├── tests/                          # Test suite (45+ test files)
│   ├── conftest.py                 # Pytest configuration
│   └── test_*.py                   # Unit/integration tests
│
├── poller/                         # Alert polling service
│   └── cap_poller.py               # CAP feed poller (93KB, main logic)
│
├── docker-compose.yml              # Multi-container orchestration
├── Dockerfile                      # Main application container
├── Dockerfile.nginx                # Nginx reverse proxy container
└── Dockerfile.icecast              # Icecast streaming server container
```

---

## Technology Stack

### Backend
- **Language:** Python 3.11
- **Framework:** Flask 3.0.3
- **WSGI Server:** Gunicorn 23.0.0 (production)
- **ORM:** SQLAlchemy 2.0.44 with Flask-SQLAlchemy 3.1.1
- **Database Driver:** psycopg2-binary 2.9.10
- **Spatial:** GeoAlchemy2 0.15.2 (PostGIS integration)
- **Migrations:** Alembic 1.14.0

### Database
- **Primary:** PostgreSQL 17 with PostGIS 3.4 extension
- **Container Image:** postgis/postgis:17-3.4
- **Features:** Spatial queries, geometry storage, JSONB support

### Frontend
- **Architecture:** Server-side rendered (Jinja2 templates)
- **JavaScript:** Vanilla ES6+ (no SPA framework)
- **CSS Framework:** Bootstrap 5.3.0 (CDN)
- **Icons:** Font Awesome 6.4.0 (CDN)
- **Real-time Updates:** Polling-based (setInterval), no WebSockets
- **HTTP Client:** Fetch API
- **CSRF Protection:** Custom middleware with automatic header injection

### Audio & Radio
- **Audio Processing:** pydub 0.25.1, scipy 1.14.1
- **TTS:** pyttsx3 2.90 (offline), Azure Cognitive Services (optional)
- **SDR:** SoapySDR with rtlsdr/airspy drivers
- **Streaming:** Icecast2 (optional)
- **Audio Codec Support:** FFmpeg (system package)

### Hardware Integration
- **GPIO:** gpiozero 2.0.1 (Raspberry Pi)
- **OLED Display:** luma.oled 3.14.0 (SSD1306/SH1106 I2C)
- **VFD Display:** pyserial 3.5 (Noritake GU140x32F-7000B)
- **LED Signs:** TCP/IP network protocol (Alpha protocol)
- **Image Processing:** Pillow 10.4.0

### Geospatial
- **Shapefile Reading:** pyshp 2.3.1
- **Spatial Queries:** PostGIS (ST_Intersects, ST_GeomFromGeoJSON, etc.)
- **Timezone Handling:** pytz 2024.2

### Deployment
- **Containerization:** Docker with Docker Compose
- **Reverse Proxy:** Nginx with automatic SSL/TLS
- **SSL Certificates:** Let's Encrypt (Certbot)
- **Process Monitoring:** Docker healthchecks

---

## Development Workflows

### Initial Setup

#### Docker Development (Recommended)
```bash
# 1. Clone repository
git clone https://github.com/KR8MER/eas-station.git
cd eas-station

# 2. Copy environment template
cp .env.example .env

# 3. Edit .env with local settings (minimum required: SECRET_KEY, POSTGRES_PASSWORD)
nano .env

# 4. Start services
docker compose up -d --build

# 5. Access application
# https://localhost (accept self-signed certificate for dev)
```

#### Local Python Development
```bash
# 1. Python 3.11+ required
python3.11 -m venv venv
source venv/bin/activate

# 2. Install system dependencies (Debian/Ubuntu)
sudo apt-get install libpq-dev ffmpeg espeak libespeak-ng1

# 3. Install Python packages
pip install -r requirements.txt

# 4. Set up PostgreSQL with PostGIS (see docs/guides/SETUP_INSTRUCTIONS.md)

# 5. Configure .env file
cp .env.example .env
# Edit database connection settings

# 6. Run development server
python app.py  # Runs on http://0.0.0.0:5000
```

### Making Changes

#### 1. **Feature Development**
```bash
# 1. Create feature branch
git checkout -b feature/your-feature-name

# 2. Make changes (follow conventions below)

# 3. Test in Docker environment (REQUIRED)
docker compose up -d --build

# 4. Run test suite
docker compose exec app pytest

# 5. Update documentation if needed
# - Update relevant files in /docs/
# - Update /templates/help.html if UI changes
# - Update VERSION file if needed

# 6. Commit changes
git add .
git commit -m "Add feature: description"

# 7. Push to remote
git push -u origin feature/your-feature-name
```

#### 2. **Bug Fixes**
```bash
# 1. Document the bug with screenshot if applicable
# Save to /bugs/descriptive-name.png

# 2. Create fix branch
git checkout -b fix/issue-description

# 3. Make focused changes (one issue at a time)

# 4. Test thoroughly

# 5. Update VERSION file (increment patch version)
echo "2.7.3" > VERSION

# 6. Commit with reference to bug screenshot
git commit -m "Fix: issue description (see /bugs/filename.png)"

# 7. Move screenshot to resolved
mkdir -p /bugs/resolved/
git mv /bugs/filename.png /bugs/resolved/
```

### Git Workflow

#### Branching Strategy
- **Main Branch:** `main` - Production-ready code
- **Feature Branches:** `feature/description` or `claude/description`
- **Bug Fixes:** `fix/description`
- **Documentation:** `docs/description`

#### Commit Message Format
```
<type>: <description>

[optional body]

[optional footer]
```

**Types:**
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `style:` Code style changes (formatting, no logic changes)
- `refactor:` Code refactoring (no functional changes)
- `test:` Adding or updating tests
- `chore:` Maintenance tasks

---

## Key Conventions

### Python Code Style

#### Naming Conventions
```python
# Functions and variables
def snake_case_function():
    local_variable = "value"

# Classes
class PascalCaseClass:
    pass

# Constants
UPPER_SNAKE_CASE = "constant"

# Private methods/variables
def _private_function():
    pass
```

#### Database Model Conventions
```python
class ExampleModel(db.Model):
    __tablename__ = 'example_table'  # snake_case, descriptive

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())

    # Foreign keys: {table}_id
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Spatial fields: named 'geom'
    geom = db.Column(Geometry('POLYGON', srid=4326))

    # JSON storage: use JSONB
    metadata = db.Column(db.JSON)
```

#### API Response Format
```python
# Success
return jsonify({
    "success": True,
    "data": {...},
    "message": "Operation completed successfully"
}), 200

# Error
return jsonify({
    "success": False,
    "error": "Error message",
    "details": {...}
}), 400
```

### Frontend Conventions

#### JavaScript
```javascript
// Function names: camelCase
function updateDashboard() {
    // ...
}

// Constants: UPPER_SNAKE_CASE
const API_ENDPOINT = '/api/alerts';

// Global functions available in window scope
window.showToast = function(message, type) {
    // ...
};
```

#### CSRF Protection (REQUIRED)
```javascript
// All POST/PUT/DELETE requests must include CSRF token
fetch('/api/endpoint', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': window.CSRF_TOKEN  // Required!
    },
    body: JSON.stringify(data)
});
```

#### Polling Pattern (No WebSockets)
```javascript
// Regular interval polling
setInterval(updateFunction, intervalMs);

// Standard intervals:
// - Health checks: 5000ms (5s)
// - Metrics: 1000ms (1s)
// - Device monitoring: 10000ms (10s)
```

### File Naming Conventions

#### Python Files
- **Route modules:** `routes_*.py` (e.g., `routes_admin.py`)
- **Test files:** `test_*.py` (e.g., `test_alerts.py`)
- **Utility modules:** `snake_case.py` (e.g., `event_codes.py`)
- **Old files:** Suffix with `_old` (NEVER `_new`)

#### Templates
- **HTML files:** `snake_case.html` (e.g., `alert_detail.html`)
- **Partials:** `_partial_name.html` (e.g., `_alert_card.html`)

#### CSS/JavaScript
- **CSS files:** `kebab-case.css` (e.g., `design-system.css`)
- **JS modules:** `kebab-case.js` (e.g., `audio-monitoring.js`)

### Route Organization

Routes are organized by feature in separate modules and registered via centralized system:

```python
# webapp/routes_example.py
def register_routes(app, logger):
    """Register example routes."""

    @app.route('/example')
    def example_route():
        return render_template('example.html')
```

**No Flask Blueprints** - Uses direct route registration for simplicity.

### Template Structure

#### Base Template Pattern
```html
<!-- templates/base.html -->
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}EAS Station{% endblock %}</title>
    <!-- Common head elements -->
</head>
<body>
    {% include 'partials/_navigation.html' %}

    <div class="container">
        {% block content %}{% endblock %}
    </div>

    {% include 'partials/_footer.html' %}

    <!-- Common scripts -->
    <script>
        window.CSRF_TOKEN = "{{ csrf_token() }}";
    </script>
    {% block scripts %}{% endblock %}
</body>
</html>
```

#### Child Template Pattern
```html
<!-- templates/feature.html -->
{% extends "base.html" %}

{% block title %}Feature Name - EAS Station{% endblock %}

{% block content %}
    <h1>Feature Name</h1>
    <!-- Feature content -->
{% endblock %}

{% block scripts %}
    <script src="{{ url_for('static', filename='js/feature.js') }}"></script>
{% endblock %}
```

---

## Common Tasks

### Adding a New Route

```python
# 1. Create route module: webapp/routes_myfeature.py
from flask import render_template, request, jsonify

def register_routes(app, logger):
    """Register my feature routes."""

    @app.route('/myfeature')
    def myfeature_index():
        """Display my feature page."""
        return render_template('myfeature.html')

    @app.route('/api/myfeature', methods=['POST'])
    def api_myfeature():
        """API endpoint for my feature."""
        data = request.get_json()
        # Process data...
        return jsonify({
            "success": True,
            "data": result
        })

# 2. Create template: templates/myfeature.html
# 3. Add navigation link in templates/base.html or templates/partials/_navigation.html
# 4. Test thoroughly
```

### Adding a Database Model

```python
# app_core/models.py
from app_core.extensions import db
from sqlalchemy import func

class MyModel(db.Model):
    """Description of the model."""
    __tablename__ = 'my_models'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
```

### Creating a Database Migration

```bash
# 1. Make changes to models in app_core/models.py

# 2. Generate migration
docker compose exec app alembic revision --autogenerate -m "Description of changes"

# 3. Review migration file in app_core/migrations/versions/

# 4. Apply migration
docker compose exec app alembic upgrade head

# 5. Rollback if needed
docker compose exec app alembic downgrade -1
```

### Adding a New Configuration Option

```bash
# 1. Add to .env.example with documentation
NEW_FEATURE_ENABLED=false  # Enable new feature (true/false)

# 2. Add to docker-compose.yml environment section
environment:
  - NEW_FEATURE_ENABLED=${NEW_FEATURE_ENABLED:-false}

# 3. Access in Python code
import os
new_feature_enabled = os.environ.get('NEW_FEATURE_ENABLED', 'false').lower() == 'true'

# 4. Add to setup wizard if user-configurable (webapp/routes_setup.py)

# 5. Document in docs/guides/HELP.md
```

### Adding a JavaScript Module

```javascript
// static/js/mymodule.js
(function() {
    'use strict';

    // Module-scoped variables
    let moduleState = {};

    // Private functions
    function privateFunction() {
        // ...
    }

    // Public API
    window.MyModule = {
        init: function() {
            // Initialize module
        },

        publicMethod: function(param) {
            // Public method
        }
    };

    // Auto-initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', window.MyModule.init);
    } else {
        window.MyModule.init();
    }
})();
```

### Adding Documentation

```markdown
# 1. Create documentation file: docs/category/TOPIC.md

# Topic Name

## Overview
Brief description of the topic.

## Usage
How to use this feature.

## Examples
Practical examples.

## Troubleshooting
Common issues and solutions.

## See Also
- [Related Topic 1](RELATED1.md)
- [Related Topic 2](RELATED2.md)

# 2. Add to docs/INDEX.md table of contents

# 3. Add link in templates/help.html if user-facing

# 4. Update mkdocs.yml nav section if applicable
```

---

## Testing Requirements

### Test Categories (Markers)

```python
import pytest

# Unit tests (fast, no external dependencies)
@pytest.mark.unit
def test_function():
    assert function() == expected

# Integration tests (mock external services)
@pytest.mark.integration
def test_integration():
    # Test with mocked services
    pass

# Functional tests (complete workflows)
@pytest.mark.functional
def test_workflow():
    # Test complete workflow
    pass

# Slow tests (long-running)
@pytest.mark.slow
def test_slow_operation():
    pass

# Hardware tests (require physical devices)
@pytest.mark.gpio
@pytest.mark.radio
@pytest.mark.audio
def test_hardware():
    # Only runs if hardware available
    pass
```

### Running Tests

```bash
# All tests
pytest

# Specific category
pytest -m unit
pytest -m integration

# Exclude slow tests
pytest -m "not slow"

# Exclude hardware tests (for CI/Docker)
pytest -m "not gpio and not radio and not audio"

# With coverage
pytest --cov=app_core --cov=app_utils --cov=webapp

# Specific file
pytest tests/test_alerts.py

# Specific test
pytest tests/test_alerts.py::test_function_name
```

### Writing Tests

```python
# tests/test_myfeature.py
import pytest
from app_core.models import MyModel
from app_core.extensions import db

@pytest.mark.unit
def test_model_creation():
    """Test creating a model instance."""
    model = MyModel(name="Test")
    assert model.name == "Test"

@pytest.mark.integration
def test_api_endpoint(client):
    """Test API endpoint."""
    response = client.post('/api/myfeature', json={'data': 'value'})
    assert response.status_code == 200
    assert response.json['success'] is True

@pytest.fixture
def sample_model(app):
    """Create a sample model for testing."""
    with app.app_context():
        model = MyModel(name="Sample")
        db.session.add(model)
        db.session.commit()
        yield model
        db.session.delete(model)
        db.session.commit()
```

### Pre-Commit Checklist

- [ ] All tests pass: `pytest`
- [ ] Code follows conventions (snake_case, PascalCase, etc.)
- [ ] CSRF protection on state-changing routes
- [ ] Frontend UI exists for new backend features
- [ ] Documentation updated if needed
- [ ] VERSION file updated if needed
- [ ] No secrets committed (.env, API keys, passwords)
- [ ] Tested in Docker environment
- [ ] No console errors in browser
- [ ] Mobile responsive (if UI changes)

---

## Important Files Reference

### Entry Points

| File | Purpose | Lines |
|------|---------|-------|
| `app.py` | Main Flask application entry point | 1,264 |
| `wsgi.py` | WSGI entry for production (Gunicorn) | 18 |
| `poller/cap_poller.py` | Alert polling service (separate container) | 93KB |

### Core Logic

| File | Purpose | Size/Lines |
|------|---------|------------|
| `app_core/models.py` | Database models (30+ models) | 1,167 lines |
| `app_core/extensions.py` | Flask extensions initialization | Small |
| `app_core/alerts.py` | Alert processing logic | Medium |
| `app_core/eas_storage.py` | EAS message storage | Medium |
| `app_core/system_health.py` | System monitoring | Medium |

### Critical Utilities

| File | Purpose | Size |
|------|---------|------|
| `app_utils/eas.py` | **EAS/SAME encoding (CRITICAL)** | 50KB |
| `app_utils/eas_decode.py` | SAME decoder | 66KB |
| `app_utils/event_codes.py` | EAS event code registry | Medium |
| `app_utils/fips_codes.py` | FIPS county/state codes | 86KB |
| `app_utils/gpio.py` | GPIO control | 63KB |
| `app_utils/system.py` | System utilities | 83KB |

### Route Modules

| File | Purpose |
|------|---------|
| `webapp/routes_public.py` | Public routes (dashboard, alerts) |
| `webapp/routes_admin.py` | Admin panel routes |
| `webapp/routes_settings_*.py` | Settings pages (audio, radio, etc.) |
| `webapp/routes_diagnostics.py` | System diagnostics |
| `webapp/routes_led.py` | LED sign control |
| `webapp/routes_vfd.py` | VFD display control |

### Key Templates

| File | Purpose | Size |
|------|---------|------|
| `templates/base.html` | Base layout with navigation | Medium |
| `templates/index.html` | Main dashboard | Medium |
| `templates/admin.html` | Admin panel | 289KB |
| `templates/system_health.html` | Health monitoring | 162KB |
| `templates/help.html` | User documentation | Large |

### Configuration

| File | Purpose |
|------|---------|
| `.env.example` | Environment configuration template (206 lines) |
| `docker-compose.yml` | Multi-container orchestration |
| `nginx.conf` | Nginx reverse proxy configuration |
| `mkdocs.yml` | Documentation site configuration |
| `pytest.ini` | Test configuration |
| `requirements.txt` | Python dependencies (83 lines) |

### Documentation

| File | Purpose |
|------|---------|
| `docs/INDEX.md` | Documentation index |
| `docs/development/AGENTS.md` | **AI agent coding guidelines** |
| `docs/architecture/SYSTEM_ARCHITECTURE.md` | System architecture |
| `docs/guides/HELP.md` | User guide |
| `docs/guides/SETUP_INSTRUCTIONS.md` | Setup guide |

---

## Database Models

### Core Alert Models
- **CAPAlert:** CAP alert storage with PostGIS geometry
- **NWSZone:** NOAA forecast zone reference data
- **Boundary:** Geographic boundary polygons

### User & Security Models
- **AdminUser:** User accounts with password hashing
- **Role:** RBAC role definitions
- **Permission:** Granular permissions
- **UserRole:** User-role associations
- **RolePermission:** Role-permission associations
- **MFAToken:** Multi-factor authentication tokens
- **APIKey:** API authentication keys

### Hardware Models
- **LEDMessage:** LED sign message queue
- **LEDSignStatus:** LED sign connection status
- **VFDDisplay:** VFD display content
- **VFDStatus:** VFD connection status
- **DisplayScreen:** Configurable display screens
- **ScreenRotation:** Screen rotation configurations

### System Models
- **SystemLog:** Application logging
- **EASMessage:** Generated EAS broadcasts
- **ManualEASEvent:** Manual alert generation
- **AudioSource:** Audio monitoring sources
- **RadioReceiver:** SDR receiver configurations
- **StreamProfile:** Icecast stream profiles

### Spatial Queries

PostGIS is used extensively for geographic filtering:

```python
# Example: Find alerts intersecting a boundary
from geoalchemy2 import func as geo_func

alerts = CAPAlert.query.filter(
    geo_func.ST_Intersects(
        CAPAlert.geom,
        boundary.geom
    )
).all()
```

---

## Security & Compliance

### FCC Part 11 Compliance

**Critical Files:**
- `app_utils/eas.py` - SAME encoding implementation
- `app_utils/event_codes.py` - Event code registry
- `docs/compliance/` - Compliance documentation

**Requirements:**
1. Valid SAME header generation per FCC Part 11
2. Attention tone generation (853 Hz and 960 Hz, both-tones FSK)
3. Three-burst header transmission
4. End-of-message (EOM) codes
5. Proper event code usage
6. Originator code compliance (EAN, RWT, etc.)

**Safety Guards:**
- Test mode indicators
- Broadcast enable flags (`EAS_BROADCAST_ENABLED`)
- Logging and audit trails
- Geographic restriction capabilities

### Security Best Practices

1. **Password Handling:**
   ```python
   from werkzeug.security import generate_password_hash, check_password_hash

   # Hash password
   hashed = generate_password_hash(password)

   # Verify password
   if check_password_hash(hashed, password):
       # Authenticated
   ```

2. **CSRF Protection:**
   ```python
   # In templates
   <form method="POST">
       <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
       <!-- Form fields -->
   </form>

   # In JavaScript
   fetch('/api/endpoint', {
       headers: {
           'X-CSRF-Token': window.CSRF_TOKEN
       }
   });
   ```

3. **API Key Authentication:**
   ```python
   from functools import wraps

   def require_api_key(f):
       @wraps(f)
       def decorated_function(*args, **kwargs):
           api_key = request.headers.get('X-API-Key')
           if not api_key or not verify_api_key(api_key):
               return jsonify({'error': 'Invalid API key'}), 401
           return f(*args, **kwargs)
       return decorated_function
   ```

4. **Input Validation:**
   ```python
   # Always validate and sanitize user input
   from flask import escape

   user_input = escape(request.form.get('input'))
   ```

### Secrets Management

**Never commit:**
- `.env` files (use `.env.example` as template)
- API keys, passwords, tokens
- Database credentials
- SSL certificates/private keys

**Use environment variables:**
```python
import os

secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    raise ValueError("SECRET_KEY not set")
```

---

## AI Assistant Guidelines

### When Working on This Codebase

#### 1. **Always Read Before Writing**
- Use `Read` tool to view files before editing
- Understand context and existing patterns
- Check related files (templates, routes, models)

#### 2. **Follow the Frontend UI Rule**
- Every backend feature MUST have a frontend UI
- No backend-only features
- Update navigation menus when adding pages
- Document UI access path

#### 3. **Respect FCC Compliance**
- Never modify EAS encoding without understanding FCC Part 11
- Maintain safety guards and test mode restrictions
- Consult `docs/compliance/` before changing broadcast logic

#### 4. **Test in Docker**
- Always test changes in Docker environment
- Use `docker compose up -d --build`
- Check logs: `docker compose logs -f app`

#### 5. **Update Documentation**
- Update relevant docs in `/docs/`
- Update `/templates/help.html` for user-facing changes
- Update `VERSION` file for releases

#### 6. **Security First**
- CSRF protection on all state-changing routes
- Never commit secrets
- Use proper password hashing
- Validate all user input

#### 7. **Version Control**
- Increment `VERSION` file appropriately
- Write clear commit messages
- Reference bug screenshots in commits
- Move resolved bugs to `/bugs/resolved/`

#### 8. **Code Quality**
- Follow naming conventions (snake_case, PascalCase)
- Add docstrings to functions and classes
- Use type hints where appropriate
- Keep functions focused and small

#### 9. **Database Changes**
- Create migrations for model changes
- Test migrations before committing
- Never delete migrations
- Use `alembic` for all schema changes

#### 10. **Frontend Changes**
- Test in multiple browsers
- Ensure mobile responsive
- Check accessibility
- No console errors

### Common Pitfalls to Avoid

1. **Don't create backend-only features** - Always include UI
2. **Don't skip CSRF protection** - Required on all POST/PUT/DELETE
3. **Don't commit `.env` files** - Use `.env.example` as template
4. **Don't modify EAS encoding without understanding FCC rules**
5. **Don't use WebSockets** - This project uses polling
6. **Don't create Flask Blueprints** - Use direct route registration
7. **Don't skip Docker testing** - Always test in Docker
8. **Don't forget to update VERSION** - Increment for releases
9. **Don't use free-text for binary choices** - Use dropdowns/toggles
10. **Don't skip documentation updates** - Keep docs in sync

### Useful Commands Reference

```bash
# Docker
docker compose up -d --build              # Build and start
docker compose logs -f app                # View app logs
docker compose exec app bash              # Shell into container
docker compose restart app                # Restart app
docker compose down                       # Stop all services

# Database
docker compose exec app alembic upgrade head    # Apply migrations
docker compose exec app alembic downgrade -1    # Rollback migration
docker compose exec app python -c "from app import *; db.create_all()"  # Create tables

# Testing
docker compose exec app pytest                  # Run all tests
docker compose exec app pytest -m unit          # Run unit tests
docker compose exec app pytest -m "not slow"    # Skip slow tests

# Shell access
docker compose exec app python              # Python REPL
docker compose exec app flask shell         # Flask shell

# Logs
docker compose logs -f app                  # App logs
docker compose logs -f nginx                # Nginx logs
docker compose logs -f noaa-poller          # Poller logs
```

### Quick Reference: File Locations

```bash
# Need to add a route? → webapp/routes_*.py
# Need to add a model? → app_core/models.py
# Need to add a template? → templates/
# Need to add CSS? → static/css/
# Need to add JavaScript? → static/js/
# Need to add a utility function? → app_utils/
# Need to add documentation? → docs/
# Need to add a test? → tests/
# Need to add a script? → scripts/
# Need to update help page? → templates/help.html + docs/guides/HELP.md
```

---

## Summary

EAS Station is a mature, production-oriented emergency alert system with:
- **Complex hardware integration** (GPIO, displays, SDR)
- **Spatial intelligence** (PostGIS)
- **FCC compliance requirements** (Part 11)
- **Docker-first deployment** (multi-container)
- **Extensive documentation** (100+ files)
- **Comprehensive testing** (45+ test files)

**Key Principles:**
1. **Safety first** - FCC compliance is critical
2. **UI required** - Every feature needs a frontend
3. **Security always** - CSRF, password hashing, input validation
4. **Test thoroughly** - Docker environment, all markers
5. **Document everything** - Keep docs in sync with code

**When in doubt:**
- Check existing patterns in similar files
- Read documentation in `/docs/`
- Test in Docker environment
- Ask for clarification rather than assuming

---

**Last Updated:** 2025-11-16
**Version:** 2.7.2
**Maintained by:** KR8MER Amateur Radio Emergency Communications

For questions or clarifications, consult:
- `/docs/development/AGENTS.md` - AI agent coding guidelines
- `/docs/architecture/SYSTEM_ARCHITECTURE.md` - System architecture
- `/docs/guides/HELP.md` - User guide
- `/README.md` - Project overview
