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

The originating-equipment badge (SAGE Digital 3644, NWS BMH, etc., from
app_utils.eas_demod.detect_endec_mode()) was only ever rendered on the
manual "Audio Decoder" upload page (templates/eas/alert_verification.html)
-- the same value is computed and stored for every live audio-received
alert too, but the live detail page only exposed it buried in a raw JSON
dump. The macro moved to templates/components/endec_badge.html so both
pages render it identically.
"""

from __future__ import annotations

import pathlib

import jinja2

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates"

BADGE_COMPONENT = TEMPLATES_DIR / "components" / "endec_badge.html"
DECODER_PAGE = TEMPLATES_DIR / "eas" / "alert_verification.html"
RECEIVED_DETAIL_PAGE = TEMPLATES_DIR / "audio_received_detail.html"


def _render_badge(mode) -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.from_string(
        "{% from 'components/endec_badge.html' import endec_badge %}"
        "{{ endec_badge(mode) }}"
    )
    return template.render(mode=mode).strip()


def test_every_known_mode_renders_its_own_label_and_color():
    expectations = {
        "SAGE_DIGITAL_3644": ("primary", "SAGE Digital 3644"),
        "SAGE_ANALOG_1822": ("primary", "SAGE Analog 1822"),
        "NWS": ("info", "NWS Legacy / EAS.js"),
        "NWS_CRS": ("info", "NWS CRS"),
        "NWS_BMH": ("info", "NWS BMH"),
        "TRILITHIC": ("secondary", "Trilithic EASyPLUS"),
        "EAS_STATION": ("success", "KR8MER EAS Station"),
        "DEFAULT": ("secondary", "DASDEC"),
    }
    for mode, (color, label_fragment) in expectations.items():
        html = _render_badge(mode)
        assert f"bg-{color}" in html, f"{mode}: expected bg-{color} in {html!r}"
        assert label_fragment in html, f"{mode}: expected {label_fragment!r} in {html!r}"


def test_unknown_mode_falls_back_gracefully():
    assert "Unknown" in _render_badge("UNKNOWN")


def test_a_missing_endec_mode_does_not_crash_the_macro():
    """Older stored alerts (or a decode that never voted) carry no key at
    all -- endec_mode is None, not the string 'UNKNOWN'."""
    html = _render_badge(None)
    assert "Unknown" in html


def test_an_unrecognized_mode_string_is_shown_verbatim_not_swallowed():
    """A future ENDEC_MODE_* constant this macro hasn't been taught yet
    must still be visible, not silently rendered as 'Unknown'."""
    html = _render_badge("SOME_FUTURE_MODE")
    assert "SOME_FUTURE_MODE" in html


def test_both_consumer_pages_import_the_shared_component():
    """Regression: the badge used to be a macro copy-pasted inline in the
    decoder page only. Both pages must share one definition so a label
    change can't drift between them."""
    for page in (DECODER_PAGE, RECEIVED_DETAIL_PAGE):
        text = page.read_text(encoding="utf-8")
        assert "from 'components/endec_badge.html' import endec_badge" in text, (
            f"{page.name} must import the shared endec_badge macro"
        )
        # No leftover inline re-definition after the extraction.
        assert "{% macro endec_badge(" not in text, (
            f"{page.name} should not define its own copy of endec_badge"
        )


def test_received_detail_page_actually_calls_the_badge_with_stored_data():
    """Regression: the value was already stored in full_alert_data for
    every live alert; only the labeled badge was missing from this page."""
    text = RECEIVED_DETAIL_PAGE.read_text(encoding="utf-8")
    assert "endec_badge(" in text
    assert "full_alert_data" in text
    assert "endec_mode" in text
