# Application Settings

EAS Station™ stores a small set of runtime application settings in the database so they can be changed from the web interface without editing `.env` or restarting services. These cover logging, file storage paths, dashboard branding, and the administrator password policy.

---

## Opening the Page

1. Navigate to the **Settings** hub (`/settings`).
2. Click the **Application Settings** card (`/admin/application/`).

Access requires the `system.configure` permission (the **admin** role). Users without it receive a permission-denied response.

On first visit the page creates a default settings row automatically. If the database is unavailable, the page falls back to in-memory defaults and shows a warning banner asking you to run database migrations.

---

## Available Settings

### Logging

| Setting | Description | Default |
|---------|-------------|---------|
| **Log Level** | Root logger verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` | `INFO` |
| **Log File** | Path to the application log file | `logs/eas_station.log` |

Log level changes are applied to the running process **immediately** on save — no restart required. Other settings require a service restart to take effect (except the backup directory, which is also applied live).

### File Storage

| Setting | Description | Default |
|---------|-------------|---------|
| **Upload Folder** | Directory for uploaded files (e.g. custom audio) | `/opt/eas-station/uploads` |
| **Backup Directory** | Destination for database backup archives | `/var/backups/eas-station` |

When you save a new backup directory, EAS Station™ tries to create it right away and verifies it is writable by the service user. If creation fails (for example, the path is on a USB or NFS mount that is not yet available), the save still succeeds but the response includes a warning — backups will fail until the path exists and is writable. The new path is pushed into the live Flask configuration so the next backup uses it without a restart.

### Dashboard Header (Branding)

| Setting | Description | Limit |
|---------|-------------|-------|
| **Dashboard Headline** | Custom headline shown on the public dashboard | 120 characters |
| **Dashboard Subtitle** | Custom subtitle shown under the headline | 160 characters |

Both fields are optional. Leave them blank to use the built-in defaults. Useful for identifying the station (e.g. "Putnam County EAS Monitor").

### Password Policy

| Setting | Description | Default |
|---------|-------------|---------|
| **Minimum Length** | Required password length (1–128 characters) | 8 |
| **Require Uppercase** | At least one uppercase letter | Off |
| **Require Lowercase** | At least one lowercase letter | Off |
| **Require Digits** | At least one number | Off |
| **Require Special** | At least one special character | Off |
| **Password Expiration** | Days before a password expires (0–3650; `0` = never) | 0 |

Policy rules are enforced when administrator passwords are **created or reset** — existing passwords are not affected until they are changed. When expiration is enabled, administrators see a warning banner starting 14 days before their password expires.

---

## Bootstrap Settings (Not Editable Here)

Some settings must still live in your `.env` file because they are needed before the database connection exists:

- `SECRET_KEY` — Flask session security key
- `DATABASE_URL` — PostgreSQL connection URL
- `CACHE_REDIS_URL` — Redis connection URL
- `CACHE_TYPE` — Cache backend type
- `FLASK_ENV` / `FLASK_DEBUG` — Flask startup mode

Manage these through **Settings → Environment** (`/settings/environment`) or by editing `.env` directly.

---

## Routes Reference

| Method | Route | Permission | Purpose |
|--------|-------|------------|---------|
| `GET` | `/admin/application/` | `system.configure` | Render the settings page |
| `POST` | `/admin/application/update` | `system.configure` | Save settings (form fields); returns JSON |
| `GET` | `/admin/application/status` | `system.view_config` | Current settings as JSON |

The `/status` endpoint returns `{"success": true, "settings": {...}}`, or HTTP 404 if no settings row has been created yet.

---

## Troubleshooting

### "Database error loading application settings"

The `application_settings` table is missing or unreachable. The page shows defaults in read-only fashion until you run migrations:

```bash
cd /opt/eas-station && source venv/bin/activate
alembic upgrade head
```

### Backup warning after saving

A message like *"Saved, but `/path` is not writable by the service user"* means the setting was stored, but the next backup will fail. Fix permissions:

```bash
sudo mkdir -p /var/backups/eas-station
sudo chown eas-station:eas-station /var/backups/eas-station
```

### Log level not changing

The level is applied immediately to the running web process, but the poller and SDR services read it at startup — restart those units after changing it:

```bash
sudo systemctl restart eas-station-poller.service eas-station-sdr.service
```

---

## Related Guides

- [Database Backups](DATABASE_BACKUPS.md) — uses the backup directory configured here
- [Audit Log Review](AUDIT_LOG_REVIEW.md) — configuration changes are logged
- [MFA / TOTP Setup](MFA_TOTP_SETUP.md) — complements the password policy
