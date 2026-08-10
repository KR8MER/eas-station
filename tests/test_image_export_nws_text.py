"""Tests for the NWS description parser used by the share-card renderer.

These lock down the behaviour that turns a CAP ``description`` back into
the tagged outline NWS wrote it as:

* tagged bullets (``* WHAT...`` and the asterisk-free ``HAZARD...`` form)
  are recovered with their labels normalised;
* the untagged lede that opens severe warnings survives;
* segments the card already covers elsewhere (WHERE, WHEN, the
  preparedness block) are dropped from the share selection;
* prose that merely happens to be shouted is *not* mistaken for an
  outline, so it still falls back to paragraph rendering;
* ``areaDesc`` lists factor their repeated state code out.

The parser is a leaf module with no package dependencies, so it is loaded
directly rather than paying for the full ``app_utils`` import.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_PKG_DIR = Path(__file__).resolve().parent.parent / "app_utils" / "image_export"
_spec = importlib.util.spec_from_file_location(
    "nws_text_under_test", _PKG_DIR / "nws_text.py"
)
assert _spec is not None and _spec.loader is not None
nws_text = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = nws_text
_spec.loader.exec_module(nws_text)


# A real NWS flood advisory, verbatim apart from trimming the city list.
FLOOD_ADVISORY = """* WHAT...Flooding caused by excessive rainfall is expected.

* WHERE...A portion of northwest Ohio, including the following counties, \
Allen OH, Defiance, Henry, Paulding and Putnam.

* WHEN...Until 1245 PM EDT.

* IMPACTS...Minor flooding in low-lying and poor drainage areas.

* ADDITIONAL DETAILS...
- At 935 AM EDT, Doppler radar indicated heavy rain due to thunderstorms.
- Between 1 and 2.5 inches of rain have fallen.
- http://www.weather.gov/safety/flood"""

# A severe thunderstorm warning: asterisk-free tags, and a lede ahead of
# the first tag that carries the storm's location and motion.
SVR_WARNING = """At 900 PM EDT, a severe thunderstorm was located near Lima, \
moving east at 40 mph.

HAZARD...60 mph wind gusts and quarter size hail.

SOURCE...Radar indicated.

IMPACT...Hail damage to vehicles is expected.

PRECAUTIONARY/PREPAREDNESS ACTIONS...
For your protection move to an interior room on the lowest floor."""


def _labels(segments):
    return [s.label for s in segments]


# ── Tagged-outline recovery ─────────────────────────────────────────────────
def test_parses_asterisk_bullet_outline():
    segments = nws_text.parse_nws_segments(FLOOD_ADVISORY)
    assert _labels(segments) == ["WHAT", "WHERE", "WHEN", "IMPACTS", "DETAILS"]
    assert segments[0].body == "Flooding caused by excessive rainfall is expected."


def test_parses_asterisk_free_tags_and_keeps_lede():
    segments = nws_text.parse_nws_segments(SVR_WARNING)
    # An empty label marks the untagged lede.
    assert segments[0].label == ""
    assert segments[0].body.startswith("At 900 PM EDT, a severe thunderstorm")
    assert _labels(segments)[1:] == [
        "HAZARD", "SOURCE", "IMPACTS", "PRECAUTIONARY/PREPAREDNESS ACTIONS",
    ]


def test_short_fragment_before_first_tag_is_not_a_lede():
    segments = nws_text.parse_nws_segments("Ohio.\n\n* WHAT...Rain.")
    assert _labels(segments) == ["WHAT"]


def test_sub_bullets_join_without_dash_glyphs():
    details = nws_text.parse_nws_segments(FLOOD_ADVISORY)[-1]
    assert details.label == "DETAILS"
    assert "- " not in details.body
    assert details.body.startswith("At 935 AM EDT, Doppler radar")
    assert details.body.endswith("inches of rain have fallen.")


def test_urls_are_stripped_from_bodies():
    body = nws_text.parse_nws_segments(FLOOD_ADVISORY)[-1].body
    assert "http" not in body
    assert "weather.gov" not in body


def test_collapsed_feed_without_newlines_still_parses():
    """Some feeds deliver the description with newlines already flattened."""
    text = ("* WHAT...Damaging winds. * WHEN...Until 6 PM. "
            "* IMPACTS...Downed trees.")
    assert _labels(nws_text.parse_nws_segments(text)) == [
        "WHAT", "WHEN", "IMPACTS",
    ]


def test_numeric_ranges_survive_bullet_cleanup():
    """The " - " bullet cleanup must not eat "1 - 2.5 inches"."""
    seg = nws_text.parse_nws_segments(
        "* IMPACTS...Snow accumulations of 1 - 2.5 inches expected.")[0]
    assert seg.body == "Snow accumulations of 1 - 2.5 inches expected."


# ── False positives: prose must fall back to paragraph rendering ────────────
@pytest.mark.parametrize("text", [
    "A strong storm will move through the area. Expect heavy rain.",
    # Legacy shouted product — ALL-CAPS with "..." separators, but no tags.
    "AT 935 AM EDT...DOPPLER RADAR INDICATED HEAVY RAIN OVER THE AREA. "
    "THE NATIONAL WEATHER SERVICE HAS ISSUED A FLOOD ADVISORY...",
    "",
])
def test_untagged_text_yields_no_segments(text):
    assert nws_text.parse_nws_segments(text) == []


# ── Share-card selection ────────────────────────────────────────────────────
def test_share_selection_drops_sections_the_card_repeats():
    segments = nws_text.select_share_segments(
        FLOOD_ADVISORY, drop_where=True, drop_when=True)
    assert _labels(segments) == ["WHAT", "IMPACTS", "DETAILS"]


def test_share_selection_keeps_where_and_when_when_not_shown_elsewhere():
    segments = nws_text.select_share_segments(FLOOD_ADVISORY)
    assert _labels(segments) == ["WHAT", "WHERE", "WHEN", "IMPACTS", "DETAILS"]


def test_share_selection_always_drops_preparedness_block():
    """That block is the CAP instruction field, drawn under ACTION already."""
    segments = nws_text.select_share_segments(SVR_WARNING)
    assert "PRECAUTIONARY/PREPAREDNESS ACTIONS" not in _labels(segments)
    assert _labels(segments) == ["", "HAZARD", "SOURCE", "IMPACTS"]


def test_share_selection_of_untagged_text_is_empty():
    assert nws_text.select_share_segments("Plain prose about a storm.") == []


# ── Affected-area compaction ────────────────────────────────────────────────
def test_repeated_state_code_is_factored_out():
    assert nws_text.compact_area_desc(
        "Allen, OH; Defiance, OH; Henry, OH; Paulding, OH; Putnam, OH"
    ) == "Allen, Defiance, Henry, Paulding, Putnam (OH)"


def test_multiple_states_group_separately_in_first_seen_order():
    assert nws_text.compact_area_desc(
        "Allen, OH; Adams, IN; Defiance, OH"
    ) == "Allen, Defiance (OH); Adams (IN)"


@pytest.mark.parametrize("area_desc,expected", [
    # Zone / marine products carry no state codes — leave them alone.
    ("Coastal Volusia; Northern Brevard", "Coastal Volusia; Northern Brevard"),
    # A single entry has nothing to factor out.
    ("Putnam, OH", "Putnam, OH"),
    ("", ""),
])
def test_area_desc_passes_through_when_nothing_to_compact(area_desc, expected):
    assert nws_text.compact_area_desc(area_desc) == expected


def test_area_compaction_never_loses_a_county():
    area_desc = "; ".join(f"County{i}, OH" for i in range(12))
    out = nws_text.compact_area_desc(area_desc)
    for i in range(12):
        assert f"County{i}" in out
