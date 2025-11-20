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
from unittest.mock import Mock, patch

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_pil_modules():
    with patch('app_core.oled.Image') as mock_image, \
         patch('app_core.oled.ImageDraw') as mock_draw, \
         patch('app_core.oled.ImageFont') as mock_font, \
         patch('app_core.oled.i2c') as mock_i2c, \
         patch('app_core.oled.ssd1306') as mock_ssd1306:

        mock_img = Mock()
        mock_img.crop = Mock(return_value=mock_img)
        mock_img.paste = Mock()
        mock_image.new = Mock(return_value=mock_img)

        mock_draw_obj = Mock()
        mock_draw_obj.text = Mock()
        mock_draw_obj.rectangle = Mock()
        mock_draw_obj.textlength = Mock(return_value=12.0)
        mock_draw.Draw = Mock(return_value=mock_draw_obj)

        mock_font_obj = Mock()
        mock_font_obj.getbbox = Mock(return_value=(0, 0, 10, 12))
        mock_font.load_default = Mock(return_value=mock_font_obj)
        mock_font.truetype = Mock(return_value=mock_font_obj)

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
    from app_core.oled import ArgonOLEDController

    return ArgonOLEDController(
        width=128,
        height=64,
        i2c_bus=1,
        i2c_address=0x3C,
    )


def _assert_points_within_bounds(call_args_list, width, height):
    for call in call_args_list:
        coords = call.args[0]
        for x, y in coords:
            assert 0 <= x < width, f"x={x} exceeds display width {width}"
            assert 0 <= y < height, f"y={y} exceeds display height {height}"


def test_render_frame_bar_elements_are_clamped(oled_controller, mock_pil_modules):
    draw_obj = mock_pil_modules['draw_obj']
    draw_obj.rectangle.reset_mock()

    oled_controller.render_frame([
        {
            'type': 'bar',
            'x': 120,
            'y': 60,
            'width': 50,
            'height': 10,
            'value': 75.0,
            'border': True,
        }
    ])

    assert draw_obj.rectangle.call_count >= 1
    _assert_points_within_bounds(draw_obj.rectangle.call_args_list, oled_controller.width, oled_controller.height)


def test_draw_rectangle_clamps_coordinates(oled_controller, mock_pil_modules):
    draw_obj = mock_pil_modules['draw_obj']
    draw_obj.rectangle.reset_mock()

    oled_controller.draw_rectangle(-10, -10, 500, 500, filled=True, clear=True)

    draw_obj.rectangle.assert_called()
    _assert_points_within_bounds(draw_obj.rectangle.call_args_list, oled_controller.width, oled_controller.height)


def test_draw_bar_graph_clamps_coordinates(oled_controller, mock_pil_modules):
    draw_obj = mock_pil_modules['draw_obj']
    draw_obj.rectangle.reset_mock()

    oled_controller.draw_bar_graph(120, 63, 50, 10, value=80.0, clear=True)

    assert draw_obj.rectangle.call_count >= 1
    _assert_points_within_bounds(draw_obj.rectangle.call_args_list, oled_controller.width, oled_controller.height)


def test_render_frame_text_height_bounds_checking(oled_controller, mock_pil_modules):
    """Test that text extending beyond screen height is not rendered"""
    draw_obj = mock_pil_modules['draw_obj']
    font_obj = mock_pil_modules['font'].truetype.return_value

    # Mock font height of 12 pixels
    font_obj.getbbox = Mock(return_value=(0, 0, 50, 12))
    draw_obj.text.reset_mock()

    # Text at Y=58 with height 12 would extend to Y=70 (beyond 64)
    oled_controller.render_frame([
        {'type': 'text', 'text': 'Out of bounds', 'x': 0, 'y': 58, 'font': 'small'}
    ])

    # Text should NOT be rendered since it would exceed bounds
    assert draw_obj.text.call_count == 0, "Text extending beyond screen bounds should not be rendered"


def test_render_frame_text_exactly_at_bounds(oled_controller, mock_pil_modules):
    """Test that text exactly fitting within bounds is rendered"""
    draw_obj = mock_pil_modules['draw_obj']
    font_obj = mock_pil_modules['font'].truetype.return_value

    # Mock font height of 12 pixels
    font_obj.getbbox = Mock(return_value=(0, 0, 50, 12))
    draw_obj.text.reset_mock()

    # Text at Y=52 with height 12 would extend to Y=64 (exactly at bounds)
    oled_controller.render_frame([
        {'type': 'text', 'text': 'Fits perfectly', 'x': 0, 'y': 52, 'font': 'small'}
    ])

    # Text should be rendered since it fits exactly
    assert draw_obj.text.call_count == 1, "Text fitting exactly within bounds should be rendered"

    # Verify Y coordinate is within bounds
    call_args = draw_obj.text.call_args
    x, y = call_args.args[0]
    assert y == 52


def test_render_frame_text_within_bounds(oled_controller, mock_pil_modules):
    """Test that text well within bounds is rendered"""
    draw_obj = mock_pil_modules['draw_obj']
    font_obj = mock_pil_modules['font'].truetype.return_value

    # Mock font height of 12 pixels
    font_obj.getbbox = Mock(return_value=(0, 0, 50, 12))
    draw_obj.text.reset_mock()

    # Text at Y=40 with height 12 would extend to Y=52 (well within 64)
    oled_controller.render_frame([
        {'type': 'text', 'text': 'Safe position', 'x': 0, 'y': 40, 'font': 'small'}
    ])

    # Text should be rendered
    assert draw_obj.text.call_count == 1

    # Verify Y coordinate
    call_args = draw_obj.text.call_args
    x, y = call_args.args[0]
    assert y == 40


def test_display_lines_text_height_bounds_checking(oled_controller, mock_pil_modules):
    """Test that display_lines respects text height bounds"""
    from app_core.oled import OLEDLineEntry

    draw_obj = mock_pil_modules['draw_obj']
    font_obj = mock_pil_modules['font'].truetype.return_value

    # Mock font height of 12 pixels
    font_obj.getbbox = Mock(return_value=(0, 0, 50, 12))
    draw_obj.text.reset_mock()

    # Create lines where the last one would exceed bounds
    lines = [
        OLEDLineEntry(text="Line 1", x=0, y=0, font="small"),
        OLEDLineEntry(text="Line 2", x=0, y=52, font="small"),  # Y=52, extends to 64 - OK
        OLEDLineEntry(text="Line 3", x=0, y=58, font="small"),  # Y=58, extends to 70 - OUT OF BOUNDS
    ]

    oled_controller.display_lines(lines)

    # Should render only first 2 lines, not the third
    assert draw_obj.text.call_count == 2, "Only text within bounds should be rendered"

    # Verify the Y coordinates of rendered text
    call_args_list = draw_obj.text.call_args_list
    assert call_args_list[0].args[0][1] == 0  # First line at Y=0
    assert call_args_list[1].args[0][1] == 52  # Second line at Y=52


def test_render_frame_multiple_font_sizes(oled_controller, mock_pil_modules):
    """Test bounds checking with different font sizes"""
    draw_obj = mock_pil_modules['draw_obj']
    font_obj = mock_pil_modules['font'].truetype.return_value
    draw_obj.text.reset_mock()

    # Test with larger font (18 pixels)
    font_obj.getbbox = Mock(return_value=(0, 0, 50, 18))

    oled_controller.render_frame([
        # Y=50 + 18 = 68, exceeds 64
        {'type': 'text', 'text': 'Large font', 'x': 0, 'y': 50, 'font': 'large'},
    ])

    # Should not render
    assert draw_obj.text.call_count == 0, "Large font text exceeding bounds should not be rendered"

    draw_obj.text.reset_mock()

    # Test with same large font at safe position
    oled_controller.render_frame([
        # Y=46 + 18 = 64, exactly fits
        {'type': 'text', 'text': 'Large font safe', 'x': 0, 'y': 46, 'font': 'large'},
    ])

    # Should render
    assert draw_obj.text.call_count == 1, "Large font text exactly fitting should be rendered"
