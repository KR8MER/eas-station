"""Guards for the shared, theme-aware Leaflet map skin.

Every Leaflet map in the app used to be built by hand: a raw
``L.map(...)`` plus a raw OpenStreetMap ``L.tileLayer(...)``, with no
relationship to the active theme and no relationship to the share-image
renderer that produces the graphics people actually forward. The result was
a bright pastel rectangle pasted into a dark card, with the alert polygon
competing against the road network for attention.

``static/css/map.css`` + ``static/js/core/map_theme.js`` are now the single
home for that treatment. These are cheap static checks over ``templates/``
and ``static/`` that keep the arrangement from coming apart:

* a page that loads Leaflet but forgets the skin renders an untoned map,
  and nothing else in the test suite would notice;
* two CSS traps in here are invisible when you get them wrong — a filter on
  a zero-size Leaflet pane silently does nothing, and Leaflet's own
  ``max-width: none`` reset is scoped to ``.leaflet-overlay-pane`` so custom
  panes collapse to zero width under the global ``svg { max-width: 100% }``
  and draw nothing at all;
* ``base.html`` hardcodes the list of dark themes for its anti-flash script,
  which silently rots when a theme is added to ``theme.js``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "templates"
MAP_CSS = REPO_ROOT / "static" / "css" / "map.css"
MAP_JS = REPO_ROOT / "static" / "js" / "core" / "map_theme.js"
THEME_JS = REPO_ROOT / "static" / "js" / "core" / "theme.js"
STYLES_CSS = REPO_ROOT / "static" / "css" / "styles.css"
BASE_HTML = TEMPLATES / "base.html"


def _templates() -> list[Path]:
    return sorted(TEMPLATES.rglob("*.html"))


def _leaflet_templates() -> list[Path]:
    """Templates that pull in Leaflet's own stylesheet or bundle."""
    hits = []
    for path in _templates():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "vendor/leaflet/leaflet.css" in text or "vendor/leaflet/leaflet.min.js" in text:
            hits.append(path)
    return hits


def test_skin_assets_exist():
    assert MAP_CSS.is_file(), "static/css/map.css is the shared Leaflet skin"
    assert MAP_JS.is_file(), "static/js/core/map_theme.js defines window.EASMap"


@pytest.mark.parametrize("template", _leaflet_templates(), ids=lambda p: p.name)
def test_leaflet_pages_load_the_shared_skin(template: Path):
    """Loading Leaflet without the skin gives an untoned, theme-blind map."""
    text = template.read_text(encoding="utf-8", errors="ignore")

    if "vendor/leaflet/leaflet.css" in text:
        assert "css/map.css" in text, (
            f"{template.relative_to(REPO_ROOT)} loads leaflet.css but not "
            "static/css/map.css — the map will ignore the active theme."
        )
    if "vendor/leaflet/leaflet.min.js" in text:
        assert "js/core/map_theme.js" in text, (
            f"{template.relative_to(REPO_ROOT)} loads Leaflet but not "
            "static/js/core/map_theme.js — window.EASMap will be undefined."
        )


@pytest.mark.parametrize("template", _leaflet_templates(), ids=lambda p: p.name)
def test_maps_are_created_through_easmap(template: Path):
    """`L.map(...)` bypasses the skin: no panes, no tone, no scale bar."""
    text = template.read_text(encoding="utf-8", errors="ignore")
    raw = re.findall(r"\bL\.map\s*\(", text)
    assert not raw, (
        f"{template.relative_to(REPO_ROOT)} calls L.map() directly. Use "
        "EASMap.create(id, opts) — or EASMap.init(map) if the map has to be "
        "constructed by hand — so it gets the toned basemap, the hazard and "
        "reference panes, and the scale bar."
    )


def test_tile_tone_is_applied_to_tiles_not_the_pane():
    """A CSS filter on a Leaflet pane is a no-op, and looks correct in devtools.

    Panes are 0×0 absolutely-positioned divs. A filter's region derives from
    the element's own box, so on a zero-size box the browser applies nothing
    while ``getComputedStyle`` still reports the filter — the failure mode is
    completely silent. The tone therefore has to sit on ``.leaflet-tile``.
    """
    css = MAP_CSS.read_text(encoding="utf-8")

    tile_rule = re.search(
        r"\.eas-map \.leaflet-tile\s*\{[^}]*\}", css, re.S
    )
    assert tile_rule and "--map-tile-filter" in tile_rule.group(0), (
        "the tone chain must be applied to .eas-map .leaflet-tile"
    )

    pane_rule = re.search(
        r"\.eas-map \.leaflet-tile-pane\s*\{([^}]*)\}", css, re.S
    )
    assert pane_rule, "expected a .eas-map .leaflet-tile-pane rule for the tint"
    assert "filter" not in pane_rule.group(1), (
        "filter on .leaflet-tile-pane silently does nothing (0×0 pane); "
        "only opacity belongs there"
    )


def test_custom_panes_reset_the_global_media_cap():
    """Leaflet only ships the reset for `.leaflet-overlay-pane`.

    ``styles.css`` caps embedded media with ``svg, canvas { max-width: 100% }``
    for mobile overflow. Inside a 0×0 pane that resolves to zero, so every
    vector layer in a custom pane renders nothing. Leaflet defends its own
    overlay pane; ours have to defend themselves.
    """
    styles = STYLES_CSS.read_text(encoding="utf-8")
    if not re.search(r"^\s*svg,[^{]*\{[^}]*max-width:\s*100%", styles, re.M):
        pytest.skip("styles.css no longer caps svg width globally")

    css = MAP_CSS.read_text(encoding="utf-8")
    for pane in ("leaflet-easReference-pane", "leaflet-easHazard-pane"):
        assert re.search(
            rf"\.{pane} svg[^{{]*\{{[^}}]*max-width:\s*none", css, re.S
        ), f"{pane} needs `max-width: none` or its vector layers vanish"


def test_tone_tokens_defined_for_both_modes():
    css = MAP_CSS.read_text(encoding="utf-8")
    root = re.search(r"^:root\s*\{(.*?)\}", css, re.S | re.M)
    dark = re.search(r'^\[data-theme-mode="dark"\]\s*\{(.*?)\}', css, re.S | re.M)
    assert root and dark, "map.css must define tone tokens for light and dark"

    for token in ("--map-tile-filter", "--map-tile-opacity", "--map-vignette"):
        assert token in root.group(1), f"{token} missing from the :root defaults"
        assert token in dark.group(1), f"{token} missing from the dark overrides"


def _dark_themes_from_theme_js() -> set[str]:
    """Theme names declared `mode: 'dark'` in static/js/core/theme.js."""
    text = THEME_JS.read_text(encoding="utf-8")
    block = re.search(r"const THEMES\s*=\s*\{(.*?)\n    \};", text, re.S)
    assert block, "could not locate the THEMES map in theme.js"
    return {
        name
        for name, body in re.findall(
            r"'([a-z]+)':\s*\{(.*?)\}", block.group(1), re.S
        )
        if "mode: 'dark'" in body
    }


def test_base_html_dark_theme_list_matches_theme_js():
    """The anti-flash script hardcodes the dark themes; keep it in sync.

    ``data-theme-mode`` is normally stamped by theme.js on DOMContentLoaded,
    which is too late for rules keyed on it — the basemap would paint its
    light tone first and snap to dark a moment later. base.html therefore
    stamps it inline, from a copy of the list.
    """
    base = BASE_HTML.read_text(encoding="utf-8")
    listed = re.search(r"const DARK_THEMES\s*=\s*\[(.*?)\];", base, re.S)
    assert listed, "base.html must declare DARK_THEMES for the anti-flash script"

    declared = set(re.findall(r"'([a-z]+)'", listed.group(1)))
    assert declared == _dark_themes_from_theme_js(), (
        "base.html's DARK_THEMES has drifted from theme.js:\n"
        f"  only in base.html: {sorted(declared - _dark_themes_from_theme_js())}\n"
        f"  only in theme.js:  {sorted(_dark_themes_from_theme_js() - declared)}"
    )


def test_leaflet_chrome_lives_only_in_map_css():
    """styles.css is loaded on every page; the Leaflet skin is not needed there."""
    styles = STYLES_CSS.read_text(encoding="utf-8")
    leftovers = sorted(set(re.findall(r"^\.leaflet-[\w.-]*", styles, re.M)))
    assert not leftovers, (
        "Leaflet rules belong in static/css/map.css, not the global "
        f"stylesheet: {leftovers}"
    )


def test_easmap_exposes_the_documented_api():
    js = MAP_JS.read_text(encoding="utf-8")
    export = re.search(r"window\.EASMap\s*=\s*\{(.*?)\n    \};", js, re.S)
    assert export, "map_theme.js must assign window.EASMap"
    for name in (
        "init",
        "create",
        "tileLayer",
        "hazardLayer",
        "referenceLayer",
        "referenceStyle",
        "severityColor",
        "onThemeChange",
    ):
        assert re.search(rf"\b{name}:", export.group(1)), (
            f"EASMap.{name} is used by templates but is no longer exported"
        )
