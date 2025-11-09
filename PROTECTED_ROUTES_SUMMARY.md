# Protected Routes Summary

## Routes WITH Permission Decorators (22 Total)

### system.view_config (5 routes - READ-ONLY)
| File | Line | Method | Route |
|------|------|--------|-------|
| webapp/admin/environment.py | 801 | GET | /api/environment/categories |
| webapp/admin/environment.py | 816 | GET | /api/environment/variables |
| webapp/admin/environment.py | 945 | GET | /api/environment/validate |
| webapp/admin/environment.py | 1018 | GET | /settings/environment |
| webapp/admin/environment.py | 1040 | GET | /admin/environment/download-env |

### system.configure (2 routes - WRITE OPERATIONS)
| File | Line | Method | Route |
|------|------|--------|-------|
| webapp/admin/environment.py | 870 | PUT | /api/environment/variables |
| webapp/admin/environment.py | 1064 | POST | /api/environment/generate-secret |

### system.view_users (3 routes - READ-ONLY)
| File | Line | Method | Route |
|------|------|--------|-------|
| webapp/routes_security.py | 211 | GET | /roles |
| webapp/routes_security.py | 221 | GET | /roles/<int:role_id> |
| webapp/routes_security.py | 313 | GET | /permissions |

### system.manage_users (4 routes - WRITE OPERATIONS)
| File | Line | Method | Route |
|------|------|--------|-------|
| webapp/routes_security.py | 229 | POST | /roles |
| webapp/routes_security.py | 273 | PUT | /roles/<int:role_id> |
| webapp/routes_security.py | 323 | PUT | /users/<int:user_id>/role |
| webapp/routes_security.py | 469 | POST | /init-roles |

### logs.view (1 route - READ-ONLY)
| File | Line | Method | Route |
|------|------|--------|-------|
| webapp/routes_security.py | 370 | GET | /audit-logs |

### logs.export (1 route - DATA EXPORT)
| File | Line | Method | Route |
|------|------|--------|-------|
| webapp/routes_security.py | 412 | GET | /audit-logs/export |

### analytics_manage (6 routes - WRITE OPERATIONS)
| File | Line | Method | Route |
|------|------|--------|-------|
| webapp/routes_analytics.py | 123 | POST | /api/analytics/metrics/aggregate |
| webapp/routes_analytics.py | 196 | POST | /api/analytics/trends/analyze |
| webapp/routes_analytics.py | 308 | POST | /api/analytics/anomalies/detect |
| webapp/routes_analytics.py | 361 | POST | /api/analytics/anomalies/<int:anomaly_id>/acknowledge |
| webapp/routes_analytics.py | 390 | POST | /api/analytics/anomalies/<int:anomaly_id>/resolve |
| webapp/routes_analytics.py | 423 | POST | /api/analytics/anomalies/<int:anomaly_id>/false-positive |

---

## Routes WITHOUT Permission Decorators (202 Total)

### CRITICAL - EAS/Broadcast Routes (NO PROTECTION!)
| File | Line | Method | Route | Risk |
|------|------|--------|-------|------|
| webapp/eas/workflow.py | 105 | POST | /manual/generate | CRITICAL - Can initiate EAS broadcasts |
| webapp/admin/audio.py | 621 | POST | /admin/eas/manual_generate | CRITICAL - Can initiate EAS broadcasts |

### CRITICAL - GPIO/Relay Control (NO PROTECTION!)
| File | Line | Method | Route | Risk |
|------|------|--------|-------|------|
| webapp/routes/system_controls.py | 171 | POST | /api/gpio/activate/<int:pin> | CRITICAL - Can control physical relays |
| webapp/routes/system_controls.py | 231 | POST | /api/gpio/deactivate/<int:pin> | CRITICAL - Can control physical relays |

### CRITICAL - System Operations (NO PROTECTION!)
| File | Line | Method | Route | Risk |
|------|------|--------|-------|------|
| webapp/admin/maintenance.py | 480 | POST | /admin/operations/upgrade | CRITICAL - Can upgrade system |
| webapp/admin/maintenance.py | 573 | POST | /admin/optimize_db | CRITICAL - Can modify database |

### HIGH - User Management (NO PROTECTION!)
| File | Line | Method | Route | Risk |
|------|------|--------|-------|------|
| webapp/admin/dashboard.py | 164 | GET/POST | /admin/users | HIGH - Can manage users |
| webapp/admin/dashboard.py | 213 | PATCH/DELETE | /admin/users/<int:user_id> | HIGH - Can delete users |

### HIGH - Receiver/Radio Configuration (NO PROTECTION!)
| File | Line | Method | Route | Risk |
|------|------|--------|-------|------|
| webapp/routes_settings_radio.py | 190 | GET | /api/radio/receivers | HIGH - View receivers |
| webapp/routes_settings_radio.py | 196 | POST | /api/radio/receivers | HIGH - Add receivers |
| webapp/routes_settings_radio.py | 219 | PUT/PATCH | /api/radio/receivers/<int:id> | HIGH - Modify receivers |
| webapp/routes_settings_radio.py | 245 | DELETE | /api/radio/receivers/<int:id> | HIGH - Delete receivers |

### HIGH - Audio/Audio Ingest (NO PROTECTION!)
| File | Line | Method | Route | Risk |
|------|------|--------|-------|------|
| webapp/admin/audio_ingest.py | 513 | GET | /api/audio/sources | HIGH - View audio sources |
| webapp/admin/audio_ingest.py | 631 | POST | /api/audio/sources | HIGH - Add audio sources |
| webapp/admin/audio_ingest.py | 754 | PATCH | /api/audio/sources/<name> | HIGH - Modify audio sources |
| webapp/admin/audio_ingest.py | 834 | DELETE | /api/audio/sources/<name> | HIGH - Delete audio sources |
| webapp/admin/audio_ingest.py | 874 | POST | /api/audio/sources/<name>/start | HIGH - Start audio source |
| webapp/admin/audio_ingest.py | 920 | POST | /api/audio/sources/<name>/stop | HIGH - Stop audio source |

---

## Permission Definitions

### Available Permissions in System

```
alerts.view              - View alerts and alert history
alerts.create            - Create manual CAP alerts
alerts.delete            - Delete CAP alerts
alerts.export            - Export alert data

eas.view                 - View EAS broadcasts (history only)
eas.broadcast            - Initiate EAS broadcasts (MISSING DECORATOR!)
eas.manual_activate      - Manually activate EAS equipment
eas.cancel               - Cancel EAS broadcasts

system.configure         - Modify system settings (MISSING DECORATOR!)
system.view_config       - View system configuration (read-only)
system.manage_users      - Create/modify users (MISSING DECORATOR!)
system.view_users        - View user list and roles

logs.view                - View audit logs
logs.export              - Export audit logs
logs.delete              - Delete audit logs

receivers.view           - View SDR receivers (MISSING DECORATOR!)
receivers.configure      - Add/modify receivers (MISSING DECORATOR!)
receivers.delete         - Remove receivers (MISSING DECORATOR!)

gpio.view                - View GPIO status (MISSING DECORATOR!)
gpio.control             - Control GPIO relays (MISSING DECORATOR!)

api.read                 - Read via REST API
api.write                - Modify via REST API
```

---

## Demo Role Specification

### Current Demo Permissions
```
✓ alerts.view
✓ eas.view
✓ system.view_config
✓ receivers.view
✓ gpio.view
```

### Safe for Demo?
```
✓ alerts.view              - YES (read-only)
✓ eas.view                 - YES (read-only, no broadcast)
✓ system.view_config       - YES (read-only)
✓ receivers.view           - YES (read-only)
✓ gpio.view                - YES (read-only, no control)

✗ alerts.create            - NO (modifies data)
✗ alerts.delete            - NO (deletes data)
✗ eas.broadcast            - NO (CRITICAL - can broadcast)
✗ gpio.control             - NO (CRITICAL - can control equipment)
✗ system.configure         - NO (CRITICAL - can break system)
✗ receivers.configure      - NO (HIGH - can misconfigure)
✗ system.manage_users      - NO (CRITICAL - can modify access)
```

### Recommended Addition for Demo
```
✓ logs.view                - YES (read-only, good for demo)
```

