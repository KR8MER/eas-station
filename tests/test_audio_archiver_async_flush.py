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
import os
import threading
import time
import unittest
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_core.audio.archiver import AudioArchiver, AudioArchiverConfig  # noqa: E402


class TestAudioArchiverAsyncFlush(unittest.TestCase):
    def _make_archiver(self) -> AudioArchiver:
        config = AudioArchiverConfig(output_dir="/tmp/archiver-test", format="wav")
        archiver = AudioArchiver(
            source_name="test-source",
            config=config,
            broadcast_queue=MagicMock(),
            sample_rate=48000,
            channels=2,
        )
        return archiver

    def test_start_flush_async_resets_buffer_before_encode_finishes(self):
        archiver = self._make_archiver()

        release_encode = threading.Event()
        flush_started = threading.Event()
        captured = {}

        def fake_flush_segment(chunks, segment_start):
            captured['chunks'] = chunks
            captured['segment_start'] = segment_start
            flush_started.set()
            # Simulate a slow FFmpeg encode -- the real-world failure mode.
            release_encode.wait(timeout=5.0)

        archiver._flush_segment = fake_flush_segment

        chunk_a = np.zeros((100, 2), dtype=np.float32)
        chunk_b = np.ones((100, 2), dtype=np.float32)
        archiver._current_chunks = [chunk_a, chunk_b]
        archiver._current_segment_start = 12345.0

        archiver._start_flush_async()

        self.assertTrue(flush_started.wait(timeout=2.0), "background flush never started")

        # This is the actual regression check: the buffer must already be
        # reset -- ready to accept new real-time audio -- while the "slow
        # encode" (still blocked on release_encode) hasn't finished yet.
        self.assertEqual(archiver._current_chunks, [])

        # And new audio arriving during the "encode" must not be lost --
        # this is exactly what an archive loop iteration does next.
        new_chunk = np.full((50, 2), 2.0, dtype=np.float32)
        archiver._current_chunks.append(new_chunk)
        self.assertEqual(len(archiver._current_chunks), 1)

        release_encode.set()
        archiver._flush_thread.join(timeout=5.0)

        self.assertEqual(len(captured['chunks']), 2)
        np.testing.assert_array_equal(captured['chunks'][0], chunk_a)
        np.testing.assert_array_equal(captured['chunks'][1], chunk_b)
        self.assertEqual(captured['segment_start'], 12345.0)

    def test_start_flush_async_is_noop_with_no_pending_chunks(self):
        archiver = self._make_archiver()
        archiver._flush_segment = MagicMock()
        archiver._current_chunks = []

        archiver._start_flush_async()

        self.assertIsNone(archiver._flush_thread)
        archiver._flush_segment.assert_not_called()


if __name__ == '__main__':
    unittest.main()
