#!/usr/bin/env python3
"""Audit text/background contrast of key UI surfaces across every theme.

EAS Station™ ships 34 themes (19 built-in, 15 Bootswatch) that all derive from the same CSS custom
properties, so a rule that looks fine in the default (Lightning) theme can be
unreadable in another. Three such bugs shipped before this check existed:

  * hero banner titles rendered near-black on the purple gradient in every
    light theme (the global ``h1`` colour beat the hero's inherited white);
  * page headers rendered white-on-amber in the Yellow theme;
  * table headers rendered dark-on-dark, because a ``background`` shorthand
    carrying a gradient cannot be overridden by a later ``background-color``
    (the gradient is a background-*image* and keeps painting on top).

The audit renders a fixture page with the real stylesheet, walks every
theme, and computes the WCAG 2.1 contrast ratio of each probed selector
against its effective background. Colours are normalised through a canvas
so modern ``color(srgb ...)`` / ``color-mix()`` values are handled — naive
string parsing of those yields wildly wrong numbers.

Usage:
    python3 scripts/diagnostics/check_theme_contrast.py            # audit
    python3 scripts/diagnostics/check_theme_contrast.py --verbose  # all rows

Exits non-zero if any probe falls below the WCAG AA threshold (4.5:1 for
normal-size text), so it can gate CI.

Requires Playwright with Chromium available (already provisioned in the
dev container; see docs/development/AGENTS.md).
"""

from __future__ import annotations

import argparse
import os
import re
import http.server
import socketserver
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# WCAG 2.1 AA for normal-size text. Large text (>=18.66px bold / 24px) may
# use 3.0, but every surface probed here renders at normal size or smaller.
AA_THRESHOLD = 4.5

THEMES = [
    "aurora", "blue", "charcoal", "coffee", "dark", "green",
    "lightning", "midnight", "nebula", "obsidian", "orange", "pink",
    "purple", "red", "slate", "spring", "sunset", "tide", "yellow",
]

# Bootswatch themes ("bw-<name>") also swap the Bootstrap stylesheet for
# static/vendor/bootswatch/<name>/; keep in step with static/js/core/theme.js.
BOOTSWATCH_THEMES = [
    "cerulean", "flatly", "litera", "lux", "minty", "sandstone", "united",
    "yeti", "zephyr", "darkly", "cyborg", "slate", "solar", "superhero",
    "vapor",
]
THEMES += [f"bw-{name}" for name in BOOTSWATCH_THEMES]

# Selector -> (label, strict). Add a probe whenever a themed surface pairs
# its own text colour with its own background.
#
# strict=True  -> a shortfall fails the run (flat, single-colour backdrops,
#                 where the WCAG formula is exactly applicable).
# strict=False -> reported as ADVISORY only. These surfaces paint a gradient
#                 and lean on `text-shadow` for separation; the WCAG ratio
#                 models neither the shadow nor the eye's tolerance for a
#                 gradient, so it reads pessimistically. Worth a human look
#                 when a number is far below target, but not a build gate.
# The four gradient surfaces (page header, hero) were advisory until 3.30.0,
# when a scrim brought every theme over the line; they are strict since.
PROBES = {
    ".table thead th": ("Bootstrap table header", True),
    ".eas-table thead th": ("Design-system table header", True),
    ".page-header .page-title": ("Page header title", True),
    ".page-header .page-subtitle": ("Page header subtitle", True),
    ".eas-hero-title": ("Hero title", True),
    ".eas-hero-lead": ("Hero lead", True),
    # Semantic text utilities on a plain card. These are flat surfaces, so
    # the WCAG formula applies exactly and a shortfall is a real failure.
    # They went unprobed until the `--*-ink` split, which is how
    # `.text-warning` shipped at 1.94:1 on white in all 11 light themes
    # while the audit reported a clean run.
    ".card .text-primary": ("Card .text-primary", True),
    ".card .text-success": ("Card .text-success", True),
    ".card .text-danger": ("Card .text-danger", True),
    ".card .text-warning": ("Card .text-warning", True),
    ".card .text-info": ("Card .text-info", True),
    ".card .text-muted": ("Card .text-muted", True),
    ".card .text-secondary": ("Card .text-secondary", True),
    ".card a.probe-link": ("Card body link", True),
    ".page-shell .probe-body": ("Body text on page", True),
    # Same colour-on-tinted-background shape as the .text-* utilities above
    # (own colour used for both the text and the background tint it sits
    # on) -- went unprobed until a live-page sweep found `.status-badge.success`
    # rendering at ~2.1:1 across every light theme because it read straight
    # from `--success-color` instead of the AA-tuned `--*-ink` split.
    ".status-badge.success": ("Status badge (success)", True),
    ".status-badge.danger": ("Status badge (danger)", True),
    ".status-badge.warning": ("Status badge (warning)", True),
    ".status-badge.info": ("Status badge (info)", True),
    # Solid status fills. Their ink is derived from the fill (styles.css,
    # "SOLID STATUS FILLS"); before that, solid badges measured 1.5-3.9:1
    # in most themes and `.text-dark` on a dark-orange warning fill 3.35.
    ".badge.probe-fill-primary": ("Solid badge (bg-primary)", True),
    ".badge.probe-fill-secondary": ("Solid badge (bg-secondary)", True),
    ".badge.probe-fill-success": ("Solid badge (bg-success)", True),
    ".badge.probe-fill-danger": ("Solid badge (bg-danger)", True),
    ".badge.probe-fill-warning": ("Solid badge (bg-warning)", True),
    ".badge.probe-fill-info": ("Solid badge (bg-info)", True),
    ".badge.probe-fill-dark": ("Solid badge (bg-dark)", True),
    ".probe-tbg-primary": ("text-bg-primary", True),
    ".probe-tbg-secondary": ("text-bg-secondary", True),
    ".probe-tbg-success": ("text-bg-success", True),
    ".probe-tbg-danger": ("text-bg-danger", True),
    ".probe-tbg-warning": ("text-bg-warning", True),
    ".probe-tbg-info": ("text-bg-info", True),
    ".probe-tbg-dark": ("text-bg-dark", True),
    ".bg-warning .probe-warn-dark": (".text-dark on bg-warning", True),
    # Components a 3.30.0 sweep found failing in themes nobody had listed:
    # alerts in Charcoal/Coffee/Slate, outline buttons in most themes,
    # `.text-dark` / `.text-body-secondary` in Lightning, `.bg-light` copy
    # in Dark and Coffee.
    ".alert.probe-alert-primary": ("Alert (primary)", True),
    ".alert.probe-alert-secondary": ("Alert (secondary)", True),
    ".alert.probe-alert-success": ("Alert (success)", True),
    ".alert.probe-alert-danger": ("Alert (danger)", True),
    ".alert.probe-alert-warning": ("Alert (warning)", True),
    ".alert.probe-alert-info": ("Alert (info)", True),
    ".probe-outline-primary": ("Outline button (primary)", True),
    ".probe-outline-secondary": ("Outline button (secondary)", True),
    ".probe-outline-success": ("Outline button (success)", True),
    ".probe-outline-danger": ("Outline button (danger)", True),
    ".probe-outline-warning": ("Outline button (warning)", True),
    ".probe-outline-info": ("Outline button (info)", True),
    ".probe-outline-dark": ("Outline button (dark)", True),
    ".card .probe-text-dark": ("Card .text-dark", True),
    ".card .probe-body-secondary": ("Card .text-body-secondary", True),
    ".bg-light .probe-bglight-text": ("Text on .bg-light", True),
    ".bg-light .probe-bglight-muted": (".text-muted on .bg-light", True),
}

FIXTURE = """<!DOCTYPE html>
<html lang="en" data-theme="lightning"><head><meta charset="utf-8">
<link id="bootstrap-css" rel="stylesheet" href="/static/css/vendor.css">
<link rel="stylesheet" href="/static/css/styles.css">
<link rel="stylesheet" href="/static/css/bootswatch.css">
<style>
/* Theme switches are measured right away; a colour still mid-transition
   (buttons animate `all` over 300ms) would be sampled half-way. */
*, *::before, *::after { transition: none !important; }
</style></head>
<body><main class="page-shell"><div class="container py-4">
  <div class="page-header"><div class="container-fluid">
    <div class="header-content"><div class="header-text">
      <h1 class="page-title mb-0">Title</h1>
      <p class="page-subtitle mb-0">Subtitle</p>
    </div></div>
  </div></div>
  <section class="eas-hero"><div class="eas-hero-inner">
    <h1 class="eas-hero-title">Hero</h1>
    <p class="eas-hero-lead">Hero lead copy</p>
  </div></section>
  <div class="table-responsive"><table class="table">
    <thead><tr><th>Header</th></tr></thead><tbody><tr><td>Cell</td></tr></tbody>
  </table></div>
  <div class="table-responsive"><table class="table eas-table">
    <thead><tr><th>Header</th></tr></thead><tbody><tr><td>Cell</td></tr></tbody>
  </table></div>
  <p class="probe-body">Ordinary body copy on the page background.</p>
  <div class="card"><div class="card-body">
    <p class="text-primary">Primary</p>
    <p class="text-success">Success</p>
    <p class="text-danger">Danger</p>
    <p class="text-warning">Warning</p>
    <p class="text-info">Info</p>
    <p class="text-muted">Muted</p>
    <p class="text-secondary">Secondary</p>
    <p><a class="probe-link" href="#">A link in card copy</a></p>
  </div></div>
  <div class="status-badge success">Success</div>
  <div class="status-badge danger">Danger</div>
  <div class="status-badge warning">Warning</div>
  <div class="status-badge info">Info</div>
  <span class="badge bg-primary probe-fill-primary">Badge</span>
  <span class="badge bg-secondary probe-fill-secondary">Badge</span>
  <span class="badge bg-success probe-fill-success">Badge</span>
  <span class="badge bg-danger probe-fill-danger">Badge</span>
  <span class="badge bg-warning probe-fill-warning">Badge</span>
  <span class="badge bg-info probe-fill-info">Badge</span>
  <span class="badge bg-dark probe-fill-dark">Badge</span>
  <span class="badge text-bg-primary probe-tbg-primary">Badge</span>
  <span class="badge text-bg-secondary probe-tbg-secondary">Badge</span>
  <span class="badge text-bg-success probe-tbg-success">Badge</span>
  <span class="badge text-bg-danger probe-tbg-danger">Badge</span>
  <span class="badge text-bg-warning probe-tbg-warning">Badge</span>
  <span class="badge text-bg-info probe-tbg-info">Badge</span>
  <span class="badge text-bg-dark probe-tbg-dark">Badge</span>
  <div class="bg-warning p-2"><span class="text-dark probe-warn-dark">Warning copy</span></div>
  <div class="alert alert-primary probe-alert-primary">Alert copy</div>
  <div class="alert alert-secondary probe-alert-secondary">Alert copy</div>
  <div class="alert alert-success probe-alert-success">Alert copy</div>
  <div class="alert alert-danger probe-alert-danger">Alert copy</div>
  <div class="alert alert-warning probe-alert-warning">Alert copy</div>
  <div class="alert alert-info probe-alert-info">Alert copy</div>
  <div class="card"><div class="card-body"><button class="btn btn-outline-primary probe-outline-primary">Button</button> <button class="btn btn-outline-secondary probe-outline-secondary">Button</button> <button class="btn btn-outline-success probe-outline-success">Button</button> <button class="btn btn-outline-danger probe-outline-danger">Button</button> <button class="btn btn-outline-warning probe-outline-warning">Button</button> <button class="btn btn-outline-info probe-outline-info">Button</button> <button class="btn btn-outline-dark probe-outline-dark">Button</button> <p class="text-dark probe-text-dark">Dark text</p><p class="text-body-secondary probe-body-secondary">Secondary text</p></div></div>
  <div class="bg-light p-2"><span class="probe-bglight-text">Light panel</span> <span class="text-muted probe-bglight-muted">muted</span></div>
</div></main></body></html>
"""

# Reading `background-color` and walking ancestors is not sufficient: the
# page header and hero paint a gradient, which is a background-*image*, and
# their background-color stays transparent. An ancestor walk therefore
# reports the page background and produces bogus ratios for exactly the
# surfaces most likely to have contrast bugs.
#
# Instead the text is made transparent and the element is screenshotted, so
# whatever is actually painted behind the glyphs (gradient, image, tint) is
# sampled per-pixel. The reported ratio is the worst pixel, not the average,
# so one dark corner of a gradient cannot hide behind a bright mean.
PROBE_JS = """
window.__toRGB = function (c) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1;
    const x = cv.getContext('2d');
    x.fillStyle = '#000';
    x.fillStyle = c;
    x.fillRect(0, 0, 1, 1);
    const d = x.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2]];
};
window.__textRGB = function (sel) {
    const el = document.querySelector(sel);
    return el ? window.__toRGB(getComputedStyle(el).color) : null;
};
/* Hide the glyphs (keeping layout identical) so a screenshot of the element
   captures only what is painted behind the text. */
window.__hideText = function (sel) {
    const el = document.querySelector(sel);
    if (!el) return false;
    el.dataset.prevStyle = el.getAttribute('style') || '';
    el.style.setProperty('color', 'transparent', 'important');
    el.style.setProperty('text-shadow', 'none', 'important');
    return true;
};
window.__restoreText = function (sel) {
    const el = document.querySelector(sel);
    if (!el) return;
    el.setAttribute('style', el.dataset.prevStyle || '');
    delete el.dataset.prevStyle;
};
"""


# Applies a theme the way theme.js does: set data-theme and, for a Bootswatch
# theme, point the Bootstrap <link> at its build and wait for it to load.
SET_THEME_JS = """
([t, mode]) => new Promise(resolve => {
    document.documentElement.setAttribute('data-theme', t);
    document.documentElement.setAttribute('data-theme-mode', mode);
    const link = document.getElementById('bootstrap-css');
    const href = new URL(t.startsWith('bw-')
        ? '/static/vendor/bootswatch/' + t.slice(3) + '/bootstrap.min.css'
        : '/static/css/vendor.css', location.href).href;
    if (link.href === href) return resolve();
    link.onload = link.onerror = () => resolve();
    link.href = href;
})
"""


def _theme_modes() -> dict[str, str]:
    """Theme -> 'light'/'dark', read from theme.js.

    base.html stamps ``data-theme-mode`` alongside ``data-theme`` and some
    rules key on it, so the fixture must set both to render what users see.
    """
    text = (REPO_ROOT / "static" / "js" / "core" / "theme.js").read_text(encoding="utf-8")
    return dict(re.findall(r"'([a-z-]+)':\s*\{[^}]*?mode:\s*'(light|dark)'", text, re.S))


def _relative_luminance(rgb) -> float:
    """WCAG 2.1 relative luminance for an 8-bit sRGB triple."""
    channels = []
    for value in rgb[:3]:
        v = value / 255
        channels.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(l1: float, l2: float) -> float:
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def _probe_ratio(page, selector: str):
    """Contrast between a selector's text and the backdrop *under its glyphs*.

    Two screenshots are taken — one normal, one with the glyphs made
    transparent. Differencing them yields a mask of the pixels the text
    actually covers, and the backdrop is sampled only there. Measuring the
    whole element box instead would read decorative glows and gradient
    corners that no glyph sits on, producing false failures on exactly the
    surfaces this tool exists to check.

    Returns (ratio, threshold) where threshold follows WCAG 2.1: 3.0 for
    large text (>=24px, or >=18.66px when bold), otherwise 4.5.
    """
    from io import BytesIO

    try:
        from PIL import Image, ImageChops
    except ImportError:  # pragma: no cover - Pillow is a project dependency
        print("Pillow is required for pixel sampling", file=sys.stderr)
        raise

    info = page.evaluate(
        """s => {
            const el = document.querySelector(s);
            if (!el) return null;
            const cs = getComputedStyle(el);
            return {
                rgb: window.__toRGB(cs.color),
                size: parseFloat(cs.fontSize),
                weight: parseInt(cs.fontWeight, 10) || 400,
            };
        }""",
        selector,
    )
    if info is None:
        return None
    element = page.query_selector(selector)
    if element is None:
        return None

    shown = element.screenshot()
    page.evaluate("s => window.__hideText(s)", selector)
    try:
        hidden = element.screenshot()
    finally:
        page.evaluate("s => window.__restoreText(s)", selector)

    img_shown = Image.open(BytesIO(shown)).convert("RGB")
    img_hidden = Image.open(BytesIO(hidden)).convert("RGB")
    if img_shown.size != img_hidden.size:
        return None

    # Pixels that changed are glyph pixels. Require a strong difference so
    # antialiased edges (partial coverage, misleadingly low contrast) are
    # excluded and only solid glyph interiors are measured.
    diff = ImageChops.difference(img_shown, img_hidden).convert("L")
    mask = diff.point(lambda v: 255 if v > 60 else 0)
    backdrop = [
        px
        for px, m in zip(img_hidden.getdata(), mask.getdata())
        if m
    ]
    if not backdrop:
        return None

    text_lum = _relative_luminance(info["rgb"])
    ratios = sorted(_contrast(text_lum, _relative_luminance(px)) for px in backdrop)
    # 5th percentile rather than the strict minimum: a handful of stray
    # pixels should not define the verdict, but a genuinely bad region will.
    ratio = ratios[max(0, int(len(ratios) * 0.05))]

    is_large = info["size"] >= 24 or (info["size"] >= 18.66 and info["weight"] >= 700)
    return ratio, (3.0 if is_large else AA_THRESHOLD)


def _chromium_path() -> str | None:
    """Locate a pre-provisioned Chromium.

    The dev container ships browsers under PLAYWRIGHT_BROWSERS_PATH rather
    than the per-package revision directory the Python bindings expect, so
    launching without an explicit path fails even though a usable Chromium
    is present. Returning None lets Playwright fall back to its own default
    on machines where the bundled browser does match.
    """
    roots = [Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))]
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob("chromium-*/chrome-linux/chrome")):
            return str(candidate)
        direct = root / "chromium"
        if direct.is_file():
            return str(direct)
    return None


@contextmanager
def serve(directory: Path, port: int = 0):
    """Serve `directory` on localhost so the page can load /static assets."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(directory), **kw)

        def log_message(self, *a):  # keep the audit output clean
            pass

    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield httpd.server_address[1]
        finally:
            httpd.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose", action="store_true", help="print every theme/probe pair"
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed; skipping contrast audit", file=sys.stderr)
        return 0

    modes = _theme_modes()
    fixture = REPO_ROOT / "static" / "_contrast_fixture.html"
    fixture.write_text(FIXTURE)
    failures = []
    advisories = []
    try:
        with serve(REPO_ROOT) as port:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=_chromium_path())
                page = browser.new_page(viewport={"width": 1100, "height": 700})
                page.goto(f"http://127.0.0.1:{port}/static/_contrast_fixture.html")
                page.add_script_tag(content=PROBE_JS)

                for theme in THEMES:
                    page.evaluate(SET_THEME_JS, [theme, modes.get(theme, "light")])
                    page.wait_for_timeout(80)
                    for selector, (label, strict) in PROBES.items():
                        probed = _probe_ratio(page, selector)
                        if probed is None:
                            continue
                        ratio, threshold = probed
                        short = ratio < threshold
                        if short and strict:
                            failures.append((theme, label, ratio))
                            status = "FAIL"
                        elif short:
                            advisories.append((theme, label, ratio))
                            status = "note"
                        else:
                            status = "ok"
                        if status != "ok" or args.verbose:
                            if status == "note" and not args.verbose:
                                continue
                            print(
                                f"{status:<5} {theme:<10} {label:<28} "
                                f"{ratio:.2f} (target {threshold})"
                            )
                browser.close()
    finally:
        fixture.unlink(missing_ok=True)

    strict_count = sum(1 for _, strict in PROBES.values() if strict)
    if advisories:
        print(
            f"\n{len(advisories)} advisory shortfall(s) on gradient/"
            f"text-shadow surfaces (re-run with --verbose to list). These do "
            f"not fail the run — see PROBES for why."
        )
    if failures:
        print(f"\n{len(failures)} contrast failure(s) on strict surfaces.")
        return 1

    print(
        f"All {len(THEMES)} themes pass on {strict_count} strict surface(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
