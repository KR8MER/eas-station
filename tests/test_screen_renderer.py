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

import pytest
import requests

import scripts.screen_renderer as screen_renderer


def _raise_connection_error(*args, **kwargs):  # pragma: no cover - helper
    raise requests.exceptions.ConnectionError("network down")


def test_fetch_data_source_without_preview_samples(monkeypatch):
    renderer = screen_renderer.ScreenRenderer(allow_preview_samples=False)
    monkeypatch.setattr(screen_renderer.requests, "get", _raise_connection_error)

    renderer.fetch_data_source("/api/system_status", "status")

    assert renderer._data_cache["status"] == {}


def test_fetch_data_source_with_preview_samples(monkeypatch):
    renderer = screen_renderer.ScreenRenderer(allow_preview_samples=True)
    monkeypatch.setattr(screen_renderer.requests, "get", _raise_connection_error)

    renderer.fetch_data_source("/api/system_status", "status")

    assert renderer._data_cache["status"] == screen_renderer.PREVIEW_SAMPLE_DATA["status"]


def test_oled_elements_compass_resolves_heading_template():
    renderer = screen_renderer.ScreenRenderer()
    template = {
        "elements": [
            {"type": "compass", "x": 30, "y": 30, "radius": 20, "heading": "{gps.track_angle}"},
        ],
    }
    api_data = {"gps": {"track_angle": 214.5}}

    rendered = renderer._render_oled_elements(template, api_data)

    assert rendered["elements"][0]["type"] == "compass"
    assert rendered["elements"][0]["heading"] == pytest.approx(214.5)


def test_oled_elements_compass_missing_heading_is_none():
    renderer = screen_renderer.ScreenRenderer()
    template = {
        "elements": [
            {"type": "compass", "x": 30, "y": 30, "radius": 20, "heading": "{gps.track_angle}"},
        ],
    }
    # No 'gps' key in api_data at all -- unresolvable template.
    rendered = renderer._render_oled_elements(template, {})

    assert rendered["elements"][0]["heading"] is None


def test_oled_elements_bars_resolves_values_source():
    renderer = screen_renderer.ScreenRenderer()
    template = {
        "elements": [
            {"type": "bars", "x": 0, "y": 0, "width": 40, "height": 16,
             "values_source": "gps.satellite_snrs", "max_value": 50},
        ],
    }
    api_data = {"gps": {"satellite_snrs": [45, 38, "bad", 12]}}

    rendered = renderer._render_oled_elements(template, api_data)

    # Non-numeric entries are dropped rather than crashing the render.
    assert rendered["elements"][0]["values"] == [45.0, 38.0, 12.0]


def test_oled_elements_bars_missing_source_is_empty_list():
    renderer = screen_renderer.ScreenRenderer()
    template = {
        "elements": [
            {"type": "bars", "x": 0, "y": 0, "width": 40, "height": 16},
        ],
    }
    rendered = renderer._render_oled_elements(template, {})

    assert rendered["elements"][0]["values"] == []


# ---------------------------------------------------------------------------
# render_vfd_screen -- resolved-elements shape (matches render_oled_screen's
# {'elements': [...]} contract so both engines push one bitmap per frame)
# ---------------------------------------------------------------------------

def test_render_vfd_screen_returns_elements_dict_not_command_list():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {
        "template_data": {
            "elements": [
                {"type": "text", "text": "{status.hostname}", "x": 0, "y": 0},
            ],
        },
    }
    rendered = renderer.render_vfd_screen(screen_data, {"status": {"hostname": "eas-demo"}})

    assert isinstance(rendered, dict)
    assert rendered["elements"][0] == {
        "type": "text", "x": 0, "y": 0, "text": "eas-demo", "invert": None,
        "max_width": None, "overflow": None, "font": None,
    }
    assert rendered["clear"] is True


def test_render_vfd_screen_text_passes_through_max_width_and_overflow():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {
        "template_data": {
            "elements": [
                {"type": "text", "text": "{alerts.features[0].properties.event}",
                 "x": 0, "y": 11, "max_width": 130, "overflow": "ellipsis"},
            ],
        },
    }
    api_data = {"alerts": {"features": [{"properties": {"event": "Severe Thunderstorm Warning"}}]}}
    rendered = renderer.render_vfd_screen(screen_data, api_data)

    el = rendered["elements"][0]
    assert el["text"] == "Severe Thunderstorm Warning"
    assert el["max_width"] == 130
    assert el["overflow"] == "ellipsis"


def test_render_vfd_screen_text_passes_through_font():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {
        "template_data": {
            "elements": [
                {"type": "text", "text": "{now.time_24}", "x": 2, "y": 9, "font": "large"},
            ],
        },
    }
    rendered = renderer.render_vfd_screen(screen_data, {})

    assert rendered["elements"][0]["font"] == "large"


def test_render_vfd_screen_segments_resolves_value_and_clamps():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {
        "template_data": {
            "elements": [
                {"type": "segments", "x": 0, "y": 0, "width": 100, "height": 8,
                 "value": "{audio.level}", "count": 14, "gap": 2},
            ],
        },
    }
    rendered = renderer.render_vfd_screen(screen_data, {"audio": {"level": 150}})

    seg = rendered["elements"][0]
    assert seg["type"] == "segments"
    assert seg["value"] == 100.0  # clamped
    assert seg["count"] == 14


def test_render_vfd_screen_bar_resolves_value_and_clamps():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {
        "template_data": {
            "elements": [
                {"type": "bar", "x": 0, "y": 0, "width": 100, "height": 8, "value": "{audio.level}"},
            ],
        },
    }
    rendered = renderer.render_vfd_screen(screen_data, {"audio": {"level": 150}})

    bar = next(el for el in rendered["elements"] if el["type"] == "bar")
    assert bar["value"] == 100.0  # clamped


def test_render_vfd_screen_supports_new_icon_and_gauge_elements():
    """The old VFD path only understood text/rectangle/line/bar; confirms
    the richer OLED-style vocabulary (icon, gauge, compass, bars) now
    survives render_vfd_screen() too."""
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {
        "template_data": {
            "elements": [
                {"type": "icon", "name": "heartbeat", "x": 2, "y": 2, "size": 8},
                {"type": "gauge", "x": 40, "y": 28, "radius": 12, "value": "{status.score}"},
                {"type": "compass", "x": 100, "y": 16, "radius": 10, "heading": "{gps.track_angle}"},
                {"type": "bars", "x": 0, "y": 0, "width": 40, "height": 16, "values_source": "gps.snrs"},
            ],
        },
    }
    api_data = {"status": {"score": 80}, "gps": {"track_angle": 45, "snrs": [10, 20]}}
    rendered = renderer.render_vfd_screen(screen_data, api_data)

    types = {el["type"] for el in rendered["elements"]}
    assert types == {"icon", "gauge", "compass", "bars"}
    gauge = next(el for el in rendered["elements"] if el["type"] == "gauge")
    assert gauge["value"] == 80.0
    compass = next(el for el in rendered["elements"] if el["type"] == "compass")
    assert compass["heading"] == 45.0
    bars = next(el for el in rendered["elements"] if el["type"] == "bars")
    assert bars["values"] == [10.0, 20.0]


# ---------------------------------------------------------------------------
# The 5 VFD screens added to bring the VFD to parity with the OLED's 11
# default screens (vfd_gpio_status, vfd_eas_decoder, vfd_audio_health,
# vfd_ipaws_poll_watch, vfd_receivers) -- each reuses an existing OLED
# screen's data source and field paths, so these confirm the exact nested
# paths those screens use resolve correctly through render_vfd_screen().
# ---------------------------------------------------------------------------

def test_render_vfd_screen_gpio_status_resolves_fields():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {"elements": [
        {"type": "text", "text": "{gpio.active_count}", "x": 111, "y": 0},
        {"type": "text", "text": "{gpio.active_pins_summary}", "x": 9, "y": 11},
        {"type": "text", "text": "{gpio.activations_today} today", "x": 9, "y": 20},
    ]}}
    api_data = {"gpio": {"active_count": 2, "active_pins_summary": "Siren, Strobe", "activations_today": 5}}
    rendered = renderer.render_vfd_screen(screen_data, api_data)

    texts = [el["text"] for el in rendered["elements"]]
    assert texts == ["2", "Siren, Strobe", "5 today"]


def test_render_vfd_screen_eas_decoder_gauge_resolves_health_percentage():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {"elements": [
        {"type": "gauge", "x": 18, "y": 20, "radius": 11, "value": "{eas_monitor.health_percentage}"},
        {"type": "text", "text": "Alerts {eas_monitor.alerts_detected}", "x": 34, "y": 20},
    ]}}
    api_data = {"eas_monitor": {"health_percentage": 92, "alerts_detected": 4}}
    rendered = renderer.render_vfd_screen(screen_data, api_data)

    gauge = next(el for el in rendered["elements"] if el["type"] == "gauge")
    assert gauge["value"] == 92.0
    text = next(el for el in rendered["elements"] if el["type"] == "text")
    assert text["text"] == "Alerts 4"


def test_render_vfd_screen_audio_health_resolves_score_and_bar():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {"elements": [
        {"type": "bar", "x": 34, "y": 10, "width": 74, "height": 8, "value": "{audio_health.overall_health_score}"},
        {"type": "text", "text": "{audio_health.active_sources}/{audio_health.total_sources} active", "x": 9, "y": 20},
    ]}}
    api_data = {"audio_health": {"overall_health_score": 88, "active_sources": 3, "total_sources": 3}}
    rendered = renderer.render_vfd_screen(screen_data, api_data)

    bar = next(el for el in rendered["elements"] if el["type"] == "bar")
    assert bar["value"] == 88.0
    text = next(el for el in rendered["elements"] if el["type"] == "text")
    assert text["text"] == "3/3 active"


def test_render_vfd_screen_ipaws_poll_watch_resolves_nested_last_poll():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {"elements": [
        {"type": "text", "text": "{status.last_poll.status}", "x": 9, "y": 11},
        {"type": "text", "text": "+{status.last_poll.alerts_new} new  {status.last_poll.alerts_fetched} fetched", "x": 0, "y": 20},
    ]}}
    api_data = {"status": {"last_poll": {"status": "OK - Success", "alerts_new": 2, "alerts_fetched": 14}}}
    rendered = renderer.render_vfd_screen(screen_data, api_data)

    texts = [el["text"] for el in rendered["elements"]]
    assert texts == ["OK - Success", "+2 new  14 fetched"]


def test_render_vfd_screen_receivers_resolves_indexed_array_fields():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {"elements": [
        {"type": "text",
         "text": "{radio.receivers[0].display_name} {radio.receivers[0].latest_status.signal_strength}dBm",
         "x": 9, "y": 11},
        {"type": "text",
         "text": "{radio.receivers[1].display_name} {radio.receivers[1].latest_status.signal_strength}dBm",
         "x": 9, "y": 20},
    ]}}
    api_data = {"radio": {"receivers": [
        {"display_name": "NOAA WX Ch4", "latest_status": {"signal_strength": -62}},
        {"display_name": "VHF Marine", "latest_status": {"signal_strength": -74}},
    ]}}
    rendered = renderer.render_vfd_screen(screen_data, api_data)

    texts = [el["text"] for el in rendered["elements"]]
    assert texts == ["NOAA WX Ch4 -62dBm", "VHF Marine -74dBm"]


# ---------------------------------------------------------------------------
# render_led_screen -- graphics mode ({'elements': [...]}, template_data has
# an 'elements' key) vs. legacy 4-line scrolling-text mode ({'lines': [...]})
# ---------------------------------------------------------------------------

def test_render_led_screen_legacy_lines_mode_unaffected():
    """The pre-existing 4-line scrolling-text path (6 default LED screens)
    must keep working unchanged -- graphics mode is opt-in via an
    'elements' key, not a replacement."""
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {
        "lines": ["{status.hostname}", "line2"],
        "color": "GREEN", "mode": "HOLD", "speed": "SPEED_3",
    }}
    rendered = renderer.render_led_screen(screen_data, {"status": {"hostname": "eas-demo"}})

    assert "elements" not in rendered
    assert rendered["lines"][0] == "eas-demo"
    assert rendered["color"] == "GREEN"


def test_render_led_screen_graphics_mode_returns_elements_dict():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {
        "elements": [
            {"type": "text", "text": "{now.time_24}", "x": 18, "y": 1, "font": "large"},
        ],
        "color": "AMBER",
    }}
    rendered = renderer.render_led_screen(screen_data, {})

    assert "lines" not in rendered
    assert rendered["color"] == "AMBER"
    assert rendered["elements"][0]["font"] == "large"


def test_render_led_screen_graphics_mode_icon_and_bar_resolve():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {"elements": [
        {"type": "icon", "name": "heartbeat", "x": 1, "y": 1, "size": 14},
        {"type": "bar", "x": 0, "y": 0, "width": 40, "height": 8, "value": "{status.cpu}"},
    ]}}
    rendered = renderer.render_led_screen(screen_data, {"status": {"cpu": 150}})

    icon = next(el for el in rendered["elements"] if el["type"] == "icon")
    assert icon["name"] == "heartbeat"
    bar = next(el for el in rendered["elements"] if el["type"] == "bar")
    assert bar["value"] == 100.0  # clamped


def test_render_led_screen_graphics_mode_unknown_element_type_dropped():
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {"elements": [
        {"type": "gauge", "x": 0, "y": 0, "radius": 10, "value": 50},
        {"type": "text", "text": "OK", "x": 0, "y": 4},
    ]}}
    rendered = renderer.render_led_screen(screen_data, {})

    types = {el["type"] for el in rendered["elements"]}
    assert types == {"text"}


def test_render_led_screen_graphics_mode_dotted_hline_folds_to_hline():
    """The screen editor's shared 'H-Divider' element type emits
    'dotted_hline' when its Dotted checkbox is on -- render_led_elements()
    has no dotted rendering at all (same downgrade-to-solid convention
    render_vfd_screen() already uses), so this must fold to plain 'hline'
    rather than being silently dropped."""
    renderer = screen_renderer.ScreenRenderer()
    screen_data = {"template_data": {"elements": [
        {"type": "dotted_hline", "x": 0, "y": 8, "width": 160},
    ]}}
    rendered = renderer.render_led_screen(screen_data, {})

    assert len(rendered["elements"]) == 1
    assert rendered["elements"][0]["type"] == "hline"
