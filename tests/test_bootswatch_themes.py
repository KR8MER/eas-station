"""Guards for the Bootswatch themes (``bw-<name>`` in ``theme.js``).

A Bootswatch theme swaps the Bootstrap stylesheet for
``static/vendor/bootswatch/<name>/bootstrap.min.css`` and relies on
``static/css/bootswatch.css`` to map EAS Station's own variables onto it.
The theme list is repeated in a few places that nothing else ties
together, and each copy fails quietly when it drifts:

* a theme registered in ``theme.js`` without its vendored stylesheet loads
  a 404 in place of Bootstrap and the page renders unstyled;
* a vendored build that still ``@import``s Google Fonts is blocked by the
  CSP (``style-src 'self'``) and leaks a request off-box on every load;
* the contrast audit only checks themes it is told about.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
THEME_JS = REPO_ROOT / "static" / "js" / "core" / "theme.js"
VENDOR = REPO_ROOT / "static" / "vendor" / "bootswatch"
BRIDGE_CSS = REPO_ROOT / "static" / "css" / "bootswatch.css"
BASE_HTML = REPO_ROOT / "templates" / "base.html"
CONTRAST_AUDIT = REPO_ROOT / "scripts" / "diagnostics" / "check_theme_contrast.py"


def _bootswatch_themes() -> dict[str, str]:
    """Map of theme key -> Bootswatch build name, from theme.js."""
    text = THEME_JS.read_text(encoding="utf-8")
    return dict(
        re.findall(r"'(bw-[a-z]+)':\s*\{[^}]*?bootswatch:\s*'([a-z]+)'", text, re.S)
    )


def test_bootswatch_themes_are_registered():
    themes = _bootswatch_themes()
    assert themes, "no Bootswatch themes found in theme.js"
    for key, build in themes.items():
        assert key == f"bw-{build}", f"{key} should be named bw-{build}"


def test_every_bootswatch_theme_is_vendored():
    missing = [
        build
        for build in _bootswatch_themes().values()
        if not (VENDOR / build / "bootstrap.min.css").is_file()
    ]
    assert not missing, f"theme.js registers Bootswatch themes with no vendored CSS: {missing}"
    assert (VENDOR / "LICENSE").is_file(), "Bootswatch's MIT LICENSE must ship with the files"


def test_vendored_bootswatch_has_no_remote_imports():
    offenders = [
        str(css.relative_to(REPO_ROOT))
        for css in VENDOR.glob("*/bootstrap.min.css")
        if re.search(r"@import\s+url\(\s*['\"]?https?:", css.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "strip the Google Fonts @import from these Bootswatch builds (CSP blocks "
        f"it and it phones home): {offenders}"
    )


def test_base_html_loads_bridge_after_styles():
    base = BASE_HTML.read_text(encoding="utf-8")
    assert 'id="bootstrap-css"' in base, "theme.js swaps the <link id=\"bootstrap-css\">"
    assert "data-bootswatch-href" in base and "__THEME__" in base
    styles = base.index("css/styles.css")
    bridge = base.index("css/bootswatch.css")
    assert bridge > styles, "bootswatch.css must load after styles.css to override it"


def test_dark_bootswatch_themes_have_surfaces():
    """Dark Bootswatch builds keep Bootstrap's light --bs-secondary-bg on
    :root, so the bridge must spell out each dark theme's surfaces."""
    text = THEME_JS.read_text(encoding="utf-8")
    dark = re.findall(r"'(bw-[a-z]+)':\s*\{[^}]*?mode:\s*'dark'", text, re.S)
    bridge = BRIDGE_CSS.read_text(encoding="utf-8")
    missing = [
        key for key in dark
        if not re.search(
            rf':root\[data-theme="{key}"\]\s*\{{[^}}]*--surface-color', bridge
        )
    ]
    assert not missing, f"bootswatch.css has no --surface-color for: {missing}"


def test_contrast_audit_covers_bootswatch_themes():
    audit = CONTRAST_AUDIT.read_text(encoding="utf-8")
    listed = re.search(r"BOOTSWATCH_THEMES\s*=\s*\[(.*?)\]", audit, re.S)
    assert listed, "check_theme_contrast.py must list BOOTSWATCH_THEMES"
    assert set(re.findall(r'"([a-z]+)"', listed.group(1))) == set(
        _bootswatch_themes().values()
    ), "check_theme_contrast.py's BOOTSWATCH_THEMES has drifted from theme.js"
