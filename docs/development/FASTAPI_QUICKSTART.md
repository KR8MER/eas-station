# FastAPI Migration Quick Start Guide

**For developers starting the Flask → FastAPI migration**

## Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Familiarity with Flask and FastAPI
- Understanding of EAS Station architecture

## Current State

The FastAPI foundation is in place:
- ✅ `fastapi_app_minimal.py` - Working minimal app (health, status endpoints)
- ✅ `app_core/fastapi_extensions.py` - Database layer
- ✅ `requirements.txt` - FastAPI dependencies installed
- ⏳ `fastapi_app.py` - Full app (has Flask dependencies, needs work)

## Quick Start

### 1. Run FastAPI Development Server

```bash
# Option 1: Using the provided script
./run_fastapi.sh dev

# Option 2: Direct uvicorn command
uvicorn fastapi_app_minimal:app --reload --port 8080 --log-level info

# Option 3: Python module
python -m uvicorn fastapi_app_minimal:app --reload --port 8080
```

**Access Points:**
- http://localhost:8080/ - Landing page
- http://localhost:8080/health - Health check
- http://localhost:8080/api/status - System status
- http://localhost:8080/docs - Interactive API docs (Swagger UI)
- http://localhost:8080/redoc - ReDoc documentation

### 2. Understanding the File Structure

```
eas-station/
├── app.py                      # Flask app (production)
├── fastapi_app_minimal.py      # FastAPI minimal (working)
├── fastapi_app.py              # FastAPI full (WIP - has Flask deps)
├── app_core/
│   ├── fastapi_extensions.py  # Database layer for FastAPI
│   └── models.py               # SQLAlchemy models (shared)
├── webapp/
│   ├── __init__.py             # Flask route registration
│   ├── routes_*.py             # 26 Flask route modules
│   ├── admin/                  # 21 Flask admin modules
│   ├── eas/                    # 2 Flask EAS modules
│   ├── routes/                 # 3 Flask route modules
│   └── fastapi/                # NEW: FastAPI routes (to create)
│       ├── __init__.py         # FastAPI router registration
│       ├── public.py           # Public routes (to create)
│       ├── auth.py             # Authentication (to create)
│       └── ... (other modules)
├── docs/development/
│   ├── FASTAPI_MIGRATION_ROADMAP.md  # Complete migration plan
│   └── FASTAPI_QUICKSTART.md         # This file
└── MIGRATION.md                # Migration overview
```

### 3. Your First Migration Task

**Start with a simple, low-risk route**: Let's migrate the health check endpoint.

#### Step 1: Create the FastAPI route file

```bash
mkdir -p webapp/fastapi
touch webapp/fastapi/__init__.py
```

#### Step 2: Create `webapp/fastapi/health.py`

```python
"""
Health and monitoring endpoints for FastAPI
"""
from fastapi import APIRouter
from datetime import datetime
import psutil

router = APIRouter(prefix="/api", tags=["health"])

@router.get("/health")
async def health_check():
    """Basic health check endpoint"""
    return {
        "status": "healthy",
        "service": "eas-station-fastapi",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

@router.get("/system_status")
async def system_status():
    """System resource status"""
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "system": {
            "cpu_percent": cpu_percent,
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent_used": memory.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent_used": disk.percent,
            },
        },
    }
```

#### Step 3: Update `fastapi_app_minimal.py` to include the router

```python
# Add near the top with other imports
from webapp.fastapi.health import router as health_router

# Add after app creation and before the existing routes
app.include_router(health_router)
```

#### Step 4: Test the endpoint

```bash
# Start the server
uvicorn fastapi_app_minimal:app --reload --port 8080

# In another terminal, test:
curl http://localhost:8080/api/health
curl http://localhost:8080/api/system_status

# Or visit in browser:
# http://localhost:8080/docs (interactive testing)
```

### 4. Next Steps - Authentication Migration

The most critical component is authentication. Here's a skeleton:

#### Create `app_core/fastapi_auth.py`

```python
"""
FastAPI authentication dependencies
"""
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
from app_core.fastapi_extensions import get_db
from app_core.auth.models import AdminUser

async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[AdminUser]:
    """
    Dependency to get the current authenticated user.
    Reads user_id from session and loads from database.
    """
    user_id = request.session.get('user_id')
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return user

async def get_current_active_user(
    user: AdminUser = Depends(get_current_user)
) -> AdminUser:
    """Dependency to ensure user is active"""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return user
```

#### Example usage in a protected route:

```python
from fastapi import APIRouter, Depends
from app_core.fastapi_auth import get_current_active_user
from app_core.auth.models import AdminUser

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/dashboard")
async def admin_dashboard(
    user: AdminUser = Depends(get_current_active_user)
):
    """Protected admin endpoint"""
    return {
        "message": f"Welcome {user.username}",
        "user_id": user.id,
        "roles": [role.name for role in user.roles]
    }
```

## Common Migration Patterns

### Pattern 1: Flask Blueprint → FastAPI Router

**Before (Flask)**:
```python
from flask import Blueprint

bp = Blueprint('example', __name__, url_prefix='/example')

@bp.route('/')
def index():
    return {"message": "Hello"}
```

**After (FastAPI)**:
```python
from fastapi import APIRouter

router = APIRouter(prefix="/example", tags=["example"])

@router.get("/")
async def index():
    return {"message": "Hello"}
```

### Pattern 2: Request Data

**Before (Flask)**:
```python
from flask import request, jsonify

@bp.route('/submit', methods=['POST'])
def submit():
    data = request.json
    name = data.get('name')
    # Process...
    return jsonify({'success': True})
```

**After (FastAPI)**:
```python
from pydantic import BaseModel

class SubmitRequest(BaseModel):
    name: str
    email: str

@router.post("/submit")
async def submit(data: SubmitRequest):
    # data.name is automatically validated
    # Process...
    return {'success': True}
```

### Pattern 3: Database Query

**Before (Flask)**:
```python
from app_core.extensions import db
from app_core.models import CAPAlert

@bp.route('/alerts')
def get_alerts():
    alerts = CAPAlert.query.filter_by(active=True).all()
    return jsonify([alert.to_dict() for alert in alerts])
```

**After (FastAPI)**:
```python
from sqlalchemy.orm import Session
from app_core.fastapi_extensions import get_db
from app_core.models import CAPAlert

@router.get("/alerts")
async def get_alerts(db: Session = Depends(get_db)):
    alerts = db.query(CAPAlert).filter_by(active=True).all()
    return [alert.to_dict() for alert in alerts]
```

### Pattern 4: Templates

**Before (Flask)**:
```python
from flask import render_template

@bp.route('/page')
def page():
    return render_template('page.html', data={'key': 'value'})
```

**After (FastAPI)**:
```python
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

@router.get("/page", response_class=HTMLResponse)
async def page(request: Request):
    return templates.TemplateResponse("page.html", {
        "request": request,  # REQUIRED by Jinja2Templates
        "data": {'key': 'value'}
    })
```

### Pattern 5: File Upload

**Before (Flask)**:
```python
from flask import request
from werkzeug.utils import secure_filename

@bp.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    filename = secure_filename(file.filename)
    file.save(f'/path/to/{filename}')
    return {'success': True}
```

**After (FastAPI)**:
```python
from fastapi import UploadFile, File
import shutil

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    # file.filename is already safe
    with open(f'/path/to/{file.filename}', 'wb') as f:
        shutil.copyfileobj(file.file, f)
    return {'success': True}
```

## Testing Your Migration

### Manual Testing
```bash
# Start FastAPI
uvicorn fastapi_app_minimal:app --reload --port 8080

# Test endpoint
curl http://localhost:8080/your-endpoint

# Or use the interactive docs
# http://localhost:8080/docs
```

### Unit Testing with pytest
```python
# tests/fastapi/test_health.py
from fastapi.testclient import TestClient
from fastapi_app_minimal import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run tests
pytest tests/fastapi/

# With coverage
pytest --cov=webapp/fastapi tests/fastapi/
```

## Debugging Tips

### 1. Enable Debug Logging
```python
# In fastapi_app_minimal.py
import logging
logging.basicConfig(level=logging.DEBUG)

# Or in uvicorn command
uvicorn fastapi_app_minimal:app --reload --log-level debug
```

### 2. Use Interactive Debugger
```python
# Add breakpoint in your code
import pdb; pdb.set_trace()

# Or use Python 3.7+ built-in
breakpoint()
```

### 3. Check OpenAPI Schema
```bash
# View the auto-generated schema
curl http://localhost:8080/openapi.json | jq
```

### 4. Test with Postman/Insomnia
- Import OpenAPI spec from http://localhost:8080/openapi.json
- Automatically generates all endpoints for testing

## Common Pitfalls

### 1. Missing `request` in Template Context
```python
# ❌ WRONG
return templates.TemplateResponse("page.html", {"data": value})

# ✅ CORRECT
return templates.TemplateResponse("page.html", {
    "request": request,  # Required!
    "data": value
})
```

### 2. Synchronous Database Calls
```python
# ✅ OK for now (using sync SQLAlchemy)
def get_alerts(db: Session = Depends(get_db)):
    return db.query(CAPAlert).all()

# 🔮 FUTURE (when we add async SQLAlchemy)
async def get_alerts(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(CAPAlert))
    return result.scalars().all()
```

### 3. Forgetting Type Hints
```python
# ❌ Type hints missing (works but loses validation)
@router.post("/create")
def create(data):
    return {"id": 1}

# ✅ Proper type hints
@router.post("/create")
def create(data: CreateRequest) -> CreateResponse:
    return CreateResponse(id=1)
```

### 4. Not Using Pydantic Models
```python
# ❌ Manual validation
@router.post("/create")
def create(request: Request):
    data = await request.json()
    if 'name' not in data:
        raise HTTPException(400, "name required")
    # ...

# ✅ Automatic validation with Pydantic
class CreateRequest(BaseModel):
    name: str
    email: EmailStr

@router.post("/create")
def create(data: CreateRequest):
    # data is automatically validated
    # ...
```

## Resources

### Documentation
- [FastAPI Official Docs](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 Docs](https://docs.sqlalchemy.org/en/20/)
- [Pydantic Docs](https://docs.pydantic.dev/)
- [Uvicorn Docs](https://www.uvicorn.org/)

### Internal Documentation
- `docs/development/FASTAPI_MIGRATION_ROADMAP.md` - Complete migration plan
- `MIGRATION.md` - Migration overview
- `docs/development/AGENTS.md` - Code style standards

### Example Code
- `fastapi_app_minimal.py` - Working minimal FastAPI app
- `app_core/fastapi_extensions.py` - Database layer example

## Getting Help

1. **Check the interactive docs**: http://localhost:8080/docs
2. **Review roadmap**: See FASTAPI_MIGRATION_ROADMAP.md for context
3. **Check Flask code**: The original Flask implementation is your reference
4. **Test early**: Use `/docs` endpoint for quick testing

## Next Steps

After completing your first route migration:

1. Review `docs/development/FASTAPI_MIGRATION_ROADMAP.md`
2. Choose next route to migrate (suggest: authentication or public routes)
3. Create migration branch: `git checkout -b feature/fastapi-migrate-<module>`
4. Follow the patterns in this guide
5. Test thoroughly
6. Submit PR with:
   - Route migration code
   - Tests
   - Updated documentation
   - Migration checklist status

## Migration Checklist for Each Route

- [ ] Create new file in `webapp/fastapi/`
- [ ] Convert Flask blueprints to FastAPI routers
- [ ] Update request handling (request.json → Pydantic models)
- [ ] Update response handling (jsonify → return dict)
- [ ] Update database queries (Flask-SQLAlchemy → SQLAlchemy)
- [ ] Update template rendering (if applicable)
- [ ] Add type hints
- [ ] Create Pydantic models for validation
- [ ] Write tests
- [ ] Test in browser/Postman
- [ ] Update documentation
- [ ] Mark complete in roadmap

---

**Happy migrating! Remember: Start small, test often, and refer to the roadmap frequently.**
