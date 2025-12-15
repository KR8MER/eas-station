# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project currently
tracks releases under the 2.x series.

## [Unreleased]

### Fixed
- **Update Script Freezing** - Fixed update.sh hanging at "Updating System Dependencies" step
  - Removed `-qq` flag from apt-get install to show actual progress output (was suppressing all output making it appear frozen)
  - Kept `DEBIAN_FRONTEND=noninteractive` to prevent interactive prompts from package configuration
  - Now shows full apt-get output so users can see installation progress and diagnose any issues
  - Matches install.sh behavior for consistency
  - VERSION bumped to 2.27.21 (bug fix)
- **Alembic Migration Idempotency** - Fixed migrations hanging when tables already exist
  - Added table existence checks to hardware_settings and icecast_settings migrations
  - Migrations now skip table creation if table already exists (idempotent)
  - Prevents "table already exists" errors that cause update.sh to hang
  - Fixes issue where update would stop after "Context impl PostgresqlImpl" message
  - VERSION bumped to 2.27.19 (bug fix)

### Removed
- **Internal Documentation Cleanup** - Removed internal planning and working memory documents (16 total files)
  - **Architecture planning docs**: Deleted REWRITE_PLAN_SUMMARY.md, REWRITE_ARCHITECTURE.md, REWRITE_ROADMAP.md, CODEBASE_INVENTORY.md, CODE_MODERNIZATION_RECOMMENDATIONS.md, APP_PY_REFACTORING_PLAN.md, LIBRARY_REPLACEMENT_AUDIT.md, LIBRARY_REPLACEMENT_IMPLEMENTATION_PLAN.md, SDR_ARCHITECTURE_REFACTORING.md, MIGRATION_GUIDE.md (planning for theoretical rewrite, not current system)
  - **Internal working memory**: Deleted CLAUDE_MEMORY.md, SDR_WORKING_MEMORY.md (AI agent internal context, not user documentation)
  - **Dated status reports**: Deleted CRITICAL_ISSUES_STATUS.md, VALIDATION_REPORT.md, ARCHITECTURE_REVIEW_BUGS.md (issues already fixed or addressed)
  - **Auto-generated stats**: Deleted static/docs/REPO_STATS.md (auto-generated, outdated: 2025-11-29)
  - **Old templates**: Deleted templates/settings/network_old.html (unreferenced old template file)
  - These documents were internal/temporary and not user-facing documentation
  - Active architecture docs remain in docs/architecture/ (SYSTEM_ARCHITECTURE.md, THEORY_OF_OPERATION.md, etc.)
  - VERSION bumped to 2.27.18 (documentation cleanup)

### Changed
- **Documentation Organization** - Cleaned up and reorganized all documentation
  - Moved `docs/TROUBLESHOOTING_504_TIMEOUT.md` to `docs/troubleshooting/` subdirectory
  - Moved `docs/ENV_FILE_MIGRATION.md` to `docs/troubleshooting/`
  - Moved `docs/Installation-Changes.md` and `docs/PostgreSQL-15-Fix.md` to `docs/installation/`
  - Moved `docs/QUICKSTART-BARE-METAL.md` to `docs/installation/`
  - Moved `docs/POLLER_MIGRATION_GUIDE.md` and `docs/SMART_SETUP.md` to `docs/guides/`
  - Moved `docs/FUTURE_ENHANCEMENTS.md` to `docs/roadmap/`
  - Moved `docs/SECURITY_FEATURES.md` to `docs/security/`
  - Updated `docs/INDEX.md` to reference new file locations and added more documentation links
  - Root directory now contains only README.md and essential scripts (install.sh, update.sh, uninstall.sh, diagnose.sh)
  - Documentation root (`docs/`) now contains only INDEX.md and README.md
  - All documentation properly organized into category subdirectories
  - VERSION bumped to 2.27.17 (documentation cleanup)

### Removed
- **Historical Fix Documentation** - Eliminated one-off fix documents from repository (27 total files)
  - **Root directory fixes**: Deleted STARTUP_FIX_SUMMARY.md, DEPLOYMENT_INSTRUCTIONS.md, FIXES_APPLIED.md, WEBSITE_504_FIX.md, FIX_FOR_TIMEOUT_ISSUE.md, DEPLOYED_SYSTEM_FIX.md, QUICK_FIX.md, QUICK_DATABASE_FIX.md, ROOT_CAUSE_ANALYSIS.md, FIX_SUMMARY_OLD.md, ISO_BUILD_READY.md, PATH_AUDIT.md, ISSUE_ANALYSIS.md
  - **Architecture fixes**: Deleted docs/architecture/AUDIO_PLAYER_FIX.md, SDR_FIX_SUMMARY.md, CHANGES_SUMMARY.md, SDR_ANALYSIS_2025-12-08.md, IMPLEMENTATION_COMPLETE.md
  - **Troubleshooting fixes**: Deleted docs/troubleshooting/AIRSPY_CONTAINER_FIX.md, AIRSPY_NO_OPEN_FIX.md, FRONTEND_AIRSPY_ERROR_AFTER_FIX.md, CONTAINERIZATION_FIXES.md, AIRSPY_SERVICE_FILE_NOT_UPDATED.md, ROOT_CAUSE_AIRSPY_BARE_METAL.md, PASSWORD_MISMATCH.md
  - **Security fixes**: Deleted docs/security/SECURITY_SUMMARY.md
  - **Installation fixes**: Deleted docs/installation/CHANGES_SUMMARY.md
  - These documents described specific bugs and fixes that are no longer relevant
  - Current troubleshooting information is maintained in `docs/troubleshooting/` directory

### Fixed
- **S.M.A.R.T. Invalid Argument Error** - Fixed smartctl compatibility issue with `-n standby` flag
  - The `-n standby` flag was being added for all device types except 'nvme' and 'auto'
  - This caused "Invalid argument" errors on USB, SCSI, and other device types that don't support standby mode
  - Changed logic to ONLY add `-n standby` flag for ATA/SATA devices (device types 'ata' or 'sat')
  - S.M.A.R.T. health monitoring now works correctly across all device types
  - VERSION bumped to 2.27.16 (bug fix)
- **Update Script Migration Errors** - Fixed migration errors being hidden by screen clear
  - Added `MIGRATION_FAILED` flag to track when Alembic migrations encounter errors
  - Screen is no longer cleared after failed migrations, keeping error output visible
  - Added pause prompt after migration errors so user can read details before continuing
  - Makes it much easier to diagnose database migration issues during updates
  - VERSION bumped to 2.27.16 (bug fix)
- **Audio Monitor Console Spam** - Removed noisy console.log/console.debug statements
  - Removed VU meter debug logging that spammed console every 5 seconds
  - Removed WebSocket connection status logging
  - Removed stream switching debug messages
  - Removed playback state debug messages
  - Removed broadcast queue statistics logging
  - Console now only shows errors and warnings, not routine operational messages
  - VERSION bumped to 2.27.16 (bug fix)
- **Audio Monitor UI Fixes** - Fixed three display issues on audio monitoring page
  - RBDS metadata now properly displays when available (added null check for source.metrics)
  - S.M.A.R.T. health display no longer shows both "✓ Healthy" and error message simultaneously
  - SDR sources no longer show buffer utilization indicator (added check for 'redis_sdr' source type)
  - VERSION bumped to 2.27.15 (bug fix)
- **Critical Audio Chipmunk Bug** - Fixed severe audio speed issue (2x speed, not 1.09x as previously calculated)
  - Root cause: FM demodulator outputs mono audio but config reported 2 channels (stereo)
  - Streaming code incorrectly treated mono samples as interleaved stereo pairs
  - This caused 48000 mono samples to be interpreted as 24000 stereo samples
  - Browser played 24000 samples at 48kHz rate = 2x speed = severe chipmunk effect
  - Fixed by detecting actual audio shape (1D vs 2D array) instead of trusting config
  - NOTE: FM stereo decoding (L-R separation) not yet implemented; only pilot detection works
  - VERSION bumped to 2.27.14 (critical bug fix)
- **S.M.A.R.T. "Invalid command line arguments"** - Fixed smartctl compatibility issue with older versions
  - Changed `--json=o` flag to `--json` for broader smartctl version support
  - The `=o` option was added in smartctl 7.2+ and caused "Invalid command line arguments" error on older systems
  - S.M.A.R.T. disk health monitoring now works on systems with smartctl < 7.2
  - VERSION bumped to 2.27.13 (bug fix)
- **Web Player Stability** - Improved audio streaming stability for continuous playback
  - Added `Accept-Ranges: none` header to prevent browser seeking in live streams
  - Added `Connection: keep-alive` header to maintain streaming connection
  - These headers prevent browsers from closing streams after buffering attempts
  - VERSION bumped to 2.27.13 (bug fix)

### Added
- **FM Stereo Pilot & RBDS Display** - Added real-time FM broadcast metadata to audio monitor
  - Shows stereo pilot tone lock status and signal strength (19 kHz pilot detection)
  - Displays stereo/mono audio mode indicator
  - Shows RBDS (Radio Broadcast Data System) station name, radio text, and program type
  - Displays PI (Program Identification) code and traffic program/alert flags
  - Shows music/speech content type flag
  - Backend already collected this data; now visible in UI
  - VERSION bumped to 2.27.13 (feature)

### Changed
- **SDR Service Architecture Simplification** - SDR service now uses separate venv with system site-packages
  - Created `venv-sdr` with `--system-site-packages` flag for direct python3-soapysdr access
  - This eliminates complex PYTHONPATH hacks that were fragile across Python versions
  - Main web service venv remains isolated to avoid gunicorn/gevent conflicts
  - SDR service uses `requirements-sdr.txt` (minimal: redis, python-dotenv)
  - install.sh and update.sh automatically create/update venv-sdr
  - Removed ~80 lines of PYTHONPATH detection code from install.sh and update.sh
  - VERSION bumped to 2.27.12

### Fixed
- **SDR Airspy "No Match" Error** - Fixed SoapySDR device opening failures for Airspy devices
  - Fixed Airspy driver rejecting `label` parameter (not supported by Airspy SoapySDR module)
  - Increased retry attempts from 3 to 5 for "no match" errors
  - Added Python 3.13 compatibility detection and error messages
  - Improved install script verification of python3-soapysdr package
  - Enhanced error messages with package installation instructions
  - VERSION bumped to 2.27.11 (bug fix)
- **Update Script Missing Dynamic Path Detection** - Fixed update.sh not applying dynamic PYTHONPATH and SOAPY_SDR_PLUGIN_PATH
  - Update script now detects Python site-packages paths (supports Python 3.10-3.13+)
  - Update script now detects SoapySDR plugin directories
  - Updates systemd service files with correct paths for current Python version
  - Previously update.sh only copied static files, leaving old hardcoded paths
  - Users must run `sudo ./update.sh` to apply the fix (not just `git pull`)
  - This is why Airspy worked after `apt install airspy` but still failed in the service
  - VERSION bumped to 2.27.10 (bug fix)
- **Airspy SDR Not Opening** - Fixed "Unable to open AirSpy device" error even with root/sudo access
  - Added `airspy` package to installation (contains firmware and host utilities like airspy_info)
  - Previously only installed `libairspy0` (library) and `soapysdr-module-airspy` (SoapySDR plugin)
  - The `airspy` package provides critical firmware loading and device initialization
  - Without it, SoapySDR cannot open the device even with correct permissions
  - Fixes error: "SoapySDR::Device::make() no match" for Airspy devices
  - VERSION bumped to 2.27.9 (bug fix)
- **SDR Not Working on Bare Metal** - Fixed SoapySDR device detection failure on bare metal installations
  - Install script now dynamically detects Python site-packages paths for all Python versions
  - Install script now dynamically detects SoapySDR plugin module paths
  - Updated systemd service to inject detected paths instead of using hardcoded paths
  - Fixes "SoapySDR::Device::make() no match" errors caused by incorrect PYTHONPATH
  - Fixes missing SoapySDR modules caused by incorrect SOAPY_SDR_PLUGIN_PATH
  - SDR worked in Docker but failed on bare metal due to venv isolation from system packages
  - Python venv doesn't use --system-site-packages to avoid conflicts with gunicorn/gevent
  - SDR service now gets correct paths to apt-installed python3-soapysdr and soapysdr-module-airspy
  - VERSION bumped to 2.27.8 (bug fix)
- **SDR Service Audio Errors** - Suppressed ALSA/PulseAudio/Jack errors in SDR hardware service logs
  - Added `PULSE_SERVER=/dev/null` to prevent PulseAudio connection attempts
  - Added `SOAPY_SDR_LOG_LEVEL=WARNING` to reduce SoapySDR log noise
  - Enhanced `ALSA_CONFIG_PATH=/dev/null` documentation explaining why audio errors appear
  - These errors are caused by soapysdr-module-audio probing for audio devices during SDR enumeration
  - The errors don't affect SDR functionality (USB radio devices work correctly)
  - To completely eliminate errors, uninstall soapysdr-module-audio if not needed for audio streaming
  - VERSION bumped to 2.27.7 (bug fix)
- **EASMonitor Backwards Compatibility** - Fixed TypeError when old code calls EASMonitor with deprecated parameters
  - Added backwards compatibility for `audio_manager` parameter (now accepts both `audio_manager` and `audio_source`)
  - Added backwards compatibility for `save_audio_files` parameter (accepted but ignored)
  - Exported `ContinuousEASMonitor` as an alias for `EASMonitor` for test compatibility
  - Prevents "TypeError: EASMonitor.__init__() got an unexpected keyword argument 'audio_manager'" errors
  - Allows deployed systems with cached Python bytecode to continue functioning during upgrades
  - VERSION bumped to 2.27.6 (bug fix)
- **Critical: Fixed Gunicorn Bypassing Database Initialization** - Changed systemd service to use `wsgi:application` instead of `app:app`
  - Previously, gunicorn was loading app.py directly, bypassing all wsgi.py initialization code
  - This caused lazy database initialization on first request, resulting in 504 Gateway Timeout errors
  - Now uses wsgi.py as entry point, which eagerly initializes database before accepting requests
  - Database initialization completes during worker startup, not during first HTTP request
  - Eliminates race conditions where multiple workers try to initialize database simultaneously
  - Web service now starts reliably without timeouts
  - VERSION bumped to 2.27.5 (critical bug fix)
- **WSGI Startup Honors Setup Mode** - Fixed wsgi.py to respect setup mode when database is unavailable
  - wsgi.py now checks if application is in setup mode before attempting database initialization
  - Prevents attempting to initialize database when connectivity check already failed during app.py import
  - Allows proper first-time setup workflow through /setup web UI
  - Eliminates unnecessary duplicate database connection attempts and error messages
  - VERSION bumped to 2.27.4 (bug fix)
- **Web Service 504 Timeout** - Fixed lazy database initialization causing 504 Gateway Timeout errors
  - Database initialization moved from first-request to worker startup in wsgi.py
  - Added eager database initialization when Gunicorn workers start
  - Added TimeoutStartSec=90 to systemd service to allow initialization time
  - Prevents health checks from timing out waiting for database schema creation
  - Fixes "Main process exited, code=killed, status=9/KILL" systemd errors
  - **Enhanced error visibility**: Clear error messages with troubleshooting steps
    - Unbuffered stderr output for immediate visibility in journalctl
    - Detailed error messages showing worker PID and specific failure reason
    - Error log written to /tmp/eas-station-web-startup-error.log for persistence
    - Helpful troubleshooting commands included in error output
  - VERSION bumped to 2.27.3 (bug fix)
- **Installation Script Error Handling** - Added proper error checking for Python virtual environment creation
  - Virtual environment creation now fails fast with clear error messages instead of silently continuing
  - pip install commands now check for success and display detailed error logs on failure
  - Prevents confusing errors later in installation when venv creation fails
  - Logs saved to /tmp for debugging (venv-creation.log, pip-upgrade.log, pip-install.log)
  - VERSION bumped to 2.27.2 (bug fix)
- **Web Service Startup Timeout** - Fixed Gunicorn workers blocking during database initialization
  - Removed import-time database initialization that caused workers to timeout
  - Database initialization now happens lazily on first request via before_request hook
  - Uses thread-safe double-checked locking to ensure initialization happens exactly once
  - Prevents 504 Gateway Timeout errors during service startup
  - VERSION bumped to 2.27.2 (bug fix)

### Improved
- **Startup Logging** - Enhanced diagnostic logging to help identify blocking issues during application startup
  - Added startup banner showing process ID
  - Added checkpoint logs at key initialization steps (✓ for success, ⊘ for skipped, ✗ for errors)
  - Added module import completion log to confirm app.py loads successfully
  - Helps diagnose silent failures that block Gunicorn workers
  - Makes it clear in logs where startup process is hanging
- **Web Service Startup Issue** - Fixed systemd service configuration preventing web app from fully starting
  - Changed `Type=notify` to `Type=simple` in `systemd/eas-station-web.service`
  - Gunicorn with gevent workers doesn't support systemd notify protocol
  - Service now starts correctly and systemd recognizes when it's ready
  - VERSION bumped to 2.27.1 (bug fix)

### Added
- **M-Protocol Phases 1-5: Complete Alpha LED Sign Control** - Deep integration with Alpha LED signs via M-Protocol
  - **Phase 1: Sign Diagnostics** - Read serial number, model, firmware, memory, temperature (Type F commands)
  - **Phase 2: Time/Date Control** - Set time, date, format, run mode, sync with system (Type E commands)
  - **Phase 3: Speaker/Beep Control** - Enable/disable speaker, beep for alerts (Type E commands)
  - **Phase 4: Brightness Control** - Set 0-100% brightness or auto mode (Type E commands)
  - **Phase 5: File Management** - Read text from file labels 0-9, A-Z (Type B commands)
  - All functions implemented in `scripts/led_sign_controller.py`
  - Comprehensive test scripts for each phase
  - Complete documentation for all phases
  - VERSION bumped to 2.27.0 (feature additions)
  - **Result**: Full programmatic control of Alpha LED signs over network
  - **Note**: Web UI integration into existing `/led-control` page pending
- **M-Protocol Phases 3-5: Complete Advanced Control** - Final implementation of speaker, brightness, and file management
  - **Phase 3: Speaker/Beep Control**
    - Added `set_speaker()` method to enable/disable speaker (Type E, Function 0x23)
    - Added `beep()` convenience method to make sign beep for alerts
    - Audio alerts for emergencies and notifications
  - **Phase 4: Brightness Control**
    - Added `set_brightness()` method to set brightness 0-100% or auto mode (Type E, Function 0x30)
    - Manual brightness control with percentage levels
    - Auto brightness mode for ambient light adaptation
    - Night mode and energy saving capabilities
  - **Phase 5: File Management**
    - Added `read_text_file()` method to read text from file labels (Type B, Function 0x42)
    - Query current display content
    - Read user-defined text files (0-9, A-Z)
  - Added `ReadTextCommand` enum for M-Protocol Type B function codes
  - Extended `WriteSpecialExtCommand` enum with speaker and brightness functions
  - Created comprehensive test script `scripts/test_alpha_advanced.py` for all advanced features
  - Added complete documentation in `docs/hardware/ALPHA_ADVANCED_PHASES3-5.md`
  - Integration examples for emergency alerts, auto-dimming, and business hours automation
  - M-Protocol implementation now production-ready with full sign control
  - VERSION bumped to 2.26.0 (feature addition)
- **M-Protocol Phase 2: Time/Date Control** - Complete time and date management for Alpha LED signs
  - Added `set_time_and_date()` method to set sign time and date (Type E, Function 0x20)
  - Added `set_day_of_week()` method to set day of week 0-6 (Type E, Function 0x22)
  - Added `set_time_format()` method to set 12h/24h time format (Type E, Function 0x27)
  - Added `set_run_mode()` method to set auto/manual operation mode (Type E, Function 0x2E)
  - Added `sync_time_with_system()` convenience method to sync sign with EAS Station time
  - Added `WriteSpecialExtCommand` enum for M-Protocol Type E function codes
  - All functions use bidirectional communication with ACK/NAK handling
  - Created test script `scripts/test_alpha_timedate.py` for testing time control
  - Added complete documentation in `docs/hardware/ALPHA_TIMEDATE_PHASE2.md`
  - VERSION bumped to 2.25.0 (feature addition)
- **M-Protocol Phase 1: Sign Diagnostics** - Alpha LED signs can now be queried for status and configuration
  - Added `read_serial_number()` method to read sign serial number (Type F, Function 0x24)
  - Added `read_model_number()` method to read sign model (Type F, Function 0x25)
  - Added `read_firmware_version()` method to read firmware version (Type F, Function 0x26)
  - Added `read_memory_configuration()` method to query memory usage (Type F, Function 0x30)
  - Added `read_temperature()` method to read internal temperature (Type F, Function 0x35)
  - Added `get_diagnostics()` method to fetch all diagnostic information at once
  - Added `_send_read_command()` generic handler for Type F read commands
  - Added `ReadSpecialExtCommand` enum for M-Protocol Type F function codes
  - Full bidirectional communication support verified and documented
  - VERSION bumped to 2.24.0 (feature addition)

### Fixed
- **Systemd Target Cycling Issue** - Fixed eas-station.target repeatedly stopping and starting
  - Changed `Requires=` to `Wants=` for postgresql, redis, nginx dependencies in eas-station.target
  - Hard `Requires=` dependencies were causing cascading restarts whenever PostgreSQL, Redis, or Nginx restarted
  - Added `PartOf=eas-station.target` to all EAS service files (web, sdr, audio, eas, hardware, poller)
  - Added `WantedBy=eas-station.target` to all EAS service files for proper target membership
  - Services now properly belong to the target and won't cause unnecessary restart cycles
  - Soft `Wants=` dependencies allow services to start even if dependencies are temporarily unavailable
  - VERSION bumped to 2.23.7 (bug fix)
- **CRITICAL: PostgreSQL username is eas_station (underscore) not eas-station (hyphen)** - Fixed all references to use correct username
  - Changed DATABASE_URL from `eas-station` to `eas_station` in .env.example, install.sh, webapp/admin/environment.py
  - Updated install.sh to create PostgreSQL user `eas_station` instead of `"eas-station"`
  - Updated pg_hba.conf rules to use `eas_station` instead of `"eas-station"`
  - Updated all GRANT statements to use `eas_station`
  - User confirmed: `psql -U eas_station` works, `psql -U eas-station` fails
  - VERSION bumped to 2.23.6 (bug fix)
- **ACTUAL ROOT CAUSE: Poller .env override mismatch** - Fixed poller failing to load DATABASE_URL from .env file
  - Changed `load_dotenv(override=False)` to `load_dotenv(override=True)` in poller/cap_poller.py (lines 131, 138)
  - Poller was using override=False while app.py uses override=True, causing environment variable mismatch
  - When poller imports from app.py, app.py's override=True happened AFTER poller's override=False
  - This caused poller to use wrong/missing DATABASE_URL even though .env file was correct
  - Other services work because they don't import app.py and use override=True directly
  - VERSION bumped to 2.23.5 (bug fix)
- **Auto-fix Password Authentication in update.sh** - update.sh now automatically syncs PostgreSQL password before running migrations
  - Added password sync step in update.sh before database migrations (line 617)
  - Runs `scripts/database/fix_database_user.sh` automatically to sync password from .env to PostgreSQL
  - Prevents "password authentication failed" errors during migrations
  - Made fix_database_user.sh completely non-interactive (removed confirmation prompt)
  - Created fix_and_restart.sh for one-command fix with service restart
  - VERSION bumped to 2.23.4 (bug fix)
- **Password Authentication Root Cause Identified** - Clarified that "password authentication failed" is a password mismatch, not network/IPv6 issue
  - Updated documentation to explain that `OperationalError` means PostgreSQL rejected the password after connection succeeded
  - Changed DATABASE_URL defaults from `localhost` to `127.0.0.1` to force IPv4 and improve consistency
  - Updated `.env.example`, `install.sh`, `webapp/admin/environment.py`, and `scripts/profile_poller.py`
  - Added `docs/troubleshooting/PASSWORD_MISMATCH.md` with detailed root cause analysis
  - Updated `QUICK_DATABASE_FIX.md` to emphasize running fix script to sync passwords
  - The fix script (`scripts/database/fix_database_user.sh`) extracts password from .env and updates PostgreSQL
  - IPv6 (::1) connections work fine - the real issue is password mismatch between .env and PostgreSQL
  - VERSION bumped to 2.23.3 (bug fix)
- **Database Authentication Issues** - Fixed database connection failures during migrations and poller service startup
  - Changed poller service `EnvironmentFile` from optional (`-/opt/eas-station/.env`) to required (`/opt/eas-station/.env`)
  - Ensures DATABASE_URL is always loaded from environment file, preventing fallback to incorrect database usernames
  - Added `scripts/database/fix_database_user.sh` to clean up incorrectly named database users (e.g., "eas_station" vs "eas-station")
  - Script automatically reassigns ownership and drops incorrect users while preserving data
  - Resolves "password authentication failed for user eas_station" errors in screen_manager and migrations
  - VERSION bumped to 2.23.2 (bug fix)
- **CAP Poller Service ModuleNotFoundError** - Fixed "No module named 'redis'" error on bare metal installations
  - Updated `systemd/eas-station-poller.service` to use virtual environment Python interpreter
  - Changed `ExecStart` from `/usr/bin/python3` to `/opt/eas-station/venv/bin/python`
  - Added `PATH=/opt/eas-station/venv/bin:...` environment variable
  - Added `PYTHONPATH=/opt/eas-station` environment variable
  - Aligns poller service with other services (web, audio, eas, sdr, hardware)
  - Resolves issue where system Python lacked required dependencies (redis, pytz, etc.)
  - VERSION bumped to 2.23.1 (bug fix)

### Changed
- **CAP Poller Refactored** - Removed non-polling responsibilities from CAP poller service
  - Removed direct EAS broadcasting (now handled by eas-service via Redis)
  - Removed direct LED sign control (now handled by dedicated service via Redis)
  - Removed direct radio/SDR capture coordination (now handled by sdr-service via Redis)
  - Added Redis event publishing for alert events (`alerts:new`, `alerts:led:*`, `alerts:broadcast_only`)
  - Removed command-line arguments: `--led-ip`, `--led-port`, `--radio-captures`
  - Removed `__init__` parameters: `led_sign_ip`, `led_sign_port`, `enable_radio_captures`
  - Removed imports: `EASBroadcaster`, `load_eas_config`, `RadioManager`, `LEDSignController`
  - Removed methods: `_setup_radio_manager()`, `_refresh_radio_configuration()`, `_coordinate_radio_captures()`, `_record_receiver_statuses()`, `update_led_display()`
  - Poller now focuses solely on: polling feeds, parsing responses, checking location matches, saving to database, and publishing events
  - VERSION bumped to 2.23.0 (architecture refactoring)

### Fixed
- **Certificate Status API Fetch Error** - Fixed "Unexpected token '<'" error in Security Settings page
  - Added `Accept: application/json` header to `/security/ssl-certificate` fetch() call (line 705 in security_settings.html)
  - Prevents HTML redirect response when authentication fails, ensuring proper JSON error handling
  - Resolves TypeError when backend returns HTML instead of expected JSON
- **Missing radio_captures Directory** - Fixed systemd namespace mounting error for eas-station-poller service
  - Added creation of `/opt/eas-station/radio_captures` directory in install.sh
  - Directory is required by `ReadWritePaths` in systemd/eas-station-poller.service (line 30)
  - Prevents "Failed to set up mount namespacing" errors on fresh installations
- **Database Migration Documentation** - Added clarifying comments to update.sh database migration
  - Documented that migrations use DATABASE_URL from .env file (not hardcoded postgres username)
  - Clarified that `from app import app, db` loads credentials from environment via os.getenv()
  - Ensures understanding that correct database user (e.g., eas_station) is used automatically
- VERSION bumped to 2.22.1 (bug fixes)

### Added
- **SSL Certificate Status UI** - Added comprehensive certificate viewer to Security Settings page
  - Shows certificate type (Let's Encrypt, Self-Signed, or None)
  - Displays validity status with color-coded badges (Valid, Expiring Soon, Expired)
  - Shows domain, issuer, valid from/until dates, and days remaining
  - Displays certbot automatic renewal timer status and next check time
  - Provides warnings for expiring (≤30 days) or expired certificates
  - Includes helpful guidance for self-signed certificates and renewal procedures
  - Auto-refreshes on page load with manual refresh button
  - Added API endpoint `/security/ssl-certificate` to retrieve certificate data
  - Created `app_core/ssl_utils.py` with certificate parsing utilities
  - Added "Security Settings" link to user dropdown menu for easy access
- VERSION bumped to 2.22.0 (new feature)

### Fixed
- **Certbot systemd service missing** - Added certbot.service and certbot.timer to systemd directory
  - Install script was trying to enable certbot.timer but the systemd files didn't exist
  - Created proper systemd service for certificate renewal with nginx reload hook
  - Timer runs twice daily (00:00 and 12:00) with randomized delay for load distribution
  - Both install.sh and update.sh now copy .timer files to /etc/systemd/system/
  - Fixes silent failure of automatic certificate renewal on deployed systems
- VERSION bumped to 2.21.11
- **Poller service user credentials** - Fixed incorrect username in `systemd/eas-station-poller.service`
  - Changed `User=easstation` to `User=eas-station` (missing dash)
  - Changed `Group=easstation` to `Group=eas-station` (missing dash)
  - Service was failing with exit code 217/USER: "Failed to determine user credentials: No such process"
  - All other services correctly use `eas-station` user/group created by install script
- **Hardware service supplementary groups** - Fixed install script and update script to create missing system groups
  - Both `install.sh` and `update.sh` now create gpio, i2c, spi, audio, plugdev, dialout groups if they don't exist
  - Hardware service was failing with exit code 216/GROUP: "Failed to determine supplementary groups: No such process"
  - Ensures turnkey installation works on all systems without pre-existing hardware groups
  - Running `update.sh` will automatically fix this issue on deployed systems
  - Critical for hardware-based features (GPIO, I2C, SPI devices, USB serial, audio)
- VERSION bumped to 2.21.10
- **EAS service crash** - Fixed `TypeError: create_fips_filtering_callback() got an unexpected keyword argument 'flask_app'`
  - Updated `eas_service.py` to use correct callback pattern with `forward_callback` parameter
  - Added proper alert forwarding handler using `forward_alert_to_api` from `app_core.audio.alert_forwarding`
  - Pattern now matches working implementation in `eas_monitoring_service.py`
- **Log message truncation** - Added `--all` flag to journalctl command to prevent message truncation
  - Service logs (systemd) now show full message content instead of truncated ellipsis (...)
  - Enhanced CSS for `.log-message` to properly wrap long messages with `word-break`, `white-space`, and `overflow-wrap`
  - Improved copy function to explicitly get text from `.log-message` span for more reliable copying
- **Poller service not starting** - Fixed systemd target to reference unified poller service
  - Updated `systemd/eas-station.target` to use `eas-station-poller.service` instead of obsolete `eas-station-noaa-poller.service` and `eas-station-ipaws-poller.service`
  - The unified poller (introduced in 2.20.0) was not being started because the target file referenced the old split poller services
  - This caused alert polling to fail silently on fresh installs and updates
- VERSION bumped to 2.21.9

### Changed
- **.env.example minimized** - Removed all comments and obsolete variables
  - Reduced from 373 lines to 36 lines
  - Kept only essential variables needed for operation
  - No explanatory comments - configuration is managed via web UI
- **ALL database connections use DATABASE_URL** - Removed POSTGRES_* variables completely
  - Format: `DATABASE_URL=postgresql+psycopg2://username:password@host:port/database`  
  - Updated ALL service files: app.py, fastapi_app.py, poller/cap_poller.py, hardware_service.py, sdr_hardware_service.py, eas_service.py, eas_monitoring_service.py
  - Updated utility scripts: run_eas_broadcaster.py, run_radio_manager.py
  - install.sh now writes DATABASE_URL instead of individual POSTGRES_* variables
- VERSION bumped to 2.21.7

### Fixed
- **Systemd logs permission error** - Added missing `os` import in `webapp/routes_logs.py`
- **Install script systemd-journal group** - Automatically adds service user to `systemd-journal` group

### Removed
- POSTGRES_USER, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_PASSWORD variables (replaced by DATABASE_URL)
- All verbose comments from .env.example (373 lines → 36 lines)
- Obsolete environment variables no longer used by the application

## [2.21.0] - 2025-12-12

### Changed
- **Environment variable consolidation** - Reduced from 93 to 73 variables by consolidating related settings
  - `MAIL_URL` replaces 5 mail variables (MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_USE_TLS)
  - `LOCATION_CONFIG` (JSON) replaces 9 location variables (DEFAULT_TIMEZONE, DEFAULT_COUNTY_NAME, DEFAULT_STATE_CODE, DEFAULT_ZONE_CODES, DEFAULT_FIPS_CODES, DEFAULT_STORAGE_ZONE_CODES, DEFAULT_MAP_CENTER_LAT, DEFAULT_MAP_CENTER_LNG, DEFAULT_MAP_ZOOM)
  - `ICECAST_CONFIG` (JSON) replaces 5 Icecast auth variables (ICECAST_SOURCE_PASSWORD, ICECAST_RELAY_PASSWORD, ICECAST_ADMIN_USER, ICECAST_ADMIN_PASSWORD, ICECAST_ADMIN)
  - `ICECAST_INTERNAL_URL` and `ICECAST_PUBLIC_URL` replace 4 connection variables (ICECAST_SERVER, ICECAST_PORT, ICECAST_EXTERNAL_PORT, ICECAST_PUBLIC_HOSTNAME)
  - `AZURE_OPENAI_CONFIG` (JSON) replaces 5 Azure OpenAI variables (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_MODEL, AZURE_OPENAI_VOICE, AZURE_OPENAI_SPEED)
- VERSION bumped to 2.21.0

### Fixed
- Copy button label on logs page changed from "Copy Logs" to "Copy" for clarity
- CSV export button relabeled to "Excel" to match user terminology  
- CSV export icon changed from `fa-file-csv` to `fa-file-excel`
- Update script (`update.sh`) now properly displays VERSION file contents instead of showing "unknown"
- Update script now prioritizes VERSION file over git commit hash for version display
- Updated POLLER_CONFIG_MIGRATION.md to clarify unified poller architecture
- Removed outdated references to separate `ipaws.env` and `noaa.env` files (no longer used in 2.20+)
- Added troubleshooting section for "IPAWS.env not found" error

### Changed
- VERSION bumped to 2.20.2

## [2.20.1] - 2025-12-11
### Changed
  - **Enhanced PyCharm integration documentation** - Added comprehensive field-by-field setup instructions in `docs/guides/PYCHARM_DEBUGGING.md`
  - Added detailed tables for every configuration dialog with all fields explained
  - Added example values for each field with explanations
  - Added step-by-step Database Tools (DataGrip) configuration
  - Added step-by-step Debug Configuration setup for AI coding assistants
  - Added validation checklist for complete PyCharm setup
  - Added "Quick Start" section with essential settings table for rapid configuration
  - **Added comprehensive GitHub Copilot integration section** - Detailed comparison with zencoder.ai
  - Added GitHub Copilot setup instructions for PyCharm and VS Code
  - Added capability comparison table (Copilot vs zencoder.ai)
  - Added workflow examples showing how to use GitHub Copilot Chat effectively
  - Added recommendations for when to use each AI assistant
  - Updated document title to cover all AI coding assistants, not just zencoder.ai
  - **Added Wing IDE integration section** - Complete setup guide for Wing Professional Python IDE
  - Added Wing IDE to Quick Start settings table with remote host configuration
  - Added Wing IDE as Option C in IDE selection with pros/cons
  - Added Wing IDE remote development capabilities and AI assistant support
  - Added comprehensive zencoder.ai integration section with API setup and testing steps
  - Added scenario-based examples showing zencoder.ai workflow (bug fixing, features, optimization)
  - Added verification tests for each capability (files, Python, database, services, logs)
  - Improved clarity on which fields are required vs optional
  - Added troubleshooting references for each configuration step

## [2.20.0] - 2025-12-11
### Added
  - **Complete whiptail-based setup** - All installation inputs now use professional TUI interface
  - **FIPS code checklist interface** - Select multiple counties at once instead of typing
  - **Radio button menus** - EAS Originator code selection with predefined options (WXR, EAS, PEP, etc.)
  - **Consistent branding** - Copyright and license info on all whiptail dialogs throughout install.sh
  - **FIPS management in eas-config** - Configure FIPS codes post-installation with same checklist UI
  - Branding footer function for consistent copyright/license display
  - Improved Python environment detection for FIPS lookup during installation

### Changed
  - **FIPS lookup workflow** - Now shows full county list with checkboxes instead of search-based approach
  - EAS Originator input changed from text entry to radio button selection for better validation
  - All whiptail dialogs now include branding footer with copyright and license information
  - Improved error messaging when Python environment isn't available during installation
  - Enhanced user experience with clearer instructions and better dialog sizing

### Fixed
  - FIPS lookup now gracefully handles case where Python dependencies aren't installed yet
  - Better validation for all user inputs with helpful error messages
  - Consistent dialog widths and heights for better readability

## [2.19.12] - 2025-12-11
### Fixed
  - Fixed logs page to display ALL logs instead of only categorized logs
  - Fixed Bootstrap modal aria-hidden accessibility warnings when adding/editing audio sources
  - Fixed potential focus trap issues preventing interaction with audio source modals
  - Fixed missing firewall rules for Icecast streaming (port 8000)

### Added
  - Added "All Logs" tab as the default view with organized category sections
  - Added collapsible accordion sections for each log category (System, Polling, Audio, GPIO, EAS Messages, etc.)
  - Added category badges showing log count per category
  - Logs now organized by category instead of mixed together chronologically
  - Added automatic firewall configuration for Icecast port 8000 during installation
  - Added firewall configuration summary in installation completion message
  - Added instructions for optionally opening PostgreSQL port with security warnings

### Changed
  - Default logs view changed from "System" to "All Logs" for better visibility
  - "All Logs" view now uses accordion with category grouping for better organization
  - Modal elements now properly blur focus before hiding to prevent accessibility issues
  - Improved log readability by separating logs into logical categories
  - Installation now automatically opens port 8000 for Icecast if enabled
  - Firewall status display now shows configured ports

## [2.19.11] - 2025-12-10
### Fixed
  - Fixed pgAdmin 4 installation failures by adding better error handling and --allow-downgrades flag
  - Fixed pgAdmin installation to gracefully skip if it fails, allowing installation to continue
  - Added error detection and informative messages for pgAdmin installation issues

### Added
  - **PostgreSQL password now displayed during installation** for easy IDE/pgAdmin access
  - Added comprehensive database credentials section in installation completion message
  - Shows full PostgreSQL connection details (host, port, database, username, password)
  - Added instructions for viewing password later: `sudo grep POSTGRES_PASSWORD /opt/eas-station/.env`
  - Enhanced installation progress messages with detailed package lists
  - Added informative descriptions of what each installation step does
  - More aesthetic progress indicators showing estimated time and package counts
  - pgAdmin access instructions (if successfully installed) in completion message
  - Separate database credentials section with security warnings

### Changed
  - Installation completion message now includes full database credentials for IDE access
  - Made install.sh significantly more informative and user-friendly
  - Enhanced progress messages to show what packages are being installed
  - Improved visual hierarchy in completion message sections
  - pgAdmin configuration skips gracefully if installation failed
  - Database password warning emphasizes saving credentials (only shown once)

## [2.19.10] - 2025-12-10
### Fixed
  - Removed Docker/container monitoring from system health in favor of systemd service monitoring
  - System health now queries systemd services directly using systemctl for accurate bare metal deployment status
  - Updated system health template to display systemd services instead of Docker containers
  
### Added
  - Systemd service monitoring for all EAS Station services (web, sdr, audio, eas, hardware, noaa-poller, ipaws-poller)
  - Dependency service monitoring (nginx, postgresql, redis-server, icecast2)
  - Service status categorization (active, inactive, failed) with visual indicators
  - Separate display sections for EAS Station services vs. system dependencies

### Changed
  - Replaced _collect_container_statuses() with _collect_systemd_services() in system.py
  - System health data structure now uses "systemd" key instead of "containers"
  - Service monitoring now uses native systemctl commands instead of Docker API
  - Health dashboard shows systemd service status with active/inactive/failed states

## [2.19.9] - 2025-12-10
### Fixed
  - Reduced excessive whitespace between navbar and page content by decreasing --layout-padding-top from 1.5rem to 0.5rem
  - Fixed NOAA_USER_AGENT validation error by adding default value in environment.py configuration
  - Fixed environment validation to check default values before reporting "required but not set" errors
  - Updated setup wizard configuration persistence notice to remove Docker/container-specific references
  - Changed setup wizard text to reflect bare metal deployment with /app-config/.env persistent volume
  - Removed Docker-specific terminology from about.html (changed "containers" to "services")
  - Removed Docker-specific terminology from admin.html (container references, --network=host flag)
  - Updated admin panel text to be deployment-agnostic (removed "inside the app container" references)
  - Removed hardcoded version number from NOAA_USER_AGENT default value to prevent version drift
  - Changed "System Reinstall" to "Fresh Installation" in setup wizard for clarity

### Changed
  - Updated setup wizard to show accurate configuration persistence behavior for bare metal deployments
  - Environment validation now respects default values defined in ENV_CATEGORIES when checking required fields
  - About page now uses deployment-agnostic terminology for service architecture
  - Admin panel now uses terminology appropriate for both Docker and bare metal deployments
  - NOAA_USER_AGENT default value no longer includes version number (simplified to "EAS Station")

## [2.19.8] - 2025-12-10
### Changed
  - Completely rewrote PyCharm/VS Code debugging guide for bare metal deployment
  - Removed all Docker/container references, replaced with systemd service instructions
  - Updated all file paths from /home/pi/eas-station to /opt/eas-station
  - Added comprehensive section on debugging individual systemd services with debugpy
  - Added detailed instructions for using AI coding agents (ZenCoder) with real-time code access
  - Updated database configuration section for bare metal PostgreSQL (not containerized)
  - Added multiple methods for enabling debugpy: temporary, persistent, and code modification
  - Documented debug port assignments for all services (5678-5684)
  - Added SSH port forwarding instructions for secure remote debugging
  - Updated troubleshooting section with systemd-specific solutions
  - Enhanced development workflow with systemd service management commands
  - Added section on testing with real hardware (GPIO, SDR, audio devices)
  - Updated quick reference with systemd commands instead of Docker commands
  - Improved summary to highlight AI agent integration and bare metal advantages
### Security
  - Added security warnings for exposing debugpy ports on all network interfaces
  - Documented SSH port forwarding as secure alternative to opening firewall ports
  - Improved PostgreSQL remote access documentation with security best practices
  - Restricted sudoers examples to specific services and journalctl units only
  - Clarified user permissions for AI agent integration with minimal necessary access

## [2.19.7] - 2025-12-10
### Fixed
  - Fixed pgAdmin4 installation to prevent apache2 from being installed as a dependency
  - Added python3-typer package installation to resolve "ModuleNotFoundError: No module named 'typer'" in pgAdmin setup
  - Added apt preferences to block apache2 packages during pgadmin4 installation
  - Added automatic apache2 masking and removal if already installed
  - Fixed remote access by configuring UFW firewall to allow ports 80 (HTTP) and 443 (HTTPS)
  - Added firewall configuration section in install.sh with proper UFW setup
  - Improved installation reliability with better dependency management

## [2.19.6] - 2025-12-10
### Changed
  - Enhanced install.sh with improved visual design and user experience
  - Added colorful banner, progress indicators, and step counters
  - Enhanced completion message with detailed component access instructions
  - Added comprehensive post-installation checklist with actionable items
  - Improved readability with emoji icons, better spacing, and color-coded sections
  - Added detailed connection instructions for all components (web UI, pgAdmin, PostgreSQL, Redis)
  - Included useful commands for backup, restore, SSL setup, and troubleshooting
  - Suppressed verbose output from package installations for cleaner display

## [2.19.5] - 2025-12-10
### Fixed
  - Fixed PostgreSQL authentication configuration in `install.sh` to allow password-based connections
  - Added `pg_hba.conf` configuration to enable `scram-sha-256` authentication for `eas_station` user
  - Updated `scripts/database/fix_database_permissions.sh` to also configure PostgreSQL authentication
  - Resolves "password authentication failed for user eas_station" errors during installation

## [2.19.4] - 2025-12-10
### Changed
  - Updated architecture documentation to reflect bare-metal systemd deployment
  - Replaced "container" terminology with "service" or "process" in architecture docs
  - Replaced "Docker" references with "systemd service" or "bare-metal" as appropriate
  - Updated mermaid chart labels in `SYSTEM_ARCHITECTURE.md` from container to service
  - Updated `HARDWARE_ISOLATION.md` with systemd service terminology and journalctl commands
  - Updated `DATA_FLOW_SEQUENCES.md` to reflect systemd service architecture
  - Aligned all documentation with ISO_BUILD_READY.md bare-metal migration status

## [2.19.3] - 2025-12-10
### Removed
  - Removed `bugs/` directory (7.7MB) - Development-only bug tracking screenshots
  - Removed `bare-metal/` directory (164KB) - Redundant transition documentation already in `docs/`
  - Removed screenshots and logos from `samples/` (1.7MB saved) - Keep only EAS test audio files
  - Moved one-off bug reproduction tests to `tests/bug_reproductions/` (excluded from ISO):
    - `test_smoking_gun_proof.py` - OLED scrolling bug verification
    - `test_nvme_samsung_990_pro.py` - NVMe performance testing
    - `test_snow_emergency_public_access.py` - Snow emergency alert bug
    - `test_oled_scroll_optimization.py` - OLED optimization tests
    - `test_oled_render_bounds.py` - OLED boundary tests

### Added
  - Added `samples/README.md` documenting EAS test audio files and their purpose
  - Added comprehensive `legacy/README.md` explaining Docker-era scripts and their bare-metal replacements
  - Added `tests/bug_reproductions/README.md` explaining one-off test files

### Changed
  - Updated `install.sh` to exclude development directories: `bugs/`, `legacy/`, `bare-metal/`, `tests/bug_reproductions/`
  - Updated `.gitignore` to exclude `bugs/` and `tests/bug_reproductions/` from version control
  - Cleaned samples directory to ~6.2MB (only EAS audio test files remain)

## [2.19.2] - 2025-12-10
### Removed
  - Removed Docker daemon health check from `/health/dependencies` endpoint
  - Moved `scripts/diagnose_cpu_loop.sh` to `legacy/` (Docker-specific)
  - Moved `scripts/diagnostics/diagnose_portainer.sh` to `legacy/` (Docker-specific)
  - Moved `scripts/collect_sdr_diagnostics.sh` to `legacy/collect_sdr_diagnostics_docker.sh` (Docker-specific)

### Added
  - Added Redis server health check to `/health/dependencies` endpoint
  - Created new bare-metal version of `scripts/collect_sdr_diagnostics.sh` using systemd and native tools

### Changed
  - Updated `webapp/routes_monitoring.py` to check Redis instead of Docker daemon
  - Updated comment in `webapp/routes_settings_radio.py` to remove Docker architecture reference
  - SDR diagnostics now use systemd service status and journalctl for logs instead of Docker commands

## [2.19.1] - 2025-12-10
### Removed
  - Removed unnecessary files from document root: `ipaws.env.example`, `noaa.env.example`, `pytest.ini`, `requirements-docs.txt`
  - Removed legacy SQL diagnostic files from root: `fix_all_stream_sample_rates.sql`, `fix_sample_rates.sql`, `diagnose_all_streams.sql`, `check_db_config.sql`
  - Moved Docker-era troubleshooting scripts to `legacy/` directory
  - Removed Docker references from documentation

### Changed
  - Updated `docs/installation/INSTALLATION_DETAILS.md` to remove Docker references
  - Updated `docs/troubleshooting/AUDIO_SQUEAL_FIX.md` to note it's for legacy Docker deployments
  - Updated `scripts/README.md` to remove references to deleted SQL files
  - Updated `webapp/routes_ipaws.py` to use systemd commands for service restarts instead of Docker
  - Updated `webapp/routes_monitoring.py` to remove docker-compose.yml from configuration checks

### Added
  - Added **Frontend-First Philosophy** to AI agent guidelines: All system management must be web-accessible
  - Added **CLI-Free Operations** requirement: Users should never need SSH or command-line access
  - Documented existing web UI features for logs, configuration, services, and troubleshooting

## [2.19.0] - 2025-12-10
### Changed
  - Updated troubleshooting guides to use systemd commands exclusively
  - Updated architecture documentation to reflect bare-metal deployment
  - Simplified migration guides to focus on bare-metal setup

## [2.18.0] - 2025-12-10
### Changed
  - Updated README.md to focus on bare metal deployment via systemd services
  - Configuration now uses `/opt/eas-station/.env` as standard location
  - Services managed via systemd: `sudo systemctl [start|stop|restart] eas-station.target`

### Removed
- Stack configuration: `stack.env`, `stack.env.example`

### Fixed
- Maintenance API uses standard filesystem paths instead of container paths

### Migration
- Complete installation guide available in `bare-metal/README.md`
- Quick start guide available in `bare-metal/QUICKSTART.md`

## [2.17.2] - 2025-12-09
### Fixed
- **EAS Monitor Display Issues**: Fixed decoding rates showing >100% and display bouncing between states
  - Root cause 1: Rate calculation `samples_per_second` was sensitive to timing variations and could spike >100%
  - Root cause 2: During startup (first 2 seconds), rate calculation reported 0, triggering "no audio" warnings
  - Root cause 3: Frontend hysteresis (2 consecutive readings) wasn't enough to prevent flicker at 100ms WebSocket rate
  - Fix 1: Added exponential moving average (EMA) smoothing with alpha=0.3 to filter timing noise
  - Fix 2: Implemented 2-second minimum sample threshold - report expected rate during warmup instead of 0
  - Fix 3: Health percentage grows linearly 0-95% during warmup for smooth visual feedback
  - Fix 4: Increased frontend hysteresis from 2 to 5 consecutive readings (500ms stability required)
  - Fix 5: Properly clamp health_percentage to [0, 1] range in all code paths
  - Result: Rates never exceed 100%, smooth warmup transition, no state bouncing

### Changed
- **Code Quality**: Extracted magic numbers to named class constants for easier configuration
  - `WARMUP_DURATION_SECONDS = 2` - Duration of warmup period
  - `WARMUP_MAX_HEALTH_PERCENTAGE = 0.95` - Maximum health shown during warmup
  - `RATE_SMOOTHING_ALPHA = 0.3` - EMA smoothing factor (lower=smoother, higher=more responsive)
  - `AUDIO_FLOWING_STABILITY_THRESHOLD = 5` - Frontend consecutive readings before state change
  - Improves maintainability and makes performance tuning easier

## [2.17.1] - 2025-12-09
### Fixed
- **CRITICAL: WebSocket Support Broken**: Fixed Flask-SocketIO async_mode mismatch that prevented WebSockets from working
  - Root cause: `app.py` used `async_mode='threading'` but gunicorn uses `--worker-class gevent`
  - This mismatch caused WebSockets to FAIL SILENTLY and fall back to long-polling
  - Fix: Changed `async_mode='threading'` to `async_mode='gevent'` to match gunicorn worker class
  - Impact: Enables real-time WebSocket updates at 10Hz (100ms) instead of 1-2 second polling intervals
  - This fixes why the entire site was polling despite WebSocket infrastructure being present
- **UI White Space**: Fixed excessive white space at top of pages caused by `flex: 1` on `.page-shell`
  - Root cause: Flexbox layout with `flex: 1` caused content to expand and fill all vertical space
  - Fix: Removed `flex: 1` from `.page-shell` - footer's `margin-top: auto` handles sticky footer
  - Result: Pages now start content immediately after navbar without huge gaps
- **EAS Monitor Status Flickering**: Fixed continuous toggling between "Processing at line rate" and "No audio sources configured"
  - Root cause: `audioFlowing` state changed on every momentary fluctuation in audio metrics
  - Fix: Added hysteresis mechanism requiring 3 consecutive stable readings before changing state
  - Result: Status display is now stable and only changes after sustained state change

### Changed
- **WebSocket Infrastructure**: Audio monitoring page already uses WebSockets when available
  - VU meters, EAS monitor, and broadcast stats all receive real-time updates via WebSocket
  - System automatically falls back to polling only if WebSocket connection fails
  - With this fix, WebSockets should now work properly and polling fallback won't be needed

### Notes
- This fixes the root cause of why 10+ previous agent sessions couldn't solve the white space issue
- The white space issue was subtle - `flex: 1` is a common flexbox pattern but caused unwanted expansion
- The WebSocket issue explains why 32 setInterval() polling calls exist throughout the codebase
- Future work: Extend WebSocket push service to broadcast all data types (alerts, system health, etc.) to eliminate remaining polling

## [2.16.5] - 2025-12-09
### Fixed
- **Application Startup Failure**: Fixed unterminated triple-quoted string literal in `webapp/admin/audio_ingest.py` at line 2237
  - Root cause: Docstring for legacy `generate_wav_stream()` function was never closed
  - This prevented database migrations from running and caused gunicorn workers to crash on startup
  - Fix: Properly closed the docstring and commented out the legacy code inside the function

## [2.16.3] - 2025-12-09
### Fixed
- **EAS Monitor Runtime Display**: Fixed runtime timer showing "0s" and buffer bar not filling on Audio Monitoring page
  - Root cause: API endpoint was not passing `wall_clock_runtime_seconds` from the audio-service metrics
  - Fix: Added `wall_clock_runtime_seconds` to the API response in `routes_eas_monitor_status.py`
- **Audio Detail Page Error**: Fixed "Unable to load audio detail at this time" error when viewing IPAWS-generated alerts
  - Root cause: Template used `url_for('alert_detail', ...)` but the route is on the `api` blueprint
  - Fix: Changed to `url_for('api.alert_detail', ...)` in `audio_detail.html`
- **Layout Spacing**: Reduced global `--layout-padding-top` from `1.5rem` to `0.5rem` to minimize gap between navbar and content
- **Audit Logs UI**: Fixed stat-card styling conflict where global vibrant gradient styles were overriding the audit logs page local styles
  - Added more specific CSS selectors (`.stats-row .stat-card`) to ensure local styles take precedence
  - Used `!important` flags to override global pseudo-elements that added shimmer/glow effects
  - Stats row now displays with correct neutral background instead of colorful mesh gradient

## [2.16.2] - 2025-12-09
### Fixed
- **Code Quality**: Fixed bare `except:` clauses in multiple files for PEP 8 compliance:
  - `scripts/run_radio_manager.py`: Added proper exception logging during cleanup
  - `debug_airspy.py`: Changed bare `except:` to `except Exception:` with comments
- **Defensive Coding**: Added None checks for `fetchone()` calls in migration and utility scripts:
  - `scripts/apply_source_type_migration.py`: Safe handling when column check returns no result
  - `app_core/migrations/versions/20251105_add_rbac_and_mfa.py`: Safe handling when INSERT RETURNING fails
  - `app_core/migrations/versions/20251116_populate_oled_example_screens.py`: Safe handling for screen insert

### Notes
- **Architecture Review**: Reviewed all 17 bugs from ARCHITECTURE_REVIEW_BUGS.md - most critical bugs (1-14) were already fixed in codebase
- Remaining bugs are low-priority design issues or already addressed

## [2.16.1] - 2025-12-09
### Fixed
- **Dashboard Layout**: Removed duplicate `page-shell` class from dashboard container that caused large gap at top of page
  - Root cause: `page-shell` was applied to both `<main>` in base.html and inner container in index.html
  - This resulted in double top padding (from both elements)
  - Fix: Removed redundant `page-shell` class from inner `<div class="container-fluid">` in index.html

## [2.16.0] - 2025-12-08
### Changed
- **BREAKING: Service Renaming - Clean Architecture**
  - Renamed `audio_service.py` → `eas_monitoring_service.py` (reflects actual purpose)
  - Renamed `sdr_service.py` → `sdr_hardware_service.py` (clarifies exclusive hardware access)
  - **Why**: Old names were confusing and led to architectural mistakes
  - **No backward compatibility wrappers** - clean break for clarity
  
### Files Changed
- `eas_monitoring_service.py`: New name for EAS monitoring + audio processing service
- `sdr_hardware_service.py`: New name for SDR hardware access service
- `RENAME_SERVICES.md`: Updated to reflect completed rename
- Old files (`audio_service.py`, `sdr_service.py`) removed completely

### Deployment Notes
```yaml
sdr-service:
  command: ["python", "sdr_hardware_service.py"]  # WAS: sdr_service.py
  
audio-service:
  command: ["python3", "eas_monitoring_service.py"]  # WAS: audio_service.py
```

Then rebuild and restart:
## [2.15.5] - 2025-12-08
### Fixed
- **CRITICAL: Complete SDR Hardware Separation**: Removed ALL SDR hardware access from audio-service.py
  - **Root Cause**: Both audio-service and sdr-service were fighting for USB access to SDR hardware
  - Removed `initialize_radio_receivers()` functionality from audio-service (kept stub for backward compat)
  - Removed RadioManager initialization and all `_radio_manager` references
  - Removed process_commands() SDR hardware operations (restart, get_spectrum, discover_devices)
  - Removed collect_metrics() radio_manager stats collection
  - Removed spectrum publishing loop with direct IQ sample access
  - **Result**: audio-service.py now ONLY subscribes to Redis channels from sdr-service
  - **Impact**: SDR hardware access is now exclusive to sdr-service.py container
  - **Why SDR Never Worked**: Both containers tried to open same USB devices → conflict
  - Fixed audio_sample_rate handling - now uses explicit setting or auto-detects from modulation
  - **Verification**: Check logs show sdr-service publishing and audio-service subscribing

## [2.15.4] - 2025-12-08
### Fixed
- **Code Quality: Removed Bare Except Statements**: Fixed 4 bare `except:` statements that could mask errors
  - `app_core/audio/eas_monitor.py`: Database rollback and SAME header parsing now log errors
  - `app_core/audio/streaming_same_decoder.py`: Message validation errors now logged at debug level
  - `app_core/audio/worker_coordinator_redis.py`: Redis connection close errors now logged
  - All exceptions now specify expected types (IndexError, AttributeError, Exception)
  - Improves debugging by making error paths visible in logs
  - Follows Python best practices for exception handling
  - **Impact**: Better error visibility and easier troubleshooting

## [2.15.3] - 2025-12-08
### Fixed
- **CRITICAL: Multi-Stream EAS Monitoring (LP1, LP2, SP1)**: Implemented per-source EAS monitoring
  - **Root Cause**: EAS monitor only listened to ONE audio source at a time (highest priority)
  - AudioIngestController.broadcast_pump selected only the highest priority running source
  - Main broadcast queue received audio from only ONE source, others were ignored
  - Result: LP1, LP2, SP1 web streams ran successfully but only ONE was monitored for EAS
  - **Fix**: Changed from single EAS monitor to per-source monitors (one for each stream)
  - Each audio source now has its own dedicated EAS monitor instance
  - All sources monitored simultaneously for SAME/EAS alerts
  - Alerts include source name in metadata for proper attribution
  - **Why IPAWS worked**: IPAWS uses internet polling (cap_poller.py), not audio monitoring
  - Enhanced logging shows which sources are being monitored
  - Proper shutdown handling for multiple monitor instances
  - Metrics collection aggregates stats from all monitors
  - **Impact**: Fixes complete loss of EAS monitoring from multiple web streams
  - **Applies to**: All deployments monitoring multiple audio sources (streams or SDR)

## [2.15.2] - 2025-12-08
### Fixed
- **CRITICAL: Audio Chain for SDR Sources (LP1, LP2, SP1)**: Fixed missing audio pipeline for SDR-based EAS monitoring
  - Added automatic audio source synchronization on audio-service startup
  - Previously, audio sources for radio receivers weren't created automatically, breaking the audio chain
  - In separated architecture, sdr-service publishes IQ samples to Redis, but audio-service needs AudioSourceConfigDB entries
  - Without these entries, RedisSDRSourceAdapter instances weren't created, preventing audio from reaching EAS monitor
  - New `sync_radio_receiver_audio_sources()` function ensures audio sources exist for all enabled receivers
  - Sets critical `managed_by='radio'` flag to trigger Redis adapter creation
  - Enhanced logging shows receiver details, subscription channels, and startup status
  - Affects LP1, LP2, SP1 and any other SDR receivers with audio_output=True
  - **Impact**: Fixes complete loss of EAS monitoring from local/state primary SDR sources

### Added
- **Diagnostic Tools**: Created comprehensive audio chain diagnostic utilities
  - `diagnose_audio_chain.py` - Full audio chain health check from SDR to EAS monitor
  - `fix_audio_source_sync.py` - Manual audio source sync tool with dry-run support
  - Both tools check receivers, audio sources, Redis connectivity, and IQ sample flow

## [2.15.1] - 2025-12-08
### Fixed
- **Template Consistency**: Fixed deprecated block usage in zigbee.html template, resolving CI failures
  - Changed `templates/settings/zigbee.html` from deprecated `{% block extra_js %}` to standard `{% block scripts %}`
  - Ensures all templates consistently use the `scripts` block for page-specific JavaScript
  - Fixes template consistency check CI workflow that was failing

## [2.15.0] - 2025-12-08
### Added - Phase 3: Professional Polish & UX Enhancements
- **Enhanced Error Messages**: Context-aware troubleshooting hints for network operations
  - Intelligent error parsing with user-friendly explanations
  - Specific hints based on error type (connection, scan, configuration)
  - Technical details available for advanced users
  - Common network issues with actionable solutions
- **Hostname Configuration**: Full system hostname management via NetworkManager
  - View current system hostname in Status tab
  - Set hostname with RFC 1123 validation
  - Persistent across reboots using hostnamectl
  - Real-time validation and feedback
- **Signal Strength Color Coding**: Visual quality indicators for WiFi networks
  - Red (0-25%): Poor signal strength
  - Orange (26-50%): Fair signal strength
  - Green (51-75%): Good signal strength
  - Teal (76-100%): Excellent signal strength
- **Information Tooltips**: Context-sensitive help throughout network UI
  - Bootstrap tooltips explaining technical terms (DHCP, Static IP, CIDR, DNS, Gateway)
  - Help icons next to complex form fields
  - Example values for IP addresses and network settings
  - Popular DNS server recommendations (Google, Cloudflare, Quad9)
- **Password Validation & Strength Indicator**: Real-time WiFi password feedback
  - WPA2/WPA3 validation (8-63 characters)
  - Visual strength indicator with color coding
  - Feedback messages for password quality
  - Frontend validation before submission
- **Loading States & Progress Indicators**: Professional async operation feedback
  - Spinners for network scans and long operations
  - Button disabling during operations to prevent double-clicks
  - Clear visual feedback for all network operations
- **Confirmation Dialogs**: Enhanced safety for destructive operations
  - Warning icons and explanations for network forget/delete
  - Clear consequences described in confirmation prompts
- **Session Persistence**: Remember user preferences
  - Last selected tab restored from session storage
  - Seamless navigation experience across page reloads
- **Auto-Refresh**: Intelligent status updates
  - Network status refreshes after configuration changes
  - Gateway info updates after connections
  - Connections list refreshes after modifications
- **Keyboard Shortcuts**: Power user features
  - Ctrl+R to refresh WiFi scan (on WiFi tab)

### Changed
- Network error displays now show hint and technical details
- Password input now includes real-time validation
- Confirmation dialogs provide more context for destructive actions
- Netmask dropdown now shows common use cases
- DNS server input includes popular server recommendations

## [2.14.0] - 2025-12-08
### Added - Phase 2: Core DASDEC3 Network Features
- **Wired Ethernet Support**: Added detection and display of eth0/ethernet interfaces with connection status
- **Static IP Configuration**: Full UI and backend for static IP settings (IP address, netmask, gateway) with toggle between DHCP and Static per interface
- **DNS Server Configuration**: Added ability to view, add, remove, and apply DNS server settings via NetworkManager
- **Network Diagnostics Tools**: Professional troubleshooting tools including:
  - Ping test with customizable packet count
  - Traceroute showing hop-by-hop network path
  - DNS lookup (nslookup) for hostname resolution
  - Default gateway information display
  - Complete routing table viewer
- **Saved Networks Management**: Display all saved WiFi profiles (not just in-range) with auto-connect status editing
- **Connection Profiles**: Complete NetworkManager connection management with:
  - List all saved connections with type and status
  - Show connection details (interface, autoconnect state)
  - Activate/deactivate connections
  - Toggle auto-connect per connection
  - Delete WiFi profiles
- **Tabbed Interface**: Professional Bootstrap tabs UI organizing features:
  - Status: Network overview and gateway info
  - WiFi: Wireless network scanning and connection
  - Wired: Ethernet interface configuration
  - DNS: DNS server management
  - Diagnostics: Network troubleshooting tools
  - Connections: Saved profile management
### Technical Details
- Added 12 new API endpoints to hardware_service.py for Phase 2 features
- Added corresponding proxy routes in webapp/admin/network.py
- Complete UI rewrite with Bootstrap tabs and professional DASDEC3-style layout
- All features use NetworkManager (nmcli) for consistency and reliability
- Static IP configuration with CIDR prefix calculation
- DNS configuration per connection with restart to apply changes
- Diagnostics tools with real-time output display
- Connection management with activate/deactivate and autoconnect toggle
### Impact
- ✅ Professional network management matching DASDEC3 standards
- ✅ Static IP support for production deployments
- ✅ DNS configuration for custom network environments
- ✅ Comprehensive diagnostics for troubleshooting
- ✅ Full control over saved network profiles
- ✅ Wired and wireless interface support
- ✅ DASDEC3-compatible feature set for professional EAS systems

## [2.13.5] - 2025-12-08
### Fixed
- **CRITICAL WiFi BUG**: Fixed WiFi scanning returning no networks even when networks available
- Added nmcli availability check - prevents silent failures when NetworkManager not installed
- Added WiFi interface auto-detection - finds wlan0/wlp* interfaces dynamically instead of hardcoded assumptions
- Fixed network status endpoint - now returns correct data structure with wifi.ssid that frontend expects
- Fixed WiFi scan race condition - replaced arbitrary 2-second sleep with proper completion detection
- Fixed disconnect functionality - backend now auto-detects active connection name instead of requiring frontend to send it
- Fixed empty scan results handling - now properly detects and reports when no networks found vs. scan failure
- Enhanced error handling and logging throughout WiFi operations
- Frontend now properly parses backend network status response structure
- Frontend disconnect sends empty body (backend auto-detects connection)
- Improved user feedback with toast notifications instead of alerts
### Impact
- ✅ WiFi scan now reliably detects and returns available networks
- ✅ Network status display shows current connection properly
- ✅ Disconnect functionality works correctly
- ✅ Better error messages help diagnose WiFi issues
- ✅ All WiFi operations (scan, connect, disconnect, forget) fully functional

## [2.13.4] - 2025-12-07
### Fixed
- **CRITICAL SEPARATION MISMATCH**: Fixed audio-service startup failing to load SDR sources from database
- audio-service was trying to create SDRSourceAdapter for `source_type='sdr'` but had no radio manager (separated architecture)
- Added detection: if source is radio-managed (`managed_by='radio'`), create RedisSDRSourceAdapter instead
- Now audio-service properly loads SDR sources on startup and subscribes to IQ samples from sdr-service
### Impact
- ✅ Audio sources persist across audio-service restarts
- ✅ No more "SDR source not available - radio manager missing" errors
- ✅ Separated architecture fully functional at startup

## [2.13.3] - 2025-12-07
### Fixed
- **CRITICAL AUDIO BUG**: Fixed source_type mismatch preventing audio from playing and Icecast mounts from appearing
- `ensure_sdr_audio_monitor_source` was sending `source_type: 'sdr'` but audio-service expected `'redis_sdr'` for separated architecture
- Result: RedisSDRSourceAdapter was never created, no audio demodulation happened, no Icecast mount appeared
- Changed to `source_type: 'redis_sdr'` so audio-service properly creates Redis IQ subscriber and Icecast output
### Impact
- ✅ Audio now plays from SDR receivers
- ✅ Icecast mounts now appear (e.g., /receiver.mp3)
- ✅ Complete end-to-end audio pipeline working

## [2.13.2] - 2025-12-07
### Fixed
- **CRITICAL END-TO-END**: Complete signal chain from detection to audio now works
- **Device Discovery**: Added `discover_devices` command handler in sdr-service
- **Receiver Creation**: Added `reload_receivers` command to sync database changes to sdr-service
- **Auto-Start**: New/updated receivers now automatically loaded by sdr-service
- Webapp now properly communicates with sdr-service for device discovery and receiver management
### Improved
- _sync_radio_manager_state now tells sdr-service to reload configuration
- Fallback to app-side radio manager if sdr-service unavailable
- Better error handling and logging throughout signal chain
- Device enumeration works in separated architecture

## [2.13.1] - 2025-12-07
### Fixed
- **CRITICAL AIRSPY BUG**: AirspyReceiver class was completely empty with NO Airspy-specific configuration
- **Airspy Never Worked**: Device would never get warm because no samples were being processed correctly
- Implemented proper `_open_handle()` override with Airspy R2 sample rate validation (2.5 MHz or 10 MHz only)
- Configured linearity gain mode for optimal strong signal handling (FM/NOAA)
- Added Bias-T safety (disabled by default to prevent equipment damage)
- Airspy R2 TCXO provides accurate frequency - no PPM correction needed
### Improved
- Comprehensive Airspy R2 configuration logging
- Sample rate validation with clear error messages
- Better exception handling for Airspy-specific settings

## [2.13.0] - 2025-12-07
### Added
- **MAJOR FEATURE**: PPM (Parts Per Million) frequency correction support for compensating crystal oscillator drift in SDRs
- Added `frequency_correction_ppm` field to RadioReceiver model and database schema
- Hardware frequency readback verification with mismatch warnings
- Comprehensive frequency tuning diagnostics and logging
### Fixed
- **Frequency Accuracy**: RTL-SDR and other low-cost SDRs now properly compensate for clock drift (typically ±50 PPM)
- **Tuning Verification**: Actual tuned frequency is now logged and verified against requested frequency
- **Diagnostic Logging**: Frequency settings, PPM correction, and readback values now logged for troubleshooting
### Improved
- Frequency accuracy can now be calibrated using PPM correction (e.g., calibrate with GSM cell tower or known station)
- Mismatch warnings help identify hardware tuning issues (> 1 kHz error triggers warning)
- Better separation: PPM correction in `ReceiverConfig` dataclass, not just database

## [2.12.27] - 2025-12-07
### Fixed
- **CRITICAL Demodulation Bug**: Added missing `process()` method to FMDemodulator and AMDemodulator classes that was being called by RedisSDRSourceAdapter but didn't exist, causing audio demodulation to fail completely
- Fixed method signature mismatch where redis_sdr_adapter.py called `demodulator.process()` but only `demodulate()` existed, preventing any audio from being generated from IQ samples

## [2.12.26] - 2025-12-07
### Fixed
- **SDR Core**: Implemented missing `get_ring_buffer_stats()` method in `_SoapySDRReceiver` that was being called by sdr_service.py but didn't exist, causing silent failures in buffer health monitoring
- **SDR Core**: Integrated SDRRingBuffer initialization in receiver startup to enable proper USB jitter absorption and backpressure handling
- **SDR Core**: Ring buffer now properly instantiated when device opens, providing robust sample buffering for reliable 24/7 SDR operation
- **SDR Core**: Capture loop now writes samples to ring buffer for overflow detection and backpressure monitoring
- **SDR Core**: Ring buffer properly shut down when receiver stops, preventing resource leaks
### Improved
- Enhanced ring buffer statistics reporting with fallback to simple buffer stats when SDRRingBuffer unavailable
- Added comprehensive buffer health metrics (overflow/underflow counts, fill percentage, total samples) to Redis
- Improved separation between app.py and SDR service - all SDR operations completely independent of Flask application
- Ring buffer overflow detection now logs dropped samples when processing can't keep up with USB data rate

## [2.12.25] - 2025-12-05
### Fixed
- **CRITICAL**: Fixed audio sources not starting when clicking start button - source name mismatch between webapp and audio-service (webapp sends "WIMT", audio-service expected "redis-WIMT")
- Fixed race condition in metrics publishing where audio-service was deleting eas_monitor metrics from Redis causing "No metrics available from audio-service" error
- Audio-service now uses original source names (not prefixed with "redis-") for separated architecture compatibility

## [2.12.24] - 2025-12-05
### Fixed
- Fixed audio-service container running Flask app.py during migrations by skipping database migrations in standalone service containers (audio-service, sdr-service, eas-service, hardware-service) that should not load the main Flask application

## [2.12.23] - 2025-12-05
### Documentation
- Clarified that SDR frontend already accepts frequency in MHz (not Hz) with automatic conversion
- Confirmed hardware-specific validation is already implemented (Airspy sample rate constraints, frequency range validation based on service type)
- Frontend validates sample rates based on hardware capabilities via `/api/radio/capabilities` endpoint
- Backend validates sample rate compatibility with driver via `validate_sample_rate_for_driver()` function

## [2.12.22] - 2025-12-05
### Fixed
- Fixed AirspyReceiver method override bug where `_open_device()` was defined but parent class uses `_open_handle()`, preventing Airspy-specific configuration (sample rate validation, linearity mode, bias-T settings) from ever executing
- Added `get_ring_buffer_stats()` method to SDR receivers to fix method-not-found errors when SDR service attempts to publish ring buffer statistics to Redis

## [2.12.21] - 2025-11-27
### Added
- Made SDR++ Server the default and recommended SDR option in the Radio Receiver settings UI
- Added prominent "SDR++ Server" quick-add button in the Quick Setup panel
- SDR++ Server now appears as the first option in the device selection dropdown
- Updated documentation (SDR Setup Guide) with comprehensive SDR++ Server setup instructions
- Added SDR++ Server to the hardware comparison table and configuration examples

### Changed
- Reordered SDR presets to prioritize SDR++ Server (network SDR) over direct USB connections
- Updated capture workflow description to mention SDR++ Server as the recommended approach
- Renamed "Discover Devices" button to "Discover USB Devices" for clarity

## [2.12.21] - 2025-11-27
### Fixed
- Let OLED alert scrolls run across the full padded buffer before wrapping so alert text cleanly exits and re-enters the screen instead of freezing or overlaying fragments.

## [2.12.20] - 2025-11-27
### Fixed
- Restored OLED alert scrolling by advancing the seamless scroll window based on elapsed frame time and speed settings so high-priority messages animate smoothly instead of freezing on a single frame.

## [2.12.19] - 2025-11-26
### Fixed
- Added IPv6 connectivity troubleshooting documentation (`docs/troubleshooting/FIX_IPV6_CONNECTIVITY.md`) so operators can diagnose SSL Labs IPv6 test failures and nginx upstream connection errors.

## [2.12.18] - 2025-11-26
### Fixed
- Redirected the policy docs URLs to the canonical `/terms` and `/privacy` routes and updated the documentation index to point to those pages so users no longer see divergent copies of the legal notices.

## [2.12.17] - 2025-11-25
### Fixed
- Redirect permission-denied responses to the dashboard blueprint's admin route so settings pages (including `/settings/alert-feeds`) return a proper 403 flow instead of a 500 BuildError when the non-namespaced endpoint is unavailable.

## [2.12.15] - 2025-11-22
### Changed
- Downsampled the continuous EAS monitor to 8 kHz (with automatic resampling from higher-rate sources) so SAME FSK decoding runs at an efficient rate without wasting CPU on unnecessary bandwidth.
- Surfaced both the source and decoder sample rates in the monitor status API so operators can verify the tap is resampling correctly instead of assuming 22.05 kHz.

## [2.12.14] - 2025-11-22
### Fixed
- Matched the streaming decoder sample rate to the active ingest source so SAME correlation and preamble detection run at the correct frequency instead of drifting off-sync when sources run at 44.1 kHz.
- Exposed the ingest-driven sample rate in the broadcast adapter stats returned with the EAS monitor status so operators can confirm the tap is aligned with the source.

## [2.12.13] - 2025-12-05
### Fixed
- Added broadcast subscription health (queue depth, underruns, last audio time) to the continuous monitor API so the dashboard shows when audio is actually flowing and operators can see the tap is healthy instead of guessing through empty fields.
- Throttled repetitive buffer underrun warnings from the monitor's broadcast adapter while still counting them for visibility, preventing log spam when sources are temporarily quiet.
- Exposed broadcast queue stats and the currently active source in `/api/audio/metrics` so VU meters can distinguish "no signal" from transport failures and display accurate runtime state.

## [2.12.12] - 2025-12-05
### Fixed
- Filled the continuous monitor status API with the streaming decoder's health, rate, and sync metrics so every dashboard field renders and operators can confirm the monitor is actively processing audio.
- Tagged live audio metrics with each source's runtime status so the VU meters reflect whether inputs are running instead of dimming as if they were offline.

## [2.12.10] - 2025-12-04
### Changed
- Added a selectable streaming mode on the audio monitor that prefers the built-in HTTPS stream by default and only opts into Icecast when operators explicitly choose it, reducing stalls when external ports are blocked.

## [2.12.9] - 2025-12-04
### Fixed
- Filter placeholder artwork metadata values (e.g., `null`, `undefined`, root-only paths) in the audio monitor so browsers stop
  requesting non-existent `/null` images from the dashboard host.

## [2.12.8] - 2025-12-03
### Fixed
- Corrected the default Icecast external port variable so Icecast URLs use the configured `ICECAST_EXTERNAL_PORT` rather than
  inheriting overrides meant for the internal port, preventing browsers from being pointed to blocked or unmapped port 8080
  endpoints.

## [2.12.7] - 2025-12-02
### Fixed
- Hardened the SDR audio monitoring stack by adding an auto-healing ingest controller that restarts stalled/error sources,
  auto-starts adapters when the live audio endpoint is hit, and exposes restart/error metadata so operators stop seeing
  permanent 503 responses, 0% buffer utilization, and "stream stalled" warnings on the monitoring dashboard.

## [2.12.6] - 2025-12-01
### Fixed
- Added a differential RBDS symbol slicer so FM demodulation correctly reconstructs PI/PS/RadioText metadata and keeps the latest
  decoded fields available to the SDR audio monitor.
- Hardened the SoapySDR receiver implementation by mapping stream error codes (including SOAPY_SDR_NOT_LOCKED) to descriptive
  messages and attaching PLL lock hints so operators immediately see when a tuner simply needs to acquire lock instead of chasing
  misleading "cannot open device" errors.

## [2.12.5] - 2025-11-30
### Changed
- Disabled the CAP poller's optional SDR capture orchestration by default so its RadioManager hooks stay idle unless the poller
  needs to request IQ/PCM recordings for an alert playback, added the `CAP_POLLER_ENABLE_RADIO` environment flag, and exposed a
  `--radio-captures/--no-radio-captures` CLI switch so operators can explicitly opt into capture requests when they actually
  want files.

## [2.12.4] - 2025-11-29
### Fixed
- Forced OLED templates with manually positioned lines to default to no-wrapping in the renderer so preview cards and physical
  displays stop stacking wrapped segments on top of each other and keep their typography aligned.

## [2.12.3] - 2025-11-29
### Fixed
- Updated the OLED layout migration to use uniquely named bind parameters so Alembic can compile the update statement without colliding with column names, preventing the `bindparam() name 'name' is reserved` failure during upgrades.

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
- Clarified the commercial license offer notes pricing covers software only and excludes any hardware costs.
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
- Removed caching from `/api/audio/metrics` and set explicit no-store headers so VU meters and live audio telemetry refresh in
  real time instead of waiting for multi-second cache windows.
- Hardened backup API endpoints by validating backup names to block path traversal before
  touching the filesystem.
- Removed the CAP poller's area-term fallback so `/alerts` only surfaces entries that explicitly name the configured SAME or
  UGC codes, eliminating false positives from neighboring county descriptions.
- Ensured the continuous EAS monitor auto-initializes on demand so the audio monitoring page no longer stalls when the monitor
  wasn't started during app boot.
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
- Clarified the update instructions to explicitly pull the Experimental branch when refreshing deployments.
- Documented the expectation that deployments supply their own PostgreSQL/PostGIS host and simplified Compose instructions to run only the application services.
- Reworked the EAS Output tab with an interactive Manual Broadcast Builder and refreshed the README/HELP documentation to cover the browser-based workflow.
- Enhanced the Manual Broadcast Builder with a hierarchical state→county SAME picker, a deduplicated PSSCCC list manager, a live `ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-` preview with field-by-field guidance, and refreshed docs that align with commercial encoder terminology.
- Added a one-touch **Quick Weekly Test** preset to the Manual Broadcast Builder so operators can load the configured SAME counties, test status, and sample script before generating audio.
- Updated the Quick Weekly Test preset to omit the attention signal by default and added a
  “No attention signal (omit)” option so manual packages can exclude the dual-tone or 1050 Hz
  alert when regulations allow.
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
  file is missing so systemd deployments no longer fail with "env file not found".
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
- Added automatic cache-busting query parameters to all Flask-served static asset URLs so envoy/nginx layers fetch freshly deployed bundles instead of stale copies (Screenshot_7-11-2025_75931_easstation.com.jpeg).

## [2.4.11] - 2025-11-09
### Fixed
- Corrected the documentation viewer's Mermaid block detection to support Windows-style line endings so diagrams render instead of showing raw code.
- Refreshed system version metadata on each request so the footer and monitoring endpoints display the latest release after version bumps.

## [2.4.1] - 2025-11-09
### Fixed
- **Resolved production nginx image regressions** - Ensured HTTPS container bundles required tooling and static assets
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
  mixed geometry types.

## [2.1.0] - 2025-10-25
### Added
- Established the NOAA CAP alert monitoring stack with Flask, PostGIS persistence,
  automatic polling, and spatial intersection tracking.
- Delivered the interactive Bootstrap-powered dashboard with alert history, statistics,
  health monitoring, and boundary management tools.
- Integrated optional LED sign controls with configurable presets, message scheduling,
  and hardware diagnostics.
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
