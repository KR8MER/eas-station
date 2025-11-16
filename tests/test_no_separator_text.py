"""Test to verify that separator text is not rendered, preventing double-scroll appearance.

This test ensures that the prepare_scroll_content method creates a seamless scrolling
buffer WITHOUT rendering the visible '***' separator text that would appear at a
different Y coordinate than the main content, causing a "two things scrolling" effect.
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
        mock_img.size = (528, 64)
        mock_image.new = Mock(return_value=mock_img)
        
        # Setup mock draw
        mock_draw_obj = Mock()
        mock_draw_obj.text = Mock()
        mock_draw_obj.textlength = Mock(return_value=100.0)
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


def test_separator_text_not_rendered(oled_controller, mock_pil_modules):
    """Test that separator text '***' is NOT rendered, preventing double-scroll appearance."""
    from app_core.oled import OLEDLine
    
    # Create a line with text
    lines = [OLEDLine(text="Test Message", x=0, y=10, font="small")]
    
    mock_draw_obj = mock_pil_modules['draw_obj']
    mock_draw_obj.text.reset_mock()
    
    content_image, dimensions = oled_controller.prepare_scroll_content(lines)
    
    # Count text rendering calls
    text_calls = mock_draw_obj.text.call_args_list
    
    # Should render the main text twice (original + duplicate for seamless loop)
    # Should NOT render separator text '***' or any similar separator marker
    assert len(text_calls) == 2, f"Expected 2 text renders (original + duplicate), got {len(text_calls)}"
    
    # Verify that both calls are for the same text (not separator)
    for call in text_calls:
        args, kwargs = call
        rendered_text = args[1] if len(args) > 1 else kwargs.get('text', '')
        assert rendered_text == "Test Message", \
            f"Expected 'Test Message' but got '{rendered_text}' - separator should not be rendered!"


def test_no_separator_at_different_y_position(oled_controller, mock_pil_modules):
    """Test that no text is rendered at a different Y position than the main content.
    
    This was the root cause of the 'two things scrolling' bug - the separator "***"
    was rendered at a different Y coordinate (centered in padded_height) while the
    main text was at its own Y position, creating the appearance of two separate
    scrolling elements.
    """
    from app_core.oled import OLEDLine
    
    # Text at Y=10
    lines = [OLEDLine(text="Main Content", x=0, y=10, font="large")]
    
    mock_draw_obj = mock_pil_modules['draw_obj']
    mock_draw_obj.text.reset_mock()
    
    content_image, dimensions = oled_controller.prepare_scroll_content(lines)
    
    text_calls = mock_draw_obj.text.call_args_list
    
    # Check that all text renders are at the same Y position
    y_positions = []
    for call in text_calls:
        args, kwargs = call
        position = args[0] if len(args) > 0 else kwargs.get('xy', (0, 0))
        x, y = position
        y_positions.append(y)
    
    # All Y positions should be the same (no separator at different Y)
    unique_y_positions = set(y_positions)
    assert len(unique_y_positions) == 1, \
        f"Multiple Y positions detected {unique_y_positions} - this causes 'two things scrolling' effect!"
    assert y_positions[0] == 10, \
        f"Expected Y=10 but got Y={y_positions[0]}"


def test_seamless_scrolling_still_works(oled_controller, mock_pil_modules):
    """Test that seamless scrolling still works correctly without visible separator."""
    from app_core.oled import OLEDLine
    
    lines = [OLEDLine(text="Scrolling Text", x=0, y=0, font="small")]
    
    content_image, dimensions = oled_controller.prepare_scroll_content(lines)
    
    # Verify dimensions are correct for seamless looping
    assert 'original_width' in dimensions
    assert 'separator_width' in dimensions
    assert dimensions['separator_width'] >= oled_controller.width, \
        "Separator width must be at least display width for seamless scrolling"
    
    # Loop point should be original_width + separator_width
    loop_point = dimensions['original_width'] + dimensions['separator_width']
    
    # Verify the pattern is correct even without visible separator text
    # Pattern: [text][blank_space][text]
    # The blank space provides the necessary separation
    assert dimensions['max_x'] >= loop_point, \
        f"Canvas width {dimensions['max_x']} should be >= loop point {loop_point}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
