# EAS Station Demo Role Implementation Guide

## Critical Security Issues Found

### 1. EAS Broadcast Routes Unprotected (CRITICAL)
- **Routes**: `/manual/generate`, `/admin/eas/manual_generate`
- **Files**: `webapp/eas/workflow.py:105`, `webapp/admin/audio.py:621`
- **Current**: Any authenticated user can initiate broadcasts
- **Risk**: Could trigger false EAS alarms to entire system
- **Solution**: Add `@require_permission('eas.broadcast')` decorator
- **Demo Impact**: Demo role should NOT have `eas.broadcast` permission

### 2. GPIO/Relay Control Unprotected (CRITICAL)
- **Routes**: `/api/gpio/activate/<pin>`, `/api/gpio/deactivate/<pin>`
- **Files**: `webapp/routes/system_controls.py:171`, line 231
- **Current**: Any authenticated user can control physical relays
- **Risk**: Could activate sirens, relays, or other equipment
- **Solution**: Add `@require_permission('gpio.control')` decorator
- **Demo Impact**: Demo role should only have `gpio.view`, NOT `gpio.control`

### 3. System Configuration Routes Unprotected (CRITICAL)
- **Routes**: `/admin/operations/upgrade`, `/admin/optimize_db`, `/admin/env_config`
- **Files**: `webapp/admin/maintenance.py`
- **Current**: Any authenticated user can modify system
- **Risk**: Could break system operations
- **Solution**: Add `@require_permission('system.configure')` decorator
- **Demo Impact**: Demo role should NOT have `system.configure` permission

### 4. User Management Unprotected (CRITICAL)
- **Routes**: `/admin/users` (GET/POST/PATCH/DELETE)
- **Files**: `webapp/admin/dashboard.py:164+`
- **Current**: Some routes lack permission checks entirely
- **Risk**: Could create users or assign roles
- **Solution**: Add `@require_permission('system.manage_users')` decorator
- **Demo Impact**: Demo role should NOT have `system.manage_users` permission

## Recommended Demo Role Permissions

### Allowed Permissions
```
✓ alerts.view
✓ eas.view
✓ system.view_config
✓ receivers.view
✓ gpio.view
✓ logs.view (RECOMMENDED ADDITION)
```

### Denied Permissions
```
✗ eas.broadcast (CRITICAL - Cannot initiate broadcasts)
✗ eas.manual_activate
✗ eas.cancel
✗ gpio.control (CRITICAL - Cannot control relays)
✗ system.configure (CRITICAL - Cannot modify settings)
✗ receivers.configure (HIGH - Cannot modify receivers)
✗ receivers.delete
✗ alerts.create
✗ alerts.delete
✗ system.manage_users
✗ system.view_users
```

## Summary Statistics

- **Total Routes in Application**: 224
- **Routes with Permission Decorators**: 22 (9.8%)
- **Routes WITHOUT Protection**: 202 (90.2%)
- **Critical Unprotected Routes**: 20+

See `ROUTE_SECURITY_ANALYSIS.txt` for full details.
