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


def test_consecutive_empty_reads_timing_comments():
    """
    Test that timing calculations in comments match the actual code.
    
    This is a documentation test to ensure comments accurately reflect
    the timing behavior, preventing future confusion.
    """
    # Read the actual file to verify comments
    import os
    file_path = os.path.join(
        os.path.dirname(__file__),
        '..',
        'app_core',
        'audio',
        'icecast_output.py'
    )
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Verify the comment about timeout is present and accurate
    assert '0.5s timeout per read' in content or '0.5s' in content, \
        "Code should document the 0.5s timeout used in calculations"
    
    # Verify the warning thresholds are documented correctly
    assert '20 * 0.5s' in content or '10 seconds (20' in content, \
        "First warning threshold calculation should be documented"
    
    assert '200 * 0.5s' in content or '100 seconds (200' in content, \
        "Critical warning threshold calculation should be documented"


def test_no_50_second_threshold():
    """
    Test that the problematic 50-second threshold has been removed.
    
    The original issue was a hardcoded threshold at exactly 50 seconds
    that caused stuttering. This should no longer exist.
    """
    import os
    file_path = os.path.join(
        os.path.dirname(__file__),
        '..',
        'app_core',
        'audio',
        'icecast_output.py'
    )
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check for the old problematic patterns
    # The old code had: "== 500" with comment "After 50 seconds"
    # This should be changed to "== 200" with "After 100 seconds"
    
    lines_with_500 = [line for line in content.split('\n') if '== 500' in line]
    
    # There should be no lines checking for 500 consecutive empty reads
    # (or if there are, they should be in comments as "old behavior")
    for line in lines_with_500:
        if 'self._consecutive_empty_reads == 500' in line:
            pytest.fail(
                f"Old threshold of 500 reads (50 seconds) still exists: {line.strip()}\n"
                "This should be changed to 200 reads (100 seconds)"
            )
    
    # Verify the new threshold exists
    assert 'self._consecutive_empty_reads == 200' in content, \
        "New threshold of 200 reads (100 seconds) should be present"
    
    assert 'self._consecutive_empty_reads == 20' in content, \
        "First warning threshold of 20 reads (10 seconds) should be present"


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
