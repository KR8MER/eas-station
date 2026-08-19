"""
Tests for the stall detection fix (PR #1818 follow-up).

Verifies that:
1. AudioIngestController(stall_seconds=30) does not fire "stalled capture"
   for sources that take up to 30s to produce their first audio chunk.
2. AudioIngestController(stall_seconds=5) (the old default) DOES fire within
   ~6s — proving the regression we fixed.
3. eas_monitoring_service creates the controller with stall_seconds=30.
4. The FFmpeg -analyzeduration flag is 2000000 (2s), not 5000000 (5s).
"""
import time
import threading
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pytest
from unittest.mock import MagicMock

# Stub out heavy web/DB dependencies so we can import audio code in isolation.
# The stall-detection logic lives entirely in app_core/audio/ingest.py which
# only needs numpy and its own broadcast_queue sibling — no Flask/DB required.
#
# All of this is transient scaffolding for the _load_direct() calls below,
# not something later test files should ever see: this file's own tests only
# reference the classes bound to module-level names further down (via direct
# object references, unaffected by sys.modules afterward). Snapshot every key
# we are about to touch so it can be restored once those classes are
# extracted -- previously this left permanent, unconditional damage in
# sys.modules for the rest of the pytest session: 'app_core' was replaced
# with an empty stub package (mod.__path__ = []), and 'app_core.audio.ingest'
# / 'app_core.audio.broadcast_queue' were overwritten with THIS file's
# privately loaded copies. Any later test doing a fresh
# `from app_core.audio.ingest import AudioSourceStatus` got a *different*,
# non-identical AudioSourceStatus class than whatever had already imported
# the real module, so `some_status == AudioSourceStatus.RUNNING` silently
# evaluated False forever after -- no exception, just wrong answers.
_STUBS = [
    'flask', 'flask_sqlalchemy', 'flask_caching', 'flask_login',
    'flask_socketio', 'flask_migrate', 'flask_wtf',
    'sqlalchemy', 'sqlalchemy.orm', 'sqlalchemy.ext',
    'sqlalchemy.ext.declarative',
    'geoalchemy2', 'geoalchemy2.types',
    'redis', 'redis.client', 'redis.exceptions',
    'celery', 'pyaudio', 'alsaaudio', 'requests',
]
_RESTORE_KEYS = _STUBS + [
    'app_core', 'app_core.audio.broadcast_queue', 'app_core.audio.ingest',
]
_sys_modules_before_stubbing = {_key: sys.modules.get(_key) for _key in _RESTORE_KEYS}

for _mod in _STUBS:
    sys.modules.setdefault(_mod, MagicMock())

# app_core/__init__.py runs DB/model imports; stub the whole package init
# by pre-populating sub-modules before app_core is first imported.
import importlib, types as _types

def _make_pkg(name):
    mod = _types.ModuleType(name)
    mod.__path__ = []
    mod.__package__ = name
    sys.modules[name] = mod
    return mod

_app_core = _make_pkg('app_core')
_app_core.db = MagicMock()

# Now we can safely import just the audio sub-package
import importlib.util as _ilu

def _load_direct(dotted, path):
    """Load a module from a file path without triggering parent __init__."""
    spec = _ilu.spec_from_file_location(dotted, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[dotted] = mod
    spec.loader.exec_module(mod)
    return mod

_base = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app_core', 'audio')
_bq   = _load_direct('app_core.audio.broadcast_queue', os.path.join(_base, 'broadcast_queue.py'))
_ing  = _load_direct('app_core.audio.ingest',          os.path.join(_base, 'ingest.py'))

AudioIngestController = _ing.AudioIngestController
AudioSourceAdapter    = _ing.AudioSourceAdapter
AudioSourceConfig     = _ing.AudioSourceConfig
AudioSourceType       = _ing.AudioSourceType
AudioSourceStatus     = _ing.AudioSourceStatus

# Everything below this file's own tests needs is now bound to a module-level
# name above (direct object references survive regardless of sys.modules).
# Put sys.modules back the way it was so later test files that import
# app_core.* for real get the real thing, not this file's private copies.
for _key, _val in _sys_modules_before_stubbing.items():
    if _val is None:
        sys.modules.pop(_key, None)
    else:
        sys.modules[_key] = _val


# ---------------------------------------------------------------------------
# Minimal adapter that produces NO audio until explicitly unlocked
# ---------------------------------------------------------------------------
class SlowStartAdapter(AudioSourceAdapter):
    """Simulates a stream source that takes time before producing audio."""

    def __init__(self, name: str = "slow-stream"):
        config = AudioSourceConfig(
            source_type=AudioSourceType.STREAM,
            name=name,
            buffer_size=256,
        )
        super().__init__(config)
        self._unlock = threading.Event()
        self.restart_count = 0

    def _start_capture(self) -> None:
        self._unlock.clear()

    def _stop_capture(self) -> None:
        self._unlock.set()

    def _read_audio_chunk(self):
        if not self._unlock.is_set():
            time.sleep(0.01)
            return None
        return np.zeros(256, dtype=np.float32)

    def unlock(self):
        self._unlock.set()

    def restart(self, reason, *, delay=0.25, max_attempts=2):
        self.restart_count += 1
        return super().restart(reason, delay=delay, max_attempts=max_attempts)


# ---------------------------------------------------------------------------
# Test 1: old default (stall_seconds=5) fires within ~10s
# ---------------------------------------------------------------------------
def test_old_default_stalls_slow_stream():
    """With stall_seconds=5, a slow stream triggers a restart within ~10s."""
    adapter = SlowStartAdapter("stall-test-old")
    controller = AudioIngestController(
        enable_monitor=True,
        monitor_interval=0.2,   # faster polling for test speed
        stall_seconds=5,
    )
    controller._monitor_grace_period = 1.0  # Shorter grace for test speed
    controller.add_source(adapter)
    adapter.start()

    # Give the monitor time to fire (grace=1s + stall=5s + margin=2s = 8s)
    deadline = time.time() + 10
    while adapter.restart_count == 0 and time.time() < deadline:
        time.sleep(0.1)

    controller.stop_all()
    assert adapter.restart_count > 0, (
        "Expected stall monitor to restart the slow adapter within 10s "
        f"with stall_seconds=5, but restart_count={adapter.restart_count}"
    )


# ---------------------------------------------------------------------------
# Test 2: fixed value (stall_seconds=30) does NOT fire in 8s for slow stream
# ---------------------------------------------------------------------------
def test_fixed_stall_seconds_does_not_fire_early():
    """With stall_seconds=30, a slow-starting stream is NOT killed in 8s."""
    adapter = SlowStartAdapter("stall-test-new")
    controller = AudioIngestController(
        enable_monitor=True,
        monitor_interval=0.2,
        stall_seconds=30,
    )
    controller._monitor_grace_period = 1.0
    controller.add_source(adapter)
    adapter.start()

    # Wait 8 seconds — the stall detector should NOT have fired
    time.sleep(8)
    restart_count_at_8s = adapter.restart_count

    controller.stop_all()
    assert restart_count_at_8s == 0, (
        "Stall monitor fired within 8s even with stall_seconds=30. "
        f"restart_count={restart_count_at_8s}"
    )


# ---------------------------------------------------------------------------
# Test 3: after adapter unlocks and produces audio, status stays RUNNING
# ---------------------------------------------------------------------------
def test_source_stays_running_once_audio_flows():
    """Once audio flows, _last_metrics_update advances and stall never fires."""
    adapter = SlowStartAdapter("stall-test-running")
    controller = AudioIngestController(
        enable_monitor=True,
        monitor_interval=0.2,
        stall_seconds=5,
    )
    controller._monitor_grace_period = 1.0
    controller.add_source(adapter)
    adapter.start()

    # Unlock after 2s (within grace period + stall window)
    time.sleep(2)
    adapter.unlock()

    # Wait another 8s — stall should NOT fire since metrics are updating
    time.sleep(8)
    restart_count = adapter.restart_count

    controller.stop_all()
    assert restart_count == 0, (
        "Stall monitor fired even though source was producing audio. "
        f"restart_count={restart_count}"
    )


# ---------------------------------------------------------------------------
# Test 4: eas_monitoring_service.py instantiates controller with stall_seconds=30
# ---------------------------------------------------------------------------
def test_eas_service_uses_30s_stall_timeout():
    """Verify eas_monitoring_service.py passes stall_seconds=30."""
    eas_service_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "eas_monitoring_service.py",
    )
    with open(eas_service_path) as f:
        source = f.read()

    assert "stall_seconds=30" in source, (
        "eas_monitoring_service.py must create AudioIngestController with "
        "stall_seconds=30 to avoid false stall detection on HTTP streams. "
        "Found:\n" + [l for l in source.splitlines() if "AudioIngestController" in l][0]
    )


# ---------------------------------------------------------------------------
# Test 5: FFmpeg -analyzeduration is 2000000 (2s), not 5000000 (5s)
# ---------------------------------------------------------------------------
def test_ffmpeg_analyzeduration_is_2s():
    """Verify the FFmpeg -analyzeduration flag is 2s, not the old 5s."""
    sources_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "app_core", "audio", "sources.py",
    )
    with open(sources_path) as f:
        source = f.read()

    # Find the analyzeduration value
    match = re.search(r"'-analyzeduration',\s*'(\d+)'", source)
    assert match, "Could not find -analyzeduration flag in sources.py"
    value = int(match.group(1))
    assert value <= 2000000, (
        f"-analyzeduration should be ≤2000000µs (2s) but found {value}µs ({value/1e6:.1f}s). "
        "A 5s analysis time combined with the old 5s stall timeout caused false stall detections."
    )


# ---------------------------------------------------------------------------
# Test 6: a source that never produces audio gets escalated to ERROR and
#         quarantined after _stall_quarantine_threshold consecutive stalls,
#         rather than restart-looping forever.
# ---------------------------------------------------------------------------
def test_persistent_stall_escalates_to_error_and_quarantine():
    """A stream that always stalls must eventually surface as ERROR + quarantine.

    Regression guard against the original behaviour: ``adapter.restart()``
    only counts a restart as failed when ``start()`` raises or returns False,
    so a stream whose ffmpeg launches fine but never delivers audio (dead
    URL, dead SDR) would otherwise cycle forever.  The monitor must track
    its own consecutive-stall counter and force ERROR + quarantine.
    """
    adapter = SlowStartAdapter("stall-test-escalate")
    controller = AudioIngestController(
        enable_monitor=True,
        monitor_interval=0.2,
        stall_seconds=2,  # tight so the test runs in seconds, not minutes
    )
    controller._monitor_grace_period = 0.5
    controller._stall_quarantine_threshold = 3
    controller.add_source(adapter)
    adapter.start()

    # Each stall cycle takes roughly grace(0.5) + stall(2) + restart_delay ~ 3s
    # so 3 cycles fit comfortably in ~15s.
    deadline = time.time() + 20
    while adapter.status != AudioSourceStatus.ERROR and time.time() < deadline:
        time.sleep(0.2)

    final_status = adapter.status
    final_quarantined = adapter.is_quarantined()
    final_error = adapter.error_message

    controller.stop_all()

    assert final_status == AudioSourceStatus.ERROR, (
        "Expected adapter to be escalated to ERROR after consecutive stalls, "
        f"got status={final_status!r}, error={final_error!r}"
    )
    assert final_quarantined, (
        "Expected adapter to be quarantined after ERROR escalation"
    )
    assert final_error and "no audio samples" in final_error, (
        f"Expected error_message to mention missing audio, got {final_error!r}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
