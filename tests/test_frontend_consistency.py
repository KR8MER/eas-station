"""Guards against the front-end duplication that CI now prevents regressing.

These are cheap static checks over ``templates/`` and ``static/``. They exist
because each of the patterns below had already spread across the codebase
before anything was watching for it:

* ``escapeHtml`` had 16 behaviourally different implementations across 22
  templates plus 6 more in ``static/js`` — several of which did not escape
  quotes and were interpolated into HTML attributes.
* ``showToast`` was redefined locally in 8 templates despite being documented
  in AGENTS.md as a global to reuse.
* ``.spinner`` / ``.status-badge`` / ``.empty-state`` were promoted into
  ``static/css/styles.css`` but the inline copies were never deleted, so the
  page-local rules kept winning the cascade and the shared ones did nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "templates"
STATIC_JS = REPO_ROOT / "static" / "js"

# The single canonical home for each shared browser helper. Every other file
# must call the global rather than declaring its own copy.
CANONICAL_UTILS = STATIC_JS / "core" / "utils.js"
CANONICAL_HOME = {
    "escapeHtml": CANONICAL_UTILS,
    "showToast": STATIC_JS / "core" / "notifications.js",
}

INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
INLINE_STYLE_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)


def _templates() -> list[Path]:
    return sorted(TEMPLATES.rglob("*.html"))


def _js_files() -> list[Path]:
    return [p for p in sorted(STATIC_JS.rglob("*.js")) if "vendor" not in p.parts]


def _inline_scripts(path: Path) -> list[str]:
    return INLINE_SCRIPT_RE.findall(path.read_text(encoding="utf-8", errors="ignore"))


def _definition_sites(name: str) -> list[str]:
    """Return every file declaring ``function <name>`` outside its canonical home."""
    # `\s*\(` right after the name keeps this from matching longer identifiers
    # such as the showToastMsg wrapper, which legitimately delegates to the global.
    pattern = re.compile(r"\bfunction\s+" + re.escape(name) + r"\s*\(")
    canonical = CANONICAL_HOME[name]
    sites = []

    for template in _templates():
        for body in _inline_scripts(template):
            if pattern.search(body):
                sites.append(str(template.relative_to(REPO_ROOT)))
                break

    for js_file in _js_files():
        if js_file == canonical:
            continue
        if pattern.search(js_file.read_text(encoding="utf-8", errors="ignore")):
            sites.append(str(js_file.relative_to(REPO_ROOT)))

    return sites


def test_escape_html_has_exactly_one_implementation():
    """Only core/utils.js may define escapeHtml."""
    duplicates = _definition_sites("escapeHtml")
    assert not duplicates, (
        "escapeHtml must be defined only in static/js/core/utils.js and used via "
        "the window.escapeHtml global. Duplicate definitions drift apart — the "
        "textContent round-trip variant does not escape quotes and is unsafe in "
        "attribute contexts. Found local definitions in:\n  "
        + "\n  ".join(duplicates)
    )


def test_canonical_escape_html_escapes_quotes():
    """The shared implementation must be attribute-safe, not just text-safe."""
    source = CANONICAL_UTILS.read_text(encoding="utf-8")
    match = re.search(r"function escapeHtml\s*\([^)]*\)\s*\{.*?\n    \}", source, re.S)
    assert match, "could not locate escapeHtml in static/js/core/utils.js"
    body = match.group(0)

    assert "textContent" not in body, (
        "escapeHtml must not use the detached-<div>/textContent round-trip: it "
        "escapes &, < and > but leaves \" and ' intact, which is unsafe wherever "
        "the result is interpolated into a quoted HTML attribute."
    )
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert entity in source, f"escapeHtml must emit {entity}"


def test_escape_html_is_exposed_as_a_global():
    """Templates call escapeHtml() bare, so it must be on window."""
    source = CANONICAL_UTILS.read_text(encoding="utf-8")
    assert "window.escapeHtml = escapeHtml" in source, (
        "escapeHtml must be published as window.escapeHtml. It was previously "
        "reachable only as EASUtils.escapeHtml, which is exactly why 22 "
        "templates grew their own local copy."
    )


def test_show_toast_is_not_redefined_locally():
    """showToast is a documented global (AGENTS.md); local copies shadow it."""
    duplicates = _definition_sites("showToast")
    assert not duplicates, (
        "showToast is provided globally by static/js/core/notifications.js and "
        "documented in AGENTS.md as a function to reuse. Local definitions "
        "shadow it and drift. Found in:\n  " + "\n  ".join(duplicates)
    )


# Selectors that live in static/css/styles.css and must not be redefined in a
# page-local <style> block, where the later rule silently wins the cascade.
SHARED_SELECTORS = (".spinner", ".status-badge", ".empty-state")

STYLES_CSS = REPO_ROOT / "static" / "css" / "styles.css"

# Bootstrap's own classes. Redefining these unscoped in one page restyles that
# page's buttons/cards only, which is precisely how pages drift apart.
BOOTSTRAP_CLASSES = (
    ".btn", ".card", ".card-header", ".card-body", ".card-footer",
    ".nav-link", ".form-label", ".form-control", ".table", ".modal",
    ".badge", ".alert", ".dropdown-menu",
)


def _unscoped_rules(template: Path) -> set[str]:
    """Return bare single-class selectors a template defines in its own <style>.

    "Unscoped" means the whole selector is one class with no ancestor, element
    or state qualifier — ``.spinner {}`` counts, ``.stat-card .stat-label {}``
    and ``.status-badge.connected {}`` do not.
    """
    found = set()
    text = template.read_text(encoding="utf-8", errors="ignore")
    for body in INLINE_STYLE_RE.findall(text):
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        for raw_selector in re.findall(r"(?:^|\})\s*([^{}@]+?)\s*\{", body):
            for part in raw_selector.split(","):
                part = part.strip()
                if re.fullmatch(r"\.[A-Za-z][\w-]*", part):
                    found.add(part)
    return found


@pytest.mark.parametrize("selector", SHARED_SELECTORS)
def test_shared_css_selectors_are_not_redefined_inline(selector):
    """A class owned by styles.css may not be redefined unscoped in a page."""
    assert re.search(re.escape(selector) + r"\s*\{", STYLES_CSS.read_text(encoding="utf-8")), (
        f"{selector} is expected to be defined in static/css/styles.css"
    )

    offenders = sorted(
        str(t.relative_to(REPO_ROOT)) for t in _templates() if selector in _unscoped_rules(t)
    )
    assert not offenders, (
        f"{selector} is defined in static/css/styles.css. Redefining it unscoped "
        "in a page-local <style> block means the page copy wins the cascade and "
        "the shared rule stops applying, which is how pages drift apart "
        "visually. Use a modifier class (e.g. .spinner-lg, .empty-state-plain, "
        ".status-badge-plain) or scope the rule under a page wrapper. Found in:"
        "\n  " + "\n  ".join(offenders)
    )


PAGE_HEADER_COMPONENT = TEMPLATES / "components" / "page_header.html"
HERO_COMPONENT = TEMPLATES / "partials" / "hero.html"


def test_no_template_hand_rolls_a_page_header():
    """Every page header must come from components/page_header.html.

    Four different header systems used to coexist: the shared component, the
    shared hero, a hand-rolled ``.page-header`` on System Health, and a bespoke
    ``.workflow-hero`` on the Broadcast Builder. Each rendered its title at a
    different size, so heading sizing visibly changed as you moved between
    pages.
    """
    offenders = []
    for template in _templates():
        if template in (PAGE_HEADER_COMPONENT, HERO_COMPONENT):
            continue
        text = template.read_text(encoding="utf-8", errors="ignore")
        # A literal class attribute containing page-header, outside a <style>.
        markup = INLINE_STYLE_RE.sub("", text)
        if re.search(r'class="[^"]*\bpage-header\b', markup):
            offenders.append(str(template.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Page headers must be rendered by including "
        "components/page_header.html (set the header_* variables), not by "
        "hand-writing .page-header markup. Found in:\n  " + "\n  ".join(offenders)
    )


COLLISION_ALLOWLIST_FILE = Path(__file__).parent / "css_collisions_allowlist.txt"


def _collision_allowlist() -> set[str]:
    if not COLLISION_ALLOWLIST_FILE.is_file():
        return set()
    entries = set()
    for raw_line in COLLISION_ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


def test_no_new_class_is_defined_unscoped_by_two_different_pages():
    """Two pages styling the same bare class name is a collision waiting to happen.

    Whichever rule the browser sees last wins, so the same class silently means
    different things on different pages. Scope the rule under a page wrapper, or
    promote it to styles.css and express the variant as a modifier.

    Pre-existing collisions are recorded in tests/css_collisions_allowlist.txt
    and are a shrinking backlog; this test guards against *new* ones.
    """
    owners: dict[str, list[str]] = {}
    for template in _templates():
        for selector in _unscoped_rules(template):
            owners.setdefault(selector, []).append(str(template.relative_to(REPO_ROOT)))

    allowed = _collision_allowlist()
    collisions = {
        k: v for k, v in sorted(owners.items()) if len(v) > 1 and k not in allowed
    }
    assert not collisions, (
        "New cross-page CSS class collision(s). Scope the rule under the page's "
        "own wrapper, or promote it to static/css/styles.css with a modifier for "
        "the variant. Do not add these to the allowlist:\n"
        + "\n".join(f"  {k}\n      " + "\n      ".join(v) for k, v in collisions.items())
    )


def test_collision_allowlist_has_no_stale_entries():
    """An allowlisted class that no longer collides must be removed from the file."""
    owners: dict[str, int] = {}
    for template in _templates():
        for selector in _unscoped_rules(template):
            owners[selector] = owners.get(selector, 0) + 1

    stale = sorted(s for s in _collision_allowlist() if owners.get(s, 0) <= 1)
    assert not stale, (
        "tests/css_collisions_allowlist.txt lists class(es) that no longer "
        "collide — delete these lines so the backlog reflects reality:\n  "
        + "\n  ".join(stale)
    )


@pytest.mark.parametrize("selector", BOOTSTRAP_CLASSES)
def test_bootstrap_classes_are_not_restyled_per_page(selector):
    """Bootstrap primitives must be themed globally, never per page."""
    offenders = sorted(
        str(t.relative_to(REPO_ROOT)) for t in _templates() if selector in _unscoped_rules(t)
    )
    assert not offenders, (
        f"{selector} is a Bootstrap class. Redefining it unscoped in a single "
        "page restyles that page's components only, so the same control looks "
        "different depending on where you are. Theme it in static/css/styles.css "
        "(or scope the rule to the page's own wrapper). Found in:\n  "
        + "\n  ".join(offenders)
    )
