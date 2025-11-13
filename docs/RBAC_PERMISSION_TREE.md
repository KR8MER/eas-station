# RBAC Permission Tree - EAS Station

## Overview

This document provides a comprehensive view of which roles can access which features in the EAS Station system.

**Last Updated**: 2025-11-09
**Total Permissions**: 22
**Total Roles**: 4 (Admin, Operator, Viewer, Demo)

---

## Role Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                        ADMIN (Full Access)                       │
│  All 22 permissions - Complete system control                   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
┌───────────────────▼─────────┐   ┌───────────▼──────────────────┐
│   OPERATOR (16 permissions) │   │   VIEWER (10 permissions)    │
│ Can broadcast & control     │   │   Read-only monitoring       │
└─────────────────────────────┘   └──────────────────────────────┘
                                              │
                                   ┌──────────▼──────────────────┐
                                   │   DEMO (4 permissions)      │
                                   │   Limited demo access       │
                                   └─────────────────────────────┘
```

---

## Permission Matrix

### Legend
- ✅ = Permission granted
- ❌ = Permission denied
- 🔒 = Route currently unprotected (security issue)

| Permission | Admin | Operator | Viewer | Demo | What It Controls |
|-----------|-------|----------|--------|------|------------------|
| **ALERTS** |
| alerts.view | ✅ | ✅ | ✅ | ✅ | View alerts, alert history, map 🔒 |
| alerts.create | ✅ | ✅ | ❌ | ❌ | Create manual CAP alerts 🔒 |
| alerts.delete | ✅ | ❌ | ❌ | ❌ | Delete CAP alerts 🔒 |
| alerts.export | ✅ | ✅ | ✅ | ❌ | Export alert data to CSV/JSON 🔒 |
| **EAS BROADCAST** |
| eas.view | ✅ | ✅ | ✅ | ✅ | View EAS workflow, message history 🔒 |
| eas.broadcast | ✅ | ✅ | ❌ | ❌ | Initiate EAS broadcasts 🔒 CRITICAL |
| eas.manual_activate | ✅ | ✅ | ❌ | ❌ | Manually activate EAS equipment 🔒 |
| eas.cancel | ✅ | ✅ | ❌ | ❌ | Cancel active/scheduled broadcasts 🔒 |
| **SYSTEM** |
| system.configure | ✅ | ❌ | ❌ | ❌ | Modify settings, env vars ✅ PROTECTED |
| system.view_config | ✅ | ✅ | ✅ | ❌ | View env vars, configuration ✅ PROTECTED |
| system.manage_users | ✅ | ❌ | ❌ | ❌ | Create/modify/delete users ✅ PROTECTED |
| system.view_users | ✅ | ✅ | ✅ | ❌ | View user list, roles ✅ PROTECTED |
| **LOGS** |
| logs.view | ✅ | ✅ | ✅ | ❌ | View system/audit logs ✅ PROTECTED |
| logs.export | ✅ | ✅ | ✅ | ❌ | Export log data ✅ PROTECTED |
| logs.delete | ✅ | ❌ | ❌ | ❌ | Delete log entries 🔒 |
| **RECEIVERS** |
| receivers.view | ✅ | ✅ | ✅ | ✅ | View SDR receivers, audio sources 🔒 |
| receivers.configure | ✅ | ❌ | ❌ | ❌ | Add/modify receivers 🔒 |
| receivers.delete | ✅ | ❌ | ❌ | ❌ | Remove receivers 🔒 |
| **GPIO** |
| gpio.view | ✅ | ✅ | ✅ | ✅ | View GPIO status, relay states 🔒 |
| gpio.control | ✅ | ✅ | ❌ | ❌ | Control GPIO pins/relays 🔒 CRITICAL |
| **API** |
| api.read | ✅ | ✅ | ✅ | ❌ | Read data via REST API 🔒 |
| api.write | ✅ | ✅ | ❌ | ❌ | Modify data via REST API 🔒 |

---

## Role Descriptions

### 👑 Admin
**Full system administrator with unrestricted access**

**Permissions**: All 22 permissions

**Can do**:
- Configure system settings and environment variables
- Manage user accounts and roles
- Initiate and cancel EAS broadcasts
- Control GPIO relays and equipment
- Add/modify/delete receivers and audio sources
- Access and export all logs and audit trails
- Delete alerts and log entries
- Full API access (read and write)

**Use case**: System administrators, IT staff

---

### ⚡ Operator
**Alert operator with broadcast capabilities**

**Permissions**: 16 permissions

**Can do**:
- ✅ Initiate EAS broadcasts
- ✅ Control GPIO relays
- ✅ Create manual alerts
- ✅ View and export logs
- ✅ Export alert data
- ✅ View system configuration
- ✅ View user list
- ✅ Full API access (read and write)

**Cannot do**:
- ❌ Modify system configuration
- ❌ Manage users or roles
- ❌ Delete alerts or logs
- ❌ Add/modify/delete receivers

**Use case**: On-duty operators, broadcast staff

---

### 👁️ Viewer
**Read-only monitoring and reporting**

**Permissions**: 10 permissions

**Can do**:
- ✅ View alerts and EAS workflow
- ✅ View system configuration
- ✅ View and export logs
- ✅ View receivers and GPIO status
- ✅ Export alert data
- ✅ View user list
- ✅ Read-only API access

**Cannot do**:
- ❌ Initiate broadcasts or control equipment
- ❌ Create or delete alerts
- ❌ Modify any settings
- ❌ Manage users
- ❌ Control GPIO

**Use case**: Managers, auditors, compliance officers

---

### 🎭 Demo
**Limited demonstration access (SAFE MODE)**

**Permissions**: Only 4 permissions

**Can do**:
- ✅ View alerts and alert history
- ✅ View EAS workflow (read-only)
- ✅ View SDR receivers and audio monitoring
- ✅ View GPIO relay status

**Cannot do**:
- ❌ Initiate EAS broadcasts
- ❌ Control GPIO relays
- ❌ Export any data
- ❌ View system configuration or environment variables
- ❌ Access logs or audit trails
- ❌ View user accounts
- ❌ Create, modify, or delete anything
- ❌ API access

**Use case**: Public demonstrations, training sessions, trade shows

---

## Feature Access by Role

### 📊 Dashboard & Monitoring
| Feature | Admin | Operator | Viewer | Demo |
|---------|-------|----------|--------|------|
| Main Dashboard | ✅ | ✅ | ✅ | ✅ |
| Alert Map | ✅ | ✅ | ✅ | ✅ |
| Alert List | ✅ | ✅ | ✅ | ✅ |
| Alert Details | ✅ | ✅ | ✅ | ✅ |
| EAS Workflow Viewer | ✅ | ✅ | ✅ | ✅ |
| Audio Monitoring | ✅ | ✅ | ✅ | ✅ |
| Receiver Status | ✅ | ✅ | ✅ | ✅ |
| GPIO Status View | ✅ | ✅ | ✅ | ✅ |

### 🎛️ Broadcast Operations
| Feature | Admin | Operator | Viewer | Demo |
|---------|-------|----------|--------|------|
| Manual EAS Broadcast | ✅ | ✅ | ❌ | ❌ |
| Cancel Broadcast | ✅ | ✅ | ❌ | ❌ |
| GPIO Control | ✅ | ✅ | ❌ | ❌ |
| LED Sign Control | ✅ | ✅ | ❌ | ❌ |
| VFD Control | ✅ | ✅ | ❌ | ❌ |
| Audio Playout | ✅ | ✅ | ❌ | ❌ |

### 📝 Alert Management
| Feature | Admin | Operator | Viewer | Demo |
|---------|-------|----------|--------|------|
| View Alerts | ✅ | ✅ | ✅ | ✅ |
| Create Manual Alerts | ✅ | ✅ | ❌ | ❌ |
| Delete Alerts | ✅ | ❌ | ❌ | ❌ |
| Export Alerts | ✅ | ✅ | ✅ | ❌ |

### 📻 Receiver Management
| Feature | Admin | Operator | Viewer | Demo |
|---------|-------|----------|--------|------|
| View Receivers | ✅ | ✅ | ✅ | ✅ |
| Add Receivers | ✅ | ❌ | ❌ | ❌ |
| Modify Receivers | ✅ | ❌ | ❌ | ❌ |
| Delete Receivers | ✅ | ❌ | ❌ | ❌ |
| View Audio Sources | ✅ | ✅ | ✅ | ✅ |
| Add Audio Sources | ✅ | ❌ | ❌ | ❌ |

### ⚙️ System Configuration
| Feature | Admin | Operator | Viewer | Demo |
|---------|-------|----------|--------|------|
| View Environment Vars | ✅ | ✅ | ✅ | ❌ |
| Modify Environment Vars | ✅ | ❌ | ❌ | ❌ |
| System Upgrade | ✅ | ❌ | ❌ | ❌ |
| Database Optimization | ✅ | ❌ | ❌ | ❌ |
| View Settings | ✅ | ✅ | ✅ | ❌ |
| Modify Settings | ✅ | ❌ | ❌ | ❌ |

### 👥 User Management
| Feature | Admin | Operator | Viewer | Demo |
|---------|-------|----------|--------|------|
| View Users | ✅ | ✅ | ✅ | ❌ |
| Create Users | ✅ | ❌ | ❌ | ❌ |
| Modify Users | ✅ | ❌ | ❌ | ❌ |
| Delete Users | ✅ | ❌ | ❌ | ❌ |
| Assign Roles | ✅ | ❌ | ❌ | ❌ |
| View Roles | ✅ | ✅ | ✅ | ❌ |
| RBAC Management | ✅ | ❌ | ❌ | ❌ |

### 📋 Logs & Audit
| Feature | Admin | Operator | Viewer | Demo |
|---------|-------|----------|--------|------|
| View System Logs | ✅ | ✅ | ✅ | ❌ |
| View Audit Logs | ✅ | ✅ | ✅ | ❌ |
| Export Logs | ✅ | ✅ | ✅ | ❌ |
| Delete Logs | ✅ | ❌ | ❌ | ❌ |

### 📤 Data Export
| Feature | Admin | Operator | Viewer | Demo |
|---------|-------|----------|--------|------|
| Export Alerts | ✅ | ✅ | ✅ | ❌ |
| Export Logs | ✅ | ✅ | ✅ | ❌ |
| Export Boundaries | ✅ | ✅ | ✅ | ❌ |
| Export Statistics | ✅ | ✅ | ✅ | ❌ |

---

## Demo Role - Safe Demonstration Mode

### Purpose
The Demo role is specifically designed for **safe public demonstrations** where you want to showcase system capabilities without risk of:
- Accidentally triggering EAS broadcasts
- Controlling physical equipment (relays, GPIO)
- Accessing sensitive configuration or credentials
- Exporting or modifying data
- Interrupting production operations

### What Demo Users Experience

#### ✅ They CAN:
1. **View Live Alerts**
   - See real-time alert map
   - Browse alert history
   - View alert details and metadata
   - See how alerts are processed

2. **Explore EAS Workflow**
   - View EAS message generation (read-only)
   - See what would be broadcast (without triggering)
   - Understand the alert processing pipeline

3. **Monitor Audio Systems**
   - Listen to live audio from SDR receivers
   - View audio source health
   - See waveform visualizations
   - Monitor audio levels

4. **Check Equipment Status**
   - View receiver status and configuration
   - See GPIO relay states
   - Monitor system health indicators

#### ❌ They CANNOT:
1. **Trigger Broadcasts**
   - No "Send Alert" button
   - No manual EAS activation
   - No GPIO control buttons

2. **Access Sensitive Data**
   - No environment variables
   - No API keys or credentials
   - No system logs (may contain sensitive info)
   - No user account information

3. **Export Data**
   - No CSV/JSON exports
   - No log downloads
   - Prevents data exfiltration

4. **Modify Anything**
   - No settings changes
   - No receiver configuration
   - No alert creation/deletion
   - Completely read-only (where permitted)

### Recommended Use Cases for Demo Role
- ✅ Trade show demonstrations
- ✅ Training sessions
- ✅ Public tours
- ✅ Client demos
- ✅ Stakeholder presentations
- ✅ Testing UI without system impact

### Creating Demo Accounts
```bash
# 1. Restart application to create demo role
docker-compose restart webapp

# 2. Create demo user via RBAC Management UI
# Navigate to: /admin/rbac
# Click "Create User"
# Username: demo (or guest, demo1, etc.)
# Password: (secure password)
# Assign Role: Demo

# 3. Share credentials safely
# Give demo users the login credentials
# They will have safe, limited access
```

---

## Security Notes

### 🔒 Currently Unprotected Routes (Security Issue)

**CRITICAL**: Many routes are currently accessible to ALL authenticated users regardless of role. The permission decorators need to be added to:

1. **EAS Broadcast** (CRITICAL PRIORITY)
   - `/manual/generate`
   - `/admin/eas/manual_generate`

2. **GPIO Control** (CRITICAL PRIORITY)
   - `/api/gpio/activate/<pin>`
   - `/api/gpio/deactivate/<pin>`

3. **User Management** (HIGH PRIORITY)
   - `/admin/users` (POST/PATCH/DELETE methods)

4. **Receiver Configuration** (HIGH PRIORITY)
   - `/api/radio/receivers` (POST/PUT/DELETE methods)
   - `/api/audio/sources` (POST/PATCH/DELETE methods)

Until these decorators are added, the Demo role's restrictions are **partially effective** - the UI will hide buttons, but direct API calls could bypass restrictions.

### Recommended Actions
1. Add permission decorators to all routes (see [IMPLEMENTATION_CHECKLIST.md](guides/IMPLEMENTATION_CHECKLIST))
2. Test each role thoroughly
3. Audit API endpoints for missing protection
4. Review logs for unauthorized access attempts

---

## Related Documentation

- [SECURITY_ANALYSIS_EXECUTIVE_SUMMARY.md](security/SECURITY_ANALYSIS_EXECUTIVE_SUMMARY) - Security audit findings
- [IMPLEMENTATION_CHECKLIST.md](guides/IMPLEMENTATION_CHECKLIST) - How to add missing decorators
- [PROTECTED_ROUTES_SUMMARY.md](reference/PROTECTED_ROUTES_SUMMARY) - Current route protection status
- `app_core/auth/roles.py` - Role definitions and permissions
- `docs/development/AUTH_PERMISSION_TREE.md` - Technical permission mapping

---

## Permission Descriptions Reference

### Alert Permissions
- **alerts.view**: View CAP alerts, alert history, and alert details on the map and alerts page
- **alerts.create**: Create new manual CAP alerts and override automatic alert filtering
- **alerts.delete**: Delete CAP alerts from the system (use with caution)
- **alerts.export**: Export alert data to CSV, JSON, or other formats for reporting

### EAS Permissions
- **eas.view**: View EAS broadcast operations, message history, and transmission status
- **eas.broadcast**: Initiate EAS broadcasts manually or automatically based on alerts
- **eas.manual_activate**: Manually activate EAS equipment and override automated triggers
- **eas.cancel**: Cancel active or scheduled EAS broadcasts (emergency stop)

### System Permissions
- **system.configure**: Modify system settings, environment variables, and core configuration
- **system.view_config**: View system configuration, settings, and environment status (read-only)
- **system.manage_users**: Create, modify, and delete user accounts and assign roles
- **system.view_users**: View user list, roles, and login history (read-only)

### Log Permissions
- **logs.view**: View system logs, polling logs, audio logs, and GPIO activation logs
- **logs.export**: Export log data for auditing, compliance, or troubleshooting purposes
- **logs.delete**: Delete log entries (use with caution, may affect audit trails)

### Receiver Permissions
- **receivers.view**: View configured receivers, SDR status, and receiver health metrics
- **receivers.configure**: Add, modify, or configure SDR receivers and audio sources
- **receivers.delete**: Remove receivers from the system configuration

### GPIO Permissions
- **gpio.view**: View GPIO pin status, relay states, and activation history
- **gpio.control**: Control GPIO pins, activate/deactivate relays, and test equipment

### API Permissions
- **api.read**: Read data via REST API endpoints (GET requests)
- **api.write**: Modify data via REST API endpoints (POST, PUT, DELETE requests)

---

**End of Permission Tree**
