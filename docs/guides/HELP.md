# 🆘 NOAA CAP Emergency Alert System Help Guide

Welcome to the operator help guide for the NOAA CAP Emergency Alert System (EAS). This document outlines everyday workflows, troubleshooting tips, and reference material for evaluating the application in lab environments or during controlled exercises.

> ⚠️ **Important:** EAS Station is experimental software. It has been cross-checked against open-source decoders like [multimon-ng](https://github.com/EliasOenal/multimon-ng), but it is not FCC-certified equipment and must never be relied upon for life-safety alerting.

## Safety Expectations
- Operate the stack in isolated development or staging networks disconnected from broadcast transmitter controls.
- Do not ingest live IPAWS credentials, dispatch feeds, or mission-critical telemetry into this environment.
- Validate any workflows on certified FCC equipment before using them in real-world alerting scenarios.
- Review the repository [Terms of Use](../policies/TERMS_OF_USE) and [Privacy Policy](../policies/PRIVACY_POLICY) with your operators prior to onboarding.

## Getting Started
1. **Review the About document:** The [About page](../reference/ABOUT) covers system goals, core services, and the complete software stack.
2. **Provision infrastructure:** Deploy Docker Engine 24+ with Docker Compose V2 and ensure a dedicated PostgreSQL 15 + PostGIS database container is available before starting the app stack.
3. **Configure environment variables:** Copy `.env.example` to `.env`, set secure secrets, and update database connection details. Optional Azure AI speech settings can remain blank until credentials are available.
4. **Launch the stack:**
   - Run `sudo docker compose up -d --build` after `.env` points at your PostgreSQL/PostGIS deployment.
   - **Note:** Docker commands require root privileges. Use `sudo` if running as a non-root user.

## Routine Operations
### Accessing the Dashboard
- Navigate to `http://<host>:5000` in a modern browser.
- Log in with administrator credentials created during initial setup.

### Monitoring Live Alerts
1. Open the **Dashboard** to view active CAP products on the interactive map.
2. Use the **Statistics** tab to analyze severity, event types, and historical counts.
3. Check **System Health** for CPU, memory, disk, receiver, and audio pipeline heartbeat metrics.

### Reviewing Compliance & Weekly Tests
- Navigate to **Compliance** (`/admin/compliance`) for a consolidated view of received versus relayed alerts, Required Weekly Tests, and background worker activity.
- Receiver health summaries, audio output heartbeat checks, and recent activity timelines pull directly from `app_core/system_health.py` and `app_core/eas_storage.py`.
- Export CSV or PDF compliance logs from the buttons at the top of the page to generate FCC-ready documentation.

### Managing Boundaries and Alerts
- Use the **Boundaries** module to upload county, district, or custom GIS polygons.
- Configure SAME coverage under **Admin → Location Settings**—the picker lists FEMA-defined
  subdivisions alongside entire counties and automatically applies the correct portion digit
  when you select a partial-county code.
- Review stored CAP products in **Alert History**. Filters by status, severity, and date help locate specific messages.
- Trigger manual broadcasts with `manual_eas_event.py` for drills or locally authored messages.

### Managing Receivers
- Visit **Settings → Radio Receivers** (`/settings/radio`) to add, edit, or remove SDR hardware profiles stored in the `RadioReceiver` table.
- Toggle **Auto Start** or **Enabled** to control which receivers the radio manager spins up during poller runs.
- Use the action menu to request synchronized IQ/PCM captures; captured files are surfaced alongside status updates in the compliance dashboard.

### Generating Sample Audio
- Use the **EAS Workflow** console (accessible from the top navigation once logged in) to craft practice activations entirely in the browser. Pick a state or territory, choose the county/parish, FEMA-defined subdivision, or statewide SAME code, and click **Add Location** to build the PSSCCC list—manual pasting is still supported for bulk entry, subdivision selections automatically set the correct portion digit, and the picker enforces the 31-code SAME limit. The originator dropdown now exposes the four FCC originator codes (EAS, CIV, WXR, PEP), the event selector is trimmed to the authorised 47 CFR §11.31(d–e) entries, and the live preview assembles the `ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-` header while explaining each field (including the 0xAB preamble and trailing `NNNN`). Tap **Quick Weekly Test** to preload your configured counties and sample script—the preset omits the attention signal per FCC guidance, but you can re-enable the dual-tone or 1050 Hz alert if needed before confirming the run. After confirmation the workflow automatically generates the package with three SAME bursts, selectable attention tone, optional narration, and EOM WAV assets with one-second guard intervals between each section.
- For automation scripts, the command-line helper is available: `sudo docker compose exec app python tools/generate_sample_audio.py`.

### Verifying Playout & Decoding Audio
- Open **Alert Verification** (`/admin/alert-verification`) to inspect delivery timelines, latency metrics, and per-target outcomes built by `app_core/eas_storage.py`.
- Upload captured WAV or MP3 files to decode SAME bursts directly in the browser; decoded headers, attention tones, and audio segments can be downloaded for archival.
- Store decoded results for future comparison and review the most recent submissions from the sidebar list.

## Troubleshooting
### Application Will Not Start
- Confirm the PostgreSQL/PostGIS database container is running and reachable.
- If you rely on the bundled service, ensure `docker-compose.embedded-db.yml` is included in the command or `COMPOSE_FILE` environment variable.
- Verify environment variables in `.env` match the external database credentials and host.
- Inspect logs using `sudo docker compose logs -f app` and `sudo docker compose logs -f poller` for detailed error messages.

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
| Build and start services (embedded database) | `sudo docker compose -f docker-compose.yml -f docker-compose.embedded-db.yml up -d --build` |
| Build and start services (external database) | `sudo docker compose up -d --build` |
| View aggregate logs | `sudo docker compose logs -f` |
| Restart the web app | `sudo docker compose restart app` |
| Run database migrations (if applicable) | `flask db upgrade` |
| Legacy sample audio helper | `sudo docker compose exec app python tools/generate_sample_audio.py` |
| Manual CAP injection | `python manual_eas_event.py --help` |

## Getting Help
- **Documentation:** Consult the [README](https://github.com/KR8MER/eas-station/blob/main/README.md) for architecture, deployment, and configuration details.
- **Change Tracking:** Review the [CHANGELOG](../reference/CHANGELOG) for the latest updates and breaking changes.
- **Issue Reporting:** Open a GitHub issue with logs, configuration details (without secrets), and replication steps.

For deeper context on the technology stack and governance, return to the [About page](../reference/ABOUT).
