"""File discovery, bucket classification and line counting.

Files are enumerated with ``git ls-files`` when the tree is a git checkout —
that respects ``.gitignore`` for free and keeps build artefacts, virtualenvs
and caches out of the counts — falling back to a filtered directory walk
otherwise.

Every counted file lands in exactly one bucket:

``project``    first-party source — Python, templates, JS, CSS, shell, SQL.
``docs``       Markdown and plain-text documentation.
``vendored``   third-party code shipped in-tree (``static/vendor/``,
               ``node_modules/``, ``*.min.js``/``*.min.css``).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Extension -> display language. Files with any other extension are counted
# toward the file totals but not the line totals (binaries, images, fonts).
LANGUAGES: Dict[str, str] = {
    '.py': 'Python',
    '.js': 'JavaScript',
    '.html': 'HTML',
    '.css': 'CSS',
    '.yml': 'YAML',
    '.yaml': 'YAML',
    '.md': 'Markdown',
    '.sh': 'Shell',
    '.json': 'JSON',
    '.sql': 'SQL',
    '.txt': 'Text',
    '.xml': 'XML',
    '.svg': 'SVG',
    '.service': 'systemd',
    '.target': 'systemd',
    '.timer': 'systemd',
}

# Path fragments that mark a file as third-party rather than ours.
VENDOR_DIRS: Tuple[str, ...] = ('static/vendor/', 'node_modules/')
VENDOR_SUFFIXES: Tuple[str, ...] = ('.min.js', '.min.css', '.js.map', '.css.map')

# Directories skipped by the non-git fallback walk.
EXCLUDE_DIRS = frozenset({
    '.git', '__pycache__', 'node_modules', '.pytest_cache', '.mypy_cache',
    '.ruff_cache', 'venv', 'env', '.venv', 'dist', 'build', '.eggs',
})

BUCKETS: Tuple[str, ...] = ('project', 'docs', 'vendored')

_HASH_COMMENT = frozenset({'.py', '.sh', '.yml', '.yaml', '.service', '.target', '.timer'})
_SLASH_COMMENT = frozenset({'.js', '.css', '.sql'})
_MARKUP_COMMENT = frozenset({'.html', '.xml', '.svg'})


def repo_root() -> Path:
    """Return the repository root (three levels up from this module)."""
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _git_tracked_files(root: Path) -> Optional[List[Path]]:
    """List tracked files via git, or None when git is unavailable."""
    try:
        result = subprocess.run(
            ['git', '-C', str(root), 'ls-files', '-z'],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug('git ls-files unavailable (%s); falling back to walk', exc)
        return None

    if result.returncode != 0:
        logger.debug('git ls-files exited %s; falling back to walk', result.returncode)
        return None

    names = result.stdout.decode('utf-8', errors='replace').split('\0')
    return [root / name for name in names if name]


def _walked_files(root: Path) -> List[Path]:
    """List files by walking the tree, skipping build and cache directories."""
    found: List[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError as exc:
            logger.debug('Skipping unreadable directory %s: %s', current, exc)
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in EXCLUDE_DIRS:
                    stack.append(entry)
            elif entry.is_file():
                found.append(entry)
    return found


def discover_files(root: Path) -> Tuple[List[Path], str]:
    """Return ``(files, source)`` where source is ``'git'`` or ``'walk'``."""
    tracked = _git_tracked_files(root)
    if tracked is not None:
        # ls-files also lists paths deleted in the working tree.
        return [path for path in tracked if path.is_file()], 'git'
    return _walked_files(root), 'walk'


def classify(rel_path: str) -> str:
    """Return the bucket ('project', 'docs' or 'vendored') for a path."""
    normalized = rel_path.replace('\\', '/')
    if any(fragment in normalized for fragment in VENDOR_DIRS):
        return 'vendored'
    if normalized.endswith(VENDOR_SUFFIXES):
        return 'vendored'
    if normalized.endswith('.md') or normalized.endswith('.txt'):
        return 'docs'
    return 'project'


# ---------------------------------------------------------------------------
# Line counting
# ---------------------------------------------------------------------------

def _count_python(lines: List[str]) -> Tuple[int, int]:
    """Count (code, comments) for Python, handling one-line docstrings."""
    code = comments = 0
    in_docstring = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if in_docstring:
            comments += 1
            if stripped.endswith('"""') or stripped.endswith("'''"):
                in_docstring = False
        elif stripped.startswith('#'):
            comments += 1
        elif stripped.startswith('"""') or stripped.startswith("'''"):
            comments += 1
            delimiter = stripped[:3]
            # A one-line docstring opens and closes on the same line, so it
            # must not put the counter into block mode.
            if not (len(stripped) >= 6 and stripped.endswith(delimiter)):
                in_docstring = True
        else:
            code += 1
    return code, comments


def _count_block_commented(lines: List[str], opener: str, closer: str,
                           line_prefixes: Tuple[str, ...]) -> Tuple[int, int]:
    """Count (code, comments) for languages with ``opener``/``closer`` blocks."""
    code = comments = 0
    in_block = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if in_block:
            comments += 1
            if closer in stripped:
                in_block = False
        elif stripped.startswith(line_prefixes):
            comments += 1
        elif stripped.startswith(opener):
            comments += 1
            if closer not in stripped:
                in_block = True
        else:
            code += 1
    return code, comments


def count_lines(path: Path, suffix: str) -> Tuple[int, int, int]:
    """Count ``(total, code, comment)`` lines for a single file.

    Blank lines are neither code nor comment; the caller derives them as
    ``total - code - comments``.
    """
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
    except OSError as exc:
        logger.debug('Unable to read %s: %s', path, exc)
        return 0, 0, 0

    lines = text.splitlines()
    total = len(lines)

    if suffix == '.py':
        code, comments = _count_python(lines)
    elif suffix in _HASH_COMMENT:
        non_blank = [line.strip() for line in lines if line.strip()]
        comments = sum(1 for line in non_blank if line.startswith('#'))
        code = len(non_blank) - comments
    elif suffix in _SLASH_COMMENT:
        code, comments = _count_block_commented(lines, '/*', '*/', ('//', '--'))
    elif suffix in _MARKUP_COMMENT:
        code, comments = _count_block_commented(lines, '<!--', '-->', ())
    else:
        code = sum(1 for line in lines if line.strip())
        comments = 0

    return total, code, comments


__all__ = [
    'BUCKETS',
    'EXCLUDE_DIRS',
    'LANGUAGES',
    'VENDOR_DIRS',
    'VENDOR_SUFFIXES',
    'classify',
    'count_lines',
    'discover_files',
    'repo_root',
]
