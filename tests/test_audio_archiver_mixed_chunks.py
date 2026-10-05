#!/usr/bin/env python3
"""
Regression test for AudioArchiver's background-flush fix.

Before the fix, _flush_segment() ran inline in _archive_loop() -- encoding a
full segment via FFmpeg (~14s wall time for 600s of 48kHz stereo on a
Raspberry Pi, measured live) blocked the loop from draining its
BroadcastQueue subscriber for that entire window, causing the upstream
publisher to drop chunks for this subscriber on every single segment flush
("Audio chunks dropped for subscriber 'archiver-<name>' ... consuming
slower than real time").

_start_flush_async() now snapshots and resets the in-memory chunk buffer
synchronously, then hands the actual encode/write/prune off to a background
thread -- so the archive loop's queue-draining is never blocked by how long
encoding takes.
"""
import sys
import time
import os
"""An EAS injection into a stereo SDR source must not lose the archive segment.

SDR sources publish ``(frames, 2)`` chunks; the EAS stream injector
publishes mono 1-D chunks into the same queue. ``_flush_segment`` used to
``np.concatenate`` them directly, which raised "all the input arrays must
have same number of dimensions" in the flush thread and dropped the
segment every time an alert played.
"""

import os
import sys
import time
import wave
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_core.audio.archiver import (  # noqa: E402
    AudioArchiver,
    AudioArchiverConfig,
    _match_chunk_shapes,
)


def test_stereo_segment_with_injected_mono_chunk_is_written(tmp_path):
    config = AudioArchiverConfig(output_dir=str(tmp_path), format="wav", silence_threshold=0.0)
    archiver = AudioArchiver(
        source_name="sdr-test", config=config, broadcast_queue=MagicMock(),
        sample_rate=48000, channels=2,
    )
    live = np.full((480, 2), 0.25, dtype=np.float32)
    eas = np.full(2400, 0.5, dtype=np.float32)  # injector: 50 ms mono

    archiver._flush_segment([live, eas, live], segment_start=time.time())

    files = list(tmp_path.rglob("*.wav"))
    assert len(files) == 1
    with wave.open(str(files[0])) as wf:
        assert wf.getnchannels() == 2
        assert wf.getnframes() == 480 + 2400 + 480


def test_upmixed_mono_chunk_is_duplicated_into_every_channel():
    out = _match_chunk_shapes([np.zeros((4, 2)), np.array([1.0, 2.0])])
    assert out[1].tolist() == [[1.0, 1.0], [2.0, 2.0]]


def test_uniform_segments_pass_through_untouched():
    mono = [np.zeros(10), np.ones(10)]
    stereo = [np.zeros((5, 2)), np.ones((5, 2))]
    assert _match_chunk_shapes(mono) is mono
    assert _match_chunk_shapes(stereo) is stereo
