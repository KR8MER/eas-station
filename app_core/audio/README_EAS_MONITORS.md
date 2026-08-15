# EAS Monitor Implementations

This directory contains two EAS monitoring implementations, each used by a
different part of the codebase.

## Active Implementations

### 1. `eas_monitor_v3.py` (Production Decoder)
**File:** `app_core/audio/eas_monitor_v3.py` (706 lines)
**Class:** `UnifiedEASMonitorService` (plus `SourceWatcher`, `HealthTracker`)

**Used by:**
- `eas_monitoring_service.py` — the `eas-station-audio.service` process, the
  system's sole EAS/SAME decoder
- `app_core/audio/ingest.py`
- `app_core/audio/redis_commands.py`
- `webapp/admin/eas_decoder_monitor.py`
- Multiple test files

**Features:**
- Single monitor thread shared across every audio source, auto-discovered
  rather than manually registered
- Centralized health tracking (`HealthTracker`)
- Lightweight per-source watchers (`SourceWatcher`) instead of one thread per
  source

**When to use:** This is the implementation that actually runs in
production. A standalone `eas_service.py` process used to run a second,
independent decoder (`eas_monitor.py`'s `EASMonitor`, below) against the same
audio stream; it was retired as a redundant duplicate with a real (if
narrow) double-broadcast race against this one — see
`docs/reference/CHANGELOG.md`. `eas_monitor_v3.py` has been the only decoder
running against live audio since.

---

### 2. `eas_monitor.py` (Single-Source Monitor)
**File:** `app_core/audio/eas_monitor.py` (1,488 lines)
**Class:** `EASMonitor` (legacy aliases `ContinuousEASMonitor` and
`EASMonitorV2` both point at the same class — there is no separate V2
implementation despite the name)

**Used by:**
- `app_core/audio/startup_integration.py` — system initialization
- Multiple test files
- Example scripts

**Features:**
- Single-source SAME decoder with its own ring buffer, health
  monitoring/watchdogs, alert dedup, and FIPS filtering
- The building block `eas_monitor_v3.py` generalized into a
  shared-across-sources design; still used directly wherever only one audio
  source needs monitoring

**When to use:** Not the production decode path (see above) — used for
single-source contexts (startup checks, tests, examples) where the
multi-source machinery in `eas_monitor_v3.py` isn't needed.

---

## Archived Implementations

### `eas_monitor_simple.py` (Removed)
**Status:** Removed from the tree along with the rest of the Docker-era `legacy/` directory; available in git history if ever needed.

**Reason for removal:** This simplified implementation with "no watchdogs, no restarts, no complexity" was an experimental version that was never integrated into the production codebase.

### `eas_service.py` (Removed)
**Status:** Removed along with its systemd unit (`eas-station-eas.service`).

**Reason for removal:** Ran its own `EASMonitor` (`eas_monitor.py`) instance
subscribed to the same Redis audio stream `eas_monitoring_service.py`
already decodes via `eas_monitor_v3.py` — a leftover from a "3-tier
separated architecture" experiment (2025-12-05) that was reversed three days
later when EAS monitoring was merged back into the audio service. It went
unnoticed and kept running for 8+ months, with two processes decoding the
same SAME headers independently. See `docs/reference/CHANGELOG.md` for the
double-broadcast race this created.
