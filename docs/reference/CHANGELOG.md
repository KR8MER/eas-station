# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project currently
tracks releases under the 2.x series.

## [2.12.2] - 2025-11-29
### Fixed
- Added an automatic SoapySDR fallback that retries opening receivers without the serial filter when the initial connection fails, letting Airspy radios initialize even if the driver rejects the serialized arguments.
- Updated the OLED layout migration to JSON-serialize `template_data` before persisting it to PostgreSQL so upgrades no longer crash with `can't adapt type 'dict'` errors.

## [2.12.1] - 2025-11-27
### Changed
- Rebuilt the EAS Station wordmark as an inline SVG partial that inherits theme colors for its accent bars and lettering, so the logo automatically matches whichever palette operators choose without filters or manual assets.
- Updated the navigation bar and hero sections on the Help, About, Privacy, Terms, and Version pages to consume the new partial, eliminating duplicate markup and keeping the refreshed layout consistent in every mode.

## [2.12.0] - 2025-11-27
### Added
- Introduced two new UI themes, **Midnight** and **Tide**, complete with theme-switcher entries and CSS variable palettes so operators can choose between a deep slate dark mode and a crisp coastal light mode.
- Published NOAA, FEMA IPAWS, and ARRL resource badges plus a curated "Trusted Field Resources" section on the Help page so the most requested links are visual, organized, and no longer broken.

### Changed
- Modernized the Help & Operations Guide layout with hero quick links, an operations flow mini-timeline, refreshed typography, and a reorganized assistance section for a more professional flow.
- Added dedicated Help-page utility styles that sharpen quick-link tiles, timeline steps, and resource cards, ensuring the guide matches the rest of the dashboard polish.

## [2.11.7] - 2025-11-18
### Changed
- Added a refresh-status meta block on the dashboard map card that now shows the last update time, refresh source, and a live
  countdown so operators can see when the next automatic poll will fire without scrolling.
- Replaced the fixed interval timer with a scheduler that pauses during manual refreshes, resumes after success or failure, and
  prevents overlapping automatic refresh attempts.
- Updated the dashboard refresh action so manual, automatic, keyboard, and debug triggers all share the same code path,
  optionally reload boundary layers, and correctly update the "Last Update" metric and header badge.

## [2.11.6] - 2025-11-23
### Removed
- Dropped the `DEFAULT_AREA_TERMS` environment variable, the accompanying admin editor entry, and the template references so
  environment exports no longer list unused area-search keywords.
### Changed
- Default location snapshots now seed `area_terms` with an empty list rather than mirroring the removed environment variable,
  keeping historic values intact without encouraging new deployments to rely on the deprecated fallback.

## [2.11.5] - 2025-11-23
### Fixed
- Removed the CAP poller's area-term fallback so alerts only appear on `/alerts` when their SAME or UGC codes match the
  configured counties, preventing neighboring-county descriptions from triggering the UI.

## [2.11.4] - 2025-11-22
### Fixed
- Fixed duplicate DOM element declarations on the Weekly Test Automation page that threw JavaScript errors and prevented saved
  SAME/FIPS counties from loading into the scheduler or badge preview.

## [2.11.3] - 2025-11-21
### Fixed
- Ensured the RWT scheduler always opens a Flask application context before touching the
  database and no longer keeps that context open during idle sleeps, eliminating the
  "working outside of application context" failures in the background worker.

## [2.11.2] - 2025-11-20
### Added
- Added an offline alert self-test harness plus `scripts/run_alert_self_test.py` so operators can replay bundled RWT captures,
  verify duplicate suppression, and confirm the configured FIPS list still forwards alerts without waiting for a live activation.
- Folded the alert self-test harness into the **Tools → Alert Verification** dashboard so operators can replay bundled or custom
  audio from the same analytics page and capture screenshots for customer assurances.
### Changed
- Consolidated the alert self-test workflow into the Alert Verification dashboard so operators validate decoding, analytics,
  and FIPS filtering from a single Tools entry instead of bouncing between separate pages.

## [2.10.0] - 2025-11-18
### Added
- Added comprehensive `utilities.css` with gradient, card, badge, spacing, layout, typography, shadow, border, visibility, and animation utilities
- Created reusable template component partials in `templates/components/` for metric cards, stat cards, page headers, status badges, and data lists
- Built new professional version page (`/help/version`) with tabbed interface featuring Overview, Changelog, Features, System Info, and JSON API tabs
- Added `changelog_parser.py` utility to parse CHANGELOG.md files and extract structured version history
- Integrated git commit information display (hash, branch, date, message) on version page
- Added visual timeline visualization for changelog with animated current version marker
- Added comprehensive feature matrix showing all installed system components and their availability status
- Added copy-to-clipboard functionality for JSON API output

### Changed
- Updated `base.html` template to include all CSS files in proper order: design-system, base, components, utilities, layout, and enhancements
- Replaced basic version page with comprehensive tabbed interface showing full release history from parsed CHANGELOG.md
- Enhanced version route in `routes_monitoring.py` to include git metadata and parsed changelog data
- Standardized gradient usage across all templates with new utility classes (.gradient-primary, .gradient-success, etc.)
- Improved version page accessibility with URL hash-based tab navigation

### Fixed
- Fixed inconsistent gradient implementations across templates by centralizing in utilities.css
- Fixed missing CSS files (design-system.css, components.css) not being loaded in base template
- Improved dark theme compatibility for version page components

## [Unreleased]
### Added
- Extended `/api/system_status` and `/api/system_health` with hostname, primary IPv4, uptime, and primary-interface metadata
  so OLED/network templates can surface real host diagnostics.
- Surfaced the Weekly Test Automation console with a county management side panel, Broadcast navigation entry, and in-product callouts so operators can edit RWT schedules and default SAME codes entirely from the UI.
- Added a curated OLED showcase rotation (system overview, alerts, network beacon, IPAWS poll watch, audio health, and audio
  telemetry) plus a `--display-type` flag to `scripts/create_example_screens.py` for targeted installs.
- Enforced Argon Industria OLED reservations by blocking BCM pins 2, 3, 4, and 14 (physical header block 1-8) from GPIO configuration, greying them out in the GPIO Pin Map, and surfacing guidance in setup, environment, and hardware docs.
- Provisioned default OLED status screens with system, alert, and audio telemetry plus on-device button shortcuts (short press to advance rotation, long press for a live snapshot).
- Added Argon Industria SSD1306 OLED module support with full configuration tooling and display workflows
  - Introduced `app_core/oled.py` with luma.oled-based controller, new `OLED_*` environment variables, and runtime initialization hooks
  - Extended screen renderer, manager, and `/api/screens` endpoints with an `oled` display type alongside LED and VFD rotations
  - Updated admin Environment editor, setup wizard, and hardware reference docs for OLED installation and configuration guidance
- Added interactive GPIO Pin Map page (System → GPIO Pin Map) to visualize the 40-pin header and
  assign alert behaviors per BCM pin with persistence to `GPIO_PIN_BEHAVIOR_MATRIX`.
- Added multi-pin GPIO configuration loader with persistent environment editor support, ensuring
  Raspberry Pi deployments can drive multiple relays with active-high/low settings and automatic
  watchdog enforcement during alert playout.
- Added IPAWS poll debug export endpoints for Excel and PDF with UI buttons on `/debug/ipaws` for rapid sharing of poll runs.
- Added comprehensive analytics and compliance enhancements with trend analysis and anomaly detection
  - Implemented `app_core/analytics/` module with metrics aggregation, trend analysis, and anomaly detection
  - Created `MetricSnapshot`, `TrendRecord`, and `AnomalyRecord` database models for time-series analytics
  - Built `MetricsAggregator` to collect metrics from alert delivery, audio health, receiver status, and GPIO activity
  - Implemented `TrendAnalyzer` with linear regression, statistical analysis, and forecasting capabilities
  - Added `AnomalyDetector` using Z-score based outlier detection, spike/drop detection, and trend break analysis
  - Created comprehensive API endpoints at `/api/analytics/*` for metrics, trends, and anomalies
  - Built analytics dashboard UI at `/analytics` with real-time metrics, trend visualization, and anomaly management
  - Added `AnalyticsScheduler` for automated background processing of metrics aggregation and analysis
  - Documented complete analytics system architecture and usage in `app_core/analytics/README.md`
  - Published comprehensive compliance reporting playbook in `docs/compliance/reporting_playbook.md` with workflows for weekly/monthly test verification, performance monitoring, anomaly investigation, and regulatory audit preparation
### Fixed
- Removed the CAP poller's area-term fallback so `/alerts` only surfaces entries that explicitly name the configured SAME or
  UGC codes, eliminating false positives from neighboring county descriptions.
- Added comprehensive audio ingest pipeline for unified capture from SDR, ALSA, and file sources
  - Implemented `app_core/audio/ingest.py` with pluggable source adapters and PCM normalization
  - Added peak/RMS metering and silence detection with PostgreSQL storage
  - Built web UI at `/settings/audio-sources` for source management with real-time metering
  - Exposed configuration for capture priority and failover in environment variables
### Fixed
- Documented the Weekly Test Automation county list regression addressed in 2.11.4 so QA can trace the scheduler fix through the
  release pipeline.
- Added FCC-compliant audio playout queue with deterministic priority-based scheduling
  - Created `app_core/audio/playout_queue.py` with Presidential > Local > State > National > Test precedence
  - Built `app_core/audio/output_service.py` background service for ALSA/JACK playback
  - Implemented automatic preemption for high-priority alerts (e.g., Presidential EAN)
  - Added playout event tracking for compliance reporting and audit trails
- Added comprehensive GPIO hardening with audit trails and operator controls
  - Created unified `app_utils/gpio.py` GPIOController with active-high/low, debounce, and watchdog timers
  - Added `GPIOActivationLog` database model tracking pin activations with operator, reason, and duration
  - Built operator override web UI at `/admin/gpio` with authentication and manual control capabilities
  - Documented complete hardware setup, wiring diagrams, and safety practices in `docs/hardware/gpio.md`
- Added comprehensive security controls with role-based access control (RBAC), multi-factor authentication (MFA), and audit logging
  - Implemented four-tier role hierarchy (Admin, Operator, Analyst, Viewer) with granular permission assignments
  - Added TOTP-based MFA enrollment and verification flows with QR code setup
  - Created comprehensive audit log system tracking all security-critical operations with retention policies
  - Built dedicated security settings UI at `/settings/security` for managing roles, permissions, and MFA
  - Added database migrations to auto-initialize roles and assign them to existing users
  - Documented security hardening procedures in `docs/MIGRATION_SECURITY.md`
- Redesigned EAS Station logo with modern signal processing visualization
  - Professional audio frequency spectrum visualization with animated elements
  - Radar/monitoring circular grid overlay for technical aesthetic
  - Animated signal waveform with alert gradient effects
  - Deep blue to cyan gradient representing signal monitoring and alert processing
  - SVG filters for depth, glow effects, and contemporary design polish

### Fixed
- Restored SSL certificate and private key export downloads by mounting the Let's Encrypt
  volume into the application container and searching both `/etc/letsencrypt` and
  `/app-config/certs` for domain materials before returning actionable guidance.
- Converted the Stream Profiles interface to the shared base layout with Bootstrap 5 modal
  controls so its header, theming, and actions match the rest of the application.
- Reduced excessive whitespace in dark themes by introducing theme-aware layout spacing
  variables that tighten main content padding and footer offsets across all dark presets.
- Ensure the 20251107 decoded audio segment migration only adds the
  attention tone and narration columns when they are missing so fresh
  installs don't abort before administrator accounts can be created.
- Allow fresh installations to run Alembic migrations without errors by skipping the
  20241205 FIPS location settings upgrade when the `location_settings` table has not
  been created yet.
- Prevent SDR audio monitors from returning HTTP 503 errors by restoring persisted adapters before serving playback, start/stop,
  and waveform endpoints so the radio settings page can stream audio reliably after restarts.
- Force dark-mode typography and link treatments to use the light contrast palette when `data-theme-mode="dark"` is active so
  copy remains readable across every dark theme variation.
- Remove the auto-injected skip navigation anchors so the navbar's leading section only presents the wordmark and health status
  indicator.
- Improved readability of dark UI themes by brightening background surfaces, borders, and text contrast variables shared across the design system, and by mapping the design system colors to each theme's palette so custom dark presets retain their intended contrast.
- Surface actionable diagnostics when GPIO hardware is inaccessible, highlighting missing
  /dev/gpiomem access and read-only sysfs mounts so deployments can correct permissions.
- Replaced the deprecated `RPi.GPIO` backend with `gpiozero` output devices and ensured typing imports
  are available so Raspberry Pi deployments boot cleanly on Pi 5 hardware.
- Ensured Docker Compose publishes nginx ports on both IPv4 and IPv6 addresses so external scanners can reach the HTTPS endpoint over IPv6.
- Reduced nginx static asset cache lifetime from 24 hours to five minutes so freshly deployed frontend changes appear without manual cache purges.
- Prevented alert verification page timeouts by offloading audio decoding to a background worker and persisting progress/results for UI polling.
- Added Raspberry Pi 5-compatible `lgpio` fallback for GPIO control so BCM pins configured as active-high no longer enter an error state when `RPi.GPIO` is unavailable.

### Changed
- Refined the theming system with higher-contrast logo treatments and added Aurora, Nebula, and Sunset presets to expand the built-in palette while keeping the wordmark legible across gradients.
- Renamed the "EAS Workflow" console to **Broadcast Builder** and linked the Weekly Test Automation page throughout the Broadcast menu and workflow hero banner so automation tooling is obvious to operators.
- **Consolidated stream support in Audio Sources system** - Removed stream support from RadioReceiver model and UI, centralizing all HTTP/M3U stream configuration through the Audio Sources page where StreamSourceAdapter already provided full functionality
  - Removed `source_type` and `stream_url` fields from RadioReceiver database model
  - RadioReceiver now exclusively handles SDR hardware (RTL-SDR, Airspy)
  - Added Stream (HTTP/M3U) option to Audio Sources UI dropdown
  - Added stream configuration fields (URL, format) to Audio Sources modal
  - Updated navigation to point to `/settings/audio` instead of deprecated `/audio/sources` route
  - Clear separation of concerns: Radio = RF hardware, Audio = all audio ingestion sources

### Fixed
- Restored `/stats` dashboard data by providing CAP alert history, reliability metrics, and polling debug visibility in `/logs`.
- **Fixed Audio Sources page not loading sources** - Corrected missing element IDs and event listeners that prevented audio sources from displaying on `/settings/audio` page
  - Fixed element IDs to match JavaScript expectations (`active-sources-count`, `total-sources-count`, `sources-list`)
  - Fixed modal IDs to match JavaScript (`addSourceModal`, `deviceDiscoveryModal`)
  - Added event listeners for Add Source, Discover Devices, and Refresh buttons
  - Added toast container for notification display
  - Removed deprecated `/audio/sources` page route
- **Fixed JSON serialization errors in audio APIs** - Backend was returning -np.inf (negative infinity) for dB levels when no audio present, causing "No number after minus sign in JSON" errors in frontend
  - Added `_sanitize_float()` helper that converts infinity/NaN to valid numbers (-120.0 dB for silence)
  - Applied sanitization to all audio API endpoints: `/api/audio/sources`, `/api/audio/metrics`, `/api/audio/health`
  - Ensures all API responses are valid JSON that browsers can parse
- **Fixed Add Audio Source button not working** - Form element IDs didn't match JavaScript expectations
  - Changed form ID from `audioSourceForm` to `addSourceForm`
  - Changed container ID from `deviceParamsContainer` to `sourceTypeConfig`
  - Updated field IDs to match JavaScript (`sourceName`, `sampleRate`, `channels`, `silenceThreshold`, `silenceDuration`)
  - Added missing `silenceDuration` field for silence detection configuration
- **Fixed audio source delete, start, and stop operations failing with 404 errors**
  - Added `encodeURIComponent()` to all fetch URLs for proper URL encoding of source names with special characters
  - Added `sanitizeId()` helper to create safe HTML element IDs (replaces special chars with underscores)
  - Fixed onclick handler escaping to prevent JavaScript injection vulnerabilities
  - Updated `updateMeterDisplay()` to use sanitized IDs when finding meter elements
- **Fixed DOM element ID mismatches** - JavaScript was looking for elements with IDs that didn't exist in HTML template
  - Changed `healthScore` → `overall-health-score`
  - Changed `silenceAlerts` → `alerts-count`
  - Added hidden `overall-health-circle` and `alerts-list` elements required by JavaScript
- **Fixed Edit Audio Source button failing** - Edit modal didn't exist in HTML template
  - Added complete `editSourceModal` with all required fields (priority, silence threshold/duration, description, enabled, auto-start)
  - Source name and type are readonly (can't be changed after creation)
  - Fixed device discovery modal to have `discoveredDevices` div for JavaScript
- **Added detailed error messages for audio source failures** - Users now see exactly why sources fail instead of generic "error" status
  - Added `error_message` field to `AudioSourceAdapter` to track failure details
  - Stream connection failures show max reconnection attempts message
  - Missing dependencies show installation instructions (e.g., "install pydub")
  - Error messages displayed in red alert boxes on source cards
  - Added disconnected status alert showing reconnection attempts
- **Fixed numpy float32 JSON serialization error** - Audio APIs were returning 500 errors due to numpy types not being JSON-serializable
  - Updated `_sanitize_float()` to detect and convert numpy.floating and numpy.integer types to Python float
  - Fixes "Object of type float32 is not JSON serializable" errors on `/api/audio/sources` and `/api/audio/metrics`
- **Fixed numpy bool_ JSON serialization error** - Audio APIs were returning intermittent 500 errors due to numpy boolean types not being JSON-serializable
  - Added `_sanitize_bool()` helper to convert numpy.bool_ types to Python bool
  - Applied to all boolean fields: silence_detected, clipping_detected, enabled, auto_start, acknowledged, resolved, is_active, is_healthy, error_detected
  - Fixes "Object of type bool is not JSON serializable" errors on `/api/audio/metrics`, `/api/audio/health`, and `/api/audio/alerts`
- **Added pydub dependency** for MP3/AAC/OGG stream decoding from HTTP/Icecast sources
  - Added `pydub==0.25.1` to requirements.txt (requires ffmpeg system package already in Dockerfile)
- Fixed module import paths in scripts/manual_eas_event.py and scripts/manual_alert_fetch.py by adding repository root to sys.path
- Fixed CSRF token protection in password change form (security settings)
- Fixed audit log pagination to cap per_page parameter at 1000 to prevent DoS attacks
- Fixed timezone handling to use timezone-aware UTC timestamps instead of naive datetime.utcnow()
- Fixed migration safety with defensive checks for permission lookup to handle missing permissions gracefully
- Fixed markdown formatting in MIGRATION_SECURITY.md with proper heading levels and code block language specs

### Changed
- Enhanced AGENTS.md with bug screenshot workflow, documentation update requirements, and semantic versioning conventions
- Reorganized root directory by moving development/debug scripts to scripts/deprecated/ and utility scripts to scripts/
- Removed README.md.backup file from repository
- Improved error logging to use logger.exception() instead of logger.error() in 8 locations across security routes for better debugging

### Added
- Added an admin location reference view that summarises the saved NOAA zone catalog
  entries, SAME/FIPS codes, and keyword matches so operators can understand how
  the configuration drives alert filtering.
- Added a public forecast zone catalog loader that ingests the bundled
  `assets/z_05mr24.dbf` file into a dedicated reference table, exposes a
  `tools/sync_zone_catalog.py` helper, and validates admin-supplied zone codes
  against the synchronized metadata.
- Added an interactive `.env` setup wizard available at `/setup`, with a CLI
  companion (`tools/setup_wizard.py`), so operators can generate secrets,
  database credentials, and location defaults before first launch without
  editing text files by hand.
- Added a repository `VERSION` manifest, shared resolver, and `tests/test_release_metadata.py` guardrail so version bumps and changelog updates stay synchronised for audit trails.
- Added `tools/inplace_upgrade.py` for in-place upgrades that pull, rebuild, migrate, and restart services without destroying volumes, plus `tools/create_backup.py` to snapshot `.env`, compose files, and a Postgres dump with audit metadata before changes.
- Introduced a compliance dashboard with CSV/PDF exports and automated
  receiver/audio health alerting to monitor regulatory readiness.
- Enabled the manual broadcast builder to target county subdivisions and the
  nationwide 000000 SAME code by exposing P-digit selection alongside the
  existing state and county pickers.
- Introduced a dedicated Audio Archive history view with filtering, playback,
  printing, and Excel export support for every generated SAME package.
- Surfaced archived audio links throughout the alert history and detail pages so
  operators can quickly review transmissions tied to a CAP product.
- Added a `manual_eas_event.py` utility that ingests raw CAP XML (e.g., RWT/RMT tests),
  validates the targeted SAME/FIPS codes, and drives the broadcaster so operators can
  trigger manual transmissions with full auditing.
- Introduced the `EAS_MANUAL_FIPS_CODES` configuration setting to control which
  locations are eligible for manual CAP forwarding.
- Bundled the full national county/parish FIPS registry for manual activations and
  exposed helpers to authorize the entire dataset with a single configuration flag.
- Cataloged the nationwide SAME event code registry together with helper utilities so
  broadcasters and manual tools can resolve official names, presets, and headers.
- Added a CLI helper (`tools/generate_sample_audio.py`) to create demonstration SAME audio
  clips without ingesting a live CAP product.
- Delivered an in-app Manual Broadcast Builder on the EAS Output tab so operators can generate SAME headers, attention tones (EAS dual-tone or 1050 Hz), optional narration, and composite audio without leaving the browser.
- Archived every manual EAS activation automatically, writing audio and summary
  assets to disk, logging them in the database, and exposing a printable/exportable
  history table within the admin console.
- Unlocked an in-app first-run experience so the Admin panel exposes an
  "First-Time Administrator Setup" wizard when no accounts exist.
- Introduced optional Azure AI speech synthesis to append narrated voiceovers when the
  appropriate credentials and SDK are available.

## [2.9.0] - 2025-11-15
### Added
- OLED alert rotations now preempt normal playlists when `skip_on_alert` is enabled, prioritizing the most severe alert and
  scrolling its text in a large font for the entire duration. EAS/IPAWS sources render their full plain-language narration while
  other sources fall back to headline + description so operators always see useful context.
- `/api/alerts` now returns each alert's source and (when available) the cached EAS narration text, allowing custom OLED/LED
  templates or Portainer dashboards to display the same preemption-ready payloads.

## [2.8.0] - 2025-02-15

### Fixed
- Prevented the `20251113_add_serial_mode_to_led_sign_status` Alembic migration from
  raising `TypeError: execute() takes 2 positional arguments but 3 were given` by
  issuing the default value backfill through the SQLAlchemy bind connection instead
  of `op.execute`, ensuring upgrades complete cleanly before the app starts.
- Added an offline pyttsx3 text-to-speech provider so narration can be generated without
  external network services when the engine is installed locally.
- Authored dedicated `docs/reference/ABOUT.md` and `docs/guides/HELP.md` documentation describing the system mission, software stack, and operational playbooks, with cross-links from the README for quick discovery.
- Exposed in-app About and Help pages so operators can read the mission overview and operations guide directly from the dashboard navigation.
- Distributed a `docker-compose.embedded-db.yml` overlay so application services
  can either rely on the bundled `alerts-db` PostGIS container or connect to an
  existing deployment without editing the primary compose file.
- Documented open-source dependency attributions in the docs and surfaced
  maintainers, licenses, and usage details on the in-app About page.
### Changed
- Documented why the platform remains on Python 3.12 instead of the new Python 3.13 release across the README and About surfaces,
  highlighting missing Linux/ARM64 wheels for SciPy and pyttsx3 and the security patch workflow for the current runtime.
- Documented Debian 14 (Trixie) 64-bit as the validated Raspberry Pi host OS while clarifying that the container image continues to ship on Debian Bookworm via the `python:3.12-slim-bookworm` base.
- Documented the release governance workflow across the README, ABOUT page, Terms of Use, master roadmap, and site footer so version numbering, changelog discipline, and regression verification remain mandatory for every contribution.
- Suppressed automatic EAS generation for Special Weather Statements and Dense Fog Advisories to align with standard activation practices.
- Clarified in the README and dependency notes that PostgreSQL with PostGIS must run in a dedicated container separate from the application services.
- Documented a single-line command for cloning the Experimental branch and launching the Docker Compose stack so operators can bootstrap quickly.
- Clarified the update instructions to explicitly pull the Experimental branch when refreshing deployments.
- Documented the expectation that deployments supply their own PostgreSQL/PostGIS host and simplified Compose instructions to run only the application services.
- Reworked the EAS Output tab with an interactive Manual Broadcast Builder and refreshed the README/HELP documentation to cover the browser-based workflow.
- Enhanced the Manual Broadcast Builder with a hierarchical state→county SAME picker, a deduplicated PSSCCC list manager, a live `ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-` preview with field-by-field guidance, and refreshed docs that align with commercial encoder terminology.
- Added a one-touch **Quick Weekly Test** preset to the Manual Broadcast Builder so operators can load the configured SAME counties, test status, and sample script before generating audio.
- Updated the Quick Weekly Test preset to omit the attention signal by default and added a
  “No attention signal (omit)” option so manual packages can exclude the dual-tone or 1050 Hz
  alert when regulations allow.
- Bundled `ffmpeg`, `espeak`, and `libespeak-ng1` system packages in the Docker image so offline narration dependencies work out of the box during container builds.
### Fixed
- Inserted the mandatory display-position byte in LED sign mode fields so M-Protocol
  frames comply with Alpha controller requirements.
- Surface offline pyttsx3 narration failures in the Manual Broadcast Builder with
  the underlying error details so operators can troubleshoot configuration
  issues without digging through logs.
- Detect missing libespeak dependencies when pyttsx3 fails and surface
  installation guidance so offline narration can be restored quickly.
- Detect missing ffmpeg dependencies and empty audio output from pyttsx3 so the
  Manual Broadcast Builder can steer operators toward the required system
  packages when narration silently fails.
- Surface actionable pyttsx3 dependency hints when audio decoding fails so
  the Manual Broadcast Builder points operators to missing libespeak/ffmpeg
  packages instead of opaque errors.
- Added an espeak CLI fallback when pyttsx3 fails to emit audio so offline
  narration still succeeds even if the engine encounters driver issues.
- Count manual EAS activations when calculating Audio Archive totals and show them
  alongside automated captures so archived transmissions are visible in the history
  table.
- Moved the Manual Broadcast Archive card to span the full EAS console width,
  matching the builder/output layout and preventing it from being tucked under the
  preview panel on large displays.
- Corrected the Quick Weekly Test preset so the sample Required Weekly Test script
  populates the message body as expected.
- Standardised the manual and automated encoder timing so each SAME section includes a one-second
  guard interval and the End Of Message burst transmits the canonical `NNNN` payload per 47 CFR §11.31.
- Replaced the free-form originator/call-sign fields with a guarded originator dropdown listing the four FCC originator codes (EAS, CIV, WXR, PEP) and a station identifier input, filtered the event selector to remove placeholder `??*` codes, and enforced the 31-location SAME limit in the UI.
- Simplified database configuration by deriving `DATABASE_URL` from the `POSTGRES_*` variables when it is not explicitly set, eliminating duplicate secrets in `.env`.
- Restored the `.env` template workflow, updated quick-start documentation to copy
  `.env.example`, and reiterated that operators must rotate the placeholder
  secrets immediately after bootstrapping the stack.
- Streamlined `.env.example` by removing unused settings and documenting optional location defaults leveraged by the admin UI.
- Updated the GPIO relay control so it remains engaged for the full alert audio playback,
  using `EAS_GPIO_HOLD_SECONDS` as the minimum release delay once audio finishes.
- Automatically generate and play an End-Of-Message (EOM) data burst sequence after each alert
  so receivers reliably return to normal programming when playback completes.
- Refactored the monolithic `app.py` into cohesive `app_core` modules (alerts, boundaries,
  database models, LED integration, and location settings) and slimmed the Flask entrypoint so
  shared helpers can be reused by CLIs and tests without importing the entire web stack.
- Manual CAP tooling now validates inputs against the registry, surfaces friendly area
  names in CLI output and audit logs, and warns when CAP payloads reference unknown codes.
- Manual CAP broadcasts enforce configurable SAME event allow-lists and display the
  selected code names in CLI output and audit trails while the broadcaster consumes
  the resolved identifiers for header generation.
- Ensured automated and manual SAME headers include the sixteen 0xAB preamble bytes
  before each burst so the transmitted RTTY data fully complies with 47 CFR §11.31.
- Restricted automatic EAS activations to CAP products whose SAME event codes match
  the authorised 47 CFR §11.31(d–f) tables, preventing unintended broadcasts for
  unclassified alerts.
### Fixed
- Corrected SAME/RTTY generation to follow 47 CFR §11.31 framing (seven LSB-first ASCII bits, trailing null bit, and precise 520 5⁄6 baud timing) so the AFSK bursts decode at the proper pitch and speed.
- Fixed admin location settings so statewide SAME/FIPS codes remain saved when operators select entire states.
- Corrected the generated End Of Message burst to prepend the sixteen 0xAB preamble bytes so decoders reliably synchronise with the termination header.
- Trimmed the manual and UI event selector to the authorised 47 CFR §11.31(d–e) code tables and removed placeholder `??*` entries.
- Eliminated `service "app" depends on undefined service "alerts-db"` errors by removing the optional compose overlay, deleting the unused service definition, and updating documentation to assume an external database.
- Ensured the Manual Broadcast Builder always renders the SAME event code list so operators can
  pick the desired code even when client-side scripts are blocked or fail to load.
- Fixed the Manual Broadcast Builder narration preview so newline escaping no longer triggers a
  browser-side "Invalid regular expression" error when rendering generated messages.
- Restored the `.env.example` template and documented the startup error shown when the
  file is missing so Docker Compose deployments no longer fail with "env file not found".
- Skip PostGIS-specific geometry checks when running against SQLite and store geometry
  fields as plain text on non-PostgreSQL databases so local development can initialize
  without spatial extensions.
- Corrected manual CAP allow-all FIPS logic to use 6-digit SAME identifiers so alerts configured
  for every county pass validation and display proper area labels.
- Resolved an SQLAlchemy metadata attribute conflict so the Flask app and polling services can
  load the EAS message model without raising declarative mapping errors.
- Ensure the Flask application automatically enables the PostGIS extension before creating
  tables so startup succeeds on fresh PostgreSQL deployments.
- Rebuilt the LED sign M-Protocol frame generation to include the SOH/type/address header,
  compute the documented XOR checksum, and verify ACK/NAK responses so transmissions match the
  Alpha manual.
- Honored the Alpha M-Protocol handshake by draining stale responses, sending EOT after
  acknowledgements, and clamping brightness commands to the single-hex-digit range required by
  the manual.
- Fixed the Alpha text write command to send the single-byte "A" opcode followed by the
  file label so frames no longer begin with an invalid "AAA" sequence that the manual forbids.
- Prevented the LED fallback initializer from raising a `NameError` when the optional
  controller module is missing so deployments without sign hardware continue to boot.

## [2.7.5] - 2025-11-15
### Fixed
- Allow first-time deployments to create the initial administrator from a dedicated
  setup wizard page so Portainer users without console access can finish onboarding
  without running CLI commands.

## [2.7.2] - 2025-11-15
### Fixed
- Restore SDR audio monitor adapters on-demand for all audio ingest APIs, eliminating the recurring 503 responses and broken
  playback streams reported on the radio settings page.

## [2.7.1] - 2025-11-15
### Fixed
- Backfill SDR squelch columns automatically when legacy deployments haven't run the
  latest Alembic migration so radio settings and monitoring pages load without
  column errors.

## [2.7.0] - 2025-11-14
### Added
- Added an audio-monitor provisioning API and UI workflow that auto-starts SDR Icecast streams, surfaces RBDS programme data, and exposes squelch/carrier telemetry directly from the radio settings page for immediate listening checks.

### Changed
- Enabled configurable squelch thresholds, timing, and carrier-loss alarms for SDR receivers with service-specific defaults tuned for Raspberry Pi deployments, reducing false positives while keeping CPU usage low.

## [2.4.16] - 2025-11-10
### Fixed
- Removed the `APP_BUILD_VERSION` environment override so persistent `.env` files can no longer pin stale release numbers; the UI now always reflects the repository `VERSION` manifest.

## [2.4.15] - 2025-11-10
### Fixed
- Ensured the version resolver invalidates its cache when `APP_BUILD_VERSION` or the `VERSION` file changes so dashboards display
  the latest release metadata immediately after deployments.
- Disabled caching on the built-in documentation viewer routes to prevent browsers and reverse proxies from serving outdated
  markdown content.

## [2.4.14] - 2025-11-10
### Fixed
- Added automatic cache-busting query parameters to all Flask-served static asset URLs so envoy/nginx layers fetch freshly deployed bundles instead of stale copies (Screenshot_7-11-2025_75931_wxalerts.k8tek.net.jpeg).

## [2.4.11] - 2025-11-09
### Fixed
- Corrected the documentation viewer's Mermaid block detection to support Windows-style line endings so diagrams render instead of showing raw code.
- Refreshed system version metadata on each request so the footer and monitoring endpoints display the latest release after version bumps.

## [2.4.1] - 2025-11-09
### Fixed
- **Resolved production nginx image regressions** - Ensured HTTPS container bundles required tooling and static assets
  - Added `certbot` to nginx Docker image so Let's Encrypt provisioning no longer fails with `certbot: not found`
  - Copied repository `static/` directory into the image to stop 404 errors for CSS, JS, and image assets
  - Updated nginx configuration to use the modern `http2 on;` directive and silence deprecation warnings during startup

## [2.3.12] - 2025-11-15
### Fixed
- Hardened admin location validation so statewide SAME/FIPS codes are always accepted and labelled consistently when saving.

## [2.3.11] - 2025-11-14
### Fixed
- Fixed admin location settings so statewide SAME/FIPS codes remain saved when operators select entire states.

## [2.3.10] - 2025-11-03
### Changed
- Reformatted SAME plain-language summaries to omit appended FIPS and state code
  suffixes, adopt the FCC county listing punctuation, and present the event
  description in the expected uppercase style.

## [2.3.9] - 2025-11-03
### Changed
- Display the per-location FIPS identifiers and state codes on the Audio Archive
  detail view so operators can confirm the targeted jurisdictions for each
  generated message without leaving the page.

## [2.3.8] - 2025-11-02
### Fixed
- Backfilled missing plain-language SAME header summaries when loading existing
  audio decodes so the alert verification and audio history pages regain their
  readable sentences.

## [2.3.7] - 2025-11-02
### Changed
- Linked the admin location reference summary and API responses to the bundled
  SAME location code directory (`assets/pd01005007curr.pdf`) and NOAA Public
  Forecast Zones catalog so operators see the authoritative data sources.

## [2.3.6] - 2025-11-02
### Added
- Added an admin location reference API and dashboard card that surfaces the saved
  NOAA zones, SAME/FIPS counties, and keyword filters so operators can review
  their configuration and confirm catalog coverage.

## [2.3.5] - 2025-11-01
### Fixed
- Prevented the public forecast zone catalog synchronizer from inserting duplicate
  zone records when the source feed repeats a zone code, eliminating startup
  failures when multiple workers initialize simultaneously.

## [2.3.3] - 2025-11-13
### Changed
- Rebased the container on the `python:3.12-slim-bookworm` image, added security upgrades during build, and refreshed pinned Python dependencies (including SciPy 1.14.1) to address Docker Hub vulnerability scans.
- Documented Raspberry Pi 5 (4 GB RAM) as the reference platform across the README, policy documents, and in-app help/about pages while noting continued Raspberry Pi 4 compatibility.

## [2.3.2] - 2025-11-02
### Changed
- The web server now falls back to a guarded setup mode when critical
  configuration is missing or the database is unreachable, redirecting all
  requests to `/setup` so operators can repair the environment without editing
  `.env` manually first.

## [2.3.1] - 2025-11-01
### Added
- Added one-click backup and upgrade controls to the Admin System Operations panel, wrapping the existing CLI helpers in background tasks with status reporting.

## [2.1.9] - 2025-10-31
### Added
- Delivered a WYSIWYG LED message designer with content-editable line cards, live colour/effect previews,
  and per-line special function toggles so operators can see the final layout before transmitting.

### Changed
- Refactored the LED controller to accept structured line payloads, allowing nested colours, display modes,
  speeds, and special functions per segment while keeping backwards compatibility with plain text arrays.
- Enhanced the LED send API to normalise structured payloads, summarise mixed-format messages for history
  records, and persist the flattened preview text for operator review.

## [2.1.8] - 2025-10-30
### Fixed
- Inserted the mandatory display-position byte in LED sign mode fields so M-Protocol
  frames comply with Alpha controller requirements.

## [2.1.7] - 2025-10-29
### Removed
- Purged IDE metadata, historical log outputs, unused static assets, and legacy diagnostic scripts
  that were no longer referenced by the application.
### Changed
- Updated ignore rules and documentation so generated EAS artifacts and runtime logs remain outside
  version control while keeping the static directory available for downloads.

## [2.1.6] - 2025-10-28
### Changed
- Aligned build metadata across environment defaults, the diagnostics endpoints, and the
  site chrome so `/health`, `/version`, and the footer display the same system version.
- Refreshed the README to highlight core features, deployment steps, and configuration
  guidance.

## [2.1.5] - 2025-10-27
### Added
- Added database-backed administrator authentication with PBKDF2 hashed passwords,
  login/logout routes, session persistence, CLI bootstrap helpers, and audit logging.
- Expanded the admin console with a user management tab, dedicated login page, and APIs
  for creating, updating, or disabling accounts.
- Introduced `.env.example` alongside README instructions covering environment setup and
  administrator onboarding.
- Implemented the EAS broadcaster pipeline that generates SAME headers, synthesizes WAV
  audio, optionally toggles GPIO relays, stores artifacts on disk, and exposes them
  through the admin interface.
- Published `/admin/eas_messages` for browsing generated transmissions and downloading
  stored assets.
### Changed
- Switched administrator password handling to Werkzeug's PBKDF2 helpers while migrating
  legacy salted SHA-256 hashes on first use.
- Extended the database seed script to provision `admin_users`, `eas_messages`, and
  `location_settings` tables together with supporting indexes.

## [2.1.4] - 2025-10-26
### Added
- Persisted configurable location settings with admin APIs and UI controls for managing
  timezone, SAME/UGC codes, default LED lines, and map defaults.
- Delivered a manual NOAA alert import workflow with backend validation, a reusable CLI
  helper, and detailed admin console feedback on imported records.
- Enabled editing and deletion of stored alerts from the admin console, including audit
  logging of changes.
- Broadened boundary metadata with new hydrography groupings and preset labels for water
  features and infrastructure overlays.
### Changed
- Hardened manual import queries to enforce supported NOAA parameters and improved error
  handling for administrative workflows.
- Updated Docker Compose defaults and boundary ingestion utilities to better support
  mixed geometry types.

## [2.1.0] - 2025-10-25
### Added
- Established the NOAA CAP alert monitoring stack with Flask, PostGIS persistence,
  automatic polling, and spatial intersection tracking.
- Delivered the interactive Bootstrap-powered dashboard with alert history, statistics,
  health monitoring, and boundary management tools.
- Integrated optional LED sign controls with configurable presets, message scheduling,
  and hardware diagnostics.
- Added containerized deployment assets (Dockerfile, docker-compose) and operational
  scripts for managing services.

## [2.2.0] - 2025-10-29
### Added
- Recorded the originating feed for each CAP alert and poll cycle, exposing the source in the
  alerts dashboard, detail view, exports, and LED signage.
- Normalised IPAWS XML payloads with explicit source tagging and circle-to-polygon conversion
  while tracking duplicate identifiers filtered during multi-feed polling.

### Changed
- Automatically migrate existing databases to include `cap_alerts.source` and
  `poll_history.data_source` columns during application or poller start-up.
- Surfaced poll provenance in the statistics dashboard, including the observed feed sources
  for the most recent runs.

## [2.3.4]
### Added
- Documented the public forecast zone catalog synchronisation workflow and
  prepared release metadata for the 2.3.4 build.

## [2.3.0] - 2025-10-30
### Changed
- Normalized every database URL builder to require `POSTGRES_PASSWORD`, apply safe
  defaults for the other `POSTGRES_*` variables, and URL-encode credentials so
  special characters work consistently across the web app, CLI, and poller.
- Trimmed duplicate database connection variables from the default `.env` file and
  aligned the container metadata defaults with the current PostGIS image tag.
- Bumped the default `APP_BUILD_VERSION` to 2.3.0 across the application and sample
  environment template so deployments surface the new release number.

## [2.4.9] - 2025-11-09
### Fixed
- Switch certbot issuance to standalone HTTP-01 mode so the container itself binds to port 80 during startup,
  eliminating the connection reset failures that occurred before nginx began serving traffic.
- Log the standalone challenge server activation so operators can confirm ACME connectivity when debugging
  certificate renewals.

## [2.4.8] - 2025-11-09
### Fixed
- Verify existing certificates against the system trust store and expiration before skipping issuance, so stale self-signed chains are purged and a new ACME request runs on startup.
- Log detailed reasons when certificate validation fails and remove the associated material, making it obvious when fallback artifacts block public issuance.

## [2.4.7] - 2025-11-09
### Fixed
- Detect existing certificates issued by anything other than Let's Encrypt (including legacy self-signed chains)
  and automatically purge them so startup always retries public issuance instead of reusing stale fallbacks.
- Extend the certificate cleanup routine to treat unknown issuers as invalid, guaranteeing that deployments replace
  outdated self-signed material with a fresh ACME request on every boot.

## [2.4.6] - 2025-11-09
### Fixed
- Remove any lingering self-signed certificate directories (including suffixed variants) on
  container startup so stale fallbacks are purged before new issuance attempts.
- Extend the certificate purge routine to clean historical self-signed material before certbot
  runs, preventing nginx from reusing temporary chains across restarts.

## [2.4.5] - 2025-11-09
### Fixed
- Purge the domain's existing `/etc/letsencrypt` material whenever a self-signed
  fallback is detected so administrators no longer need to manually delete
  leftover files before retrying ACME issuance.
- Force certbot to request a fresh certificate for self-signed domains by
  assigning a stable certificate name and forcing renewal so nginx replaces
  fallback chains during the next startup sequence.

## [2.4.4] - 2025-11-09
### Fixed
- Detect legacy self-signed fallback certificates by inspecting the existing fullchain.pem and
  purge them before retrying Let's Encrypt so deployments stop serving stale fallback chains
  from earlier releases.
- Remove invalid certificate files prior to issuing new ones so nginx never launches with the
  leftover self-signed materials while ACME runs.

## [2.4.3] - 2025-11-09
### Fixed
- Detect previously generated self-signed certificates and automatically retry Let's Encrypt
  issuance so production domains replace fallback certs on the next start.
- Tag self-signed fallbacks with a marker file and clear it after successful issuance to avoid
  skipping renewal attempts on subsequent container restarts.

## [2.4.2] - 2025-11-09
### Fixed
- Provision certbot in the nginx container via Python's package manager so Let's Encrypt
  requests no longer fail with `certbot: not found`.
- Replaced bash-specific `[[ ... ]]` usage in the nginx initialization script with
  POSIX-compatible logic to maintain reliable self-signed fallback handling.
