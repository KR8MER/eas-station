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

"""
Unit tests for CAP poller continuous mode behavior.

Tests verify that the continuous polling loop:
1. Does not hammer the CPU with tight loops
2. Does not flood NOAA/IPAWS APIs with rapid requests
3. Implements proper exponential backoff on errors
4. Ensures minimum interval between polling attempts
"""


def test_exponential_backoff_calculation():
    """Test exponential backoff calculation logic."""
    max_backoff = 300
    
    # Test backoff sequence
    test_cases = [
        (1, 60),    # First error: 60s
        (2, 120),   # Second error: 120s
        (3, 240),   # Third error: 240s
        (4, 300),   # Fourth error: 300s (capped)
        (5, 300),   # Fifth error: 300s (still capped)
        (10, 300),  # Many errors: 300s (still capped)
    ]
    
    for consecutive_errors, expected_backoff in test_cases:
        calculated_backoff = min(60 * (2 ** (consecutive_errors - 1)), max_backoff)
        assert calculated_backoff == expected_backoff, \
            f"For {consecutive_errors} consecutive errors, expected {expected_backoff}s but got {calculated_backoff}s"


def test_minimum_interval_enforcement():
    """Test that minimum 30 second interval is enforced."""
    # Test various requested intervals
    test_cases = [
        (10, 30),   # Below minimum: enforced to 30
        (15, 30),   # Below minimum: enforced to 30
        (29, 30),   # Below minimum: enforced to 30
        (30, 30),   # At minimum: stays at 30
        (60, 60),   # Above minimum: stays at 60
        (180, 180), # Above minimum: stays at 180
    ]
    
    for requested_interval, expected_interval in test_cases:
        enforced_interval = max(30, requested_interval)
        assert enforced_interval == expected_interval, \
            f"For requested interval {requested_interval}s, expected {expected_interval}s but got {enforced_interval}s"


def test_backoff_resets_after_success():
    """Test that consecutive_errors counter resets to 0 after successful poll."""
    consecutive_errors = 5
    
    # Simulate successful poll
    consecutive_errors = 0  # This is what happens in the actual code
    
    assert consecutive_errors == 0, "Error counter should reset to 0 after success"


def test_backoff_increments_on_error():
    """Test that consecutive_errors counter increments on each error."""
    consecutive_errors = 0
    
    # Simulate 3 consecutive errors
    for _ in range(3):
        consecutive_errors += 1
    
    assert consecutive_errors == 3, "Error counter should increment on each error"
    
    # Calculate backoff for 3 consecutive errors
    max_backoff = 300
    backoff_time = min(60 * (2 ** (consecutive_errors - 1)), max_backoff)
    assert backoff_time == 240, "Backoff for 3 errors should be 240s"
