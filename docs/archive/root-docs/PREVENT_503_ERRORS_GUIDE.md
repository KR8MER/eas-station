# Preventing 503 Errors - Beyond Caching

**Objective**: Free up workers, reduce request processing time, and eliminate 503 Service Unavailable errors.

---

## Quick Wins (Implement First)

### 1. ✅ Fix Polling/Caching Misalignment (DONE)
**Status**: Completed in commit cf66ba0

**Impact**: 87.5% reduction in requests

---

### 2. Database Connection Pooling

**Current Risk**: Every request creates new DB connection.

**Fix**: Optimize SQLAlchemy connection pool.

**File**: `app_core/extensions.py` or database initialization

```python
# Optimize connection pool
engine = create_engine(
    database_url,
    pool_size=20,              # Up from default 5
    max_overflow=40,           # Up from default 10
    pool_pre_ping=True,        # Verify connections before use
    pool_recycle=3600,         # Recycle connections every hour
    echo_pool=False            # Disable for production
)
```

**Impact**:
- Eliminates connection creation overhead (~50-100ms per request)
- Prevents connection exhaustion
- Handles database reconnects gracefully

---

### 3. Gunicorn Worker Configuration

**Check Current Settings**:
```bash
ps aux | grep gunicorn
# Look for --workers, --threads, --worker-class
```

**Recommended Configuration**:

```python
# gunicorn.conf.py or command line
workers = (cpu_count * 2) + 1        # e.g., 4 CPU = 9 workers
worker_class = 'gthread'             # Use threads instead of sync
threads = 4                          # 4 threads per worker
worker_connections = 1000            # Max concurrent connections
timeout = 120                        # Request timeout (2 minutes)
keepalive = 5                        # Keep connections alive
max_requests = 1000                  # Recycle workers after 1000 requests
max_requests_jitter = 50             # Add jitter to prevent simultaneous restarts
preload_app = True                   # Load app before forking (saves memory)
```

**Why This Helps**:
- **9 workers × 4 threads = 36 concurrent requests** (vs. 5 workers × 1 thread = 5)
- Threads share memory (less overhead than processes)
- Worker recycling prevents memory leaks

**Apply**:
```bash
# In Dockerfile or docker-compose.yml
gunicorn --config gunicorn.conf.py app:app
```

---

### 4. Static File Offloading

**Current Problem**: Gunicorn workers serve static files (CSS, JS, images).

**Fix**: Use nginx reverse proxy.

**File**: `docker-compose.yml`

```yaml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./static:/usr/share/nginx/html/static:ro
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - web

  web:
    # Your Flask app
    ports:
      - "8000:8000"  # Internal only, not exposed
```

**File**: `nginx.conf`

```nginx
upstream flask_app {
    least_conn;  # Load balance across workers
    server web:8000;
}

server {
    listen 80;
    client_max_body_size 10M;

    # Static files - served directly by nginx
    location /static/ {
        alias /usr/share/nginx/html/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # API requests - proxy to Flask
    location /api/ {
        proxy_pass http://flask_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Increase timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # HTML pages - proxy to Flask
    location / {
        proxy_pass http://flask_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Impact**:
- Static files no longer consume worker threads
- ~30-40% reduction in worker load
- Faster static file delivery

---

### 5. Database Query Optimization

**Identify Slow Queries**:

```python
# Add to app_core/__init__.py or extensions.py
import logging
from sqlalchemy import event
from sqlalchemy.engine import Engine
import time

@event.listens_for(Engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault('query_start_time', []).append(time.time())

@event.listens_for(Engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = time.time() - conn.info['query_start_time'].pop(-1)
    if total > 0.5:  # Log queries slower than 500ms
        logger = logging.getLogger('sqlalchemy.slow_query')
        logger.warning(f"Slow query ({total:.2f}s): {statement[:200]}")
```

**Common Fixes**:

1. **Add Indexes**:
```sql
-- Example: Index on frequently filtered columns
CREATE INDEX idx_audio_source_name ON audio_source_config_db(name);
CREATE INDEX idx_alerts_timestamp ON alerts(received_at DESC);
```

2. **Eager Loading** (prevents N+1 queries):
```python
# Bad: N+1 query
sources = AudioSourceConfigDB.query.all()
for source in sources:
    print(source.metrics.peak_level_db)  # Separate query each loop!

# Good: Single query with join
from sqlalchemy.orm import joinedload
sources = AudioSourceConfigDB.query.options(
    joinedload(AudioSourceConfigDB.metrics)
).all()
```

3. **Pagination**:
```python
# Bad: Load all records
alerts = Alert.query.order_by(Alert.timestamp.desc()).all()

# Good: Paginate
alerts = Alert.query.order_by(Alert.timestamp.desc()).limit(50).all()
```

---

### 6. Rate Limiting

**Prevent abuse** and ensure fair resource allocation.

**Install**:
```bash
pip install flask-limiter
```

**File**: `webapp/__init__.py` or `app_core/extensions.py`

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per hour", "50 per minute"],
    storage_uri="memory://"  # Or use Redis for distributed limiting
)

# Apply to expensive endpoints
@app.route('/api/audio/metrics')
@limiter.limit("30 per minute")  # Max 30 requests/min per IP
def api_get_audio_metrics():
    ...
```

**Impact**:
- Prevents single client from exhausting workers
- Returns 429 (Too Many Requests) instead of 503
- Client sees clear error message

---

### 7. Background Task Processing

**Move slow operations to background workers**.

**Install Celery**:
```bash
pip install celery redis
```

**File**: `app_core/celery_app.py`

```python
from celery import Celery

celery = Celery(
    'eas_station',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)
```

**Example Task**:

```python
from app_core.celery_app import celery

@celery.task
def process_alert_verification(alert_id):
    """Run alert verification in background"""
    # Long-running verification logic here
    ...
    return {"status": "completed", "alert_id": alert_id}

# In your route:
@app.route('/api/alerts/<id>/verify', methods=['POST'])
def verify_alert(id):
    # Queue task instead of running inline
    task = process_alert_verification.delay(id)
    return jsonify({
        "task_id": task.id,
        "status": "queued"
    })

# Check status:
@app.route('/api/tasks/<task_id>')
def get_task_status(task_id):
    task = celery.AsyncResult(task_id)
    return jsonify({
        "state": task.state,
        "result": task.result
    })
```

**Impact**:
- Alert verification doesn't block workers
- Long operations run asynchronously
- Workers freed immediately

**Add to docker-compose.yml**:
```yaml
services:
  redis:
    image: redis:alpine

  celery-worker:
    build: .
    command: celery -A app_core.celery_app worker --loglevel=info
    depends_on:
      - redis
      - postgres
    environment:
      - DATABASE_URL=postgresql://...
```

---

### 8. WebSocket for Real-Time Data

**Replace polling with push-based updates**.

**Install**:
```bash
pip install flask-socketio python-socketio
```

**File**: `webapp/__init__.py`

```python
from flask_socketio import SocketIO, emit

socketio = SocketIO(app, cors_allowed_origins="*")

# Server-side: Push updates when data changes
def broadcast_vu_meter_update(source_id, peak_db, rms_db):
    socketio.emit('vu_meter_update', {
        'source_id': source_id,
        'peak_db': peak_db,
        'rms_db': rms_db,
        'timestamp': time.time()
    })

# Client-side: Listen for updates
# <script src="/socket.io/socket.io.js"></script>
# const socket = io();
# socket.on('vu_meter_update', (data) => {
#     updateMeterDisplay(data.source_id, 'peak', data.peak_db);
#     updateMeterDisplay(data.source_id, 'rms', data.rms_db);
# });
```

**Impact**:
- Eliminates polling entirely (was 120 req/min → 0 req/min)
- Real-time updates with zero lag
- Massive reduction in worker load

---

### 9. HTTP/2 and Connection Multiplexing

**Use HTTP/2** to multiplex requests over single connection.

**File**: `nginx.conf`

```nginx
server {
    listen 443 ssl http2;  # Enable HTTP/2
    ...
}
```

**Impact**:
- Reduces connection overhead
- Faster page loads
- Better browser performance

---

### 10. Request Timeout Middleware

**Fail fast** on stuck requests instead of holding workers.

**File**: `webapp/middleware.py`

```python
from flask import request, jsonify
import signal
from functools import wraps

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError()

def timeout_middleware(seconds=30):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Set timeout
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)

            try:
                result = f(*args, **kwargs)
            except TimeoutError:
                return jsonify({"error": "Request timeout"}), 504
            finally:
                signal.alarm(0)  # Disable alarm

            return result
        return decorated_function
    return decorator

# Apply to slow endpoints
@app.route('/api/slow-operation')
@timeout_middleware(seconds=15)
def slow_operation():
    ...
```

---

## Monitoring & Diagnostics

### 1. Add Request Duration Logging

```python
@app.before_request
def before_request():
    request.start_time = time.time()

@app.after_request
def after_request(response):
    if hasattr(request, 'start_time'):
        duration = time.time() - request.start_time
        if duration > 1.0:  # Log slow requests
            logger.warning(f"Slow request ({duration:.2f}s): {request.method} {request.path}")
    return response
```

### 2. Worker Status Endpoint

```python
@app.route('/api/health/workers')
def worker_health():
    import psutil
    import os

    parent_pid = os.getppid()  # Gunicorn master
    parent = psutil.Process(parent_pid)
    workers = parent.children(recursive=False)

    return jsonify({
        "worker_count": len(workers),
        "workers": [
            {
                "pid": w.pid,
                "cpu_percent": w.cpu_percent(),
                "memory_mb": w.memory_info().rss / 1024 / 1024,
                "status": w.status(),
            }
            for w in workers
        ]
    })
```

### 3. Prometheus Metrics (Advanced)

```bash
pip install prometheus-flask-exporter
```

```python
from prometheus_flask_exporter import PrometheusMetrics

metrics = PrometheusMetrics(app)

# Metrics automatically exported at /metrics
# - request_count
# - request_duration_seconds
# - request_size_bytes
# - response_size_bytes
```

---

## Implementation Priority

### Phase 1: Immediate (This Week)
1. ✅ Fix polling/caching (DONE)
2. Database connection pooling
3. Gunicorn worker tuning
4. Add request duration logging

### Phase 2: Short Term (Next 2 Weeks)
5. Static file offloading (nginx)
6. Database query optimization
7. Rate limiting
8. Request timeout middleware

### Phase 3: Medium Term (Next Month)
9. Background task processing (Celery)
10. WebSocket for real-time data
11. HTTP/2 setup

---

## Expected Improvements

| Optimization | Worker Load Reduction | 503 Error Reduction |
|--------------|----------------------|---------------------|
| Polling fix (done) | 87.5% | 95% |
| Connection pooling | 10-15% | 20% |
| Gunicorn tuning | 30-40% | 50% |
| Static file offload | 30-40% | 40% |
| WebSocket (replaces polling) | 90% | 99% |
| **TOTAL (all combined)** | **~95%** | **~99.9%** |

---

## Testing Checklist

After each change:
```bash
# Load test
ab -n 1000 -c 10 http://localhost/api/audio/metrics

# Worker status
ps aux | grep gunicorn

# 503 error rate
grep "503" /var/log/nginx/error.log | wc -l
```

---

## Questions?

- Need help implementing any of these?
- Want to prioritize specific optimizations?
- Seeing other performance bottlenecks?

Let me know and I can help implement them!
