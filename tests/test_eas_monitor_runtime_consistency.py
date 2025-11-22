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

import time
import numpy as np
from unittest.mock import MagicMock, patch

from app_core.audio.eas_monitor import ContinuousEASMonitor


class DummyAudioManager:
    """Dummy audio manager for testing."""
    def __init__(self):
        self.sample_rate = 16000
        
    def get_active_source(self):
        return "test-source"
    
    def read_audio(self, chunk_samples):
        """Return dummy audio samples."""
        return np.zeros(chunk_samples, dtype=np.float32)


def _create_monitor() -> ContinuousEASMonitor:
    """Create a test monitor instance."""
    monitor = ContinuousEASMonitor(
        audio_manager=DummyAudioManager(),
        save_audio_files=False,
    )
    monitor.alert_callback = MagicMock()
    return monitor


def test_runtime_consistency_after_restart():
    """
    Test that runtime values remain consistent after a watchdog restart.
    
    This test verifies the fix for the issue where runtime would jump between
    values (e.g., 6 min -> 2 sec -> 6 min) when the watchdog restarted the
    monitor thread.
    """
    monitor = _create_monitor()
    
    # Simulate monitor running for some time
    monitor._start_time = time.time() - 60.0  # Started 60 seconds ago
    
    # Simulate decoder processing some samples
    monitor._streaming_decoder.samples_processed = 16000 * 60  # 60 seconds of audio
    
    # Get initial status
    status1 = monitor.get_status()
    
    # Verify initial state
    assert status1['running'] is False  # Not actually started
    assert status1['wall_clock_runtime_seconds'] > 0  # Should have elapsed time
    initial_wall_clock = status1['wall_clock_runtime_seconds']
    
    # Simulate watchdog restart (this should reset _start_time now)
    monitor._restart_monitor_thread()
    
    # Small delay to simulate time passing
    time.sleep(0.1)
    
    # Get status after restart
    status2 = monitor.get_status()
    
    # After restart, both timers should be near zero (recently restarted)
    # The fix ensures _start_time is reset in _restart_monitor_thread()
    assert status2['wall_clock_runtime_seconds'] < 1.0, \
        "wall_clock_runtime_seconds should be near 0 after restart"
    
    # Runtime should also be small since decoder was reset
    assert status2['runtime_seconds'] < 1.0, \
        "runtime_seconds should be near 0 after restart"
    
    # They should be reasonably close to each other (within 1 second)
    time_diff = abs(status2['wall_clock_runtime_seconds'] - status2['runtime_seconds'])
    assert time_diff < 1.0, \
        f"wall_clock and runtime should be consistent, but differ by {time_diff}s"


def test_start_time_reset_on_restart():
    """
    Test that _start_time is properly reset when monitor thread restarts.
    
    This is the core fix for the runtime inconsistency issue.
    """
    monitor = _create_monitor()
    
    # Set initial start time (simulating a running monitor)
    initial_start_time = time.time() - 300.0  # Started 5 minutes ago
    monitor._start_time = initial_start_time
    
    # Restart the monitor thread
    monitor._restart_monitor_thread()
    
    # Verify start time was reset to current time
    assert monitor._start_time is not None, "_start_time should not be None after restart"
    
    # Should be very recent (within last second)
    time_since_restart = time.time() - monitor._start_time
    assert time_since_restart < 1.0, \
        f"_start_time should be reset to current time, but was {time_since_restart}s ago"
    
    # Should definitely not be the old start time
    assert monitor._start_time > initial_start_time, \
        "_start_time should be newer than the old value"


def test_runtime_values_consistency():
    """
    Test that runtime_seconds and wall_clock_runtime_seconds are consistent
    during normal operation.
    """
    monitor = _create_monitor()
    
    # Start the monitor
    current_time = time.time()
    monitor._start_time = current_time
    
    # Simulate processing audio for 10 seconds
    samples_for_10_sec = 16000 * 10  # 16kHz * 10 seconds
    monitor._streaming_decoder.samples_processed = samples_for_10_sec
    
    # Advance time by 10 seconds
    with patch('time.time', return_value=current_time + 10.0):
        status = monitor.get_status()
        
        # Both should be around 10 seconds
        assert 9.0 <= status['runtime_seconds'] <= 11.0, \
            f"runtime_seconds should be ~10s but is {status['runtime_seconds']}"
        
        assert 9.0 <= status['wall_clock_runtime_seconds'] <= 11.0, \
            f"wall_clock_runtime_seconds should be ~10s but is {status['wall_clock_runtime_seconds']}"
        
        # They should be very close to each other (within 1 second)
        time_diff = abs(status['wall_clock_runtime_seconds'] - status['runtime_seconds'])
        assert time_diff < 1.0, \
            f"Runtime values should be consistent, differ by {time_diff}s"


def test_samples_per_second_calculation():
    """
    Test that samples_per_second is calculated correctly and doesn't
    cause issues after restart.
    """
    monitor = _create_monitor()
    
    # Set up monitor with some runtime
    current_time = time.time()
    monitor._start_time = current_time - 5.0  # Running for 5 seconds
    
    # Process 5 seconds of audio at 16kHz
    monitor._streaming_decoder.samples_processed = 16000 * 5
    
    status = monitor.get_status()
    
    # Should be processing at approximately 16000 samples/sec
    assert status['samples_per_second'] > 0, "samples_per_second should be positive"
    assert 15000 <= status['samples_per_second'] <= 17000, \
        f"samples_per_second should be ~16000 but is {status['samples_per_second']}"
    
    # Health should be good (close to 100%)
    assert status['health_percentage'] >= 0.9, \
        f"health_percentage should be high but is {status['health_percentage']}"


def test_restart_count_increments():
    """
    Test that restart_count is properly tracked.
    """
    monitor = _create_monitor()
    
    initial_count = monitor._restart_count
    assert initial_count == 0, "Initial restart count should be 0"
    
    # Restart once
    monitor._restart_monitor_thread()
    assert monitor._restart_count == 1, "Restart count should increment to 1"
    
    # Restart again
    monitor._restart_monitor_thread()
    assert monitor._restart_count == 2, "Restart count should increment to 2"
    
    # Verify it's in the status
    status = monitor.get_status()
    assert status['restart_count'] == 2, "Status should include restart_count"
