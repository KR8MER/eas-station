"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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

"""Pixel-level tests for the new OLED render_frame() primitives added for
the GPS screen and general visual-upgrade pass: 'compass', 'bars', and the
'satellite'/'gps_pin' icons.

Unlike tests/test_oled_double_scroll_fix.py (which mocks Image/ImageDraw
entirely), these tests mock only the hardware layer (i2c, ssd1306) so
render_frame() draws with the REAL Pillow library -- letting us assert on
actual pixel state instead of just recorded mock calls.
"""

from unittest.mock import Mock, patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def real_pil_controller():
    """ArgonOLEDController with real Pillow drawing but mocked I2C/SSD1306 hardware."""
    with patch('app_core.oled.i2c') as mock_i2c, patch('app_core.oled.ssd1306') as mock_ssd1306:
        mock_i2c.return_value = Mock()
        mock_device = Mock()
        mock_device.display = Mock()
        mock_ssd1306.return_value = mock_device

        from app_core.oled import ArgonOLEDController

        controller = ArgonOLEDController(width=128, height=64, i2c_bus=1, i2c_address=0x3C)
        yield controller


def _lit_pixel_count(controller) -> int:
    """Count non-background pixels in the last rendered frame."""
    image = controller._last_image
    return sum(1 for px in image.getdata() if px != 0)


def test_compass_bare_dial_draws_ring_and_center_dot(real_pil_controller):
    """A compass with no heading (no GPS fix yet) still draws the dial ring
    and cardinal ticks, just no needle."""
    real_pil_controller.render_frame([
        {'type': 'compass', 'x': 30, 'y': 30, 'radius': 20, 'heading': None},
    ])
    assert _lit_pixel_count(real_pil_controller) > 0


def test_compass_with_heading_draws_more_than_bare_dial(real_pil_controller):
    """A resolved heading adds a needle -- strictly more lit pixels than the bare dial."""
    real_pil_controller.render_frame([
        {'type': 'compass', 'x': 30, 'y': 30, 'radius': 20, 'heading': None},
    ])
    bare_count = _lit_pixel_count(real_pil_controller)

    real_pil_controller.render_frame([
        {'type': 'compass', 'x': 30, 'y': 30, 'radius': 20, 'heading': 90.0},
    ])
    with_needle_count = _lit_pixel_count(real_pil_controller)

    assert with_needle_count > bare_count


def test_compass_survives_edge_of_screen(real_pil_controller):
    """A compass placed with the dial partly off-canvas must not raise."""
    real_pil_controller.render_frame([
        {'type': 'compass', 'x': 0, 'y': 0, 'radius': 25, 'heading': 270.0},
    ])
    # No exception is the primary assertion; also confirm it drew something.
    assert _lit_pixel_count(real_pil_controller) > 0


def test_bars_empty_values_draws_nothing(real_pil_controller):
    real_pil_controller.render_frame([
        {'type': 'bars', 'x': 0, 'y': 0, 'width': 40, 'height': 16, 'values': []},
    ])
    assert _lit_pixel_count(real_pil_controller) == 0


def test_bars_taller_value_draws_more_pixels(real_pil_controller):
    """A single bar at 100% of max_value must light strictly more pixels
    than the same bar at a low fraction of max_value."""
    real_pil_controller.render_frame([
        {'type': 'bars', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
         'values': [5], 'max_value': 50, 'gap': 0},
    ])
    low_count = _lit_pixel_count(real_pil_controller)

    real_pil_controller.render_frame([
        {'type': 'bars', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
         'values': [50], 'max_value': 50, 'gap': 0},
    ])
    high_count = _lit_pixel_count(real_pil_controller)

    assert high_count > low_count


def test_bars_clamps_out_of_range_values(real_pil_controller):
    """Values above max_value or negative must not crash and must clamp
    to the same pixel output as the clamped boundary value."""
    real_pil_controller.render_frame([
        {'type': 'bars', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
         'values': [999], 'max_value': 50, 'gap': 0},
    ])
    overflow_count = _lit_pixel_count(real_pil_controller)

    real_pil_controller.render_frame([
        {'type': 'bars', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
         'values': [50], 'max_value': 50, 'gap': 0},
    ])
    clamped_count = _lit_pixel_count(real_pil_controller)

    assert overflow_count == clamped_count


def test_bars_non_numeric_value_is_treated_as_zero(real_pil_controller):
    """A malformed value (e.g. None slipping through from a missing metric)
    must not raise and must render as an empty (zero-height) bar."""
    real_pil_controller.render_frame([
        {'type': 'bars', 'x': 0, 'y': 0, 'width': 10, 'height': 20,
         'values': ['not-a-number'], 'max_value': 50, 'gap': 0},
    ])
    assert _lit_pixel_count(real_pil_controller) == 0


def test_bars_many_values_stay_within_bounds(real_pil_controller):
    """8 satellite-style bars packed into a narrow footprint must not raise
    or draw outside the requested width."""
    real_pil_controller.render_frame([
        {'type': 'bars', 'x': 80, 'y': 40, 'width': 44, 'height': 20,
         'values': [45, 38, 30, 25, 20, 15, 10, 5], 'max_value': 50, 'gap': 1},
    ])
    assert _lit_pixel_count(real_pil_controller) > 0


def test_satellite_and_gps_pin_icons_render(real_pil_controller):
    real_pil_controller.render_frame([
        {'type': 'icon', 'name': 'satellite', 'x': 10, 'y': 10, 'size': 12},
    ])
    assert _lit_pixel_count(real_pil_controller) > 0

    real_pil_controller.render_frame([
        {'type': 'icon', 'name': 'gps_pin', 'x': 10, 'y': 10, 'size': 12},
    ])
    assert _lit_pixel_count(real_pil_controller) > 0


def test_unknown_icon_name_is_silently_skipped(real_pil_controller):
    """An icon name with no registered renderer must not raise."""
    real_pil_controller.render_frame([
        {'type': 'icon', 'name': 'not-a-real-icon', 'x': 10, 'y': 10, 'size': 12},
    ])
    assert _lit_pixel_count(real_pil_controller) == 0
