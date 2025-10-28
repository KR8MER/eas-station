# 🆘 NOAA CAP Emergency Alert System Help Guide

Welcome to the operator help guide for the NOAA CAP Emergency Alert System (EAS). This document outlines everyday workflows, troubleshooting tips, and reference material for running the application in production or during exercises.

## Getting Started
1. **Review the About document:** The [About page](ABOUT.md) covers system goals, core services, and the complete software stack.
2. **Provision infrastructure:** Deploy Docker Engine 24+ with Docker Compose V2 and ensure a dedicated PostgreSQL 15 + PostGIS database container is available before starting the app stack.
3. **Configure environment variables:** Copy `.env.example` to `.env`, set secure secrets, and update database connection details. Optional Azure AI speech settings can remain blank until credentials are available.
4. **Launch the stack:**
   - Use `docker compose --profile embedded-db up -d --build` to include the optional bundled PostGIS container.
   - Use `docker compose up -d --build` when connecting to an existing PostgreSQL/PostGIS deployment.

## Routine Operations
### Accessing the Dashboard
- Navigate to `http://<host>:5000` in a modern browser.
- Log in with administrator credentials created during initial setup.

### Monitoring Live Alerts
1. Open the **Dashboard** to view active CAP products on the interactive map.
2. Use the **Statistics** tab to analyze severity, event types, and historical counts.
3. Check **System Health** for CPU, memory, disk, and service heartbeat metrics.

### Managing Boundaries and Alerts
- Use the **Boundaries** module to upload county, district, or custom GIS polygons.
- Review stored CAP products in **Alert History**. Filters by status, severity, and date help locate specific messages.
- Trigger manual broadcasts with `manual_eas_event.py` for drills or locally authored messages.

### Generating Sample Audio
- Use **Admin → EAS Output → Manual Broadcast Builder** to craft practice activations entirely in the browser. The tool outputs individual WAV files for the SAME header bursts, attention tone (EAS or 1050 Hz), optional narration, and the EOM burst.
- The legacy helper remains available for automation: `docker compose exec app python tools/generate_sample_audio.py`.

## Troubleshooting
### Application Will Not Start
- Confirm the PostgreSQL/PostGIS database container is running and reachable.
- If you rely on the bundled service, ensure the `embedded-db` profile is enabled (check `COMPOSE_PROFILES` or rerun Compose with `--profile embedded-db`).
- Verify environment variables in `.env` match the external database credentials and host.
- Inspect logs using `docker compose logs -f app` and `docker compose logs -f poller` for detailed error messages.

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
| Build and start services (embedded database) | `docker compose --profile embedded-db up -d --build` |
| Build and start services (external database) | `docker compose up -d --build` |
| View aggregate logs | `docker compose logs -f` |
| Restart the web app | `docker compose restart app` |
| Run database migrations (if applicable) | `flask db upgrade` |
| Legacy sample audio helper | `docker compose exec app python tools/generate_sample_audio.py` |
| Manual CAP injection | `python manual_eas_event.py --help` |

## Getting Help
- **Documentation:** Consult the [README](README.md) for architecture, deployment, and configuration details.
- **Change Tracking:** Review the [CHANGELOG](CHANGELOG.md) for the latest updates and breaking changes.
- **Issue Reporting:** Open a GitHub issue with logs, configuration details (without secrets), and replication steps.

For deeper context on the technology stack and governance, return to the [About page](ABOUT.md).
