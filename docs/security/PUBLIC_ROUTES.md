# Public vs. Authenticated Routes

EAS Station denies by default: `before_request` in `app.py` redirects any
anonymous request to `/login` unless the path is explicitly allowed. This page
records what is allowed, why, and how to decide where a new route belongs.

A station published at a public hostname (`easstation.com`, a Tailscale
funnel, a port-forward) serves these routes to the whole internet. Treat this
list as the perimeter.

---

## The three tiers

| Tier | Who can read it | Defined in `app.py` |
|---|---|---|
| **Public** | Anyone, from anywhere | `_PUBLIC_PAGE_PATHS`, `_PUBLIC_PAGE_PREFIXES`, `PUBLIC_API_GET_PATHS` |
| **Local** | Anyone on the appliance or its LAN, no session needed | `LOCAL_API_GET_PATHS` |
| **Authenticated** | Signed-in users, subject to RBAC | everything else (the default) |

Signing in grants access to all three from anywhere. The local tier only
removes the *anonymous-from-the-internet* path.

---

## Tier 1 — Public

### Pages

`/` · `/about` · `/help` · `/help/version` · `/terms` · `/privacy` ·
`/sms-compliance` · `/support` · `/version` · `/repo-stats` · `/attribution` ·
`/style-guide` · `/docs` and everything under `/docs/` (viewer, assets, search)
· `/login` · `/logout` · `/mfa/verify` · `/setup…` · `/static/…` ·
`/sitemap.xml` · `/robots.txt` · `/favicon.ico` · `/ping` · `/health` ·
`/health/dependencies`

**Documentation is never gated.** The `/docs` tree, the help and about pages,
the legal pages, and `/attribution` (AGPL-3.0 and third-party licence
disclosures) must be readable without an account — a licence notice behind a
password is not a licence notice. `/style-guide` is the UI component reference
the developer docs link to; it is static markup with no station data.

### APIs (GET only)

| Endpoint | Why it is public |
|---|---|
| `/api/alerts`, `/api/alerts/historical` | Emergency alert content — the point of the station |
| `/api/boundaries` | Map geometry the public landing page draws |
| `/api/broadcast/state` | Polled by `base.html`/navbar on every page including `/login`; active flag + count only |
| `/api/health` | Liveness probe for external monitoring |
| `/api/release-manifest` | Version shown on the public `/version` page |
| `/api/traffic/client` | Visitor screen-resolution beacon |

Non-GET methods are never public, even on these paths.

---

## Tier 2 — Local network only

These describe the **machine**, not the alerting service, and nothing on a
public hostname should serve them anonymously:

| Endpoint | Exposes |
|---|---|
| `/api/smart_diag` | Raw `smartctl` output — drive models, serial numbers, firmware, temperatures, power-on hours, error logs; `lsblk` topology |
| `/api/system_status` | Hostname, primary IP address, CPU/memory/disk utilisation, uptime |
| `/api/system_health` | Service and dependency health detail |
| `/api/monitoring/radio` | Receiver/SDR state |
| `/api/eas-monitor/status` | Decoder state |
| `/api/audio/metrics`, `/api/audio/metrics/latest`, `/api/audio/health`, `/api/audio/sources` | Audio hardware and source configuration |

They stay unauthenticated for local callers because
`scripts/screen_renderer.ScreenRenderer` — used by the displays subsystem to
populate OLED/LED/VFD screens — fetches them from `http://localhost:5000` with
no session. Gating them outright would blank those screens.

`_is_local_network_client()` accepts loopback, RFC1918/RFC4193 private ranges,
link-local and CGNAT, and **fails closed** on a missing or malformed address.
`request.remote_addr` is the real client IP because `ProxyFix(x_for=1)` trusts
exactly one hop (our own nginx), so a remote caller cannot claim to be local by
sending its own `X-Forwarded-For`.

---

## Tier 3 — Authenticated (the default)

Everything else: `/admin/…`, `/security/…`, `/settings/…`, `/logs`, `/alerts`,
`/audio…`, `/eas/…`, `/analytics`, `/stats`, `/diagnostics`, `/displays`,
`/screens`, `/export/…`, `/debug/…`, `/rwt-schedule`, `/system_health`,
`/navigation`, `/search`, and every non-GET API.

Most also carry a `@require_permission(...)` decorator, so RBAC narrows access
further for signed-in users.

**One deliberate exception:** on a system with no administrator account yet,
`/admin` and `/admin/users` answer anonymously so the first admin can be
created. That exemption is guarded by `g.admin_setup_mode`
(`AdminUser.query.count() == 0`) and closes permanently once an account exists.

---

## Adding a route

Ask what the response reveals:

- **Alert content, legal text, documentation, or a version string?** Public.
- **Anything about this machine** — hostnames, addresses, hardware, disks,
  service internals, configuration? Local tier at most; authenticated if no
  on-box consumer needs it.
- **Anything about operations** — logs, audit trails, recordings, settings,
  station identity? Authenticated, with a `@require_permission`.
- **Any method other than GET?** Authenticated. No exceptions.

When in doubt, leave it authenticated: the default is safe, and a missing entry
shows up immediately as a redirect to `/login`.

## Re-running the audit

`tests/test_public_route_audit.py` enforces the invariants above and fails if a
documentation route is gated or a machine-describing endpoint becomes
internet-public. To review the full picture:

```bash
python - <<'PY'
import app as appmod
pub, prefixes = appmod._PUBLIC_PAGE_PATHS, appmod._PUBLIC_PAGE_PREFIXES
for rule in sorted(appmod.app.url_map.iter_rules(), key=str):
    path = str(rule)
    if path in pub or any(path.startswith(p) for p in prefixes):
        tier = "PUBLIC"
    elif path.rstrip('/') in appmod.PUBLIC_API_GET_PATHS:
        tier = "PUBLIC-API"
    elif path.rstrip('/') in appmod.LOCAL_API_GET_PATHS:
        tier = "LOCAL"
    else:
        tier = "AUTH"
    print(f"{tier:<11}{path}")
PY
```

To confirm the perimeter on a running station, request an endpoint from off-box
and expect `401`:

```bash
curl -si https://<your-station>/api/smart_diag | head -1   # HTTP/1.1 401
curl -si https://<your-station>/attribution   | head -1    # HTTP/1.1 200
```
