# Full EAS Console Parity To-Do List

## 1. Multi-SDR Front-End Orchestration
- [ ] Build a modular multi-SDR capture framework.
  - Sketch a `radio/` package (for example `app_core/radio/manager.py`) that defines a `ReceiverInterface` abstraction (configure, tune, start/stop stream) and concrete drivers for supported SDR SDKs (SoapySDR, RTL-SDR via pyrtlsdr, Airspy, etc.).
  - Extend the poller layer (`poller/` services) to request audio captures via the new manager when SAME bursts are detected, buffering raw IQ or PCM data per receiver.
  - Persist receiver configuration in Postgres (new tables via Alembic migration under `app_core/models.py`) and surface a CRUD UI in `webapp/routes/settings_radio.py` with a template in `templates/settings/radio.html`.
  - Update system health endpoints to report receiver lock, signal metrics, and error states.

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
- [ ] Create a compliance dashboard.
  - Build a dashboard view (`webapp/routes/eas_compliance.py`, `templates/eas/compliance.html`) summarizing weekly tests, received vs. relayed alerts, and receiver status.
  - Implement automatic generation of EAS logs and export to CSV/PDF for station records in `app_core/eas_storage.py`.
  - Add alerting hooks (email/SNMP) via a background worker (`app_core/system_health.py`) when receivers or audio paths fail.

## 6. Configuration & Deployment Tooling
- [ ] Ship setup and deployment tooling.
  - Provide guided setup scripts (`tools/setup_wizard.py`) that populate `.env`, radio configs, and audio profiles.
  - Extend Docker services (update `docker-compose.yml`) with containers for audio capture (PulseAudio/JACK) and hardware access, documenting udev rules in `docs/deployment/audio_hardware.md`.
  - Add automated tests (pytest-based under `tests/`) covering ingest/output mocks and GPIO logic to prevent regressions.
