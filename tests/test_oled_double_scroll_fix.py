"""Test to verify the double scrolling fix.

This test ensures that when scrolling text on the OLED display,
only ONE copy of the text is visible at any given offset, preventing
the double-scrolling visual glitch.
"""

import pytest
from unittest.mock import Mock, patch

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_pil_modules():
    """Mock PIL modules for testing without actual hardware."""
    with patch('app_core.oled.Image') as mock_image, \
         patch('app_core.oled.ImageDraw') as mock_draw, \
         patch('app_core.oled.ImageFont') as mock_font, \
         patch('app_core.oled.i2c') as mock_i2c, \
         patch('app_core.oled.ssd1306') as mock_ssd1306:
        
        # Setup mock image
        mock_img = Mock()
        mock_img.crop = Mock(return_value=mock_img)
        mock_img.paste = Mock()
        mock_img.size = (356, 64)  # Will be updated based on actual buffer size
        mock_image.new = Mock(return_value=mock_img)
        
        # Setup mock draw
        mock_draw_obj = Mock()
        mock_draw_obj.text = Mock()
        mock_draw_obj.textlength = Mock(return_value=100.0)  # 100px text width
        mock_draw.Draw = Mock(return_value=mock_draw_obj)
        
        # Setup mock font
        mock_font_obj = Mock()
        mock_font_obj.getbbox = Mock(return_value=(0, 0, 10, 12))
        mock_font.load_default = Mock(return_value=mock_font_obj)
        mock_font.truetype = Mock(return_value=mock_font_obj)
        
        # Setup mock device
        mock_device = Mock()
        mock_device.display = Mock()
        mock_ssd1306.return_value = mock_device
        
        yield {
            'image': mock_image,
            'draw': mock_draw,
            'font': mock_font,
            'device': mock_device,
            'img': mock_img,
            'draw_obj': mock_draw_obj,
        }


@pytest.fixture
def oled_controller(mock_pil_modules):
    """Create an OLED controller instance for testing."""
    from app_core.oled import ArgonOLEDController
    
    controller = ArgonOLEDController(
        width=128,
        height=64,
        i2c_bus=1,
        i2c_address=0x3C,
    )
    return controller


def test_padding_prevents_double_text_visibility(oled_controller, mock_pil_modules):
    """Test that padding is at least display_width to prevent double text."""
    from app_core.oled import OLEDLine
    
    # Create a line with text shorter than display width
    lines = [OLEDLine(text="Test Message", x=0, y=0, font="small")]
    
    content_image, dimensions = oled_controller.prepare_scroll_content(lines)
    
    original_width = dimensions['original_width']
    separator_width = dimensions['separator_width']
    display_width = oled_controller.width
    
    # CRITICAL: separator_width should be at least display_width
    # This ensures that both text copies cannot appear in the same 128px window
    assert separator_width >= display_width, (
        f"Padding {separator_width}px is less than display width {display_width}px! "
        "This would allow both text copies to be visible simultaneously."
    )
    
    # The loop point should be: original_width + separator_width
    loop_point = original_width + separator_width
    
    # Verify that at the loop point, only the second copy is visible
    # When offset = loop_point, the crop window shows pixels [loop_point, loop_point + display_width]
    # This should only show the second text copy, not overlap with the first
    assert loop_point >= original_width, "Loop point must be past the first text copy"


def test_seamless_loop_with_adequate_padding(oled_controller, mock_pil_modules):
    """Test that the loop resets seamlessly without showing both text copies."""
    from app_core.oled import OLEDLine
    
    # Test with various text widths
    test_cases = [
        ("Short", 50),   # Text narrower than display (50px < 128px)
        ("Medium Text Here", 100),  # Text narrower than display (100px < 128px)
        ("Very Long Text That Exceeds Display Width", 200),  # Text wider than display
    ]
    
    for text, expected_min_width in test_cases:
        # Mock textlength to return specific width
        mock_pil_modules['draw_obj'].textlength = Mock(return_value=float(expected_min_width))
        
        lines = [OLEDLine(text=text, x=0, y=0, font="small")]
        content_image, dimensions = oled_controller.prepare_scroll_content(lines)
        
        original_width = dimensions['original_width']
        separator_width = dimensions['separator_width']
        display_width = oled_controller.width
        
        # For short text (< display_width), padding must equal display_width
        # For long text (> display_width), padding can be smaller but should still be adequate
        if original_width < display_width:
            assert separator_width == display_width, (
                f"For short text ({original_width}px), padding must equal display width ({display_width}px) "
                f"to prevent double visibility, but got {separator_width}px"
            )
        else:
            # For long text, padding should still be at least display_width for consistency
            assert separator_width >= display_width, (
                f"Padding should be at least {display_width}px for consistency, "
                f"but got {separator_width}px"
            )


def test_no_overlap_at_any_offset(oled_controller, mock_pil_modules):
    """Test that at no offset value can both text copies be visible."""
    from app_core.oled import OLEDLine
    
    # Use a specific text width that would cause double visibility with old implementation
    test_text_width = 80  # Less than 128px, would show both copies with old padding
    mock_pil_modules['draw_obj'].textlength = Mock(return_value=float(test_text_width))
    
    lines = [OLEDLine(text="Test", x=0, y=0, font="small")]
    content_image, dimensions = oled_controller.prepare_scroll_content(lines)
    
    original_width = dimensions['original_width']
    separator_width = dimensions['separator_width']
    display_width = oled_controller.width
    loop_point = original_width + separator_width
    
    # Simulate scrolling through all offsets
    for offset in range(loop_point + 1):
        # Crop window for this offset
        crop_left = offset
        crop_right = offset + display_width
        
        # Check if this window would show BOTH text copies
        # First text: [0, original_width]
        # Second text: [original_width + separator_width, original_width + separator_width + original_width]
        
        first_text_start = 0
        first_text_end = original_width
        second_text_start = original_width + separator_width
        second_text_end = second_text_start + original_width
        
        # Check if crop window overlaps with first text
        shows_first_text = (crop_left < first_text_end) and (crop_right > first_text_start)
        
        # Check if crop window overlaps with second text
        shows_second_text = (crop_left < second_text_end) and (crop_right > second_text_start)
        
        # CRITICAL: Should never show both texts simultaneously
        assert not (shows_first_text and shows_second_text), (
            f"At offset {offset}, crop window ({crop_left}-{crop_right}) shows BOTH text copies! "
            f"First text: {first_text_start}-{first_text_end}, "
            f"Second text: {second_text_start}-{second_text_end}"
        )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
