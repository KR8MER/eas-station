# Gated Alerts (Hold-Off Timer with Manual Override)

Gated alerts add an optional review window before lower-priority CAP/OTA
alerts broadcast, giving an operator a chance to approve them early or
cancel them outright. If nobody acts, the alert auto-releases and broadcasts
normally once the timer expires — the delay is the only behavior change.

**Immediate urgency or Extreme severity alerts always bypass the gate** and
broadcast immediately, exactly as they do today. Gating only ever applies to
everything else (watches, advisories, routine updates).

This feature is disabled by default. Enabling it changes nothing about
*which* alerts broadcast — only *when* the lower-priority ones do.

---

## Where to Configure

**Settings → Alert Gating** (`/admin/alert-gating/`).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| Alert Gating | dropdown | `Disabled` | Master on/off switch. When disabled, all alerts broadcast immediately as before. |
| Hold-Off Duration | seconds (10–3600) | `120` | How long a gated alert waits before it auto-releases. |

Settings persist in the `alert_gating_settings` table.

## Where to Review Pending Alerts

**Broadcast → Pending Alerts** (`/admin/pending-alerts/`).

Lists every alert currently held by the gate, with:

- Event, source (CAP or OTA), severity/urgency, and headline
- A live countdown to auto-release, updated in real time
- **Approve** — broadcasts the alert immediately, skipping the rest of the wait
- **Cancel** — permanently blocks the alert; it will never air, even after the timer expires

The list updates live via WebSocket push (falls back to polling automatically
if the socket connection drops).

## Scope

Gating applies to both alert-ingest paths:

- **CAP poller** — NOAA/IPAWS feed alerts (`auto_forward_cap_alert`)
- **OTA relay** — alerts decoded off the air from an upstream EAS source (`auto_forward_ota_alert`)

## How It Works

1. A qualifying alert arrives. If it's Immediate urgency or Extreme severity, it broadcasts immediately — nothing else in this list applies to it.
2. Otherwise, if gating is enabled, a row is created in the Pending Alerts queue with a hold-off deadline (`hold_until`).
3. A background scheduler (running in the poller service for CAP alerts, and the EAS monitor service for OTA alerts) sweeps for expired holds roughly every 15–30 seconds and releases them automatically.
4. An operator can act on a pending alert at any time before that: Approve releases it early; Cancel blocks it permanently.
5. Once released (by timer or Approve), the alert replays through the exact same broadcast pipeline used for non-gated alerts — nothing about audio generation, GPIO activation, or notification dispatch is different for a released gated alert.

## Physical Indicator (Optional)

If your station has a spare GPIO-driven lamp or buzzer, you can assign it the
**Gated Alert Pending** behavior on the GPIO pin map
(`/admin/gpio/pin-map`). It holds active for as long as at least one alert is
sitting in the Pending Alerts queue, and releases when the queue is empty —
useful for an unattended studio where an operator might not otherwise notice
something is waiting for review.

## Audit Trail

Every resolved gated alert records who approved or cancelled it, from what IP
address, and when — visible in the Pending Alerts queue's history and in the
configuration audit log (Reports → Audit Log).

## Possible Future Enhancement

A natural companion to the output-side **Gated Alert Pending** GPIO behavior
above would be physical GPIO *input* pins wired to Approve/Cancel buttons,
so an operator could act on a pending alert without opening the web UI —
mirroring how the station already handles other physical controls. Not
implemented in this release.
