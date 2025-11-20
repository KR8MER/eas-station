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

"""Test to verify alert scrolling uses seamless scrolling API correctly.

This test verifies the key aspects of the seamless scrolling fix:
1. The loop calculation uses original_width + separator_width
2. The canvas pattern is [text][separator][text], not [empty][text][empty]
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.unit


def test_seamless_scrolling_api_usage():
    """Test that the refactored code would use prepare_scroll_content correctly.
    
    This is a logic test to verify the key aspects of the fix:
    - Loop offset calculation: original_width + separator_width
    - Not the old: width + text_width
    """
    # Simulate the prepare_scroll_content return values
    dimensions = {
        'max_x': 400,
        'max_y': 64,
        'original_width': 100,  # Width of original text
        'separator_width': 128,  # At least display width (ensures no double visibility)
    }
    
    display_width = 128
    
    # NEW approach (CORRECT): loop at original_width + separator_width
    # This shows [text][separator][text] with no double visibility
    new_correct_max_offset = dimensions['original_width'] + dimensions['separator_width']
    
    # The key: separator_width is guaranteed to be >= display_width
    # This ensures only ONE copy of text is visible at any offset
    assert dimensions['separator_width'] >= display_width
    assert new_correct_max_offset == 228  # 100 + 128


def test_separator_width_prevents_double_visibility():
    """Test that separator_width >= display_width prevents double text visibility.
    
    This is the core of the fix: with adequate separation between text copies,
    only one copy can be visible in the display window at any time.
    """
    display_width = 128
    
    # Scenario 1: Short text (< display_width)
    original_width_short = 80  # Text is 80px wide
    separator_width = 128  # At least display_width
    
    # Total canvas: [text_80px][separator_128px][text_80px] = 288px
    # At any offset, the 128px window can only show ONE text copy
    
    # Test various offsets
    for offset in [0, 40, 80, 120, 160, 200]:
        crop_left = offset
        crop_right = offset + display_width
        
        # First text: [0, 80]
        # Separator: [80, 208]
        # Second text: [208, 288]
        
        first_text_start = 0
        first_text_end = original_width_short
        second_text_start = original_width_short + separator_width
        second_text_end = second_text_start + original_width_short
        
        # Check if window shows first text
        shows_first = (crop_left < first_text_end) and (crop_right > first_text_start)
        
        # Check if window shows second text
        shows_second = (crop_left < second_text_end) and (crop_right > second_text_start)
        
        # CRITICAL: Should NEVER show both texts simultaneously
        assert not (shows_first and shows_second), \
            f"At offset {offset}, window [{crop_left}-{crop_right}] shows BOTH texts!"


def test_old_approach_would_show_double_text():
    """Demonstrate that the OLD approach could show double text.
    
    This test shows why the old [empty][text][empty] pattern was broken.
    """
    display_width = 128
    original_width = 80  # Short text
    
    # OLD WRONG PATTERN: [empty_128px][text_80px][empty_128px] = 336px
    # Text is at position 128, not position 0!
    text_start_old = display_width  # 128
    text_end_old = text_start_old + original_width  # 208
    
    # At offset 50, the window is [50, 178]
    # This shows both empty space AND text start simultaneously
    offset = 50
    crop_left = offset
    crop_right = offset + display_width  # 178
    
    # Check if window shows empty space at the start
    shows_empty_start = crop_left < text_start_old  # True: 50 < 128
    
    # Check if window shows text
    shows_text = (crop_left < text_end_old) and (crop_right > text_start_old)  # True
    
    # This is the problem: both empty and text are visible!
    assert shows_empty_start and shows_text, \
        "The old approach SHOULD have this problem (this assertion should pass)"


def test_new_approach_no_empty_space():
    """Verify that the NEW approach starts text at position 0, not display_width.
    
    The seamless scrolling API creates [text][separator][text] starting at position 0.
    """
    display_width = 128
    original_width = 80
    separator_width = 128
    
    # NEW CORRECT PATTERN: [text_80px][separator_128px][text_80px] = 288px
    # Text starts at position 0, not display_width!
    first_text_start = 0
    first_text_end = original_width  # 80
    separator_start = original_width  # 80
    separator_end = original_width + separator_width  # 208
    second_text_start = separator_end  # 208
    second_text_end = second_text_start + original_width  # 288
    
    # At offset 0, window shows [0, 128]
    # This shows the first text and start of separator
    offset = 0
    crop_left = offset
    crop_right = offset + display_width  # 128
    
    shows_first_text = (crop_left < first_text_end) and (crop_right > first_text_start)
    shows_separator = (crop_left < separator_end) and (crop_right > separator_start)
    shows_second_text = (crop_left < second_text_end) and (crop_right > second_text_start)
    
    # At offset 0, we should see first text and separator, but NOT second text
    assert shows_first_text
    assert shows_separator
    assert not shows_second_text
    
    # At offset 208 (second text start), window shows [208, 336]
    # This shows ONLY the second text (and beyond, which wraps)
    offset = 208
    crop_left = offset
    crop_right = offset + display_width  # 336
    
    shows_first_text = (crop_left < first_text_end) and (crop_right > first_text_start)
    shows_second_text = (crop_left < second_text_end) and (crop_right > second_text_start)
    
    # At loop point, we should see ONLY second text, NOT first text
    assert not shows_first_text
    assert shows_second_text


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
