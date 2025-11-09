# EAS Station - Function Tree Index & Quick Start

**Generated:** 2025-11-06  
**Main Document:** [`FUNCTION_TREE.md`](/FUNCTION_TREE.md) (1,211 lines)  
**Summary:** [`FUNCTION_TREE_SUMMARY.txt`](/FUNCTION_TREE_SUMMARY.txt) (147 lines)

---

## Quick Navigation Guide

### For Different User Types

**👨‍💻 Developers Adding Features**
1. Read the **Module Dependency Graph** (section near end)
2. Locate your module in **FUNCTION_TREE.md**
3. Find related classes/functions by searching the document
4. Check **API Routes** section for endpoint patterns

**🔍 Code Reviewers**
1. Use **RBAC & Security Features** sections
2. Check **Database Schema Overview**
3. Review function signatures in relevant modules
4. Verify error handling via class methods

**🤖 AI Agents/LLMs**
1. Search for specific function by name (Ctrl+F)
2. Find all functions in a module (grep module section)
3. Understand data flow through dependency graph
4. Identify related components by subsystem

**📊 Project Managers**
1. Review **Statistics** in summary
2. Check **Architecture Overview**
3. Understand **Key Components** table
4. See **Security Features** implemented

---

## Direct Links to Major Sections

### Data & Models
- [Core Models & Data Layer](#core-models--data-layer) - 24 database tables
- [Database Schema Overview](#database-schema-overview) - Complete schema
- [Configuration & Environment Variables](#configuration--environment-variables) - All config vars

### Authentication & Access
- [Authentication & RBAC](#authentication--rbac) - User management
- [Security Features](#security-features) - Protection mechanisms

### Processing & Control
- [Audio System](#audio-system) - Audio capture & processing
- [EAS/SAME Processing](#eassame-processing) - Alert encoding
- [GPIO & Relay Control](#gpio--relay-control) - Hardware control
- [Radio Management](#radio-management) - SDR receivers

### Web & API
- [Web API Routes](#web-api-routes) - Public API endpoints
- [Admin Interface Routes](#admin-interface-routes) - Admin API endpoints

### Analytics & Monitoring
- [Analytics & Monitoring](#analytics--monitoring) - Metrics & anomalies
- [System Health Monitoring](#system-health-systemhealthpy) - Health tracking

### Displays
- [LED/VFD Display Control](#ledvfd-display-control) - Hardware interfaces

### Utilities
- [Utilities & Helpers](#utilities--helpers) - Formatting, conversion, etc.

---

## Common Tasks & Where to Find Info

### Task: Add a New API Endpoint

**Search these sections:**
1. `/admin/` modules in webapp for pattern
2. `register_*_routes()` functions
3. Flask route decorators (@app.route)
4. Line numbers for implementation location

**Example:** Find `/api/alerts/<id>/geometry` implementation
- File: `/home/user/eas-station/webapp/admin/api.py`
- Line: 52
- Look for Flask route decorator pattern

### Task: Understand RBAC System

**Read sections:**
1. Authentication & RBAC
2. Role definitions (line 93-98 in roles.py)
3. Permission definitions (line 100-137)
4. Default role permissions (line 140-198)
5. Decorator patterns (lines 235-314)

### Task: Add Audio Source Type

**Navigate to:**
1. Audio System section
2. `AudioSourceType` enum (line 26 in ingest.py)
3. Concrete adapters section (sources.py)
4. `create_audio_source()` factory (line 652)

### Task: Add Database Model

**Steps:**
1. Go to Core Models section
2. Review existing models for pattern
3. Check `extensions.py` for db instance
4. Look at migration files for schema changes

### Task: Create New Alert Type

**Find:**
1. EAS/SAME Processing section
2. `EVENT_CODE_REGISTRY` in event_codes.py
3. `build_same_header()` function (line 387)
4. Event code resolution functions

### Task: Modify Display Hardware

**Check:**
1. LED/VFD Display Control section
2. `led_controller` and `vfd_controller` globals
3. Model classes: `LEDMessage`, `VFDDisplay`
4. Route handlers in routes_led.py, routes_vfd.py

---

## Module File Structure

```
app_core/
├── models.py                    ← Database models
├── extensions.py                ← db instance
├── alerts.py                    ← Alert processing
├── boundaries.py                ← Geographic boundaries
├── location.py                  ← Location settings
├── eas_storage.py              ← EAS file management
├── system_health.py            ← Health monitoring
├── poller_debug.py             ← Polling debug
├── led.py                       ← LED interface
├── vfd.py                       ← VFD interface
├── auth/
│   ├── __init__.py
│   ├── roles.py                ← RBAC system
│   ├── mfa.py                  ← MFA/TOTP
│   └── audit.py                ← Audit logging
├── audio/
│   ├── __init__.py
│   ├── ingest.py              ← Audio source abstraction
│   ├── sources.py             ← Concrete adapters
│   ├── metering.py            ← Audio metering
│   ├── output_service.py      ← Playback control
│   └── playout_queue.py       ← Audio queue
├── radio/
│   ├── __init__.py
│   ├── manager.py             ← Receiver manager
│   ├── drivers.py             ← SDR drivers
│   ├── discovery.py           ← Hardware discovery
│   └── schema.py              ← Database schema
├── analytics/
│   ├── __init__.py
│   ├── models.py              ← Analytics data models
│   ├── aggregator.py          ← Metrics aggregation
│   ├── anomaly_detector.py    ← Anomaly detection
│   ├── trend_analyzer.py      ← Trend analysis
│   └── scheduler.py           ← Job scheduling
└── migrations/
    └── versions/              ← Database migrations

app_utils/
├── eas.py                       ← EAS generation
├── eas_decode.py               ← EAS decoding
├── eas_fsk.py                  ← FSK modulation
├── eas_tts.py                  ← Text-to-speech
├── gpio.py                      ← GPIO control
├── event_codes.py              ← Event code database
├── fips_codes.py               ← FIPS code lookups
├── zone_catalog.py             ← Zone database
├── time.py                      ← Timezone utilities
├── formatting.py               ← Output formatting
├── location_settings.py         ← Location config
├── alert_sources.py            ← Source tracking
├── export.py                    ← Data export
├── setup_wizard.py             ← Setup wizard
├── versioning.py               ← Version info
└── system.py                    ← System utilities

webapp/
├── __init__.py                  ← Route registration
├── routes_public.py            ← Public pages
├── routes_analytics.py         ← Analytics API
├── routes_debug.py             ← Debug endpoints
├── routes_exports.py           ← Export endpoints
├── routes_led.py               ← LED routes
├── routes_monitoring.py        ← Monitoring endpoints
├── routes_security.py          ← RBAC/MFA endpoints
├── routes_settings_audio.py    ← Audio settings
├── routes_settings_radio.py    ← Radio settings
├── routes_setup.py             ← Setup wizard
├── routes_vfd.py               ← VFD routes
├── routes_screens.py           ← Screen management
├── template_helpers.py         ← Template utilities
├── documentation.py            ← Documentation routes
├── admin/
│   ├── __init__.py
│   ├── api.py                  ← Admin REST API
│   ├── auth.py                 ← Authentication
│   ├── boundaries.py           ← Boundary management
│   ├── coverage.py             ← Coverage calculation
│   ├── dashboard.py            ← Admin dashboard
│   ├── environment.py          ← Env config editor
│   ├── intersections.py        ← Intersections
│   ├── maintenance.py          ← Maintenance ops
│   ├── audio.py                ← Audio config
│   ├── audio_ingest.py        ← Audio ingestion
│   └── audio/
│       ├── __init__.py
│       ├── detail.py
│       ├── files.py
│       └── history.py
└── routes/
    ├── __init__.py
    ├── alert_verification.py   ← Alert verification
    ├── eas_compliance.py       ← Compliance tracking
    └── system_controls.py      ← System control

scripts/
├── screen_manager.py            ← Screen rotation
├── screen_renderer.py           ← Screen rendering
├── vfd_controller.py            ← VFD control script
├── led_sign_controller.py       ← LED control script
└── ...
```

---

## Search Tips

**To find something quickly in FUNCTION_TREE.md:**

1. **Function by name:** `Ctrl+F` + function name
2. **Class methods:** Search for `| function_name |`
3. **API endpoints:** Search for `@app.route` or `| /api/`
4. **Database tables:** Search for `class TableName(db.Model)`
5. **Configuration:** Search for `| ENVIRONMENT_VAR |`
6. **Security info:** Search for `RBAC`, `permission`, `role`

**Examples:**
- Find AudioMeter: `Ctrl+F` "AudioMeter"
- Find all RBAC functions: `Ctrl+F` "RBAC"
- Find LED routes: `Ctrl+F` "routes_led"
- Find GPIO: `Ctrl+F` "GPIOController"

---

## Key Statistics at a Glance

| Category | Count |
|----------|-------|
| Database Models | 24 |
| Web Routes | 40+ |
| REST API Endpoints | 25+ |
| Functions Documented | 150+ |
| Classes Documented | 98+ |
| Configuration Variables | 30+ |
| RBAC Permissions | 21+ |
| Predefined Roles | 3 |
| Audio Source Types | 5 |
| TTS Providers | 4 |

---

## Document Statistics

| Metric | Value |
|--------|-------|
| Total Lines | 1,211 |
| Markdown Tables | 40+ |
| Code Sections | 30+ |
| Headings | 80+ |
| File Size | 44 KB |
| Coverage | ~95% of major modules |

---

## When to Use This Document

**Use FUNCTION_TREE.md when:**
- Learning the codebase structure
- Finding a specific function/class
- Understanding a module's capabilities
- Looking for API endpoints
- Researching implementation details
- Onboarding to the project
- Debugging issues (find related functions)

**Use FUNCTION_TREE_SUMMARY.txt when:**
- Getting a quick overview
- Checking what was documented
- Understanding document structure
- Checking statistics

**Use FUNCTION_TREE_INDEX.md (this file) when:**
- Starting a task (quick task lookup)
- Navigating large functions/classes
- Finding related components
- Quick reference to file structure

---

## Version Information

- **EAS Station Version:** 2.1.9
- **Document Generated:** 2025-11-06
- **Codebase Status:** Production (as of commit a490e4a)
- **Python Version:** 3.7+
- **Database:** PostgreSQL with PostGIS

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| FUNCTION_TREE.md | Complete function reference (this one) |
| FUNCTION_TREE_SUMMARY.txt | Overview & statistics |
| README.md | Project setup & overview |
| docs/archive/2025/SECURITY_FIXES.md | Historical security updates |
| KNOWN_BUGS.md | Known issues |
| docs/ | Complete documentation |
| CHANGELOG | Version history |

---

## Getting Started

### For New Developers:
1. Read README.md (general overview)
2. Skim this index (quick navigation)
3. Review FUNCTION_TREE_SUMMARY.txt (statistics)
4. Open FUNCTION_TREE.md in editor (bookmark it!)
5. Find your module of interest using table of contents

### For Quick Questions:
1. Use Ctrl+F to search FUNCTION_TREE.md
2. Check FUNCTION_TREE_SUMMARY.txt for statistics
3. Review related section in full document

### For Code Navigation:
1. Find your file in module structure (above)
2. Search for class/function in FUNCTION_TREE.md
3. Note line number
4. Jump to file & line number in editor

---

**End of Index**

Last Updated: 2025-11-06
