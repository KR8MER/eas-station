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

"""Guards against static/js/screen-editor.js's client-side LED_GLYPH_5x7
table drifting from scripts/dotmatrix_preview_font.py's server-side
FONT_5x7 -- the two are hand-duplicated (no shared build step), and a glyph
added to one and forgotten in the other renders correctly in the
server-rendered "pixel-accurate" preview modal while silently showing as
blank on the live editing canvas, or vice versa.
"""

import ast
import re
from pathlib import Path

from scripts.dotmatrix_preview_font import FONT_5x7

SCREEN_EDITOR_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "screen-editor.js"


def _load_js_glyph_table():
    src = SCREEN_EDITOR_JS.read_text(encoding="utf-8")
    match = re.search(r"const LED_GLYPH_5x7 = (\{.*?\n\s*\});", src, re.DOTALL)
    assert match, "LED_GLYPH_5x7 table not found in screen-editor.js"
    return ast.literal_eval(match.group(1))


def test_led_glyph_table_matches_server_font_keys():
    js_glyphs = _load_js_glyph_table()
    assert set(js_glyphs) == set(FONT_5x7), (
        "static/js/screen-editor.js's LED_GLYPH_5x7 and "
        "scripts/dotmatrix_preview_font.py's FONT_5x7 must define the same "
        "characters -- a character missing from one renders inconsistently "
        "between the live editing canvas and the server-rendered preview."
    )


def test_led_glyph_table_matches_server_font_shapes():
    js_glyphs = _load_js_glyph_table()
    for ch, rows in FONT_5x7.items():
        assert js_glyphs[ch] == list(rows), f"Glyph mismatch for {ch!r}"
