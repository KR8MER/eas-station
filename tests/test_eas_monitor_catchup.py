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

Regression tests for the unified EAS monitor catch-up drain.

Covers the recorded-alert stutter fix: the monitor loop used to read exactly
one 100 ms chunk per source per cycle, while every stalled sibling source
blocked the cycle for its full 0.1 s read timeout.  One stalled source capped
active sources at exactly real-time consumption (zero margin); two stalled
sources or any decode overhead put them permanently behind with no catch-up,
until the subscription queue engaged drop-oldest and every recorded alert was
shredded into fragments with ~100 ms holes.

The fix drains a source's entire backlog (bounded per cycle) whenever one is
waiting, so the monitor recovers from stalls faster than real time.
"""

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.audio.broadcast_queue import BroadcastQueue
from app_core.audio.eas_monitor_v3 import UnifiedEASMonitorService

SAMPLE_RATE = 16000
CHUNK = 1600  # 100 ms at 16 kHz


class FakeAdapter:
    def __init__(self, q: BroadcastQueue):
        self._q = q

    def get_eas_broadcast_queue(self) -> BroadcastQueue:
        return self._q


class FakeController:
    def __init__(self, queues):
        self._sources = {name: FakeAdapter(q) for name, q in queues.items()}


def _make_service(queues):
    svc = UnifiedEASMonitorService(audio_controller=FakeController(queues))

    def _discover(self=svc):
        with self._watchers_lock:
            for name, adapter in self.audio_controller._sources.items():
                if name not in self._watchers:
                    self._add_watcher(name, adapter)

    svc._discover_sources = _discover
    return svc


def _tone_chunk(i: int) -> np.ndarray:
    t = (np.arange(CHUNK) + i * CHUNK) / SAMPLE_RATE
    return (0.4 * np.sin(2 * np.pi * 853 * t)).astype(np.float32)


def test_backlog_drains_despite_stalled_sibling_sources():
    """An active source's backlog must drain faster than real time even when
    two sibling sources are stalled (each blocking the cycle for its read
    timeout).  The old one-chunk-per-cycle loop consumed at most 5 chunks/s
    in this scenario — half of real time — so the backlog only ever grew."""
    active_q = BroadcastQueue(name='eas-active', max_queue_size=10000)
    queues = {
        'active': active_q,
        'stalled-1': BroadcastQueue(name='eas-stalled-1', max_queue_size=10000),
        'stalled-2': BroadcastQueue(name='eas-stalled-2', max_queue_size=10000),
    }
    svc = _make_service(queues)
    svc.start()
    try:
        # Wait for the watcher subscriptions before publishing.
        deadline = time.time() + 5.0
        while time.time() < deadline and active_q.get_stats()['subscribers'] == 0:
            time.sleep(0.02)
        assert active_q.get_stats()['subscribers'] == 1

        # 20 s of audio published as an instantaneous backlog (what piles up
        # while the monitor is stalled behind slow siblings).
        n_chunks = 200
        for i in range(n_chunks):
            active_q.publish(_tone_chunk(i))

        expected_samples = n_chunks * CHUNK

        # With the catch-up drain this completes in a few seconds despite the
        # two stalled sources; without it, consumption is capped at ~5
        # chunks/s and would need 40+ seconds (and real deployments never
        # catch up at all).
        deadline = time.time() + 15.0
        while time.time() < deadline:
            with svc._audio_rings_lock:
                processed = svc._ring_total_added.get('active', 0)
            if processed >= expected_samples:
                break
            time.sleep(0.1)

        with svc._audio_rings_lock:
            processed = svc._ring_total_added.get('active', 0)
        assert processed >= expected_samples, (
            f"monitor failed to catch up: {processed}/{expected_samples} samples "
            f"processed — backlog is not being drained"
        )

        # Nothing may have been dropped: dropped chunks are audio holes in
        # recorded alerts.
        assert active_q.get_stats()['dropped_chunks'] == 0
    finally:
        svc.stop()


def test_per_source_status_reports_backlog():
    q = BroadcastQueue(name='eas-status', max_queue_size=10000)
    svc = _make_service({'src': q})
    svc.start()
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and q.get_stats()['subscribers'] == 0:
            time.sleep(0.02)

        for i in range(20):
            q.publish(_tone_chunk(i))

        deadline = time.time() + 10.0
        while time.time() < deadline:
            with svc._audio_rings_lock:
                if svc._ring_total_added.get('src', 0) >= 20 * CHUNK:
                    break
            time.sleep(0.1)

        status = svc.get_status()
        assert 'src' in status['monitors']
        assert 'queue_backlog_chunks' in status['monitors']['src']
        # Fully drained after catch-up
        assert status['monitors']['src']['queue_backlog_chunks'] == 0
    finally:
        svc.stop()
