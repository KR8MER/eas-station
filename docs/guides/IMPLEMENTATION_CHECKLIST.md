# Route Permission Implementation Checklist

## Critical Routes Requiring Immediate Protection

### Phase 1: CRITICAL Routes (Must be completed FIRST)

- [ ] **EAS Broadcast Routes** 
  - [ ] File: `webapp/eas/workflow.py` Line 105 - `POST /manual/generate`
    - Add: `@require_permission('eas.broadcast')`
  - [ ] File: `webapp/admin/audio.py` Line 621 - `POST /admin/eas/manual_generate`
    - Add: `@require_permission('eas.broadcast')`
  - Status: CRITICAL - Any authenticated user can broadcast

- [ ] **GPIO Control Routes**
  - [ ] File: `webapp/routes/system_controls.py` Line 171 - `POST /api/gpio/activate/<int:pin>`
    - Add: `@require_permission('gpio.control')`
  - [ ] File: `webapp/routes/system_controls.py` Line 231 - `POST /api/gpio/deactivate/<int:pin>`
    - Add: `@require_permission('gpio.control')`
  - Status: CRITICAL - Can control physical relays

- [ ] **User Management Routes**
  - [ ] File: `webapp/admin/dashboard.py` Line 164 - `GET/POST /admin/users`
    - Add: `@require_permission('system.manage_users')`
  - [ ] File: `webapp/admin/dashboard.py` Line 213 - `PATCH/DELETE /admin/users/<int:user_id>`
    - Add: `@require_permission('system.manage_users')`
  - Status: CRITICAL - Can create/delete users

### Phase 2: HIGH Priority Routes

- [ ] **Receiver/Radio Configuration Routes**
  - [ ] File: `webapp/routes_settings_radio.py` Line 196 - `POST /api/radio/receivers`
    - Add: `@require_permission('receivers.configure')`
  - [ ] File: `webapp/routes_settings_radio.py` Line 219 - `PUT/PATCH /api/radio/receivers/<int:id>`
    - Add: `@require_permission('receivers.configure')`
  - [ ] File: `webapp/routes_settings_radio.py` Line 245 - `DELETE /api/radio/receivers/<int:id>`
    - Add: `@require_permission('receivers.configure')`
  - Status: HIGH - Can misconfigure receivers

- [ ] **Audio/Audio Ingest Routes**
  - [ ] File: `webapp/admin/audio_ingest.py` Line 631 - `POST /api/audio/sources`
    - Add: `@require_permission('receivers.configure')`
  - [ ] File: `webapp/admin/audio_ingest.py` Line 754 - `PATCH /api/audio/sources/<name>`
    - Add: `@require_permission('receivers.configure')`
  - [ ] File: `webapp/admin/audio_ingest.py` Line 834 - `DELETE /api/audio/sources/<name>`
    - Add: `@require_permission('receivers.configure')`
  - [ ] File: `webapp/admin/audio_ingest.py` Line 874 - `POST /api/audio/sources/<name>/start`
    - Add: `@require_permission('receivers.configure')`
  - [ ] File: `webapp/admin/audio_ingest.py` Line 920 - `POST /api/audio/sources/<name>/stop`
    - Add: `@require_permission('receivers.configure')`
  - Status: HIGH - Can stop audio monitoring

- [ ] **System Operations Routes**
  - [ ] File: `webapp/admin/maintenance.py` Line 480 - `POST /admin/operations/upgrade`
    - Add: `@require_permission('system.configure')`
  - [ ] File: `webapp/admin/maintenance.py` Line 573 - `POST /admin/optimize_db`
    - Add: `@require_permission('system.configure')`
  - [ ] File: `webapp/admin/maintenance.py` Line 636 - `GET/POST /admin/env_config`
    - Add: `@require_permission('system.configure')`
  - Status: HIGH - Can break system operations

### Phase 3: MEDIUM Priority Routes

- [ ] **Alert Management Routes**
  - [ ] File: `webapp/admin/maintenance.py` Line 1035 - `PATCH/DELETE /admin/alerts/<int:id>`
    - Add: `@require_permission('alerts.delete')`
  - [ ] File: `webapp/admin/maintenance.py` Line 1212 - `POST /admin/mark_expired`
    - Add: `@require_permission('alerts.delete')`
  - Status: MEDIUM - Can delete alert history

- [ ] **Boundary Management Routes**
  - [ ] File: `webapp/admin/boundaries.py` Line 350 - `POST /admin/upload_boundaries`
    - Add: `@require_permission('system.configure')`
  - [ ] File: `webapp/admin/boundaries.py` Line 442 - `DELETE /admin/clear_boundaries/<type>`
    - Add: `@require_permission('system.configure')`
  - [ ] File: `webapp/admin/boundaries.py` Line 489 - `DELETE /admin/clear_all_boundaries`
    - Add: `@require_permission('system.configure')`
  - Status: MEDIUM - Can modify boundary data

### Phase 4: Demo Role Configuration

- [ ] **Ensure Demo Role has CORRECT permissions:**
  - [ ] Verify `alerts.view` - ALLOWED
  - [ ] Verify `eas.view` - ALLOWED
  - [ ] Verify `system.view_config` - ALLOWED
  - [ ] Verify `receivers.view` - ALLOWED
  - [ ] Verify `gpio.view` - ALLOWED
  - [ ] Verify `logs.view` - ALLOWED (RECOMMENDED)
  
- [ ] **Ensure Demo Role does NOT have:**
  - [ ] ✗ `eas.broadcast` - DENIED
  - [ ] ✗ `eas.manual_activate` - DENIED
  - [ ] ✗ `eas.cancel` - DENIED
  - [ ] ✗ `gpio.control` - DENIED
  - [ ] ✗ `system.configure` - DENIED
  - [ ] ✗ `receivers.configure` - DENIED
  - [ ] ✗ `receivers.delete` - DENIED
  - [ ] ✗ `alerts.create` - DENIED
  - [ ] ✗ `alerts.delete` - DENIED
  - [ ] ✗ `system.manage_users` - DENIED
  - [ ] ✗ `system.view_users` - DENIED
  - [ ] ✗ `logs.export` - DENIED
  - [ ] ✗ `logs.delete` - DENIED

### Phase 5: Testing

- [ ] **Test with ADMIN Role**
  - [ ] All protected routes return 200 or 201 (success)
  - [ ] Can access all admin functions

- [ ] **Test with OPERATOR Role**
  - [ ] Can access EAS broadcast routes
  - [ ] Can access GPIO control routes
  - [ ] Cannot access system.configure routes

- [ ] **Test with VIEWER Role**
  - [ ] Can access read-only routes
  - [ ] Cannot access any write operations

- [ ] **Test with DEMO Role** (CRITICAL)
  - [ ] Can view alerts (/alerts, /api/alerts)
  - [ ] Can view EAS history (/eas, /manual/events)
  - [ ] Can view system config (/settings/environment)
  - [ ] Can view receivers (/api/radio/receivers GET)
  - [ ] Can view GPIO status (/api/gpio/status)
  - [ ] CANNOT initiate broadcast (/manual/generate returns 403)
  - [ ] CANNOT control GPIO (/api/gpio/activate returns 403)
  - [ ] CANNOT modify settings (/api/environment/variables PUT returns 403)
  - [ ] CANNOT manage users (/admin/users returns 403)
  - [ ] CANNOT manage receivers (/api/radio/receivers POST returns 403)

- [ ] **Test with NO ROLE (unauthenticated)**
  - [ ] All /admin routes redirect to login
  - [ ] All /api routes return 401 Unauthorized
  - [ ] Public pages (/, /about, /help) still accessible

### Phase 6: Documentation

- [ ] Update API documentation with permission requirements
- [ ] Create user guide for demo role limitations
- [ ] Document all protected routes in RBAC documentation
- [ ] Add permission requirements to swagger/OpenAPI docs

### Phase 7: Security Review

- [ ] Code review of all permission decorator additions
- [ ] Test with security-focused test cases
- [ ] Verify no permission bypass vulnerabilities
- [ ] Check for missing permission checks on related endpoints

## Code Template for Implementation

### Adding Permission Decorator (Top Pattern)
```python
@require_permission('permission.name')
def route_function():
    """Route documentation."""
    pass
```

### Adding Permission Decorator (Bottom Pattern - as in environment.py)
```python
@app.route('/path/to/route', methods=['POST'])
@require_permission('permission.name')
def route_function():
    """Route documentation."""
    pass
```

### Adding Multiple Permissions (ANY of these)
```python
@require_any_permission('permission.one', 'permission.two')
def route_function():
    """Requires at least one permission."""
    pass
```

### Adding Multiple Permissions (ALL of these)
```python
@require_all_permissions('permission.one', 'permission.two')
def route_function():
    """Requires all permissions."""
    pass
```

## Verification After Implementation

Run this analysis script to verify all routes are protected:
```bash
python3 << 'VERIFY'
import re
import os

unprotected = []
for root, dirs, files in os.walk('/home/user/eas-station/webapp'):
    for file in files:
        if file.endswith('.py'):
            with open(os.path.join(root, file)) as f:
                lines = f.readlines()
                for i, line in enumerate(lines):
                    if '@app.route' in line or '.route(' in line:
                        has_perm = any('@require' in lines[j] for j in range(max(0, i-5), min(i+3, len(lines))))
                        if not has_perm:
                            path = os.path.join(root, file)
                            unprotected.append((path, i+1, line.strip()))

if unprotected:
    print(f"WARNING: {len(unprotected)} unprotected routes found:")
    for path, line, route in unprotected[:10]:
        print(f"  {path.replace('/home/user/eas-station/', '')}:{line} {route}")
else:
    print("SUCCESS: All critical routes are protected!")
VERIFY
```

## Progress Tracking

| Phase | Status | Target Date | Notes |
|-------|--------|-------------|-------|
| Phase 1: CRITICAL | [ ] TODO | Day 1 | Must complete before demo |
| Phase 2: HIGH | [ ] TODO | Day 2 | High priority but not blocking |
| Phase 3: MEDIUM | [ ] TODO | Day 3 | Can be deferred if needed |
| Phase 4: Demo Role | [ ] TODO | Day 4 | Verify all permissions |
| Phase 5: Testing | [ ] TODO | Day 5 | Test all roles thoroughly |
| Phase 6: Documentation | [ ] TODO | Day 6 | Update docs |
| Phase 7: Security Review | [ ] TODO | Day 7 | Final security check |

