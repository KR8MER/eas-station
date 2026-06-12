# EAS Monitor Implementations

This directory contains two active EAS monitoring implementations, each designed for different use cases.

## Active Implementations

### 1. `eas_monitor.py` (Primary Implementation)
**File:** `app_core/audio/eas_monitor.py` (1,488 lines)
**Class:** `ContinuousEASMonitor`

**Used by:**
- `eas_service.py` - Main EAS service
- `app_core/audio/startup_integration.py` - System initialization
- Multiple test files
- Example scripts

**Features:**
- Professional audio subsystem integration
- 24/7 alert monitoring
- Comprehensive SAME decoder
- Ring buffer management
- Alert deduplication
- Health monitoring and watchdogs
- Callback system for alert notifications
- FIPS code filtering

**When to use:** Default choice for production deployments. Fully featured, battle-tested implementation.

---

### 2. `eas_monitor_v2.py` (Alternative Implementation)
**File:** `app_core/audio/eas_monitor_v2.py` (391 lines)
**Class:** `EASMonitorV2`

**Used by:**
- `eas_monitoring_service.py` - Monitoring service

**Features:**
- Complete architecture rewrite
- Robust audio reading with timeout detection
- Consistent status reporting
- Clear health metrics
- Proper error recovery
- No silent failures
- Simplified architecture

**When to use:** Alternative implementation with improved error handling and health monitoring. Designed to fix fundamental architecture issues found in long-running deployments.

---

## Archived Implementations

### `eas_monitor_simple.py` (Removed)
**Status:** Removed from the tree along with the rest of the Docker-era `legacy/` directory; available in git history if ever needed.

**Reason for removal:** This simplified implementation with "no watchdogs, no restarts, no complexity" was an experimental version that was never integrated into the production codebase.

---

## Choosing an Implementation

| Feature | eas_monitor.py | eas_monitor_v2.py |
|---------|----------------|-------------------|
| Lines of code | 1,488 | 391 |
| Complexity | High | Medium |
| Features | Comprehensive | Focused |
| Health monitoring | Yes | Enhanced |
| Error recovery | Yes | Improved |
| Production use | Primary | Alternative |
| Recommended for | Full deployments | Simpler setups |

**Default recommendation:** Use `eas_monitor.py` (ContinuousEASMonitor) unless you have specific requirements for the V2 architecture.

---

## Future Consolidation

These two implementations serve different needs. A future enhancement could consolidate the best features of both into a single, unified implementation.
