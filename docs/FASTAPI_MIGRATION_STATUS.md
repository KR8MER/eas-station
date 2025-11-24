# FastAPI Migration Status

## Overview

EAS Station is being migrated from Flask to FastAPI for improved performance, native async support, and automatic OpenAPI documentation.

**Status:** 🟢 **Initial Implementation Complete - Ready for Testing**

**Version:** 3.0.0-alpha (FastAPI branch)

---

## What's Implemented

### ✅ Core Infrastructure

- [x] FastAPI application structure (`app_fastapi.py`)
- [x] Async SQLAlchemy 2.0 database configuration
- [x] Pydantic schemas for request/response validation
- [x] Environment configuration with pydantic-settings
- [x] Middleware (CORS, GZip compression)
- [x] Global exception handling
- [x] Automatic OpenAPI documentation generation

### ✅ API Endpoints (Placeholder Implementation)

**Audio API** (`/api/audio/*`)
- [x] GET `/sources` - List audio sources
- [x] POST `/sources` - Create audio source
- [x] GET `/sources/{source_id}` - Get source details
- [x] PATCH `/sources/{source_id}` - Update source
- [x] DELETE `/sources/{source_id}` - Delete source
- [x] POST `/sources/{source_id}/start` - Start source
- [x] POST `/sources/{source_id}/stop` - Stop source
- [x] GET `/metrics` - Real-time metrics
- [x] GET `/health` - Audio system health
- [x] GET `/waveform/{source_id}` - Waveform data
- [x] GET `/spectrogram/{source_id}` - Spectrogram data

**Alerts API** (`/api/alerts/*`)
- [x] GET `/` - List alerts (with pagination)
- [x] GET `/stats` - Alert statistics
- [x] GET `/{alert_id}` - Get alert details
- [x] POST `/` - Create manual alert

**System API** (`/api/system/*`)
- [x] GET `/health` - Health check
- [x] GET `/status` - System status
- [x] GET `/resources` - Resource usage

**EAS Monitor API** (`/api/eas-monitor/*`)
- [x] GET `/status` - EAS monitor status
- [x] POST `/start` - Start EAS monitor
- [x] POST `/stop` - Stop EAS monitor

### ✅ WebSocket Support

- [x] Native WebSocket endpoint at `/ws`
- [x] Connection management
- [x] Broadcast functionality
- [x] Message type handling (ping/pong, subscribe, etc.)

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements-fastapi.txt
```

### 2. Start FastAPI Application

```bash
./start-fastapi.sh
```

Or manually:

```bash
uvicorn app_fastapi:app --reload --port 8001
```

### 3. Access API Documentation

- **Swagger UI:** http://localhost:8001/api/docs
- **ReDoc:** http://localhost:8001/api/redoc
- **OpenAPI JSON:** http://localhost:8001/api/openapi.json

### 4. Test WebSocket Connection

```javascript
const ws = new WebSocket('ws://localhost:8001/ws');

ws.onopen = () => {
    console.log('Connected!');
    ws.send(JSON.stringify({ type: 'ping' }));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Received:', data);
};
```

---

## Architecture

### Directory Structure

```
eas-station/
├── app_fastapi.py              # FastAPI application entry point
├── requirements-fastapi.txt     # FastAPI dependencies
├── start-fastapi.sh            # Startup script
└── fastapi_app/
    ├── __init__.py
    ├── config.py               # Settings management
    ├── database.py             # Async SQLAlchemy setup
    ├── routers/
    │   ├── __init__.py
    │   ├── audio.py            # Audio endpoints
    │   ├── alerts.py           # Alert endpoints
    │   ├── system.py           # System endpoints
    │   ├── eas_monitor.py      # EAS monitor endpoints
    │   └── websocket.py        # WebSocket endpoint
    ├── schemas/
    │   ├── __init__.py
    │   ├── audio.py            # Audio Pydantic schemas
    │   ├── alerts.py           # Alert Pydantic schemas
    │   └── system.py           # System Pydantic schemas
    └── services/
        └── (future services)
```

### Technology Stack

**FastAPI Stack:**
```
FastAPI 0.115.0
├─ Uvicorn (ASGI server)
├─ Native WebSocket support
├─ SQLAlchemy 2.0 (async)
├─ Pydantic 2.10 (validation)
└─ asyncpg (PostgreSQL driver)
```

**Key Dependencies:**
- `fastapi` - Modern async web framework
- `uvicorn[standard]` - ASGI server
- `pydantic` & `pydantic-settings` - Data validation
- `sqlalchemy[asyncio]` - Async ORM
- `asyncpg` - Fast PostgreSQL async driver
- `python-jose` - JWT authentication
- `websockets` - WebSocket support

---

## Performance Comparison

### Expected Performance Improvements

| Metric | Flask | FastAPI | Improvement |
|--------|-------|---------|-------------|
| Request throughput | 1000 req/s | 3000-5000 req/s | 3-5x faster |
| Response time | 50ms | 15-20ms | 60-70% faster |
| Concurrent connections | Limited by gevent | Scales with async | Much better |
| WebSocket | Flask-SocketIO | Native | Simpler, faster |

### Benchmarking (TODO)

Run benchmarks after implementing actual database queries:

```bash
# Install Apache Bench
apt-get install apache2-utils

# Test Flask
ab -n 10000 -c 100 http://localhost:5000/api/audio/sources

# Test FastAPI
ab -n 10000 -c 100 http://localhost:8001/api/audio/sources
```

---

## Next Steps

### Phase 1: Connect to Real Data Sources ⏳

- [ ] Implement actual database queries in audio router
- [ ] Connect to Redis for metrics
- [ ] Integrate with audio service API
- [ ] Implement actual alert queries

### Phase 2: Authentication & Authorization

- [ ] Migrate Flask-Login to FastAPI-Users
- [ ] Implement JWT authentication
- [ ] Add OAuth2 password flow
- [ ] Add API key authentication for services

### Phase 3: WebSocket Real-time Updates

- [ ] Integrate WebSocket with audio metrics
- [ ] Broadcast alert notifications
- [ ] Stream EAS monitor updates
- [ ] Add client heartbeat/reconnection

### Phase 4: Background Tasks

- [ ] Health monitoring background task
- [ ] Metrics aggregation task
- [ ] Alert polling task
- [ ] Cleanup tasks

### Phase 5: Migration & Coexistence

- [ ] Run Flask and FastAPI side-by-side
- [ ] Proxy specific routes to FastAPI
- [ ] Gradually migrate frontend to use FastAPI
- [ ] Complete migration and deprecate Flask

---

## Testing

### Manual Testing

1. **Health Check:**
   ```bash
   curl http://localhost:8001/health
   ```

2. **API Documentation:**
   Open http://localhost:8001/api/docs in browser

3. **WebSocket:**
   Use browser console or wscat:
   ```bash
   npm install -g wscat
   wscat -c ws://localhost:8001/ws
   ```

### Automated Testing (TODO)

```bash
pytest tests/test_fastapi_*.py -v
```

---

## Configuration

### Environment Variables

Create `.env` file or set these variables:

```bash
# FastAPI Configuration
FASTAPI_PORT=8001
DEBUG=true
ENVIRONMENT=development

# Database (async driver)
DATABASE_URL=postgresql+asyncpg://eas:eas@localhost:5432/eas

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
SECRET_KEY=<generate-with-secrets.token_urlsafe(32)>
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
CORS_ORIGINS=["*"]

# Audio Service
AUDIO_SERVICE_URL=http://localhost:5002
```

### Generate Secret Key

```python
import secrets
print(secrets.token_urlsafe(32))
```

---

## Known Issues & Limitations

1. **Database Queries:** Most endpoints return placeholder data (TODO: implement)
2. **Authentication:** Not yet implemented
3. **Audio Service Integration:** Placeholder responses
4. **Redis Integration:** Not yet connected
5. **Background Tasks:** Not yet implemented

---

## Compatibility

### Running Both Flask and FastAPI

FastAPI runs on port 8001 by default (Flask on 5000), so both can run simultaneously:

```bash
# Terminal 1: Flask
python app.py

# Terminal 2: FastAPI
./start-fastapi.sh
```

### Shared Resources

- ✅ Database: Compatible (same models)
- ✅ Redis: Compatible (same keys)
- ✅ Templates: Compatible (Jinja2)
- ✅ Static files: Shared directory
- ⚠️ Sessions: Different mechanisms (Flask-Login vs JWT)

---

## Documentation

### API Documentation

FastAPI provides automatic interactive API documentation:

- **Swagger UI** (http://localhost:8001/api/docs)
  - Interactive API testing
  - Try out endpoints directly
  - See request/response schemas

- **ReDoc** (http://localhost:8001/api/redoc)
  - Clean, readable documentation
  - Better for reference
  - Exportable

### OpenAPI Spec

Download the OpenAPI 3.0 specification:
```bash
curl http://localhost:8001/api/openapi.json > openapi.json
```

Use with code generators:
```bash
# Generate Python client
openapi-generator generate -i openapi.json -g python -o client/

# Generate TypeScript client
openapi-generator generate -i openapi.json -g typescript-axios -o frontend/api/
```

---

## Migration Checklist

### Completed ✅

- [x] Project structure
- [x] Dependencies
- [x] Database configuration
- [x] Pydantic schemas
- [x] API router stubs
- [x] WebSocket support
- [x] OpenAPI documentation
- [x] Startup script
- [x] Configuration management

### In Progress ⏳

- [ ] Database query implementation
- [ ] Redis integration
- [ ] Audio service integration
- [ ] Authentication

### Planned 📋

- [ ] Background tasks
- [ ] Testing suite
- [ ] Performance benchmarks
- [ ] Deployment configuration
- [ ] Frontend migration
- [ ] Flask deprecation

---

## Resources

### Official Documentation

- **FastAPI:** https://fastapi.tiangolo.com/
- **Pydantic:** https://docs.pydantic.dev/
- **SQLAlchemy Async:** https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- **Uvicorn:** https://www.uvicorn.org/

### Related Files

- `docs/archive/root-docs/FASTAPI_MIGRATION.md` - Original migration plan
- `app.py` - Current Flask application
- `app_fastapi.py` - New FastAPI application
- `requirements.txt` - Flask dependencies
- `requirements-fastapi.txt` - FastAPI dependencies

---

## Support

For questions or issues with the FastAPI migration:

1. Check this documentation
2. Review FastAPI docs: https://fastapi.tiangolo.com/
3. Open an issue on GitHub
4. Contact: support@easstation.com

---

**Last Updated:** 2025-11-24
**Migration Status:** Alpha - Ready for Testing
**Next Milestone:** Connect to real data sources
