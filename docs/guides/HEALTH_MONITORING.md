# Health Monitoring Endpoints

EAS Station™ exposes a set of REST health-check endpoints under `/api/health/` for verifying that the separated services (web app, audio service, Redis, Icecast) and the host itself are healthy. They return JSON and use HTTP status codes that integrate cleanly with external monitoring systems: **200** when healthy, **503** when degraded or down, **500** on an internal check error.

These endpoints power the in-app status indicators (navbar health dot, System Health dashboard at `/system_health`) and are also suitable for Nagios/Zabbix/Uptime-Kuma-style probes.

---

## Authentication

| Endpoint | Authentication |
|----------|---------------|
| `GET /api/health` | **None** — public liveness check |
| `GET /api/health/audio-service` | Logged-in session required |
| `GET /api/health/redis` | Logged-in session required |
| `GET /api/health/icecast` | Logged-in session required |
| `GET /api/health/system` | Logged-in session required |
| `GET /api/health/resources` | Logged-in session required |
| `GET /api/health/ntp` | Logged-in session required |

The route handlers themselves carry no role/permission decorators — protection comes from the application's deny-by-default request guard, which allows unauthenticated `GET` only for the exact path `/api/health` (the basic liveness alias for `/health`). All `/api/health/<subpath>` endpoints return **401** `{"error": "Authentication required"}` without a valid login session. No specific role is needed beyond being logged in; any active account (including **viewer**) can read them.

`GET /health` and `GET /health/dependencies` are also public and provide a basic liveness check and a dependency summary respectively.

---

## Endpoint Reference

### `GET /api/health/audio-service`

The primary check for the separated architecture: confirms the audio-service process is alive and publishing metrics to Redis.

- **200** — heartbeat present and fresher than 15 seconds
- **503** — no metrics in Redis (`status: "down"`) or heartbeat older than 15 seconds (`status: "stale"`)

```json
{
  "status": "healthy",
  "message": "Audio-service publishing metrics",
  "healthy": true,
  "age_seconds": 2.4,
  "last_heartbeat": 1718000000.0,
  "redis_available": true,
  "audio_controller": { "sources_count": 2, "active_source": "sdr_wx1" },
  "eas_monitor": { "running": true, "samples_processed": 123456789 }
}
```

### `GET /api/health/redis`

Connects to Redis directly (2-second timeout), measures ping latency, and reports server info.

- **200** — connection OK
- **503** — cannot connect (`status: "unavailable"`)

Response fields: `host`, `port`, `db`, `latency_ms`, `version`, `uptime_seconds`, `connected_clients`, `used_memory_human`.

### `GET /api/health/icecast`

Checks the Icecast streaming server.

- **200** with `status: "disabled"` — Icecast is not enabled (treated as healthy, not an error)
- **200** with `status: "healthy"` — running normally
- **200** with `status: "degraded"` — running, but the check reported issues (listed in `issues`)
- **503** with `status: "unavailable"` — enabled but not reachable

Response includes the collected Icecast status fields such as `enabled`, `running`, `server`, `port`, `listeners`, `sources`, and `issues`.

### `GET /api/health/system`

Aggregate roll-up of the web app, audio service, Redis, and Icecast. This is the single best endpoint to poll from external monitoring.

- **200** — all critical services healthy (`status: "healthy"`)
- **503** — one or more down (`status: "degraded"`)

Critical services are `app`, `redis`, and `audio_service`; Icecast only affects the overall result when it is enabled.

```json
{
  "status": "healthy",
  "healthy": true,
  "services": {
    "app": { "healthy": true },
    "redis": { "healthy": true, "age_seconds": 1.8 },
    "audio_service": { "healthy": true, "age_seconds": 1.8 },
    "icecast": { "healthy": true, "enabled": true, "running": true, "status": "ok", "listeners": 3 }
  },
  "timestamp": 1718000000.0
}
```

### `GET /api/health/resources`

Host resource utilization read from `/proc` (no external dependencies). Always **200** when the collection succeeds.

| Field | Description |
|-------|-------------|
| `cpu_percent` | CPU usage sampled over a 0.1 s window |
| `load_average` | `1min` / `5min` / `15min` load averages |
| `memory` | `total_mb`, `used_mb`, `available_mb`, `percent` |
| `disk` | Root filesystem `total_gb`, `used_gb`, `free_gb`, `percent` |
| `uptime_seconds` | Host uptime |
| `timestamp` | Collection time (epoch seconds) |

### `GET /api/health/ntp`

System clock synchronization status — important for accurate SAME timestamps. The check tries `timedatectl show-timesync`, then `timedatectl status`, then `chronyc tracking`, and reports whichever data it could collect.

- **200** with `status: "ok"` — clock synchronized
- **200** with `status: "not_synced"` — NTP reports not synchronized (`healthy: false`)
- **200** with `status: "unknown"` — no NTP tooling answered

Response fields: `synchronized`, `server`, `offset_ms`, `stratum`, `poll_interval_s`, `ntp_service`, `method`, `timestamp`.

> Note: the NTP and not-synced cases still return HTTP 200 — alert on the `healthy` field, not only the status code, if clock sync matters to you.

---

## Using with External Monitoring

### Unauthenticated liveness probe

For a simple "is it up" check, use the public alias:

```bash
curl -fsS https://your-eas-station.example.com/api/health
```

### Authenticated detail checks

The detailed endpoints need a login session. Create a dedicated **viewer** account (without MFA) for monitoring, log in once to capture the session cookie, then reuse it:

```bash
# Log in and store the session cookie (the /login endpoint is CSRF-exempt)
curl -fsS -c /tmp/eas-monitor.cookies \
  -d 'username=monitor' -d 'password=<password>' \
  https://your-eas-station.example.com/login

# Poll the aggregate health endpoint — exit code is non-zero on 503
curl -fsS -b /tmp/eas-monitor.cookies \
  https://your-eas-station.example.com/api/health/system

# Alert when root disk usage exceeds 80%
curl -fsS -b /tmp/eas-monitor.cookies \
  https://your-eas-station.example.com/api/health/resources \
  | jq -e '.disk.percent < 80'
```

Sessions expire (default lifetime is configurable), so have your monitoring job re-login on a 401.

### Suggested polling matrix

| Endpoint | Suggested interval | Alert when |
|----------|--------------------|-----------|
| `/api/health/system` | 30–60 s | HTTP 503 |
| `/api/health/resources` | 1–5 min | `disk.percent` > 80 or `memory.percent` > 90 |
| `/api/health/ntp` | 5–15 min | `healthy` is `false` |
| `/api/health/icecast` | 1–5 min | HTTP 503 (when streaming is enabled) |

---

## Related Guides

- [Disk Space Cleanup](../maintenance/DISK_SPACE_CLEANUP.md) — what to do when `/api/health/resources` reports a full disk
- [Icecast Streaming Setup](ICECAST_STREAMING_SETUP.md) — configuring the streaming server checked above
- [502/504 Gateway Errors](../troubleshooting/TROUBLESHOOTING_504_TIMEOUT.md) — when the web app itself stops answering
