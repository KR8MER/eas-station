# Process Separation Proposal

## Problem
Currently, htop shows all CPU usage under "cap_poller.py" even when the actual culprit is:
- EAS audio monitor
- Radio SDR drivers
- Database operations
- Flask app components

**This makes debugging impossible** - we can't tell which subsystem is consuming CPU.

## Root Cause
The `poller/cap_poller.py` imports from `app` and `app_core`, which loads the entire Flask application stack including:
- Flask web server
- SQLAlchemy ORM
- EAS audio monitor
- Radio management
- All routes and middleware

```python
# In poller/cap_poller.py
from app import (
    db,
    CAPAlert,
    SystemLog,
    Boundary,
    Intersection,
    # ... loads ENTIRE Flask app!
)
from app_utils.eas import EASBroadcaster, load_eas_config
from app_core.radio import RadioManager
```

## Current Architecture

```
┌─────────────────────────────────────┐
│   eas-station-noaa-poller-1         │
│   (Single Python Process)           │
│                                     │
│  ┌───────────────────────────────┐  │
│  │  cap_poller.py                │  │
│  │  - CAP API polling            │  │
│  │  - Database queries           │  │
│  │  - Alert processing           │  │
│  └───────────────────────────────┘  │
│              ↓ imports               │
│  ┌───────────────────────────────┐  │
│  │  Flask App (app_core)         │  │
│  │  - EAS Audio Monitor (Thread) │  │
│  │  - Radio SDR (Thread)         │  │
│  │  - Database ORM               │  │
│  └───────────────────────────────┘  │
│                                     │
│  htop shows: "python cap_poller.py" │
│  CPU: 100% (but WHO is using it??) │
└─────────────────────────────────────┘
```

## Proposed Architecture

```
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│  eas-station-poller     │  │  eas-station-app        │  │  eas-station-audio      │
│  (Separate Process)     │  │  (Separate Process)     │  │  (Separate Process)     │
│                         │  │                         │  │                         │
│  ┌────────────────────┐ │  │  ┌────────────────────┐ │  │  ┌────────────────────┐ │
│  │ cap_poller.py      │ │  │  │ Flask Web Server   │ │  │  │ EAS Audio Monitor  │ │
│  │ - CAP polling      │ │  │  │ - Web UI           │ │  │  │ - Audio scanning   │ │
│  │ - Alert processing │ │  │  │ - REST API         │ │  │  │ - EAS detection    │ │
│  │ - DB via models    │ │  │  │ - Dashboard        │ │  │  │ - SAME decoding    │ │
│  └────────────────────┘ │  │  └────────────────────┘ │  │  └────────────────────┘ │
│                         │  │                         │  │                         │
│  htop: "cap_poller"     │  │  htop: "gunicorn"       │  │  htop: "eas_monitor"    │
│  CPU: 2% (correct!)     │  │  CPU: 5% (correct!)     │  │  CPU: 95% (AHA!)        │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘
         │                           │                             │
         └───────────────────────────┴─────────────────────────────┘
                                     │
                              ┌──────────────┐
                              │  PostgreSQL  │
                              │  (Database)  │
                              └──────────────┘
```

## Implementation Options

### Option 1: Separate Containers (Recommended)

**Benefits**:
- Complete isolation
- Independent scaling
- Clear CPU attribution
- Easier debugging
- Better resource limits

**Changes Needed**:
1. Create new `eas-audio-monitor` service in docker-compose.yml
2. Extract audio monitoring into standalone script
3. Use database as communication channel (or Redis/message queue)
4. Remove app imports from cap_poller.py

**docker-compose.yml**:
```yaml
services:
  noaa-poller:
    command: ["python", "poller/cap_poller.py", "--continuous", "--interval", "180"]
    # Lean imports, no Flask app
    
  app:
    command: ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
    # Web UI only, no audio monitoring
    
  eas-audio-monitor:  # NEW SERVICE
    image: eas-station:latest
    command: ["python", "scripts/run_eas_audio_monitor.py"]
    # Audio monitoring only
    depends_on:
      - app
      - alerts-db
```

### Option 2: Multiprocessing Within Container

**Benefits**:
- Simpler deployment (one container)
- Shared memory possible
- Faster communication

**Changes Needed**:
1. Use Python multiprocessing to spawn EAS monitor
2. Still shows as separate processes in htop
3. Refactor to avoid shared imports

**Implementation**:
```python
# In cap_poller.py or startup script
import multiprocessing

def run_eas_monitor():
    from app_core.audio import start_eas_monitor
    start_eas_monitor()

def run_cap_poller():
    # Current cap_poller logic
    pass

if __name__ == '__main__':
    # Spawn as separate processes
    eas_process = multiprocessing.Process(target=run_eas_monitor, name='eas-monitor')
    poller_process = multiprocessing.Process(target=run_cap_poller, name='cap-poller')
    
    eas_process.start()
    poller_process.start()
    
    eas_process.join()
    poller_process.join()
```

### Option 3: Move Audio Monitor to App Container

**Benefits**:
- Minimal changes
- Audio monitor runs where it belongs (with Flask app)
- Cap poller becomes lean

**Changes Needed**:
1. Remove EAS audio init from cap_poller
2. Let Flask app handle audio monitoring
3. Decouple models (use REST API instead of direct imports)

**This is probably the quickest fix!**

## Recommended Approach: Option 3 (Move to App)

### Why?
- Least disruptive
- EAS audio monitor SHOULD run with the web app, not the poller
- Cap poller only needs to write alerts to DB, not monitor audio
- Quick to implement

### Steps:

1. **Check where EAS monitor is started in cap_poller**
   ```bash
   grep -n "EASBroadcaster\|audio\|monitor" poller/cap_poller.py
   ```

2. **Move EAS initialization to Flask app only**
   - The Flask app (`app.py`) should start the EAS monitor
   - The cap poller should NOT import or start it

3. **Decouple cap_poller from Flask app**
   - Create a minimal `models_minimal.py` with just the SQLAlchemy models
   - Remove `from app import ...`
   - Use direct SQLAlchemy without Flask-SQLAlchemy

4. **Update docker-compose**
   - Ensure `app` service has audio devices/permissions
   - Verify `noaa-poller` doesn't need audio access

### Code Changes Required:

**poller/cap_poller.py**:
```python
# BEFORE
from app import db, CAPAlert, SystemLog, ...  # Loads entire Flask app!

# AFTER  
from sqlalchemy.orm import declarative_base
from models_minimal import CAPAlert, SystemLog, ...  # Just models
```

**app.py** (Flask app):
```python
# Add initialization for EAS audio monitor
if not setup_mode_active():
    from app_core.audio import initialize_eas_monitor
    initialize_eas_monitor()  # Start monitoring here, not in poller
```

## Quick Fix for Immediate Debugging

While planning the architecture change, use these tools to see what's actually consuming CPU:

### 1. Thread-Level View
```bash
docker exec eas-station-noaa-poller-1 ps -eLf
# Shows threads with their own CPU percentages
```

### 2. Python Profiling
```bash
# Install py-spy (Python performance profiler)
docker exec eas-station-noaa-poller-1 pip install py-spy

# Show live profile
docker exec eas-station-noaa-poller-1 py-spy top --pid 1

# Generate flame graph
docker exec eas-station-noaa-poller-1 py-spy record -o profile.svg --pid 1 --duration 30
```

### 3. Set Process Names
In the meantime, we can set thread names to identify them:
```python
# In EAS monitor
import threading
threading.current_thread().name = "EAS-Monitor"

# In radio drivers
threading.current_thread().name = f"SDR-{receiver_id}"
```

Then ps/htop will show thread names:
```
PID  %CPU COMMAND
123  2.0  python cap_poller.py
124  95.0 python cap_poller.py [EAS-Monitor]  # AHA! This is the culprit!
125  1.0  python cap_poller.py [SDR-rtl0]
```

## Timeline

### Immediate (Hours)
- ✅ Add EAS_SCAN_INTERVAL config (done)
- ✅ Fix N+1 query problem (done)
- ⏳ Apply EAS_SCAN_INTERVAL=6.0 in production
- ⏳ Verify CPU drops

### Short-term (Days)
- Move EAS audio monitor to app container (Option 3)
- Decouple cap_poller from Flask imports
- Verify htop shows correct process names

### Long-term (Weeks)
- Full containerization (Option 1)
- Separate containers for each component
- Proper IPC/message queue
- Independent scaling

## Success Criteria

After implementation, `htop` should show:
```
PID   %CPU  COMMAND
1234  2%    python cap_poller.py          # Cap polling only
5678  5%    gunicorn wsgi:app             # Flask web UI
9012  10%   python eas_audio_monitor.py   # Audio monitoring
```

Instead of:
```
PID   %CPU  COMMAND
1234  100%  python cap_poller.py          # Everything lumped together!
```

## Benefits

1. **Clear Attribution**: Know exactly which component uses CPU
2. **Easier Debugging**: Profile/restart individual components
3. **Better Scaling**: Scale components independently
4. **Resource Limits**: Apply CPU/memory limits per component
5. **Cleaner Architecture**: Separation of concerns
6. **Faster Development**: Work on one component without affecting others

## Questions to Answer

1. Does cap_poller actually need to start EAS broadcaster, or should it just write alerts to DB?
2. Is the audio monitoring for broadcast alerts or for monitoring incoming radio?
3. Can we use REST API instead of direct model imports?
4. What are the dependencies between components?

## Conclusion

The architectural issue is clear: everything runs in one process, making it impossible to identify CPU culprits. The solution is process separation, with Option 3 (move audio monitor to app container) being the quickest path forward.
