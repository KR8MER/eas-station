# EAS Station - Function Tree & Architecture Reference

**Last Updated:** 2025-11-06  
**System Version:** 2.1.9  
**Document Purpose:** Comprehensive catalog of all major modules, classes, functions, and API endpoints for developer reference

---

## Table of Contents

1. [Core Models & Data Layer](#core-models--data-layer)
2. [Authentication & RBAC](#authentication--rbac)
3. [Audio System](#audio-system)
4. [Radio Management](#radio-management)
5. [EAS/SAME Processing](#eassame-processing)
6. [GPIO & Relay Control](#gpio--relay-control)
7. [Web API Routes](#web-api-routes)
8. [Admin Interface Routes](#admin-interface-routes)
9. [Utilities & Helpers](#utilities--helpers)
10. [Analytics & Monitoring](#analytics--monitoring)
11. [LED/VFD Display Control](#ledvfd-display-control)

---

## Core Models & Data Layer

### Location: `/home/user/eas-station/app_core/models.py`

**Database Models:**

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `NWSZone` | NOAA public forecast zone reference | `__repr__` | 58 |
| `Boundary` | Geographic boundaries for alert coverage | - | 81 |
| `CAPAlert` | CAP alert records from NOAA | `__setattr__` (source normalization) | 97 |
| `SystemLog` | Audit/system logging | - | 132 |
| `AdminUser` | User accounts with auth | `set_password`, `check_password`, `to_safe_dict`, `is_authenticated` (property) | 143 |
| `EASMessage` | Encoded EAS broadcast messages | `to_dict` | 212 |
| `EASDecodedAudio` | Decoded EAS audio analysis results | `to_dict` | 254 |
| `ManualEASActivation` | Manual EAS broadcast records | `to_dict` | 287 |
| `AlertDeliveryReport` | Compliance delivery reports | `to_dict` | 352 |
| `Intersection` | Alert-to-boundary spatial intersections | - | 396 |
| `PollHistory` | CAP fetch/polling history | - | 412 |
| `PollDebugRecord` | Detailed poll debug information | - | 426 |
| `LocationSettings` | Station location & timezone config | `to_dict` | 458 |
| `RadioReceiver` | SDR hardware configuration | `to_receiver_config`, `latest_status` | 536 |
| `RadioReceiverStatus` | Historical SDR status samples | `to_receiver_status` | 607 |
| `LEDMessage` | LED sign message records | - | 657 |
| `LEDSignStatus` | LED sign hardware status | - | 677 |
| `VFDDisplay` | VFD display content & state | - | 691 |
| `VFDStatus` | VFD hardware status tracking | - | 710 |
| `AudioSourceMetrics` | Real-time audio metering | - | 725 |
| `AudioHealthStatus` | Audio system health snapshots | - | 757 |
| `AudioAlert` | Audio system alert records | - | 791 |
| `AudioSourceConfigDB` | Persistent audio source configs | `to_dict` | 830 |
| `GPIOActivationLog` | GPIO relay audit trail | `to_dict` | 869 |
| `DisplayScreen` | Custom LED/VFD screen templates | `to_dict` | 922 |
| `ScreenRotation` | Screen rotation schedule configs | `to_dict` | 981 |

**Supporting Functions:**

- `_spatial_backend_supports_geometry()` (24) - Detect PostgreSQL for spatial features
- `_geometry_type(geometry_type: str)` (40) - Type factory for geometry columns
- `_log_warning(message: str)` (51) - App context-aware logging

---

## Authentication & RBAC

### Location: `/home/user/eas-station/app_core/auth/roles.py`

**RBAC Models:**

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `Role` | User role with permissions | `has_permission`, `get_permission_names`, `to_dict` | 30 |
| `Permission` | Permission that can be assigned to roles | `to_dict` | 65 |
| `RoleDefinition` (Enum) | Predefined role names (ADMIN, OPERATOR, VIEWER) | - | 93 |
| `PermissionDefinition` (Enum) | All permission names by resource.action format | - | 100 |

**RBAC Functions:**

| Function | Purpose | Parameters | Line |
|----------|---------|-----------|------|
| `get_current_user()` | Retrieve user from session | none | 201 |
| `has_permission(permission_name, user=None)` | Check user permission | permission_name, user | 210 |
| `require_permission(permission_name)` | Route decorator for single permission | permission_name | 235 |
| `require_any_permission(*permission_names)` | Route decorator for ANY permission | permission_names | 261 |
| `require_all_permissions(*permission_names)` | Route decorator for ALL permissions | permission_names | 289 |
| `initialize_default_roles_and_permissions()` | Bootstrap RBAC system | none | 317 |

**Default Roles & Permissions (Line 140-198):**
- **ADMIN**: Full access to all resources
- **OPERATOR**: Can manage alerts and EAS, view system config
- **VIEWER**: Read-only access to most resources

---

### Location: `/home/user/eas-station/app_core/auth/mfa.py`

**MFA Functions:**
- TOTP enrollment and verification
- Backup code generation and validation

---

## Audio System

### Location: `/home/user/eas-station/app_core/audio/`

#### **ingest.py** - Audio Source Abstraction

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `AudioSourceType` (Enum) | Source types: SDR, ALSA, PULSE, FILE, STREAM | - | 26 |
| `AudioSourceStatus` (Enum) | Status: IDLE, RUNNING, ERROR, PAUSED | - | 35 |
| `AudioMetrics` | Audio capture metrics | - | 45 |
| `AudioSourceConfig` | Configuration container | - | 58 |
| `AudioSourceAdapter` (ABC) | Base class for all sources | `start`, `stop`, `read_audio`, `get_metrics`, `get_status` | 76 |
| `AudioIngestController` | Central audio ingestion manager | `create_source`, `remove_source`, `start_source`, `stop_source`, `get_source_status`, `list_sources` | 246 |

#### **sources.py** - Concrete Audio Source Implementations

| Class | Purpose | Line |
|-------|---------|------|
| `SDRSourceAdapter` | SDR radio receiver input | 52 |
| `ALSASourceAdapter` | ALSA device input | 122 |
| `PulseSourceAdapter` | PulseAudio input | 183 |
| `FileSourceAdapter` | File-based input (WAV, MP3) | 254 |
| `StreamSourceAdapter` | HTTP/M3U stream input | 386 |
| `create_audio_source(config)` | Factory function | 652 |

#### **metering.py** - Audio Analysis & Health Monitoring

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `AlertLevel` (Enum) | Alert severity: INFO, WARNING, ERROR, CRITICAL | - | 22 |
| `AudioAlert` | Alert record | - | 31 |
| `AudioMeter` | Real-time audio level metering | `analyze_chunk`, `check_clipping`, `get_metrics` | 41 |
| `SilenceDetector` | Silence detection & tracking | `detect_silence`, `is_silenced`, `reset` | 128 |
| `AudioHealthMonitor` | Overall health monitoring | `update_metrics`, `check_health`, `generate_alerts` | 276 |

#### **output_service.py** - Audio Output/Playback

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `PlayoutStatus` (Enum) | Status: IDLE, PLAYING, PAUSED, ERROR | - | 24 |
| `PlayoutEvent` | Playback event record | - | 34 |
| `AudioOutputService` | Audio playback management | `queue_audio`, `play`, `pause`, `stop`, `get_status` | 57 |

#### **playout_queue.py** - Audio Queue Management

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `PrecedenceLevel` (Enum) | Priority: 0=CRITICAL to 3=LOW | - | 28 |
| `SeverityLevel` (Enum) | Alert severity ratings | - | 43 |
| `UrgencyLevel` (Enum) | Alert urgency levels | - | 52 |
| `PlayoutItem` | Queued audio item with metadata | - | 62 |
| `AudioPlayoutQueue` | FIFO audio playback queue | `enqueue`, `dequeue`, `get_queue_status`, `reorder_by_priority` | 261 |

---

## Radio Management

### Location: `/home/user/eas-station/app_core/radio/`

#### **manager.py** - Radio Receiver Manager

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `ReceiverConfig` | SDR receiver configuration | - | 17 |
| `ReceiverStatus` | Current receiver status snapshot | - | 31 |
| `ReceiverInterface` (ABC) | Abstract receiver driver interface | `start`, `stop`, `is_locked`, `get_signal_strength` | 43 |
| `RadioManager` | Central manager for all receivers | `register_driver`, `create_receiver`, `get_receiver_status`, `list_receivers`, `start_audio_capture`, `stop_audio_capture`, `get_audio_data` | 73 |

#### **drivers.py** - SDR Driver Implementations

| Class | Purpose | Line |
|-------|---------|------|
| `_SoapySDRHandle` | SoapySDR library wrapper | 14 |
| `_CaptureTicket` | Audio capture session ticket | 24 |
| `_SoapySDRReceiver` | SoapySDR-based receiver driver (RTL-SDR, Airspy) | 95 |
| `RTLSDRReceiver` | RTL-SDR specific implementation | 382 |
| `AirspyReceiver` | Airspy specific implementation | 388 |
| `register_builtin_drivers(manager)` | Register standard drivers | 394 |

#### **discovery.py** - Hardware Discovery & Enumeration

| Function | Purpose | Line |
|----------|---------|------|
| `enumerate_devices()` | List connected SDR devices | 45 |
| `get_device_capabilities(driver, device_args)` | Query device specs | 88 |
| `check_soapysdr_installation()` | Verify SoapySDR availability | 186 |
| `get_recommended_settings(driver, use_case)` | Get optimal config for use case | 238 |

#### **schema.py** - Database Schema

| Function | Purpose | Line |
|----------|---------|------|
| `ensure_radio_tables(logger)` | Create radio receiver tables | 75 |

---

## EAS/SAME Processing

### Location: `/home/user/eas-station/app_utils/`

#### **eas.py** - EAS Audio Generation & Broadcasting

**Data Classes:**

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `EASAudioGenerator` | EAS/SAME audio encoding engine | `generate`, `generate_eom_audio`, `generate_attention_tone`, `generate_silence` | 572 |
| `EASBroadcaster` | EAS broadcast orchestration | `broadcast`, `cancel_broadcast`, `get_broadcast_status` | 853 |

**Utility Functions:**

| Function | Purpose | Parameters | Line |
|----------|---------|-----------|------|
| `load_eas_config(base_path)` | Load EAS runtime configuration | base_path | 55 |
| `describe_same_header(header, lookup, state_index)` | Parse SAME header fields | header, lookup, state_index | 186 |
| `build_same_header(alert, payload, config, ...)` | Construct SAME header from alert | alert, payload, config, ... | 387 |
| `build_eom_header(config)` | Build end-of-message header | config | 461 |
| `manual_default_same_codes()` | Get default SAME codes for manual activations | none | 481 |
| `samples_to_wav_bytes(samples, sample_rate)` | Convert audio samples to WAV bytes | samples, sample_rate | 549 |

**Constants:**
- `P_DIGIT_MEANINGS` (108) - SAME portion digit labels
- `ORIGINATOR_DESCRIPTIONS` (110) - EAS originator descriptions
- `PRIMARY_ORIGINATORS` (117) - Valid originator codes
- `SAME_HEADER_FIELD_DESCRIPTIONS` (120) - SAME header format documentation

#### **eas_decode.py** - EAS Audio Decoding & Analysis

**Data Classes:**

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `SAMEHeaderDetails` | Parsed SAME header fields | - | 28 |
| `SAMEAudioSegment` | Individual audio segment | - | 227 |
| `SAMEAudioDecodeResult` | Complete decode analysis | - | 266 |
| `AudioDecodeError` | Decode exception | - | 23 |

**Decoding Functions:**

| Function | Purpose | Line |
|----------|---------|------|
| `decode_same_audio(path, sample_rate=None)` | Main SAME audio decoder | 1347 |
| `build_plain_language_summary(header, fields)` | Convert SAME header to plain English | 165 |
| `_detect_audio_sample_rate(path)` | Auto-detect audio sample rate | 1280 |
| `_read_audio_samples(path, sample_rate)` | Load audio file as float samples | 368 |
| `_correlate_and_decode_with_dll(samples, sample_rate)` | Correlate and decode FSK bits | 456 |
| `_extract_bits(samples, sample_rate)` | Extract FSK bits from audio | 640 |
| `_extract_bytes_from_bits(bits)` | Convert bits to bytes | 697 |
| `_bits_to_text(bits)` | Convert bytes to SAME header text | 925 |
| `_score_candidate(metadata)` | Score decode quality | 1069 |

#### **eas_fsk.py** - FSK Encoding (SAME Modulation)

| Function | Purpose | Line |
|----------|---------|------|
| `same_preamble_bits(repeats)` | Generate FSK preamble | 16 |
| `encode_same_bits(message, include_preamble)` | Encode SAME text as FSK bits | 30 |
| `generate_fsk_samples(bits, sample_rate, freq_mark, freq_space, ...)` | Generate FSK audio samples | 63 |

**Constants:**
- `SAME_BAUD` - FSK baud rate
- `SAME_MARK_FREQ` - Mark frequency (1200 Hz)
- `SAME_SPACE_FREQ` - Space frequency (2200 Hz)
- `SAME_PREAMBLE_REPETITIONS` - Number of preamble bytes

#### **eas_tts.py** - Text-to-Speech Integration

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `TTSEngine` | TTS provider wrapper | `synthesize`, `get_available_voices`, `set_voice` | 114 |

**Helper Functions:**

| Function | Purpose | Line |
|----------|---------|------|
| `_espeak_voice_from_preference(preference)` | Validate espeak voice token | 40 |
| `_normalize_pcm_samples(raw_frames, sample_width, ...)` | Convert audio to 16-bit mono | 53 |
| `_pyttsx3_dependency_hint()` | Suggest missing dependencies | 75 |
| `_pyttsx3_error_hint(exc)` | Generate friendly error message | 96 |

**Supported TTS Providers:**
- pyttsx3 (local, offline)
- Azure Cognitive Services
- Azure OpenAI
- Google Cloud TTS

---

## GPIO & Relay Control

### Location: `/home/user/eas-station/app_utils/gpio.py`

**Data Classes:**

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `GPIOState` (Enum) | Pin state: INACTIVE, ACTIVE, ERROR, WATCHDOG_TIMEOUT | - | 27 |
| `GPIOActivationType` (Enum) | Activation type: MANUAL, AUTOMATIC, TEST, OVERRIDE | - | 35 |
| `GPIOActivationEvent` | GPIO event record | `to_dict` | 44 |
| `GPIOPinConfig` | Pin configuration | - | 74 |

**GPIO Controller:**

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `GPIOController` | Unified GPIO control with audit logging | `add_pin`, `remove_pin`, `activate`, `deactivate`, `get_state`, `get_all_states`, `cleanup` | 85 |
| `GPIORelayController` | Legacy relay control (deprecated) | `activate`, `deactivate` | 533 |

**Features:**
- Debounce logic (configurable delay)
- Hold times (minimum activation duration)
- Watchdog timers (prevent stuck relays)
- Complete activation audit trail
- Thread-safe operations

---

## Web API Routes

### Location: `/home/user/eas-station/webapp/`

#### **routes_public.py** - Public & Operator Routes

| Route | Method | Purpose | Line |
|-------|--------|---------|------|
| `/` | GET | Main dashboard index | 32 |
| `/stats` | GET | System statistics page | 45 |
| `/alerts` | GET | Alert history/list page | - |
| `/boundaries` | GET | Boundary visualization | - |

#### **routes_analytics.py** - Analytics & Reporting

| Route | Purpose | Module |
|-------|---------|--------|
| `/api/analytics/*` | Analytics data endpoints | routes_analytics.py |

#### **routes_monitoring.py** - System Monitoring

| Route | Purpose | Module |
|-------|---------|--------|
| `/api/health/*` | System health status | routes_monitoring.py |
| `/api/audio-sources/*` | Audio source metrics | routes_monitoring.py |
| `/api/receivers/*` | Radio receiver status | routes_monitoring.py |

#### **routes_security.py** - User & Security Management

| Route | Method | Purpose | Line |
|-------|--------|---------|------|
| `/auth/mfa/status` | GET | Check MFA enrollment | 37 |
| `/auth/mfa/enroll/start` | POST | Begin MFA setup | 54 |
| `/auth/mfa/enroll/qr` | GET | Get QR code for MFA | 93 |
| `/auth/mfa/enroll/verify` | POST | Verify MFA setup | 123 |
| `/auth/mfa/disable` | POST | Disable MFA | 163 |
| `/api/roles` | GET | List all roles | 213 |
| `/api/roles/<role_id>` | GET | Get role details | 223 |
| `/api/roles` | POST | Create new role | 231 |
| `/api/roles/<role_id>` | PUT | Update role | 275 |
| `/api/permissions` | GET | List all permissions | 315 |
| `/api/users/<user_id>/role` | POST | Assign user to role | 325 |
| `/api/audit-logs` | GET | List audit logs | 372 |
| `/api/audit-logs/export` | GET | Export audit logs | 414 |
| `/api/rbac/init-defaults` | POST | Initialize default roles | 471 |
| `/api/rbac/check-permission` | POST | Check user permission | 485 |
| `/security/settings` | GET | Security settings page | 506 |

#### **routes_led.py** - LED Sign Routes

| Route | Purpose |
|-------|---------|
| `/api/led/status` | Current LED status |
| `/api/led/message` | Queue LED message |
| `/api/led/config` | LED configuration |

#### **routes_vfd.py** - VFD Display Routes

| Route | Purpose |
|-------|---------|
| `/api/vfd/status` | Current VFD status |
| `/api/vfd/display` | Display content on VFD |
| `/api/vfd/config` | VFD configuration |

#### **routes_screens.py** - Display Screens

| Route | Purpose |
|-------|---------|
| `/api/screens` | List all screens |
| `/api/screens/<id>` | Get/update screen |
| `/api/rotations` | List screen rotations |

#### **routes_exports.py** - Data Export

| Route | Purpose |
|-------|---------|
| `/api/export/alerts` | Export alert data |
| `/api/export/compliance` | Export compliance reports |

#### **routes_debug.py** - Debugging Routes

| Route | Purpose |
|-------|---------|
| `/api/debug/poll-history` | Poll history debug |
| `/api/debug/eas-messages` | EAS message debugging |

#### **routes/alert_verification.py** - Alert Verification

| Route | Purpose | Line |
|-------|---------|------|
| `/api/alerts/<alert_id>/verify` | Verify alert authenticity | 26 |

#### **routes/eas_compliance.py** - EAS Compliance

| Route | Purpose | Line |
|-------|---------|------|
| `/api/eas/compliance/*` | Compliance tracking endpoints | 22 |

#### **routes/system_controls.py** - System Control

| Route | Purpose | Line |
|-------|---------|------|
| `/api/system/restart` | Restart application | 23 |
| `/api/system/broadcast-test` | Test broadcast | - |

---

## Admin Interface Routes

### Location: `/home/user/eas-station/webapp/admin/`

#### **api.py** - Admin REST API

| Route | Method | Purpose | Line |
|-------|--------|---------|------|
| `/api/alerts/<alert_id>/geometry` | GET | Alert geometry & boundaries | 52 |
| `/api/alerts/<alert_id>` | GET | Alert details | - |
| `/api/boundaries` | GET | List boundaries | - |
| `/api/system/health` | GET | System health snapshot | - |
| `/api/system/cpu-usage` | GET | CPU usage percent | - |
| `/api/system/memory` | GET | Memory usage | - |
| `/api/system/disk` | GET | Disk usage | - |

**Helper Functions:**

| Function | Purpose | Line |
|----------|---------|------|
| `_get_cpu_usage_percent()` | Get recent CPU sample | 34 |
| `register_api_routes(app, logger)` | Register all API endpoints | 49 |

#### **auth.py** - Authentication Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/login` | GET,POST | User login |
| `/logout` | GET | User logout |
| `/admin/users` | GET,POST | Manage users |
| `/admin/users/<user_id>` | GET,PUT,DELETE | User operations |

#### **boundaries.py** - Boundary Management

| Route | Purpose |
|-------|---------|
| `/admin/boundaries` | Browse boundaries |
| `/admin/boundaries/import` | Import boundary data |
| `/api/boundaries` | List/query boundaries |
| `/api/boundaries/<id>` | Boundary details |

**Helper Functions:**

| Function | Purpose | Line |
|----------|---------|------|
| `ensure_alert_source_columns(logger)` | Schema migration helper | 31 |
| `ensure_boundary_geometry_column(logger)` | Add geometry column if needed | 102 |
| `extract_feature_metadata(feature)` | Parse GeoJSON feature | 153 |
| `register_boundary_routes(app, logger)` | Register boundary routes | 242 |

#### **maintenance.py** - System Maintenance & Imports

| Route | Purpose | Line |
|-------|---------|------|
| `/admin/maintenance` | Maintenance dashboard | - |
| `/api/maintenance/backup` | Backup operations | - |
| `/api/maintenance/upgrade` | System upgrade | - |
| `/api/alerts/import-noaa` | Import from NOAA API | - |
| `/api/alerts/import-manual` | Manual alert import | - |

**Helper Functions:**

| Function | Purpose | Line |
|----------|---------|------|
| `normalize_manual_import_datetime(value)` | Parse import datetime | 212 |
| `format_noaa_timestamp(dt_value)` | Format NOAA timestamp | 235 |
| `build_noaa_alert_request(...)` | Build NOAA API request | 243 |
| `retrieve_noaa_alerts(...)` | Fetch from NOAA API | 325 |
| `serialize_admin_alert(alert)` | Convert alert to JSON | 299 |
| `_start_background_operation(name, command)` | Run background task | 125 |
| `register_maintenance_routes(app, logger)` | Register routes | 439 |

#### **dashboard.py** - Admin Dashboard

| Route | Purpose | Line |
|-------|---------|------|
| `/admin` | Admin home page | - |
| `/admin/dashboard` | Main dashboard | 30 |

#### **environment.py** - Environment Configuration

| Route | Purpose |
|-------|---------|
| `/admin/environment` | Environment variable editor |
| `/api/environment` | Get/update environment |

**Helper Functions:**

| Function | Purpose | Line |
|----------|---------|------|
| `get_env_file_path()` | Locate .env file | 586 |
| `read_env_file()` | Parse environment variables | 595 |
| `write_env_file(env_vars)` | Save environment variables | 627 |
| `register_environment_routes(app, logger)` | Register routes | 669 |

#### **audio.py** - Audio Configuration Routes

| Route | Purpose | Line |
|-------|---------|------|
| `/admin/audio` | Audio configuration page | 49 |
| `/api/audio/sources` | List audio sources | - |

#### **audio_ingest.py** - Audio Ingestion Control

| Route | Purpose | Line |
|-------|---------|------|
| `/api/audio-ingest/sources` | List audio ingestion sources | 145 |
| `/api/audio-ingest/sources/<name>/start` | Start audio capture | - |
| `/api/audio-ingest/sources/<name>/stop` | Stop audio capture | - |
| `/api/audio-ingest/metrics` | Get metering data | - |

**Helper Functions:**

| Function | Purpose | Line |
|----------|---------|------|
| `_get_audio_controller()` | Get audio ingestion controller | 24 |
| `_initialize_audio_sources(controller)` | Setup configured sources | 33 |
| `_serialize_audio_source(source_name, adapter)` | Convert source to JSON | 107 |
| `register_audio_ingest_routes(app, logger_instance)` | Register routes | 145 |

#### **coverage.py** - Alert Coverage Analysis

| Function | Purpose | Line |
|----------|---------|------|
| `calculate_coverage_percentages(alert_id, intersections)` | Calculate coverage stats | 14 |

#### **intersections.py** - Intersection Management

| Route | Purpose | Line |
|-------|---------|------|
| `/api/intersections` | List intersections | 16 |

---

## Utilities & Helpers

### Location: `/home/user/eas-station/app_utils/`

#### **alert_sources.py** - Alert Source Management

| Function | Purpose | Line |
|----------|---------|------|
| `normalize_alert_source(value)` | Normalize source identifier | 21 |
| `summarise_sources(values)` | Summarize multiple sources | 40 |
| `expand_source_summary(summary)` | Expand summary back to set | 50 |

#### **event_codes.py** - EAS Event Code Utilities

| Constant | Purpose | Line |
|----------|---------|------|
| `EVENT_CODE_REGISTRY` | Complete event code database | - |

| Function | Purpose | Line |
|----------|---------|------|
| `normalise_event_code(value)` | Normalize event code | 87 |
| `resolve_event_code_from_name(name)` | Look up code by name | 107 |
| `resolve_event_code(event_name, candidates)` | Resolve best matching code | 113 |
| `describe_event_code(code)` | Get event description | 126 |
| `normalise_event_tokens(values)` | Normalize event name tokens | 133 |
| `format_event_code_list(codes)` | Format codes for display | 159 |

#### **fips_codes.py** - FIPS/SAME Code Database

| Function | Purpose | Line |
|----------|---------|------|
| `get_us_state_county_tree()` | Get state/county hierarchy | 3451 |
| `get_same_lookup()` | Get FIPS-to-display lookup | 3471 |
| `_build_county_index()` | Build county name index | 3342 |
| `_build_state_tree()` | Build state/county tree | 3368 |

#### **formatting.py** - Output Formatting

| Function | Purpose | Line |
|----------|---------|------|
| `format_bytes(bytes_value)` | Format bytes as human-readable | 8 |
| `format_uptime(seconds)` | Format uptime duration | 24 |

#### **time.py** - Timezone & DateTime Utilities

| Function | Purpose | Line |
|----------|---------|------|
| `get_location_timezone()` | Get configured timezone | 19 |
| `get_location_timezone_name()` | Get timezone name | 25 |
| `set_location_timezone(tz_name)` | Set timezone | 32 |
| `utc_now()` | Current UTC time | 52 |
| `local_now()` | Current local time | 58 |
| `parse_nws_datetime(dt_string, logger)` | Parse NWS datetime format | 64 |
| `format_local_datetime(dt, include_utc)` | Format datetime for display | 118 |
| `format_local_date(dt)` | Format date only | 137 |
| `format_local_time(dt)` | Format time only | 151 |
| `is_alert_expired(expires_dt)` | Check if alert expired | 165 |

#### **versioning.py** - Version Management

| Function | Purpose | Line |
|----------|---------|------|
| `get_current_version()` | Get system version | 15 |

#### **zone_catalog.py** - NWS Zone Catalog

| Class | Purpose | Line |
|-------|---------|------|
| `ZoneRecord` | NWS zone data | 15 |
| `CountySubdivisionRecord` | County subdivision record | 38 |
| `ZoneSyncResult` | Sync operation result | 55 |

| Function | Purpose | Line |
|----------|---------|------|
| `iter_zone_records(path)` | Iterate zone DBF records | 131 |
| `iter_county_subdivision_records(path)` | Iterate subdivision records | 188 |
| `load_zone_records(path)` | Load all zones | 244 |
| `sync_zone_catalog(...)` | Sync zones to database | 271 |

#### **location_settings.py** - Location Configuration

| Function | Purpose | Line |
|----------|---------|------|
| `ensure_list(value)` | Ensure list type | 35 |
| `sanitize_fips_codes(values)` | Validate FIPS codes | 43 |
| `normalise_fips_codes(values)` | Normalize FIPS format | 68 |
| `normalise_upper(values)` | Uppercase normalize | 94 |
| `as_title(value)` | Title case formatting | 98 |

#### **setup_wizard.py** - Configuration Wizard

| Class | Purpose | Line |
|-------|---------|------|
| `WizardField` | Form field definition | 43 |
| `WizardState` | Configuration state holder | 75 |
| `WizardSection` | Configuration section | 149 |

| Function | Purpose | Line |
|----------|---------|------|
| `load_wizard_state()` | Load configuration state | 400 |
| `generate_secret_key()` | Generate SECRET_KEY | 425 |
| `create_env_backup()` | Backup environment file | 431 |
| `build_env_content(state, updates)` | Render .env content | 441 |
| `write_env_file(state, updates, create_backup)` | Save environment | 470 |
| `clean_submission(raw_form)` | Clean form input | 482 |

#### **export.py** - Data Export

| Function | Purpose | Line |
|----------|---------|------|
| `generate_csv(records, fieldnames)` | Generate CSV from records | 26 |

---

## Analytics & Monitoring

### Location: `/home/user/eas-station/app_core/analytics/`

#### **models.py** - Analytics Data Models

| Class | Purpose | Line |
|-------|---------|------|
| `MetricSnapshot` | Single metric measurement | 13 |
| `TrendRecord` | Trend analysis record | 101 |
| `AnomalyRecord` | Anomaly detection record | 219 |

#### **aggregator.py** - Metrics Aggregation

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `MetricsAggregator` | Aggregate multiple metrics | `aggregate_metrics`, `compute_statistics` | 34 |

#### **anomaly_detector.py** - Anomaly Detection

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `AnomalyDetector` | Detect statistical anomalies | `detect_anomalies`, `analyze_trend` | 25 |

#### **trend_analyzer.py** - Trend Analysis

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `TrendAnalyzer` | Analyze metric trends | `calculate_trend`, `predict_trend`, `get_trend_summary` | 25 |

#### **scheduler.py** - Analytics Scheduling

| Class | Purpose | Key Methods | Line |
|-------|---------|-----------|------|
| `AnalyticsScheduler` | Schedule analytics tasks | `start`, `stop`, `add_job`, `remove_job` | 25 |

| Function | Purpose | Line |
|----------|---------|------|
| `get_scheduler()` | Get global scheduler | 197 |
| `start_scheduler()` | Start scheduler | 205 |
| `stop_scheduler()` | Stop scheduler | 211 |

---

## LED/VFD Display Control

### Location: `/home/user/eas-station/app_core/led.py`

#### **Location: `/home/user/eas-station/app_core/vfd.py`

| Function | Purpose | Line |
|----------|---------|------|
| `ensure_led_tables(force)` | Create/migrate LED tables | 104 |
| `initialise_led_controller(logger)` | Initialize LED hardware | - |
| `ensure_vfd_tables()` | Create/migrate VFD tables | - |
| `initialise_vfd_controller(logger)` | Initialize VFD hardware | - |

**Global Instances:**
- `led_controller` - LED sign interface
- `vfd_controller` - VFD display interface
- `LED_AVAILABLE` - Hardware availability flag
- `VFD_AVAILABLE` - Hardware availability flag

---

## Core Application

### Location: `/home/user/eas-station/app.py`

**Flask Application Setup & Configuration:**

| Function | Purpose | Parameters | Line |
|----------|---------|-----------|------|
| `_build_database_url()` | Construct database URL | none | 284 |
| `_get_eas_output_root()` | Get EAS output directory | none | 313 |
| `_get_eas_static_prefix()` | Get web subdir for EAS files | none | 318 |
| `_resolve_eas_disk_path(filename)` | Safe path resolution | filename | 322 |
| `_load_or_cache_audio_data(message, variant)` | Load EAS audio from disk/cache | message, variant | 348 |
| `_load_or_cache_summary_payload(message)` | Load EAS text summary | message | 386 |
| `_remove_eas_files(message)` | Remove EAS files from disk | message | 411 |
| `ensure_postgis_extension()` | Ensure PostGIS in PostgreSQL | none | 473 |
| `initialize_database()` | Create/initialize schema | none | 758 |
| `generate_csrf_token()` | Generate CSRF token | none | 276 |
| `create_app(config)` | Application factory | config | 949 |

**Request Hooks:**

| Hook | Purpose | Line |
|------|---------|------|
| `before_request()` | Pre-request validation & setup | 630 |
| `after_request(response)` | Post-request cleanup & CORS | 721 |

**Error Handlers:**

| Handler | Purpose | Line |
|---------|---------|------|
| `not_found_error(error)` | 404 Not Found | 554 |
| `internal_error(error)` | 500 Internal Server Error | 562 |
| `forbidden_error(error)` | 403 Forbidden | 573 |
| `bad_request_error(error)` | 400 Bad Request | 581 |

**Context Processors:**

| Function | Purpose | Line |
|----------|---------|------|
| `inject_global_vars()` | Inject variables into templates | 597 |

**CLI Commands:**

| Command | Purpose | Line |
|---------|---------|------|
| `init_db()` | Initialize database | 865 |
| `test_led()` | Test LED controller | 872 |
| `create_admin_user_cli(username, password)` | Create admin user | 889 |
| `cleanup_expired()` | Mark expired alerts | 921 |

---

## Key Modules & Subsystems

### EAS Storage (app_core/eas_storage.py)

**Core Functions:**

| Function | Purpose | Line |
|----------|---------|------|
| `record_audio_decode_result(...)` | Store decoded audio analysis | 77 |
| `load_recent_audio_decodes(limit)` | Retrieve recent decodes | 136 |
| `load_or_cache_audio_data(message, variant)` | Load EAS audio with caching | 309 |
| `load_or_cache_summary_payload(message)` | Load EAS text summary | 366 |
| `remove_eas_files(message)` | Clean up EAS files | 393 |
| `collect_alert_delivery_records(...)` | Build delivery report data | 973 |
| `build_alert_delivery_trends(...)` | Generate trend analysis | 1163 |
| `collect_compliance_log_entries(...)` | Gather compliance data | 1246 |
| `collect_compliance_dashboard_data(window_days)` | Aggregate compliance metrics | 1337 |
| `generate_compliance_log_csv(entries)` | Export compliance as CSV | 1418 |
| `generate_compliance_log_pdf(...)` | Export compliance as PDF | 1468 |

### Alerts & Boundary Intersection (app_core/alerts.py)

| Function | Purpose | Line |
|----------|---------|------|
| `calculate_alert_intersections(alert)` | Calculate alert-to-boundary intersections | 174 |
| `assign_alert_geometry(alert, geometry_data)` | Assign geometry to alert | 250 |
| `parse_noaa_cap_alert(alert_payload)` | Parse NOAA CAP JSON | 280 |
| `get_active_alerts_query()` | Query active alerts | 150 |
| `get_expired_alerts_query()` | Query expired alerts | 159 |
| `ensure_multipolygon(geometry)` | Normalize geometry type | 166 |

### Boundaries (app_core/boundaries.py)

**Configuration & Utilities:**

| Function | Purpose | Line |
|----------|---------|------|
| `normalize_boundary_type(value)` | Normalize boundary type | 89 |
| `get_boundary_display_label(boundary_type)` | Get display name | 108 |
| `get_boundary_group(boundary_type)` | Get grouping category | 119 |
| `get_boundary_color(boundary_type)` | Get map color | 124 |
| `get_field_mappings()` | Get field name mappings | 129 |
| `extract_name_and_description(properties, boundary_type)` | Parse GeoJSON properties | 170 |
| `describe_mtfcc(code)` | Describe MTFCC code | 227 |
| `calculate_geometry_length_miles(geometry)` | Calculate boundary perimeter | 274 |

### Location Settings (app_core/location.py)

| Function | Purpose | Line |
|----------|---------|------|
| `get_location_settings(force_reload)` | Get current location config | 145 |
| `update_location_settings(data)` | Update location settings | 160 |
| `describe_location_reference(...)` | Describe location reference | 308 |

### System Health (app_core/system_health.py)

| Function | Purpose | Line |
|----------|---------|------|
| `get_system_health(logger)` | Get current system health | 39 |

### Poll Debug (app_core/poller_debug.py)

| Function | Purpose | Line |
|----------|---------|------|
| `ensure_poll_debug_table(logger)` | Create debug table | 14 |
| `serialise_debug_record(record)` | Convert record to dict | 29 |
| `summarise_run(records)` | Summarize poll run | 63 |

---

## Extension & Plugin Architecture

### Location: `/home/user/eas-station/app_core/extensions.py`

**Database Extension:**
- `db` - SQLAlchemy database instance

**Usage Pattern:**
```python
from app_core.extensions import db

class MyModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... fields
```

---

## Route Registration System

### Location: `/home/user/eas-station/webapp/__init__.py`

| Class | Purpose | Line |
|-------|---------|------|
| `RouteModule` | Route module metadata container | 32 |

| Function | Purpose | Line |
|----------|---------|------|
| `iter_route_modules()` | Iterate available route modules | 40 |
| `register_routes(app, logger)` | Register all route modules | 64 |

**Registered Route Modules:**
- `admin` - Admin interface
- `admin.api` - Admin REST API
- `admin.auth` - Authentication
- `admin.audio` - Audio configuration
- `admin.audio_ingest` - Audio ingestion control
- `admin.boundaries` - Boundary management
- `admin.dashboard` - Admin dashboard
- `admin.environment` - Environment config
- `admin.maintenance` - System maintenance
- `public` - Public routes
- `analytics` - Analytics routes
- `debug` - Debug routes
- `exports` - Data export routes
- `led` - LED sign routes
- `monitoring` - System monitoring
- `screens` - Display screens
- `security` - Security/RBAC routes
- `settings_audio` - Audio settings
- `settings_radio` - Radio settings
- `setup` - Setup wizard
- `vfd` - VFD display routes
- `routes.alert_verification` - Alert verification
- `routes.eas_compliance` - EAS compliance
- `routes.system_controls` - System controls

---

## Configuration & Environment Variables

### Key Configuration Variables

**Database:**
- `DATABASE_URL` - PostgreSQL connection string
- `SQLALCHEMY_DATABASE_URI` - Flask SQLAlchemy URI
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`

**Session & Security:**
- `SECRET_KEY` - Flask session signing key (REQUIRED)
- `SESSION_COOKIE_SECURE` - HTTPS-only cookies
- `SESSION_LIFETIME_HOURS` - Session timeout (default: 12)
- `CORS_ALLOWED_ORIGINS` - CORS whitelist
- `CORS_ALLOW_CREDENTIALS` - Allow credentials in CORS

**EAS Broadcasting:**
- `EAS_BROADCAST_ENABLED` - Enable EAS audio generation
- `EAS_OUTPUT_DIR` - Directory for generated audio files
- `EAS_OUTPUT_WEB_SUBDIR` - Web path for audio files
- `EAS_ORIGINATOR` - 3-letter originator code
- `EAS_STATION_ID` - 8-letter station ID
- `EAS_GPIO_PIN` - GPIO pin for transmitter keying
- `EAS_GPIO_ACTIVE_STATE` - HIGH or LOW for active
- `EAS_GPIO_HOLD_SECONDS` - Minimum transmit duration
- `EAS_SAMPLE_RATE` - Audio sample rate (default: 16000)
- `EAS_ATTENTION_TONE_SECONDS` - Tone duration (default: 8)

**Text-to-Speech:**
- `EAS_TTS_PROVIDER` - TTS backend: pyttsx3, azure, openai
- `AZURE_SPEECH_KEY` - Azure Cognitive Services key
- `AZURE_SPEECH_REGION` - Azure region
- `AZURE_OPENAI_ENDPOINT` - Azure OpenAI endpoint
- `AZURE_OPENAI_KEY` - Azure OpenAI key

**Compliance & Health:**
- `COMPLIANCE_ALERT_EMAILS` - Compliance alert email list
- `COMPLIANCE_SNMP_TARGETS` - SNMP trap targets
- `COMPLIANCE_SNMP_COMMUNITY` - SNMP community string
- `COMPLIANCE_HEALTH_INTERVAL` - Health check interval (seconds)
- `RECEIVER_OFFLINE_THRESHOLD_MINUTES` - Receiver timeout
- `AUDIO_PATH_ALERT_THRESHOLD_MINUTES` - Audio path timeout

---

## Database Schema Overview

### Key Tables

**Alert Management:**
- `cap_alerts` - CAP alert records
- `eas_messages` - Encoded EAS broadcasts
- `eas_decoded_audio` - Decoded audio analysis
- `manual_eas_activations` - Manual EAS activations
- `alert_delivery_reports` - Compliance delivery metrics

**Geographic:**
- `boundaries` - Geographic boundaries
- `intersections` - Alert-to-boundary intersections
- `nws_zones` - NWS forecast zone catalog

**Configuration:**
- `location_settings` - Station location & timezone
- `radio_receivers` - SDR receiver configurations
- `radio_receiver_status` - Historical receiver status
- `audio_source_configs` - Audio source configurations

**User & Security:**
- `admin_users` - User accounts
- `roles` - User roles
- `permissions` - Permissions
- `role_permissions` - Role-permission mapping

**Display & Output:**
- `led_messages` - LED sign messages
- `led_sign_status` - LED hardware status
- `vfd_displays` - VFD content
- `vfd_status` - VFD hardware status
- `display_screens` - Custom screen templates
- `screen_rotations` - Screen rotation schedules

**Monitoring:**
- `audio_source_metrics` - Real-time audio metering
- `audio_health_status` - Audio system health snapshots
- `audio_alerts` - Audio system alerts
- `gpio_activation_logs` - GPIO relay audit trail
- `system_log` - General system logging
- `poll_history` - CAP fetch history
- `poll_debug_records` - Detailed poll debugging

**Analytics:**
- `metric_snapshots` - Point-in-time metrics
- `trend_records` - Trend analysis data
- `anomaly_records` - Anomaly detection results

---

## Authentication & Authorization Flow

```
Request → before_request() hook
  ├─ Check if setup mode required
  ├─ Load current user from session
  ├─ Check RBAC if protected route
  └─ Verify CSRF token if POST/PUT/DELETE
    
Route handler executes with:
  ├─ g.current_user (AdminUser or None)
  ├─ g.admin_setup_mode (bool)
  └─ @require_permission decorator checks

after_request() hook
  └─ Add CORS headers if API endpoint
```

---

## Testing Hooks

**Pytest Fixtures & Utilities:**
- Located in `/home/user/eas-station/tests/`
- Database: SQLite in-memory test database
- Flash messages, request context mocking
- Mock audio/GPIO hardware

---

## Performance Optimizations

**Database:**
- Connection pooling via SQLAlchemy
- Query indexing on frequently filtered columns
- Lazy loading for relationships
- Bulk operations for batch inserts

**Audio:**
- Ring buffers for audio streaming
- Chunk-based processing (not full file in memory)
- Async audio I/O where possible
- Sample rate conversion caching

**Web:**
- JSON API caching headers
- CSS/JS minification in production
- Static file caching
- Gzip compression

---

## Security Features

**Authentication:**
- Password hashing with werkzeug
- Session-based with secure cookies
- MFA support (TOTP + backup codes)
- Last login tracking

**Authorization:**
- Fine-grained RBAC system
- Per-resource permissions
- Decorator-based enforcement
- Audit logging for sensitive operations

**API Security:**
- CSRF protection on all mutations
- CORS whitelist enforcement
- SQL injection prevention via ORM
- Input validation/sanitization

**Data Protection:**
- TLS/HTTPS enforcement in production
- Sensitive data in environment variables
- Database user isolation
- Audio file access control

---

## Troubleshooting & Debug Routes

**Debug Routes (if enabled):**
- `/api/debug/poll-history` - Poll operation debugging
- `/api/debug/eas-messages` - EAS message inspection
- System health endpoints at `/api/system/*`

**Common Issues:**

1. **Database Connection:** Check `DATABASE_URL` and PostgreSQL availability
2. **EAS Generation:** Verify TTS provider configuration and audio library availability
3. **Radio Receivers:** Check SoapySDR installation and device permissions
4. **LED/VFD:** Verify serial port and hardware availability
5. **Audio:** Check ALSA/PulseAudio setup and microphone permissions

---

## Version History

- **2.1.9** - Current version (Nov 2025)
- Adds per-line LED formatting
- WYSIWYG message editing
- Numpy serialization fixes
- RBAC and MFA implementation
- Analytics suite
- Stream support for audio sources

See `CHANGELOG` and `VERSION` files for detailed history.

---

## Related Documentation

- **README.md** - Project overview and setup
- **docs/archive/2025/SECURITY_FIXES.md** - Historical security updates
- **[KNOWN_BUGS.md](KNOWN_BUGS.md)** - Known issues and workarounds
- **docs/** - Complete documentation directory

---

## Module Dependency Graph

```
app.py (Flask entry point)
  ├─ app_core/
  │  ├─ models.py (ORM models)
  │  ├─ extensions.py (db instance)
  │  ├─ alerts.py (alert processing)
  │  ├─ boundaries.py (geographic)
  │  ├─ location.py (config)
  │  ├─ auth/
  │  │  ├─ roles.py (RBAC)
  │  │  ├─ mfa.py (2FA)
  │  │  └─ audit.py (audit log)
  │  ├─ audio/
  │  │  ├─ ingest.py (source abstraction)
  │  │  ├─ sources.py (concrete sources)
  │  │  ├─ metering.py (health monitoring)
  │  │  ├─ output_service.py (playback)
  │  │  └─ playout_queue.py (queue)
  │  ├─ radio/
  │  │  ├─ manager.py (receiver manager)
  │  │  ├─ drivers.py (SDR drivers)
  │  │  ├─ discovery.py (hardware enum)
  │  │  └─ schema.py (database)
  │  ├─ analytics/
  │  │  ├─ models.py (data classes)
  │  │  ├─ aggregator.py (metrics)
  │  │  ├─ anomaly_detector.py (anomalies)
  │  │  ├─ trend_analyzer.py (trends)
  │  │  └─ scheduler.py (scheduling)
  │  ├─ eas_storage.py (EAS file management)
  │  ├─ led.py (LED interface)
  │  ├─ vfd.py (VFD interface)
  │  └─ system_health.py (health monitoring)
  ├─ app_utils/
  │  ├─ eas.py (EAS generation)
  │  ├─ eas_decode.py (EAS decoding)
  │  ├─ eas_fsk.py (FSK modulation)
  │  ├─ eas_tts.py (text-to-speech)
  │  ├─ gpio.py (GPIO control)
  │  ├─ event_codes.py (EAS codes)
  │  ├─ fips_codes.py (geographic codes)
  │  ├─ time.py (timezone utilities)
  │  ├─ formatting.py (output formatting)
  │  ├─ zone_catalog.py (zone database)
  │  └─ alert_sources.py (source tracking)
  └─ webapp/
     ├─ routes_public.py (public pages)
     ├─ routes_*.py (feature routes)
     ├─ admin/
     │  ├─ api.py (REST endpoints)
     │  ├─ auth.py (login/logout)
     │  ├─ boundaries.py (boundaries)
     │  ├─ maintenance.py (maintenance)
     │  ├─ environment.py (config editor)
     │  └─ *
     ├─ routes/ (submodule routes)
     │  ├─ alert_verification.py
     │  ├─ eas_compliance.py
     │  └─ system_controls.py
     └─ __init__.py (route registration)
```

---

**Document End**

