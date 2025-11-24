# Raspberry Pi Performance Optimization Guide

## Current Configuration Issues

### Identified Bottlenecks

1. **Worker Configuration**: `--workers ${MAX_WORKERS:-1}` with default of **1 worker**
   - `.env.example` shows `MAX_WORKERS=2` but Dockerfile defaults to 1
   - With 30+ polling loops, even 2 workers is insufficient

2. **Thread Configuration**: `--threads 2` (only 2 threads per worker)
   - Total concurrency: 2 workers × 2 threads = **4 concurrent requests max**
   - With frontend hammering at 792 req/min, this creates massive queuing

3. **No Database Connection Pooling Optimization**
   - Default SQLAlchemy pool size (5 connections)
   - With 4 threads competing for 5 connections, contention occurs

4. **Gunicorn Worker Class**: `gthread` (okay for I/O bound but not optimal for Pi)

## Recommended Optimizations

### 1. Increase Thread Pool (Immediate Impact)

**Current:**
```bash
gunicorn --workers 2 --threads 2  # = 4 concurrent requests
```

**Optimized for Pi 4/5:**
```bash
gunicorn --workers 2 --threads 4  # = 8 concurrent requests
```

**Optimized for Pi 3:**
```bash
gunicorn --workers 1 --threads 6  # = 6 concurrent requests (uses less memory)
```

**Why:** With caching, most requests are fast. More threads allow handling burst traffic.

#### Implementation:
Update `.env`:
```bash
MAX_WORKERS=2
GUNICORN_THREADS=4  # New variable
```

Update Dockerfile CMD:
```bash
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5000 --workers ${MAX_WORKERS:-2} --threads ${GUNICORN_THREADS:-4} --timeout 300 --worker-class gthread --worker-tmp-dir /dev/shm --log-level info --access-logfile - --error-logfile - app:app"]
```

### 2. Optimize Database Connection Pool

**Current:** Default pool_size=5, max_overflow=10

**Add to app.py:**
```python
# Optimize for Pi with limited resources but high concurrency needs
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 8,              # Increased from 5
    'max_overflow': 12,          # Increased from 10
    'pool_pre_ping': True,       # Already set
    'pool_recycle': 3600,        # Already set
    'pool_timeout': 10,          # Add timeout to prevent indefinite waiting
    'connect_args': {
        'connect_timeout': 10,
        'application_name': 'eas_station',  # Help identify queries in pg_stat_activity
    }
}
```

### 3. Enable Database Query Result Caching

Add to `app_core/cache.py`:
```python
from flask_caching import Cache

# Configure query result caching
cache_config = {
    'CACHE_TYPE': os.environ.get('CACHE_TYPE', 'simple'),
    'CACHE_DEFAULT_TIMEOUT': int(os.environ.get('CACHE_DEFAULT_TIMEOUT', '300')),
    'CACHE_KEY_PREFIX': 'eas_',
}

# Add query caching for expensive spatial queries
def cache_query_result(cache_key, ttl):
    """Decorator for caching database query results"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout=ttl)
            return result
        return wrapper
    return decorator
```

### 4. Lazy Load Heavy Queries

**Problem:** Boundary queries with geometries are expensive

**Solution:** Add pagination and limit geometry precision

```python
# In webapp/admin/api.py, update get_boundaries()

# Add query parameter for geometry simplification
simplify = request.args.get('simplify', 'true').lower() == 'true'
tolerance = float(request.args.get('tolerance', '0.001'))

if simplify:
    # Simplify geometries for faster rendering
    boundaries_query = boundaries_query.with_entities(
        Boundary.id,
        Boundary.name,
        Boundary.type,
        func.ST_AsGeoJSON(func.ST_Simplify(Boundary.geom, tolerance)).label('geometry')
    )
else:
    # Full precision (slower)
    boundaries_query = boundaries_query.with_entities(
        Boundary.id,
        Boundary.name,
        Boundary.type,
        func.ST_AsGeoJSON(Boundary.geom).label('geometry')
    )
```

### 5. Add Database Indexes for Hot Paths

**Check existing indexes:**
```sql
-- Connect to postgres
\c alerts
\di
```

**Add missing indexes:**
```sql
-- If not exists, add indexes for commonly filtered columns
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cap_alerts_expires ON cap_alerts(expires);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cap_alerts_status ON cap_alerts(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cap_alerts_source ON cap_alerts(source);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_source_metrics_timestamp ON audio_source_metrics(timestamp DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_health_status_timestamp ON audio_health_status(timestamp DESC);
```

### 6. Optimize Frontend Bundle Size

**Current:** Loading Bootstrap, Font Awesome, and custom JS from CDN

**Optimization:**
1. Use defer/async for non-critical JS
2. Lazy load charts and visualizations
3. Implement code splitting for admin features

**Add to base.html:**
```html
<!-- Defer non-critical scripts -->
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/js/all.min.js"></script>

<!-- Load chart libraries only when needed -->
{% block lazy_scripts %}{% endblock %}
```

### 7. Reduce Logging Overhead

**Add to .env:**
```bash
# Reduce log verbosity in production
LOG_LEVEL=WARNING  # Change from INFO to WARNING
WEB_ACCESS_LOG=false  # Disable access logs (already supported)

# Disable debug logging in audio monitoring
AUDIO_DEBUG_LOGGING=false
```

**Update logging configuration in app.py:**
```python
# Only log INFO+ in production, DEBUG in development
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, log_level.upper(), logging.INFO),
    format='%(levelname)s:%(name)s:%(message)s'
)
```

### 8. Use Filesystem Cache for Multi-Worker Deployments

**Problem:** Simple cache (in-memory) doesn't share between workers

**Solution:** Use filesystem cache on Pi

**Update .env:**
```bash
CACHE_TYPE=filesystem
CACHE_DIR=/tmp/eas-station-cache
CACHE_DEFAULT_TIMEOUT=300
```

**Why:** Filesystem cache on `/tmp` (tmpfs on Pi) is shared between workers and survives worker restarts.

### 9. Optimize Static Asset Delivery

**Add to nginx.conf (if using nginx):**
```nginx
location /static/ {
    alias /app/static/;
    expires 1y;
    add_header Cache-Control "public, immutable";
    gzip on;
    gzip_types text/css application/javascript image/svg+xml;
}
```

**Or add to Flask app.py:**
```python
@app.after_request
def add_header(response):
    if request.path.startswith('/static/'):
        response.cache_control.max_age = 31536000  # 1 year
        response.cache_control.public = True
    return response
```

### 10. Enable Gzip Compression

**Add to gunicorn command:**
```bash
# Not directly supported in gunicorn, use nginx or add Flask-Compress

# Install: pip install flask-compress
# Add to app.py:
from flask_compress import Compress
Compress(app)
```

**Update requirements.txt:**
```
Flask-Compress==1.15
```

## Performance Testing Commands

### Test Current Performance
```bash
# Install apache bench
apt-get install apache2-utils

# Test API endpoint under load
ab -n 1000 -c 10 http://localhost:5000/api/system_status

# Monitor during test
docker exec -it eas-station top
docker exec -it eas-station ps aux
```

### Monitor Database Performance
```bash
# Connect to postgres
docker exec -it postgres psql -U postgres -d alerts

# Check slow queries
SELECT query, calls, mean_exec_time 
FROM pg_stat_statements 
ORDER BY mean_exec_time DESC 
LIMIT 10;

# Check cache hit ratio
SELECT 
    sum(heap_blks_read) as heap_read,
    sum(heap_blks_hit) as heap_hit,
    sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) as cache_hit_ratio
FROM pg_statio_user_tables;
```

### Monitor Cache Effectiveness
```bash
# Check browser console for cache stats
getCacheStats()

# Should see:
# { validEntries: 15, hitRate: 0.92 }
# Hit rate above 85% is good
```

## Implementation Priority

### Phase 1: Immediate (Zero Code Changes)
1. ✅ Client-side caching (already implemented)
2. ✅ Server-side caching (already implemented)
3. Update MAX_WORKERS=2 in .env (if not already set)
4. Set CACHE_TYPE=filesystem in .env
5. Set LOG_LEVEL=WARNING in .env

### Phase 2: Configuration Changes (5 minutes)
1. Add GUNICORN_THREADS environment variable
2. Update Dockerfile CMD to use GUNICORN_THREADS
3. Increase database pool_size to 8
4. Add Flask-Compress for gzip

### Phase 3: Code Optimizations (30 minutes)
1. Add query result caching decorator
2. Optimize boundary query with ST_Simplify
3. Lazy load chart libraries
4. Add missing database indexes

### Phase 4: Advanced (if needed)
1. Consider Redis for cache backend (requires redis container)
2. Implement WebSocket for real-time data (replace polling)
3. Service worker for offline support
4. Consider async workers (uvicorn + FastAPI for async endpoints)

## Expected Results

### Before Optimizations
- Load Time: 5-10 seconds
- API Response: 500-2000ms
- Concurrent Users: 2-3 max
- Audio Stuttering: Frequent
- 503 Errors: Common

### After Phase 1 (Current)
- Load Time: 2-4 seconds
- API Response: 50-200ms (cached)
- Concurrent Users: 5-8
- Audio Stuttering: Rare
- 503 Errors: Uncommon

### After Phase 2
- Load Time: 1-3 seconds
- API Response: 20-100ms (cached)
- Concurrent Users: 10-15
- Audio Stuttering: None
- 503 Errors: Very rare

### After Phase 3
- Load Time: 1-2 seconds
- API Response: 10-50ms (cached)
- Concurrent Users: 20-30
- Audio Stuttering: None
- 503 Errors: None

## Raspberry Pi Model Recommendations

### Pi 3B+ (1GB RAM)
```bash
MAX_WORKERS=1
GUNICORN_THREADS=4
CACHE_TYPE=filesystem
CACHE_DEFAULT_TIMEOUT=600  # Longer cache
```

### Pi 4 (2GB+ RAM)
```bash
MAX_WORKERS=2
GUNICORN_THREADS=4
CACHE_TYPE=filesystem
CACHE_DEFAULT_TIMEOUT=300
```

### Pi 5 (4GB+ RAM)
```bash
MAX_WORKERS=3
GUNICORN_THREADS=4
CACHE_TYPE=filesystem  # or redis
CACHE_DEFAULT_TIMEOUT=300
```

## Troubleshooting

### Still Seeing Slowness?
1. Check cache hit rate: `getCacheStats()` in browser console
2. Check worker count: `docker exec eas-station ps aux | grep gunicorn`
3. Check database connections: `SELECT count(*) FROM pg_stat_activity;`
4. Check memory: `docker stats eas-station`
5. Check for swap usage: `free -h` (swap usage = bad performance)

### Audio Still Stuttering?
1. Verify cache is working (check browser console)
2. Reduce polling intervals further (edit setInterval values)
3. Check CPU usage: `docker exec eas-station top`
4. Consider disabling non-essential features temporarily

### Database Slow?
1. Run `VACUUM ANALYZE;` on postgres
2. Check for missing indexes
3. Consider increasing shared_buffers in PostgreSQL
4. Monitor `pg_stat_statements` for slow queries
