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

from __future__ import annotations

"""Structural checks on the docs/ tree: every local link resolves, and every
file is reachable from mkdocs.yml's nav.

A manual audit (2026-08-26) found the doc tree in good shape -- 92 files,
zero broken links, perfect nav coverage -- but nothing enforced that state
going forward; both could silently rot as the tree grows (a renamed file
leaves a dangling link, a new doc never gets added to mkdocs.yml and
becomes unreachable from the published site). These tests pin that
snapshot down as a regression guard.
"""

import re
from pathlib import Path
from typing import Iterator, Set, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"

#: Markdown link/image target: matches both `[text](target)` and
#: `![alt](target)` since the latter is a superset of the former syntax.
_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")

#: Fenced code blocks (``` ... ```) are stripped before link-scanning --
#: docs that show example markdown syntax (e.g. docs/reference/DIAGRAMS.md's
#: "![Diagram Name](path/to/diagram.svg)" embedding example, or Python
#: regex literals in docs/development/AGENTS.md that happen to contain a
#: "](...)" substring) are illustrative text, not real references, and
#: must not be resolved as broken links.
_FENCED_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)

_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "//", "data:")


def _iter_doc_files() -> Iterator[Path]:
    for path in DOCS_DIR.rglob("*.md"):
        yield path


def _local_links(markdown_source: str) -> Iterator[str]:
    """Yield every local (non-external) link target in *markdown_source*,
    with fenced code blocks stripped first so example syntax is never
    mistaken for a real reference."""
    stripped = _FENCED_CODE_BLOCK_RE.sub("", markdown_source)
    for match in _LINK_RE.finditer(stripped):
        link = match.group(1)
        if link.startswith(_EXTERNAL_PREFIXES):
            continue
        yield link


def _broken_links() -> Iterator[Tuple[Path, str]]:
    for path in _iter_doc_files():
        content = path.read_text(encoding="utf-8", errors="ignore")
        for link in _local_links(content):
            target_part = link.split("#", 1)[0]
            if not target_part:
                continue  # pure same-page anchor, e.g. "#some-heading"
            target = (path.parent / target_part).resolve()
            if not target.exists():
                yield path.relative_to(REPO_ROOT), link


def test_no_broken_local_links_in_docs() -> None:
    offenders = list(_broken_links())
    assert not offenders, (
        "These docs/*.md files link to a local path that doesn't exist "
        "(external http(s)/mailto links are not checked):\n"
        + "\n".join(f"  {path} -> {link}" for path, link in offenders)
    )


def test_link_checker_actually_scans_something() -> None:
    """Guards the check above: if DOCS_DIR were ever empty or the glob
    broke, the assertion in test_no_broken_local_links_in_docs would
    trivially pass with nothing to check -- silently disabling this
    protection. Pin a floor so that kind of regression is loud."""
    doc_files = list(_iter_doc_files())
    assert len(doc_files) >= 50, (
        f"Expected at least 50 files under docs/, found {len(doc_files)}. "
        "If docs/ was restructured, update DOCS_DIR/this test too -- "
        "don't just lower the count."
    )


class _NavOnlyLoader(yaml.SafeLoader):
    """SafeLoader that tolerates mkdocs.yml's `!!python/name:...` tags
    (used by markdown_extensions config, e.g. emoji_index/emoji_generator)
    by ignoring them instead of trying to import the referenced object --
    only the plain-scalar `nav:` tree is needed here."""


_NavOnlyLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:", lambda loader, suffix, node: None
)


def _mkdocs_nav_paths() -> Set[str]:
    """Every docs/*.md path referenced anywhere in mkdocs.yml's nav tree,
    as paths relative to docs/."""
    with (REPO_ROOT / "mkdocs.yml").open(encoding="utf-8") as f:
        config = yaml.load(f, Loader=_NavOnlyLoader)

    paths: Set[str] = set()

    def _walk(node) -> None:
        if isinstance(node, str):
            if node.endswith(".md"):
                paths.add(node)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                _walk(value)

    _walk(config.get("nav", []))
    return paths


def test_every_doc_file_is_reachable_from_mkdocs_nav() -> None:
    nav_paths = _mkdocs_nav_paths()
    actual_paths = {
        str(path.relative_to(DOCS_DIR)).replace("\\", "/")
        for path in _iter_doc_files()
    }

    orphaned = sorted(actual_paths - nav_paths)
    assert not orphaned, (
        "These docs/*.md files exist on disk but aren't reachable from "
        "mkdocs.yml's nav -- they won't appear on the published site "
        "(add them to the nav, or delete them if they're stale):\n"
        + "\n".join(f"  {path}" for path in orphaned)
    )


def test_mkdocs_nav_never_points_at_a_missing_file() -> None:
    nav_paths = _mkdocs_nav_paths()
    actual_paths = {
        str(path.relative_to(DOCS_DIR)).replace("\\", "/")
        for path in _iter_doc_files()
    }

    missing = sorted(nav_paths - actual_paths)
    assert not missing, (
        "mkdocs.yml's nav references these docs/*.md paths, but the "
        "files don't exist (renamed or deleted without updating the "
        "nav):\n"
        + "\n".join(f"  {path}" for path in missing)
    )
