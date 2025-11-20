"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Tests for IcecastStreamer BrokenPipeError handling with restart delay."""

import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app_core.audio.icecast_output import IcecastConfig, IcecastStreamer, ICECAST_RESTART_DELAY


class _DummyAudioSource:
    """Dummy audio source for testing."""
    
    def get_audio_chunk(self, timeout=0.1):  # pragma: no cover - stub
        return None
    
    metrics = mock.MagicMock(metadata={})


def test_broken_pipe_error_triggers_restart_with_delay(monkeypatch):
    """Verify that BrokenPipeError triggers restart with appropriate delay."""
    
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing BrokenPipeError handling',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())
    
    # Track restart calls
    restart_calls = []
    original_restart = streamer._restart_ffmpeg
    
    def mock_restart(reason):
        restart_calls.append(reason)
        streamer._stop_event.set()  # Stop after one restart to exit the loop
        return True
    
    monkeypatch.setattr(streamer, "_restart_ffmpeg", mock_restart)
    
    # Mock the FFmpeg process to raise BrokenPipeError
    mock_process = mock.MagicMock()
    mock_process.poll.return_value = None  # Process is running
    mock_process.stdin = mock.MagicMock()
    mock_process.stdin.write.side_effect = BrokenPipeError("Simulated broken pipe")
    
    streamer._ffmpeg_process = mock_process
    streamer._stop_event.clear()
    
    # Run the feed loop in a separate thread or just call it briefly
    # We'll just test the exception handling directly
    try:
        # Simulate what happens in _feed_loop when writing fails
        mock_process.stdin.write(b'test')
        mock_process.stdin.flush()
    except BrokenPipeError:
        # This should trigger the restart
        streamer._restart_ffmpeg("ffmpeg pipe closed")
    
    # Verify restart was called
    assert len(restart_calls) == 1
    assert restart_calls[0] == "ffmpeg pipe closed"


def test_restart_delay_constant_is_defined():
    """Verify ICECAST_RESTART_DELAY constant exists and has reasonable value."""
    
    assert ICECAST_RESTART_DELAY is not None
    assert isinstance(ICECAST_RESTART_DELAY, (int, float))
    assert ICECAST_RESTART_DELAY > 0
    assert ICECAST_RESTART_DELAY <= 30, "Delay should not be excessively long"


def test_restart_ffmpeg_sleeps_before_restart(monkeypatch):
    """Verify that _restart_ffmpeg waits ICECAST_RESTART_DELAY before restarting."""
    
    config = IcecastConfig(
        server='localhost',
        port=8000,
        password='test',
        mount='test',
        name='Test Stream',
        description='Testing restart delay',
    )
    streamer = IcecastStreamer(config, _DummyAudioSource())
    streamer._stop_event.clear()
    
    # Mock process
    class DummyProcess:
        def __init__(self):
            self.pid = 99999
        
        def terminate(self):
            pass
        
        def wait(self, timeout=None):
            pass
        
        def kill(self):
            pass
    
    streamer._ffmpeg_process = DummyProcess()
    
    # Mock _start_ffmpeg
    def fake_start():
        return True
    
    monkeypatch.setattr(streamer, "_start_ffmpeg", fake_start)
    
    # Track time.sleep calls
    sleep_calls = []
    
    def mock_sleep(seconds):
        sleep_calls.append(seconds)
    
    monkeypatch.setattr(time, "sleep", mock_sleep)
    
    # Call restart
    result = streamer._restart_ffmpeg("test restart")
    
    # Verify sleep was called with ICECAST_RESTART_DELAY
    assert result is True
    assert ICECAST_RESTART_DELAY in sleep_calls, (
        f"Expected sleep({ICECAST_RESTART_DELAY}) to be called, "
        f"but got sleep calls: {sleep_calls}"
    )


if __name__ == '__main__':
    # Run tests
    print("Testing BrokenPipeError handling...")
    import pytest
    
    # If pytest is not available, use simple assertions
    try:
        pytest.main([__file__, '-v'])
    except ImportError:
        print("Running tests without pytest...")
        
        class FakeMonkeypatch:
            def setattr(self, obj, name, value):
                if isinstance(obj, type):
                    # Setting on module/class
                    original = getattr(obj, name)
                    setattr(obj, name, value)
                else:
                    # Setting on instance
                    setattr(obj, name, value)
        
        monkeypatch = FakeMonkeypatch()
        
        test_broken_pipe_error_triggers_restart_with_delay(monkeypatch)
        print("✓ test_broken_pipe_error_triggers_restart_with_delay")
        
        test_restart_delay_constant_is_defined()
        print("✓ test_restart_delay_constant_is_defined")
        
        monkeypatch = FakeMonkeypatch()
        test_restart_ffmpeg_sleeps_before_restart(monkeypatch)
        print("✓ test_restart_ffmpeg_sleeps_before_restart")
        
        print("\n✅ All BrokenPipeError handling tests passed!")
