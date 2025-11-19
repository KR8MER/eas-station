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
