# Route Registration TypeError - Critical Startup Failure

## Error Signature

```
TypeError: register_eas_monitor_routes() takes 1 positional argument but 2 were given
```

**Impact**: Complete application startup failure - app crashes before workers can start.

---

## Full Error Trace

```python
Traceback (most recent call last):
  File "/app/app.py", line 572, in <module>
    register_routes(app, logger)
  File "/app/webapp/__init__.py", line 83, in register_routes
    module.registrar(app, logger)
TypeError: register_eas_monitor_routes() takes 1 positional argument but 2 were given
```

**Error Location**: App startup (line 572 of app.py)
**Failure Point**: Route module registration loop
**Result**: Worker fails to boot, Gunicorn shuts down master process

---

## Root Cause

### The Pattern

ALL route registration functions in the EAS Station follow this signature:

```python
def register_SOMETHING(app: Flask, logger_instance) -> None:
    """Register routes."""
    # Use the passed logger
    ...
```

**Examples from codebase:**
- `routes_public.register(app, logger)` ✅
- `routes_setup.register(app, logger)` ✅
- `routes_monitoring.register(app, logger)` ✅
- `routes_analytics.register(app, logger)` ✅

### The Violation

When creating `webapp/routes_eas_monitor_status.py`, the function was initially written as:

```python
def register_eas_monitor_routes(app: Flask) -> None:  # ❌ WRONG
    """Register EAS monitoring status routes."""
    ...
```

**Missing**: The second `logger_instance` parameter.

### Why It Failed

The route registration loop in `webapp/__init__.py` calls ALL registrars with TWO arguments:

```python
# Line 83 in webapp/__init__.py
def register_routes(app: Flask, logger) -> None:
    """Register all route groups with the provided Flask application."""

    for module in iter_route_modules():
        try:
            if module.requires_logger:
                module.registrar(app, logger)  # ← ALWAYS passes 2 args!
            else:
                module.registrar(app)
        except TypeError as e:
            logger.error(f"Failed to register route module: {e}")
            raise
```

**Result**: Function expected 1 arg, got 2 → TypeError → startup crash.

---

## Impact Assessment

### Severity: CRITICAL ⚠️

**Application State**: Completely non-functional
**User Impact**: No access to any features
**Data Loss Risk**: None (app never starts)
**Recovery**: Requires code fix + container restart

### Cascading Effects

1. **Alembic migrations fail** - Can't import `app.py`
2. **Gunicorn workers crash** - Can't load WSGI app
3. **Health checks fail** - No HTTP server running
4. **Monitoring alerts** - Container restarts repeatedly

### Detection Indicators

**Logs:**
```
ERROR: Worker failed to boot
ERROR: Shutting down: Master
ERROR: Reason: Worker failed to boot
```

**Container Status:**
```bash
$ docker compose ps
NAME     STATUS
eas_core  Restarting (3)  # ← Continuous crash loop
```

**HTTP Checks:**
```bash
$ curl http://localhost:5000/
curl: (7) Failed to connect  # ← No server listening
```

---

## Fix Applied

### Code Change

**File**: `webapp/routes_eas_monitor_status.py`

**Before (Broken)**:
```python
def register_eas_monitor_routes(app: Flask) -> None:
    """Register EAS monitoring status routes."""
```

**After (Fixed)**:
```python
def register_eas_monitor_routes(app: Flask, logger_instance) -> None:
    """Register EAS monitoring status routes."""
    # Use passed logger if provided
    global logger
    if logger_instance:
        logger = logger_instance
```

**Commit**: `ea5ada2` - "Fix route registration signature - app startup crash"

### Deployment Steps

1. **Code fix committed** - Corrected function signature
2. **Clear bytecode cache** - Remove `.pyc` files
3. **Restart container** - Load corrected code
4. **Verify startup** - Check for successful worker boot

```bash
# Clear cache
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# Restart container
docker compose restart eas_core

# Verify successful startup
docker compose logs eas_core | grep -i "EAS\|Booting worker"
```

---

## Prevention

### Design Pattern Rule

**ALWAYS** follow the standard route registration signature:

```python
def register_MODULENAME_routes(app: Flask, logger_instance) -> None:
    """Register MODULE routes."""
    # Optional: Use passed logger
    global logger
    if logger_instance:
        logger = logger_instance

    # Register routes
    @app.route("/...")
    def endpoint():
        ...

    # Log registration
    logger.info("Registered MODULE routes")
```

### Verification Checklist

When adding new route modules:

- [ ] Function signature matches: `(app: Flask, logger_instance)`
- [ ] Module added to `webapp/__init__.py` imports
- [ ] Module added to `iter_route_modules()` generator
- [ ] `requires_logger=True` (or omitted, defaults to True)
- [ ] Test import: `python -c "from webapp import routes_NEWMODULE"`
- [ ] Test startup: `docker compose restart && docker compose logs`

### Automated Detection

**Pre-commit hook** (recommended):

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Check all route registration functions match pattern
grep -r "^def register.*routes\(" webapp/ | while read -r line; do
    if ! echo "$line" | grep -q "app.*logger"; then
        echo "ERROR: Route registration must accept (app, logger_instance)"
        echo "Found: $line"
        exit 1
    fi
done
```

---

## Related Issues

### Similar Errors in Codebase History

**None documented** - This is the first occurrence of this pattern violation.

### Why This Wasn't Caught Earlier

1. **No route modules added recently** - Established modules all follow pattern
2. **No automated signature checking** - Type hints present but not enforced
3. **Example code worked** - Examples don't use route registration system
4. **Integration tests pass** - Tests mock route registration

### Lessons Learned

1. **Follow established patterns** - Check existing code before creating new modules
2. **Test startup immediately** - Don't wait for full feature completion
3. **Bytecode cache matters** - `.pyc` files can hide fixes
4. **Error messages are precise** - "takes 1 positional argument but 2 were given" = signature mismatch

---

## Testing

### Regression Test

Add to integration test suite:

```python
def test_all_route_registrars_accept_logger():
    """Verify all route registration functions accept (app, logger)."""
    from webapp import iter_route_modules
    from flask import Flask
    import logging

    app = Flask(__name__)
    logger = logging.getLogger(__name__)

    for module in iter_route_modules():
        if module.requires_logger:
            try:
                # Should not raise TypeError
                module.registrar(app, logger)
            except TypeError as e:
                pytest.fail(
                    f"Route module {module.name} has incorrect signature: {e}"
                )
```

### Manual Verification

```bash
# Check function signature
grep -A 2 "def register_eas_monitor_routes" \
    webapp/routes_eas_monitor_status.py

# Expected output:
# def register_eas_monitor_routes(app: Flask, logger_instance) -> None:
#     """Register EAS monitoring status routes."""
```

---

## Recovery Procedure

If this error occurs in production:

### Step 1: Identify the Problem Module

```bash
# Check error logs for module name
docker compose logs eas_core 2>&1 | grep "TypeError.*register"

# Output shows: register_eas_monitor_routes() takes 1 positional argument
#                ^^^^^^^^^^^^^^^^^^^^^^^ - This is the problem module
```

### Step 2: Fix the Signature

```bash
# Edit the file
vi webapp/routes_eas_monitor_status.py

# Change:
# def register_eas_monitor_routes(app: Flask) -> None:
# To:
# def register_eas_monitor_routes(app: Flask, logger_instance) -> None:
#     global logger
#     if logger_instance:
#         logger = logger_instance
```

### Step 3: Clear Cache and Restart

```bash
# Clear Python bytecode cache
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# Commit fix
git add webapp/routes_eas_monitor_status.py
git commit -m "Fix route registration signature"

# Restart container
docker compose restart eas_core

# OR force rebuild if cache persists
docker compose down
docker compose build --no-cache eas_core
docker compose up -d
```

### Step 4: Verify Resolution

```bash
# Check logs for successful startup
docker compose logs eas_core 2>&1 | grep -i "worker\|listening"

# Expected:
# [INFO] Booting worker with pid: 123
# [INFO] Listening at: http://0.0.0.0:5000

# Test endpoint
curl http://localhost:5000/api/eas-monitor/status

# Should return JSON, not connection error
```

---

## Technical Details

### Python Function Signature Matching

Python's function call mechanism:
1. Counts positional arguments passed
2. Matches against function definition
3. Raises TypeError if count doesn't match

```python
# Function expects 1 positional arg
def func(a):
    pass

# Caller passes 2 positional args
func(1, 2)  # TypeError: func() takes 1 positional argument but 2 were given
```

### Docker Python Bytecode Cache

**Location**: `__pycache__/` directories
**Files**: `*.pyc` (compiled Python bytecode)
**Behavior**: Python caches compiled code for faster imports

**Problem**: Container may cache OLD bytecode even after source changes

**Solution**: Clear cache OR restart container (clears interpreter state)

### Gunicorn Worker Boot Process

```
1. Gunicorn master starts
2. Master forks worker processes
3. Each worker imports WSGI app (app.py)
4. app.py calls register_routes()
5. register_routes() loops through modules
6. Calls each module.registrar(app, logger)
7. IF TypeError → worker crashes
8. Master detects worker exit code 3
9. Master shuts down with "Worker failed to boot"
```

---

## References

- **Commit**: `ea5ada2` - "Fix route registration signature - app startup crash"
- **Related**: `1e9f64a` - "Complete end-to-end EAS monitoring integration"
- **Code Pattern**: `webapp/__init__.py:74-90` - Route registration loop
- **Error Handling**: `webapp/__init__.py:83` - TypeError catch

---

**Document Version**: 1.0
**Created**: 2025-11-20
**Last Updated**: 2025-11-20
**Status**: ✅ Resolved in commit `ea5ada2`
