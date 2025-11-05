# Security Features Migration Guide

Quick guide for deploying the new security features (RBAC + MFA) to an existing EAS Station installation.

## Prerequisites

- Existing EAS Station installation (v2.3.14 or later)
- Admin access to the system
- Database backup completed

## Step-by-Step Migration

### 1. Backup Current System

```bash
# Backup database
docker-compose exec alerts-db pg_dump -U postgres eas_station > backup_$(date +%Y%m%d).sql

# Backup configuration
cp .env .env.backup
```

### 2. Pull Latest Code

```bash
git fetch origin
git checkout claude/session-planning-011CUq5efSfi6YHh5ch91m2C
```

### 3. Update Dependencies

```bash
# Rebuild container with new dependencies (pyotp, qrcode)
docker-compose build app

# Or install directly if not using Docker
pip install -r requirements.txt
```

### 4. Run Database Migration

```bash
# Apply migration
docker-compose exec app flask db upgrade

# Verify migration succeeded
docker-compose exec alerts-db psql -U postgres -d eas_station -c "\dt" | grep -E "roles|permissions|audit_logs"
```

Expected output:
```text
 public | audit_logs        | table | postgres
 public | permissions       | table | postgres
 public | role_permissions  | table | postgres
 public | roles             | table | postgres
```

### 5. Initialize Default Roles

```bash
# Start application
docker-compose up -d app

# Wait for app to be ready
sleep 5

# Initialize roles via Flask shell
docker-compose exec app flask shell
```

In Flask shell:
```python
from app_core.auth.roles import initialize_default_roles_and_permissions
initialize_default_roles_and_permissions()
exit()
```

Or via API (if already logged in):
```bash
curl -X POST http://localhost:5000/security/init-roles \
  -H "Content-Type: application/json" \
  -b cookies.txt
```

### 6. Assign Roles to Existing Users

#### Option A: Via Flask Shell

```bash
docker-compose exec app flask shell
```

```python
from app_core.models import AdminUser
from app_core.auth.roles import Role
from app_core.db import db

# Get admin role
admin_role = Role.query.filter_by(name='admin').first()

# Assign to all existing users (or specific users)
users = AdminUser.query.all()
for user in users:
    user.role_id = admin_role.id
    print(f"Assigned admin role to {user.username}")

db.session.commit()
print("All users updated!")
exit()
```

#### Option B: Via API

```bash
# Get user ID
curl http://localhost:5000/admin/users | jq '.users[] | {id, username}'

# Assign role (role_id: 1=admin, 2=operator, 3=viewer)
curl -X PUT http://localhost:5000/security/users/1/role \
  -H "Content-Type: application/json" \
  -d '{"role_id": 1}' \
  -b cookies.txt
```

### 7. Verify Role Assignment

```bash
docker-compose exec app flask shell
```

```python
from app_core.models import AdminUser

users = AdminUser.query.all()
for user in users:
    role_name = user.role.name if user.role else "NO ROLE"
    print(f"{user.username}: {role_name}")
exit()
```

### 8. Test Login

```bash
# Test login still works
curl -X POST http://localhost:5000/login \
  -d "username=admin&password=yourpassword" \
  -c cookies.txt \
  -L

# Verify you can access protected routes
curl http://localhost:5000/admin \
  -b cookies.txt
```

### 9. Enable MFA for Admin Users (Recommended)

For each admin user:

1. Log in to web UI
2. Navigate to profile/security settings (or use API)
3. Click "Enable Two-Factor Authentication"
4. Scan QR code with authenticator app
5. Enter verification code
6. Save backup codes securely

Via API:
```bash
# Start enrollment
curl -X POST http://localhost:5000/security/mfa/enroll/start \
  -b cookies.txt

# Get QR code
curl http://localhost:5000/security/mfa/enroll/qr \
  -b cookies.txt \
  -o mfa_qr.png

# Complete enrollment (after scanning QR)
curl -X POST http://localhost:5000/security/mfa/enroll/verify \
  -H "Content-Type: application/json" \
  -d '{"code": "123456"}' \
  -b cookies.txt
```

### 10. Review Audit Logs

```bash
# Check audit logs are working
curl 'http://localhost:5000/security/audit-logs?days=1' \
  -b cookies.txt | jq '.logs[] | {action, username, timestamp}'
```

### 11. Update Documentation/Procedures

- Update operator procedures with new login flow (MFA)
- Document role assignments for your organization
- Update backup procedures to include audit logs

## Post-Migration Checklist

- [ ] All existing users have roles assigned
- [ ] Test login with each role type
- [ ] Admin users enrolled in MFA
- [ ] Test MFA login flow
- [ ] Audit logs populating correctly
- [ ] Permission decorators working (403 on unauthorized routes)
- [ ] HTTPS enabled (if production)
- [ ] Session timeout configured appropriately
- [ ] Backup procedures updated
- [ ] Operator documentation updated

## Rollback Procedure

If issues occur:

```bash
# Revert code
git checkout main

# Restore database backup
docker-compose down
docker-compose up -d alerts-db
docker-compose exec -T alerts-db psql -U postgres -d eas_station < backup_YYYYMMDD.sql

# Restart all services
docker-compose up -d
```

## Common Issues

### Issue: "User has no role" - 403 errors on all routes

**Fix:** Assign roles to all users (Step 6)

### Issue: Migration fails with "column already exists"

**Fix:** Migration is idempotent. Check existing schema:
```bash
docker-compose exec alerts-db psql -U postgres -d eas_station -c "\d admin_users"
```

If columns exist, migration already ran successfully.

### Issue: Cannot import pyotp/qrcode

**Fix:** Rebuild container or reinstall dependencies:
```bash
docker-compose build --no-cache app
docker-compose up -d app
```

### Issue: Existing sessions broken after migration

**Expected:** Users need to log in again after migration. Sessions are regenerated.

## Monitoring After Migration

Monitor for 24-48 hours:

```bash
# Watch application logs
docker-compose logs -f app | grep -E "ERROR|WARNING|permission"

# Monitor failed login attempts
watch -n 60 'curl -s http://localhost:5000/security/audit-logs?action=auth.login.failure -b cookies.txt | jq ".logs | length"'

# Check for permission denied events
curl 'http://localhost:5000/security/audit-logs?action=security.permission_denied&days=1' \
  -b cookies.txt
```

## Getting Help

- Review `/docs/SECURITY.md` for detailed documentation
- Check audit logs for specific error details
- Review application logs: `docker-compose logs app`
- File GitHub issue with migration details

## Migration Success Criteria

✅ Database migration completed without errors
✅ Default roles created (admin, operator, viewer)
✅ All existing users have roles assigned
✅ Login functionality works for all users
✅ Permission decorators enforcing access control
✅ Audit logs recording security events
✅ MFA enrollment workflow functional
✅ MFA login flow tested successfully
✅ No errors in application logs
✅ System health checks passing

---

**Estimated migration time:** 15-30 minutes
**Downtime required:** ~2 minutes (database migration only)
**Recommended window:** During maintenance period with operator notification
