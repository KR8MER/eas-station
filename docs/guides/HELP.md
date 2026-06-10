# 🆘 NOAA CAP Emergency Alert System Help Guide

Welcome to the operator help guide for the NOAA CAP Emergency Alert System (EAS). This document outlines everyday workflows, troubleshooting tips, and reference material for evaluating the application in lab environments or during controlled exercises.

> ⚠️ **Important:** EAS Station™ is experimental software. It has been cross-checked against open-source decoders like [multimon-ng](https://github.com/EliasOenal/multimon-ng), but it is not FCC-certified equipment and must never be relied upon for life-safety alerting.

## Safety Expectations
- Operate the stack in isolated development or staging networks disconnected from broadcast transmitter controls.
- Do not ingest live IPAWS credentials, dispatch feeds, or mission-critical telemetry into this environment.
- Validate any workflows on certified FCC equipment before using them in real-world alerting scenarios.
- Review the repository [Terms of Use](../policies/TERMS_OF_USE.md) and [Privacy Policy](../policies/PRIVACY_POLICY.md) with your operators prior to onboarding.

## Getting Started
1. **Review the About document:** The [About page](../reference/ABOUT.md) covers system goals, core services, and the complete software stack.
3. **Install EAS Station™:** Follow the [Installation Quick Start](../installation/QUICKSTART.md) and [Installation Details](../installation/INSTALLATION_DETAILS.md) for a bare-metal deployment on Debian/Ubuntu with PostgreSQL + PostGIS and Redis.
4. **Launch the stack:**

## Routine Operations
### Accessing the Dashboard
- Navigate to `http://<host>:5000` in a modern browser.
- Log in with administrator credentials created during initial setup.

### Monitoring Live Alerts
1. Open the **Dashboard** to view active CAP products on the interactive map.
2. Use the **Statistics** tab to analyze severity, event types, and historical counts.
3. Check **System Health** for CPU, memory, disk, receiver, and audio pipeline heartbeat metrics.

### Reviewing Compliance & Weekly Tests
- Navigate to **Compliance** (`/admin/compliance`) for a consolidated view of CAP receipts, CAP→SAME relays, off-air decoded broadcasts (from RF/stream receivers), manual activations, Required Weekly Tests, and background worker activity.
- Receiver health summaries, audio output heartbeat checks, and recent activity timelines pull directly from `app_core/system_health.py` and `app_core/eas_storage.py`.
- Export CSV or PDF compliance logs from the buttons at the top of the page to generate FCC-ready documentation. Each log entry carries the Part 11 identity fields — originator code (ORG), event code (EEE), location codes (PSSCCC), station identifier (LLLLLLLL), issue and purge times, and the action taken — per 47 CFR §§ 11.35(a) and 11.54(a)(3).

### Managing Boundaries and Alerts
- Use the **Boundaries** module to upload county, district, or custom GIS polygons.
- Configure SAME coverage under **Admin → Location Settings**—the picker lists FEMA-defined
  subdivisions alongside entire counties and automatically applies the correct portion digit
  when you select a partial-county code.
- Review stored CAP products in **Alert History**. Filters by status, severity, and date help locate specific messages.
- Trigger manual broadcasts with `manual_eas_event.py` for drills or locally authored messages.

#### US County Boundaries (IPAWS SAME Coverage)
Navigate to **Admin → County Boundaries** (`/admin/county_boundaries`) to manage the Census
TIGER/Line county shapefile. IPAWS/NWS alerts carry 6-digit SAME geocodes (e.g. `039137`)
instead of polygon geometry; EAS Station™ converts those codes to highlighted county outlines
on the alert detail map by looking up this table. Without it, affected alerts show
"Alert has no geographic data."

Page sections, top to bottom:

| Section | Purpose |
|---|---|
| **Status Cards** | Shows table health, county count, state count, and bundled shapefile presence |
| **Load County Boundaries** | Import from bundled Census shapefile (~3,235 counties) or upload a custom ZIP |
| **Loaded States** | Table of loaded states with **View on Map** (🗺) and **Delete** (🗑) per-state actions |
| **County Boundary Map** | Interactive Leaflet map — select a state from the dropdown or click **View on Map** in the table above; click any county to see name, GEOID, and SAME code |
| **Search Counties** | Real-time search by county name, 5-digit GEOID, or state abbreviation; click a result to load that state on the map |
| **Table Lookup / Diagnostics** | Enter comma-separated SAME codes or GEOIDs to verify database presence before an activation |

> **Note:** EAS Station™ auto-loads the bundled shapefile on first startup if the table is
> empty. This page is only needed for manual reloads, partial-state imports, or diagnostics.

### Managing Receivers
- Visit **Settings → Radio Receivers** (`/settings/radio`) to add, edit, or remove SDR hardware profiles stored in the `RadioReceiver` table.
- Toggle **Auto Start** or **Enabled** to control which receivers the radio manager spins up during poller runs.
- Use the action menu to request synchronized IQ/PCM captures; captured files are surfaced alongside status updates in the compliance dashboard.

### Generating Sample Audio
- Use the **Broadcast Builder** console (accessible from the top navigation once logged in) to craft practice activations entirely in the browser. Pick a state or territory, choose the county/parish, FEMA-defined subdivision, or statewide SAME code, and click **Add Location** to build the PSSCCC list—manual pasting is still supported for bulk entry, subdivision selections automatically set the correct portion digit, and the picker enforces the 31-code SAME limit. The originator dropdown now exposes the four FCC originator codes (EAS, CIV, WXR, PEP), the event selector is trimmed to the authorised 47 CFR §11.31(d–e) entries, and the live preview assembles the `ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-` header while explaining each field (including the 0xAB preamble and trailing `NNNN`). Tap **Quick Weekly Test** to preload your configured counties and sample script—the preset omits the attention signal per FCC guidance, but you can re-enable the dual-tone or 1050 Hz alert if needed before confirming the run. After confirmation the workflow automatically generates the package with three SAME bursts, selectable attention tone, optional narration, and EOM WAV assets with one-second guard intervals between each section.

### Verifying Playout & Decoding Audio
- Open **Alert Verification** (`/admin/alert-verification`) to inspect delivery timelines, latency metrics, and per-target outcomes built by `app_core/eas_storage.py`.
- Upload captured WAV or MP3 files to decode SAME bursts directly in the browser; decoded headers, attention tones, and audio segments can be downloaded for archival.
- Store decoded results for future comparison and review the most recent submissions from the sidebar list.

## Troubleshooting
### Application Will Not Start
- Confirm the PostgreSQL/PostGIS database container is running and reachable.
- Verify environment variables in `.env` match the external database credentials and host.

### Spatial Queries Failing
- Ensure the PostGIS extension is enabled on the database (`CREATE EXTENSION postgis;`).
- Check that boundary records contain valid geometry and are not empty.

### Audio Generation Errors
- Confirm optional Azure speech dependencies are installed (`azure-cognitiveservices-speech`).
- If using the built-in tone generator only, leave Azure variables unset to fall back to the default synthesizer.

### LED Sign Not Responding
- Verify hardware cabling and power for the Alpha Protocol LED sign.
- Check the LED controller logs for handshake or checksum errors.
- Confirm LED settings in the admin interface match the physical device configuration.

## Reference Commands
| Task | Command |
|------|---------|
| Check all service status | `sudo systemctl status eas-station.target` |
| View web service logs | `sudo journalctl -u eas-station-web.service -f` |
| Restart the web app | `sudo systemctl restart eas-station-web.service` |
| Restart all services | `sudo systemctl restart eas-station.target` |
| Run database migrations | `cd /opt/eas-station && alembic upgrade head` |
| Generate sample audio | `python3 tools/generate_sample_audio.py` |
| Manual CAP injection | `python3 scripts/manual_eas_event.py --help` |
| Collect SDR diagnostics | `bash scripts/collect_sdr_diagnostics.sh` |

## Related Documentation
- **[Changelog](../reference/CHANGELOG.md)** - Completed features and recent releases
- **[System Architecture](../architecture/SYSTEM_ARCHITECTURE.md)** - Understand the technical design
- **[About EAS Station™](../reference/ABOUT.md)** - Project mission and scope

## Getting Help
- **Documentation:** Consult the [README](https://github.com/KR8MER/eas-station/blob/main/README.md) for architecture, deployment, and configuration details.
- **Change Tracking:** Review the [CHANGELOG](../reference/CHANGELOG.md) for the latest updates and breaking changes.
- **Issue Reporting:** Open a GitHub issue with logs, configuration details (without secrets), and replication steps.

For deeper context on the technology stack and governance, return to the [About page](../reference/ABOUT.md).
