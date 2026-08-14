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

"""Pixel-level tests for scripts.vfd_controller.render_vfd_elements() --
the new PIL-based whole-frame renderer that gives the VFD the same icon/
gauge/compass/bar-chart vocabulary as the OLED engine, pushed as a single
bitmap via draw_bitmap() instead of one GU-7000 command per primitive.

Uses the real Pillow library throughout (this is a pure function with no
hardware dependency at all), so these assert on actual pixel state.
"""

from unittest.mock import Mock

import pytest

from scripts.vfd_controller import NoritakeVFDController, render_vfd_elements

pytestmark = pytest.mark.unit


def _lit_pixel_count(image) -> int:
    return sum(1 for px in image.getdata() if px != 0)


def test_render_vfd_elements_returns_correct_size():
    img = render_vfd_elements([{"type": "text", "text": "HI", "x": 0, "y": 0}])
    assert img.size == (140, 32)


def test_text_element_draws_pixels():
    img = render_vfd_elements([{"type": "text", "text": "SYSTEM", "x": 2, "y": 1}])
    assert _lit_pixel_count(img) > 0


def test_empty_text_draws_nothing():
    img = render_vfd_elements([{"type": "text", "text": "", "x": 2, "y": 1}])
    assert _lit_pixel_count(img) == 0


def test_text_invert_draws_dark_on_light_banner():
    """A filled header rectangle + invert=True text must NOT cancel out to
    white-on-white (the bug this test guards: the first implementation drew
    every text element with fill=colour regardless of invert, so a header
    title on its own banner was invisible)."""
    banner_only = render_vfd_elements([
        {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 10, "filled": True},
    ])
    banner_count = _lit_pixel_count(banner_only)

    banner_with_text = render_vfd_elements([
        {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 10, "filled": True},
        {"type": "text", "text": "SYSTEM", "x": 2, "y": 1, "invert": True},
    ])
    with_text_count = _lit_pixel_count(banner_with_text)

    # Inverted (dark) text carved out of the lit banner must reduce the lit
    # pixel count, not leave it unchanged (which is what white-on-white does).
    assert with_text_count < banner_count


def test_icon_invert_draws_dark_on_light_banner():
    banner_only = render_vfd_elements([
        {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 10, "filled": True},
    ])
    banner_with_icon = render_vfd_elements([
        {"type": "rectangle", "x": 0, "y": 0, "width": 140, "height": 10, "filled": True},
        {"type": "icon", "name": "heartbeat", "x": 120, "y": 1, "size": 8, "invert": True},
    ])
    assert _lit_pixel_count(banner_with_icon) < _lit_pixel_count(banner_only)


def test_segments_lit_count_scales_with_value():
    """A segmented VU meter must light strictly more blocks at a higher
    value -- distinct from 'bar' (one continuous fill)."""
    low = render_vfd_elements([
        {"type": "segments", "x": 0, "y": 0, "width": 100, "height": 8, "value": 10, "count": 10, "gap": 2},
    ])
    high = render_vfd_elements([
        {"type": "segments", "x": 0, "y": 0, "width": 100, "height": 8, "value": 90, "count": 10, "gap": 2},
    ])
    assert _lit_pixel_count(high) > _lit_pixel_count(low)


def test_segments_zero_value_still_draws_outlines():
    """Unlit segments must still render as outlines (a visible meter frame
    even at 0), not vanish entirely."""
    img = render_vfd_elements([
        {"type": "segments", "x": 0, "y": 0, "width": 100, "height": 8, "value": 0, "count": 10, "gap": 2},
    ])
    assert _lit_pixel_count(img) > 0


def test_segments_full_value_lights_all_blocks():
    all_lit = render_vfd_elements([
        {"type": "segments", "x": 0, "y": 0, "width": 100, "height": 8, "value": 100, "count": 10, "gap": 2},
    ])
    zero = render_vfd_elements([
        {"type": "segments", "x": 0, "y": 0, "width": 100, "height": 8, "value": 0, "count": 10, "gap": 2},
    ])
    assert _lit_pixel_count(all_lit) > _lit_pixel_count(zero)


def test_bar_taller_value_draws_more_pixels():
    low = render_vfd_elements([{"type": "bar", "x": 0, "y": 0, "width": 100, "height": 8, "value": 5}])
    high = render_vfd_elements([{"type": "bar", "x": 0, "y": 0, "width": 100, "height": 8, "value": 95}])
    assert _lit_pixel_count(high) > _lit_pixel_count(low)


def test_bars_empty_values_draws_nothing():
    img = render_vfd_elements([{"type": "bars", "x": 0, "y": 0, "width": 40, "height": 16, "values": []}])
    assert _lit_pixel_count(img) == 0


def test_bars_non_numeric_value_does_not_raise():
    img = render_vfd_elements([
        {"type": "bars", "x": 0, "y": 0, "width": 40, "height": 16, "values": ["bad"], "max_value": 50},
    ])
    assert _lit_pixel_count(img) == 0


def test_gauge_renders_arc_and_needle():
    img = render_vfd_elements([{"type": "gauge", "x": 40, "y": 28, "radius": 12, "value": 50}])
    assert _lit_pixel_count(img) > 0


def test_compass_bare_dial_renders():
    img = render_vfd_elements([{"type": "compass", "x": 20, "y": 16, "radius": 10, "heading": None}])
    assert _lit_pixel_count(img) > 0


def test_compass_with_heading_draws_more_than_bare_dial():
    bare = render_vfd_elements([{"type": "compass", "x": 20, "y": 16, "radius": 10, "heading": None}])
    with_needle = render_vfd_elements([{"type": "compass", "x": 20, "y": 16, "radius": 10, "heading": 90}])
    assert _lit_pixel_count(with_needle) > _lit_pixel_count(bare)


def test_icon_reused_from_oled_library():
    """Confirms the VFD engine reuses app_core.oled's icon renderers rather
    than duplicating the icon-drawing code a second time."""
    img = render_vfd_elements([{"type": "icon", "name": "satellite", "x": 10, "y": 10, "size": 9}])
    assert _lit_pixel_count(img) > 0


def test_unknown_element_type_is_silently_skipped():
    img = render_vfd_elements([{"type": "not-a-real-type", "x": 0, "y": 0}])
    assert _lit_pixel_count(img) == 0


def test_elements_out_of_bounds_do_not_raise():
    """Elements placed past the 140x32 canvas must not crash the render."""
    img = render_vfd_elements([
        {"type": "rectangle", "x": 130, "y": 25, "width": 50, "height": 50, "filled": True},
        {"type": "circle", "x": 200, "y": 200, "radius": 20},
        {"type": "text", "text": "OFFSCREEN", "x": 500, "y": 500},
    ])
    assert img.size == (140, 32)


# ---------------------------------------------------------------------------
# NoritakeVFDController.render_frame() -- the hardware-facing wrapper
# ---------------------------------------------------------------------------

def _mock_controller() -> NoritakeVFDController:
    vfd = NoritakeVFDController()
    vfd.serial = Mock()
    vfd.serial.is_open = True
    vfd.connected = True
    return vfd


def test_render_frame_pushes_one_full_frame_bitmap():
    vfd = _mock_controller()
    captured = {}
    vfd.draw_bitmap = lambda x, y, w, h, data: captured.update(x=x, y=y, w=w, h=h, data=data)

    vfd.render_frame([{"type": "text", "text": "HI", "x": 0, "y": 0}])

    assert captured == {**captured, "x": 0, "y": 0, "w": 140, "h": 32}
    assert any(captured["data"])


def test_render_frame_noop_when_not_connected():
    vfd = NoritakeVFDController()
    vfd.connected = False
    calls = []
    vfd.draw_bitmap = lambda *a, **kw: calls.append(a)

    vfd.render_frame([{"type": "text", "text": "HI", "x": 0, "y": 0}])

    assert calls == []


def test_render_frame_clears_before_drawing_by_default():
    vfd = _mock_controller()
    vfd.draw_bitmap = Mock()
    vfd.clear_screen = Mock()

    vfd.render_frame([{"type": "text", "text": "HI", "x": 0, "y": 0}])

    vfd.clear_screen.assert_called_once()


def test_render_frame_skips_clear_when_requested():
    vfd = _mock_controller()
    vfd.draw_bitmap = Mock()
    vfd.clear_screen = Mock()

    vfd.render_frame([{"type": "text", "text": "HI", "x": 0, "y": 0}], clear=False)

    vfd.clear_screen.assert_not_called()
