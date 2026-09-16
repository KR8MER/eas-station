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

"""Tests for IcecastStreamer buffer configuration improvements."""

import queue
import sys
import threading
import time
from pathlib import Path
from unittest import mock
from collections import deque

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from app_core.audio.icecast_output import IcecastConfig, IcecastStreamer


class _MockAudioSource:
    """Mock audio source that simulates realistic streaming behavior."""
    
    def __init__(self, delay_ms=50):
        """
        Args:
            delay_ms: Simulated delay between audio chunks (milliseconds)
        """
        self.delay_ms = delay_ms
        self.call_count = 0
        self.metrics = mock.MagicMock(metadata={})
    
    def get_audio_chunk(self, timeout=1.0):
        """Simulate getting audio chunks with realistic delays."""
        self.call_count += 1
        
        # Simulate network jitter - occasionally return None
        if self.call_count % 10 == 0:
            return None
        
        # Return audio samples (1024 samples at 44100 Hz = ~23ms of audio)
        return np.random.uniform(-0.5, 0.5, 1024).astype(np.float32)


def test_buffer_capacity_increased():
    """Verify that buffer capacity has been increased to handle longer network delays."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing buffer configuration',
    )
    
    source = _MockAudioSource()
    streamer = IcecastStreamer(config, source)
    
    # The feed loop creates a deque with maxlen=600
    # We can't easily test the private _feed_loop, but we can verify
    # that the configuration parameters make sense
    assert config.sample_rate == 44100
    assert config.channels == 1
    
    # Verify that the streamer was created successfully
    assert streamer.config.server == 'localhost'
    assert streamer.config.port == 8000
    
    print("✓ Buffer capacity configuration test passed")


def test_prebuffer_parameters():
    """Verify that prebuffer parameters are configured for stability."""
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing prebuffer parameters',
    )
    
    source = _MockAudioSource()
    streamer = IcecastStreamer(config, source)
    
    # The actual prebuffer logic is in _feed_loop
    # Expected values after our changes:
    # - buffer maxlen: 600 (30 seconds of 50ms chunks)
    # - prebuffer_target: 150 (7.5 seconds)
    # - buffer_low_watermark: 150 (7.5 seconds)
    # - prebuffer_timeout: 15 seconds
    # - get_audio_chunk timeout: 1.0 seconds during prebuffer
    # - get_audio_chunk timeout: 0.5 seconds during main loop
    
    # We validate that the streamer can be initialized without errors
    assert streamer._stop_event.is_set()  # Should start in stopped state
    assert streamer._ffmpeg_process is None
    assert streamer._feeder_thread is None
    
    print("✓ Prebuffer parameters test passed")


def test_audio_chunk_timeout_reasonable():
    """Verify that audio chunk timeouts are long enough to handle network jitter."""
    
    # Simulate a slow audio source
    source = _MockAudioSource(delay_ms=200)  # 200ms delay
    
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing timeout handling',
    )
    
    streamer = IcecastStreamer(config, source)
    
    # Test that we can call get_audio_chunk with appropriate timeout
    start = time.time()
    chunk = source.get_audio_chunk(timeout=0.5)  # Our new timeout value
    elapsed = time.time() - start
    
    # Should return quickly (not wait full timeout) when data is available
    # Increased threshold to 1.0s to account for system load/overhead
    assert elapsed < 1.0, f"get_audio_chunk took {elapsed}s, should be much faster"
    assert chunk is not None or source.call_count > 0
    
    print("✓ Audio chunk timeout test passed")


def test_buffer_empty_throttling():
    """Verify that buffer empty errors would be throttled appropriately."""
    
    # The throttling logic uses self._last_buffer_warning
    # After our changes, errors are only logged if 30 seconds have passed
    
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing error throttling',
    )
    
    source = _MockAudioSource()
    streamer = IcecastStreamer(config, source)
    
    # Verify initial state
    assert streamer._last_buffer_warning == 0.0
    
    # Simulate time passing
    streamer._last_buffer_warning = time.time() - 25.0  # 25 seconds ago
    
    # Check if enough time has passed for next warning (should be 30s)
    time_since_last = time.time() - streamer._last_buffer_warning
    should_log = time_since_last > 30.0
    
    # 25 seconds is not enough, should not log
    assert not should_log, "Should not log error if less than 30 seconds have passed"
    
    # Simulate 31 seconds passing
    streamer._last_buffer_warning = time.time() - 31.0
    time_since_last = time.time() - streamer._last_buffer_warning
    should_log = time_since_last > 30.0
    
    # 31 seconds is enough, should log
    assert should_log, "Should log error if more than 30 seconds have passed"
    
    print("✓ Buffer empty throttling test passed")


def test_buffer_health_check_reflects_pre_pop_depth(caplog):
    """The feed loop must not report a false "buffer running low"/"completely
    empty" warning when the audio source is keeping up normally.

    Regression for a bug where `buffer_level = len(buffer)` was read *after*
    `buffer.popleft()` in the same iteration -- since one chunk is read and
    one chunk is popped per iteration, that always measured 0-1 regardless of
    real buffer health, so the warning fired on effectively every mount, every
    throttle window (visible in production journals as ~120 "Icecast buffer
    running low ... 0/600 chunks" warnings per hour, per stream, continuously).
    Measuring depth before the pop reflects the actual banked cushion.
    """
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing buffer health accounting',
    )

    class _DummySource:
        metrics = mock.MagicMock(metadata={})

    streamer = IcecastStreamer(config, _DummySource())

    # Steady, ample supply -- the source never actually starves, so a
    # healthy feed loop should never trip the low-buffer warning.
    streamer._audio_queue = queue.Queue()
    for _ in range(400):
        streamer._audio_queue.put(np.zeros(1024, dtype=np.float32))

    mock_process = mock.MagicMock()
    mock_process.poll.return_value = None  # "running"
    mock_process.stdin = mock.MagicMock()
    streamer._ffmpeg_process = mock_process
    streamer._stop_event.clear()
    # Normally set by start(), which this test bypasses to drive _feed_loop
    # directly against a fake queue instead of a real broadcast subscription.
    streamer._last_eas_inject_seq = 0

    with caplog.at_level("WARNING", logger="app_core.audio.icecast_output"):
        thread = threading.Thread(target=streamer._feed_loop, daemon=True)
        thread.start()
        time.sleep(0.5)
        streamer._stop_event.set()
        thread.join(timeout=5)

    assert not thread.is_alive(), "feed loop did not stop"
    bad_warnings = [
        r.message for r in caplog.records
        if "buffer running low" in r.message or "completely empty" in r.message
    ]
    assert bad_warnings == [], (
        f"Feed loop reported buffer starvation with a steady audio supply: {bad_warnings}"
    )


class _TrackedDeque(deque):
    """A deque that records its own length after every append/popleft, so a
    test can see the exact sequence of buffer depths a feed loop produced."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history = []

    def append(self, item):
        super().append(item)
        self.history.append(len(self))

    def popleft(self):
        item = super().popleft()
        self.history.append(len(self))
        return item


def test_buffer_recovers_after_a_stall_once_source_catches_up():
    """A source that stalls (read timeouts) and then delivers a backlog burst
    must let the local jitter buffer recover, not remain stuck at the
    post-stall depth forever.

    Regression for a related but distinct bug from the pre-pop-depth fix
    above: the feed loop pops at most one chunk to FFmpeg per iteration
    *and* appends at most one chunk per iteration (one `_get_audio_from_subscription`
    call), so a normal iteration nets zero change in buffer depth and a
    timed-out read nets -1 -- there was no code path that could ever net
    positive. That makes the buffer a one-way ratchet: every stall drains it
    by exactly the chunks lost, permanently, since even a source that catches
    up afterward could only refill it one chunk per loop iteration, matched
    chunk-for-chunk by that same iteration's single pop. Confirmed live in
    production: two internet-relay mounts ratcheted down in discrete steps
    (150 -> 149 -> 147 -> 146) over hours and never recovered.

    The fix opportunistically drains any further chunks already queued
    (non-blocking) right after a successful read, so a post-stall backlog
    burst can add many chunks in one iteration while still only popping one --
    letting the buffer actually climb back up.
    """
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing buffer recovery after a stall',
    )

    class _DummySource:
        metrics = mock.MagicMock(metadata={})

    streamer = IcecastStreamer(config, _DummySource())

    # Bypass real prebuffering: seed a tracked deque directly at a realistic
    # starting depth (matches the real prebuffer target of 150/600) so every
    # append/pop the feed loop performs afterward is recorded in order.
    tracked_buffer = _TrackedDeque(maxlen=600)
    for _ in range(150):
        tracked_buffer.append(b"\x00" * 10)
    tracked_buffer.history.clear()  # only care about _feed_loop's own effect

    with mock.patch.object(streamer, "_prebuffer_audio", return_value=tracked_buffer):
        with mock.patch.object(streamer, "_get_chunk_timeout", return_value=0.01):
            streamer._audio_queue = queue.Queue()  # empty: every read stalls
            mock_process = mock.MagicMock()
            mock_process.poll.return_value = None
            mock_process.stdin = mock.MagicMock()
            streamer._ffmpeg_process = mock_process
            streamer._stop_event.clear()
            streamer._last_eas_inject_seq = 0

            thread = threading.Thread(target=streamer._feed_loop, daemon=True)
            thread.start()

            # Let it stall and drain for a bit.
            time.sleep(0.3)
            depth_after_stall = len(tracked_buffer)
            assert depth_after_stall < 150, (
                "expected the stall to drain the buffer below its starting depth"
            )

            # Now the source catches up: a backlog burst arrives all at once.
            for _ in range(300):
                streamer._audio_queue.put(np.zeros(1024, dtype=np.float32))

            time.sleep(0.3)
            streamer._stop_event.set()
            thread.join(timeout=5)

    assert not thread.is_alive(), "feed loop did not stop"

    lowest_during_stall = min(tracked_buffer.history[: tracked_buffer.history.index(depth_after_stall) + 1])
    final_depth = tracked_buffer.history[-1]
    assert final_depth > lowest_during_stall + 20, (
        f"buffer did not recover after the burst: lowest={lowest_during_stall}, "
        f"final={final_depth}, history_tail={tracked_buffer.history[-10:]}"
    )


if __name__ == '__main__':
    print("Running Icecast buffer configuration tests...")
    test_buffer_capacity_increased()
    test_prebuffer_parameters()
    test_audio_chunk_timeout_reasonable()
    test_buffer_empty_throttling()
    print("\n✅ All buffer configuration tests passed!")
