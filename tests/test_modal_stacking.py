"""Guard against modals trapped below the Bootstrap backdrop.

``static/css/styles.css`` has a rule -- ``.page-shell > *:not(.orb):not(.modal)``
-- that gives every direct child of the page's ``<main class="page-shell">``
its own stacking context (``z-index: 1``), so page content never visually
bleeds through the sticky navbar. Bootstrap's modal backdrop is appended
directly to ``<body>`` (outside ``.page-shell`` entirely) at ``z-index: 1040``.

A ``.modal`` that is itself a direct child of ``.page-shell`` is excluded
from that rule by name and renders above the backdrop, as intended. A
``.modal`` placed *outside* ``.page-shell`` altogether (e.g. ``base.html``'s
``#globalUnitsModal``, which lives after ``</main>``) is unaffected for the
same reason -- it never enters a stacking context created by that rule.

But a ``.modal`` nested *inside* some other direct child of ``.page-shell``
(almost always a ``.container-fluid`` wrapping the page's real content)
inherits that ancestor's ``z-index: 1`` stacking context, trapping it below
the backdrop. The symptom looks nothing like a stacking bug: the modal
renders, looks correct, even scrolls if it has ``modal-dialog-scrollable``
-- but every click lands on the backdrop instead of the modal's own
buttons, and the only way out is a full page reload. This was shipped and
went unnoticed because verification checked computed CSS properties
(``overflow-y``, whether the class was present) rather than actually
clicking a button inside the open modal.

Three real instances of this were found by rendering every page in a
headless browser and asking, for each ``.modal``, "does document.body
still deliver a click at the button's actual screen coordinates to the
button, not to something else?" -- fixed by moving each modal's markup to
be a direct child of ``.page-shell`` (see the comment on
``templates/admin/certbot.html``'s ``#logModal``, the first place this
pattern was solved). This test statically re-derives the same "is this
modal nested inside a non-modal, non-orb direct child of the content
block" check from template source, so a modal reintroduced inside a
container -- in an included partial or otherwise -- fails CI instead of
shipping silently broken.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "templates"

# Matches a bare <div ...> or </div>, tolerant of attributes spanning
# multiple lines and Jinja {{ }}/{% %} inside attribute values. Doesn't
# attempt to handle self-closing div syntax (templates here don't use it).
_DIV_OPEN = re.compile(r"<div\b([^>]*)>", re.IGNORECASE | re.DOTALL)
_DIV_CLOSE = re.compile(r"</div\s*>", re.IGNORECASE)
_DIV_TAG = re.compile(r"<div\b[^>]*>|</div\s*>", re.IGNORECASE | re.DOTALL)
_CLASS_ATTR = re.compile(r'class\s*=\s*"([^"]*)"', re.IGNORECASE)
_INCLUDE = re.compile(r'{%-?\s*include\s+[\'"]([^\'"]+)[\'"]\s*-?%}')

# Modals that are structurally nested in the template source (so this
# static check would otherwise flag them) but are provably safe because
# JavaScript relocates them to a direct child of <body> before they can
# ever be shown -- moving them out of the stacking context this test
# guards against by a different, equally valid mechanism. Each entry must
# name the file and line that performs the relocation; a modal id here
# without one is not a real exception.
_RELOCATED_AT_RUNTIME = {
    # static/js/admin/core.js:185 -- `document.body.appendChild(confirmModalEl)`
    # on DOMContentLoaded, before any code can call .show() on it.
    "confirmationModal",
}


def _resolve_includes(text: str, seen: frozenset[str] = frozenset()) -> str:
    """Splice in {% include 'x.html' %} targets, recursively.

    Not a real Jinja renderer -- doesn't touch {% if %}/{% for %}, which is
    fine here: this check only cares about which <div> a <div class="modal">
    ends up nested inside, and conditionals don't change that nesting shape
    (a block that's sometimes absent doesn't change what wraps a block
    that's always present).
    """

    def repl(match: re.Match[str]) -> str:
        target = match.group(1)
        if target in seen:
            return ""  # guard against include cycles
        path = TEMPLATES / target
        if not path.is_file():
            return ""
        return _resolve_includes(
            path.read_text(encoding="utf-8", errors="ignore"), seen | {target}
        )

    return _INCLUDE.sub(repl, text)


def _content_block(text: str) -> str | None:
    """Extract the raw text of {% block content %}...{% endblock %}."""
    m = re.search(
        r"{%-?\s*block\s+content\s*-?%}(.*?){%-?\s*endblock\s*-?%}",
        text,
        re.DOTALL,
    )
    return m.group(1) if m else None


def _classes(attrs: str) -> set[str]:
    m = _CLASS_ATTR.search(attrs)
    if not m:
        return set()
    return set(m.group(1).split())


def _find_trapped_modals(content: str) -> list[str]:
    """Return the id= of every <div class="modal ..."> nested inside a
    non-modal, non-orb <div> within this content block (i.e. not at the
    block's own top level, where it would render as a direct child of
    .page-shell)."""
    trapped = []
    # Stack of (classes, depth-that-is-"risky") for open divs. A div is
    # "risky" if it is itself excluded from the page-shell direct-child
    # exemption (not .modal, not .orb) -- i.e. it's a normal wrapper that
    # would carry the z-index:1 stacking context if it sat directly under
    # .page-shell, OR it's already nested inside a risky ancestor.
    stack: list[bool] = []  # True == this div (or an ancestor) is risky
    pos = 0
    for m in _DIV_TAG.finditer(content):
        if m.group(0).lower().startswith("</div"):
            if stack:
                stack.pop()
            continue
        attrs = _DIV_OPEN.match(m.group(0))
        cls = _classes(attrs.group(1)) if attrs else set()
        is_modal = "modal" in cls
        is_orb = "orb" in cls
        currently_nested_in_risky = any(stack)
        if is_modal and currently_nested_in_risky:
            id_match = re.search(r'id\s*=\s*"([^"]*)"', attrs.group(1) if attrs else "")
            modal_id = id_match.group(1) if id_match else "(no id)"
            if modal_id not in _RELOCATED_AT_RUNTIME:
                trapped.append(modal_id)
        this_div_is_risky = currently_nested_in_risky or not (is_modal or is_orb)
        stack.append(this_div_is_risky)
    return trapped


def _page_templates() -> list[Path]:
    """Templates that extend base.html and define {% block content %}."""
    out = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if '{% extends "base.html" %}' in text and "{% block content %}" in text:
            out.append(path)
    return out


@pytest.mark.parametrize("template", _page_templates(), ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_modals_are_not_trapped_below_backdrop(template: Path):
    text = template.read_text(encoding="utf-8", errors="ignore")
    content = _content_block(text)
    if content is None:
        pytest.skip("no {% block content %} found")
    resolved = _resolve_includes(content)
    if "modal" not in resolved:
        pytest.skip("no modal on this page")

    trapped = _find_trapped_modals(resolved)
    assert not trapped, (
        f"{template.relative_to(TEMPLATES)}: modal(s) {trapped} are nested inside "
        "a non-modal wrapper div within {% block content %}, so they inherit that "
        "wrapper's z-index:1 stacking context (from the .page-shell > "
        "*:not(.orb):not(.modal) rule in styles.css) and render trapped below "
        "Bootstrap's body-level backdrop -- visible but unclickable and "
        "unscrollable. Move the modal's markup to be a direct child of "
        "{% block content %} (a sibling of the page's top-level container, not "
        "nested inside it), matching templates/admin/certbot.html's #logModal."
    )
