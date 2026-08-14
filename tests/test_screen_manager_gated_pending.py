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

"""Tests for the gated-alerts "Pending Review" display scene.

Covers scripts/screen_manager_gated.py (pure builders + hardware-push
helpers) and the rotation-priority wiring added to ScreenManager in
scripts/screen_manager.py: the scene must rank below an active/incoming
CAP alert but above routine rotation content, and must never appear when
the pending count is zero.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from scripts.screen_manager_gated import (
    build_led_pending_message,
    build_oled_pending_elements,
    build_vfd_pending_elements,
    push_led_pending_scene,
    push_oled_pending_scene,
    push_vfd_pending_scene,
    query_gated_pending_summary,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# query_gated_pending_summary
# ---------------------------------------------------------------------------

def _fake_gated_alert_cls(rows):
    """Build a mock GatedAlert-like class with the query chain used by
    query_gated_pending_summary (mirrors webapp/admin/pending_alerts.py's
    query: without_audio().filter_by(status='pending').order_by(...).limit(n).all())."""
    cls = MagicMock(name="GatedAlert")
    chain = cls.without_audio.return_value
    chain.filter_by.return_value = chain
    chain.order_by.return_value = chain
    chain.limit.return_value = chain
    chain.all.return_value = rows
    return cls


def test_query_gated_pending_summary_empty():
    gated_alert_cls = _fake_gated_alert_cls([])
    count, items = query_gated_pending_summary(gated_alert_cls=gated_alert_cls)
    assert count == 0
    assert items == []


def test_query_gated_pending_summary_formats_rows():
    row1 = MagicMock(event_code="TOR", headline="Tornado Warning near Springfield")
    row2 = MagicMock(event_code=None, event="Severe Thunderstorm Warning", headline=None)
    gated_alert_cls = _fake_gated_alert_cls([row1, row2])

    count, items = query_gated_pending_summary(gated_alert_cls=gated_alert_cls)

    assert count == 2
    assert items[0] == {"event_code": "TOR", "headline": "Tornado Warning near Springfield"}
    # Falls back to `event` when headline is blank, and event_code defaults to "".
    assert items[1] == {"event_code": "", "headline": "Severe Thunderstorm Warning"}

    gated_alert_cls.without_audio.return_value.limit.assert_called_once_with(8)


def test_query_gated_pending_summary_respects_custom_limit():
    gated_alert_cls = _fake_gated_alert_cls([])
    query_gated_pending_summary(limit=3, gated_alert_cls=gated_alert_cls)
    gated_alert_cls.without_audio.return_value.limit.assert_called_once_with(3)


# ---------------------------------------------------------------------------
# build_oled_pending_elements
# ---------------------------------------------------------------------------

def test_build_oled_pending_elements_returns_none_when_zero():
    assert build_oled_pending_elements(0, []) is None


def test_build_oled_pending_elements_header_shows_count():
    items = [{"event_code": "TOR", "headline": "Tornado Warning"}]
    elements = build_oled_pending_elements(3, items)
    assert elements is not None
    header_texts = [el["text"] for el in elements if el.get("type") == "text" and el.get("invert")]
    assert "PENDING REVIEW" in header_texts
    assert "3" in header_texts


def test_build_oled_pending_elements_caps_visible_rows_and_adds_more_line():
    items = [
        {"event_code": f"E{i}", "headline": f"Headline {i}"} for i in range(5)
    ]
    elements = build_oled_pending_elements(5, items)
    body_rows = [el for el in elements if el.get("type") == "text" and not el.get("invert")]
    # 3 item rows + 1 "+N more" row
    assert len(body_rows) == 4
    assert body_rows[-1]["text"] == "+2 more"


def test_build_oled_pending_elements_uses_ellipsis_overflow_for_truncation():
    items = [{"event_code": "TOR", "headline": "x" * 200}]
    elements = build_oled_pending_elements(1, items)
    item_row = [el for el in elements if el.get("type") == "text" and not el.get("invert")][0]
    assert item_row["overflow"] == "ellipsis"
    assert item_row["max_width"] > 0


# ---------------------------------------------------------------------------
# build_led_pending_message
# ---------------------------------------------------------------------------

def test_build_led_pending_message_returns_none_when_zero():
    assert build_led_pending_message(0, []) is None


def test_build_led_pending_message_singular_vs_plural():
    single = build_led_pending_message(1, [{"event_code": "TOR", "headline": "Tornado Warning"}])
    plural = build_led_pending_message(2, [{"event_code": "TOR", "headline": "Tornado Warning"}])
    assert "1 ALERT " in single["lines"][0] or single["lines"][0].endswith("1 ALERT")
    assert "2 ALERTS" in plural["lines"][0]
    assert single["mode"] == "SCROLL"
    assert single["color"] == "YELLOW"


def test_build_led_pending_message_includes_top_item_detail():
    message = build_led_pending_message(1, [{"event_code": "TOR", "headline": "Tornado Warning"}])
    assert "TOR" in message["lines"][0]
    assert "Tornado Warning" in message["lines"][0]


def test_build_led_pending_message_truncates_long_text():
    long_headline = "x" * 300
    message = build_led_pending_message(1, [{"event_code": "TOR", "headline": long_headline}])
    assert len(message["lines"][0]) <= 120
    assert message["lines"][0].endswith("…")


# ---------------------------------------------------------------------------
# build_vfd_pending_elements
# ---------------------------------------------------------------------------

def test_build_vfd_pending_elements_returns_none_when_zero():
    assert build_vfd_pending_elements(0, []) is None


def test_build_vfd_pending_elements_shape():
    items = [{"event_code": "TOR", "headline": "Tornado Warning"}]
    elements = build_vfd_pending_elements(2, items)
    types = [el["type"] for el in elements]
    assert "rectangle" in types
    assert "icon" in types
    text_values = " ".join(el["text"] for el in elements if el["type"] == "text")
    assert "2" in text_values
    assert "TOR" in text_values


def test_build_vfd_pending_elements_truncates_lines():
    items = [{"event_code": "TOR", "headline": "x" * 100}]
    elements = build_vfd_pending_elements(1, items)
    for element in elements:
        if element.get("type") == "text":
            assert len(element["text"]) <= 20


# ---------------------------------------------------------------------------
# push_* hardware helpers
# ---------------------------------------------------------------------------

def test_push_oled_pending_scene_calls_render_frame():
    controller = MagicMock(width=128, height=64)
    items = [{"event_code": "TOR", "headline": "Tornado Warning"}]
    result = push_oled_pending_scene(controller, 1, items)
    assert result is True
    controller.render_frame.assert_called_once()
    elements_arg = controller.render_frame.call_args[0][0]
    assert isinstance(elements_arg, list) and len(elements_arg) > 0


def test_push_oled_pending_scene_noop_when_zero():
    controller = MagicMock(width=128, height=64)
    result = push_oled_pending_scene(controller, 0, [])
    assert result is False
    controller.render_frame.assert_not_called()


def test_push_oled_pending_scene_swallows_render_exception():
    controller = MagicMock(width=128, height=64)
    controller.render_frame.side_effect = RuntimeError("boom")
    result = push_oled_pending_scene(controller, 1, [{"event_code": "TOR", "headline": "x"}])
    assert result is False


def test_push_led_pending_scene_sends_message_with_named_enums():
    led_module = MagicMock()
    led_module.Color.YELLOW = "yellow-enum"
    led_module.DisplayMode.SCROLL = "scroll-enum"
    led_module.Speed.SPEED_3 = "speed3-enum"
    led_module.led_controller = MagicMock()

    rendered = push_led_pending_scene(led_module, 1, [{"event_code": "TOR", "headline": "Tornado Warning"}])

    assert rendered is not None
    led_module.led_controller.send_message.assert_called_once()
    kwargs = led_module.led_controller.send_message.call_args.kwargs
    assert kwargs["color"] == "yellow-enum"
    assert kwargs["mode"] == "scroll-enum"
    assert kwargs["speed"] == "speed3-enum"


def test_push_led_pending_scene_noop_when_no_controller():
    led_module = MagicMock()
    led_module.led_controller = None
    result = push_led_pending_scene(led_module, 3, [{"event_code": "TOR", "headline": "x"}])
    assert result is None


def test_push_vfd_pending_scene_calls_render_frame():
    vfd_module = MagicMock()
    vfd_module.vfd_controller = MagicMock()

    elements = push_vfd_pending_scene(vfd_module, 1, [{"event_code": "TOR", "headline": "Tornado Warning"}])

    assert elements is not None
    vfd_module.vfd_controller.render_frame.assert_called_once()
    elements_arg = vfd_module.vfd_controller.render_frame.call_args[0][0]
    assert isinstance(elements_arg, list) and len(elements_arg) > 0


def test_push_vfd_pending_scene_noop_when_no_controller():
    vfd_module = MagicMock()
    vfd_module.vfd_controller = None
    result = push_vfd_pending_scene(vfd_module, 3, [{"event_code": "TOR", "headline": "x"}])
    assert result is None


# ---------------------------------------------------------------------------
# ScreenManager rotation-priority wiring
# ---------------------------------------------------------------------------

def test_screen_manager_gated_pending_attrs_default_empty():
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    assert manager._gated_pending_count == 0
    assert manager._gated_pending_alerts == []
    # Distinct from the pre-existing, unrelated "next active CAPAlert" concept.
    assert manager._pending_alert is None


def test_led_rotation_shows_gated_scene_instead_of_normal_screens():
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._led_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": False}
    manager._gated_pending_count = 2
    manager._gated_pending_alerts = [{"event_code": "TOR", "headline": "Tornado Warning"}]
    manager._display_gated_pending_led = MagicMock()
    manager._display_led_screen = MagicMock()

    manager._check_led_rotation()

    manager._display_gated_pending_led.assert_called_once()
    manager._display_led_screen.assert_not_called()


def test_led_rotation_falls_through_to_normal_screens_when_no_pending():
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._led_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": False}
    manager._gated_pending_count = 0
    manager._last_led_update = datetime.min
    manager._display_gated_pending_led = MagicMock()
    manager._display_led_screen = MagicMock()
    manager._update_rotation_state = MagicMock()

    manager._check_led_rotation()

    manager._display_gated_pending_led.assert_not_called()
    manager._display_led_screen.assert_called_once()


def test_led_rotation_freezes_when_skip_on_alert_true_and_alert_active():
    """Same bug as the VFD's (see test_vfd_rotation_freezes_...): with
    skip_on_alert True (the seeded default before 20260814_add_led_
    graphics_screens.py), _check_led_rotation() returns before reaching
    either the gated-pending scene or the normal rotation loop -- the LED
    has no OLED-style alert-preemption path, so this froze the sign on
    whatever was last shown for the alert's whole duration."""
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._led_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": True}
    manager._gated_pending_count = 0
    manager._has_active_alerts = MagicMock(return_value=True)
    manager._display_gated_pending_led = MagicMock()
    manager._display_led_screen = MagicMock()

    manager._check_led_rotation()

    manager._display_gated_pending_led.assert_not_called()
    manager._display_led_screen.assert_not_called()


def test_led_rotation_continues_when_skip_on_alert_false_and_alert_active():
    """20260814_add_led_graphics_screens.py flips the seeded default to
    False so the rotation (which already includes led_alert_summary)
    keeps cycling during an active CAP alert instead of freezing."""
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._led_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": False}
    manager._gated_pending_count = 0
    manager._has_active_alerts = MagicMock(return_value=True)
    manager._display_gated_pending_led = MagicMock()
    manager._display_led_screen = MagicMock()

    manager._check_led_rotation()

    manager._display_gated_pending_led.assert_not_called()
    manager._display_led_screen.assert_called_once()


def test_vfd_rotation_shows_gated_scene_instead_of_normal_screens():
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._vfd_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": False}
    manager._gated_pending_count = 1
    manager._display_gated_pending_vfd = MagicMock()
    manager._display_vfd_screen = MagicMock()

    manager._check_vfd_rotation()

    manager._display_gated_pending_vfd.assert_called_once()
    manager._display_vfd_screen.assert_not_called()


def test_vfd_rotation_freezes_when_skip_on_alert_true_and_alert_active():
    """The historical bug this guards against re-appearing: with
    skip_on_alert True (the old seeded default), _check_vfd_rotation()
    returns before reaching either the gated-pending scene or the normal
    rotation loop -- unlike OLED, the VFD has no dedicated alert-preemption
    display, so this path drew nothing at all, freezing the panel on
    whatever was last shown for the alert's whole duration."""
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._vfd_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": True}
    manager._gated_pending_count = 0
    manager._has_active_alerts = MagicMock(return_value=True)
    manager._display_gated_pending_vfd = MagicMock()
    manager._display_vfd_screen = MagicMock()

    manager._check_vfd_rotation()

    manager._display_gated_pending_vfd.assert_not_called()
    manager._display_vfd_screen.assert_not_called()


def test_vfd_rotation_continues_when_skip_on_alert_false_and_alert_active():
    """20260814_add_vfd_status_screens.py flips the seeded default to
    False specifically so the rotation (which now includes vfd_alert_status)
    keeps cycling during an active CAP alert instead of freezing."""
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._vfd_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": False}
    manager._gated_pending_count = 0
    manager._has_active_alerts = MagicMock(return_value=True)
    manager._display_gated_pending_vfd = MagicMock()
    manager._display_vfd_screen = MagicMock()

    manager._check_vfd_rotation()

    manager._display_gated_pending_vfd.assert_not_called()
    manager._display_vfd_screen.assert_called_once()


def test_oled_rotation_shows_gated_scene_instead_of_normal_screens():
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._oled_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": False}
    manager._gated_pending_count = 1
    manager._display_gated_pending_oled = MagicMock()
    manager._display_oled_screen = MagicMock()

    manager._check_oled_rotation()

    manager._display_gated_pending_oled.assert_called_once()
    manager._display_oled_screen.assert_not_called()


def test_oled_rotation_active_alert_still_takes_priority_over_gated_scene():
    """skip_on_alert + an active CAP alert must preempt the OLED before the
    gated-pending check is ever reached -- the Pending Review scene ranks
    below an active/incoming alert, never above it."""
    from scripts.screen_manager import ScreenManager

    manager = ScreenManager()
    manager._oled_rotation = {"screens": [{"screen_id": 1, "duration": 5}], "skip_on_alert": True}
    manager._gated_pending_count = 5
    manager._handle_oled_alert_preemption = MagicMock(return_value=True)
    manager._display_gated_pending_oled = MagicMock()
    manager._display_oled_screen = MagicMock()

    manager._check_oled_rotation()

    manager._handle_oled_alert_preemption.assert_called_once()
    manager._display_gated_pending_oled.assert_not_called()
    manager._display_oled_screen.assert_not_called()


def test_gated_pending_oled_display_respects_refresh_throttle():
    import sys
    from unittest.mock import patch

    from scripts.screen_manager import GATED_PENDING_REFRESH_SECONDS, ScreenManager

    manager = ScreenManager()
    manager._gated_pending_count = 1
    manager._gated_pending_alerts = [{"event_code": "TOR", "headline": "x"}]
    now = datetime.utcnow()
    manager._last_oled_gated_update = now

    fake_oled_module = MagicMock()
    fake_oled_module.oled_controller = MagicMock(width=128, height=64)
    fake_oled_module.initialise_oled_display = MagicMock()

    with patch.dict(sys.modules, {"app_core.oled": fake_oled_module}), \
         patch("scripts.screen_manager_gated.push_oled_pending_scene", return_value=True) as push_mock:

        # Still within the throttle window: must not render again.
        manager._display_gated_pending_oled(now + timedelta(seconds=1))
        push_mock.assert_not_called()

        # Past the throttle window: renders and updates the timestamp.
        later = now + timedelta(seconds=GATED_PENDING_REFRESH_SECONDS + 1)
        manager._display_gated_pending_oled(later)
        push_mock.assert_called_once()
        assert manager._last_oled_gated_update == later


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
