# New Features Documentation

This document outlines all the major backend and frontend features added to EAS Station recently.

## Table of Contents

1. [Role-Based Access Control (RBAC)](#role-based-access-control-rbac)
2. [Multi-Factor Authentication (MFA)](#multi-factor-authentication-mfa)
3. [Audit Logging](#audit-logging)
4. [GPIO Management](#gpio-management)
5. [Analytics System](#analytics-system)
6. [Audio Ingest System](#audio-ingest-system)
7. [VFD Display Management](#vfd-display-management)
8. [Environment Configuration](#environment-configuration)

---

## Role-Based Access Control (RBAC)

### Overview
Comprehensive role and permission management system for fine-grained access control.

### Features
- **Pre-defined Roles**: Admin, Operator, and Viewer
- **Granular Permissions**: Resource-action based permissions (e.g., `alerts.view`, `eas.broadcast`)
- **User Role Assignment**: Assign roles to users with inherited permissions
- **Custom Roles**: Create custom roles with specific permission sets

### Access the UI
Navigate to: **Admin → RBAC Management** (`/admin/rbac`)

### Available Permissions

#### Alerts
- `alerts.view` - View alerts
- `alerts.create` - Create custom alerts
- `alerts.delete` - Delete alerts
- `alerts.export` - Export alert data

#### EAS
- `eas.view` - View EAS configuration
- `eas.broadcast` - Trigger broadcasts
- `eas.manual_activate` - Manual EAS activation
- `eas.cancel` - Cancel active broadcasts

#### System
- `system.configure` - Modify system configuration
- `system.view_config` - View system configuration
- `system.manage_users` - Create/edit/delete users
- `system.view_users` - View user list

#### Logs
- `logs.view` - View system logs
- `logs.export` - Export logs
- `logs.delete` - Delete log entries

#### GPIO
- `gpio.view` - View GPIO status
- `gpio.control` - Activate/deactivate pins

#### API
- `api.read` - Read via API
- `api.write` - Write via API

### API Endpoints
- `GET /security/roles` - List all roles
- `POST /security/roles` - Create new role
- `PUT /security/roles/<id>` - Update role
- `GET /security/permissions` - List all permissions
- `PUT /security/users/<id>/role` - Assign user role

### Code Example
```python
from app_core.auth import require_permission

@app.route('/api/some-endpoint')
@require_permission('alerts.create')
def create_alert():
    # Only users with 'alerts.create' permission can access
    pass
```

---

## Multi-Factor Authentication (MFA)

### Overview
TOTP-based two-factor authentication with backup recovery codes.

### Features
- **TOTP Authentication**: Time-based One-Time Passwords
- **QR Code Enrollment**: Easy setup with authenticator apps
- **Backup Codes**: 10 recovery codes per user
- **Enrollment Flow**: Step-by-step guided setup

### Access the UI
Navigate to: **Admin → Security Settings** (`/security/settings`)

### Supported Authenticator Apps
- Google Authenticator (Android/iOS)
- Microsoft Authenticator (Android/iOS)
- Authy (Android/iOS/Desktop)
- 1Password, LastPass, etc.

### Enrollment Process
1. Click "Enable Two-Factor Authentication"
2. Scan QR code with your authenticator app
3. Enter 6-digit verification code
4. Save backup recovery codes securely

### API Endpoints
- `POST /security/mfa/enroll/start` - Start enrollment
- `GET /security/mfa/enroll/qr` - Get QR code image
- `POST /security/mfa/enroll/verify` - Complete enrollment
- `POST /security/mfa/disable` - Disable MFA

### Audit Events
- `mfa_enrolled` - User enabled MFA
- `mfa_disabled` - User disabled MFA
- `mfa_verified` - Successful MFA login
- `mfa_failed` - Failed MFA attempt

---

## Audit Logging

### Overview
Comprehensive security audit trail with filtering, search, and export capabilities.

### Features
- **24+ Event Types**: Login, logout, config changes, broadcasts, etc.
- **Detailed Context**: IP address, user agent, timestamps
- **Advanced Filtering**: By action, user, status, time period
- **CSV Export**: Export logs for compliance reporting

### Access the UI
Navigate to: **Admin → Audit Logs** (`/admin/audit-logs`)

### Logged Events

#### Authentication
- `login_success`, `login_failure`
- `logout`, `session_expired`

#### MFA
- `mfa_enrolled`, `mfa_disabled`
- `mfa_verified`, `mfa_failed`

#### User Management
- `user_created`, `user_updated`, `user_deleted`
- `user_activated`, `user_deactivated`
- `user_role_changed`

#### System Operations
- `config_updated`, `receiver_configured`
- `eas_broadcast`, `gpio_activated`
- `alert_deleted`, `log_exported`

#### Security
- `permission_denied`, `invalid_token`
- `rate_limit_exceeded`

### API Endpoints
- `GET /security/audit-logs` - List logs with filters
- `GET /security/audit-logs/export` - Export as CSV

### Query Parameters
- `page` - Page number (default: 1)
- `per_page` - Items per page (default: 50, max: 1000)
- `action` - Filter by event type
- `user_id` - Filter by user ID
- `success` - Filter by success/failure
- `days` - Time window (default: 30)

---

## GPIO Management

### Overview
Relay control with activation logging, statistics, and audit trails.

### Features
- **Manual Control**: Activate/deactivate GPIO pins
- **Activation Types**: Manual, automatic, test, override
- **History Timeline**: View recent activations with details
- **Statistics Dashboard**: Usage analytics per pin
- **Watchdog Protection**: Configurable timeout prevents stuck pins

### Access the UI
- **Control Panel**: **Operations → GPIO Control** (`/gpio_control`)
- **Statistics**: **Admin → GPIO Statistics** (`/admin/gpio/statistics`)

### Configuration
Configure via environment settings (Settings → Environment → GPIO Control) or
set the following environment variables:
```bash
EAS_GPIO_PIN=17                           # Primary GPIO pin (BCM numbering)
EAS_GPIO_ACTIVE_STATE=HIGH                # HIGH or LOW when the relay is active
EAS_GPIO_HOLD_SECONDS=5                   # Minimum time before release
EAS_GPIO_WATCHDOG_SECONDS=300             # Safety timeout before auto-release
GPIO_ADDITIONAL_PINS="22:Aux Relay:LOW:2:120"  # Extra pins (one or many)
```

### API Endpoints
- `GET /api/gpio/status` - Get all pin states
- `POST /api/gpio/activate/<pin>` - Activate pin
- `POST /api/gpio/deactivate/<pin>` - Deactivate pin
- `GET /api/gpio/history` - Query activation history
- `GET /api/gpio/statistics` - Get usage statistics

### Activation Log Fields
- `pin` - GPIO pin number
- `activation_type` - manual | automatic | test | override
- `activated_at`, `deactivated_at` - Timestamps
- `duration_seconds` - How long active
- `operator` - Username (for manual/override)
- `alert_id` - Associated alert (for automatic)
- `reason` - Human-readable reason
- `success` - Whether activation succeeded
- `error_message` - Error details if failed

### Statistics
- Total activations by pin
- Success rates
- Average duration
- Activations by type (manual, automatic, test, override)
- Recent errors

---

## Analytics System

### Overview
Metrics aggregation, trend analysis, and anomaly detection for system health monitoring.

### Features
- **Metric Snapshots**: Periodic sampling of system metrics
- **Trend Analysis**: Statistical analysis with forecasting
- **Anomaly Detection**: Z-score and baseline comparison
- **Multi-Period Aggregation**: Hourly, daily, weekly rollups

### Access the UI
Navigate to: **Admin → Analytics Dashboard** (`/analytics`)

### Metric Categories
- **Alert Delivery**: Success rates, latency
- **Audio Health**: Signal quality, health scores
- **Receiver Status**: Availability, uptime
- **GPIO Activity**: Activation patterns
- **Compliance**: FCC compliance metrics

### API Endpoints

#### Metrics
- `GET /api/analytics/metrics` - Query metric snapshots
- `POST /api/analytics/metrics/aggregate` - Trigger aggregation
- `GET /api/analytics/metrics/categories` - List categories

#### Trends
- `GET /api/analytics/trends` - Query trend analysis
- `POST /api/analytics/trends/analyze` - Run trend analysis

#### Anomalies
- `GET /api/analytics/anomalies` - List detected anomalies
- `POST /api/analytics/anomalies/<id>/acknowledge` - Acknowledge
- `POST /api/analytics/anomalies/<id>/resolve` - Mark resolved

### Database Models

#### MetricSnapshot
```python
- category (String) - Metric category
- name (String) - Metric name
- value (Float) - Measured value
- unit (String) - Unit of measurement
- aggregation_period (String) - hourly/daily/weekly
- timestamp (DateTime) - When measured
```

#### TrendRecord
```python
- metric_category, metric_name (String)
- trend_direction (String) - rising/falling/stable
- trend_strength (String) - weak/moderate/strong
- slope, intercept, r_squared (Float) - Linear regression
- percent_change (Float) - Change over period
- analysis_time (DateTime)
```

#### AnomalyRecord
```python
- metric_category, metric_name (String)
- anomaly_type (String) - silence, clipping, disconnect, etc.
- severity (String) - info/warning/error/critical
- detected_at (DateTime)
- acknowledged (Boolean)
- resolved (Boolean)
```

---

## Audio Ingest System

### Overview
Multi-source audio capture with health monitoring and alert generation.

### Features
- **Multiple Source Types**: SDR, ALSA, PulseAudio, file-based
- **Priority-Based Scheduling**: Automatic failover
- **Health Monitoring**: Real-time metrics and scoring
- **Alert Generation**: Silence, clipping, disconnect detection
- **Device Discovery**: Automatic audio device enumeration

### Access the UI
Navigate to: **Operations → Audio Sources** (`/audio/sources`)

### Source Types
- **SDR**: Software-defined radio receivers
- **ALSA**: Advanced Linux Sound Architecture devices
- **PulseAudio**: PulseAudio sound server
- **File**: Pre-recorded audio files

### API Endpoints

#### Source Management
- `GET /api/audio/sources` - List all sources
- `POST /api/audio/sources` - Create source
- `GET /api/audio/sources/<name>` - Get source details
- `PATCH /api/audio/sources/<name>` - Update source
- `DELETE /api/audio/sources/<name>` - Delete source

#### Control
- `POST /api/audio/sources/<name>/start` - Start capturing
- `POST /api/audio/sources/<name>/stop` - Stop capturing

#### Monitoring
- `GET /api/audio/metrics` - Current metrics
- `GET /api/audio/health` - Health status
- `GET /api/audio/alerts` - List alerts
- `GET /api/audio/devices` - Discover devices

### Configuration Parameters
```json
{
  "name": "primary_sdr",
  "source_type": "sdr",
  "priority": 0,
  "enabled": true,
  "auto_start": true,
  "config_params": {
    "frequency_hz": 162550000,
    "sample_rate": 48000,
    "gain": 20,
    "device_index": 0
  },
  "silence_threshold_db": -60,
  "silence_duration_seconds": 5
}
```

### Health Metrics
- `peak_level_db`, `rms_level_db` - Audio levels
- `sample_rate`, `channels` - Audio format
- `frames_captured` - Total frames
- `silence_detected`, `clipping_detected` - Issues
- `buffer_utilization` - Buffer usage percentage
- `health_score` - Overall score (0-100)

---

## VFD Display Management

### Overview
Control Noritake GU140x32F-7000B graphics displays with content queue and priority management.

### Features
- **Content Types**: Text, image, alert, status
- **Priority Levels**: 0=emergency, 1=alert, 2=normal, 3=low
- **Content Queue**: Schedule display content
- **Brightness Control**: 8 levels (0-7)
- **Status Monitoring**: Connection status, error tracking

### Access the UI
Navigate to: **Operations → VFD Display** (`/vfd_control`)

### API Endpoints
- `GET /api/vfd/status` - Get hardware status
- `POST /api/vfd/clear` - Clear display
- `POST /api/vfd/brightness` - Set brightness (0-7)
- `POST /api/vfd/text` - Display text
- `POST /api/vfd/image` - Display image
- `GET /api/vfd/queue` - Get content queue

### Display Content Example
```json
{
  "content_type": "alert",
  "content_data": "SEVERE WEATHER WARNING",
  "priority": 0,
  "x_position": 0,
  "y_position": 0,
  "duration_seconds": 60,
  "scheduled_time": null
}
```

---

## Environment Configuration

### Overview
Web-based environment variable editor with validation and dual-file support.

### Features
- **Dual File Support**: Edit both `.env` and `stack.env`
- **Categorized Variables**: Organized by system sections
- **Validation**: Ensure valid configuration
- **Live Editing**: Update running configuration

### Access the UI
Navigate to: **Settings → Environment Settings** (`/settings/environment`)

### Variable Categories
- **Core**: SECRET_KEY, DATABASE_URL, DEBUG
- **Database**: POSTGRES_* settings
- **Location**: DEFAULT_COUNTY_NAME, DEFAULT_STATE_CODE
- **EAS**: EAS_BROADCAST_ENABLED, EAS_ORIGINATOR
- **GPIO**: EAS_GPIO_PIN, GPIO_ADDITIONAL_PINS
- **Audio**: Audio source configuration
- **API Keys**: External service credentials

### API Endpoints
- `GET /api/environment/categories` - List categories
- `GET /api/environment/variables` - Get all variables
- `PUT /api/environment/variables` - Update variables
- `GET /api/environment/validate` - Validate configuration

---

## Migration Notes

### Database Migrations

All new features require database migrations:

```bash
# Run migrations to create new tables
alembic upgrade head
```

### New Tables Created
- `roles` - User roles
- `permissions` - Available permissions
- `role_permissions` - Role-permission mapping
- `audit_logs` - Security audit trail
- `gpio_activation_logs` - GPIO activation history
- `metric_snapshots` - Time-series metrics
- `trend_records` - Trend analysis results
- `anomaly_records` - Detected anomalies
- `audio_source_configs` - Audio source persistence
- `audio_source_metrics` - Audio metrics
- `audio_health_status` - Audio system health
- `audio_alerts` - Audio system alerts
- `vfd_displays` - VFD display queue
- `vfd_status` - VFD hardware status

### Required Packages
All dependencies are already in `requirements.txt`:
- `pyotp` - TOTP for MFA
- `qrcode` - QR code generation
- `Pillow` - Image processing for QR codes
- `scipy` - Statistical analysis for trends
- `numpy` - Numerical operations

---

## Security Considerations

### Authentication
- All admin endpoints require authentication
- MFA enrollment recommended for all users
- Session management with secure cookies
- CSRF protection on all forms

### Authorization
- Permission checks on all sensitive operations
- Role-based access control enforced
- Audit logging of all security events

### Data Protection
- MFA secrets encrypted at rest
- Backup codes hashed before storage
- Passwords hashed with salts
- Sensitive config masked in UI

---

## Testing

### Manual Testing Checklist

#### RBAC
- [ ] Create custom role
- [ ] Assign permissions to role
- [ ] Assign role to user
- [ ] Verify permission enforcement

#### MFA
- [ ] Enroll with authenticator app
- [ ] Login with TOTP code
- [ ] Use backup code
- [ ] Disable MFA

#### Audit Logs
- [ ] View logs in UI
- [ ] Filter by action type
- [ ] Filter by user
- [ ] Export to CSV

#### GPIO
- [ ] Manual pin activation
- [ ] View activation history
- [ ] Check statistics dashboard
- [ ] Verify error logging

#### Analytics
- [ ] View metrics dashboard
- [ ] Check trend analysis
- [ ] Review anomaly detection
- [ ] Acknowledge/resolve anomalies

#### Audio Ingest
- [ ] Add audio source
- [ ] Start/stop capture
- [ ] Monitor health metrics
- [ ] Review audio alerts

---

## Troubleshooting

### Common Issues

#### "Permission denied" errors
- Verify user has required role
- Check role has necessary permissions
- Review audit logs for details

#### MFA enrollment fails
- Ensure PyOTP and QRCode packages installed
- Check time synchronization on server
- Verify secret not already set

#### GPIO activation not working
- Check GPIO permissions on host
- Verify pin numbers in environment config
- Review GPIO activation logs for errors

#### Analytics data not appearing
- Run manual aggregation: `POST /api/analytics/metrics/aggregate`
- Check database for metric_snapshots entries
- Verify logger is writing metrics

---

## API Authentication

All API endpoints require authentication via session cookies. For API access:

1. Login via `/login` endpoint
2. Session cookie automatically included in subsequent requests
3. CSRF token required for POST/PUT/DELETE requests

Example:
```python
import requests

session = requests.Session()

# Login
session.post('http://localhost:5000/login', json={
    'username': 'admin',
    'password': 'password'
})

# Access protected API
response = session.get('http://localhost:5000/security/roles')
print(response.json())
```

---

## Future Enhancements

### Planned Features
- [ ] LDAP/Active Directory integration
- [ ] API key management for external integrations
- [ ] Advanced role hierarchy with inheritance
- [ ] Real-time websocket updates for dashboards
- [ ] Custom metric definitions via UI
- [ ] Alert rule builder for anomaly detection
- [ ] Scheduled GPIO activations
- [ ] Audio source hot-swapping

---

## Support

For questions or issues:
- GitHub Issues: https://github.com/KR8MER/eas-station/issues
- Documentation: See `/docs` directory
- Community: GitHub Discussions

---

**Last Updated**: 2025-01-06
**Version**: 1.0.0
