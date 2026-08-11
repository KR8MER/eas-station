"""Guards against dropdown menus being clipped by their surrounding card.

``.card`` in ``static/css/styles.css`` sets ``overflow: hidden`` so the
``::before`` accent line, the ``::after`` glow and any card media stay inside
the rounded corners. That same declaration clips *every* absolutely-positioned
descendant that leaves the card box — and a Bootstrap dropdown menu is exactly
that. On the Received Alerts filter panel the Audio Source / Event Type
multi-selects were sliced off at the card's bottom edge, leaving barely one
option reachable.

The failure is silent in code review: nothing in the template is wrong, the
menu opens, Popper positions it correctly, and only a rendered browser shows
that most of it is invisible and un-clickable. These static checks keep the
three pieces of the fix wired together:

* the card must stop clipping while a menu is open, and
* it must be lifted above the cards that follow it — ``backdrop-filter`` makes
  every ``.card`` its own stacking context, and equal-``z-index`` stacking
  contexts paint in document order, so the next card would paint over the
  un-clipped menu, and
* the accent line must carry its own ``border-radius``, because it no longer
  has the card's clipping to round its corners for it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STYLES_CSS = REPO_ROOT / "static" / "css" / "styles.css"
UTILS_JS = REPO_ROOT / "static" / "js" / "core" / "utils.js"


def _rule_body(css: str, selector: str) -> str | None:
    """Return the declaration block of the first rule matching ``selector``."""
    match = re.search(
        r"(?:^|\})\s*" + re.escape(selector) + r"\s*(?:,[^{}]*)?\{([^{}]*)\}",
        css,
        re.M,
    )
    return match.group(1) if match else None


def test_card_still_clips_by_default():
    """The premise of the fix — if this ever changes, the rest is dead weight."""
    css = STYLES_CSS.read_text(encoding="utf-8")
    body = _rule_body(css, ".card")
    assert body is not None, "expected a bare `.card` rule in styles.css"
    assert "overflow: hidden" in body, (
        "`.card` no longer sets `overflow: hidden`. If that was deliberate, the "
        "companion `.card:has(.dropdown-menu.show)` rule can go too."
    )


def test_open_dropdown_unclips_and_lifts_the_card():
    css = STYLES_CSS.read_text(encoding="utf-8")

    match = re.search(
        r"\.card:has\(\.dropdown-menu\.show\)\s*,\s*"
        r"\.card\.has-open-dropdown\s*\{([^{}]*)\}",
        css,
        re.S,
    )
    assert match, (
        "expected a rule matching both `.card:has(.dropdown-menu.show)` and "
        "`.card.has-open-dropdown` — the first covers browsers with `:has()`, "
        "the second is driven from static/js/core/utils.js for the rest."
    )
    body = match.group(1)

    assert "overflow: visible" in body, (
        "a card holding an open dropdown must stop clipping, or the menu is "
        "sliced off at the card's edge."
    )

    z_index = re.search(r"z-index:\s*(\d+)", body)
    assert z_index, (
        "the card must be lifted while a menu is open; without a z-index the "
        "next card down the page paints over the un-clipped menu."
    )
    # Must clear sibling cards but stay under the sticky navbar (1030),
    # modals and toasts.
    assert 0 < int(z_index.group(1)) < 1030, (
        f"z-index {z_index.group(1)} is outside the sane range: it has to beat "
        "sibling cards but stay below the sticky navbar at z-index 1030."
    )


def test_card_decorations_are_suppressed_while_unclipped():
    """`::before`/`::after` only read as decorations because the card crops them.

    The glow is sized 200% at -50% and would bleed across the page; the 3px
    accent strip is trimmed at each end by the card's corner arc and cannot
    round itself to match (border-radius on a 3px-tall box scales down to a 3px
    radius, leaving the ends poking out). Both are hover-only, so they sit out
    while the card is unclipped.
    """
    css = STYLES_CSS.read_text(encoding="utf-8")
    match = re.search(
        r"\.card:has\(\.dropdown-menu\.show\)::before\s*,\s*"
        r"\.card:has\(\.dropdown-menu\.show\)::after\s*,\s*"
        r"\.card\.has-open-dropdown::before\s*,\s*"
        r"\.card\.has-open-dropdown::after\s*\{([^{}]*)\}",
        css,
        re.S,
    )
    assert match and "opacity: 0" in match.group(1), (
        "both `.card::before` and `.card::after` must be held at opacity 0 "
        "while the card has an open dropdown — they escape the card box "
        "the moment it stops clipping."
    )

    # These have to win against `.card:hover::before` / `.card:hover::after`,
    # which set opacity to 1. The `.has-open-dropdown` variants only tie with
    # those on specificity, so source order carries them.
    for hover_rule in (".card:hover::before", ".card:hover::after"):
        assert css.index(hover_rule) < match.start(), (
            f"the suppression rule must come after `{hover_rule}` in source "
            "order — the class-based selector only ties with it on specificity."
        )


def test_utils_js_tracks_open_dropdowns():
    """The `:has()`-free fallback: a class toggled from Bootstrap's events."""
    js = UTILS_JS.read_text(encoding="utf-8")

    assert "show.bs.dropdown" in js and "hidden.bs.dropdown" in js, (
        "static/js/core/utils.js must listen for Bootstrap's dropdown "
        "show/hide events to maintain the `has-open-dropdown` class."
    )
    assert "has-open-dropdown" in js, (
        "the listeners must toggle the `has-open-dropdown` class that "
        "styles.css keys the un-clipping rule off."
    )
    assert "closest('.card')" in js, (
        "Bootstrap fires the event on the toggle button, so the handler has "
        "to walk up to the owning card."
    )

    hidden_handler = js.split("hidden.bs.dropdown", 1)[1]
    assert "querySelector('.dropdown-menu.show')" in hidden_handler, (
        "the hide handler must re-read the card rather than clearing the class "
        "outright: a card can hold several dropdowns (the Received Alerts "
        "filter panel holds two), and clicking from one straight to the next "
        "gives no guaranteed ordering between this event and the other menu's "
        "show — clearing blindly re-clips the card under the menu that just "
        "opened."
    )
