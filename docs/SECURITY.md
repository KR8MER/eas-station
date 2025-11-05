# EAS Station Security Guide

## Overview

EAS Station implements comprehensive security controls including Role-Based Access Control (RBAC), Multi-Factor Authentication (MFA), and detailed audit logging. This guide covers setup, configuration, and best practices for securing your EAS Station deployment.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Role-Based Access Control](#role-based-access-control)
3. [Multi-Factor Authentication](#multi-factor-authentication)
4. [Audit Logging](#audit-logging)
5. [API Endpoints](#api-endpoints)
6. [Security Best Practices](#security-best-practices)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

### 1. Apply Database Migration

After pulling the latest changes, apply the security migration:

```bash
docker-compose exec app flask db upgrade
```

### 2. Initialize Default Roles

Initialize the three default roles (admin, operator, viewer) and their permissions:

```bash
curl -X POST http://localhost:5000/security/init-roles \
  -H "Content-Type: application/json" \
  -b cookies.txt
```

Or use the API endpoint after logging in as an admin.

### 3. Assign Roles to Users

Assign roles to existing users:

```python
from app_core.models import AdminUser
from app_core.auth.roles import Role
from app_core.db import db

# Get user and role
user = AdminUser.query.filter_by(username='your_username').first()
admin_role = Role.query.filter_by(name='admin').first()

# Assign role
user.role_id = admin_role.id
db.session.commit()
```

Or via API:

```bash
curl -X PUT http://localhost:5000/security/users/1/role \
  -H "Content-Type: application/json" \
  -d '{"role_id": 1}' \
  -b cookies.txt
```

---

## Role-Based Access Control

### Default Roles

EAS Station provides three predefined roles:

#### 1. **Admin** (Full Access)
- All system permissions
- User and role management
- System configuration
- Alert and EAS operations
- Log management
- GPIO and hardware control

#### 2. **Operator** (Operations Access)
- Alert viewing and creation
- EAS broadcast and manual activation
- GPIO control
- Log viewing and export
- **Cannot**: Manage users, modify system configuration, delete data

#### 3. **Viewer** (Read-Only)
- View alerts, logs, and system status
- Export logs
- **Cannot**: Create/delete data, broadcast EAS, control GPIO, manage users

### Permission Model

Permissions follow the format: `resource.action`

**Resources:**
- `alerts` - CAP alerts and EAS messages
- `eas` - EAS broadcast operations
- `system` - System configuration and user management
- `logs` - System and audit logs
- `receivers` - SDR receivers
- `gpio` - GPIO relay control
- `api` - API access

**Actions:**
- `view` - Read access
- `create` - Create new records
- `delete` - Delete records
- `export` - Export data
- `configure` - Modify configuration
- `control` - Activate/control hardware
- `manage_users` - User administration

### Using Permission Decorators

In your route handlers:

```python
from app_core.auth.roles import require_permission

@app.route('/admin/users')
@require_permission('system.manage_users')
def manage_users():
    # Only accessible by users with system.manage_users permission
    pass

@app.route('/alerts')
@require_permission('alerts.view')
def view_alerts():
    # Accessible by users with alerts.view permission
    pass
```

Multiple permission patterns:

```python
from app_core.auth.roles import require_any_permission, require_all_permissions

# Require ANY of these permissions
@require_any_permission('alerts.view', 'alerts.create')
def alerts_page():
    pass

# Require ALL of these permissions
@require_all_permissions('alerts.delete', 'system.configure')
def critical_operation():
    pass
```

### Checking Permissions Programmatically

```python
from app_core.auth.roles import has_permission

if has_permission('eas.broadcast'):
    # User can broadcast
    pass
```

### Creating Custom Roles

Via Python:

```python
from app_core.auth.roles import Role, Permission
from app_core.db import db

# Create a custom role
custom_role = Role(
    name='technician',
    description='Technical support staff with limited access'
)

# Assign specific permissions
perms = Permission.query.filter(Permission.name.in_([
    'receivers.view',
    'receivers.configure',
    'logs.view',
    'system.view_config'
])).all()

custom_role.permissions.extend(perms)
db.session.add(custom_role)
db.session.commit()
```

Via API:

```bash
curl -X POST http://localhost:5000/security/roles \
  -H "Content-Type: application/json" \
  -d '{
    "name": "technician",
    "description": "Technical support role",
    "permission_ids": [1, 2, 5, 8]
  }' \
  -b cookies.txt
```

---

## Multi-Factor Authentication

### Overview

EAS Station supports TOTP-based two-factor authentication compatible with:
- Google Authenticator
- Microsoft Authenticator
- Authy
- Any RFC 6238 compliant authenticator app

### Enrolling in MFA

#### 1. Start Enrollment

```bash
curl -X POST http://localhost:5000/security/mfa/enroll/start \
  -b cookies.txt
```

Response includes:
```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "provisioning_uri": "otpauth://totp/EAS%20Station:username?secret=...",
  "message": "Scan the QR code with your authenticator app..."
}
```

#### 2. Get QR Code

Open in browser while logged in:
```
http://localhost:5000/security/mfa/enroll/qr
```

Or via curl:
```bash
curl http://localhost:5000/security/mfa/enroll/qr \
  -b cookies.txt \
  -o mfa_qr.png
```

#### 3. Verify Setup

Enter the 6-digit code from your authenticator app:

```bash
curl -X POST http://localhost:5000/security/mfa/enroll/verify \
  -H "Content-Type: application/json" \
  -d '{"code": "123456"}' \
  -b cookies.txt
```

Response includes:
```json
{
  "success": true,
  "backup_codes": [
    "A1B2C3D4",
    "E5F6G7H8",
    ...
  ],
  "message": "MFA enrolled successfully..."
}
```

**IMPORTANT:** Save your backup codes in a secure location!

### Login Flow with MFA

1. Enter username and password
2. If MFA is enabled, redirected to `/mfa/verify`
3. Enter 6-digit TOTP code from authenticator app
4. Alternatively, use an 8-character backup code
5. Session established after successful verification

### MFA Session Timeout

- Partial authentication (post-password) expires in **5 minutes**
- Must complete MFA verification within timeout window
- Expired sessions require starting login process again

### Backup Codes

- 10 backup codes generated during enrollment
- Each code is single-use
- 8 characters, alphanumeric (e.g., "A1B2C3D4")
- Hashed in database (bcrypt)
- Used when authenticator app unavailable

### Disabling MFA

Requires password confirmation:

```bash
curl -X POST http://localhost:5000/security/mfa/disable \
  -H "Content-Type: application/json" \
  -d '{"password": "your_password"}' \
  -b cookies.txt
```

### Checking MFA Status

```bash
curl http://localhost:5000/security/mfa/status \
  -b cookies.txt
```

---

## Audit Logging

### Overview

All security-sensitive operations are logged to the `audit_logs` table with:
- Timestamp (UTC)
- User ID and username
- Action type (e.g., `auth.login.success`, `mfa.enrolled`)
- Resource affected (type and ID)
- IP address and user agent
- Success/failure status
- Additional details (JSON)

### Audit Actions Tracked

**Authentication:**
- `auth.login.success` / `auth.login.failure`
- `auth.logout`
- `auth.session.expired`

**MFA:**
- `mfa.enrolled` / `mfa.disabled`
- `mfa.verify.success` / `mfa.verify.failure`
- `mfa.backup_code.used`

**User Management:**
- `user.created` / `user.updated` / `user.deleted`
- `user.activated` / `user.deactivated`
- `user.role.changed`
- `user.password.changed`

**Permissions:**
- `role.created` / `role.updated` / `role.deleted`
- `permission.granted` / `permission.revoked`

**Operations:**
- `eas.broadcast` / `eas.manual_activation` / `eas.cancellation`
- `config.updated`
- `gpio.activated` / `gpio.deactivated`
- `alert.deleted` / `log.exported` / `log.deleted`

**Security Events:**
- `security.permission_denied`
- `security.invalid_token`
- `security.rate_limit_exceeded`

### Viewing Audit Logs

#### Via API

```bash
# Recent logs (last 30 days)
curl 'http://localhost:5000/security/audit-logs?days=30' \
  -b cookies.txt

# Filter by user
curl 'http://localhost:5000/security/audit-logs?user_id=1' \
  -b cookies.txt

# Filter by action
curl 'http://localhost:5000/security/audit-logs?action=auth.login.failure' \
  -b cookies.txt

# Only failed operations
curl 'http://localhost:5000/security/audit-logs?success=false' \
  -b cookies.txt
```

#### Export as CSV

```bash
curl 'http://localhost:5000/security/audit-logs/export?days=90' \
  -b cookies.txt \
  -o audit_logs.csv
```

### Programmatic Logging

```python
from app_core.auth.audit import AuditLogger, AuditAction

# Simple logging
AuditLogger.log(
    action=AuditAction.CONFIG_UPDATED,
    resource_type='audio_source',
    resource_id='1',
    details={'field': 'volume', 'old_value': 0.8, 'new_value': 0.9}
)

# Convenience methods
AuditLogger.log_login_success(user_id, username)
AuditLogger.log_permission_denied(user_id, username, 'system.configure', '/admin/settings')
```

### Retention Management

Clean up old audit logs:

```python
from app_core.auth.audit import AuditLogger

# Delete logs older than 90 days
deleted_count = AuditLogger.cleanup_old_logs(days=90)
```

Recommended retention: **90 days** (FCC compliance may require longer)

---

## API Endpoints

### Authentication
- `POST /login` - Username/password authentication
- `POST /mfa/verify` - MFA verification
- `GET /logout` - Sign out

### MFA Management
- `GET /security/mfa/status` - Check MFA status
- `POST /security/mfa/enroll/start` - Start MFA enrollment
- `GET /security/mfa/enroll/qr` - Get QR code image
- `POST /security/mfa/enroll/verify` - Complete enrollment
- `POST /security/mfa/disable` - Disable MFA

### Role Management
- `GET /security/roles` - List all roles
- `GET /security/roles/<id>` - Get role details
- `POST /security/roles` - Create custom role
- `PUT /security/roles/<id>` - Update role
- `GET /security/permissions` - List all permissions
- `PUT /security/users/<id>/role` - Assign role to user

### Audit Logs
- `GET /security/audit-logs` - List audit logs (paginated, filterable)
- `GET /security/audit-logs/export` - Export logs as CSV

### Utilities
- `POST /security/init-roles` - Initialize default roles
- `POST /security/permissions/check` - Check if user has permission

---

## Security Best Practices

### 1. **Enable MFA for All Admin Users**

Require MFA for users with `admin` role:

```python
# Enforce MFA policy
admin_users = AdminUser.query.join(Role).filter(Role.name == 'admin').all()
for user in admin_users:
    if not user.mfa_enabled:
        # Send notification to enable MFA
        pass
```

### 2. **Principle of Least Privilege**

- Assign `viewer` role by default
- Grant `operator` role only when needed
- Limit `admin` role to system administrators

### 3. **Regular Audit Log Review**

Schedule weekly reviews:

```bash
# Failed login attempts
curl 'http://localhost:5000/security/audit-logs?action=auth.login.failure&days=7' \
  -b cookies.txt

# Permission denied events
curl 'http://localhost:5000/security/audit-logs?action=security.permission_denied&days=7' \
  -b cookies.txt
```

### 4. **Session Management**

Configure secure session settings in `app.py`:

```python
app.config['SESSION_COOKIE_SECURE'] = True       # HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True     # Prevent JavaScript access
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour timeout
```

### 5. **Network Security**

- Run EAS Station behind reverse proxy (nginx/Apache)
- Enable HTTPS with valid TLS certificates
- Use firewall rules to restrict admin access
- Consider VPN for remote administration

### 6. **Password Policies**

Implement strong password requirements:

```python
import re

def validate_password(password):
    """Enforce password complexity."""
    if len(password) < 12:
        return False, "Password must be at least 12 characters"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain lowercase letter"
    if not re.search(r'[0-9]', password):
        return False, "Password must contain number"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain special character"
    return True, "Valid"
```

### 7. **Backup Security Data**

Regularly backup:
- User accounts and roles
- Audit logs (before cleanup)
- Security configuration

```bash
pg_dump -U postgres -d eas_station -t admin_users -t roles -t permissions -t audit_logs > security_backup.sql
```

### 8. **Monitor for Anomalies**

Set up alerts for:
- Multiple failed login attempts
- MFA verification failures
- Permission denied events
- Unexpected role changes
- Admin account creation

---

## Troubleshooting

### User Cannot Log In After Migration

**Symptom:** User has no role assigned, all routes return 403 Forbidden

**Solution:** Assign a role to the user

```python
from app_core.models import AdminUser
from app_core.auth.roles import Role
from app_core.db import db

user = AdminUser.query.filter_by(username='username').first()
admin_role = Role.query.filter_by(name='admin').first()
user.role_id = admin_role.id
db.session.commit()
```

### MFA Enrollment Fails

**Symptom:** "pyotp is required" error

**Solution:** Ensure dependencies are installed

```bash
pip install pyotp==2.9.0 qrcode==8.0
# Or rebuild Docker container
docker-compose build app
```

### QR Code Not Displaying

**Symptom:** 500 error when accessing `/security/mfa/enroll/qr`

**Solution:** Check that Pillow is installed

```bash
pip install Pillow==10.4.0
```

### Permission Decorator Not Working

**Symptom:** Routes accessible even without permission

**Solution:** Ensure user has a role assigned and role has the required permission

```python
from app_core.auth.roles import has_permission

# Debug permission check
user_id = session.get('user_id')
user = AdminUser.query.get(user_id)
print(f"User role: {user.role.name if user.role else None}")
print(f"Has permission: {has_permission('alerts.view')}")
```

### Audit Logs Growing Too Large

**Symptom:** Database size increasing rapidly

**Solution:** Implement scheduled cleanup

```python
# Add to scheduled task (cron/celery)
from app_core.auth.audit import AuditLogger

# Keep 90 days of logs
AuditLogger.cleanup_old_logs(days=90)
```

### Session Expires During MFA

**Symptom:** "Session expired. Please log in again." after entering password

**Solution:** Complete MFA verification within 5 minutes. If consistently timing out, increase timeout:

```python
# In app_core/auth/mfa.py
class MFASession:
    TIMEOUT_MINUTES = 10  # Increase from 5 to 10
```

---

## Migration Checklist

When deploying security features to existing EAS Station:

- [ ] Pull latest code from security branch
- [ ] Install new dependencies: `pip install -r requirements.txt`
- [ ] Run database migration: `flask db upgrade`
- [ ] Initialize default roles: `POST /security/init-roles`
- [ ] Assign roles to all existing users
- [ ] Test login with each role
- [ ] Enroll MFA for admin users
- [ ] Test MFA login flow
- [ ] Review audit log functionality
- [ ] Update documentation/procedures
- [ ] Configure log retention policy
- [ ] Set up audit log monitoring
- [ ] Enable HTTPS if not already active
- [ ] Review session timeout settings

---

## Additional Resources

- **RFC 6238**: TOTP Algorithm Specification
- **NIST SP 800-63B**: Digital Identity Guidelines (Authentication)
- **OWASP Authentication Cheat Sheet**: https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- **47 CFR Part 11**: FCC EAS Regulations (compliance requirements)

---

## Support

For security issues or questions:
- Review audit logs for suspicious activity
- Check system logs: `docker-compose logs app`
- Contact: security@eas-station.example.com (update with your contact)
- File GitHub issue: https://github.com/your-repo/eas-station/issues

**Security Vulnerabilities:** Report privately via email, not public issues.
