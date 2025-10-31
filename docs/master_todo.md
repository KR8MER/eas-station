# Master Implementation Roadmap

This master checklist captures the remaining high-impact efforts required to move the laboratory-grade EAS Console toward a production-ready platform. Each theme links to the current code locations and spells out an actionable plan so contributors can pick up the work quickly. As a reminder, the project is an experimental reference build and must not be relied upon in place of FCC-certified equipment.

## 1. Audio Ingest Unification
- **Goal**: Normalize capture from SDR, ALSA/Pulse, and file inputs into a single managed pipeline.
- **Status**: SAME capture flows exist per receiver, but there is no shared ingest abstraction.
- **Plan**:
  1. Introduce `app_core/audio/ingest.py` with pluggable source adapters and a queue that emits PCM frames.
  2. Add configuration parsing to `configure.py` for source priorities, failover, and metering thresholds.
  3. Persist metering data through a lightweight model (e.g., `AudioIngestStatus`) for UI display in system health views.
  4. Provide calibration and diagnostics utilities under `tools/audio_debug.py` for each adapter.

## 2. Audio Output & Playout Scheduling
- **Goal**: Guarantee deterministic alert playout across tones, voice, GPIO triggers, and archives.
- **Status**: Manual scripts exist; there is no queue-driven playout engine or precedence enforcement.
- **Plan**:
  1. Extend `app_utils/eas.py` with a playout queue orchestrating SAME headers, tones, and recorded content.
  2. Spin up a dedicated service (e.g., `components/audio_output_service.py`) that can target monitor/program buses through ALSA/JACK.
  3. Encode precedence logic in `app_core/eas_storage.py` so overlapping alerts follow FCC ordering.
  4. Update triggering scripts and APIs (`manual_eas_event.py`, `/api/manual-alert`) to report playout status and retention artifacts.

## 3. GPIO & External Control Hardening
- **Goal**: Provide reliable control over transmitters and peripherals with auditability.
- **Status**: GPIO helpers are embedded in broader utilities without normalization or history tracking.
- **Plan**:
  1. Refactor GPIO logic into `app_utils/gpio.py` with configuration for active-high/low, debounce, and watchdog timers.
  2. Store activation history via new models in `app_core/models.py` and surface a timeline under `templates/system_health.html`.
  3. Create operator override views in `webapp/routes/system_controls.py` with proper authentication and audit logs.
  4. Document wiring and safety practices in `docs/hardware/gpio.md`.

## 4. Security & Access Controls
- **Goal**: Enforce least-privilege access and track operator actions.
- **Status**: Basic authentication exists, but roles, MFA, and auditing are absent.
- **Plan**:
  1. Implement role definitions in `app_core/auth/roles.py` and gate sensitive endpoints accordingly.
  2. Add TOTP enrollment and verification flows in `webapp/routes/auth.py` with supporting templates under `templates/auth/`.
  3. Log configuration changes to an `AuditLog` model with retention controls and review pages.
  4. Publish security guidance in `docs/security_hardening.md` with MFA, firewall, and patching expectations.

## 5. Resilience & Disaster Recovery
- **Goal**: Maintain service continuity during hardware or network outages.
- **Status**: No automated backup, health probing, or multi-site guidance is in place.
- **Plan**:
  1. Create `tools/backup_scheduler.py` to orchestrate rolling database/media snapshots and restore validation.
  2. Add `/health/dependencies` probes that cover database, Redis, and audio services for orchestration checks.
  3. Provide optional warm-standby synchronization via `docker-compose.override.yml` samples and documented rsync strategies.
  4. Author operator runbooks in `docs/runbooks/outage_response.md` for failover activation and verification.

## 6. Deployment & Setup Experience
- **Goal**: Reduce onboarding time for lab evaluators and contributors.
- **Status**: Environment bootstrapping is manual, with scattered notes across documentation.
- **Plan**:
  1. Build `tools/setup_wizard.py` to capture station metadata, audio profiles, and receiver definitions into `.env` and the database.
  2. Expand `docker-compose.yml` with optional services for audio capture daemons and document udev/USB permissions under `docs/deployment/audio_hardware.md`.
  3. Add integration tests (pytest) that mock ingest/output paths and GPIO behaviors under `tests/` to protect against regressions.
  4. Centralize post-install checklists in `docs/deployment/post_install.md`.

## 7. Analytics & Compliance Enhancements
- **Goal**: Give operators actionable insight into alert flow health and compliance posture.
- **Status**: Baseline dashboards and CSV exports exist, but trend analysis and anomaly detection are limited.
- **Plan**:
  1. Extend verification analytics in `app_core/eas_storage.py` to compute trend aggregates (per originator, per station) for charts.
  2. Add anomaly detection hooks in `app_utils/analytics.py` that flag missing audio, delayed retransmissions, or receiver outages.
  3. Surface charts and drill-downs within `templates/eas/alert_verification.html` using the existing chart helpers.
  4. Document reporting workflows in `docs/compliance/reporting_playbook.md`.

## 8. Documentation & Operator Enablement
- **Goal**: Keep all safety disclaimers, legal notices, and operating guides synchronized between the repository and web UI.
- **Status**: Legal notices exist, but the roadmap and operator guides are spread across multiple documents without a central index.
- **Plan**:
  1. Maintain this master roadmap alongside `docs/eas_todo.md` to reflect tactical progress.
  2. Cross-link README, ABOUT, and HELP pages to the latest disclaimers (Terms of Use, Privacy Policy) and roadmap status.
  3. Schedule periodic documentation audits to ensure web templates (`templates/*.html`) match repository markdown content.
  4. Capture release notes in `CHANGELOG.md` summarizing roadmap milestones.

---

## Getting Started Checklist
Use this quick triage list when kicking off a new contribution:
1. Pick a roadmap item above and review the referenced modules/templates.
2. Search for existing patterns in `app_core/` and `webapp/routes_*` that mirror the planned work.
3. Draft design notes in an issue or PR describing the scoped deliverables and test strategy.
4. Implement changes alongside unit/integration tests where feasible.
5. Update documentation or UI so operators understand the new capability and the accompanying limitations.

Maintaining this document:
- Update status bullets to reflect newly completed milestones.
- Link to relevant PRs or issues for traceability.
- Keep safety disclaimers and legal obligations visible when new functionality might impact operational risk.
