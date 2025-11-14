"""Utilities for tracking and resolving the application's release version."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple


_ROOT = Path(__file__).resolve().parents[1]
_VERSION_PATH = _ROOT / "VERSION"
_GIT_DIR = _ROOT / ".git"


@lru_cache(maxsize=1)
def _resolve_git_directory() -> Optional[Path]:
    """Return the filesystem path to the active git metadata directory."""

    if _GIT_DIR.is_dir():
        return _GIT_DIR

    if _GIT_DIR.is_file():
        try:
            gitdir_record = _GIT_DIR.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None

        if gitdir_record.startswith("gitdir:"):
            git_dir_path = gitdir_record.split(":", 1)[1].strip()
            candidate = Path(git_dir_path)
            if not candidate.is_absolute():
                candidate = (_GIT_DIR.parent / candidate).resolve()
            if candidate.exists():
                return candidate

    return None


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


def _read_env_commit() -> Optional[str]:
    """Return the commit hash provided via environment variables, if any."""

    for env_var in ("GIT_COMMIT", "SOURCE_VERSION", "HEROKU_SLUG_COMMIT"):
        commit = os.getenv(env_var)
        if commit:
            return commit.strip() or None
    return None


def _read_git_head() -> Optional[str]:
    """Resolve the current commit hash from the local ``.git`` metadata."""

    git_dir = _resolve_git_directory()
    if git_dir is None:
        return None

    head_path = git_dir / "HEAD"
    try:
        head_content = head_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None

    if not head_content:
        return None

    if head_content.startswith("ref:"):
        ref = head_content.split(" ", 1)[1]
        ref_path = git_dir / ref
        try:
            return ref_path.read_text(encoding="utf-8").strip() or None
        except FileNotFoundError:
            packed_refs_path = git_dir / "packed-refs"
            try:
                for line in packed_refs_path.read_text(encoding="utf-8").splitlines():
                    if not line or line.startswith(("#", "^")):
                        continue
                    parts = line.split(" ", 1)
                    if len(parts) != 2:
                        continue
                    commit_hash, packed_ref = parts
                    if packed_ref.strip() == ref:
                        return commit_hash.strip() or None
            except FileNotFoundError:
                return None
            return None

    return head_content


@lru_cache(maxsize=1)
def _resolve_git_commit() -> Optional[str]:
    """Resolve the active git commit hash from the environment or repository."""

    commit = _read_env_commit()
    if commit:
        return commit

    return _read_git_head()


def get_current_commit(short_length: int = 6) -> str:
    """Return the short git commit hash for the running application."""

    commit = _resolve_git_commit()
    if not commit:
        return "unknown"

    if short_length <= 0:
        return commit

    return commit[:short_length]


__all__ = ["get_current_version", "get_current_commit"]
