"""Utilities for tracking and resolving the application's release version."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple


_ROOT = Path(__file__).resolve().parents[1]
_VERSION_PATH = _ROOT / "VERSION"


def _get_version_file_state() -> Tuple[Optional[float], bool]:
    """Return the VERSION file modification time and existence flag.

    The ``exists`` flag differentiates between a missing VERSION file and a
    zero-length file on disk.  ``mtime`` is returned separately so cache keys
    change when the file is rewritten even if its size stays the same.
    """

    try:
        stat_result = _VERSION_PATH.stat()
    except FileNotFoundError:
        return None, False
    return stat_result.st_mtime, True


@lru_cache(maxsize=4)
def _resolve_version(version_state: Tuple[Optional[float], bool]) -> str:
    """Resolve the active version string using the provided cache key.

    ``version_state`` is the tuple returned by :func:`_get_version_file_state`.
    By keying on the VERSION file metadata we invalidate the cache whenever the
    file is rewritten while the process is running (for example after a config
    reload or when the VERSION file is updated on disk).
    """

    mtime, exists = version_state
    if not exists:
        return "0.0.0"

    try:
        return _VERSION_PATH.read_text(encoding="utf-8").strip() or "0.0.0"
    except FileNotFoundError:
        return "0.0.0"


def get_current_version() -> str:
    """Return the effective application version.

    The resolver reads the repository ``VERSION`` manifest and falls back to
    ``"0.0.0"`` when no explicit version is available.  The helper keeps a small
    cache that automatically invalidates when the VERSION file metadata changes
    so deployments pick up the new version without needing a full process
    restart.
    """

    version_state = _get_version_file_state()
    return _resolve_version(version_state)


__all__ = ["get_current_version"]
