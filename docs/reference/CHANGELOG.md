# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project currently
tracks releases under the 2.x series.

## [Unreleased]
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

