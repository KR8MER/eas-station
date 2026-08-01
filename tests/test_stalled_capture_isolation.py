"""
Regression tests: stalled captures must NEVER stall the rest of the system.

Guards the fixes for the "stalled capture froze the entire audio service"
incident (all sources STOPPED, EAS Continuous Monitor "Unavailable",
"Audio service metrics are unavailable" banner):

1. AudioIngestController's registry lock is never held during blocking
   adapter.start()/stop() work — metrics collection and status queries stay
   responsive while a source is being started or stopped.
2. Stalled-source restarts run in per-source background recovery threads,
   so one stalled capture's slow restart cannot delay stall detection or
   recovery of any other source.
3. Only one recovery per source runs at a time (no restart pile-ups).
4. eas_monitoring_service.py runs the source watchdog in its own thread
   (never inline with metrics publishing), queries auto-start config inside
   a Flask app context, and auto-starts sources in parallel at boot.
"""
import os
import re
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pytest
from unittest.mock import MagicMock

# Stub out heavy web/DB dependencies so we can import audio code in isolation
# (same bootstrap as tests/test_stall_detection_fix.py).
_STUBS = [
    'flask', 'flask_sqlalchemy', 'flask_caching', 'flask_login',
    'flask_socketio', 'flask_migrate', 'flask_wtf',
    'sqlalchemy', 'sqlalchemy.orm', 'sqlalchemy.ext',
    'sqlalchemy.ext.declarative',
    'geoalchemy2', 'geoalchemy2.types',
    'redis', 'redis.client', 'redis.exceptions',
    'celery', 'pyaudio', 'alsaaudio', 'requests',
]
for _mod in _STUBS:
    sys.modules.setdefault(_mod, MagicMock())

import types as _types


def _make_pkg(name):
    mod = _types.ModuleType(name)
    mod.__path__ = []
    mod.__package__ = name
    sys.modules.setdefault(name, mod)
    return sys.modules[name]


_app_core = _make_pkg('app_core')
if not hasattr(_app_core, 'db'):
    _app_core.db = MagicMock()

import importlib.util as _ilu


def _load_direct(dotted, path):
    """Load a module from a file path without triggering parent __init__."""
    if dotted in sys.modules and hasattr(sys.modules[dotted], '__file__'):
        return sys.modules[dotted]
    spec = _ilu.spec_from_file_location(dotted, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    return mod


_REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
_base = os.path.join(_REPO_ROOT, 'app_core', 'audio')
_bq = _load_direct('app_core.audio.broadcast_queue', os.path.join(_base, 'broadcast_queue.py'))
_ing = _load_direct('app_core.audio.ingest', os.path.join(_base, 'ingest.py'))

AudioIngestController = _ing.AudioIngestController
AudioSourceAdapter = _ing.AudioSourceAdapter
AudioSourceConfig = _ing.AudioSourceConfig
AudioSourceType = _ing.AudioSourceType
AudioSourceStatus = _ing.AudioSourceStatus


# ---------------------------------------------------------------------------
# Test adapters
# ---------------------------------------------------------------------------
class SlowStartAdapter(AudioSourceAdapter):
    """Adapter whose _start_capture blocks (simulates dead-URL stream start)."""

    def __init__(self, name: str, start_delay: float = 0.0, stop_delay: float = 0.0):
        config = AudioSourceConfig(
            source_type=AudioSourceType.STREAM,
            name=name,
            buffer_size=256,
        )
        super().__init__(config)
        self._start_delay = start_delay
        self._stop_delay = stop_delay

    def _start_capture(self) -> None:
        if self._start_delay:
            time.sleep(self._start_delay)

    def _stop_capture(self) -> None:
        if self._stop_delay:
            time.sleep(self._stop_delay)

    def _read_audio_chunk(self):
        time.sleep(0.01)
        return None


class NeverProducesAdapter(AudioSourceAdapter):
    """Adapter that starts fine but never delivers audio; restart is observable."""

    def __init__(self, name: str, restart_block_seconds: float = 0.0):
        config = AudioSourceConfig(
            source_type=AudioSourceType.STREAM,
            name=name,
            buffer_size=256,
        )
        super().__init__(config)
        self._restart_block_seconds = restart_block_seconds
        self.restart_started_at = None
        self.restart_count = 0

    def _start_capture(self) -> None:
        pass

    def _stop_capture(self) -> None:
        pass

    def _read_audio_chunk(self):
        time.sleep(0.01)
        return None

    def restart(self, reason, *, delay=0.25, max_attempts=2):
        if self.restart_started_at is None:
            self.restart_started_at = time.time()
        self.restart_count += 1
        if self._restart_block_seconds:
            time.sleep(self._restart_block_seconds)
        return True


# ---------------------------------------------------------------------------
# 1. Registry lock must not be held during blocking start
# ---------------------------------------------------------------------------
def test_blocking_start_does_not_block_status_queries():
    """get_all_sources()/get_all_status() stay fast while a source is starting."""
    controller = AudioIngestController(enable_monitor=False)
    slow = SlowStartAdapter("slow-start", start_delay=1.5)
    fast = SlowStartAdapter("fast-idle")
    controller.add_source(slow)
    controller.add_source(fast)

    starter = threading.Thread(target=controller.start_source, args=("slow-start",))
    starter.start()
    time.sleep(0.3)  # ensure start_source is inside the blocking _start_capture

    t0 = time.time()
    sources = controller.get_all_sources()
    statuses = controller.get_all_status()
    names = controller.list_sources()
    elapsed = time.time() - t0

    starter.join(timeout=5)
    controller.stop_all()

    assert elapsed < 0.5, (
        f"Status queries took {elapsed:.2f}s while a source was starting — "
        "the registry lock is being held across blocking adapter.start() work"
    )
    assert set(sources) == {"slow-start", "fast-idle"}
    assert set(statuses) == {"slow-start", "fast-idle"}
    assert set(names) == {"slow-start", "fast-idle"}


# ---------------------------------------------------------------------------
# 2. Registry lock must not be held during blocking stop
# ---------------------------------------------------------------------------
def test_blocking_stop_does_not_block_status_queries():
    """get_all_sources() stays fast while a source is stopping."""
    controller = AudioIngestController(enable_monitor=False)
    slow = SlowStartAdapter("slow-stop", stop_delay=1.5)
    controller.add_source(slow)
    controller.start_source("slow-stop")

    stopper = threading.Thread(target=controller.stop_source, args=("slow-stop",))
    stopper.start()
    time.sleep(0.3)  # ensure stop_source is inside the blocking _stop_capture

    t0 = time.time()
    controller.get_all_sources()
    controller.get_all_status()
    elapsed = time.time() - t0

    stopper.join(timeout=5)

    assert elapsed < 0.5, (
        f"Status queries took {elapsed:.2f}s while a source was stopping — "
        "the registry lock is being held across blocking adapter.stop() work"
    )


# ---------------------------------------------------------------------------
# 3. One stalled source's slow restart must not delay another's recovery
# ---------------------------------------------------------------------------
def test_stalled_restart_does_not_serialize_other_recoveries():
    """Two stalled sources: A's restart blocks 3s; B's restart must still
    start within ~1.5s of A's, not after A's finishes (the old serial path)."""
    adapter_a = NeverProducesAdapter("stall-a", restart_block_seconds=3.0)
    adapter_b = NeverProducesAdapter("stall-b")
    controller = AudioIngestController(
        enable_monitor=True,
        monitor_interval=0.2,
        stall_seconds=1,
    )
    controller._monitor_grace_period = 0.5
    controller.add_source(adapter_a)
    controller.add_source(adapter_b)
    adapter_a.start()
    adapter_b.start()

    deadline = time.time() + 8
    while (
        (adapter_a.restart_started_at is None or adapter_b.restart_started_at is None)
        and time.time() < deadline
    ):
        time.sleep(0.05)

    a_started = adapter_a.restart_started_at
    b_started = adapter_b.restart_started_at
    controller.stop_all()

    assert a_started is not None, "Source A's stalled-capture restart never fired"
    assert b_started is not None, "Source B's stalled-capture restart never fired"
    gap = abs(b_started - a_started)
    assert gap < 1.5, (
        f"Source B's restart started {gap:.2f}s after source A's — restarts are "
        "serialized in the shared monitor thread, so one stalled capture delays "
        "recovery of every other source"
    )


# ---------------------------------------------------------------------------
# 4. Only one recovery per source may be in flight
# ---------------------------------------------------------------------------
def test_duplicate_recovery_skipped_while_in_flight():
    controller = AudioIngestController(enable_monitor=False)
    release = threading.Event()
    ran = []

    def _action():
        ran.append(time.time())
        release.wait(5)

    assert controller.spawn_recovery("src", _action, "test") is True
    time.sleep(0.1)
    assert controller.recovery_in_flight("src") is True
    # Second recovery for the same source must be refused while one runs
    assert controller.spawn_recovery("src", _action, "test-duplicate") is False
    # A different source is independent
    assert controller.spawn_recovery("other", lambda: None, "test-other") is True

    release.set()
    deadline = time.time() + 2
    while controller.recovery_in_flight("src") and time.time() < deadline:
        time.sleep(0.02)
    assert controller.recovery_in_flight("src") is False
    # After completion a new recovery may start
    release.clear()
    assert controller.spawn_recovery("src", lambda: None, "test-again") is True
    assert len(ran) == 1


# ---------------------------------------------------------------------------
# 5. Service-level guards (source-text assertions on eas_monitoring_service.py)
# ---------------------------------------------------------------------------
def _service_source() -> str:
    path = os.path.join(_REPO_ROOT, "eas_monitoring_service.py")
    with open(path) as f:
        return f.read()


def test_watchdog_runs_in_dedicated_thread_not_main_loop():
    """The source watchdog must never run inline with metrics publishing."""
    src = _service_source()
    assert "def _source_watchdog_loop(" in src, (
        "eas_monitoring_service.py must define _source_watchdog_loop — the "
        "watchdog may not run inline in the metrics loop"
    )
    assert 'name="SourceWatchdog"' in src, (
        "The watchdog must be launched in its own named thread"
    )
    assert "last_source_watchdog_time" not in src, (
        "Inline watchdog remnants found in the main loop — restarting a "
        "stalled source there blocks metrics publishing and makes the whole "
        "audio service report as unavailable"
    )


def test_watchdog_queries_auto_start_config_inside_app_context():
    """The auto-start DB query must run inside a Flask app context.

    Without one, Flask-SQLAlchemy raises on every cycle, the exception is
    swallowed, auto_start_names stays empty forever, and STOPPED auto-start
    sources are never restarted.
    """
    src = _service_source()
    match = re.search(
        r"def _source_watchdog_loop\(.*?(?=\ndef |\Z)", src, re.S
    )
    assert match, "_source_watchdog_loop not found"
    body = match.group(0)
    assert "AudioSourceConfigDB.query.all()" in body
    assert "app.app_context()" in body, (
        "Watchdog must wrap AudioSourceConfigDB queries in app.app_context()"
    )
    assert body.index("app.app_context()") < body.index(
        "AudioSourceConfigDB.query.all()"
    ), "app_context() must be entered before the AudioSourceConfigDB query"


def test_watchdog_uses_per_source_recovery_threads():
    """Watchdog restarts must go through controller.spawn_recovery."""
    src = _service_source()
    match = re.search(
        r"def _source_watchdog_loop\(.*?(?=\ndef |\Z)", src, re.S
    )
    assert match, "_source_watchdog_loop not found"
    body = match.group(0)
    assert "spawn_recovery" in body, (
        "Watchdog must dispatch restarts via audio_controller.spawn_recovery "
        "so one blocked source cannot delay recovery of the others"
    )


def test_startup_auto_start_is_parallel():
    """Boot-time auto-start must not serialize on dead sources."""
    src = _service_source()
    assert "auto-start-" in src and "_auto_start_one" in src, (
        "initialize_audio_controller must auto-start sources in parallel "
        "threads — a single dead stream URL must not delay startup (and "
        "therefore decoding) for every healthy source"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
