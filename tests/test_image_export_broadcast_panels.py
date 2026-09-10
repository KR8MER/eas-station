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


def test_expires_block_shrinks_long_timestamp_to_fit_column():
    """A long absolute stamp ("Sep 9 . 8:48 AM EDT") measures wider than the
    narrow column at the full 30px title size -- and that column sits only
    a handful of pixels from the canvas's right edge, so any overflow gets
    hard-clipped by the image boundary rather than just looking cramped.
    The drawn value must never be wider than the column it's given."""
    from datetime import datetime, timedelta, timezone

    iw = 284
    img, draw = _canvas(w=iw + 66)  # extra margin to catch overflow past iw
    fonts = image_export._load_fonts()
    alert = _FakeAlert()
    # _short_local_dt only includes the date when expires falls on a
    # different calendar day than sent -- that's what makes the string
    # long enough to reproduce the overflow ("Sep 9 . 8:48 AM EDT" vs.
    # same-day's bare "8:48 AM EDT").
    alert.sent = datetime.now(timezone.utc) - timedelta(days=1)
    alert.expires = alert.sent + timedelta(days=1, hours=2, minutes=29)

    time_str = image_export._short_local_dt(alert.expires, ref=alert.sent)
    # Sanity check this fixture actually reproduces the overflow the fix
    # addresses: at the original fixed 30px size it must not fit.
    assert image_export._tw(fonts["title"], time_str) > iw

    image_export._draw_expires_block(draw, fonts, 0, 0, iw, 400, alert)

    # No non-background pixel painted past the column's own width.
    assert not _region_has_nonbg_pixel(img, (iw, 0, iw + 66, 400))


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


def test_narrow_column_shows_headline_for_non_severe_events_too():
    """A non-severe-weather CAP event (e.g. a 911/telephone outage notice)
    carries no damage tier, tornado tag, or wind/hail stats -- every
    weather-specific narrow-column drawer no-ops. The column must still
    show the same generic HEADLINE / DESCRIPTION text the wide-column
    layout always shows, not just a bare EXPIRES time."""
    from datetime import datetime, timedelta, timezone

    alert = _FakeAlert()
    alert.event = "911 Landline Issue"
    alert.sent = datetime.now(timezone.utc)
    alert.expires = alert.sent + timedelta(hours=2, minutes=29)
    alert.headline = "911 emergency telephone service is down in Test County"
    alert.description = (
        "The 911 emergency landline system serving Test County is out of "
        "service. Residents needing emergency assistance should use a "
        "mobile phone to dial 911."
    )
    alert.instruction = ""

    png = image_export.generate_alert_image(
        alert, {}, {}, {"county_name": "Test County, OH"},
        aspect_ratio="landscape",
    )
    img = Image.open(io.BytesIO(png)).convert("RGB")

    ix, iy, iw, ih = image_export._LAYOUT_LANDSCAPE.info_rect
    bg = image_export._BG
    # EXPIRES alone only fills a small strip near the top of the column;
    # the fallback headline/description must paint well below it too.
    lower_two_thirds = img.crop((ix, iy + ih // 3, ix + iw, iy + ih))
    assert any(px != bg for px in lower_two_thirds.getdata())
    img = Image.open(io.BytesIO(png))
    assert img.size == (1200, 630)


def test_narrow_column_shows_full_content_even_with_threat_data(monkeypatch):
    """The actual fix: HEADLINE, AFFECTED AREAS, DESCRIPTION and COVERAGE
    used to be entirely omitted from the narrow (landscape) column whenever
    any threat-specific content rendered (damage tier, tornado tag, or a
    wind/hail stat box) -- exactly the common case for severe products. All
    layouts must carry the same information regardless of width, so these
    must now render unconditionally, the same as the wide-column layout."""
    calls = []
    for name in ("_draw_nws_headline", "_draw_areas", "_draw_description", "_draw_coverage"):
        monkeypatch.setattr(
            image_export.render, name,
            lambda *a, _n=name, **k: calls.append(_n) or (a[4] if len(a) > 4 else 0),
        )

    alert = _FakeAlert()
    ipaws_data = {
        "threat_data": {
            "wind": {"threat": "DESTRUCTIVE", "gust": "80", "gust_unit": "MPH",
                     "display": "Destructive!", "level": "possible"},
        },
    }

    image_export.generate_alert_image(
        alert, {}, ipaws_data, {"county_name": "Test County, OH"},
        aspect_ratio="landscape",
    )

    assert "_draw_nws_headline" in calls
    assert "_draw_areas" in calls
    assert "_draw_description" in calls
    assert "_draw_coverage" in calls


def test_narrow_column_draws_instruction_before_headline(monkeypatch):
    """Regression for a bug caught by rendering an actual sample card (not
    caught by the test above, which only checks each drawer was called, not
    in what order): on a content-dense product -- damage tier + EXPIRES +
    two hazard stat boxes + a storm-motion line + a long headline -- the
    narrow column's fixed ~482px height ran out before ever reaching
    INSTRUCTION, so "move to an interior room" silently vanished off the
    bottom while the less safety-critical HEADLINE text (which just repeats
    context the event banner above already shows) survived. INSTRUCTION
    must be drawn before HEADLINE/AREAS/DESCRIPTION so space pressure can
    only clip the narrative sections, never the one thing on this card that
    tells someone what to physically do."""
    calls = []
    for name in ("_draw_instruction", "_draw_nws_headline", "_draw_areas", "_draw_description"):
        monkeypatch.setattr(
            image_export.render, name,
            lambda *a, _n=name, **k: calls.append(_n) or (a[4] if len(a) > 4 else 0),
        )

    alert = _FakeAlert()
    ipaws_data = {
        "threat_data": {
            "wind": {"threat": "DESTRUCTIVE", "gust": "80", "gust_unit": "MPH",
                     "display": "Destructive!", "level": "possible"},
        },
    }

    image_export.generate_alert_image(
        alert, {}, ipaws_data, {"county_name": "Test County, OH"},
        aspect_ratio="landscape",
    )

    assert calls[0] == "_draw_instruction"


def test_narrow_column_instruction_survives_a_content_dense_card():
    """End-to-end version of the ordering test above: render a real card
    with the exact dense combination that triggered the bug (damage tier,
    wind+hail stats, storm motion, a long NWS headline) and confirm the
    WHAT TO DO band actually paints pixels, not just that the drawer was
    called in the right order."""
    from datetime import datetime, timedelta, timezone

    alert = _FakeAlert()
    alert.sent = datetime.now(timezone.utc)
    alert.expires = alert.sent + timedelta(minutes=45)
    alert.headline = (
        "The National Weather Service in Wilmington has issued a Severe "
        "Thunderstorm Warning for southern Test County"
    )
    ipaws_data = {
        "nws_headline": alert.headline,
        "threat_data": {
            "wind": {"threat": "DESTRUCTIVE", "gust": "80", "gust_unit": "MPH",
                     "display": "Destructive!", "level": "possible"},
            "hail": {"threat": "CONSIDERABLE", "size": "1.75",
                     "descriptor": "Golf Ball", "display": "Considerable",
                     "level": "possible"},
        },
        "storm_motion": {"compass_toward": "SE", "speed_mph": "45", "toward_deg": 135},
    }

    png = image_export.generate_alert_image(
        alert, {}, ipaws_data, {"county_name": "Test County, OH"},
        aspect_ratio="landscape",
    )
    img = Image.open(io.BytesIO(png)).convert("RGB")

    # _INSTR_ACCENT (warning-yellow) is _draw_instruction's distinctive
    # accent-bar colour (panels_text.py) -- nothing else on this card uses
    # it, so its presence anywhere in the narrow column is an unambiguous
    # signal the instruction band actually painted, not just that *some*
    # non-background pixel landed there.
    ix, iy, iw, ih = image_export._LAYOUT_LANDSCAPE.info_rect
    column = img.crop((ix, iy, ix + iw, iy + ih))
    assert image_export._INSTR_ACCENT in {px for px in column.getdata()}
