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

"""The two live-monitoring pages must present the same chrome.

System Health and the GNSS & Time dashboard show the same *kind* of thing —
a header with live status pills, a heartbeat dot, and a strip of
severity-tinted metric tiles — but each page had grown its own private copy
under `health-*` and `gps-*` prefixes. The copies drifted: different surface
tokens, two different greens for "OK", different idle colours for the
heartbeat dot, and one page hand-rolled its header instead of using the
shared component every other page uses.

These tests pin the shared chrome so the two pages cannot drift apart again.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[1]
STYLES_CSS = REPO_ROOT / "static" / "css" / "styles.css"

MONITORING_PAGES = {
    "system_health": REPO_ROOT / "templates" / "system_health.html",
    "gps_dashboard": REPO_ROOT / "templates" / "admin" / "gps_dashboard.html",
}

# Class names that were page-private before the chrome was unified. None of
# them may come back: each one is a copy of something now in styles.css.
RETIRED_CLASSES = [
    "health-status-strip",
    "health-status-tile",
    "health-pill",
    "health-live-dot",
    "health-dash-pills",
    "gps-status-strip",
    "gps-status-tile",
    "gps-pill",
    "gps-live-dot",
    "gps-dash-header",
]


def _page_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name,path", sorted(MONITORING_PAGES.items()))
class TestSharedHeaderComponent:
    """Both pages must use the canonical page-header component."""

    def test_includes_the_shared_page_header(self, name, path):
        source = _page_source(path)
        assert "components/page_header.html" in source, (
            f"{name} does not include the shared page header component. "
            "AGENTS.md requires every page to use it rather than hand-rolling "
            "a header, which is what made these two pages look unrelated."
        )

    def test_sets_the_header_component_variables(self, name, path):
        source = _page_source(path)
        for variable in ("header_icon", "header_title", "header_actions"):
            assert re.search(rf"{{%\s*set\s+{variable}\b", source), (
                f"{name} includes the header component without setting "
                f"{variable}."
            )

    def test_does_not_hand_roll_a_page_header(self, name, path):
        source = _page_source(path)
        assert not re.search(r'<div\s+class="[^"]*\bpage-header\b', source), (
            f"{name} hand-rolls a .page-header div. Use the component."
        )


@pytest.mark.parametrize("name,path", sorted(MONITORING_PAGES.items()))
class TestSharedStatusChrome:
    """Both pages must consume the shared strip / pill / dot classes."""

    def test_uses_shared_status_strip_and_tiles(self, name, path):
        source = _page_source(path)
        assert 'class="status-strip' in source, f"{name} has no .status-strip"
        tiles = source.count('class="status-tile')
        assert tiles == 7, (
            f"{name} renders {tiles} .status-tile elements; both monitoring "
            "strips are seven tiles wide."
        )

    def test_uses_shared_pill_and_dot(self, name, path):
        source = _page_source(path)
        assert 'class="status-pill' in source, f"{name} has no .status-pill"
        assert 'class="live-dot"' in source, f"{name} has no .live-dot"

    @pytest.mark.parametrize("retired", RETIRED_CLASSES)
    def test_no_retired_page_private_classes(self, name, path, retired):
        """Guard against a page re-growing its own copy.

        Matches class *attributes* and CSS *selectors* only — element IDs
        such as ``id="gps-live-dot"`` are deliberately unchanged, because
        the page JavaScript resolves those by ID.
        """
        source = _page_source(path)
        offenders = re.findall(rf'class="[^"]*\b{re.escape(retired)}\b', source)
        offenders += re.findall(rf"^\s*\.{re.escape(retired)}\b", source, re.M)
        assert not offenders, (
            f"{name} still uses the retired class {retired!r}: {offenders[:3]}"
        )


class TestSharedChromeIsDefinedOnce:
    """The shared classes must live in styles.css, not in a page."""

    @pytest.mark.parametrize(
        "selector",
        [".status-strip", ".status-tile", ".status-pill", ".live-dot"],
    )
    def test_defined_in_styles_css(self, selector):
        css = STYLES_CSS.read_text(encoding="utf-8")
        assert re.search(rf"^{re.escape(selector)}\s*{{", css, re.M), (
            f"{selector} is not defined in static/css/styles.css"
        )

    @pytest.mark.parametrize("name,path", sorted(MONITORING_PAGES.items()))
    def test_pages_do_not_redefine_the_shared_classes(self, name, path):
        """A page-local redefinition is how the copies drifted last time."""
        source = _page_source(path)
        start = source.index("{% block extra_css %}")
        end = source.index("{% endblock %}", start)
        page_css = source[start:end]
        for selector in (".status-strip", ".status-tile", ".status-pill", ".live-dot"):
            # Bare redefinition, i.e. not scoped under .page-header-actions or
            # similar — those are legitimate contextual adjustments.
            bare = re.findall(
                rf"^\s*{re.escape(selector)}[\s,{{]", page_css, re.M
            )
            assert not bare, (
                f"{name} redefines the shared {selector} in its own CSS block. "
                "Change static/css/styles.css so both pages stay in step."
            )


class TestSeverityPaletteIsConsistent:
    """One meaning, one colour.

    The pages previously used two different greens for "OK" — #6ee07a on
    System Health's pills and #3fb950 on the GNSS tiles — because each page
    had picked its own. The shared CSS keeps two palettes on purpose (tiles
    sit on the page surface, pills sit on the header gradient), but each must
    be defined exactly once.
    """

    @staticmethod
    def _shared_section() -> str:
        css = STYLES_CSS.read_text(encoding="utf-8")
        marker = "Telemetry Status Strip"
        assert marker in css, "shared status-strip section missing from styles.css"
        return css[css.index(marker):]

    def test_tile_severity_colours_defined_once_each(self):
        section = self._shared_section()
        for sev in ("ok", "warn", "fault", "info"):
            hits = re.findall(rf"^\.status-tile\.sev-{sev}\b", section, re.M)
            assert len(hits) == 2, (
                f".status-tile.sev-{sev} should be declared exactly twice "
                f"(rail + value colour), found {len(hits)}"
            )

    def test_pill_tones_defined_once_each(self):
        section = self._shared_section()
        for tone in ("ok", "warn", "danger", "info", "muted"):
            hits = re.findall(rf"^\.status-pill\.{tone}\b", section, re.M)
            assert len(hits) == 1, (
                f".status-pill.{tone} should be declared exactly once, "
                f"found {len(hits)}"
            )

    def test_tiles_use_one_surface_token(self):
        """The two strips previously disagreed on their background token.

        System Health used --surface-color and the GNSS page used
        --bg-secondary, so the same strip could paint differently on the
        two pages under one theme.
        """
        section = self._shared_section()
        tile_block = section[section.index(".status-tile {"):]
        tile_block = tile_block[:tile_block.index("}")]
        assert "--surface-color" in tile_block
        assert "--bg-secondary" not in tile_block
