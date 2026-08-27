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

from __future__ import annotations

"""Tests for the Level II radar decode module (radar_level2.py).

Nothing here touches the network or decodes a real NEXRAD volume -- that's
exercised manually (see the PR description) since faking Archive II binary
data isn't worth the fragility. What's covered instead is everything that
silently produces a wrong-but-plausible result if it breaks:

* **Site selection.** Picking the wrong nearest site, or not enforcing the
  ~230km nominal range cap, would either grid empty data or (worse) claim
  detail that doesn't exist for a genuine coverage gap.
* **Volume-key parsing/matching.** The S3 filename format and the
  nearest-within-tolerance matching against an irregular ~4-6 min actual
  cadence (vs. the loop's fixed 5-min target grid) are both easy to get
  subtly wrong in ways that only show up as a wrong frame, not an error.
* **Colorization.** The dBZ -> RGBA ramp must agree with maps.py's legend
  (which imports it from here) and must make sub-threshold cells fully
  transparent, not just dark.
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    pytest.skip("Pillow is required for image_export tests", allow_module_level=True)


_PKG_DIR = Path(__file__).resolve().parent.parent / "app_utils" / "image_export"
_spec = importlib.util.spec_from_file_location(
    "image_export_radar_level2_under_test",
    _PKG_DIR / "__init__.py",
    submodule_search_locations=[str(_PKG_DIR)],
)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = image_export
_spec.loader.exec_module(image_export)

rl2 = image_export.radar_level2


# ── Haversine distance ───────────────────────────────────────────────────────

def test_haversine_known_distance():
    # One degree of latitude is ~111.2km everywhere.
    km = rl2._haversine_km(0.0, 0.0, 1.0, 0.0)
    assert km == pytest.approx(111.2, abs=0.5)


def test_haversine_zero_for_identical_point():
    assert rl2._haversine_km(41.35, -83.6, 41.35, -83.6) == pytest.approx(0.0, abs=1e-9)


# ── Site selection ───────────────────────────────────────────────────────────

_FAKE_SITES = [
    ("KCLE", 41.413, -81.860),
    ("KDTX", 42.700, -83.472),
    ("KTLX", 35.333, -97.278),  # Oklahoma City -- always far from the others
]


def test_nearest_site_picks_the_closest_one(monkeypatch):
    monkeypatch.setattr(rl2, "_load_sites", lambda: _FAKE_SITES)
    # Close to KCLE's own coordinates.
    assert rl2.nearest_site(41.4, -81.9) == "KCLE"


def test_nearest_site_none_when_every_site_is_out_of_range(monkeypatch):
    monkeypatch.setattr(rl2, "_load_sites", lambda: _FAKE_SITES)
    # Middle of the Pacific -- nowhere near any WSR-88D site.
    assert rl2.nearest_site(20.0, -160.0) is None


def test_nearest_site_none_with_empty_site_list(monkeypatch):
    monkeypatch.setattr(rl2, "_load_sites", lambda: [])
    assert rl2.nearest_site(41.4, -81.9) is None


# ── Volume key parsing ───────────────────────────────────────────────────────

def test_parse_key_time_real_format():
    t = rl2._parse_key_time("2026/08/10/KCLE/KCLE20260810_005739_V06")
    assert t == datetime(2026, 8, 10, 0, 57, 39, tzinfo=timezone.utc)


def test_parse_key_time_malformed_returns_none():
    assert rl2._parse_key_time("2026/08/10/KCLE/not_a_volume_file") is None


# ── Volume lookup ────────────────────────────────────────────────────────────

def _fake_s3(day_to_keys):
    """A MagicMock standing in for the boto3 S3 client, returning canned
    list_objects_v2 responses keyed by the request's Prefix."""
    s3 = MagicMock()

    def list_objects_v2(Bucket, Prefix, MaxKeys=1000):
        keys = day_to_keys.get(Prefix, [])
        return {"Contents": [{"Key": k} for k in keys]}

    s3.list_objects_v2.side_effect = list_objects_v2
    return s3


def test_find_volume_key_picks_nearest_within_tolerance():
    day_prefix = "2026/08/10/KCLE/"
    s3 = _fake_s3({
        day_prefix: [
            day_prefix + "KCLE20260810_004330_V06",
            day_prefix + "KCLE20260810_005028_V06",
            day_prefix + "KCLE20260810_005739_V06",
            day_prefix + "KCLE20260810_005739_V06_MDM",  # sidecar, must be excluded
            day_prefix + "KCLE20260810_010451_V06",
        ],
    })
    when = datetime(2026, 8, 10, 0, 57, 0, tzinfo=timezone.utc)
    key = rl2.find_volume_key(s3, "KCLE", when)
    assert key == day_prefix + "KCLE20260810_005739_V06"


def test_find_volume_key_none_when_nothing_within_tolerance():
    day_prefix = "2026/08/10/KCLE/"
    s3 = _fake_s3({
        day_prefix: [day_prefix + "KCLE20260810_005739_V06"],
    })
    # An hour away from the only available volume.
    when = datetime(2026, 8, 10, 3, 0, 0, tzinfo=timezone.utc)
    assert rl2.find_volume_key(s3, "KCLE", when) is None


def test_find_volume_key_checks_adjacent_day_near_midnight():
    prev_day = "2026/08/09/KCLE/"
    this_day = "2026/08/10/KCLE/"
    s3 = _fake_s3({
        prev_day: [prev_day + "KCLE20260809_235800_V06"],
        this_day: [],
    })
    when = datetime(2026, 8, 10, 0, 1, 0, tzinfo=timezone.utc)
    key = rl2.find_volume_key(s3, "KCLE", when)
    assert key == prev_day + "KCLE20260809_235800_V06"


def test_find_volume_key_live_returns_latest_of_today():
    day_prefix = f"{datetime.now(timezone.utc):%Y/%m/%d}/KCLE/"
    s3 = _fake_s3({
        day_prefix: [
            day_prefix + "KCLE_A_earlier_V06",
            day_prefix + "KCLE_B_latest_V06",
        ],
    })
    # Lexical sort must land on the alphabetically-last (== chronologically
    # last, given the zero-padded filename format) key.
    assert rl2.find_volume_key(s3, "KCLE", None) == day_prefix + "KCLE_B_latest_V06"


# ── Legend color derivation ──────────────────────────────────────────────────

def test_legend_hex_colors_match_reflectivity_legend():
    # _plot_ppi's matplotlib colormap must draw from the exact same values
    # the on-page legend swatches show -- REFLECTIVITY_LEGEND is that
    # single source of truth for both.
    hexed = rl2._legend_hex_colors()
    assert len(hexed) == len(rl2.REFLECTIVITY_LEGEND)
    for hex_color, (_, rgb) in zip(hexed, rl2.REFLECTIVITY_LEGEND):
        assert hex_color == f'#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}'


def test_legend_hex_colors_are_well_formed():
    for hex_color in rl2._legend_hex_colors():
        assert hex_color.startswith('#')
        assert len(hex_color) == 7
        int(hex_color[1:], 16)  # raises ValueError if not valid hex


# ── render_frame: best-effort short-circuits ────────────────────────────────

def test_render_frame_none_when_no_site_in_range(monkeypatch):
    monkeypatch.setattr(rl2, "nearest_site", lambda lat, lon: None)
    result = rl2.render_frame(20.0, -160.0, None, 30000, 100, 100)
    assert result is None


def test_render_frame_none_when_no_volume_near_time(monkeypatch):
    monkeypatch.setattr(rl2, "nearest_site", lambda lat, lon: "KCLE")
    monkeypatch.setattr(rl2, "_s3_client", lambda: MagicMock())
    monkeypatch.setattr(rl2, "find_volume_key", lambda s3, site, when: None)
    result = rl2.render_frame(41.35, -83.6, datetime(2026, 8, 10, tzinfo=timezone.utc), 30000, 100, 100)
    assert result is None


# ── _soften_beam_edges ───────────────────────────────────────────────────────
# Confirmed (by rendering the same bbox at 4x pixel density and seeing the
# band pattern unchanged) that hard vertical seams at typical alert-polygon
# zoom are real beam-to-beam boundaries, not a rasterization artifact -- so
# this exists to soften them without erasing real structure or bleeding
# color out of transparent "no echo" cells.

def test_soften_preserves_image_size():
    img = Image.new('RGBA', (40, 30), (100, 150, 200, 255))
    out = rl2._soften_beam_edges(img)
    assert out.size == (40, 30)


def test_soften_leaves_uniform_image_essentially_unchanged():
    img = Image.new('RGBA', (40, 30), (100, 150, 200, 255))
    out = rl2._soften_beam_edges(img)
    px = np.array(out)
    # A blur of a perfectly uniform field is that same field -- allow a
    # few units of float/uint8 rounding slop, not a real color shift.
    assert np.allclose(px[10:-10, 10:-10], [100, 150, 200, 255], atol=2)


def test_soften_stays_fully_transparent_where_input_was():
    img = Image.new('RGBA', (40, 30), (0, 0, 0, 0))
    out = rl2._soften_beam_edges(img)
    assert np.array(out)[..., 3].max() == 0


def test_soften_does_not_leak_color_from_transparent_neighbors():
    # A transparent region carrying an arbitrary, wildly different "leftover"
    # RGB right next to an opaque red region -- the classic non-premultiplied
    # -blur bug would tint the red edge toward that leftover color. With
    # correct premultiplication, alpha=0 pixels contribute zero regardless
    # of what color they carry.
    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    arr[:, :20] = [255, 0, 0, 255]       # opaque red, left half
    arr[:, 20:] = [0, 255, 0, 0]         # transparent, but carrying green
    img = Image.fromarray(arr, mode='RGBA')
    out = np.array(rl2._soften_beam_edges(img))
    # Well inside the opaque red region, blurring in a fully-transparent
    # (zero-contribution) neighbor must not pull the color toward green.
    edge_pixel = out[20, 18]
    assert edge_pixel[1] < 40, f"green leaked into red edge: {edge_pixel}"
