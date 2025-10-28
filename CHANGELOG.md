# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project currently
tracks releases under the 2.1.x series.

## [Unreleased]
### Added
- Added a `manual_eas_event.py` utility that ingests raw CAP XML (e.g., RWT/RMT tests),
  validates the targeted SAME/FIPS codes, and drives the broadcaster so operators can
  trigger manual transmissions with full auditing.
- Introduced the `EAS_MANUAL_FIPS_CODES` configuration setting to control which
  locations are eligible for manual CAP forwarding.
- Bundled the full national county/parish FIPS registry for manual activations and
  exposed helpers to authorize the entire dataset with a single configuration flag.
- Cataloged the nationwide SAME event code registry together with helper utilities so
  broadcasters and manual tools can resolve official names, presets, and headers.
### Changed
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
### Fixed
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

