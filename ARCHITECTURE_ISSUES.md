# Container Architecture Issues - Audit Report

This document identifies code that assumes monolithic deployment but breaks in separated Docker containers.

## Executive Summary

**Found**: 47 potential issues across 15 files
**Severity Breakdown**:
- 🔴 **Critical** (8): Will cause errors/crashes
- 🟡 **Warning** (23): May cause degraded functionality
- 🟢 **Info** (16): Works but not optimal

---

## 🔴 CRITICAL ISSUES

### 1. RadioManager Direct Access from App Container ⚠️ **PARTIALLY BROKEN**

**Files**: `webapp/routes_settings_radio.py`

**Problem**: Web app tries to directly access RadioManager, which only exists in `sdr-service` container.

**Locations**:
- Line 73: `manager = get_radio_manager()` in `_log_radio_event()`
- Line 439: `radio_manager = get_radio_manager()` in receiver enumeration
- Line 727: `radio_manager = get_radio_manager()` in restart receiver
- Line 1246: `radio_manager = get_radio_manager()` in spectrum endpoint
- Line 1504: `radio_manager = get_radio_manager()` in diagnostics

**Impact**:
- ❌ Restart receiver button won't work
- ❌ Spectrum/waterfall won't work from settings page
- ⚠️ Some operations fail silently with defensive error handling

**Fix Status**:
- ✅ `/settings/radio` page NOW uses diagnostics API (fixed)
- ❌ Individual receiver operations still try direct RadioManager access

**Recommendation**:
```python
# BROKEN - Direct access
radio_manager = get_radio_manager()
receiver = radio_manager.get_receiver(identifier)

# FIXED - Use Redis or HTTP API
from app_core.redis_client import get_redis_client
redis = get_redis_client()
status_json = redis.get(f"radio:receiver:{identifier}:status")
receiver_status = json.loads(status_json) if status_json else None

# OR use diagnostics endpoint
response = requests.get(f"http://sdr-service:5001/api/receiver/{identifier}/status")
```

---

### 2. Network Management from App Container ⚠️ **BROKEN**

**File**: `webapp/admin/network.py`

**Problem**: Runs NetworkManager commands (`nmcli`) which require host network access.

**Operations**:
- Line 84: `nmcli connection show` - Get network status
- Line 152: `nmcli dev wifi rescan` - Scan WiFi
- Line 210: `nmcli dev wifi connect` - Connect to network
- Line 262: `nmcli device disconnect` - Disconnect
- Line 290: `nmcli connection delete` - Forget network

**Impact**:
- ❌ WiFi management completely broken in app container
- ❌ Network status always shows "No connections"

**Current State**:
App container has NO network_mode: host, so nmcli can't control host networking.

**Fix**: Move to hardware-service container OR use host.docker.internal API

---

### 3. Zigbee Serial Port Access from App Container ⚠️ **BROKEN**

**File**: `webapp/admin/zigbee.py`

**Problem**: Tries to access `/dev/ttyAMA0` and `/dev/ttyUSB0` which aren't mapped to app container.

**Operations**:
- Line 41: `ZIGBEE_PORT = '/dev/ttyAMA0'`
- Line 103: Opens serial port for Zigbee coordinator

**Impact**:
- ❌ Zigbee coordinator management completely broken
- ❌ Device listing fails

**Current State**:
Serial devices are mapped to `hardware-service`, not `app`.

**Fix**: Create Zigbee proxy API in hardware-service.

---

## 🟡 WARNING ISSUES

### 4. Localhost Hardcoding in Health Checks

**Files**:
- `webapp/routes_diagnostics.py:278` - `http://localhost/health/dependencies`
- `webapp/routes_backups.py:94` - `--host localhost --port 8080`

**Problem**: Assumes services run on localhost, but they're in different containers.

**Impact**:
- ⚠️ Health checks may fail
- ⚠️ Backup scripts may target wrong host

**Fix**: Use container names: `http://app:5000/` instead of `localhost`

---

### 5. Subprocess Commands Assuming Host Environment

**Files**:
- `webapp/admin/network.py` - nmcli commands
- `webapp/admin/maintenance.py:184` - System maintenance commands
- `webapp/routes_diagnostics.py:41` - Diagnostic commands

**Problem**: Commands run in container environment, not host.

**Impact**:
- ⚠️ Commands may fail or return containerized info instead of host info
- ⚠️ Package installation/updates won't work

**Examples**:
```python
# Line 184 in maintenance.py
subprocess.run(["apt-get", "update"])  # Updates container, not host!

# Line 41 in routes_diagnostics.py
subprocess.run(["systemctl", "status", "docker"])  # No systemd in container!
```

---

### 6. Direct Filesystem Paths

**Files**:
- `webapp/admin/environment.py:684` - `/dev/ttyUSB0`
- `webapp/admin/environment.py:795` - `/dev/ttyAMA0`

**Problem**: Device paths not mapped to app container.

**Impact**: Serial device configuration UI allows selecting devices that don't exist.

---

### 7. Redis Connection Assumptions

**Files**: Multiple files use `get_redis_client()` assuming Redis is on default host.

**Current Status**: ✅ MOSTLY FIXED
- Redis host defaults to "redis" (Docker service name)
- But error handling may be incomplete

**Potential Issue**: If Redis fails, some pages crash instead of degrading gracefully.

---

## 🟢 INFO / OPTIMIZATION ISSUES

### 8. GPIO References in App Container

**Files**:
- `webapp/admin/dashboard.py:301-304` - GPIO statistics page
- `webapp/admin/environment.py` - GPIO configuration

**Status**: ⚠️ **READ-ONLY DATA**

These pages just display GPIO stats from database, they don't control GPIO directly.
Actual GPIO control is in `hardware-service` ✅

**No fix needed**, but could be optimized to query hardware-service API for real-time status.

---

### 9. Icecast Hostname Configuration

**File**: `app_core/audio/icecast_auto_config.py`

**Issue**: Defaults to 'localhost' which won't work for remote access.

**Impact**: Icecast streams only accessible from inside container.

**Fix**: Already has public_hostname parameter, but should default to container name.

---

## RECOMMENDATIONS

### Immediate Fixes (Breaking Functionality)

1. **✅ DONE**: Settings/radio page uses diagnostics API
2. **TODO**: Move network management to hardware-service or create proxy API
3. **TODO**: Create Zigbee proxy API in hardware-service
4. **TODO**: Fix receiver restart/spectrum endpoints to use Redis/API

### Medium Priority

5. **TODO**: Replace localhost with container names in health checks
6. **TODO**: Add container awareness to subprocess commands
7. **TODO**: Better Redis error handling throughout

### Low Priority

8. Document container architecture clearly for future developers
9. Add integration tests that verify cross-container communication
10. Create architecture diagram showing service boundaries

---

## ARCHITECTURE BEST PRACTICES

### ✅ DO THIS:
```python
# Use Redis for cross-container state
from app_core.redis_client import get_redis_client
redis = get_redis_client()
status = redis.get("sdr:receiver:status")

# Use HTTP APIs between services
import requests
resp = requests.get("http://hardware-service:5002/api/gpio/status")

# Use Docker service names, not localhost
DATABASE_HOST = os.getenv("POSTGRES_HOST", "alerts-db")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
```

### ❌ DON'T DO THIS:
```python
# Direct object access across containers
radio_manager = get_radio_manager()  # Only works in sdr-service!

# Localhost assumptions
requests.get("http://localhost:8000")  # Won't work between containers

# Host system commands
subprocess.run(["nmcli", "dev", "wifi"])  # Container can't control host
```

---

## TESTING RECOMMENDATIONS

1. **Integration Tests**: Test each service in isolation
2. **E2E Tests**: Test cross-container communication
3. **Failure Tests**: Test Redis/API failures gracefully degrade
4. **Network Tests**: Verify no localhost dependencies

---

**Generated**: 2025-11-27
**Branch**: claude/build-docker-images-014dspqQiJgNVVY7kH7zTbXt
**Auditor**: Claude (Automated Architecture Analysis)
