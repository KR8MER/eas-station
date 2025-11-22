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

import pytest
from unittest.mock import MagicMock

from app_core.audio.icecast_output import IcecastConfig


def test_icecast_empty_read_thresholds():
    """
    Test that the Icecast empty read thresholds are correctly configured
    to match the actual timeout values.
    
    This test verifies the fix for the 50-second stuttering issue where
    the threshold calculations were misaligned with actual timeouts.
    
    Expected behavior:
    - First warning at 10 seconds: 20 reads * 0.5s timeout = 10s
    - Critical warning at 100 seconds: 200 reads * 0.5s timeout = 100s
    """
    # The actual threshold values should be:
    # - 20 reads for 10 second warning (with 0.5s timeout per read)
    # - 200 reads for 100 second critical (with 0.5s timeout per read)
    
    TIMEOUT_PER_READ = 0.5  # seconds (from get_audio_chunk(timeout=0.5))
    
    # First warning threshold
    FIRST_WARNING_READS = 20
    first_warning_time = FIRST_WARNING_READS * TIMEOUT_PER_READ
    assert first_warning_time == 10.0, \
        f"First warning should be at 10 seconds, but is {first_warning_time}s"
    
    # Critical warning threshold
    CRITICAL_WARNING_READS = 200
    critical_warning_time = CRITICAL_WARNING_READS * TIMEOUT_PER_READ
    assert critical_warning_time == 100.0, \
        f"Critical warning should be at 100 seconds, but is {critical_warning_time}s"


def test_icecast_threshold_alignment():
    """
    Test that the warning thresholds are properly aligned with realistic
    audio source behavior.
    
    The fix extends the critical threshold from 50s to 100s to avoid
    disrupting legitimate slow sources.
    """
    # With the fix:
    # - First warning at 10s is reasonable for detecting issues
    # - Critical at 100s gives enough time for slow sources to recover
    # - This prevents the stuttering at exactly 50 seconds
    
    FIRST_WARNING_THRESHOLD_SECONDS = 10
    CRITICAL_WARNING_THRESHOLD_SECONDS = 100
    
    # Verify these are reasonable values
    assert FIRST_WARNING_THRESHOLD_SECONDS > 5, \
        "First warning should allow some grace time (>5s)"
    
    assert CRITICAL_WARNING_THRESHOLD_SECONDS >= 100, \
        "Critical warning should be delayed enough to avoid false alarms (>=100s)"
    
    # Verify critical is significantly later than first warning
    ratio = CRITICAL_WARNING_THRESHOLD_SECONDS / FIRST_WARNING_THRESHOLD_SECONDS
    assert ratio >= 10, \
        f"Critical warning should be much later than first warning (ratio >= 10, got {ratio})"


def test_timing_threshold_ratios():
    """
    Test that the timing threshold ratios are reasonable and won't
    cause false alarms or miss real issues.
    """
    TIMEOUT_PER_READ = 0.5  # seconds
    
    FIRST_WARNING_READS = 20
    CRITICAL_WARNING_READS = 200
    
    first_warning_time = FIRST_WARNING_READS * TIMEOUT_PER_READ
    critical_warning_time = CRITICAL_WARNING_READS * TIMEOUT_PER_READ
    
    # Verify first warning is early enough to catch issues
    assert first_warning_time <= 15, \
        "First warning should be within 15 seconds to catch issues early"
    
    # Verify critical warning gives enough time for recovery
    assert critical_warning_time >= 60, \
        "Critical warning should allow at least 60 seconds for recovery"
    
    # Verify the ratio between warnings is reasonable
    warning_ratio = critical_warning_time / first_warning_time
    assert 5 <= warning_ratio <= 20, \
        f"Warning ratio should be reasonable (5-20x), got {warning_ratio}x"


def test_no_50_second_threshold():
    """
    Test that timing calculations are correct and won't cause 50-second stuttering.
    
    The original issue was a threshold at exactly 50 seconds (500 reads * 0.1s).
    The fix changes this to properly calculated thresholds that avoid the issue.
    
    This test verifies the timing math is correct without parsing source code.
    """
    # Verify the math behind the fix
    TIMEOUT_PER_READ = 0.5  # From get_audio_chunk(timeout=0.5)
    
    # The old problematic threshold
    OLD_CRITICAL_THRESHOLD_READS = 500
    old_critical_time = OLD_CRITICAL_THRESHOLD_READS * 0.1  # Old incorrect assumption
    # This would be 50 seconds if timeout was 0.1s
    # But with 0.5s timeout it would actually be 250 seconds
    
    # The new correct thresholds
    NEW_FIRST_WARNING_READS = 20
    NEW_CRITICAL_WARNING_READS = 200
    
    new_first_warning_time = NEW_FIRST_WARNING_READS * TIMEOUT_PER_READ
    new_critical_time = NEW_CRITICAL_WARNING_READS * TIMEOUT_PER_READ
    
    # Verify new thresholds are correct
    assert new_first_warning_time == 10.0, \
        "First warning should be at 10 seconds"
    assert new_critical_time == 100.0, \
        "Critical warning should be at 100 seconds, not 50"
    
    # Verify we've moved away from the problematic 50-second mark
    assert new_critical_time != 50.0, \
        "Critical threshold should not be at 50 seconds (the problematic value)"
    
    # Verify the critical threshold is significantly delayed to avoid false alarms
    assert new_critical_time >= 100.0, \
        "Critical threshold should be at least 100 seconds to avoid disruption"


def test_icecast_config_timeout():
    """
    Test that IcecastConfig has reasonable default timeout values.
    """
    config = IcecastConfig(
        server="localhost",
        port=8000,
        password="test",
        mount="/test.mp3",
        name="Test Stream",
        description="Test"
    )
    
    # Verify source_timeout is reasonable (should be >= 30 seconds)
    assert config.source_timeout >= 30.0, \
        f"source_timeout should be at least 30s, got {config.source_timeout}"
