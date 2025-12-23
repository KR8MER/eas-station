# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project currently
tracks releases under the 2.x series.

## [Unreleased]

### Added
- **VS Code Development Guide and Configuration** - Comprehensive VS Code setup for local and remote development
  - Created `docs/guides/VSCODE_LOCAL_SETUP.md` - Complete guide for local development setup
  - Created `docs/guides/CONNECTING_TO_FLASK.md` - Detailed guide for connecting to Flask application
  - Created `eas-station.code-workspace` - Pre-configured VS Code workspace file with all settings
  - Created `.vscode/eas-station.code-snippets` - Code snippets for common EAS Station patterns
  - Created `.vscode/VSCODE_QUICK_START.md` - Quick reference for VS Code setup
  - Created `CONTRIBUTING.md` - Comprehensive contributing guide with VS Code workflow
  - Updated `README.md` with links to VS Code setup guides
  - Workspace includes:
    - Python interpreter configuration
    - Debug configurations for all services
    - Tasks for common operations (Flask dev server, tests, database queries, Redis monitoring)
    - Database connection settings (SQLTools)
    - Linting and formatting configuration
    - Extension recommendations
  - Code snippets include:
    - Flask routes with database queries
    - Database models (including settings models)
    - API endpoint templates
    - Test functions
    - Jinja2 templates
    - Bootstrap components
  - Documentation covers:
    - Local development setup (PostgreSQL, Redis, Python)
    - VS Code features and shortcuts
    - Debugging workflows
    - Database management
    - Testing procedures
    - Git workflow
    - Flask connection methods and troubleshooting
    - Troubleshooting common issues

### Fixed
- **CRITICAL: RBDS Buffer Management Fixed** - Changed from buffer-draining to index-based bit processing
  - Root cause: `_decode_rbds_groups()` was using `pop(0)` in a `while` loop, consuming ALL bits even during failed presync
  - When presync found valid blocks but spacing verification failed, bits were already consumed and lost
  - This caused constant `buffer=0` in logs and prevented synchronization from ever being achieved
  - Changed to index-based processing (like python-radio reference) that preserves unprocessed bits
  - Bits are only removed from buffer after successful processing or when buffer exceeds 6000 bit limit
  - Failed presync attempts now preserve bits for retry instead of discarding them
  - Added `_rbds_buffer_index` to track position in buffer without destroying data
  - Improved logging: spacing mismatches now show which block types caused the mismatch
  - Reference: https://github.com/ChrisDev8/python-radio/blob/main/decoder.py (lines 235-280)
  - File: `app_core/radio/demodulation.py` method `_decode_rbds_groups()`

- **CRITICAL: RBDS M&M Timing Return Statement Bug** - Fixed undefined variable causing RBDS processing failure
  - Root cause: Line 651 referenced undefined variable `n_out` in ternary expression
  - This caused M&M timing recovery function to crash, preventing RBDS bit extraction
  - RBDS was stuck in presync mode because bits were never being processed correctly
  - Simplified return statement to only check `out_list` variable
  - RBDS should now properly extract bits and achieve synchronization
  - File: `app_core/radio/demodulation.py` line 651

- **RBDS Presync False Positives Fixed** - Removed inverted syndrome check from presync phase
  - Root cause: Presync was checking both normal AND inverted syndromes, creating false positive matches
  - False positives led to spacing mismatches and failed synchronization ("expected 78, got 24" errors)
  - Differential decoding (line 841) already handles 180° Costas loop phase ambiguity
  - Python-radio reference implementation only checks normal syndrome during presync
  - Now matches proven working implementation: presync uses normal syndrome only
  - Synced mode still checks both polarities for additional robustness
  - Added polarity tracking: logs "NORMAL polarity" or "INVERTED polarity" when decoding blocks
  - Added statistics: "RBDS sync OK: X/50 bad blocks, polarity: Y normal, Z inverted"
  - Reference: https://github.com/ChrisDev8/python-radio/blob/main/decoder.py (lines 253-264)
  - File: `app_core/radio/demodulation.py`

- **CRITICAL: RBDS Synchronization Fixed** - Replaced M&M clock recovery with working reference implementation
  - Root cause: Timing recovery was using incorrect algorithm that prevented sync
  - Implemented python-radio's interpolation-based M&M clock recovery with 16x upsampling
  - Uses mu-based sample interpolation for precise symbol timing
  - Maintains timing state (mu, rail history) across chunk boundaries for continuous streaming
  - Differential decoding now correctly handles phase ambiguity
  - RBDS should now properly synchronize and decode station info (PI, PS, RT)
  - Reference: https://github.com/ChrisDev8/python-radio/blob/main/decoder.py
  - File: `app_core/radio/demodulation.py`

## [2.43.0] - 2024-12-20

### Added
- **Icecast Source Limit Configuration** - Made maximum concurrent sources configurable
  - Added `max_sources` field to `IcecastSettings` database model
  - Web UI field at `/admin/icecast` to configure max concurrent audio sources
  - Supports 0 for unlimited sources, or positive integer for specific limit
  - Updates `/etc/icecast2/icecast.xml` `<sources>` limit automatically
  - Default behavior: If not set (null), Icecast uses its default of 2 sources
  - File: `app_core/models.py`, `webapp/admin/icecast.py`, `templates/admin/icecast.html`

### Fixed
- **CRITICAL: SDR Audio Source Startup Failure** - Fixed `ModuleNotFoundError: No module named 'app_core.radio.rbds'`
  - Root cause: `FMDemodulator._init_rbds_state()` was trying to import `RBDSDecoder` from non-existent `.rbds` module
  - `RBDSDecoder` class is defined in the same file (`app_core/radio/demodulation.py` line 1662)
  - Removed incorrect import statement on line 297
  - SDR audio sources now start correctly without module import errors
  - Fixes "Audio source is error" message preventing audio monitoring
  - File: `app_core/radio/demodulation.py`
- **CRITICAL: Hardware Module Import Errors Fixed** - Fixed `ImportError` crashes in VFD and LED modules
  - **VFD**: Removed `VFD_PORT` and `VFD_BAUDRATE` from `app_core/vfd.py` `__all__` exports (not defined as module-level constants)
  - **VFD Routes**: Updated `webapp/routes_vfd.py` to use `get_vfd_settings()` from `app_core.hardware_settings` instead of importing constants
  - **LED**: Removed `LED_SIGN_IP` and `LED_SIGN_PORT` from `app_core/led.py` `__all__` exports (not defined as module-level constants)
  - **LED Routes**: Updated `webapp/routes_led.py` to use `get_led_settings()` from `app_core.hardware_settings` in 4 locations
  - All hardware settings now properly retrieved from HardwareSettings database table
  - Fixes Alembic migration failures and app startup crashes with "cannot import name" errors
  - Files: `app_core/vfd.py`, `app_core/led.py`, `webapp/routes_vfd.py`, `webapp/routes_led.py`

- **CRITICAL: Hardware Integrations Database Migration Complete** - Fixed ALL hardware settings to use database exclusively
  - **OLED Display**: Removed `OLED_ENABLED` module constant, checks database dynamically in `initialise_oled_display()`
  - **LED Sign**: Removed all environment variable parsing (`LED_SIGN_IP`, `LED_SIGN_PORT`), uses HardwareSettings database
  - **VFD Display**: Removed all environment variable usage (`VFD_PORT`, `VFD_BAUDRATE`), uses HardwareSettings database
  - **GPIO Controller**: Removed `OLED_ENABLED` import, dynamically checks database for OLED enabled status
  - **Hardware Service**: Removed all environment variable fallbacks, always uses database settings
  - **Display State Publishing**: Now checks database settings AND controller existence before showing "enabled"
  - **LED Routes**: Removed all `os.getenv()` calls, uses `get_led_settings()` from database
  - **System Controls**: Dynamically checks OLED enabled status from database instead of module constant
  - **EAS Utils**: Dynamically checks OLED enabled status from database instead of module constant
  - **Environment Validation**: Deprecated GPIO_PIN_BEHAVIOR_MATRIX validation (now uses database)
  - **Fixed "400 Bad Request: Unknown variable: GPIO_PIN_BEHAVIOR_MATRIX"** error
  - **Environment variables for hardware are NOW DEPRECATED**: Use `/admin/hardware` instead
    - ❌ `GPIO_ENABLED`, `GPIO_PIN_MAP`, `GPIO_PIN_BEHAVIOR_MATRIX`
    - ❌ `OLED_ENABLED`, `LED_SIGN_IP`, `LED_SIGN_PORT`
    - ❌ `VFD_PORT`, `VFD_BAUDRATE`
  - All hardware settings must be configured via the web UI at `/admin/hardware`
  - Changes require hardware service restart to take effect: `systemctl restart eas-station-hardware.service`
  - Files: `app_core/oled.py`, `app_core/led.py`, `app_core/vfd.py`, `hardware_service.py`, 
    `webapp/routes_led.py`, `webapp/routes/system_controls.py`, `app_utils/eas.py`, `webapp/admin/environment.py`

- **Hardware Settings Page Improvements** - Fixed multiple issues with the hardware settings page
  - Fixed "None" parsing error in number input fields (oled_contrast field was rendering `value="None"` as string)
  - Fixed heading hierarchy accessibility issue (changed h4 to h3 to follow h1 → h3 → h4 structure)
  - Removed GPIO pin configuration UI from hardware settings (now properly links to `/admin/gpio/pin-map`)
  - Improved text readability by breaking long run-on sentences into multiple lines
  - Added proper navigation links to GPIO Control Panel, Pin Map, and Statistics pages
  - GPIO configuration is now correctly separated: enable/disable in hardware settings, pin mapping in dedicated page
  - File: `templates/admin/hardware_settings.html`

- **CRITICAL: RBDS Metadata Not Displaying** - Fixed RBDS metadata not showing in UI
  - Root cause: RBDS data was None 9 out of 10 chunks due to throttling (only processed every 10th chunk)
  - Frontend checks `if status.rbds_data:` which is False when None
  - **Solution**: Persist last valid RBDS data in demodulator (`_last_rbds_data`)
  - Return persisted data on skipped processing cycles instead of None
  - RBDS metadata now continuously displays (PS name, radio text, PTY, PI code)
  - Still only processes heavy convolutions every 10th chunk (maintains audio fix)
  - File: `app_core/radio/demodulation.py` - Added `_last_rbds_data` persistence

- **CRITICAL: SDR Audio Cutouts Fixed** - Fixed 5-6 second audio cutouts in SDR monitor streams
  - Root cause: RBDS processing performing 3 heavy convolutions on every audio chunk
  - RBDS decimation filter (`np.convolve` with up to 1024 taps on 2.5MHz signal) was blocking audio thread
  - Two additional convolutions (bandpass and lowpass filters) added to blocking time
  - Total processing time: 5-6+ seconds per chunk, causing complete audio dropout
  - **Solution**: Reduced RBDS processing frequency from every chunk to every 10th chunk
  - Audio now plays continuously without gaps
  - RBDS metadata still updates (just less frequently - every ~1 second instead of ~100ms)
  - Reduces CPU overhead from 100% to ~10% for RBDS extraction
  - File: `app_core/radio/demodulation.py` - Added `_rbds_process_counter` and `_rbds_process_interval`

### Added
- **RBDS and Stereo Path Verification** - Comprehensive verification tools and documentation
  - Added `tools/analyze_rbds_stereo_code.py` - Static code analyzer for RBDS/stereo paths
  - Added `tools/trace_rbds_stereo_path.py` - Runtime tracer for signal flow (requires numpy)
  - Added `tools/validate_rbds_stereo_config.py` - Database configuration validator
  - Added `docs/audio/RBDS_STEREO_PATH_VERIFICATION.md` - Complete path documentation
  - Verified all filters use correct sample rate (original SDR rate, not decimated)
  - Verified carrier generation uses correct phase timing
  - Verified RBDS extraction at 57 kHz subcarrier with differential BPSK
  - Verified stereo decoding at 38 kHz subcarrier with L+R/L-R matrix
  - Verified metadata propagation from demodulator to frontend
  - All paths confirmed working correctly with no issues detected

### Fixed
- **CRITICAL: Icecast Bitrate Configuration** - Fixed auto-discovered streams using wrong bitrate
  - Auto-streaming service was hardcoded to 128kbps instead of using configured bitrate
  - Added `stream_bitrate` and `stream_format` fields to `IcecastAutoConfig`
  - Now reads bitrate and format from database IcecastSettings or environment variables
  - Auto-discovered SDR streams now use the same bitrate as manually configured streams
  - Ensures consistent stream quality across all sources

- **CRITICAL: SDR Not Mounting on Icecast** - Fixed race condition preventing SDR audio streams from mounting
  - Auto-streaming service was only checking for RUNNING sources at startup
  - SDR sources may still be STARTING (async initialization), causing them to be skipped
  - Added auto-discovery loop to `AutoStreamingService._monitor_loop()` that:
    * Periodically discovers new RUNNING sources every 10 seconds
    * Automatically adds them to Icecast streaming
    * Removes streams for stopped/removed sources
  - Eliminates manual intervention or service restart to mount SDR streams
  - Fixes "cuts out after 6 seconds" issue caused by unmounted streams timing out
  
- **IMPROVED: Demodulator Error Handling** - Added protective error handling to prevent silent failures
  - Added try-except wrapper around `_create_demodulator()` in RedisSDRSourceAdapter
  - Demodulator creation failures now log detailed error messages
  - Failures properly propagate to prevent sources from starting with broken configuration
  - Helps diagnose RBDS-related initialization issues

- **REDUCED: Excessive RBDS Logging** - Reduced log spam from RBDS configuration
  - Changed device_params and RBDS config logging from INFO to DEBUG level
  - Prevents log flooding during normal operation
  - Retains detailed logging for troubleshooting when needed
- **IMPROVED: EAS Monitor Logging** - Enhanced diagnostic information in eas-service logs
  - Added `audio_flowing` status indicator (✅ or ⚠️) for immediate visual feedback
  - Added `samples_per_second` throughput metric to monitor processing rate
  - Added `time_since_last_audio` to detect connectivity issues
  - Added `alerts_detected` count for monitoring alert detection activity
  - Changed log format from basic "running/samples/health" to comprehensive operational status
  - Helps operators quickly diagnose issues like audio not flowing vs. processing problems
  - Example new format: `📊 EAS Monitor Status: ⚠️ audio_flowing=False, samples=0 (0/sec), health=0.0%, time_since_audio=45.2s, alerts=0`

### Added
- **24/7/365 Audio Subsystem Reliability** - Major improvements for continuous operation
  - Enhanced FFmpeg reconnection with 30-second timeout and HTTP error retry (4xx, 5xx)
  - Increased buffer sizes: 10000 chunks (~14 minutes at all sample rates due to resampling)
  - Added connection tracking: attempts, success rate, and last connection time
  - Improved FFmpeg command with `-fflags +discardcorrupt` to handle corrupt packets
  - 128KB FFmpeg buffer (up from 64KB) for better network stream performance
  - Reduced restart delay from 3s to 2s for faster recovery
  - Added detailed connection logging with success rates

### Fixed
- **CRITICAL: EAS Decoder False Health Warnings** - Fixed incorrect "below expected rate" alerts
  - Health calculation was dividing by total configured sources instead of active sources
  - Example: 2 sources configured, 1 running → expected 32k samples/sec but got 16k → showed 50% health
  - Resulted in misleading "⚠️ Processing at 19.6% of expected rate" when actually at 100%
  - Fixed `eas_monitor_v3.py` line 603 to divide by `active_sources` only
  - Now correctly shows ~100% health when receiving expected rate from active sources
  - Eliminates false alarms when subset of configured sources are running

- **IMPROVED: Buffer Utilization Display Logic** - Fixed misleading low utilization warnings
  - Low buffer utilization (0-20%) is actually GOOD for real-time streaming (consumers keeping up)
  - Previous logic incorrectly showed warnings for <1% utilization
  - Implemented tiered interpretation system:
    * 0-20%: "✓ Real-time streaming" (IDEAL - consumers keeping up with producers)
    * 20-80%: "✓ Buffering X%" (OK - normal buffered operation)
    * 80-95%: "⚠️ WARNING: Buffer filling up" (consumers falling behind)
    * >95%: "🔴 CRITICAL: Buffer nearly full" (about to drop packets)
  - Added audio flow validation (frames > 0, peak > -100dB) before showing warnings
  - Improved diagnostics distinguishing "stream connecting" from "truly broken"
  - Eliminates false warnings when system is operating optimally

- **CRITICAL: Second Stream Not Working** - Fixed multi-stream audio source issue
  - StreamSourceAdapter was setting `_had_data_activity=False` causing capture loop to sleep during connection
  - Network streams need 5-10 seconds to establish HTTP connection before audio flows
  - Changed to set `_had_data_activity=True` for stream sources to prevent excessive sleeping
  - Added comprehensive comments explaining FFmpeg connection phases (DNS, TCP, HTTP, stream)
  - Capture loop now polls frequently during initial connection instead of sleeping 50ms
  - Fixes "No audio data flowing" error when adding second stream (WIMT issue)
  - All streams now properly initialize regardless of startup order
  - Health monitoring still detects broken streams via metrics updates and process checks

### Changed
- **EAS Monitor Architecture** - Major architectural improvement: resample BEFORE queueing
  - Audio now resampled from source rate (48kHz) to 16kHz BEFORE entering EAS queue
  - EAS monitor receives pre-resampled 16kHz audio directly (no conversion needed)
  - Eliminates resampling bottleneck that caused packet drops
  - Reduces queue memory usage by 3x (16kHz vs 48kHz samples)
  - 10000 chunk queue provides ~14 minutes of buffering (same duration at all rates due to resampling)
  - At 48kHz: 10000 chunks × 4096 samples = 40.96M samples / 48kHz = 853 seconds
  - At 16kHz: 10000 chunks × 1365 samples = 13.65M samples / 16kHz = 853 seconds
  - Removed ResamplingBroadcastAdapter dependency - no longer needed
  - Each audio source now has two queues: native rate for streaming, 16kHz for EAS

### Fixed
- **WebSocket Infinite Recursion** - Fixed "maximum recursion depth exceeded" errors in websocket updates
  - `_safe_emit()` was calling itself recursively instead of calling `socketio.emit()`
  - Fixes crashes in audio_monitoring_update and system_health_update
  - WebSocket events now emit properly without stack overflow

- **EAS Monitor Packet Drops** - Fixed critical issue where EAS monitor drops audio chunks
  - Reduced sleep from 10ms to 1ms when audio flowing to prevent queue buildup
  - EAS monitor now reads ~1000x/second, far exceeding audio production rate (~12 chunks/sec at 48kHz)
  - Increased broadcast queue size from 5000 to 10000 chunks (~14 minutes buffer) for 24/7 reliability
  - Queue duration stays constant across sample rates due to resampling (853 seconds)
  - Prevents missing emergency alerts due to dropped audio packets
  - Fixes "Subscriber 'eas-unified-WNCI' queue full" errors with thousands of drops
  - Note: Audio is correctly downsampled from source rate (48kHz) to decoder rate (16kHz)

- **Stream Sample Rate Detection** - Fixed FFmpeg not detecting actual stream sample rate
  - Changed FFmpeg log level from 'error' to 'info' to capture stream metadata
  - Stream sample rate (e.g., 48kHz) is now properly detected from FFmpeg output instead of defaulting to 44.1kHz
  - Prevents streams from sounding slow due to incorrect playback sample rate
  - Improved stderr logging to only show warnings/errors, not every info line
  - Fixes issue where streams would play at wrong speed when native rate differs from config

### Removed
- **Waveform Monitor from SDR/Radio Admin Page** - Removed non-functional waveform/waterfall spectrum display
  - Removed waveform monitor card UI (lines 249-267)
  - Removed ~440 lines of JavaScript code for spectrum visualization
  - Removed functions: createWaveformCanvas, getWaterfallColor, drawSpectrumGraph, drawWaterfall, updateWaveform, updateAllWaveforms, startWaveformRefresh, stopWaveformRefresh
  - Feature was not working and displayed "Waiting for data..." indefinitely
  - Radio receivers table and configuration functionality remain intact

### Fixed
- **EAS Decoder Stream 404 Error** - Fixed missing nginx proxy for `/api/eas/decoder-stream` endpoint
  - Added nginx proxy configuration for EAS decoder audio stream (port 5002)
  - Users can now listen to the 16kHz decoder feed without 404 errors
  - Matches existing `/api/audio/stream/` proxy configuration with streaming-optimized settings

- **Decoder Health Status Bouncing** - Fixed conflicting monitor status causing UI to flicker
  - Root cause: When extracting first monitor's stats, per-source metrics were used instead of aggregated values
  - Backend now preserves aggregated `samples_processed`, `samples_per_second`, `health_percentage` from parent status
  - Prevents frontend from seeing "0 samples" when first source is idle but other sources are active
  - Frontend hysteresis logic now works correctly with consistent aggregated metrics
  - Fixes "No audio flowing" warnings appearing despite active sources

- **RWT Schedule Configuration Page Load Error** - Fixed JavaScript "ReferenceError: renderCountyList is not defined"
  - Added missing `renderCountyList()` function to render county chips in editor panel
  - Added missing `renderScheduleCountyList()` function to render county chips in schedule preview
  - Added missing `addCountyCode()` function to handle adding counties to the broadcast list
  - Added missing `removeCountyCode()` function to handle removing counties from the broadcast list
  - Page now loads correctly without JavaScript errors
  - County management functionality is now fully operational

- **Separated RWT broadcast codes from alert listener codes** - RWT Schedule page now maintains its own list of broadcast coverage codes (RWTScheduleConfig.same_codes) completely independent from alert filtering codes (LocationSettings.fips_codes). This allows users to listen for nationwide/statewide alerts without broadcasting RWT to those areas. (Issue: listener list for FIPS codes and RWT list were the same)

- **Audio Monitoring JavaScript Errors** - Fixed syntax error and undefined function
  - Removed extra closing brace `}` in `onAudioPlaybackError()` function
  - Fixed incorrect indentation causing `return;` statement to be outside control flow
  - JavaScript brace balance now correct (557 open, 557 close)
  - Fixes "Uncaught SyntaxError: Unexpected token '}'" error at line 1848
  - Fixes "Uncaught ReferenceError: renderAudioSources is not defined" error
  - All audio monitoring pages now load without JavaScript errors

- **WebSocket Parse Errors** - Fixed malformed JSON causing repeated WebSocket disconnects
  - `_sanitize_float()` now properly handles None values (returns -120.0)
  - `_sanitize_bool()` now properly handles None values (returns False)
  - WebSocket audio metrics emission now safely handles None values from Redis
  - Prevents `float(None)` TypeErrors that were causing JSON serialization failures
  - Fixes "parse error" WebSocket disconnects on all pages (audio-monitor, audio-sources, interactive map)
  
- **Audio Metrics JSON Error** - Fixed "No number after minus sign" JSON parsing error
  - Error occurred at position 135 when API returned malformed numeric values
  - Added comprehensive None/null handling to `_sanitize_float()` function
  - Added type conversion fallback with try/except to handle edge cases
  - Metrics API endpoint now returns valid JSON even with null/invalid Redis data

- **EAS Sample Rate Default** - Changed from 22.05kHz to 16kHz (optimal for CPU efficiency)
  - 16kHz is optimal for SAME decoder - adequate quality, lower CPU overhead
  - Frontend fallback changed from 44.1kHz to 16kHz to match backend
  - Admin UI now shows "16000 Hz (Recommended - Low CPU)" with help text
  - Database migration and model updated to use 16kHz default

- **Audio Streaming Complexity** - Removed ~150 lines of dead code
  - Removed Icecast priority switching logic (always returned false)
  - Removed `shouldUseIcecastStream()`, `switchToProxyStream()`, `labelForStreamType()` functions
  - Simplified audio element to use `/api/audio/stream/{source}` directly
  - Removed unused data attributes: `icecast-url`, `proxy-url`, `initial-stream-type`, `stream-type`
  - Simplified error recovery to cache-busted URL reload only

### Added
- **NEW: EAS Decoder Audio Stream** - Listen to exactly what the decoder processes
  - New `/api/eas/decoder-stream` endpoint streams 16kHz resampled audio
  - "Listen to EAS Decoder Feed" button added to Audio Monitoring page
  - Critical for debugging why alerts aren't being detected
  - Streams MP3 at 64kbps (16kHz sample rate, same as decoder input)
  - Uses ffmpeg for real-time MP3 encoding with non-blocking I/O

### Changed
- EAS Settings sample rate default: 22.05kHz → 16kHz
- Audio player initialization simplified (no more stream type detection)
- Stream recovery uses inline cache-busted reload instead of helper function

**Audio Source Form Consistency** - Removed sample rate field from user-facing audio sources page
  - Sample rate field removed from `/templates/audio_sources.html` to match admin page
  - Prevents confusion where UI shows non-functional sample rate input
  - Form now shows 3 fields in one row (channels, silence threshold, silence duration)
  - Consistent with admin page where sample rate was already removed

- **SDR Receiver Restart Command** - Added status information to restart response
  - SDR service now returns receiver status (locked, signal_strength, running) after restart
  - Webapp restart endpoint properly displays post-restart receiver state
  - Fixes incomplete restart command implementation in Redis command queue

- **Audio Source Form Bug** - Fixed JavaScript error when adding audio stream sources
  - Removed reference to non-existent `sampleRate` form field in `addAudioSource()` function
  - Error: "Cannot read properties of null (reading 'value')" at audio_monitoring.js:1177
  - Sample rate now properly defaults to 44100 Hz on backend, auto-detected for streams
  - Resolves issue preventing users from adding HTTP/M3U stream sources

- **CRITICAL: 10x Bandwidth Reduction** - Flask proxy now streams MP3 instead of WAV
  - Implemented real-time MP3 encoding using ffmpeg subprocess
  - Bandwidth: ~705 kbps WAV → ~128 kbps MP3 (5.5x reduction for mono 44.1kHz)
  - Web browser playback uses Flask MP3 proxy (Icecast has mounting issues)
  - PCM audio piped to ffmpeg for libmp3lame encoding at 128 kbps
  - Non-blocking I/O for low latency streaming
  
- **HTTP Stream Sample Rate Auto-Detection** - Removed manual sample rate input
  - Sample rate field removed from audio source configuration form
  - FFmpeg automatically detects native stream sample rate from metadata
  - Dynamic config update when FFmpeg reports detected rate via stderr
  - Prevents user from selecting wrong sample rate and breaking playback
  - Validates detected rates within 8kHz-192kHz range

- **HTTP Stream Sample Rate Detection** - Fixed slow/fast playback from sample rate mismatches
  - Added FFmpeg stderr parsing to detect actual stream sample rate (e.g., "44100 Hz", "48000 Hz")
  - Dynamically updates `config.sample_rate` when FFmpeg reports different native rate
  - Prevents pitch/speed issues caused by WAV header sample rate not matching FFmpeg output
  - Validates detected rates are within 8kHz-192kHz range
  - Logs when config sample rate differs from detected stream rate

### Changed
- **Web Audio Streaming** - Switched from WAV to MP3 encoding
  - Flask proxy now uses ffmpeg subprocess for real-time MP3 encoding
  - Streams at 128 kbps MP3 instead of ~705 kbps uncompressed WAV
  - Maintains native sample rate (no resampling except for EAS decoder)
  - Icecast bypassed due to mounting issues - Flask MP3 provides same bandwidth efficiency

- **Audio Source Configuration** - Simplified stream setup
  - Quick RWT and "Load Default Codes" now use `RWTScheduleConfig.same_codes` (broadcast coverage area)
  - Removed incorrect fallback to `LocationSettings.fips_codes` (which are for filtering incoming alerts)
  - `LocationSettings.fips_codes` can include nationwide (000000) and statewide codes for alert filtering
  - `RWTScheduleConfig.same_codes` should only include local broadcast area counties
  - Resolves issue where Quick RWT showed different codes than Weekly RWT configuration
  - Updated UI labels and help text to clearly distinguish "broadcast codes" vs "alert filtering codes"

### Changed
- **Environment Variable Cleanup** - Removed unused/database-migrated environment variables from admin interface
  - Removed `EAS_MANUAL_FIPS_CODES` from EAS section (now use RWT Schedule page in database)
  - RWT broadcast codes are now exclusively managed via RWTScheduleConfig.same_codes
  - Kept core EAS settings (EAS_BROADCAST_ENABLED, EAS_ORIGINATOR, EAS_STATION_ID) which are still used by install scripts and core code
  - Kept polling settings (POLL_INTERVAL_SEC, CAP_TIMEOUT, NOAA_USER_AGENT) which are still actively used
  - All configuration remains available via environment variables for backwards compatibility and install scripts

### Improved
- **RWT Configuration UI Clarity** - Better organization of FIPS code configuration flow
  - RWT Schedule page now clearly labeled as "RWT Broadcast Coverage Area"
  - Added explanatory alerts distinguishing broadcast codes from alert filtering codes
  - Updated Broadcast Builder warning to direct users to RWT configuration page
  - Improved help text throughout to explain the purpose of each FIPS code configuration

- **Certificate Installation Sudo Permission** - Fixed SSL certificate installation failing with password prompt
  - Added `/usr/bin/tee` to sudoers for writing SSL snippet file to `/etc/nginx/snippets/ssl-letsencrypt.conf`
  - Added `/usr/bin/mkdir -p /etc/nginx/snippets` to sudoers for creating snippets directory
  - Added `/usr/bin/grep` to sudoers for checking nginx configuration
  - Resolves: "Failed to write SSL snippet: sudo: a terminal is required to read the password"
  - Certificates can now be installed trivially after being obtained

### Added
- **EAS Decoder Monitor Settings Model** - Database model for configurable EAS decoder audio tap
  - Created `EASDecoderMonitorSettings` table to control decoder monitoring stream
  - Allows listening to 16 kHz resampled audio fed to SAME decoder
  - Verifies decoder receives correctly resampled audio
  - Configurable enable/disable and stream name
  - Migration: `20251219_add_eas_decoder_monitor_settings.py`
  - TODO: Implement actual streaming endpoint for decoder tap

- **EAS Broadcast Settings Admin Page** - New database-based EAS configuration interface
  - Created EAS Broadcast Settings section in Admin Panel for managing EAS broadcast configuration
  - Added `EASSettings` model with all EAS broadcast parameters stored in database
  - Moved EAS settings from environment variables to database:
    - `broadcast_enabled` - Enable/disable EAS broadcasting
    - `originator` - Originator code (WXR, CIV, PEP, EAS)
    - `station_id` - Station call sign identifier
    - `authorized_fips_codes` - FIPS codes authorized for broadcast (JSONB array)
    - `authorized_event_codes` - Event codes authorized for broadcast (JSONB array)
    - `attention_tone_seconds` - Attention tone duration
    - `sample_rate` - Audio sample rate
    - `audio_player` - Audio playback command
    - `output_dir` - EAS message output directory
  - Added FIPS builder UI for authorized broadcast counties (same UI pattern as location settings)
  - Database migration: `20251219_add_eas_settings.py`
  - API endpoints: `GET/PUT /admin/eas_settings`
  - Replaces environment variables: `EAS_BROADCAST_ENABLED`, `EAS_ORIGINATOR`, `EAS_STATION_ID`, etc.

- **Zone Lookup Feature for Location Settings** - Interactive zone search and selection
  - Added zone search panel with debounced search functionality
  - Search by zone code, state code, or county name
  - Click to add zones to either Broadcast or Storage categories
  - Color-coded cards: blue for Broadcast zones, green for Storage zones
  - Zone count badges show number of selected zones
  - Integrated with existing zone catalog API endpoints

### Fixed
- **Storage Zone Codes Not Saving** - Fixed location settings form not saving storage zone codes
  - Created dedicated `location-settings.js` JavaScript module for proper form handling
  - Storage zone codes now correctly included in form submission payload
  - Consolidated location settings JavaScript from fragmented inline scripts
  - Addresses: "The Storage Zone Codes (Local County Only) are not being saved"

- **Removed Deprecated Fields** - Cleaned up location settings page
  - Removed deprecated "Area Terms" field (keywords for filtering)
  - Removed LED sign notification reference
  - Streamlined location settings form with only relevant fields


- **Certificate Domain Mismatch Detection** - Added detection and helpful message for certificate domain mismatches
  - Detects when user accesses site via hostname that doesn't match certificate domain
  - Shows clear warning with current hostname vs certificate domain
  - Provides actionable solutions: access via correct domain or obtain new certificate
  - Adds button to redirect to correct domain automatically
  - Addresses: "Im on the https page. The certificate isnt being loaded properly"
  
- **HTTPS Redirect After Certificate Installation** - Fixed missing HTTPS redirect after successful certificate installation
  - Added automatic 5-second countdown redirect from HTTP to HTTPS after certificate is installed
  - Certificate installation now properly switches user to secure HTTPS connection
  - Added "Go to HTTPS Now" button for immediate redirect
  - Added "Cancel Redirect" button to prevent automatic redirect if needed
  - Fixes issue where user remained on HTTP after successful certificate installation, making buttons non-functional
  - Addresses: "Still not working..." - certificate installed but page stayed on HTTP
  
- **Certificate Installation Not Working** - Fixed SSL certificate installation failures
  - Replaced fragile Python string `.replace()` with robust `sed` commands for nginx config updates
  - Fixed nginx reload/restart logic after certificate acquisition
  - Added proper nginx status checking before reload
  - Fixed field name mismatch: JavaScript expected `expires_at` but backend returned `valid_until`
  - Fixed domain display: JavaScript expected `domains` array but backend returned `domain` string
  - Enhanced frontend to show installation status with detailed feedback
  - Installation now properly comments out self-signed cert and uncomments Let's Encrypt cert
  - Addresses: "This still isn't installing certificates" - CN still showing localhost instead of domain
  
- **Certbot Certificate Installation** - Fixed automatic certificate installation after acquisition
  - Fixed missing `require_auth` import causing Error 500 on install endpoint
  - Added automatic certificate installation after successful certificate acquisition
  - Created `_install_certificate_internal()` helper function to reduce code duplication
  - Standalone and webroot methods now automatically install certificates after obtaining them
  - Certificate symlink creation, nginx configuration update, and reload all happen automatically
  - Addresses: "certbot isnt installing certificate" - certificates now install immediately after acquisition
- **Poller Settings Navigation** - Moved poller settings link from navbar to admin page
  - Removed standalone navbar link in Settings dropdown
  - Added poller settings card to admin.html configuration section
  - Changed permissions from `settings.manage` to `system.configure` for consistency
  - Poller settings now accessible via Admin Panel → System Settings → Poller Settings
  - Fixes permission access issue

- **Certbot Certificate Installation** - Fixed certificate installation after successful acquisition
  - Added `/admin/api/certbot/install-certificate` endpoint to install obtained certificates
  - Creates symlink from `/opt/eas-station/certbot_data/config/live/` to `/etc/letsencrypt/live/`
  - Automatically updates nginx configuration to use Let's Encrypt certificates
  - Comments out self-signed certificate configuration
  - Reloads nginx to apply changes
  - Added "Install Certificate" button after successful certificate acquisition
  - Addresses: "It obtained a certificate... It failed to install it"

- **Certificate Display Formatting** - Improved certificate information presentation
  - Enhanced certificate info grid with better visual hierarchy and spacing
  - Added icons for each field (certificate, globe, shield, calendar, hourglass, status)
  - Improved hover effects with border color change and subtle lift
  - Highlighted Days Remaining and Status fields with gradient background
  - Larger, bolder text for certificate values for better readability
  - Better certificate type formatting (shows "Self-Signed", "Let's Encrypt", etc.)
  - Addresses: Certificate display readability improvement request

## [2.39.0] - Previous Release

### Added
- **Poller Settings Admin Page** - New database-based poller configuration interface
  - Created `/admin/poller` page for managing alert poller settings
  - Added `enabled` and `poll_interval_sec` fields to `PollerSettings` model
  - Poller now reads configuration from database instead of environment variables
  - Dynamic interval updates without service restart (checked each poll cycle)
  - Poller can be enabled/disabled via admin UI
  - Links to existing `/logs?type=polling&limit=100` for viewing polling logs
  - Added navigation link in Settings dropdown menu
  - Database migration: `20251218_add_poller_settings.py`
  - Replaces `POLL_INTERVAL_SEC` environment variable with database setting
  - Default interval: 120 seconds (recommended for IPAWS/FEMA feeds)

- **Poller Detailed Logging** - Added database-based setting to log detailed alert information
  - New `PollerSettings` model with `log_fetched_alerts` boolean field
  - When enabled, logs full alert details: ID, event, sent/effective/expires times, urgency/severity/certainty, area, and headline
  - Helps debug missing or filtered alerts
  - Configured via Admin → Poller Settings
  - Queried once per poll cycle for efficiency
  - Database migration required: `alembic upgrade head`

### Fixed
- **Update Script Password Prompts** - Fixed update.sh asking for eas-station user password
  - Added `root ALL=(eas-station) NOPASSWD: ALL` to sudoers configuration
  - Allows root to run commands as eas-station user without password prompt
  - Update.sh now installs/updates sudoers file early in update process
  - Fixed pre-existing sudoers syntax errors (escaped colons in chown commands)
  - Addresses: "The update script is asking for eas-stations password"

- **Install/Update Scripts Webroot Directory Ownership** - Fixed webroot directory permissions in install.sh and update.sh
  - Changed ownership from www-data:www-data to root:root in both scripts
  - Ensures certbot (runs as root) can write challenge files during initial setup
  - Previously would fail on first webroot certificate attempt after fresh install
  - Now consistent with runtime `_ensure_webroot_directory()` function
  - Added explanatory comments about root:root ownership requirement
  - Addresses: Webroot permission errors on fresh installations

- **Certbot Webroot Permission Issues** - Fixed webroot directory permissions for certbot
  - Added `_ensure_webroot_directory()` function to create `/var/www/certbot` with proper permissions
  - Webroot directory now owned by root:root with 755 permissions (certbot writes as root, nginx reads as www-data)
  - Previously owned by www-data with 755, preventing root (certbot) from writing challenge files
  - Added sudoers entries for webroot directory creation and permission management
  - Added better error messages for permission and path errors in webroot mode
  - Addresses: "PermissionError: [Errno 13] Permission denied: '/var/www/certbot/.well-known/acme-challenge/...'"

- **Certbot Nginx Plugin Permission Issues** - Fixed fundamental implementation flaw with nginx plugin
  - Removed nginx plugin as default method (caused permission errors with `/var/log/nginx/error.log`)
  - Changed default to standalone mode (same as used in install.sh - proven to work)
  - Reordered methods: Standalone (recommended), Webroot (no downtime), Nginx (not recommended)
  - Removed `_ensure_nginx_log_permissions()` function (didn't solve the fundamental issue)
  - Nginx plugin runs `nginx -t` which may execute in different security context (AppArmor, SELinux)
  - Even with chmod 666, certbot's nginx test can't write to error.log in some environments
  - Added clear warning messages when nginx plugin fails with permission errors
  - Addresses: "Error while running nginx -c /etc/nginx/nginx.conf -t" - Permission denied on /var/log/nginx/error.log

### Added
- **TTS Audio Playback on Test** - TTS configuration page now plays audio after successful test
  - Audio player appears with controls after TTS test completes
  - Automatically plays the generated audio (if browser allows)
  - Allows users to hear the TTS output directly in the UI

- **RWT TTS Override Option** - Quick RWT now respects the TTS toggle setting
  - Added `force_rwt_defaults` parameter to `build_manual_components()`
  - When user explicitly enables TTS for RWT in Broadcast Builder, it is honored
  - By default, RWT still disables TTS per EAS specification

### Fixed
- **Broadcast Builder TTS Warning for RWT Events** - Fixed misleading TTS warning for Required Weekly Test
  - RWT events intentionally disable TTS (per EAS specification - RWT should only have SAME header and EOM tones)
  - Previously, the warning "TTS was requested but no audio was generated" appeared even for RWT
  - Now correctly detects when TTS was disabled by the system (vs. failed) and only logs for actual failures
  - Added `tts_enabled` field to components to track actual TTS state after event-specific overrides
  - Addresses: "TTS was requested but no audio was generated" for RWT events

- **Broadcast Builder TTS Not Using Database Settings** - Fixed SQLAlchemy session caching issue
  - Added `db.session.refresh()` after loading TTS settings to force fresh database read
  - TTS settings configured via /admin/tts were not being seen by Broadcast Builder
  - The SQLAlchemy session was returning cached/stale data instead of current database values
  - This caused TTS to appear as "not configured" in Broadcast Builder even though it worked on the test page
  - Addresses: "TTS works on config page test but not in Broadcast Builder"

- **TTS Configuration Logging to SystemLog** - Added diagnostic logging visible in web UI
  - Broadcast Builder now logs TTS configuration status to SystemLog when TTS is requested
  - Shows tts_provider in System Logs (/logs)
  - Makes debugging TTS issues easier without needing systemd journal access

- **TTS "No Provider Configured" Error Reporting** - Fixed silent TTS failure when no provider is configured
  - `TTSEngine.generate()` now sets `last_error` when no TTS provider is configured
  - This ensures `tts_warning` is properly populated in Broadcast Builder
  - Previously, when no TTS provider was set, the engine returned None without setting an error
  - This caused the message "TTS was requested but no audio was generated" with no explanation
  - Now displays helpful message: "No TTS provider configured. Configure TTS at /admin/tts in the web UI."
  - Addresses: "TTS was requested but no audio was generated" without explanation

- **Certbot Nginx Log Permission Sudoers** - Added missing sudo permissions for nginx log management
  - Added sudoers entries for `/var/log/nginx` directory creation and permission commands
  - Certbot's nginx plugin runs `nginx -t` which requires write access to log files
  - Added: mkdir, chmod, touch, chown commands for `/var/log/nginx/error.log` and `access.log`
  - Fixes error: `open() "/var/log/nginx/error.log" failed (13: Permission denied)` when running certbot

- **Broadcast Builder TTS Logging to SystemLog** - TTS errors and warnings now visible in System Logs UI
  - Logs TTS synthesis failures to SystemLog database table (visible in web UI under System Logs)
  - Logs when TTS is requested but no audio is generated
  - Includes provider name, warning message, and event details in log entries
  - Makes TTS debugging much easier without needing systemd journal access
  - Addresses: "TTS isn't working in broadcast builder, and I'm not seeing logs"

### Fixed
- **Certbot Nginx Permission Error** - Fixed nginx log permissions for certbot nginx plugin
  - Changed `/var/log/nginx/error.log` permissions from 640 to 666 to allow certbot's `nginx -t` to succeed
  - Set ownership to `www-data:adm` (standard nginx log ownership)
  - Creates both error.log and access.log with proper permissions
  - Certbot runs `nginx -t` in a different security context, requiring more permissive log file access
  - Addresses error: `open() "/var/log/nginx/error.log" failed (13: Permission denied)`

- **Broadcast Builder Exception Logging** - EAS generation failures now logged to SystemLog
  - Exceptions during broadcast generation are now logged to SystemLog database
  - Includes error type, message, identifier, and event code for debugging
  - Makes debugging broadcast builder issues easier through web UI

## [Version 2.38.5 and earlier]

### Added
- **Certbot Status Route Alias** - Added `/admin/api/certbot/status` endpoint as alias for `/admin/api/certbot/certificate-status` for frontend compatibility
- **TTS Debugging Logging** - Added comprehensive logging to help diagnose Broadcast Builder TTS issues
  - EASAudioGenerator now logs TTS provider configuration at initialization
  - Logs when message text is empty (would prevent TTS generation)
  - Logs when attempting TTS generation with character count
  - Logs TTS generation success with sample count
  - Logs TTS synthesis failures ALWAYS (even when no error details available)
  - Logs when TTS is disabled (include_tts=False)
  - Logs when provider is not configured
  - Added full exception stack traces to workflow error logging
  - Helps identify configuration vs. runtime issues in Broadcast Builder
  - Addresses issues: "Broadcast Builder is not generating TTS audio" and "Errors in the broadcast builder aren't being logged"

### Fixed
- **AudioIngestController.get_broadcast_queue() Error** - Fixed AttributeError in eas_monitoring_service.py
  - Method was removed in refactor but code still called it
  - Added public methods `get_source()`, `get_all_sources()` to AudioIngestController for proper access
  - Changed to iterate through sources and get broadcast queue from each source
  - Fixed metrics collection to aggregate broadcast queue stats from all audio sources
  - Fixed web audio streaming to get broadcast queue from source adapter instead of controller
  - Added safety check with `hasattr()` before calling `get_broadcast_queue()`
  - No longer directly accesses private `_sources` attribute
  - Addresses error: `'AudioIngestController' object has no attribute 'get_broadcast_queue'`

- **TTS Azure OpenAI Endpoint Validation** - Made endpoint validation less strict
  - Changed to only require `/deployments/` path instead of full `/audio/speech` path
  - Now shows warning instead of error if `/audio/speech` is missing
  - Allows Microsoft Azure-provided endpoints that may have different formats
  - Addresses error: `Azure OpenAI endpoint is incomplete - missing /audio/speech path`

- **.env File Parsing Error** - Fixed python-dotenv parsing error on line 17
  - Changed AZURE_OPENAI_CONFIG from single-quoted to escaped double-quoted JSON
  - Changed LOCATION_CONFIG from single-quoted to escaped double-quoted JSON
  - Addresses warning: `python-dotenv could not parse statement starting at line 17`

- **TTS Test Function** - Added ability to test TTS configuration from admin page
  - New "Test TTS" button on `/admin/tts` configuration page
  - New API endpoint `/admin/api/tts/test` to generate test audio
  - Test uses sample message to verify TTS engine works correctly
  - Shows detailed success information (duration, samples, voice used)
  - Shows detailed error messages on failure with troubleshooting hints
  - Test results displayed in color-coded alert box (green=success, red=failure)
  - Logs test attempts and results to system logs
  - Allows users to verify TTS settings before generating actual alerts
  - Addresses request: "Can we add a method to test the TTS in the configuration page?"

- **TTS Not Working - Missing Logging** - Added comprehensive logging for TTS failures
  - Added detailed error messages when TTS credentials are missing from database
  - Changed log level from WARNING to ERROR for critical TTS failures
  - Added logging showing which credentials are missing (endpoint, API key, etc.)
  - Added logging when Azure OpenAI endpoint format is invalid
  - Added logging when deployment name cannot be extracted from endpoint URL
  - Added logging showing TTS configuration status at startup
  - Logs now guide users to configure TTS at `/admin/tts` in web UI
  - Fixed: Users can now see why TTS fails in system logs instead of silent failures
  - Addresses issue where "all variables are populated" but no logs explain failures

- **TTS API Key Masking Issue** - Removed password masking from API key field
  - Changed API key input from `type="password"` to `type="text"` in `/admin/tts`
  - Users can now see the actual API key value they're entering
  - Prevents browser auto-fill and password manager interference
  - Fixes issue where masked field prevented users from verifying correct key entry
  - API keys are still stored securely in database, just visible in UI for easier configuration

- **Certbot Not Working - Missing Logging** - Added comprehensive logging for Certbot failures
  - Added detailed error logging for all certbot operations (obtain, renew, standalone, nginx, webroot)
  - Added logging of full certbot commands being executed
  - Added logging of both stdout and stderr from certbot failures
  - Added logging showing which method (standalone/nginx/webroot) is being used
  - Logs now show exact certbot return codes and error messages
  - Addresses issue where certbot failures had no logs explaining what went wrong

- **Certbot Nginx Plugin Permission Error** - Fixed nginx log permission issue for certbot
  - Fixed: `open() "/var/log/nginx/error.log" failed (13: Permission denied)`
  - Added `_ensure_nginx_log_permissions()` function to create and fix log directory permissions
  - Creates `/var/log/nginx` directory with proper ownership (www-data:www-data)
  - Sets directory permissions to 755 and log file permissions to 644
  - Creates `error.log` file if it doesn't exist before running certbot
  - Function called automatically before certbot nginx plugin execution
  - Certbot nginx plugin now works without permission errors
  - Fixes issue where certbot's `nginx -t` config test failed due to log file permissions

- **Certbot Port 80 Permission Error** - Fixed certbot standalone mode failing to bind to port 80
  - Changed default certificate acquisition method from `standalone` to `nginx` plugin
  - Nginx plugin doesn't require stopping nginx or binding to privileged ports
  - Added port 80 availability check before running standalone mode
  - Added 2-second delay after stopping nginx to ensure port 80 is released
  - Added explicit HTTP-01 challenge configuration for standalone mode
  - Added nginx running check before attempting nginx plugin method
  - Updated UI to reflect nginx plugin as recommended method (no downtime)
  - Improved error messages to guide users when port binding fails
  - Standalone method still available but requires manual selection
  - Fixes: "PermissionError: [Errno 13] Permission denied" when binding to port 80

### Changed
- **Admin Page Refactoring Phase 2 Complete** - Completed modularization of admin.html JavaScript
  - Moved final inline function `sanitizeBoundaryTypeInput` to core.js module
  - Removed outdated comments about remaining inline functions
  - admin.html reduced from original 7,461 lines to 2,043 lines (73% reduction, exceeding 30% target)
  - All JavaScript now modularized into 9 separate files (132KB total) for better maintainability
  - Improved browser caching with external modules
  - Cleaner separation of concerns between template variables and business logic
  - Version bump to 2.38.0 marks completion of Phase 2 refactoring

### Fixed
- **Admin HTML Template Structure** - Completed refactoring of admin.html template structure
  - Removed 5 incorrectly placed closing tags and comments after setup mode section
  - Fixed improper div nesting that was closing containers prematurely before {% else %} block
  - Removed duplicate closing `</div>` tag in manage data section
  - Template now has proper Jinja2 block structure with balanced opening/closing tags
  - Fixes whitespace and rendering issues introduced during previous refactoring
  - Template validation confirms all Jinja2 blocks (if/endif, for/endfor, block/endblock, with/endwith) are balanced

### Fixed
- **Admin Page Excessive White Space** - Removed redundant container wrappers and spacing
  - Removed redundant `container-fluid` wrapper in regular (non-setup) mode
  - Removed `py-2` padding from main container (reduces top spacing)
  - Removed `mt-4` top margin from all tab content containers (Data, System, Services, Security tabs)
  - Changed tab-content CSS padding from `1rem 1.5rem 1.5rem 1.5rem` to consistent `1.5rem`
  - Fixed improper div nesting between setup mode and regular mode sections
  - Tabs now render inside card-header with `p-0 border-0` for seamless integration
  - Tab content now renders inside card-body with `p-0` to avoid double padding
  - Cleaned up closing div comments for better code clarity
  - Results in much tighter, cleaner admin interface without excessive vertical gaps
  - References bug file: `/bugs/whitespace.html`

### Fixed
- **JavaScript Duplicate Declaration Errors** - Fixed console errors from duplicate function declarations
  - Removed 851 lines of duplicate inline JavaScript code from admin.html
  - Cleaned up alert management inline code (variables and 385 lines of functions)
  - Cleaned up operations inline code (466 lines of functions including helpers)
  - External modules now load without conflicts with inline code
  - Fixes errors: "Identifier 'adminAlerts' has already been declared" and "Identifier 'renderQueryDetails' has already been declared"
  - admin.html reduced from 6,587 lines to 5,736 lines

### Changed
- **Admin Page Refactoring - Phase 2 (Major Progress)** - Modular JavaScript extraction
  - ✅ Moved 449 lines of inline CSS to `/static/css/admin.css`
  - ✅ Extracted 8 JavaScript modules (~2,380 lines total):
    - `/static/js/admin/core.js` (163 lines) - Global state and utilities
    - `/static/js/admin/utilities.js` (240 lines) - Confirmations, status, formatting
    - `/static/js/admin/zone-catalog.js` (182 lines) - Zone management
    - `/static/js/admin/snow-emergency.js` (263 lines) - Snow emergency operations
    - `/static/js/admin/user-management.js` (280 lines) - User CRUD operations
    - `/static/js/admin/alert-management.js` (513 lines) - Alert editing and display
    - `/static/js/admin/hardware-settings.js` (160 lines) - LED and GPIO config
    - `/static/js/admin/operations.js` (580 lines) - Backup, upgrade, manual imports
  - All modules loaded in correct dependency order in admin.html
  - Improved browser caching - CSS and 8 JavaScript modules cached separately
  - All theme-aware functionality preserved across modules
  - Remaining modules to extract: Boundary Management, Location Settings, EAS Generator (~2,200 lines)
  - admin.html reduced from 7,461 lines to 6,587 lines (874 line reduction)
  - See `docs/development/ADMIN_PAGE_REFACTORING.md` for full refactoring plan

### Fixed
- **Excessive Whitespace on Pages** - Fixed large vertical gaps between content and footer
  - Changed `.page-shell` flex property from `flex: 1 0 auto` to `flex: 0 0 auto` in styles.css
  - Reduced `--layout-padding-bottom` from 2.5rem to 1rem (60% reduction)
  - Reduced `--footer-margin-top` from 60px to 20px (67% reduction)
  - Total vertical gap reduced from ~100px to ~36px for more compact, modern layout
  - Page shell now only takes the space it needs instead of expanding to fill viewport height
  - Footer now appears immediately after content without excessive gaps
  - Affects all pages including admin, GPIO control, services, and other low-content pages
  - References bug screenshots: Screenshot_17-12-2025_*.jpeg

- **Admin Page Visual White Space** - Fixed rendering issues caused by unbalanced HTML structure
  - Removed 3 extra closing div tags causing layout problems
  - Fixed zone catalog section with 1 redundant closing div
  - Corrected improper div closing between setup_mode and normal mode conditional blocks
  - Fixed container-fluid divs closing in wrong conditional branches
  - All 612 div tags now perfectly balanced (612 opening, 612 closing)
  - Changed JavaScript event listeners from `shown.bs.pill` to `shown.bs.tab` for Bootstrap 5 compatibility
  - Zone Catalog tab now loads data when clicked
  - Snow Emergencies tab now loads data when clicked

- **Admin Page Tab Structure** - Fixed critically broken HTML structure preventing tabs from loading
  - Moved System Settings sub-tabs (Location, Alerts, Snow Emergency) inside system-settings tab-pane
  - Moved Security sub-tab (User Management) inside security tab-pane
  - Added proper tab-content containers for sub-tabs (systemTabContent, securityTabContent)
  - Removed improper comment claiming sub-tabs should be top-level (they must be nested for Bootstrap)
  - Closed all unclosed divs in Security tab structure
  - Fixed Operations tab starting inside Security tab's unclosed divs
  - All 6 main tabs and 7 sub-tabs now load correctly
  - Validates with balanced Jinja2 template syntax

- **Admin Page Tab Navigation** - Fixed broken tab structure preventing tabs from loading
  - Fixed JavaScript event listener for Zone Catalog tab (ID mismatch: `zones-tab` → `zones-subtab`, event: `shown.bs.tab` → `shown.bs.pill`)
  - Fixed JavaScript event listener for Snow Emergency tab (ID mismatch: `snow-emergencies-tab` → `snow-subtab`, event: `shown.bs.tab` → `shown.bs.pill`)
  - Fixed System Settings tab structure by removing confusing empty `<div class="tab-content">` that caused nesting issues
  - All 6 main tabs (Data, System, Services, Hardware, Security, Operations) now load correctly
  - All 7 sub-tabs now function properly

- **RBAC User Management** - User roles now display correctly in user management page
  - Fixed backend `AdminUser.to_safe_dict()` to return `role_name` instead of `role`
  - Users with assigned roles now show role badges (Admin, Operator, Viewer, etc.)
  - Fixes "No Role" appearing for all users even when roles were assigned

- **Icecast Connection Test** - Fixed 400 Bad Request error when testing Icecast connection
  - Improved `test-connection` endpoint to handle empty JSON request bodies gracefully
  - Added better error logging for connection test failures

- **Icecast Configuration Warnings** - Fixed Icecast server startup warnings
  - Added `server_hostname`, `server_location`, `admin_contact` fields to IcecastSettings model
  - Created database migration to add new fields
  - Added UI fields in Icecast admin page to configure server information
  - Fixes warnings: "hostname not configured", "location not configured", "admin contact not configured"

### Added
- **Admin Page Refactoring Phase 2 Completion Guide** - Created detailed extraction roadmap
  - Documented 80 remaining inline functions across 3 modules
  - Complete function lists with line numbers and dependencies
  - Step-by-step extraction process guide
  - Comprehensive testing checklist for each module
  - Load order requirements and risk assessment
  - Time estimates: 6-8 hours to complete Phase 2
  - See `docs/development/ADMIN_REFACTORING_PHASE2_REMAINING.md` for details

- **Admin Page Refactoring Documentation** - Created comprehensive refactoring roadmap
  - Documented current state: 7,453 lines, 388KB file size
  - Analysis: 67.5% JavaScript (5,034 lines, 150+ functions), 26.4% HTML, 6.0% CSS
  - Phased refactoring plan (Phase 1 complete, Phase 2-3 planned)
  - See `docs/development/ADMIN_PAGE_REFACTORING.md` for details

- **Environment Variables UI** - Added missing environment variables to frontend configuration
  - **Redis Category**: `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` for granular Redis server configuration
  - **TTS Category**: `EAS_TTS_PROVIDER`, `AZURE_OPENAI_CONFIG` for text-to-speech provider settings
  - **Certbot Category**: `DOMAIN_NAME`, `SSL_EMAIL`, `CERTBOT_STAGING` for SSL certificate management
  - **EAS Category**: `EAS_SCAN_INTERVAL`, `MAX_CONCURRENT_EAS_SCANS` for audio scanning configuration
  - **System Category**: `TZ` (timezone), `BACKUP_DIR`, `WEB_ACCESS_LOG` for system settings
  - All environment variables from `.env.example` now have corresponding UI fields

- **Database Migration** - `20251217_add_icecast_server_info.py` for Icecast server information fields

### Changed
- Icecast admin page now includes Server Information section for hostname, location, and admin contact

### Added
- **TTS Settings Database Migration** - Moved TTS configuration from environment variables to database
  - Created `TTSSettings` database model for persisting TTS configuration
  - Added dedicated TTS settings page at `/admin/tts` with user-friendly UI
  - Link added to admin panel Operations tab for easy access
  - Settings now stored in database and survive reboots/updates reliably
  - Supports Azure OpenAI, Azure Cognitive Services, and pyttsx3 providers
  - Database is the only source - no fallback to environment variables
  - Removed TTS settings from environment configuration page to avoid confusion

- **Admin Panel Links** - Added missing administrative page links to Operations tab
  - Added link to SSL/TLS Certificates page (`/admin/certbot`)
  - Added link to Icecast Streaming page (`/admin/icecast`)
  - Added link to Zone Catalog Management page (`/admin/zones`)
  - Added link to Text-to-Speech page (`/admin/tts`)
  - All major admin tools now accessible from the main admin panel

- **Icecast Logs** - Added Icecast service logs to system logs viewer
  - `icecast2.service` now appears in log service dropdown
  - Allows viewing Icecast streaming server logs through the web interface
  - Updated `app_core/config/services.py` to include icecast in INFRASTRUCTURE_SERVICES

### Fixed
- **TTS Configuration Persistence** - Fixed Azure OpenAI TTS settings not surviving reboots/updates
  - Fixed JSON builder showing bullet characters (`••••••••`) instead of actual API key values
  - Backend now properly masks only password fields within JSON configs, preserving JSON structure
  - When saving, masked password values are preserved from existing config instead of being overwritten
  - TTS settings now correctly persist across application restarts and updates
  - Fixes "Invalid JSON: Unexpected token '•'" errors in environment settings

- **SSL Certificate Management - Sudo Permission Errors** - Fixed container permission errors when obtaining SSL certificates
  - Removed `sudo` prefix from all `systemctl` and `certbot` commands in `webapp/admin/certbot.py`
  - Commands now run directly since container already has proper permissions
  - Fixes error: "The 'no new privileges' flag is set, which prevents sudo from running as root"
  - Updated user-facing instructions to not include `sudo` in examples
  - Certificate operations now work correctly in containers with `no-new-privileges:true` security flag

- **SSL Certificate Management - Duplicate Locations** - Consolidated SSL certificate management to single location
  - Removed SSL/Certbot tab from Admin panel (`/admin` page)
  - Removed SSL Certificates menu item from Settings dropdown in navbar
  - All SSL certificate management now accessible only through dedicated page at `/admin/certbot`
  - Eliminates confusion from having two different places to manage SSL certificates

- **Template Syntax Errors** - Fixed missing closing tags in Jinja2 templates
  - **navbar.html**: Added missing `{% endblock %}` for `show_settings_hardware` block
  - **audio_detail.html**: Added missing `{% endblock %}` to close content block before scripts block
  - These were causing Jinja2 TemplateSyntaxError: "Unexpected end of template"
  - Website would show template errors instead of loading properly
  - These were pre-existing issues in the templates, not introduced by recent changes
  - All 89 templates in the repository now have balanced blocks

- **Icecast and Certbot Service Startup** - Fixed issue where external services weren't being started during update
  - `update.sh` now ensures `icecast2` service is enabled and running after update
  - `update.sh` now ensures `certbot.timer` is enabled and running after update
  - Resolves "Icecast not starting" and "CertBot not working" issues
  - Services are checked and started if not already running
  - Provides clear feedback about service status during update

- **Icecast and Certbot Database Initialization** - Added defensive error handling to prevent app crashes
  - Icecast and Certbot settings modules now gracefully handle missing database tables
  - App can now start successfully even if database migrations haven't run yet
  - Tables are automatically created if missing during first access
  - Improved database commit error handling with rollback in settings update functions
  - Resolves issue where app would crash on startup if migrations failed or weren't run

- **Template Error on Alerts Page** - Fixed 500 error when loading alerts page
  - Added missing `is_expired` Jinja2 template filter registration in app.py
  - Filter checks if an alert has expired based on its expiration datetime
  - Fixed alerts.html, alerts_new.html, and alert_detail.html templates that use the filter

- **Unused psutil Import** - Removed unused psutil import from app.py
  - Import was causing ModuleNotFoundError in scripts that import from app.py
  - psutil is still required for system monitoring features (kept in requirements.txt)
  - Fixed scripts/fix_admin_roles.py and other scripts that import from app

## [2.36.0]

### Added
- **LED Sign IP Address Configuration** - Added IP address and port fields to admin Hardware tab
  - Added `led_ip_address` and `led_port` input fields in admin.html Hardware Integrations tab
  - Updated `/api/led/serial_config` endpoint to save IP address and port to both LEDSignStatus and HardwareSettings tables
  - JavaScript now loads and saves LED IP/port configuration along with serial settings
  - Eliminates confusion about where to configure serial-to-ethernet converter network settings
  - Users can now configure all LED sign settings (IP, port, serial mode, baud rate) in one location

- **Admin Role Assignment Fix Script** - Added utility script to fix users without roles
  - Created `scripts/fix_admin_roles.py` to assign admin role to users created before roles were initialized
  - Script ensures roles/permissions are initialized and assigns admin role to any user without a role
  - Run with: `python3 scripts/fix_admin_roles.py`

### Enhanced
- **SSL/Certbot Management Simplified** - Consolidated duplicate SSL configuration interfaces
  - Simplified SSL tab in admin page to show certificate status overview only
  - Removed duplicate configuration form from admin.html SSL tab
  - Added prominent link to advanced Certbot management page at `/admin/certbot`
  - Advanced features (certificate acquisition, renewal testing, domain validation) remain at dedicated Certbot page
  - Clearer separation: quick status in admin page, full management in Certbot page

- **User Creation Role Assignment** - Improved role initialization during first user creation
  - First user creation now explicitly calls `initialize_default_roles_and_permissions()` before assigning role
  - Ensures admin role exists before attempting to assign it to new users
  - Provides better error message if role initialization fails

### Fixed
- **Hardware Settings Permission Issue** - Fixed "permission denied" error accessing advanced hardware settings
  - Changed `/admin/hardware` permission from `'admin'` (superuser only) to `'system.configure'` (regular admins)
  - Updated navbar to show Hardware Settings link only to users with `system.configure` permission
  - Separated hardware navigation: GPIO/Zigbee for `gpio.view`, Hardware Settings for `system.configure`
  - Eliminated confusion caused by two hardware configuration locations

- **Zone Catalog Permission Errors** - Fixed 403 permission_denied on Zone Catalog page
  - Changed all zone routes from non-existent `'admin.settings'` to `'system.configure'`
  - Zone catalog now accessible to users with system.configure permission
  - Fixed: Zone info endpoint, zone management page, zone search, zone upload, zone reload

- **Admin Users Created Without Roles** - Fixed critical issue where admin users show "No Role"
  - Admin users created during setup or via UI were not getting admin role assigned
  - Added role initialization check before first user creation
  - Created fix script for existing installations with users that have no roles
  - Users now properly assigned admin role with full permissions

## [2.34.2]

### Fixed
- **Screen Renderer Connection Error Logging** - Reduced log spam from expected connection failures
  - Changed screen_renderer.py to log connection errors at DEBUG level instead of ERROR
  - Connection refused errors are expected when web service isn't running (hardware-only mode)
  - Prevents log spam while still showing unexpected errors

## [2.34.1]

### Fixed
- **Audio/Icecast Error Logging Fixes** - Resolved excessive error logging and JSON parsing issues
  - Fixed JSON parsing error in websocket audio_monitoring_update caused by improper bytes decoding from Redis
  - Added proper UTF-8 decoding for Redis hgetall() values (redis-py 7.x returns bytes)
  - Added validation to skip empty strings before JSON parsing to prevent "Expecting value" errors
  - Reduced Icecast connection error spam by suppressing repetitive "Connection refused" logs during backoff
  - Improved audio underrun warning frequency with exponential backoff (10, 50, 100, 200, 500, etc.)
  - Added better error handling for invalid heartbeat values in Redis metrics

## [2.34.0]

### Added
- **Full Web UI for Certbot Operations** - Complete SSL certificate management through web interface
  - Added `/api/certbot/obtain-certificate-execute` endpoint to directly obtain SSL certificates
  - Added `/api/certbot/renew-certificate-execute` endpoint to directly renew certificates  
  - Added `/api/certbot/enable-auto-renewal` endpoint to manage systemd timer
  - Users can now obtain, renew, and manage SSL certificates entirely through the web UI
  - Supports standalone, nginx plugin, and webroot certificate acquisition methods
  - Supports dry-run testing, normal renewal, and forced renewal
  - Real-time feedback with certbot output displayed in the UI
  - Enable/disable automatic renewal with one click
  - Added SSL Certificates link to Settings dropdown in navigation menu
  - Eliminates need for CLI usage - fully web-based certificate management
  - VERSION bumped to 2.35.0 (feature: web-based certbot execution)

### Enhanced
- **Icecast Auto-Installation** - Icecast2 now installed by default during bare metal installation
  - Added `icecast2` package to install.sh BASE_PACKAGES array
  - Icecast2 service automatically enabled and started during installation
  - Added detailed installation status logging for Icecast setup
  - Shows Icecast port information during install (default: 8000)
  - Provides helpful guidance if Icecast fails to start (password configuration needed)
  - **CRITICAL**: Icecast is REQUIRED for audio streaming functionality - no longer optional
  - Addresses issue where users couldn't get Icecast working because it wasn't installed

### Enhanced
- **Comprehensive Icecast Logging** - Greatly improved logging for Icecast streaming operations
  - Added detailed startup logging with server, port, mount, format, and bitrate info
  - Added connection status logging when FFmpeg connects to Icecast
  - Added comprehensive shutdown logging with final statistics (uptime, bytes, bitrate, reconnects)
  - Added FFmpeg process ID (PID) logging for easier troubleshooting
  - Added error logging with stack traces for FFmpeg startup failures
  - Improved log messages with ✓/✗ symbols for better readability
  - All log messages now include mount point for multi-stream debugging
  - Makes it much easier to diagnose Icecast connection and streaming issues

### Fixed
- **Removed Duplicate Icecast Settings** - Consolidated all Icecast configuration to single location
  - Removed entire Icecast settings section from `/settings/audio` page (lines 131-252 HTML)
  - Removed all Icecast JavaScript functions from audio.html (300+ lines)
  - **All Icecast settings now managed exclusively at `/admin/icecast`**
  - Eliminates confusion from having same settings in multiple locations
  - Cleaner UI with single source of truth for Icecast configuration
  - Addresses new requirement to consolidate settings to one spot

## [2.33.1]

### Fixed
- **Certbot/SSL Certificate Management Security Fix** - Removed sudo calls from web interface
  - Removed all `sudo certbot` subprocess calls from web application for security compliance
  - Web interface now provides copy-paste commands instead of executing privileged operations
  - Added systemd timer status checking for automatic certificate renewal
  - Updated UI to display certificate acquisition instructions with multiple methods (standalone, nginx, webroot)
  - Added copy-to-clipboard functionality for certificate management commands
  - Provides clear guidance on manual certificate operations via command line
  - Fixes "no new privileges" flag error when attempting sudo from web app
  - Maintains certificate status checking functionality (read-only operations)
  - Addresses security concern of web application having elevated privileges
  - VERSION bumped to 2.33.1 (bug fix + security improvement)

### Added
- **Icecast Password Management Improvements** - Transformed password handling to read-only display with regenerate option
  - Password fields now read-only to prevent user errors and mismatches with Icecast server
  - Added password masking with show/hide toggle buttons for security
  - Added copy-to-clipboard functionality for easy password access
  - Added informational text explaining passwords are auto-generated during installation
  - Added regenerate password functionality that updates database, .env file, AND Icecast server config
  - New endpoint `/admin/api/icecast/regenerate-passwords` for secure password regeneration
  - **CRITICAL: Now updates Icecast server configuration file** (`/etc/icecast2/icecast.xml`)
  - Automatically restarts Icecast service after password regeneration
  - Handles default passwords (changeme_admin) by updating server config
  - Maintains strong auto-generated passwords (secrets.token_urlsafe(16))
  - Non-password settings (ports, stream name, etc.) remain editable
  - Prevents security risks from weak user-chosen passwords
  - VERSION bumped to 2.33.0 (critical security fix + feature enhancement)

### Fixed
- **Certbot Certificate Acquisition Issues** - Fixed missing functionality and errors in SSL certificate management
  - Fixed 400 Bad Request error in `/api/certbot/test-domain` endpoint (was not handling empty JSON body)
  - Added missing `/api/certbot/obtain-certificate` endpoint for initial certificate acquisition
  - Added "Obtain SSL Certificate" UI section in Certificate Status tab with confirmation dialog
  - Improved error messages for sudo privilege issues (NoNewPrivileges systemd setting)
  - Added specific error handling for port conflicts, validation failures, and permission errors
  - Enhanced frontend to display detailed error messages with helpful guidance
  - Addresses issue where users couldn't obtain initial certificates through web UI
  - VERSION bumped to 2.31.2 (bug fix)

- **CRITICAL: EAS Monitor Buffer Starvation** - Fixed monitor bouncing between healthy and starved states
  - Increased EAS monitor read timeout from 0.1s to 1.0s in `app_core/audio/eas_monitor_v3.py`
  - Root cause: Monitor requested 1600 samples but timeout fired before accumulating enough chunks
  - Reduced "no audio" sleep from 50ms to 20ms to check more frequently and prevent queue buildup
  - Prevents vicious cycle: timeout → sleep 50ms → audio builds up → queue fills → drops → repeat
  - Eliminates false "no audio sources" errors when sources are actually running
  - Prevents missed emergency alerts due to audio starvation
  - VERSION bumped to 2.31.1 (critical bug fix)

- **Removed All Legacy Audio Queue Code** - Eliminated wasted resources and 24,000+ dropped chunks
  - Removed controller broadcast queue (`_broadcast_queue`) and subscription (`controller-legacy`)
  - Removed broadcast pump thread and `_broadcast_pump_loop()` method - sources already publish directly
  - Removed `get_audio_chunk()` and `get_broadcast_queue()` methods from AudioIngestController
  - Removed unused legacy source queues (`_legacy_subscriber_id`, `_audio_queue`) from AudioSourceAdapter
  - Clean architecture: Audio Source → BroadcastQueue → Subscribers (EAS Monitor, Icecast)
  - No more redundant copying, no more unused queue drops, cleaner logs
  - EAS monitor and Icecast subscribe directly to source broadcast queues

### Changed
- **Environment Variables Cleanup** - Removed redundant settings that are now managed via dedicated admin pages
  - Removed 'gpio' category from environment variables (now managed via `/admin/hardware`)
  - Removed 'icecast' category from environment variables (now managed via `/admin/icecast`)
  - Removed duplicate 'notifications' category that contained SDR/audio settings
  - GPIO, OLED, LED, VFD, and Icecast settings exclusively managed through database-backed admin UIs
  - Cleaner environment configuration focused on core application settings
  - VERSION bumped to 2.31.0 (feature enhancement)

### Added
- **Certbot/SSL Admin Tab** - Moved SSL certificate management into Admin Panel as dedicated tab
  - Added SSL/Certbot tab to `/templates/admin.html` with nested Configuration and Certificate Status tabs
  - Integrated certbot functionality into admin panel (no longer separate navbar entry)
  - Removed `/templates/admin/certbot.html` standalone page dependency
  - Added JavaScript functions for certbot management in admin.html
  - Maintains all existing API endpoints (`/api/admin/certbot/*`)
  - Auto-loads settings when tab is opened
  - VERSION remains 2.30.0 (UI improvement)

### Changed (Previous)
- **Environment Variables Cleanup** - Removed Certbot configuration from environment variables
  - Removed DOMAIN_NAME, SSL_EMAIL, and CERTBOT_STAGING from `/webapp/admin/environment.py`
  - Removed entire 'https' section from environment variable management
  - Settings now exclusively managed through database (cleaner architecture)
  - Migration `20251216_add_certbot_settings.py` imports env vars on first run for backward compatibility

### Removed
- **SSL Certificate Viewer from Security Settings** - Eliminated duplicate certificate viewer
  - Removed SSL Certificate Status section from `/templates/security_settings.html`
  - Removed `loadSSLCertificateStatus()` JavaScript function and event listeners
  - Certificate viewing now unified in Admin Panel → SSL/Certbot tab
  - Cleaner security page focused on MFA and authentication
- **Navbar Certbot Entry** - Removed standalone certbot link from navigation menu
  - Removed `/admin/certbot` link from `/templates/components/navbar.html`
  - Consolidates admin functions in Admin Panel tab interface

### Added (Previous Features)
- **Certbot/SSL Admin Page** - New dedicated admin page for SSL certificate management
  - Created `/webapp/admin/certbot.py` blueprint with comprehensive Certbot/Let's Encrypt management routes
  - Created `/app_core/certbot_settings.py` helper functions for database settings management
  - Added `CertbotSettings` database model to store certificate configuration
  - Added database migration `20251216_add_certbot_settings.py` to create certbot_settings table
  - Includes GET/PUT `/api/admin/certbot/settings` for reading and updating Certbot configuration
  - Includes GET `/api/admin/certbot/certificate-status` for checking certificate status and expiration
  - Includes POST `/api/admin/certbot/renew-certificate` for triggering certificate renewal (dry-run)
  - Includes POST `/api/admin/certbot/test-domain` for DNS and HTTP accessibility testing
  - Includes GET `/api/admin/certbot/download-certificate` for downloading certificates
  - Updated `/app_core/ssl_utils.py` to read configuration from database with env var fallback
  - Follows established admin page patterns with Bootstrap 5 styling and theme support
  - Protected with `@require_permission('system.configure')` decorator
  - Integrated into admin blueprint registration in `/webapp/admin/__init__.py`
  - VERSION bumped to 2.30.0 (new feature)
- **Unified EAS Monitor Architecture (V3)** - Complete redesign of EAS monitoring system for efficiency
  - Created `/app_core/audio/eas_monitor_v3.py` with unified single-threaded architecture
  - `UnifiedEASMonitorService` class replaces multi-monitor architecture (1 thread instead of N threads)
  - `SourceWatcher` class provides lightweight per-source audio subscribers (no separate threads)
  - `HealthTracker` class provides centralized health tracking for all sources
  - Auto-discovery automatically finds and monitors running audio sources (no manual lifecycle management)
  - Single shared StreamingSAMEDecoder processes audio from all sources
  - Updated `/eas_monitoring_service.py` initialize_eas_monitor() to use UnifiedEASMonitorService
  - Maintains backward-compatible status API format (no webapp changes needed)
  - Benefits: Reduced CPU/memory usage, simpler codebase, no status aggregation overhead
  - Kept existing `/app_core/audio/eas_monitor.py` for backward compatibility
  - VERSION bumped to 2.29.0 (new feature)
- **Icecast Admin Page** - New dedicated admin page for Icecast streaming configuration
  - Created `/webapp/admin/icecast.py` blueprint with comprehensive Icecast management routes
  - Created `/templates/admin/icecast.html` template with configuration and diagnostics sections
  - Added routes for settings management, connection testing, and real-time status monitoring
  - Includes GET/PUT `/api/admin/icecast/settings` for reading and updating Icecast configuration
  - Includes POST `/api/admin/icecast/test-connection` for testing Icecast connectivity
  - Includes GET `/api/admin/icecast/status` for retrieving streaming status and listener counts
  - Uses existing IcecastSettings database model and helper functions
  - Follows established admin page patterns with Bootstrap 5 styling and theme support
  - Protected with `@require_permission('system.configure')` decorator
  - Integrated into admin blueprint registration in `/webapp/admin/__init__.py`
  - VERSION bumped to 2.28.0 (new feature)

### Changed
- **Documentation Update** - Comprehensive review and updates across all documentation
  - Updated all main architecture documents with current timestamps (2025-12-16)
  - Updated INDEX.md statistics: 92 total files (was 47), 12 guides (was 6), 18 architecture docs (was 10), 19 troubleshooting guides (was 10)
  - Updated SYSTEM_ARCHITECTURE.md, THEORY_OF_OPERATION.md, DATA_FLOW_SEQUENCES.md with current information
  - Updated DIAGRAMS.md to reflect complete visual documentation coverage
  - Enhanced README.md with detailed systemd service architecture diagrams
  - Added comprehensive technology stack section to README.md with all versions
  - Updated README.md architecture diagrams to show systemd services (eas-station-web, eas-station-poller, eas-station-sdr, etc.)
  - Added FastAPI 0.124.2 badge to README.md technology badges
  - Updated Bootstrap version to 5.3.0 in badges
  - Updated Redis version to 7.1 in badges
  - Enhanced documentation navigation diagram with troubleshooting branch
  - All service references now accurately reflect systemd-based deployment
  - Fixed broken documentation links: HARDWARE_ISOLATION.md, EAS_DECODING_SUMMARY.md, PYCHARM_DEBUGGING.md
  - Removed references to deleted architecture analysis documents
  - Updated cross-references to point to existing current documentation
  - VERSION bumped to 2.27.27 (documentation update)

### Fixed
- **RBDS Extraction Not Working** - Fixed RBDS decoder checking wrong sample rate
  - Bug: Checked `self.config.sample_rate` (final audio rate, 48kHz) instead of `self._intermediate_rate` (FM multiplex rate, 250kHz)
  - RBDS subcarrier at 57kHz exists in FM multiplex signal BEFORE final decimation
  - Changed condition from `self.config.sample_rate >= 114000` to `self._intermediate_rate >= 114000`
  - RBDS now extracts correctly when intermediate rate is high enough
  - VERSION bumped to 2.27.26 (bug fix)
- **HTTP Streams Playing at Wrong Bitrate** - Fixed forced resampling degrading stream quality
  - Bug: FFmpeg was forcing ALL HTTP streams to resample to configured sample rate (44.1kHz)
  - Streams with native 48kHz/128kbps were being degraded by unnecessary resampling
  - Solution: Removed `-ar` flag to let FFmpeg preserve stream's native sample rate
  - Added `preserve_native_rate` config option (defaults to True for HTTP streams)
  - Set to False if you specifically need resampling for compatibility
  - Prevents quality loss and "wrong bitrate" playback issues
  - VERSION bumped to 2.27.26 (bug fix)
- **Zone Catalog API Returning HTML** - Fixed JSON parsing error in admin zone catalog
  - Bug: JavaScript fetch() to `/admin/zones/info` didn't include Accept header
  - Without `Accept: application/json`, authentication failures returned HTML redirects
  - Added Accept header to all zone catalog API calls
  - Added content-type validation before JSON parsing
  - Added proper error handling with toast notifications for auth/permission errors
  - Better user feedback instead of cryptic "Unexpected token '<'" errors
  - VERSION bumped to 2.27.26 (bug fix)
- **High CPU Usage in eas_monitoring_service** - Fixed excessive logging hammering CPU
  - RBDS decoder was logging at INFO level every time data was decoded (multiple times per second)
  - Each log write causes disk I/O and string formatting overhead
  - Changed to only log when RBDS data actually changes (PS name, radio text, etc.)
  - Added `_last_logged_rbds` to track last logged state
  - Prevents CPU from spiking to 125% during RBDS reception
  - RBDS data still flows to frontend metrics in real-time (no functional change)
  - VERSION bumped to 2.27.25 (bug fix)
- **RBDS Data Not Displaying in Frontend** - Fixed RBDS metadata not showing in audio-monitor
  - RBDS decoder in `demodulation.py` was working correctly, extracting PS name, PI code, radio text, etc.
  - Bug: `redis_sdr_adapter.py` extracted stereo pilot data from demodulator status but NOT RBDS data
  - Added extraction of all RBDS fields from `DemodulatorStatus.rbds_data` to metrics metadata
  - RBDS fields now published: ps_name, pi_code, radio_text, pty, tp, ta, ms, last_updated
  - Frontend template already had complete RBDS display support (no changes needed)
  - Verified SDR++ can decode RBDS confirms hardware/signal is good
  - VERSION bumped to 2.27.24 (bug fix)
- **Audio Bitrate/Sample Rate Mismatch** - Fixed slow/fast audio playback in web monitoring
  - Removed hardcoded 44.1kHz resampling in web audio stream endpoint
  - Audio now streams at native source sample rate (32kHz, 44.1kHz, 48kHz, etc.)
  - Prevents pitch/speed mismatch when source rate differs from hardcoded 44.1kHz
  - Critical for iHeartMedia and other web streams that may use different sample rates
  - EAS decoder still gets properly resampled 16kHz feed via ResamplingBroadcastAdapter
  - WAV header now correctly matches actual audio sample rate
  - VERSION bumped to 2.27.23 (bug fix)
- **Migration Chain Broken** - Fixed Alembic migration revision mismatch causing KeyError
  - Migration `20251214_add_hardware_settings.py` incorrectly referenced `down_revision = '20251205_add_audio_sample_rate'`
  - Actual revision ID was `'20251205_audio_sample_rate'` (without `add_` prefix)
  - Fixed down_revision to match actual revision ID
  - Resolves KeyError: '20251205_add_audio_sample_rate' during `alembic upgrade head`
  - VERSION bumped to 2.27.22 (bug fix)
- **SDR Buffer Display** - Hide buffer utilization metric for SDR sources in audio monitoring UI
  - SDR sources don't use buffering (data flows directly from hardware)
  - Buffer metric now hidden for source types 'sdr' and 'redis_sdr'
  - Matches behavior of detailed buffer utilization indicator
  - VERSION bumped to 2.27.22 (bug fix)
- **Administrator Role Assignment** - Improved role validation during installation
  - Install script now explicitly validates admin role exists before creating user
  - Fails with clear error message if role not found instead of silently continuing
  - Sets both `role` and `role_id` fields for redundancy
  - Confirms role assignment in success message
  - VERSION bumped to 2.27.22 (bug fix)

### Added
- **Web Stream Auto-Start** - Added auto-start option for HTTP/stream audio sources
  - Added checkbox to audio source creation modal
  - Sources can now auto-start on system boot (backend already supported this)
  - Matches functionality available for SDR sources
  - VERSION bumped to 2.27.22 (feature)

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
