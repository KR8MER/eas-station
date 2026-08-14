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

"""Pixel-level tests for scripts.led_sign_controller.render_led_elements() --
the PIL-based whole-frame renderer that gives the LED sign's Picture File
(Dots/graphics) mode an icon+text vocabulary, pushed as a single bitmap via
send_dots_graphic() instead of the sign's own scrolling-text renderer.

The 160x16 canvas is half the VFD's 32 rows -- only a single hero row's
worth of content fits, so this only offers text/icon/rectangle/hline/vline/
bar, not gauge/compass/segments/bars (those need the VFD's extra height).

Uses the real Pillow library throughout (this is a pure function with no
hardware dependency at all), so these assert on actual pixel state.
"""

from unittest.mock import Mock

import pytest

from scripts.led_sign_controller import (
    Alpha9120CController,
    Color,
    _image_to_dots_grid,
    render_led_elements,
)

pytestmark = pytest.mark.unit


def _lit_pixel_count(image) -> int:
    return sum(1 for px in image.getdata() if px != 0)


def test_render_led_elements_returns_correct_size():
    img = render_led_elements([{"type": "text", "text": "HI", "x": 0, "y": 0}])
    assert img.size == (160, 16)


def test_text_element_draws_pixels():
    img = render_led_elements([{"type": "text", "text": "CPU", "x": 0, "y": 4}])
    assert _lit_pixel_count(img) > 0


def test_empty_text_draws_nothing():
    img = render_led_elements([{"type": "text", "text": "", "x": 0, "y": 4}])
    assert _lit_pixel_count(img) == 0


def test_text_font_large_draws_more_pixels_than_default():
    """The 15pt bold hero size (font: 'large') must be visibly bigger than
    the default 7px -- this is the whole point of a graphics screen over
    plain scrolling text: one value gets real typographic weight."""
    default_size = render_led_elements([{"type": "text", "text": "92%", "x": 18, "y": 1}])
    large = render_led_elements([{"type": "text", "text": "92%", "x": 18, "y": 1, "font": "large"}])
    assert _lit_pixel_count(large) > _lit_pixel_count(default_size)


def test_text_max_width_truncates_long_text():
    """Without max_width, Pillow draws text past the 160px edge with no
    clipping at all -- same protection VFD's render_vfd_elements() got
    earlier today, ported here for the same reason (unbounded alert
    labels)."""
    long_text = "MEM 52% DSK 61% NET OK GPS FIX"
    unbounded = render_led_elements([{"type": "text", "text": long_text, "x": 0, "y": 5}])
    bounded = render_led_elements([
        {"type": "text", "text": long_text, "x": 0, "y": 5, "max_width": 40, "overflow": "ellipsis"},
    ])
    assert _lit_pixel_count(bounded) < _lit_pixel_count(unbounded)
    assert _lit_pixel_count(bounded) > 0


def test_icon_reused_from_oled_library():
    """Confirms the LED engine reuses app_core.oled's icon renderers
    rather than duplicating the icon-drawing code a third time."""
    img = render_led_elements([{"type": "icon", "name": "warning", "x": 1, "y": 1, "size": 14}])
    assert _lit_pixel_count(img) > 0


def test_unknown_icon_name_is_silently_skipped():
    img = render_led_elements([{"type": "icon", "name": "not-a-real-icon", "x": 1, "y": 1, "size": 14}])
    assert _lit_pixel_count(img) == 0


def test_bar_taller_value_draws_more_pixels():
    low = render_led_elements([{"type": "bar", "x": 0, "y": 0, "width": 40, "height": 8, "value": 5}])
    high = render_led_elements([{"type": "bar", "x": 0, "y": 0, "width": 40, "height": 8, "value": 95}])
    assert _lit_pixel_count(high) > _lit_pixel_count(low)


def test_unknown_element_type_is_silently_skipped():
    img = render_led_elements([{"type": "not-a-real-type", "x": 0, "y": 0}])
    assert _lit_pixel_count(img) == 0


def test_elements_out_of_bounds_do_not_raise():
    """Elements placed past the 160x16 canvas must not crash the render."""
    img = render_led_elements([
        {"type": "rectangle", "x": 150, "y": 10, "width": 50, "height": 50, "filled": True},
        {"type": "text", "text": "OFFSCREEN", "x": 500, "y": 500},
    ])
    assert img.size == (160, 16)


def test_image_to_dots_grid_matches_lit_pixels():
    """_image_to_dots_grid() (fed to send_dots_graphic()) must carry the
    same on/off pattern as the source image, not an inverted or
    transposed one."""
    img = render_led_elements([{"type": "rectangle", "x": 0, "y": 0, "width": 4, "height": 4, "filled": True}])
    grid = _image_to_dots_grid(img)
    assert len(grid) == 16
    assert len(grid[0]) == 160
    assert grid[0][0] == 1
    assert grid[0][10] == 0


# ---------------------------------------------------------------------------
# Alpha9120CController.render_frame() -- the hardware-facing wrapper
# ---------------------------------------------------------------------------

def _mock_controller() -> Alpha9120CController:
    controller = Alpha9120CController(host="127.0.0.1", port=10001)
    controller.connected = True
    return controller


def test_render_frame_pushes_dots_to_dedicated_graphics_label():
    """render_frame() must never write to send_dots_graphic()'s own
    default label "A" -- that's send_message()'s TEXT file, and a file's
    type is fixed at allocation time (see configure_graphics_memory())."""
    controller = _mock_controller()
    captured = {}
    controller.send_dots_graphic = lambda dots, color=None, file_label="A": captured.update(
        dots=dots, color=color, file_label=file_label
    ) or True

    controller.render_frame([{"type": "text", "text": "HI", "x": 0, "y": 4}])

    assert captured["file_label"] == Alpha9120CController.GRAPHICS_FILE_LABEL
    assert captured["file_label"] != "A"
    assert len(captured["dots"]) == 16
    assert len(captured["dots"][0]) == 160


def test_render_frame_defaults_to_amber():
    controller = _mock_controller()
    captured = {}
    controller.send_dots_graphic = lambda dots, color=None, file_label="A": captured.update(color=color) or True

    controller.render_frame([{"type": "text", "text": "HI", "x": 0, "y": 4}])

    assert captured["color"] == Color.AMBER


def test_render_frame_passes_through_explicit_color():
    controller = _mock_controller()
    captured = {}
    controller.send_dots_graphic = lambda dots, color=None, file_label="A": captured.update(color=color) or True

    controller.render_frame([{"type": "text", "text": "HI", "x": 0, "y": 4}], color=Color.RED)

    assert captured["color"] == Color.RED


# ---------------------------------------------------------------------------
# configure_graphics_memory() -- destructive, confirm-gated
# ---------------------------------------------------------------------------

def test_configure_graphics_memory_requires_confirm():
    controller = _mock_controller()
    controller.set_memory_configuration = Mock(return_value=True)

    result = controller.configure_graphics_memory(confirm=False)

    assert result is False
    controller.set_memory_configuration.assert_not_called()


def test_configure_graphics_memory_allocates_text_and_dots_files():
    controller = _mock_controller()
    controller.set_memory_configuration = Mock(return_value=True)

    result = controller.configure_graphics_memory(confirm=True)

    assert result is True
    controller.set_memory_configuration.assert_called_once()
    files = controller.set_memory_configuration.call_args[0][0]
    labels_to_types = {f["label"]: f["type"] for f in files}
    assert labels_to_types.get("A") == "A"  # TEXT file, unchanged default label
    assert labels_to_types.get(Alpha9120CController.GRAPHICS_FILE_LABEL) == "D"  # DOTS file


def test_configure_graphics_memory_dots_file_sized_for_160x16():
    controller = _mock_controller()
    controller.set_memory_configuration = Mock(return_value=True)

    controller.configure_graphics_memory(confirm=True)

    files = controller.set_memory_configuration.call_args[0][0]
    dots_file = next(f for f in files if f["type"] == "D")
    # ceil(160/8) bytes per row * 16 rows
    assert dots_file["size"] == 320


# ---------------------------------------------------------------------------
# scripts.screen_manager._display_led_screen() -- graphics-mode dispatch
# ---------------------------------------------------------------------------

def test_display_led_screen_delegates_to_render_frame_for_graphics_mode():
    """_display_led_screen() must call led_controller.render_frame() when
    the renderer returns an 'elements' shape, not send_message() -- the
    two modes (graphics vs. legacy scrolling text) must stay distinct
    dispatch branches, matching _display_vfd_screen()'s render_frame()
    delegation (see tests/test_vfd_display_bugs.py)."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "scripts" / "screen_manager.py"
    content = source.read_text(encoding="utf-8")
    start = content.index("def _display_led_screen")
    end = content.index("\n    def ", start + 1)
    method_source = content[start:end]

    assert "led_controller.render_frame(" in method_source
    assert "'elements' in rendered" in method_source
    assert "led_controller.send_message(" in method_source  # legacy path still present
