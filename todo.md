# EAS Station Development Tasks

## Selected Task: Audio Ingest Pipeline Implementation

Based on the master roadmap, I'll work on implementing the unified audio ingest pipeline (Requirement 1) which is currently incomplete and critical for the drop-in replacement goal.

### Task Overview
**Goal**: Normalize capture from SDR, ALSA/Pulse, and file inputs into a single managed pipeline with metering and diagnostics.

### Implementation Plan
1. Create `app_core/audio/ingest.py` with pluggable source adapters
2. Add configuration parsing to `configure.py` for source priorities and failover
3. Implement peak/RMS metering and silence detection
4. Store metering data for UI display in system health views
5. Provide calibration utilities under `tools/audio_debug.py`
6. Add configuration documentation in `docs/audio.md`

### Progress Tracking
- [x] Create app_core/audio directory structure
- [x] Implement base audio source adapter interface
- [x] Create SDR audio source adapter
- [x] Create ALSA/Pulse audio source adapter  
- [x] Create file input audio source adapter
- [x] Implement unified ingest controller
- [x] Add peak/RMS metering and silence detection
- [x] Create metering storage models
- [x] Update configure.py for audio settings
- [x] Create audio debug utilities
- [x] Update system health endpoints
- [x] Add documentation
- [x] Write tests
- [x] Create pull request

### Reference Implementation
This task builds on the existing radio manager infrastructure in `app_core/radio/` and will integrate with the system health monitoring in `app_core/system_health.py`.