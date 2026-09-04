"""Tests for the broadcast-style narrow-column info-panel drawers added to
app_utils/image_export/panels.py (_draw_damage_callout, _draw_expires_block,
_draw_hazard_stat_boxes, _draw_storm_motion_line) and the landscape layout
change that activates them.

These sit alongside test_image_export_themes.py rather than in it (already
1300+ lines) -- same loading pattern (import the package directly via
importlib so this doesn't pay for the full app_utils import), same
before -- but each new function needs its own assertion about what it
paints, so it's given its own file.

The overriding concerns:

* The landscape layout is genuinely map-dominant now (~75% width), and the
  info column is narrow enough to trip render.py's INFO_NARROW_MAX_W
  branch, so generate_alert_image() actually exercises the new drawers by
  default rather than only through direct unit calls.
* Each new drawer no-ops (returns iy unchanged, paints nothing) when its
  data is absent, matching every existing drawer's convention -- a missing
  hazard tag must never leave a broken/empty box on the card.
* _draw_damage_callout only fires for the two elevated NWS damage tiers
  (Considerable/Destructive), not for a plain Possible/Radar/Observed tag
  -- and reads the raw `threat` string rather than the coarser `level`
  bucket, which collapses those tiers together (see display_data.py's
  _threat_level()).
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    pytest.skip("Pillow is required for image_export tests", allow_module_level=True)


_PKG_DIR = Path(__file__).resolve().parent.parent / "app_utils" / "image_export"
_spec = importlib.util.spec_from_file_location(
    "image_export_broadcast_panels_under_test",
    _PKG_DIR / "__init__.py",
    submodule_search_locations=[str(_PKG_DIR)],
)
assert _spec is not None and _spec.loader is not None
image_export = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = image_export
_spec.loader.exec_module(image_export)


class _FakeAlert:
    """Minimal stand-in for CAPAlert with just the attributes the renderer touches."""
    id = 0
    event = "Severe Thunderstorm Warning"
    severity = "Severe"
    urgency = "Immediate"
    certainty = "Observed"
    status = "Actual"
    sent = None
    expires = None
    headline = "TEST HEADLINE"
    description = "Test description."
    instruction = "Move indoors and away from windows."
    area_desc = "Test Area"


def _canvas(w=284, h=400):
    img = Image.new("RGB", (w, h), image_export._BG)
    return img, ImageDraw.Draw(img)


def _region_has_nonbg_pixel(img: Image.Image, box) -> bool:
    x0, y0, x1, y1 = box
    bg = image_export._BG
    region = img.crop((x0, y0, x1, y1))
    return any(px != bg for px in region.getdata())


# ── Layout: the landscape preset is genuinely map-dominant now ─────────────

def test_landscape_info_panel_is_narrow():
    layout = image_export._LAYOUT_LANDSCAPE
    map_w = layout.map_rect[2]
    info_w = layout.info_rect[2]
    assert map_w / layout.width >= 0.7, "map should dominate the canvas"
    assert info_w < image_export.INFO_NARROW_MAX_W, (
        "info column must be narrow enough to trip render.py's "
        "narrow-column drawer branch"
    )


# ── _draw_damage_callout ─────────────────────────────────────────────────────

@pytest.mark.parametrize("threat_str,expect_text", [
    ("DESTRUCTIVE", "DESTRUCTIVE DAMAGE EXPECTED"),
    ("CONSIDERABLE", "CONSIDERABLE DAMAGE THREAT"),
])
def test_damage_callout_draws_for_elevated_tiers(threat_str, expect_text):
    img, draw = _canvas()
    fonts = image_export._load_fonts()
    ipaws_data = {"threat_data": {"wind": {"threat": threat_str, "level": "possible"}}}

    new_iy = image_export._draw_damage_callout(draw, fonts, 0, 0, 284, 400, ipaws_data)

    assert new_iy > 0
    assert _region_has_nonbg_pixel(img, (0, 0, 284, new_iy))


@pytest.mark.parametrize("ipaws_data", [
    None,
    {},
    {"threat_data": {}},
    {"threat_data": {"wind": {"threat": "POSSIBLE", "level": "possible"}}},
    {"threat_data": {"hail": {"threat": "RADAR INDICATED", "level": "radar"}}},
])
def test_damage_callout_noop_without_elevated_tier(ipaws_data):
    img, draw = _canvas()
    fonts = image_export._load_fonts()

    new_iy = image_export._draw_damage_callout(draw, fonts, 0, 0, 284, 400, ipaws_data)

    assert new_iy == 0
    assert not _region_has_nonbg_pixel(img, (0, 0, 284, 60))


def test_damage_callout_prefers_destructive_over_considerable():
    """Wind Considerable + hail Destructive -> the worse of the two wins."""
    img, draw = _canvas()
    fonts = image_export._load_fonts()
    ipaws_data = {
        "threat_data": {
            "wind": {"threat": "CONSIDERABLE", "level": "possible"},
            "hail": {"threat": "DESTRUCTIVE", "level": "possible"},
        }
    }

    tier = image_export.panels._damage_callout_tier(ipaws_data["threat_data"])
    assert tier == "destructive"


# ── _draw_expires_block ──────────────────────────────────────────────────────

def test_expires_block_draws_when_expires_set():
    from datetime import datetime, timedelta, timezone

    img, draw = _canvas()
    fonts = image_export._load_fonts()
    alert = _FakeAlert()
    alert.sent = datetime.now(timezone.utc)
    alert.expires = alert.sent + timedelta(minutes=45)

    new_iy = image_export._draw_expires_block(draw, fonts, 0, 0, 284, 400, alert)

    assert new_iy > 0
    assert _region_has_nonbg_pixel(img, (0, 0, 284, new_iy))


def test_expires_block_noop_without_expires():
    img, draw = _canvas()
    fonts = image_export._load_fonts()
    alert = _FakeAlert()
    alert.expires = None

    new_iy = image_export._draw_expires_block(draw, fonts, 0, 0, 284, 400, alert)

    assert new_iy == 0
    assert not _region_has_nonbg_pixel(img, (0, 0, 284, 60))


# ── _draw_hazard_stat_boxes ──────────────────────────────────────────────────

def test_hazard_stat_boxes_draw_one_box_per_present_hazard():
    img, draw = _canvas()
    fonts = image_export._load_fonts()
    ipaws_data = {
        "threat_data": {
            "wind": {"gust": "80", "gust_unit": "MPH", "level": "possible"},
            "hail": {"size": "1.75", "descriptor": "Golf Ball", "level": "possible"},
        }
    }

    new_iy = image_export._draw_hazard_stat_boxes(draw, fonts, 0, 0, 284, 400, ipaws_data)

    # Two boxes stacked vertically -> some content in both the top and
    # bottom halves of the drawn region, not just clustered at the top.
    assert _region_has_nonbg_pixel(img, (0, 0, 284, 88))
    assert _region_has_nonbg_pixel(img, (0, 94, 284, 182))
    assert new_iy > 176


def test_hazard_stat_boxes_noop_without_threat_data():
    img, draw = _canvas()
    fonts = image_export._load_fonts()

    new_iy = image_export._draw_hazard_stat_boxes(draw, fonts, 0, 0, 284, 400, None)

    assert new_iy == 0
    assert not _region_has_nonbg_pixel(img, (0, 0, 284, 200))


def test_hazard_stat_boxes_skip_hazard_missing_its_value():
    """A wind threat tag with no parsed gust value must not draw an empty box."""
    img, draw = _canvas()
    fonts = image_export._load_fonts()
    ipaws_data = {"threat_data": {"wind": {"gust": "", "level": "possible"}}}

    new_iy = image_export._draw_hazard_stat_boxes(draw, fonts, 0, 0, 284, 400, ipaws_data)

    assert new_iy == 0


# ── _draw_storm_motion_line ──────────────────────────────────────────────────

def test_storm_motion_line_draws_when_present():
    img, draw = _canvas()
    fonts = image_export._load_fonts()
    ipaws_data = {"storm_motion": {"compass_toward": "SE", "speed_mph": "47"}}

    new_iy = image_export._draw_storm_motion_line(draw, fonts, 0, 0, 284, 400, ipaws_data)

    assert new_iy > 0
    assert _region_has_nonbg_pixel(img, (0, 0, 284, new_iy))


@pytest.mark.parametrize("ipaws_data", [
    None,
    {},
    {"storm_motion": {}},
    {"storm_motion": {"compass_toward": "SE"}},  # missing speed
    {"storm_motion": {"speed_mph": "47"}},  # missing direction
])
def test_storm_motion_line_noop_without_full_data(ipaws_data):
    img, draw = _canvas()
    fonts = image_export._load_fonts()

    new_iy = image_export._draw_storm_motion_line(draw, fonts, 0, 0, 284, 400, ipaws_data)

    assert new_iy == 0
    assert not _region_has_nonbg_pixel(img, (0, 0, 284, 30))


# ── Section icon key rename (ACTION -> WHAT TO DO) ──────────────────────────

def test_action_section_renamed_to_what_to_do():
    assert "WHAT TO DO" in image_export.icons._SECTION_ICON_FN
    assert "ACTION" not in image_export.icons._SECTION_ICON_FN


# ── End-to-end: generate_alert_image() actually exercises the new path ─────

def test_generate_alert_image_landscape_with_threats_renders_narrow_column():
    from datetime import datetime, timedelta, timezone

    alert = _FakeAlert()
    alert.sent = datetime.now(timezone.utc)
    alert.expires = alert.sent + timedelta(minutes=45)
    ipaws_data = {
        "threat_data": {
            "wind": {"threat": "DESTRUCTIVE", "gust": "80", "gust_unit": "MPH",
                     "display": "Destructive!", "level": "possible"},
            "hail": {"threat": "CONSIDERABLE", "size": "1.75",
                     "descriptor": "Golf Ball", "display": "Considerable",
                     "level": "possible"},
        },
        "storm_motion": {"compass_toward": "SE", "speed_mph": "47", "toward_deg": 135},
    }

    png = image_export.generate_alert_image(
        alert, {}, ipaws_data, {"county_name": "Test County, OH"},
        aspect_ratio="landscape",
    )

    assert png.startswith(b"\x89PNG")
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)

    ix, iy, iw, ih = image_export._LAYOUT_LANDSCAPE.info_rect
    # Something painted across the whole narrow column, not just a sliver
    # at the very top -- the damage callout + EXPIRES + two stat boxes +
    # motion line + WHAT TO DO block should fill well past the halfway
    # point of the available height.
    bg = image_export._BG
    lower_half = img.convert("RGB").crop((ix, iy + ih // 2, ix + iw, iy + ih))
    assert any(px != bg for px in lower_half.getdata())


def test_generate_alert_image_landscape_without_threats_still_renders():
    """No threat_data / storm_motion at all -- every new drawer no-ops, and
    the card must still be a valid, non-empty PNG (mirrors a non-severe or
    non-tagged weather product)."""
    alert = _FakeAlert()
    png = image_export.generate_alert_image(
        alert, {}, None, {"county_name": "Test County, OH"},
        aspect_ratio="landscape",
    )
    assert png.startswith(b"\x89PNG")
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)
