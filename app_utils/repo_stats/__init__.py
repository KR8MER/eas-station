"""Repository statistics computed live from the working tree.

This replaces the old ``scripts/generate_repo_stats.py`` + committed
``static/repo_stats.html`` blob, which went stale the moment anyone pushed a
commit and reported numbers that did not describe this project:

* ``@app.route``/``@bp.route`` were the only route decorators the old regex
  matched, so every named blueprint (``@security_bp.route`` and ~30 siblings)
  was invisible — it reported 239 routes when the app serves well over 500.
* Third-party assets under ``static/vendor/`` were counted as project code.
  They are roughly two thirds of the tracked files and half of the tracked
  lines, so "550,959 lines of code" was mostly minified Bootstrap and
  Chart.js.

Everything here is derived on demand and cached for a short TTL, so the page
can never drift from the tree it is describing. See :mod:`.scanner` for how
files are found and bucketed, and :mod:`.inventory` for routes and components.

Usage::

    from app_utils.repo_stats import get_stats

    stats = get_stats(app=current_app)      # cached up to CACHE_TTL_SECONDS
    stats = get_stats(app=current_app, refresh=True)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .inventory import count_components, routes_from_source, routes_from_url_map
from .scanner import (
    BUCKETS,
    EXCLUDE_DIRS,
    LANGUAGES,
    LANGUAGE_GLYPHS,
    LANGUAGE_LOGOS,
    VENDOR_DIRS,
    VENDOR_SUFFIXES,
    classify,
    count_lines,
    discover_files,
    git_history,
    repo_root,
)

logger = logging.getLogger(__name__)

#: How long a computed snapshot stays warm before the next request recomputes.
CACHE_TTL_SECONDS = 600

_cache_lock = threading.Lock()
_cache: Dict[str, object] = {'expires_at': 0.0, 'stats': None}


def _empty_bucket() -> Dict[str, object]:
    return {
        'files': 0,
        'total': 0,
        'code': 0,
        'comments': 0,
        'blank': 0,
        'by_language': defaultdict(
            lambda: {'files': 0, 'total': 0, 'code': 0, 'comments': 0}
        ),
    }


def _finalize(bucket: Dict[str, object]) -> Dict[str, object]:
    """Derive blank lines and turn the language map into a sorted list.

    Each language carries its brand ``logo`` filename and a Font Awesome
    ``glyph`` fallback so templates never have to hardcode either.
    """
    bucket['blank'] = bucket['total'] - bucket['code'] - bucket['comments']
    languages = bucket.pop('by_language')
    bucket['languages'] = sorted(
        (
            {
                'name': name,
                'logo': LANGUAGE_LOGOS.get(name),
                'glyph': LANGUAGE_GLYPHS.get(name, 'fas fa-file-code'),
                **values,
            }
            for name, values in languages.items()
        ),
        key=lambda item: item['total'],
        reverse=True,
    )
    return bucket


def compute_stats(app=None, root: Optional[Path] = None) -> Dict[str, object]:
    """Analyse the repository and return a statistics snapshot.

    Args:
        app: Optional Flask app. When given, routes are read from its live
            URL map instead of being guessed from source.
        root: Optional repository root override (used by tests).

    Returns:
        A JSON-serialisable dict of statistics.
    """
    started = time.monotonic()
    base = Path(root) if root is not None else repo_root()

    files, source = discover_files(base)
    buckets = {name: _empty_bucket() for name in BUCKETS}
    directories = set()
    total_files = 0

    for path in files:
        try:
            rel = path.relative_to(base).as_posix()
        except ValueError:
            continue

        total_files += 1
        parent = str(Path(rel).parent)
        directories.add('.' if parent == '.' else parent)

        bucket = buckets[classify(rel)]
        bucket['files'] += 1

        suffix = path.suffix.lower()
        language = LANGUAGES.get(suffix)
        if language is None:
            continue

        total, code, comments = count_lines(path, suffix)
        bucket['total'] += total
        bucket['code'] += code
        bucket['comments'] += comments

        entry = bucket['by_language'][language]
        entry['files'] += 1
        entry['total'] += total
        entry['code'] += code
        entry['comments'] += comments

    routes = routes_from_url_map(app) if app is not None else None
    if not routes or not routes['total']:
        routes = routes_from_source(base)

    return {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
        'file_source': source,
        'total_files': total_files,
        'directories': len(directories),
        'buckets': {name: _finalize(buckets[name]) for name in BUCKETS},
        'routes': routes,
        'components': count_components(base, files),
        'git_history': git_history(base) if source == 'git' else None,
        'duration_ms': round((time.monotonic() - started) * 1000, 1),
    }


def get_stats(app=None, refresh: bool = False) -> Dict[str, object]:
    """Return cached statistics, recomputing when stale or ``refresh=True``."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get('stats')
        if not refresh and cached is not None and now < _cache['expires_at']:
            return cached  # type: ignore[return-value]

    stats = compute_stats(app=app)

    with _cache_lock:
        _cache['stats'] = stats
        _cache['expires_at'] = time.monotonic() + CACHE_TTL_SECONDS
    return stats


def invalidate_cache() -> None:
    """Drop the cached snapshot (used by tests and the Recalculate button)."""
    with _cache_lock:
        _cache['stats'] = None
        _cache['expires_at'] = 0.0


__all__ = [
    'BUCKETS',
    'CACHE_TTL_SECONDS',
    'EXCLUDE_DIRS',
    'LANGUAGES',
    'LANGUAGE_GLYPHS',
    'LANGUAGE_LOGOS',
    'VENDOR_DIRS',
    'VENDOR_SUFFIXES',
    'classify',
    'compute_stats',
    'count_components',
    'count_lines',
    'discover_files',
    'get_stats',
    'git_history',
    'invalidate_cache',
    'repo_root',
    'routes_from_source',
    'routes_from_url_map',
]
