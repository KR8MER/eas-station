"""The default theme is Lightning, and the retired Cosmo theme stays gone.

The default is spelled out in three places that nothing else ties together:
``DEFAULT_THEME`` in theme.js, the server-rendered ``<html data-theme>`` and
the anti-flash fallback in base.html. If they disagree, a first visit paints
one theme and snaps to another once theme.js loads.

Browsers that saved ``cosmo`` before it was removed must be migrated by the
anti-flash script; otherwise they paint with no theme palette at all until
theme.js falls back.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
THEME_JS = REPO_ROOT / "static" / "js" / "core" / "theme.js"
BASE_HTML = REPO_ROOT / "templates" / "base.html"
STYLES_CSS = REPO_ROOT / "static" / "css" / "styles.css"


def _default_from_theme_js() -> str:
    match = re.search(r"const DEFAULT_THEME = '([a-z-]+)';", THEME_JS.read_text(encoding="utf-8"))
    assert match, "theme.js must declare DEFAULT_THEME"
    return match.group(1)


def test_default_theme_is_lightning():
    assert _default_from_theme_js() == "lightning"


def test_base_html_agrees_with_theme_js_default():
    base = BASE_HTML.read_text(encoding="utf-8")
    default = _default_from_theme_js()
    assert f'<html lang="en" data-theme="{default}"' in base
    assert f"localStorage.getItem('theme') || '{default}'" in base


def test_light_toggle_target_exists_and_is_light():
    text = THEME_JS.read_text(encoding="utf-8")
    match = re.search(r"const DEFAULT_LIGHT_THEME = '([a-z-]+)';", text)
    assert match, "theme.js must declare DEFAULT_LIGHT_THEME for the sun/moon toggle"
    entry = re.search(rf"'{match.group(1)}':\s*\{{[^}}]*mode:\s*'(light|dark)'", text)
    assert entry and entry.group(1) == "light", "the quick toggle's light target must be a light theme"


def test_cosmo_is_retired_and_migrated():
    assert "'cosmo':" not in THEME_JS.read_text(encoding="utf-8")
    assert '[data-theme="cosmo"]' not in STYLES_CSS.read_text(encoding="utf-8")
    base = BASE_HTML.read_text(encoding="utf-8")
    assert "savedTheme === 'cosmo'" in base, "base.html must migrate a saved 'cosmo' choice"
