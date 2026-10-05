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

"""Regression tests for wall-clock Icecast feed pacing.

1. One-in/one-out: an injected EAS alert is queued as 50 ms chunks while a
   stream source's live chunks are 85 ms, so the alert went out at ~59% of
   real time (measured ~50% for ~30 s, heard as stutter).
2. Byte-counting fixed that but starved bursty HTTP sources -- only the
   first chunk of each burst earned output -- WNCI ran at ~70% and
   listeners' players kept reconnecting.

``RealTimePacer`` releases by elapsed wall-clock time, so both cases come
out at real time.
"""

import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.icecast_pacing import RealTimePacer

_BPS = 48000 * 2  # mono int16 at 48 kHz
_EAS_CHUNK = b"\x00" * int(_BPS * 0.050)   # injector: 50 ms
_LIVE_CHUNK = b"\x00" * (4096 * 2)         # stream source: ~85.3 ms


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _pacer(clock):
    return RealTimePacer(lambda: _BPS, clock=clock)


def _run(buffer, clock, pacer, seconds, burst):
    """Deliver live chunks in bursts of *burst* at the source's real rate."""
    out = 0
    period = len(_LIVE_CHUNK) / _BPS * burst
    for _ in range(int(seconds / period)):
        clock.t += period
        buffer.extend([_LIVE_CHUNK] * burst)
        out += sum(map(len, pacer.release(buffer)))
    return out / (_BPS * seconds)


def test_bursty_source_is_released_in_real_time():
    clock = _Clock()
    pacer = _pacer(clock)
    buffer = deque([_LIVE_CHUNK] * 60)        # ~5 s prebuffer
    pacer.release(buffer)
    assert abs(_run(buffer, clock, pacer, 120.0, burst=4) - 1.0) < 0.01


def test_eas_backlog_plays_in_real_time_despite_mismatched_chunk_sizes():
    clock = _Clock()
    pacer = _pacer(clock)
    buffer = deque([_EAS_CHUNK] * 349)        # 17.45 s alert, below high water
    pacer.release(buffer)
    released = []
    for _ in range(int(10 / 0.0853)):         # 10 s of live 85 ms reads
        clock.t += len(_LIVE_CHUNK) / _BPS
        buffer.append(_LIVE_CHUNK)
        released.extend(pacer.release(buffer))
    eas_seconds = sum(len(c) for c in released if c is _EAS_CHUNK) / _BPS
    assert abs(eas_seconds - 10.0) < 0.1


def test_long_backlog_drains_slightly_faster_than_real_time():
    clock = _Clock()
    pacer = _pacer(clock)
    buffer = deque([_LIVE_CHUNK] * 600)       # ~51 s, above the 20 s high water
    pacer.release(buffer)
    rate = _run(buffer, clock, pacer, 10.0, burst=1)
    assert 1.01 < rate < 1.03


def test_idle_time_does_not_bank_credit_for_a_later_burst():
    clock = _Clock()
    pacer = _pacer(clock)
    empty = deque()
    pacer.release(empty)
    clock.t += 30.0
    assert pacer.release(empty) == []
    buffer = deque([_EAS_CHUNK] * 50)
    clock.t += 0.05
    assert len(pacer.release(buffer)) <= 2   # not a 30 s burst


def test_feed_loop_releases_through_the_pacer():
    """The feed loop must not fall back to chunk- or read-counted writes."""
    import inspect

    from app_core.audio.icecast_output import IcecastStreamer

    source = inspect.getsource(IcecastStreamer._feed_loop)
    assert "RealTimePacer(" in source
    assert "pacer.release(buffer)" in source
    assert "chunk = buffer.popleft()" not in source
