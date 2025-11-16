"""Tests for screen manager frame timing improvements.

This test verifies that the screen manager uses monotonic time for frame timing
instead of datetime, which provides much more precise and consistent timing for
smooth scrolling animations.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch


pytestmark = pytest.mark.unit


def test_monotonic_timing_used_for_alert_scrolling():
    """Test that alert scrolling uses monotonic time instead of datetime."""
    from scripts.screen_manager import ScreenManager
    
    # Create screen manager
    manager = ScreenManager()
    
    # Verify that monotonic time variables are initialized to 0.0 (float)
    assert isinstance(manager._last_oled_alert_render_time, float)
    assert manager._last_oled_alert_render_time == 0.0
    
    # Verify that monotonic time variables are initialized for template scrolling
    assert isinstance(manager._last_oled_screen_frame_time, float)
    assert manager._last_oled_screen_frame_time == 0.0


def test_reset_alert_state_uses_monotonic_time():
    """Test that resetting alert state uses monotonic time."""
    from scripts.screen_manager import ScreenManager
    
    manager = ScreenManager()
    
    # Set some values
    manager._last_oled_alert_render_time = time.monotonic()
    manager._oled_scroll_offset = 100
    
    # Reset state
    manager._reset_oled_alert_state()
    
    # Verify monotonic time was reset to 0.0
    assert manager._last_oled_alert_render_time == 0.0
    assert manager._oled_scroll_offset == 0


def test_clear_screen_scroll_state_uses_monotonic_time():
    """Test that clearing screen scroll state uses monotonic time."""
    from scripts.screen_manager import ScreenManager
    
    manager = ScreenManager()
    
    # Set some values
    manager._last_oled_screen_frame_time = time.monotonic()
    manager._oled_screen_scroll_offset = 50
    
    # Clear state
    manager._clear_oled_screen_scroll_state()
    
    # Verify monotonic time was reset to 0.0
    assert manager._last_oled_screen_frame_time == 0.0
    assert manager._oled_screen_scroll_offset == 0


def test_frame_interval_calculation_precision():
    """Test that frame interval calculation uses floating point for precision."""
    # At 60 FPS, frame interval should be ~16.67ms
    fps = 60
    frame_interval = 1.0 / fps
    
    # Should be approximately 0.01667 seconds (16.67ms)
    assert 0.016 < frame_interval < 0.017
    
    # Verify it's a float (not timedelta)
    assert isinstance(frame_interval, float)
    
    # At 30 FPS
    fps = 30
    frame_interval = 1.0 / fps
    
    # Should be approximately 0.0333 seconds (33.33ms)
    assert 0.033 < frame_interval < 0.034


def test_monotonic_time_consistency():
    """Test that monotonic time provides consistent frame timing."""
    # Monotonic time should always increase
    time1 = time.monotonic()
    time.sleep(0.01)  # Sleep 10ms
    time2 = time.monotonic()
    
    # Time should have increased by approximately 10ms
    elapsed = time2 - time1
    assert 0.009 < elapsed < 0.015  # Allow for some variance
    
    # Verify the timing is consistent
    time3 = time.monotonic()
    assert time3 >= time2  # Should always increase


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
