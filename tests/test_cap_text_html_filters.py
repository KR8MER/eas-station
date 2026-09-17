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

"""Regression tests for the nl2br/cap_paragraphs Jinja filters.

Bug (found via a user-submitted Alert Details PDF, 2026-09-17): the alert
description/instruction on the Alert Details page rendered literal,
visible text like ``</p><p class="mt-2 mb-0">`` and ``<br>`` instead of
real paragraph breaks, for a perfectly clean CAP alert whose stored
``description`` column contains plain text with real ``\\n\\n`` breaks
(verified directly against the database -- no HTML in the source data).

Root cause: the templates spelled the transform out inline as
``{{ text | e | replace('\\n\\n', '</p><p ...>') | replace(...) | safe }}``.
``| e`` produces a Jinja/MarkupSafe ``Markup`` object. Jinja's ``|replace``
filter, given an already-``Markup`` value, routes to ``Markup.replace()``
-- which HTML-escapes its *own* replacement argument too, as part of the
invariant that keeps a ``Markup`` value safe to pass around. So the
``<p>``/``<br>`` tags the template meant to insert came out
double-escaped: syntactically present in the string, but as the literal
text ``&lt;p ...&gt;`` rather than a real tag -- exactly what a browser
renders as visible ``<p ...>`` text once marked ``| safe`` at the end.

The fix moves the whole escape-then-substitute transform into Python
(``webapp/template_helpers.py::_nl2br_filter`` /
``_cap_paragraphs_filter``), building the finished HTML as a plain
``str`` (never touching ``Markup.replace()``) and wrapping the result in
``Markup`` exactly once, at the very end.
"""

import re
from pathlib import Path

from webapp.template_helpers import _cap_paragraphs_filter, _nl2br_filter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Matches the exact bug shape: `| e` (or `|e`) followed, anywhere later in
# the same expression, by a `replace(` filter call. A legitimate `replace`
# filter used on plain (non-escaped) text elsewhere in a template is fine;
# it's specifically *escape-then-replace* that triggers Markup.replace().
DANGEROUS_CHAIN = re.compile(r"\|\s*e\s*\|(?:[^{}]*\|)?\s*replace\s*\(")


class TestNl2brFilter:
    def test_escapes_and_converts_newlines(self):
        result = _nl2br_filter("line one\nline two")
        assert str(result) == "line one<br>\nline two"

    def test_escapes_literal_html_in_source_text(self):
        # A CAP feed that (deliberately or not) embeds a real tag in its
        # "plain text" must not have that tag rendered as live markup.
        result = _nl2br_filter("click <script>alert(1)</script> here")
        assert "<script>" not in str(result)
        assert "&lt;script&gt;" in str(result)

    def test_inserted_br_is_real_markup_not_escaped_text(self):
        result = _nl2br_filter("a\nb")
        # This is the exact failure mode the bug produced: the <br> this
        # filter inserts must be a real tag, not the literal text
        # "&lt;br&gt;" a naive escape-then-replace chain would leave behind.
        assert "&lt;br&gt;" not in str(result)
        assert "<br>" in str(result)

    def test_empty_input_returns_empty_markup(self):
        assert str(_nl2br_filter(None)) == ""
        assert str(_nl2br_filter("")) == ""


class TestCapParagraphsFilter:
    def test_double_newline_becomes_real_paragraph_break(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = str(_cap_paragraphs_filter(text))
        assert '</p><p class="mt-2 mb-0">' in result
        # The literal, human-readable failure mode from the bug report.
        assert "&lt;/p&gt;&lt;p" not in result

    def test_bullet_line_gets_br(self):
        text = "Details...\n- item one\n- item two"
        result = str(_cap_paragraphs_filter(text))
        assert "<br>- item one" in result
        assert "&lt;br&gt;" not in result

    def test_reproduces_and_fixes_the_reported_flood_warning_text(self):
        """The actual description text from the CAP alert in the bug
        report (Database ID #1108, a Van Wert County, OH Flood Warning),
        confirmed clean plain text via direct database query."""
        text = (
            "Wabash River at Wabash affecting Cass IN, Miami and Wabash "
            "Counties.\n\nSaint Marys River near Decatur affecting Adams, "
            "Allen IN and Van Wert Counties."
        )
        result = str(_cap_paragraphs_filter(text))
        assert "</p><p" in result
        assert "&lt;" not in result, (
            "No escaped-tag artifacts should survive -- this is exactly "
            "what a user would see as literal '</p><p class=...>' text "
            "on the Alert Details page before this fix."
        )

    def test_single_newline_collapses_to_space(self):
        result = str(_cap_paragraphs_filter("wrapped\nline"))
        assert "wrapped line" in result

    def test_escapes_literal_html_in_source_text(self):
        result = _cap_paragraphs_filter("<img src=x onerror=alert(1)>")
        assert "<img" not in str(result)
        assert "&lt;img" in str(result)

    def test_empty_input_returns_empty_markup(self):
        assert str(_cap_paragraphs_filter(None)) == ""
        assert str(_cap_paragraphs_filter("")) == ""


class TestNoDangerousEscapeReplaceChainInTemplates:
    """Structural guard: `| e | ... | replace(...)` must never reappear in
    a template. It's the exact shape that caused the bug -- Jinja routes
    `|replace` on an already-`|e`-escaped value through
    ``Markup.replace()``, which re-escapes its own replacement argument.
    Use the ``nl2br``/``cap_paragraphs`` filters (or a new one following
    the same pattern) instead of spelling this out inline.
    """

    def test_no_template_chains_escape_then_replace(self):
        offenders = []
        jinja_comment = re.compile(r"\{#.*?#\}", re.DOTALL)
        for path in TEMPLATES_DIR.rglob("*.html"):
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
            # Strip Jinja comments first: this file's own explanatory
            # comments quote the exact bad pattern as documentation, which
            # would otherwise false-positive against the live code check.
            text = jinja_comment.sub("", raw_text)
            for match in DANGEROUS_CHAIN.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{line_no}")

        assert not offenders, (
            "Found `| e | ... replace(...)` chains -- these render their "
            "own replacement HTML as escaped, visible text instead of "
            "real markup (Jinja's |replace filter routes to "
            "Markup.replace(), which escapes its replacement argument). "
            "Use the `nl2br` or `cap_paragraphs` template filter instead "
            "(webapp/template_helpers.py):\n"
            + "\n".join(f"  {o}" for o in offenders)
        )
