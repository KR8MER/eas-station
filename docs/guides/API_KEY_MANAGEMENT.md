# API Key Management

> **⚠️ Status (May 2026): planned, not yet implemented.** API key authentication, the `X-API-Key` header, the `/admin/api-keys` UI, and the per-key rate-limiting layer described in this document are part of the planned external-integration surface and are **not currently shipped**. The codebase today has no `APIKey` model, no `/admin/api-keys` route, and no `X-API-Key` middleware. Until those land, programmatic access to EAS Station™ requires reusing an authenticated session cookie (and CSRF token) from a logged-in user, or wiring your script to the same login flow a browser uses. This document is kept as the design reference for the feature.

EAS Station™ provides a REST API accessible via cryptographically secure API keys. API keys allow external tools, scripts, and integrations to query alert data, system status, and perform management operations without using a web browser session.

---

## Overview

| Property | Value |
|----------|-------|
| Authentication header | `X-API-Key: <key>` |
| Key format | 32-byte URL-safe random token |
| Key storage | Hashed in database (plaintext shown once at creation) |
| Rate limiting | Per-key, configurable |
| Roles | Keys inherit a specific role's permissions |

---

## Creating an API Key

1. Log in as an **Admin** user.
2. Navigate to **Admin → API Keys**.
3. Click **Generate New Key**.
4. Fill in the form:
   - **Label** — A human-readable name (e.g., `monitoring-script`, `grafana-integration`).
   - **Role** — Select the permission level: `Admin`, `Operator`, or `Analyst`.
   - **Expiry** — Optional expiration date. Leave blank for a non-expiring key.
5. Click **Create**.
6. **Copy the full key immediately.** It is displayed only once. EAS Station™ stores only a hashed version and cannot recover the plaintext key later.

---

## Using an API Key

Include the key in the `X-API-Key` request header:

```bash
# Example: list active alerts
curl -H "X-API-Key: your-api-key-here" \
     https://your-eas-station.example.com/api/alerts/active
```

```python
import requests

key = "your-api-key-here"
base = "https://your-eas-station.example.com"

resp = requests.get(f"{base}/api/alerts/active",
                    headers={"X-API-Key": key})
resp.raise_for_status()
alerts = resp.json()
```

---

## Available API Endpoints

### Alerts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/alerts/active` | Active (non-expired) alerts |
| `GET` | `/api/alerts/history` | Alert history with filters |
| `GET` | `/api/alerts/<id>` | Single alert detail |
| `GET` | `/api/alerts/stats` | Alert count and severity statistics |

**Query parameters for `/api/alerts/history`:**

| Parameter | Description | Example |
|-----------|-------------|---------|
| `days` | Lookback window (default: 7) | `?days=30` |
| `severity` | Filter by severity | `?severity=Extreme` |
| `event` | Filter by event code | `?event=TOR` |
| `limit` | Max results (default: 100) | `?limit=50` |

### System Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Overall system health summary |
| `GET` | `/api/health/services` | Per-service status |
| `GET` | `/api/health/audio` | Audio pipeline health |
| `GET` | `/api/health/sdr` | SDR receiver status |
| `GET` | `/api/health/database` | Database connectivity |

### Analytics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/analytics/metrics` | Metric snapshots |
| `GET` | `/api/analytics/trends` | Trend data |
| `GET` | `/api/analytics/anomalies` | Detected anomalies |

### EAS Messages

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/eas/messages` | Recent EAS messages |
| `GET` | `/api/eas/messages/<id>` | EAS message detail + audio URL |

### Backups (Admin role required)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/backups/list` | List available backups |
| `POST` | `/api/backups/create` | Create a new backup |
| `GET` | `/api/backups/validate/<name>` | Validate backup integrity |
| `GET` | `/api/backups/download/<name>` | Download backup as `.tar.gz` |

### Security

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/security/audit-logs` | Audit log entries |
| `GET` | `/security/ip-filters` | IP allowlist/blocklist |
| `POST` | `/security/ip-filters` | Add IP filter |
| `DELETE` | `/security/ip-filters/<id>` | Remove IP filter |

---

## Permission Levels by Role

| Role | Alerts | System Health | Analytics | Backups | Admin Actions |
|------|--------|--------------|-----------|---------|---------------|
| Analyst | Read | Read | Read | Read | No |
| Operator | Read | Read | Read | Create | Limited |
| Admin | Read/Write | Full | Full | Full | Yes |

---

## Managing Existing Keys

Navigate to **Admin → API Keys** to:

- **View** all keys, their labels, roles, creation date, last-used timestamp, and expiry.
- **Rotate** a key — generates a new token value with the same label and role. The old key is immediately invalidated.
- **Disable** a key temporarily without deleting it.
- **Delete** a key permanently.

!!! warning "Key rotation"
    After rotating a key, update all external systems that use it before the old key is invalidated.

---

## Best Practices

1. **Least privilege** — Use an `Analyst` key for read-only integrations. Only use `Admin` keys for automation that must modify configuration.
2. **Label keys clearly** — Include the integration name and environment (e.g., `grafana-prod`, `monitoring-dev`).
3. **Set expiry dates** — For temporary access or testing, always set an expiration.
4. **Rotate keys periodically** — Rotate keys that access sensitive endpoints at least every 90 days.
5. **Never commit keys to version control** — Use environment variables or a secrets manager.
6. **Monitor last-used** — Investigate keys that have not been used recently or that show unexpected activity in the audit log.

---

## Troubleshooting

### 401 Unauthorized

- Verify the `X-API-Key` header is present and spelled correctly.
- Confirm the key has not been disabled or deleted (**Admin → API Keys**).
- Check whether the key has expired.

### 403 Forbidden

- The key's role does not have permission for the requested endpoint. Use a key with a higher-privilege role.

### Unexpected 429 Too Many Requests

- The key has hit its rate limit. Reduce request frequency or contact an admin to increase the limit.

### Key not showing in list

- Only active (non-deleted) keys are listed. Deleted keys cannot be recovered.
