# Full EAS Console Parity To-Do List

> 📌 Looking for a condensed overview with next steps? Start with the [Master Implementation Roadmap](master_todo.md) for high-level priorities and planning guidance, then use this document to track granular milestones.

## Recently Completed Milestones
- **Multi-receiver orchestration** – The new radio manager (`app_core/radio/manager.py`) and SoapySDR drivers coordinate RTL2832U and Airspy hardware, persist configuration in `RadioReceiver` models, and expose CRUD management through `/settings/radio`.
- **Compliance dashboards** – `/admin/compliance` now surfaces received vs. relayed counts, Required Weekly Test tracking, receiver health snapshots, and CSV/PDF exports powered by `app_core/eas_storage.py` and `app_core/system_health.py`.
- **Alert verification lab** – `/admin/alert-verification` correlates playout telemetry with CAP ingestion, visualises latency trends, and decodes uploaded WAV/MP3 captures using `app_utils.eas_decode` helpers.
- **SAME ingest tooling** – Operators can capture, store, and review decoded audio segments through the alert verification workflow, enriching compliance evidence with archival audio artifacts.
~~## 1. Multi-SDR Front-End Orchestration *(recommended starting point)*
- [x] Build a modular multi-SDR capture framework.
  - [x] Draft base interfaces and a coordination manager in `app_core/radio/manager.py`.
  - [x] Implement SoapySDR-backed drivers for RTL2832U and Airspy receivers in `app_core/radio/drivers.py`, plus helper registration utilities.
  - [x] Extend the poller layer (`poller/` services) to request audio captures via the new manager when SAME bursts are detected, buffering raw IQ or PCM data per receiver.
  - [x] Persist receiver configuration in Postgres (new tables via Alembic migration under `app_core/models.py`) and surface a CRUD UI in `webapp/routes_settings_radio.py` with a template in `templates/settings/radio.html`.
    - [x] Added SQLAlchemy models for receiver configuration and status history in `app_core/models.py`.
  - [x] Update system health endpoints to report receiver lock, signal metrics, and error states.
~~

## 2. Audio Ingest Pipeline ✅ COMPLETE
- [x] Implement a unified audio ingest pipeline.
  - [x] ✅ Created `app_core/audio/ingest.py` with pluggable adapters for SDR, ALSA/PyAudio, and file inputs with PCM normalization (PR #315).
  - [x] ✅ Added peak/RMS metering and silence detection with PostgreSQL storage via `AudioSource` models for UI display (PR #315).
  - [x] ✅ Exposed configuration for capture priority and failover in `.env` with comprehensive documentation (PR #315).
  - [x] ✅ Built web UI at `/settings/audio-sources` for testing, calibration, and real-time metering visualization (PR #338, #343).

## 3. Audio Output & Playout Scheduling ✅ COMPLETE
- [x] Build an advanced audio playout engine.
  - [x] ✅ Extended `app_utils/eas.py` with `AudioPlayoutQueue` for SAME headers, tones, voice, and recorded content with GPIO integration (PR #372).
  - [x] ✅ Created `app_core/audio/output_service.py` background service with JACK/ALSA support for monitor/program bus routing (PR #372).
  - [x] ✅ Implemented FCC precedence logic in `app_core/eas_storage.py` (Presidential > Local > State > National > Test) with automatic preemption (PR #372).
  - [x] ✅ Updated EASBroadcaster to support queue mode with playout event tracking and delivery status reporting (PR #372).

## 4. GPIO Relay & External Control Enhancements ✅ COMPLETE
- [x] Enhance the relay/GPIO control module.
  - [x] ✅ Refactored GPIO into unified `app_utils/gpio.py` GPIOController with active-high/low, debounce, and watchdog timers (PR #371).
  - [x] ✅ Added `GPIOActivationLog` model in `app_core/models.py` with activation timeline displayed in GPIO control panel (PR #371).
  - [x] ✅ Implemented manual override web UI at `/admin/gpio` in `webapp/routes/system_controls.py` with authentication and reason logging (PR #371).

## 5. Compliance & Monitoring Dashboard
- [x] Create a compliance dashboard.
  - [x] Build a dashboard view (`webapp/routes/eas_compliance.py`, `templates/eas/compliance.html`) summarizing weekly tests, received vs. relayed alerts, and receiver status.
  - [x] Implement automatic generation of EAS logs and export to CSV/PDF for station records in `app_core/eas_storage.py`.
  - [x] Add alerting hooks (email/SNMP) via a background worker (`app_core/system_health.py`) when receivers or audio paths fail.

## 6. Configuration & Deployment Tooling
- [ ] Ship setup and deployment tooling.
  - [x] Provide guided setup scripts (`tools/setup_wizard.py`) that populate `.env`, radio configs, and audio profiles.
  - [x] Persist Icecast rebroadcast configuration through `/api/audio/icecast/config` and the Audio Settings UI so operator changes survive restarts.
  - [ ] Extend Docker services (update `docker-compose.yml`) with containers for audio capture (PulseAudio/JACK) and hardware access, documenting udev rules in `docs/deployment/audio_hardware.md`.
  - [ ] Add automated tests (pytest-based under `tests/`) covering ingest/output mocks and GPIO logic to prevent regressions.

## 7. Alert Verification & Analytics
- [x] Build an alert verification pipeline.
  - [x] Correlate CAP messages with downstream playout logs in `app_core/eas_storage.py` to confirm full delivery paths.
  - [x] Add a validation view (`webapp/routes/alert_verification.py`, `templates/eas/alert_verification.html`) that highlights mismatches, missing audio, or delayed retransmissions.
  - [x] Generate trend analytics (per originator, per station) stored in a new reporting table with Alembic migration and surfaced via charts using the existing `static/js/charts/` helpers.
- [x] Ship CSV exports from the verification view using shared utilities in `app_utils/export.py`.
  - [x] Create a way to ingest .WAV and .MP3 files containing EAS Headers and display and possibly store the results of the decode.

## 8. Security & Access Controls ✅ COMPLETE
- [x] Harden operator access and system security.
  - [x] ✅ Implemented four-tier RBAC (Admin, Operator, Analyst, Viewer) in `app_core/auth/roles.py` with permission-gated admin routes (PR #373).
  - [x] ✅ Added TOTP-based MFA enrollment flows in `webapp/routes_security.py` with QR code setup UI under `/settings/security` (PR #373).
  - [x] ✅ Built comprehensive audit logging system with dedicated `AuditLog` table, retention policies, and review interface (PR #373).
  - [x] ✅ Documented security migration procedures in `docs/MIGRATION_SECURITY.md` with role assignment, MFA setup, and deployment guidance (PR #373).

## 9. Resilience & Disaster Recovery
- [ ] Improve resilience for severe weather outages.
  - [x] Add health probes for dependent services (database, Redis, audio daemons, Icecast) exposed via `/health/dependencies` endpoint.
  - [x] Store forwarded-alert metadata with downstream message identifiers to support compliance traceability in `ReceivedEASAlert` records.
  - [ ] Provide rotating backup orchestration docs tying together `tools/rotate_backups.py`, systemd timers, and off-site replication.
  - [ ] Implement an optional cold-standby node synchronization workflow using `docker-compose.override.yml` examples for multi-site deployments.
  - [ ] Provide operator runbooks in `docs/runbooks/outage_response.md` describing failover activation and validation steps.

## 10. Stereo & RBDS Demodulation Enhancements
- [x] Deliver FM stereo demodulation with RBDS extraction in `app_core/radio/demodulation.py` so SDR sources can surface PS name, Radio Text, and PTY metadata.
- [ ] Surface RBDS metadata in the radio settings UI and expose it through the analytics API for logging dashboards.
- [ ] Package standby-node bootstrap scripts that restore the latest backup, re-key TLS certificates, and verify Icecast connectivity before entering service.
