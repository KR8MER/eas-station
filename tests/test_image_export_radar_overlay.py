"""Tests for the share-card map's radar reflectivity overlay.

Three things this depends on, none of which fail loudly if they break:

* **Tile-to-Mercator math.** ``_tile_bbox_to_3857`` must give the WMS request
  the exact bbox the basemap tile mosaic covers, in meters -- get this wrong
  and the radar image silently misaligns with the polygon/basemap instead of
  erroring.
* **Time rounding.** The WMS-T service's capabilities document does not
  advertise nearest-value snapping (PT5M cadence), so requesting an
  un-rounded timestamp can come back with no data for an alert that really
  did have radar coverage.
* **Category gating.** Only weather (CAP category 'Met') alerts should ever
  trigger the radar fetch -- a road-closure or gas-leak share card has no
  reason to make this extra network call, let alone show a misleading empty
  radar frame.

The renderer package is loaded directly so the tests do not pay for the
full ``app_utils`` import (psutil, sqlalchemy, …) -- same pattern as
test_image_export_map_style.py.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    pytest.skip("Pillow is required for image_export tests", allow_module_level=True)


_PKG_DIR = Path(__file__).resolve().parent.parent / "app_utils" / "image_export"
_spec = importlib.util.spec_from_file_location(
    "image_export_radar_overlay_under_test",
    _PKG_DIR / "__init__.py",
    submodule_search_locations=[str(_PKG_DIR)],
)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = image_export
_spec.loader.exec_module(image_export)

maps_mod = image_export.maps
radar_level2_mod = image_export.radar_level2


# ── Tile-to-Mercator conversion ─────────────────────────────────────────────

def test_full_world_tile_maps_to_full_mercator_extent():
    """At z=0 there is exactly one tile, (0,0), covering the whole world."""
    x_min, y_min, x_max, y_max = maps_mod._tile_bbox_to_3857(0, 0, 0, 0, 0)
    extent = maps_mod._MERCATOR_EXTENT_M
    assert x_min == pytest.approx(-extent)
    assert x_max == pytest.approx(extent)
    assert y_min == pytest.approx(-extent)
    assert y_max == pytest.approx(extent)


def test_tile_bbox_north_is_higher_y_than_south():
    """Tile y increases southward (slippy-map convention); Mercator meters
    increase northward -- get the flip wrong and radar renders upside down
    relative to the basemap."""
    # ty=0 is the northernmost row at any zoom.
    _, _, _, y_max_north = maps_mod._tile_bbox_to_3857(0, 0, 0, 0, 4)
    _, y_min_south, _, _ = maps_mod._tile_bbox_to_3857(0, 15, 0, 15, 4)
    assert y_max_north > y_min_south


def test_wider_tile_range_gives_wider_bbox():
    single = maps_mod._tile_bbox_to_3857(5, 5, 5, 5, 4)
    double = maps_mod._tile_bbox_to_3857(5, 5, 6, 5, 4)
    single_width = single[2] - single[0]
    double_width = double[2] - double[0]
    assert double_width == pytest.approx(single_width * 2)


# ── Time rounding ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("input_minute,expected_minute", [
    (0, 0), (4, 0), (5, 5), (9, 5), (37, 35), (59, 55),
])
def test_floor_to_5min_rounds_down_to_the_wmst_cadence(input_minute, expected_minute):
    dt = datetime(2026, 8, 27, 9, input_minute, 42, tzinfo=timezone.utc)
    rounded = maps_mod._floor_to_5min(dt)
    assert rounded.minute == expected_minute
    assert rounded.second == 0 and rounded.microsecond == 0


def test_floor_to_5min_assumes_utc_for_naive_datetimes():
    naive = datetime(2026, 8, 27, 9, 37, 0)
    rounded = maps_mod._floor_to_5min(naive)
    assert rounded.tzinfo is not None
    assert rounded.minute == 35


# ── _fetch_radar_overlay ─────────────────────────────────────────────────────

def _fake_png_response(status_code=200, content_type="image/png"):
    buf_img = Image.new("RGBA", (4, 4), (0, 200, 0, 255))
    import io
    buf = io.BytesIO()
    buf_img.save(buf, format="PNG")
    resp = Mock()
    resp.status_code = status_code
    resp.headers = {"Content-Type": content_type}
    resp.content = buf.getvalue()
    resp.text = ""
    return resp


def test_fetch_radar_overlay_scales_down_alpha_for_legibility(monkeypatch):
    """The fetched tile is fully opaque; the overlay must come back at
    _RADAR_OPACITY so it doesn't obscure the hazard polygon drawn on top."""
    monkeypatch.setattr(maps_mod._http, "get", lambda *a, **k: _fake_png_response())

    result = maps_mod._fetch_radar_overlay(10, 10, 11, 11, 8, 512, 512, None)

    assert result is not None
    assert result.mode == "RGBA"
    _, _, _, alpha = result.split()
    max_alpha = alpha.getextrema()[1]
    assert max_alpha == pytest.approx(int(255 * maps_mod._RADAR_OPACITY), abs=2)


def test_fetch_radar_overlay_sends_time_param_rounded_to_5min(monkeypatch):
    captured = {}

    def _fake_get(url, params=None, **kwargs):
        captured.update(params or {})
        return _fake_png_response()

    monkeypatch.setattr(maps_mod._http, "get", _fake_get)

    when = datetime(2026, 8, 27, 9, 37, 12, tzinfo=timezone.utc)
    maps_mod._fetch_radar_overlay(10, 10, 11, 11, 8, 512, 512, when)

    assert captured["TIME"] == "2026-08-27T09:35:00Z"
    assert captured["LAYERS"] == maps_mod._RADAR_WMS_LAYER
    assert captured["SRS"] == "EPSG:3857"


def test_fetch_radar_overlay_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(maps_mod._http, "get", lambda *a, **k: _fake_png_response(status_code=500))
    result = maps_mod._fetch_radar_overlay(10, 10, 11, 11, 8, 512, 512, None)
    assert result is None


def test_fetch_radar_overlay_returns_none_on_network_exception(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("no route to host")
    monkeypatch.setattr(maps_mod._http, "get", _raise)
    result = maps_mod._fetch_radar_overlay(10, 10, 11, 11, 8, 512, 512, None)
    assert result is None


# ── _render_map category gating ─────────────────────────────────────────────

_TEST_GEOM = {
    "type": "Polygon",
    "coordinates": [[[-84.30, 41.10], [-83.85, 40.86], [-83.90, 40.72],
                     [-84.22, 40.61], [-84.30, 41.10]]],
}


def test_render_map_fetches_radar_for_met_category(monkeypatch):
    monkeypatch.setattr(maps_mod, "_fetch_tile", lambda tx, ty, z: None)
    monkeypatch.setattr(maps_mod, "_fetch_county_outlines", lambda *a, **k: [])
    calls = []
    monkeypatch.setattr(
        maps_mod, "_fetch_radar_overlay",
        lambda *a, **k: calls.append(True) or None,
    )

    maps_mod._render_map(_TEST_GEOM, "severe", category="Met", map_w=300, map_h=250)

    assert len(calls) == 1


def test_render_map_never_calls_level2(monkeypatch):
    """The share card, the Radar Loop, and the alert page's live "Radar (at
    time of alert)" toggle (a Leaflet WMS tile layer -- see
    static/js/core/map_theme.js's radarLayer()) must all show the same
    radar product for the same alert. _render_map() therefore always goes
    through the Level III WMS mosaic and never touches radar_level2's
    Level II decode, which used a different resolution and color ramp and
    made the share card/loop look like a different storm than the live
    toggle for the same alert."""
    monkeypatch.setattr(maps_mod, "_fetch_tile", lambda tx, ty, z: None)
    monkeypatch.setattr(maps_mod, "_fetch_county_outlines", lambda *a, **k: [])

    level2_calls = []

    def fake_level2(*args, **kwargs):
        level2_calls.append(True)
        canvas_w, canvas_h = args[4], args[5]
        return Image.new("RGBA", (canvas_w, canvas_h), (0, 128, 0, 100))

    monkeypatch.setattr(radar_level2_mod, "render_frame", fake_level2)

    wms_calls = []
    monkeypatch.setattr(
        maps_mod, "_fetch_radar_overlay",
        lambda *a, **k: wms_calls.append(True) or None,
    )

    maps_mod._render_map(_TEST_GEOM, "severe", category="Met", map_w=300, map_h=250)

    assert level2_calls == []
    assert len(wms_calls) == 1


@pytest.mark.parametrize("category", [None, "Transport", "Safety", "Geo", "Other"])
def test_render_map_skips_radar_for_non_met_categories(monkeypatch, category):
    monkeypatch.setattr(maps_mod, "_fetch_tile", lambda tx, ty, z: None)
    monkeypatch.setattr(maps_mod, "_fetch_county_outlines", lambda *a, **k: [])
    calls = []
    monkeypatch.setattr(
        maps_mod, "_fetch_radar_overlay",
        lambda *a, **k: calls.append(True) or None,
    )

    maps_mod._render_map(_TEST_GEOM, "severe", category=category, map_w=300, map_h=250)

    assert calls == []


def test_render_map_survives_radar_fetch_failure(monkeypatch):
    """A missing radar layer must never break the share card -- it already
    renders fine without one (WMS error, no coverage, etc.)."""
    monkeypatch.setattr(maps_mod, "_fetch_tile", lambda tx, ty, z: None)
    monkeypatch.setattr(maps_mod, "_fetch_county_outlines", lambda *a, **k: [])
    monkeypatch.setattr(maps_mod, "_fetch_radar_overlay", lambda *a, **k: None)

    img = maps_mod._render_map(_TEST_GEOM, "severe", category="Met", map_w=300, map_h=250)

    assert img.size == (300, 250)
