#!/usr/bin/env python3
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

"""Guard the mobile layout rules that a stylesheet edit can silently break.

The bug this was written for: inside ``@media (max-width: 575.98px)`` the
standard ``.page-header`` carried ``margin-left/right: -0.125rem``. The header
is normally a direct child of the unpadded ``.page-shell``, so that bleed made
it ~3px wider than the viewport and scrolled the *entire document* sideways on
every page using the standard header — a violation of the project's own
"no horizontal scrolling at >=320px" rule that was easy to miss because the
overflow is only a couple of pixels.

A full-width element cannot have a negative horizontal margin and still fit.
These checks are static (no browser needed) so they run in ordinary CI.
"""

import re
from pathlib import Path

import pytest


STYLES = Path(__file__).resolve().parent.parent / 'static' / 'css' / 'styles.css'

#: Full-bleed layout containers: these span their parent's width, so any
#: negative horizontal margin pushes them past the viewport edge.
FULL_WIDTH_SELECTORS = (
    '.page-header',
    '.page-header-gradient',
    '.page-shell',
)

#: Breakpoints where a few pixels of overflow actually scroll the document.
MOBILE_BREAKPOINTS = ('575.98px', '399.98px', '767.98px')


def _strip_comments(css: str) -> str:
    """Remove ``/* ... */`` comments.

    Required before any selector matching: a comment sitting between two rules
    is captured as part of the following selector, so ``.page-header`` preceded
    by an explanatory comment would never compare equal to ``.page-header``.
    """
    return re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)


def _media_blocks(css: str):
    """Yield (condition, body) for each top-level ``@media`` block."""
    for match in re.finditer(r'@media([^{]+)\{', css):
        start = match.end()
        depth = 1
        index = start
        while index < len(css) and depth:
            if css[index] == '{':
                depth += 1
            elif css[index] == '}':
                depth -= 1
            index += 1
        yield match.group(1).strip(), css[start:index - 1]


def _rules(body: str):
    """Yield (selector, declarations) for each rule in a stylesheet body."""
    for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', body):
        yield match.group(1).strip(), match.group(2)


@pytest.fixture(scope='module')
def css() -> str:
    return _strip_comments(STYLES.read_text(encoding='utf-8'))


def test_full_width_elements_have_no_negative_horizontal_margin_on_mobile(css):
    """A full-width block plus a negative side margin always overflows."""
    offenders = []

    for condition, body in _media_blocks(css):
        if not any(bp in condition for bp in MOBILE_BREAKPOINTS):
            continue
        for selector, declarations in _rules(body):
            targets = [part.strip() for part in selector.split(',')]
            if not any(target in FULL_WIDTH_SELECTORS for target in targets):
                continue
            for prop in ('margin-left', 'margin-right', 'margin-inline-start',
                         'margin-inline-end'):
                found = re.search(
                    rf'(?<![\w-]){prop}\s*:\s*(-[\d.]+\w*)', declarations)
                if found:
                    offenders.append(
                        f'@media {condition} -> {selector} '
                        f'{prop}: {found.group(1)}'
                    )

    assert not offenders, (
        'Full-width elements must not use a negative horizontal margin at '
        'mobile breakpoints — it scrolls the whole document sideways:\n  '
        + '\n  '.join(offenders)
    )


def test_page_header_variants_agree_on_mobile_margins(css):
    """The two header variants must not drift apart again.

    ``.page-header`` grew a bleed that ``.page-header-gradient`` never had, so
    whether a page overflowed depended on which variant it happened to use.
    """
    margins = {'.page-header': set(), '.page-header-gradient': set()}

    for condition, body in _media_blocks(css):
        if not any(bp in condition for bp in MOBILE_BREAKPOINTS):
            continue
        for selector, declarations in _rules(body):
            target = selector.strip()
            if target not in margins:
                continue
            for prop in ('margin-left', 'margin-right'):
                found = re.search(
                    rf'(?<![\w-]){prop}\s*:\s*([^;]+)', declarations)
                if found:
                    margins[target].add(f'{prop}:{found.group(1).strip()}')

    assert margins['.page-header'] == margins['.page-header-gradient'], (
        'The standard and gradient page headers disagree on mobile horizontal '
        f'margins: {margins}'
    )
