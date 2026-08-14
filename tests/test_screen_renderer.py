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
