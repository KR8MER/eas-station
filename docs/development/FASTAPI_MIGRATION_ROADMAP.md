# FastAPI Migration Roadmap

**Document Version**: 1.0  
**Last Updated**: 2025-12-10  
**Status**: Planning Phase  
**Current Progress**: ~5% (Foundation Complete)

## Executive Summary

This document provides a comprehensive roadmap for migrating EAS Station from Flask to FastAPI. The migration is being executed gradually to minimize risk while modernizing the application architecture for better performance, maintainability, and developer experience.

### Why FastAPI?

1. **Performance**: ASGI-based async architecture (2-3x faster than Flask for I/O-bound operations)
2. **Modern Python**: Native support for type hints and async/await
3. **Auto Documentation**: Built-in OpenAPI/Swagger documentation
4. **WebSocket Support**: Native async WebSocket implementation
5. **Data Validation**: Pydantic models for automatic request/response validation
6. **Developer Experience**: Better IDE support, faster development cycles

### Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Nginx (Port 8888/443)                 │
│                    (SSL Termination & Proxy)                 │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│              Flask App (Port 5000) - PRODUCTION              │
│                                                               │
│  • Gunicorn with gevent workers                              │
│  • Flask-SQLAlchemy for database                             │
│  • Flask-SocketIO for WebSockets (gevent mode)              │
│  • Flask-Login for authentication                            │
│  • 51 route modules                                          │
│  • Jinja2 templates                                          │
│  • ~15,000 lines of route code                               │
└─────────────────────────────────────────────────────────────┘
```

### Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Nginx (Port 8888/443)                 │
│                    (SSL Termination & Proxy)                 │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│            FastAPI App (Port 8080) - PRODUCTION              │
│                                                               │
│  • Uvicorn with async workers                                │
│  • Pure SQLAlchemy 2.0 with async                            │
│  • Native WebSocket + Socket.IO compatibility                │
│  • FastAPI dependency injection for auth                     │
│  • API Routers (modular design)                              │
│  • Jinja2Templates (FastAPI integration)                     │
│  • Auto-generated OpenAPI documentation                      │
└─────────────────────────────────────────────────────────────┘
```

## Current Status (December 2025)

### ✅ Completed (Phase 0: Foundation)

| Component | Status | Files | Notes |
|-----------|--------|-------|-------|
| FastAPI Dependencies | ✅ | `requirements.txt` | FastAPI, Uvicorn, Slowapi added |
| Minimal Working App | ✅ | `fastapi_app_minimal.py` | Health, status, version endpoints |
| Database Layer | ✅ | `app_core/fastapi_extensions.py` | SQLAlchemy wrapper for FastAPI |
| Startup Script | ✅ | `run_fastapi.sh` | Dev/prod modes |
| Migration Guide | ✅ | `MIGRATION.md` | Initial documentation |
| Auto Documentation | ✅ | `/docs`, `/redoc` | OpenAPI spec generation |

### 🚧 In Progress

| Component | Status | Blocker | ETA |
|-----------|--------|---------|-----|
| Full FastAPI App | 🚧 | Has Flask dependencies | Week 1 |
| Route Framework | 🚧 | Template system needed | Week 2 |

### ⏳ Not Started (Remaining Work)

See sections below for detailed breakdown.

---

## Migration Phases

### Phase 1: Core Infrastructure (Weeks 1-2)

**Goal**: Establish foundation for route migration without Flask dependencies

#### 1.1 Complete FastAPI Application Base
- [ ] Remove Flask dependencies from `fastapi_app.py`
- [ ] Implement Jinja2Templates integration
- [ ] Create FastAPI-compatible context processors
- [ ] Test database connection pooling
- [ ] Configure logging integration

**Files to modify**:
- `fastapi_app.py` (remove Flask imports)
- Create `app_core/fastapi_context.py` (context processors)
- Create `app_core/fastapi_templates.py` (template utilities)

**Acceptance criteria**:
- `fastapi_app.py` runs without Flask installed
- Templates render with proper context
- Database queries execute successfully
- Logging works correctly

#### 1.2 Authentication System
- [ ] Create `get_current_user()` dependency
- [ ] Implement session-based authentication
- [ ] Migrate MFA enrollment logic
- [ ] Migrate MFA verification logic
- [ ] Create role-based access decorators
- [ ] Implement password hashing compatibility

**Files to create**:
- `app_core/fastapi_auth.py` (auth dependencies)
- `app_core/fastapi_mfa.py` (MFA logic)
- `app_core/fastapi_rbac.py` (role-based access)

**Files to reference**:
- `webapp/admin/auth.py` (Flask auth logic)
- `app_core/auth/models.py` (user models)
- `app_core/auth/roles.py` (roles/permissions)

**Acceptance criteria**:
- Users can log in via FastAPI
- MFA enrollment works
- MFA verification works
- Sessions persist correctly
- RBAC decorators enforce permissions

#### 1.3 CSRF Protection
- [ ] Create CSRF middleware
- [ ] Implement token generation
- [ ] Add token validation
- [ ] Configure exempt endpoints
- [ ] Test double-submit cookie pattern

**Files to create**:
- `app_core/fastapi_csrf.py`

**Acceptance criteria**:
- POST/PUT/DELETE require CSRF token
- Exempt endpoints work without token
- Token refresh on login/logout
- Compatible with JavaScript frontend

#### 1.4 Template System
- [ ] Migrate `template_helpers.py` functions
- [ ] Create FastAPI context processors
- [ ] Update `url_for()` calls
- [ ] Handle flash messages
- [ ] Test theme system

**Files to modify**:
- `webapp/template_helpers.py` → `app_core/fastapi_template_helpers.py`

**Acceptance criteria**:
- All template filters work
- Theme switching functional
- URL generation correct
- Flash messages display

---

### Phase 2: Public & Health Endpoints (Week 3)

**Goal**: Migrate low-risk, high-visibility public routes

#### 2.1 Public Routes
- [ ] Migrate landing page (`/`)
- [ ] Migrate about page (`/about`)
- [ ] Migrate help page (`/help`)
- [ ] Migrate terms of service
- [ ] Migrate privacy policy

**Files to migrate**:
- `webapp/routes_public.py` → `webapp/fastapi/routes_public.py`

**Templates to verify**:
- `templates/index.html`
- `templates/about.html`
- `templates/help.html`

#### 2.2 Health & Monitoring
- [ ] Migrate `/health` endpoint
- [ ] Migrate `/api/system_status`
- [ ] Migrate `/api/system_health`
- [ ] Migrate `/api/metrics`

**Files to migrate**:
- `webapp/admin/health_endpoints.py` → `webapp/fastapi/health.py`
- `webapp/routes_monitoring.py` (parts) → `webapp/fastapi/monitoring.py`

#### 2.3 Documentation Routes
- [ ] Migrate `/docs` routes
- [ ] Migrate `/api-docs`

**Files to migrate**:
- `webapp/documentation.py` → `webapp/fastapi/documentation.py`

**Acceptance criteria**:
- Public pages load correctly
- Health checks return accurate data
- Monitoring endpoints work
- No authentication required for public routes

---

### Phase 3: Authentication & Sessions (Week 4)

**Goal**: Complete authentication migration with MFA support

#### 3.1 Login/Logout
- [ ] Migrate `/login` (GET)
- [ ] Migrate `/login` (POST)
- [ ] Migrate `/logout`
- [ ] Test session creation
- [ ] Test session destruction

#### 3.2 MFA Endpoints
- [ ] Migrate `/mfa/enroll` (GET)
- [ ] Migrate `/mfa/enroll` (POST)
- [ ] Migrate `/mfa/verify` (GET)
- [ ] Migrate `/mfa/verify` (POST)
- [ ] Migrate `/mfa/disable`
- [ ] Migrate `/mfa/backup-codes`

#### 3.3 User Management
- [ ] Migrate `/admin/users` (list)
- [ ] Migrate `/admin/users/create`
- [ ] Migrate `/admin/users/edit/<id>`
- [ ] Migrate `/admin/users/delete/<id>`
- [ ] Migrate `/admin/users/reset-password/<id>`

**Files to migrate**:
- `webapp/admin/auth.py` → `webapp/fastapi/auth.py`

**Templates to verify**:
- `templates/login.html`
- `templates/mfa_enroll.html`
- `templates/mfa_verify.html`

**Acceptance criteria**:
- Login flow works end-to-end
- MFA enrollment/verification works
- Sessions persist across requests
- CSRF protection active
- Role-based access enforced

---

### Phase 4: Admin Dashboard & Settings (Weeks 5-6)

**Goal**: Migrate admin interface and configuration pages

#### 4.1 Admin Dashboard
- [ ] Migrate `/admin`
- [ ] Migrate system health cards
- [ ] Migrate alert statistics
- [ ] Migrate recent activity feed

**Files to migrate**:
- `webapp/admin/dashboard.py` → `webapp/fastapi/admin/dashboard.py`

**Templates**:
- `templates/admin/dashboard.html`

#### 4.2 Environment Settings
- [ ] Migrate `/admin/environment`
- [ ] Migrate variable updates
- [ ] Migrate variable validation
- [ ] Test .env persistence

**Files to migrate**:
- `webapp/admin/environment.py` → `webapp/fastapi/admin/environment.py`

#### 4.3 Network Settings
- [ ] Migrate `/admin/network`
- [ ] Migrate IP configuration
- [ ] Migrate DNS settings

**Files to migrate**:
- `webapp/admin/network.py` → `webapp/fastapi/admin/network.py`

#### 4.4 Maintenance Pages
- [ ] Migrate `/admin/maintenance`
- [ ] Migrate database operations
- [ ] Migrate log viewing
- [ ] Migrate backups

**Files to migrate**:
- `webapp/admin/maintenance.py` → `webapp/fastapi/admin/maintenance.py`
- `webapp/routes_backups.py` → `webapp/fastapi/backups.py`

**Acceptance criteria**:
- Admin dashboard loads with live data
- Settings can be modified
- Changes persist to database
- Validation prevents invalid configs

---

### Phase 5: Audio & Radio Configuration (Weeks 7-8)

**Goal**: Migrate audio/radio settings and monitoring

#### 5.1 Radio Receivers
- [ ] Migrate `/settings/radio`
- [ ] Migrate receiver CRUD operations
- [ ] Migrate frequency configuration
- [ ] Migrate squelch settings

**Files to migrate**:
- `webapp/routes_settings_radio.py` → `webapp/fastapi/settings/radio.py`

#### 5.2 Audio Settings
- [ ] Migrate `/settings/audio`
- [ ] Migrate audio device configuration
- [ ] Migrate broadcast settings
- [ ] Migrate voice settings

**Files to migrate**:
- `webapp/routes_settings_audio.py` → `webapp/fastapi/settings/audio.py`
- `webapp/admin/audio.py` → `webapp/fastapi/admin/audio.py`

#### 5.3 Audio Monitoring
- [ ] Migrate `/audio/monitoring`
- [ ] Migrate VU meter endpoint
- [ ] Migrate EAS monitor status
- [ ] Migrate spectrum waterfall

**Files to migrate**:
- `webapp/routes_eas_monitor_status.py` → `webapp/fastapi/eas_monitor.py`

#### 5.4 Audio Files
- [ ] Migrate `/audio/files` (list)
- [ ] Migrate `/audio/upload`
- [ ] Migrate `/audio/play/<id>`
- [ ] Migrate `/audio/download/<id>`
- [ ] Migrate `/audio/delete/<id>`

**Files to migrate**:
- `webapp/admin/audio/files.py` → `webapp/fastapi/audio/files.py`
- `webapp/admin/audio/history.py` → `webapp/fastapi/audio/history.py`
- `webapp/admin/audio/received.py` → `webapp/fastapi/audio/received.py`
- `webapp/admin/audio/detail.py` → `webapp/fastapi/audio/detail.py`

**Acceptance criteria**:
- Radio receivers can be configured
- Audio settings persist
- Audio files upload/download correctly
- Monitoring displays real-time data

---

### Phase 6: EAS Workflow & Compliance (Weeks 9-10)

**Goal**: Migrate core EAS functionality

#### 6.1 EAS Message Management
- [ ] Migrate `/eas/messages` (list)
- [ ] Migrate `/eas/messages/create`
- [ ] Migrate `/eas/messages/edit/<id>`
- [ ] Migrate `/eas/messages/broadcast/<id>`
- [ ] Migrate `/eas/messages/delete/<id>`

**Files to migrate**:
- `webapp/eas/messages.py` → `webapp/fastapi/eas/messages.py`

#### 6.2 EAS Workflow
- [ ] Migrate `/eas/workflow`
- [ ] Migrate alert processing
- [ ] Migrate SAME generation
- [ ] Migrate audio generation

**Files to migrate**:
- `webapp/eas/workflow.py` → `webapp/fastapi/eas/workflow.py`

#### 6.3 Compliance Monitoring
- [ ] Migrate `/compliance/dashboard`
- [ ] Migrate `/compliance/receivers`
- [ ] Migrate `/compliance/reports`

**Files to migrate**:
- `webapp/routes/eas_compliance.py` → `webapp/fastapi/compliance.py`

#### 6.4 Alert Verification
- [ ] Migrate `/alerts/verify/<id>`
- [ ] Migrate verification status updates

**Files to migrate**:
- `webapp/routes/alert_verification.py` → `webapp/fastapi/alerts/verification.py`

**Acceptance criteria**:
- Manual alerts can be created
- SAME headers generate correctly
- Audio files generate successfully
- Compliance tracking works
- Verification reports accurate

---

### Phase 7: Real-time Features & WebSockets (Weeks 11-12)

**Goal**: Implement real-time updates via WebSocket

#### 7.1 WebSocket Infrastructure
- [ ] Set up Socket.IO with FastAPI
- [ ] Create connection handler
- [ ] Implement authentication for WebSocket
- [ ] Test broadcast functionality

**Files to create**:
- `app_core/fastapi_socketio.py`

#### 7.2 Audio Monitoring WebSocket
- [ ] Migrate VU meter updates
- [ ] Migrate EAS decoder status
- [ ] Migrate broadcast status
- [ ] Test 100ms update rate

**Events to migrate**:
- `audio_vu_meter`
- `eas_decoder_status`
- `broadcast_status`

#### 7.3 System Health WebSocket
- [ ] Migrate system metrics
- [ ] Migrate receiver status
- [ ] Migrate alert updates

**Events to migrate**:
- `system_health`
- `receiver_status`
- `new_alert`

#### 7.4 Background Tasks
- [ ] Migrate RWT scheduler
- [ ] Migrate health monitoring worker
- [ ] Migrate screen manager
- [ ] Migrate analytics scheduler

**Files to migrate**:
- `app_core/rwt_scheduler.py` (refactor for FastAPI)
- `app_core/system_health.py` (refactor for async)
- `scripts/screen_manager.py` (refactor for async)

**Acceptance criteria**:
- WebSocket connections stable
- Real-time updates work
- Background tasks run on schedule
- No memory leaks

---

### Phase 8: Specialized Features (Weeks 13-14)

**Goal**: Migrate remaining specialized features

#### 8.1 IPAWS Integration
- [ ] Migrate `/ipaws/config`
- [ ] Migrate `/ipaws/alerts`
- [ ] Migrate polling functionality

**Files to migrate**:
- `webapp/routes_ipaws.py` → `webapp/fastapi/ipaws.py`

#### 8.2 Display Systems
- [ ] Migrate LED sign control (`/led/*`)
- [ ] Migrate VFD control (`/vfd/*`)
- [ ] Migrate screen control (`/screens/*`)

**Files to migrate**:
- `webapp/routes_led.py` → `webapp/fastapi/led.py`
- `webapp/routes_vfd.py` → `webapp/fastapi/vfd.py`
- `webapp/routes_screens.py` → `webapp/fastapi/screens.py`

#### 8.3 Analytics
- [ ] Migrate `/analytics/dashboard`
- [ ] Migrate `/analytics/reports`
- [ ] Migrate scheduled report generation

**Files to migrate**:
- `webapp/routes_analytics.py` → `webapp/fastapi/analytics.py`

#### 8.4 Debugging & Diagnostics
- [ ] Migrate `/debug/*`
- [ ] Migrate `/diagnostics/*`
- [ ] Migrate SDR troubleshooting

**Files to migrate**:
- `webapp/routes_debug.py` → `webapp/fastapi/debug.py`
- `webapp/routes_diagnostics.py` → `webapp/fastapi/diagnostics.py`
- `webapp/admin/audio_sdr_fix.py` → `webapp/fastapi/admin/sdr_fix.py`

#### 8.5 Miscellaneous Features
- [ ] Migrate `/snow-emergencies`
- [ ] Migrate `/exports/*`
- [ ] Migrate `/audio-tests`
- [ ] Migrate `/stream-profiles`
- [ ] Migrate `/security/*`
- [ ] Migrate `/setup/*`

**Files to migrate**:
- `webapp/routes_snow_emergencies.py` → `webapp/fastapi/snow_emergencies.py`
- `webapp/routes_exports.py` → `webapp/fastapi/exports.py`
- `webapp/routes_audio_tests.py` → `webapp/fastapi/audio_tests.py`
- `webapp/routes_stream_profiles.py` → `webapp/fastapi/stream_profiles.py`
- `webapp/routes_security.py` → `webapp/fastapi/security.py`
- `webapp/routes_setup.py` → `webapp/fastapi/setup.py`

**Acceptance criteria**:
- All specialized features functional
- No regressions in functionality
- Performance equal or better than Flask

---

### Phase 9: Testing & Validation (Weeks 15-16)

**Goal**: Comprehensive testing before production

#### 9.1 Unit Tests
- [ ] Create pytest fixtures for FastAPI
- [ ] Write tests for authentication
- [ ] Write tests for each endpoint
- [ ] Achieve >80% code coverage

**Files to create**:
- `tests/fastapi/test_auth.py`
- `tests/fastapi/test_routes_*.py`
- `tests/fastapi/conftest.py` (fixtures)

#### 9.2 Integration Tests
- [ ] Test complete workflows
- [ ] Test WebSocket connections
- [ ] Test background tasks
- [ ] Test error handling

#### 9.3 Performance Tests
- [ ] Benchmark endpoint response times
- [ ] Load test with realistic traffic
- [ ] WebSocket stress test
- [ ] Database query optimization

**Tools**:
- `locust` for load testing
- `pytest-benchmark` for benchmarks

#### 9.4 Security Audit
- [ ] Review authentication logic
- [ ] Test CSRF protection
- [ ] Check for SQL injection vulnerabilities
- [ ] Verify CORS configuration
- [ ] Test rate limiting

#### 9.5 Regression Testing
- [ ] Compare Flask vs FastAPI responses
- [ ] Verify data consistency
- [ ] Check for broken links
- [ ] Test all user workflows

**Acceptance criteria**:
- All tests pass
- Performance meets targets
- No security vulnerabilities
- Documentation complete

---

### Phase 10: Production Deployment (Weeks 17-18)

**Goal**: Deploy to production with gradual traffic migration

#### 10.1 Docker Configuration
- [ ] Update Dockerfile for FastAPI
- [ ] Create `docker-compose.fastapi.yml`
- [ ] Configure nginx for dual routing
- [ ] Test container builds

**Files to modify**:
- `Dockerfile` (add CMD option for FastAPI)
- `docker-compose.yml` (add fastapi service)
- `nginx.conf` (add FastAPI upstream)

#### 10.2 Environment Configuration
- [ ] Document environment variables
- [ ] Create migration checklist
- [ ] Update `.env.example`

#### 10.3 Gradual Migration
- [ ] Deploy FastAPI alongside Flask
- [ ] Route 10% traffic to FastAPI
- [ ] Monitor metrics for 48 hours
- [ ] Route 50% traffic to FastAPI
- [ ] Monitor metrics for 48 hours
- [ ] Route 100% traffic to FastAPI
- [ ] Monitor metrics for 1 week

#### 10.4 Rollback Preparation
- [ ] Document rollback procedure
- [ ] Create rollback scripts
- [ ] Test rollback process

#### 10.5 Flask Deprecation
- [ ] Archive Flask code
- [ ] Remove Flask dependencies
- [ ] Update documentation
- [ ] Announce migration complete

**Acceptance criteria**:
- Production deployment successful
- Monitoring shows no issues
- User feedback positive
- Flask cleanly removed

---

## Technical Details

### Key Architectural Changes

| Aspect | Flask | FastAPI | Migration Complexity |
|--------|-------|---------|---------------------|
| **WSGI/ASGI** | WSGI (sync) | ASGI (async) | Medium |
| **Server** | Gunicorn + gevent | Uvicorn | Low |
| **Database** | Flask-SQLAlchemy | Pure SQLAlchemy 2.0 | Medium |
| **Sessions** | Flask sessions | Starlette SessionMiddleware | Low |
| **WebSocket** | Flask-SocketIO | Native + Socket.IO | High |
| **Auth** | Flask-Login | Dependency injection | Medium |
| **Templates** | Jinja2 + Flask context | Jinja2Templates | Medium |
| **Request Context** | `g`, `request`, `session` | `Request`, `Depends()` | High |
| **Routing** | `@app.route()` | `@router.get/post()` | Low |
| **Error Handlers** | `@app.errorhandler()` | `@app.exception_handler()` | Low |
| **Background Tasks** | APScheduler + Flask context | APScheduler or native async | Medium |
| **Rate Limiting** | Flask-Limiter | Slowapi | Low |
| **CSRF** | Custom middleware | Custom middleware | Medium |
| **File Uploads** | `request.files` | `UploadFile` | Low |
| **Streaming** | `send_file()` | `FileResponse` | Low |

### Compatibility Layers

To minimize code changes, we'll create compatibility wrappers:

1. **Database**: `app_core/fastapi_extensions.py` ✅
   - Provides `get_db()` dependency
   - Session management similar to Flask-SQLAlchemy

2. **Templates**: `app_core/fastapi_templates.py` (to create)
   - Jinja2Templates with custom context
   - Compatible `url_for()` function
   - Flash message support

3. **Authentication**: `app_core/fastapi_auth.py` (to create)
   - `get_current_user()` dependency
   - Role-based decorators
   - MFA support

4. **Request Context**: `app_core/fastapi_context.py` (to create)
   - Replacement for Flask's `g` object
   - Request-scoped data storage

### Code Migration Patterns

#### Flask Route → FastAPI Route

**Before (Flask)**:
```python
from flask import Blueprint, render_template, request, jsonify

bp = Blueprint('example', __name__)

@bp.route('/example', methods=['GET', 'POST'])
def example_route():
    if request.method == 'POST':
        data = request.json
        # Process data
        return jsonify({'success': True})
    return render_template('example.html')
```

**After (FastAPI)**:
```python
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

router = APIRouter(prefix="/example", tags=["example"])
templates = Jinja2Templates(directory="templates")

class ExampleRequest(BaseModel):
    field1: str
    field2: int

@router.get("/", response_class=HTMLResponse)
async def example_get(request: Request):
    return templates.TemplateResponse("example.html", {"request": request})

@router.post("/")
async def example_post(data: ExampleRequest):
    # Process data
    return {"success": True}
```

#### Authentication

**Before (Flask)**:
```python
from flask_login import login_required, current_user

@bp.route('/protected')
@login_required
def protected_route():
    user = current_user
    return render_template('protected.html', user=user)
```

**After (FastAPI)**:
```python
from app_core.fastapi_auth import get_current_user
from app_core.auth.models import AdminUser

@router.get("/protected", response_class=HTMLResponse)
async def protected_route(
    request: Request,
    user: AdminUser = Depends(get_current_user)
):
    return templates.TemplateResponse("protected.html", {
        "request": request,
        "user": user
    })
```

#### Database Queries

**Before (Flask)**:
```python
from app_core.extensions import db
from app_core.models import CAPAlert

@bp.route('/alerts')
def list_alerts():
    alerts = CAPAlert.query.filter_by(active=True).all()
    return render_template('alerts.html', alerts=alerts)
```

**After (FastAPI)**:
```python
from sqlalchemy.orm import Session
from app_core.fastapi_extensions import get_db
from app_core.models import CAPAlert

@router.get("/alerts", response_class=HTMLResponse)
async def list_alerts(
    request: Request,
    db: Session = Depends(get_db)
):
    alerts = db.query(CAPAlert).filter_by(active=True).all()
    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "alerts": alerts
    })
```

---

## File Organization

### Current Structure
```
webapp/
├── __init__.py (route registration)
├── routes_*.py (26 route modules)
├── admin/
│   ├── *.py (21 admin modules)
│   └── audio/ (4 submodules)
├── eas/
│   ├── messages.py
│   └── workflow.py
└── routes/
    ├── alert_verification.py
    ├── eas_compliance.py
    └── system_controls.py
```

### Target Structure
```
webapp/
├── __init__.py (Flask registration - to deprecate)
├── routes_*.py (Flask routes - to deprecate)
├── fastapi/ (NEW)
│   ├── __init__.py (FastAPI router registration)
│   ├── public.py
│   ├── health.py
│   ├── auth.py
│   ├── monitoring.py
│   ├── admin/
│   │   ├── dashboard.py
│   │   ├── users.py
│   │   ├── environment.py
│   │   ├── network.py
│   │   └── maintenance.py
│   ├── eas/
│   │   ├── messages.py
│   │   ├── workflow.py
│   │   └── compliance.py
│   ├── audio/
│   │   ├── files.py
│   │   ├── history.py
│   │   ├── monitoring.py
│   │   └── settings.py
│   ├── settings/
│   │   ├── radio.py
│   │   └── audio.py
│   └── ... (other modules)
└── admin/ (Flask admin - to deprecate)
```

---

## Rollback Strategy

### Immediate Rollback (< 5 minutes)
If critical issues occur during gradual migration:

1. **Nginx Configuration**: Route 100% traffic back to Flask
   ```nginx
   upstream app {
       server app:5000;  # Flask
       # server fastapi:8080;  # FastAPI - commented out
   }
   ```

2. **Docker Compose**: Stop FastAPI container
   ```bash
   docker compose stop fastapi
   docker compose restart nginx
   ```

### Short-term Rollback (< 1 hour)
If issues discovered after full cutover:

1. Revert nginx configuration
2. Restart Flask container
3. Stop FastAPI container
4. Verify Flask functionality

### Long-term Strategy
If fundamental issues require extended work:

1. Branch strategy: Keep Flask on `main`, FastAPI on feature branch
2. Continue development on feature branch
3. Address issues incrementally
4. Plan second migration attempt

---

## Risk Mitigation

### High-Risk Areas

1. **Authentication & Sessions**
   - **Risk**: Users logged out unexpectedly
   - **Mitigation**: 
     - Parallel testing with test accounts
     - Session compatibility layer
     - Gradual rollout starting with staff accounts

2. **WebSocket Connections**
   - **Risk**: Real-time monitoring breaks
   - **Mitigation**: 
     - Fallback to polling if WebSocket fails
     - Extensive testing with multiple clients
     - Monitor connection stability metrics

3. **Database Connection Pooling**
   - **Risk**: Connection exhaustion or deadlocks
   - **Mitigation**: 
     - Load testing before production
     - Monitor pool statistics
     - Configure appropriate pool sizes

4. **Background Workers**
   - **Risk**: Scheduled tasks fail or run multiple times
   - **Mitigation**: 
     - Idempotent task design
     - Locking mechanisms
     - Monitoring task execution

### Medium-Risk Areas

1. **Template Rendering**
   - **Risk**: Broken links or missing context
   - **Mitigation**: Manual testing of all pages

2. **File Uploads**
   - **Risk**: Large files timeout or corrupt
   - **Mitigation**: Size limits, streaming uploads

3. **API Response Format**
   - **Risk**: Breaking changes for external clients
   - **Mitigation**: Version API endpoints, maintain compatibility

---

## Success Metrics

### Performance Targets

| Metric | Flask Baseline | FastAPI Target | Improvement |
|--------|----------------|----------------|-------------|
| **Average Response Time** | 150ms | < 100ms | 33% faster |
| **P95 Response Time** | 500ms | < 300ms | 40% faster |
| **Requests/sec** | 100 | 200+ | 2x throughput |
| **WebSocket Latency** | 100ms | < 50ms | 2x faster |
| **Memory Usage** | 512MB | < 400MB | 22% reduction |
| **CPU Usage** | 40% | < 30% | 25% reduction |

### Functional Requirements

- [ ] 100% feature parity with Flask version
- [ ] No data loss during migration
- [ ] No breaking changes for users
- [ ] All automated tests passing
- [ ] Documentation up to date

### User Acceptance Criteria

- [ ] No increase in support tickets
- [ ] Positive user feedback
- [ ] Staff training completed
- [ ] Migration announced

---

## Resources & Tools

### Documentation
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [Uvicorn Documentation](https://www.uvicorn.org/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

### Testing Tools
- pytest + pytest-asyncio
- pytest-benchmark
- locust (load testing)
- Postman/Insomnia (API testing)

### Monitoring
- Prometheus metrics
- Grafana dashboards
- Application logging
- Error tracking (Sentry if configured)

---

## Timeline & Effort Estimates

### Optimistic (10 weeks)
- Dedicated full-time developer
- No major blockers
- Existing code well-structured

### Realistic (16 weeks)
- Developer working on migration 50-75% time
- Some technical challenges
- Need for additional testing

### Pessimistic (24 weeks)
- Developer working on migration part-time
- Significant refactoring needed
- Production issues requiring rollback

### Current Estimate: **16 weeks** (4 months)

**Start Date**: 2025-12-10  
**Target Completion**: 2026-04-10  
**Production Cutover**: 2026-04-17

---

## Appendices

### A. Route Migration Checklist

Complete checklist of all 51+ route modules:

#### Public Routes (5)
- [ ] `routes_public.py` - Landing, about, help
- [ ] `documentation.py` - API docs
- [ ] `routes_setup.py` - Setup wizard
- [ ] `routes_monitoring.py` - Public monitoring
- [ ] `webapp/admin/health_endpoints.py` - Health checks

#### Authentication (1)
- [ ] `webapp/admin/auth.py` - Login, logout, MFA

#### Admin (15)
- [ ] `routes_admin.py` - Admin blueprint
- [ ] `webapp/admin/dashboard.py` - Admin dashboard
- [ ] `webapp/admin/environment.py` - Environment variables
- [ ] `webapp/admin/network.py` - Network config
- [ ] `webapp/admin/maintenance.py` - Maintenance
- [ ] `webapp/admin/boundaries.py` - Geographic boundaries
- [ ] `webapp/admin/intersections.py` - Boundary intersections
- [ ] `webapp/admin/coverage.py` - Coverage analysis
- [ ] `webapp/admin/zigbee.py` - Zigbee devices
- [ ] `webapp/admin/api.py` - Admin API
- [ ] `webapp/admin/audio.py` - Audio admin
- [ ] `webapp/admin/audio_ingest.py` - Audio ingest
- [ ] `webapp/admin/audio_sdr_fix.py` - SDR troubleshooting
- [ ] `webapp/admin/audio/files.py` - Audio files
- [ ] `webapp/admin/audio/history.py` - Audio history
- [ ] `webapp/admin/audio/received.py` - Received audio
- [ ] `webapp/admin/audio/detail.py` - Audio detail

#### Settings (2)
- [ ] `routes_settings_radio.py` - Radio receivers
- [ ] `routes_settings_audio.py` - Audio settings

#### EAS Core (5)
- [ ] `webapp/eas/messages.py` - EAS messages
- [ ] `webapp/eas/workflow.py` - EAS workflow
- [ ] `webapp/routes/alert_verification.py` - Alert verification
- [ ] `webapp/routes/eas_compliance.py` - Compliance monitoring
- [ ] `webapp/routes/system_controls.py` - System controls

#### Audio/Radio (3)
- [ ] `routes_eas_monitor_status.py` - EAS monitoring
- [ ] `routes_audio_tests.py` - Audio tests
- [ ] `routes_stream_profiles.py` - Stream profiles

#### Integrations (1)
- [ ] `routes_ipaws.py` - IPAWS integration

#### Display Systems (3)
- [ ] `routes_led.py` - LED signs
- [ ] `routes_vfd.py` - VFD displays
- [ ] `routes_screens.py` - Screen management

#### Reporting & Analytics (3)
- [ ] `routes_analytics.py` - Analytics
- [ ] `routes_exports.py` - Data exports
- [ ] `routes_backups.py` - Backups

#### Utilities (5)
- [ ] `routes_debug.py` - Debug tools
- [ ] `routes_diagnostics.py` - Diagnostics
- [ ] `routes_security.py` - Security
- [ ] `routes_rwt_schedule.py` - RWT scheduler
- [ ] `routes_snow_emergencies.py` - Snow emergencies

#### Support (1)
- [ ] `template_helpers.py` - Template utilities

**Total: 51 modules**

### B. Testing Checklist

- [ ] Unit tests for authentication
- [ ] Unit tests for database operations
- [ ] Unit tests for each endpoint
- [ ] Integration tests for workflows
- [ ] WebSocket connection tests
- [ ] Performance benchmarks
- [ ] Load testing
- [ ] Security audit
- [ ] Regression testing
- [ ] User acceptance testing

### C. Environment Variables

New variables needed for FastAPI:

```bash
# FastAPI Configuration
FASTAPI_PORT=8080
UVICORN_WORKERS=4
UVICORN_LOG_LEVEL=info

# WebSocket
WEBSOCKET_PING_INTERVAL=25
WEBSOCKET_PING_TIMEOUT=60

# Performance
FASTAPI_POOL_SIZE=10
FASTAPI_MAX_OVERFLOW=20
FASTAPI_POOL_TIMEOUT=30
```

---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-10 | AI Agent | Initial roadmap creation |

---

## Approval & Sign-off

- [ ] Technical Lead Review
- [ ] Security Review
- [ ] Product Owner Approval
- [ ] Stakeholder Communication

---

**End of Document**
