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

"""Tests for the server-side VFD/LED preview image renderers.

The module is loaded directly from its file so the test does not pull in the
``services.displays`` package __init__ (which imports Flask and the rest of the
displays subsystem).  Rendering requires Pillow; the whole module is skipped
when it is unavailable.
"""

import base64
import importlib.util
import io
import os

import pytest

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "services", "displays", "preview_render.py",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("preview_render_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pr = _load_module()

pytestmark = pytest.mark.skipif(
    not getattr(pr, "_PIL_AVAILABLE", False),
    reason="Pillow not installed; preview rendering unavailable",
)


def _decode_data_uri(uri):
    assert uri.startswith("data:image/png;base64,"), f"unexpected URI prefix: {uri[:32]}"
    return base64.b64decode(uri.split(",", 1)[1])


def _assert_png(uri, expected_w=None, expected_h=None):
    from PIL import Image
    data = _decode_data_uri(uri)
    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG"
    if expected_w is not None:
        assert img.width == expected_w
    if expected_h is not None:
        assert img.height == expected_h
    return img


def test_led_preview_returns_png_data_uri():
    uri = pr.render_led_preview(["SEVERE WEATHER", "TORNADO WARNING", "TAKE COVER", "NOW"], "RED")
    _assert_png(uri)


def test_led_preview_accepts_dict_lines():
    # ScreenRenderer can emit per-line dicts ({'text': ..., 'color': ...}).
    uri = pr.render_led_preview(
        [{"text": "LINE ONE"}, {"text": "LINE TWO"}, "plain", None],
        "AMBER",
    )
    _assert_png(uri)


def test_led_preview_unknown_colour_falls_back():
    # An effect colour like RAINBOW or garbage must not raise.
    uri = pr.render_led_preview(["HELLO"], "NOT_A_REAL_COLOR")
    _assert_png(uri)


def test_led_preview_handles_empty_input():
    uri = pr.render_led_preview([], "GREEN")
    _assert_png(uri)


def test_vfd_preview_from_commands():
    commands = [
        {"type": "clear"},
        {"type": "text", "x": 4, "y": 2, "text": "EAS STATION"},
        {"type": "line", "x1": 0, "y1": 15, "x2": 139, "y2": 15},
        {"type": "rectangle", "x1": 2, "y1": 18, "x2": 60, "y2": 28, "filled": False},
        {"type": "text", "x": 4, "y": 20, "text": "12:34"},
    ]
    img = _assert_png(pr.render_vfd_preview(commands))
    # VFD is 140x32 native rendered at scale 9.
    assert img.width == 140 * 9
    assert img.height == 32 * 9


def test_vfd_preview_clear_resets_grid():
    # A clear after drawing must blank the panel.
    drawn = pr.render_vfd_preview([{"type": "text", "x": 0, "y": 0, "text": "X"}])
    cleared = pr.render_vfd_preview(
        [{"type": "text", "x": 0, "y": 0, "text": "X"}, {"type": "clear"}]
    )
    assert _decode_data_uri(drawn) != _decode_data_uri(cleared)


def test_vfd_idle_returns_png():
    _assert_png(pr.render_vfd_idle(), expected_w=140 * 9, expected_h=32 * 9)


def test_vfd_empty_commands_returns_blank_png():
    # No commands -> blank panel image, not an exception or None.
    _assert_png(pr.render_vfd_preview([]))


# ---------------------------------------------------------------------------
# render_oled_elements_preview() -- the screen editor's live preview calls
# this (via POST /api/screens/preview) so what an operator designs matches
# the real ArgonOLEDController.render_frame() output pixel-for-pixel,
# instead of the editor canvas's own client-side approximation.
# ---------------------------------------------------------------------------

def test_oled_elements_preview_returns_png_data_uri():
    uri = pr.render_oled_elements_preview([
        {"type": "text", "text": "HELLO", "x": 4, "y": 4},
        {"type": "icon", "name": "warning", "x": 4, "y": 20, "size": 12},
    ])
    _assert_png(uri)


def test_oled_elements_preview_empty_input_returns_none():
    assert pr.render_oled_elements_preview([]) is None
    assert pr.render_oled_elements_preview(None) is None


def test_oled_elements_preview_compass_does_not_raise():
    # Real device hardware (i2c/ssd1306) is mocked internally -- this must
    # never touch actual hardware even outside a request context.
    uri = pr.render_oled_elements_preview([
        {"type": "compass", "x": 30, "y": 30, "radius": 20, "heading": 90},
    ])
    _assert_png(uri, expected_w=128 * 4, expected_h=64 * 4)
