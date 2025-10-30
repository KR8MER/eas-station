# Full EAS Console Parity To-Do List
~~## 1. Multi-SDR Front-End Orchestration *(recommended starting point)*
- [x] Build a modular multi-SDR capture framework.
  - [x] Draft base interfaces and a coordination manager in `app_core/radio/manager.py`.
  - [x] Implement SoapySDR-backed drivers for RTL2832U and Airspy receivers in `app_core/radio/drivers.py`, plus helper registration utilities.
  - [x] Extend the poller layer (`poller/` services) to request audio captures via the new manager when SAME bursts are detected, buffering raw IQ or PCM data per receiver.
  - [x] Persist receiver configuration in Postgres (new tables via Alembic migration under `app_core/models.py`) and surface a CRUD UI in `webapp/routes_settings_radio.py` with a template in `templates/settings/radio.html`.
    - [x] Added SQLAlchemy models for receiver configuration and status history in `app_core/models.py`.
  - [x] Update system health endpoints to report receiver lock, signal metrics, and error states.
~~

## 2. Audio Ingest Pipeline
- [ ] Implement a unified audio ingest pipeline.
  - Create an ingest controller (e.g., `app_core/audio/ingest.py`) that can subscribe to SDR streams, ALSA/pyaudio devices, or file inputs and normalize them into a standard PCM format.
  - Add peak/RMS metering and silence detection to guard against dead air, storing recent measurements in Redis or Postgres for UI display.
  - Expose configuration for capture priority and failover in `.env` parsing (see `configure.py`) and document it in `docs/audio.md`.
  - Provide CLI utilities in `tools/audio_debug.py` to test and calibrate each source.

## 3. Audio Output & Playout Scheduling
- [ ] Build an advanced audio playout engine.
  - Extend `app_utils/eas.py` with a playout queue that chains SAME headers, tones, voice, and recorded content; allow multi-channel output targets (e.g., GPIO-triggered transmitter, streaming encoder, file archive).
  - Integrate with JACK/ALSA via a dedicated service (`components/audio_output_service.py`) that can route simultaneous feeds (monitor, program).
  - Add scheduling/prioritization in `app_core/eas_storage.py` so conflicting alerts follow FCC precedence rules.
  - Update `manual_eas_event.py` and API endpoints to trigger the new playout path and return delivery status.

## 4. GPIO Relay & External Control Enhancements
- [ ] Enhance the relay/GPIO control module.
  - Refactor GPIO handling in `app_utils/eas.py` into a separate helper (`app_utils/gpio.py`) supporting active-high/low, pre/post delays, and watchdog timeouts.
  - Add database logging of relay activations in `app_core/models.py` and surface a timeline in `templates/system_health.html`.
  - Implement a manual override web control in `webapp/routes/system_controls.py`, ensuring proper authentication and audit logging.

## 5. Compliance & Monitoring Dashboard
- [x] Create a compliance dashboard.
  - [x] Build a dashboard view (`webapp/routes/eas_compliance.py`, `templates/eas/compliance.html`) summarizing weekly tests, received vs. relayed alerts, and receiver status.
  - [x] Implement automatic generation of EAS logs and export to CSV/PDF for station records in `app_core/eas_storage.py`.
  - [x] Add alerting hooks (email/SNMP) via a background worker (`app_core/system_health.py`) when receivers or audio paths fail.

## 6. Configuration & Deployment Tooling
- [ ] Ship setup and deployment tooling.
  - Provide guided setup scripts (`tools/setup_wizard.py`) that populate `.env`, radio configs, and audio profiles.
  - Extend Docker services (update `docker-compose.yml`) with containers for audio capture (PulseAudio/JACK) and hardware access, documenting udev rules in `docs/deployment/audio_hardware.md`.
  - Add automated tests (pytest-based under `tests/`) covering ingest/output mocks and GPIO logic to prevent regressions.

## 7. Alert Verification & Analytics
- [x] Build an alert verification pipeline.
  - [x] Correlate CAP messages with downstream playout logs in `app_core/eas_storage.py` to confirm full delivery paths.
  - [x] Add a validation view (`webapp/routes/alert_verification.py`, `templates/eas/alert_verification.html`) that highlights mismatches, missing audio, or delayed retransmissions.
  - [x] Generate trend analytics (per originator, per station) stored in a new reporting table with Alembic migration and surfaced via charts using the existing `static/js/charts/` helpers.
- [x] Ship CSV exports from the verification view using shared utilities in `app_utils/export.py`.
  - [x] Create a way to ingest .WAV and .MP3 files containing EAS Headers and display and possibly store the results of the decode.

## 8. Security & Access Controls
- [ ] Harden operator access and system security.
  - Implement role-based access controls in `app_core/auth/roles.py` and enforce them across admin routes.
  - Require MFA enrollment for operator accounts, adding TOTP enrollment flows in `webapp/routes/auth.py` and templates under `templates/auth/`.
  - Add security auditing hooks that log configuration and control changes to a dedicated table with retention policies.
  - Document security procedures in `docs/security_hardening.md`, including recommended firewall rules and patch cadence.

## 9. Resilience & Disaster Recovery
- [ ] Improve resilience for severe weather outages.
  - Create automated database backup routines (`tools/backup_scheduler.py`) and provide restore playbooks in `docs/disaster_recovery.md`.
  - Add health probes for dependent services (database, Redis, audio daemons) exposed via `/health/dependencies` endpoint.
  - Implement an optional cold-standby node synchronization workflow using `docker-compose.override.yml` examples for multi-site deployments.
  - Provide operator runbooks in `docs/runbooks/outage_response.md` describing failover activation and validation steps.
