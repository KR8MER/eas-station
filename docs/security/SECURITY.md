# EAS Station™ Security Guide

## Overview

EAS Station™ implements comprehensive security controls including Role-Based Access Control (RBAC), Multi-Factor Authentication (MFA), and detailed audit logging. This guide covers setup, configuration, and best practices for securing your EAS Station™ deployment.

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
from app_core.extensions import db

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

EAS Station™ provides three predefined roles:

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
from app_core.extensions import db

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

EAS Station™ supports TOTP-based two-factor authentication compatible with:
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

The audit log is **tamper-evident**: every row is SHA-256 hash-chained to its
predecessor and signed with a station-specific Ed25519 key, so database-level
edits, deletions, and insertions are cryptographically detectable. Verify it
at any time via **System Logs → Audit → Verify Chain Integrity** or
`GET /security/audit-logs/verify`. Full design, threat model, and key
management: [Audit Log Integrity](AUDIT_LOG_INTEGRITY.md).

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
- `alert.received` (recorded automatically on CAP alert ingest)
- `config.updated`
- `gpio.activated` / `gpio.deactivated`
- `alert.deleted` / `log.exported` / `log.deleted`
- `audit.chain.verified` (tamper-evidence verification run)

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

- Run EAS Station™ behind reverse proxy (nginx/Apache)
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
from app_core.extensions import db

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

When deploying security features to existing EAS Station™:

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
- Contact the maintainer: Timothy.Kramer@easstation.com
- File GitHub issue: https://github.com/KR8MER/eas-station/issues

**Security Vulnerabilities:** Report privately via email, not public issues.

---

## Security Features

This section describes the comprehensive security features implemented to protect against malicious login attempts, SQL injection, command injection, and brute force attacks.

### 1. Input Validation

**Location**: `app_core/auth/input_validation.py`

The input validator checks for:
- SQL injection patterns (`' OR 1=1`, `UNION SELECT`, etc.)
- Command injection patterns (`&&`, `||`, `;`, backticks, etc.)
- Non-printable characters
- Overly long inputs

All malicious inputs are:
- Rejected immediately
- Sanitized before logging
- Logged for security analysis
- Trigger automatic IP banning (24 hours)

### 2. Rate Limiting

**Location**: `app_core/auth/rate_limiter.py`

**Configuration**:
- Max attempts: 5 failed logins
- Lockout duration: 15 minutes
- Attempt window: 5 minutes

Features:
- Per-IP tracking of failed attempts
- Automatic lockout after threshold
- Cleanup of old entries

### 3. Flood Protection

**Location**: `app_core/auth/ip_filter.py` (FloodProtection class)

**Configuration**:
- Max attempts per minute: 10
- Auto-ban duration: 1 hour

Detects and automatically bans IPs making rapid-fire login attempts.

### 4. Global Ban List (Allowlist/Blocklist)

**Location**: `app_core/auth/ip_filter.py`

**Database Table**: `ip_filters`

The `ip_filters` table is the **single source of truth** ("Global Ban List").
Bans arrive from several detectors and are acted on by multiple **enforcement
layers** — the application `before_request` gate, the host firewall (via
fail2ban), and fail2ban integration. Administrators manage everything in one
place; there is no separate "fail2ban ban list".

Each blocklist row carries a **`source`** (`IPFilterSource`): `manual`,
`login_brute_force`, `ssh_brute_force`, `malicious_request`, `flood`,
`api_abuse`, `stream_abuse` — surfaced as a badge in the UI. The Security
Center's **Global Ban List** tab also shows an Enforcement Status card, Security
Metrics, and a firewall-sync indicator with one-click Resync (`/security/overview`).

Features:
- **Allowlist**: Trusted IPs/ranges that bypass all checks
- **Blocklist**: Banned IPs/ranges that cannot access the system
- **Source tracking**: which detector/operator added each ban (badged in the UI)
- CIDR range support (e.g., `192.168.1.0/24`)
- Optional expiration times
- Active/inactive toggle
- Manual and automatic entries

**Auto-ban Triggers**:
1. **Malicious Input** (24 hours): SQL/command injection attempt
2. **Brute Force** (24 hours): 5 failed login attempts
3. **Flooding** (1 hour): >10 attempts per minute

### 5. Security Logging

**Location**: `app_core/auth/security_logger.py`

**Log File**: `/var/log/eas-station/security.log`

**Event Types**:
- `MALICIOUS_LOGIN`: SQL/command injection attempt
- `FAILED_LOGIN`: Regular failed login
- `RATE_LIMIT_EXCEEDED`: Too many attempts

**Format** (fail2ban compatible):
```
[YYYY-MM-DD HH:MM:SS UTC] EVENT_TYPE from IP_ADDRESS username=USERNAME details=DETAILS
```

### 6. Audit Logging

**Location**: `app_core/auth/audit.py`

**Database Table**: `audit_logs`

Comprehensive audit trail of all security events including:
- Login successes/failures
- MFA events
- IP filter changes
- Permission denials

---

## fail2ban Integration

### One ban list, two enforcement layers

EAS Station keeps a **single** ban list in the database — the `ip_filters` table,
managed on **Security Center → Banned IPs**. A global `before_request` gate
(`app.py`) checks every request against it, and the application **auto-bans**
malicious / brute-force / flooding IPs into that same table
(`app_core/auth/ip_filter.py`).

fail2ban is an **optional firewall actuator** for that one list — it is *not* a
second ban list. When firewall enforcement is enabled, every application
ban/unban (manual or automatic) is mirrored by `app_core/auth/firewall.py` into a
dedicated `eas-station` fail2ban jail (`bantime = -1`), so the attacker is also
dropped at the host firewall before traffic reaches the web process. fail2ban
does **not** independently scan the web log here; the application performs
detection, so there is nothing to reconcile between two lists.

### Web UI (recommended)

Managed entirely from **Security Center → fail2ban** — no SSH or manual file
editing required:

1. fail2ban ships **pre-installed** (it is in the base package list in both
   `install.sh` and `update.sh`), so there is nothing to install. If the tab
   reports it missing, run `sudo bash update.sh` to restore it.
2. Toggle **Mirror application bans to the host firewall** and click
   **Save & Apply**. EAS Station writes `/etc/fail2ban/jail.local`, restarts the
   service, and resyncs the current ban list into the firewall.
3. Continue to add/remove/review web bans on the **Banned IPs** tab — they are
   mirrored automatically. Use **Resync bans** if the firewall and database ever
   drift (e.g. after a manual fail2ban restart).
4. Optionally enable **Protect host SSH daemon** (`sshd` jail). fail2ban bans SSH
   brute-force attempts the app cannot see (they hit port 22 directly). Because an
   IP hammering SSH is a bad actor everywhere, these offenders are **automatically
   imported into the unified ban list** (so they're blocked at the web layer and,
   when enforcement is on, at all ports on the host firewall). They're also listed
   on the fail2ban tab; unbanning there clears them from the global list too. The
   import is one-way and idempotent. It runs continuously in the background (a
   sync scheduler, `app_core/fail2ban_sync.py`, started with the web app), so SSH
   bans reach the Global Ban List even with the UI closed — and also on tab
   refresh and on **Resync bans**.

Settings persist in the `fail2ban_settings` table (survives upgrades). The UI
calls `webapp/admin/fail2ban.py`, which runs privileged commands via the sudoers
entries in `config/sudoers-eas-station`. Because the application-level gate always
applies, web bans remain enforced even if fail2ban is stopped — the firewall layer
is purely additive defence-in-depth.

### Manual configuration (advanced / reference)

You normally never need this. For reference, the legacy log-scanning jail/filter
approach (if you prefer fail2ban to parse the security log directly instead of
being driven by the application) is:

1. **Install fail2ban**:
```bash
sudo apt-get install fail2ban
```

2. **Configure Jail** (`/etc/fail2ban/jail.local`):
```ini
[eas-station-malicious]
enabled = true
port = http,https
filter = eas-station-malicious
logpath = /var/log/eas-station/security.log
maxretry = 1
bantime = 3600
findtime = 600

[eas-station-auth]
enabled = true
port = http,https
filter = eas-station-auth
logpath = /var/log/eas-station/security.log
maxretry = 5
bantime = 1800
findtime = 600
```

3. **Create Malicious Filter** (`/etc/fail2ban/filter.d/eas-station-malicious.conf`):
```ini
[Definition]
failregex = ^.*MALICIOUS_LOGIN from <HOST>.*$
ignoreregex =
```

4. **Create Auth Filter** (`/etc/fail2ban/filter.d/eas-station-auth.conf`):
```ini
[Definition]
failregex = ^.*(FAILED_LOGIN|RATE_LIMIT_EXCEEDED) from <HOST>.*$
ignoreregex =
```

5. **Restart fail2ban**:
```bash
sudo systemctl restart fail2ban
```

### Testing fail2ban

```bash
# Check status
sudo fail2ban-client status eas-station-malicious
sudo fail2ban-client status eas-station-auth

# View banned IPs
sudo fail2ban-client get eas-station-malicious banned

# Unban an IP
sudo fail2ban-client set eas-station-malicious unbanip 192.168.1.1
```

---

## IP Filter Web Interface

### Malicious Login Attempts Page

**URL**: `/admin/malicious-logins`

**Features**:
- View all malicious login attempts
- Statistics dashboard (total attempts, unique IPs, today's attempts)
- Top attacking IP addresses
- Quick ban from statistics
- fail2ban configuration viewer

### IP Filter Management

**Location**: Same page as malicious logins

**Actions**:
- Add to allowlist/blocklist
- Support for single IPs or CIDR ranges
- Set expiration time (blocklist only)
- Toggle active/inactive
- Delete filters
- View reason and description
- **Geolocation**: each entry shows a country flag, city, region and country
  (IPv4 and IPv6) when a MaxMind GeoLite2 database is configured under Settings →
  Traffic Analytics. Resolution is best-effort and offline — no database means a
  blank location and no network calls; CIDR ranges and local addresses show none.

**Example Allowlist Entries**:
- `192.168.1.0/24` - Internal network
- `10.0.0.5` - Admin workstation

**Example Blocklist Entries**:
- `1.2.3.4` - Known attacker
- `5.6.7.0/24` - Malicious subnet

### IP Filter API Endpoints

- `GET /security/ip-filters` - List all filters
- `POST /security/ip-filters` - Add new filter
- `DELETE /security/ip-filters/<id>` - Delete filter
- `POST /security/ip-filters/<id>/toggle` - Toggle active status
- `POST /security/ip-filters/cleanup` - Clean up expired filters
- `GET /security/malicious-login-attempts` - List malicious attempts with IP statistics

---

## Security Feature Configuration

### Rate Limiting

Edit `app_core/auth/rate_limiter.py`:
```python
MAX_ATTEMPTS = 5  # Maximum failed attempts before lockout
LOCKOUT_DURATION = timedelta(minutes=15)  # How long to lock out
ATTEMPT_WINDOW = timedelta(minutes=5)  # Time window to count attempts
```

### Flood Protection

Edit `app_core/auth/ip_filter.py`:
```python
MAX_ATTEMPTS_PER_MINUTE = 10  # Max attempts per minute
FLOOD_BAN_HOURS = 1  # Ban duration for flooding
```

### Auto-Ban

Edit `app_core/auth/ip_filter.py`:
```python
FAILED_ATTEMPTS_THRESHOLD = 5  # Failed attempts before auto-ban
BAN_DURATION_HOURS = 24  # Ban duration
```

---

## Security Monitoring

Recommended monitoring:
- Track failed login attempts per hour
- Alert on >50 malicious attempts in 1 hour
- Alert on auto-ban triggers
- Weekly review of blocklist entries
- Monitor fail2ban ban count

---

## Locked Out Admin

If an admin IP is accidentally blocked:

1. **Via Database**:
```sql
DELETE FROM ip_filters WHERE ip_address = '1.2.3.4';
```

2. **Via fail2ban**:
```bash
sudo fail2ban-client set eas-station-auth unbanip 1.2.3.4
```

### Check Security Logs

```bash
tail -f /var/log/eas-station/security.log
```
