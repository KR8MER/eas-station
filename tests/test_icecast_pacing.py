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

"""Regression tests for duration-based Icecast feed pacing.

An injected EAS alert is queued as 50 ms chunks while a stream source's
live chunks are 85 ms (4096 frames at 48 kHz). The feed loop used to
release one buffered chunk per chunk read, so the alert went out at
50/85 = 59% of real time -- measured on air as ~50% for ~30 s, heard as
stutter. These tests drive ``ByteCreditPacer`` with those exact sizes.
"""

import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.icecast_pacing import ByteCreditPacer

_BYTES_PER_SEC = 48000 * 2  # mono int16 at 48 kHz
_EAS_CHUNK = b"\x00" * int(_BYTES_PER_SEC * 0.050)    # injector: 50 ms
_LIVE_CHUNK = b"\x00" * (4096 * 2)                    # stream source: ~85 ms


def _simulate(seconds: float) -> float:
    """Feed live chunks for *seconds* with 17 s of EAS queued; return out/in."""
    pacer = ByteCreditPacer()
    buffer = deque([_EAS_CHUNK] * 349)
    bytes_in = bytes_out = 0
    for _ in range(int(seconds * _BYTES_PER_SEC / len(_LIVE_CHUNK))):
        buffer.append(_LIVE_CHUNK)
        pacer.earn(len(_LIVE_CHUNK))
        bytes_in += len(_LIVE_CHUNK)
        bytes_out += sum(len(c) for c in pacer.release(buffer))
    return bytes_out / bytes_in


def test_eas_backlog_plays_in_real_time_despite_mismatched_chunk_sizes():
    # One-in/one-out would give 50/85 = 0.59 over the alert window.
    assert abs(_simulate(10.0) - 1.0) < 0.02


def test_long_run_output_matches_input():
    assert abs(_simulate(120.0) - 1.0) < 0.01


def test_idle_time_does_not_bank_credit_for_a_later_burst():
    pacer = ByteCreditPacer()
    empty = deque()
    for _ in range(100):
        pacer.earn(len(_LIVE_CHUNK))
        assert pacer.release(empty) == []
    buffer = deque([_EAS_CHUNK] * 50)
    pacer.earn(len(_EAS_CHUNK))
    assert len(pacer.release(buffer)) == 1


def test_starved_read_releases_exactly_one_chunk():
    pacer = ByteCreditPacer()
    buffer = deque([_LIVE_CHUNK] * 10)
    pacer.earn_one_chunk(buffer)
    assert len(pacer.release(buffer)) == 1
    assert len(buffer) == 9


def test_starved_read_on_empty_buffer_is_a_no_op():
    pacer = ByteCreditPacer()
    buffer = deque()
    pacer.earn_one_chunk(buffer)
    assert pacer.release(buffer) == []


def test_feed_loop_releases_through_the_pacer():
    """The feed loop must not fall back to a fixed one-chunk-per-read write."""
    import inspect

    from app_core.audio.icecast_output import IcecastStreamer

    source = inspect.getsource(IcecastStreamer._feed_loop)
    assert "pacer.release(buffer)" in source
    assert "pacer.earn(len(pcm_bytes))" in source
    assert "chunk = buffer.popleft()" not in source
