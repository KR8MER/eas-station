"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""Regression test for a self-deadlock in AutoStreamingService._monitor_loop().

Step 5 of the monitor loop used to call self.remove_source() while still
holding self._lock (acquired for step 4), and remove_source() re-acquires
that same non-reentrant threading.Lock() -- the monitor thread deadlocked
against itself, which permanently blocked every other caller of
get_status() (including the audio-service's Redis metrics loop, which is
what the web UI's health status depends on).
"""

import threading
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.audio.auto_streaming import AutoStreamingService
from app_core.audio.ingest import AudioSourceStatus


class _FakeStreamer:
    def __init__(self):
        self.stopped = False

    def get_stats(self):
        return {"running": True}

    def stop(self):
        self.stopped = True

    def start(self):
        return True

    class config:
        mount = "/fake.mp3"


class _FakeSourceAdapter:
    def __init__(self, status):
        self.status = status


class _FakeAudioController:
    def __init__(self, sources):
        self._sources = sources

    def get_all_sources(self):
        return self._sources


def test_monitor_loop_step5_does_not_self_deadlock():
    """A stopped source with an existing streamer must be removed without
    the monitor thread ever hanging -- reproduces the exact scenario that
    froze the audio-service's Redis heartbeat in production."""
    stopped_source = _FakeSourceAdapter(AudioSourceStatus.STOPPED)
    controller = _FakeAudioController({"src1": stopped_source})

    service = AutoStreamingService(audio_controller=controller)
    service._streamers["src1"] = _FakeStreamer()

    # Run exactly one iteration: patch time.sleep(10.0) (the end-of-iteration
    # marker) to stop the loop immediately instead of actually sleeping.
    import app_core.audio.auto_streaming as auto_streaming_module

    real_sleep = time.sleep

    def _fast_sleep(seconds):
        if seconds == 10.0:
            service._stop_event.set()
            return
        real_sleep(min(seconds, 0.01))

    auto_streaming_module.time.sleep = _fast_sleep
    try:
        thread = threading.Thread(target=service._monitor_loop, daemon=True)
        thread.start()
        thread.join(timeout=5.0)

        assert not thread.is_alive(), (
            "AutoStreamingService._monitor_loop() deadlocked -- step 5 is "
            "calling remove_source() while still holding self._lock"
        )
    finally:
        auto_streaming_module.time.sleep = real_sleep
        service._stop_event.set()

    # The stopped source's streamer must have actually been removed.
    assert "src1" not in service._streamers

    # And the lock must be free -- a second, independent caller (mirroring
    # the metrics loop's get_status() call) must not block.
    acquired = service._lock.acquire(timeout=2.0)
    assert acquired, "self._lock was left held after the monitor loop exited"
    service._lock.release()
