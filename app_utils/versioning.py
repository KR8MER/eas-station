"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Utilities for tracking and resolving the application's release version."""

import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple


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


def _read_env_branch() -> Optional[str]:
    """Return the branch name provided via environment variables, if any."""

    branch = os.getenv("GIT_BRANCH")
    if branch:
        return branch.strip() or None
    return None


def _read_env_commit_details() -> Tuple[Optional[str], Optional[str]]:
    """Return commit date and message provided via environment variables."""

    date = os.getenv("GIT_COMMIT_DATE")
    message = os.getenv("GIT_COMMIT_MESSAGE")
    return (date.strip() or None if date else None, message.strip() or None if message else None)


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


def _read_git_branch() -> Optional[str]:
    """Return the current branch name from the git metadata."""

    git_dir = _resolve_git_directory()
    if git_dir is None:
        return None

    head_path = git_dir / "HEAD"
    try:
        head_content = head_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None

    if head_content.startswith("ref:"):
        ref = head_content.split(" ", 1)[1].strip()
        return ref.split("/")[-1]

    return None


def _format_reflog_timestamp(timestamp: str, tz_offset: str) -> Optional[str]:
    """Return an ISO 8601 timestamp derived from reflog metadata."""

    try:
        epoch = int(timestamp)
    except (TypeError, ValueError):
        return None

    try:
        sign = 1 if tz_offset.startswith("+") else -1
        hours = int(tz_offset[1:3])
        minutes = int(tz_offset[3:5])
        offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
    except Exception:
        offset = timezone.utc

    dt = datetime.fromtimestamp(epoch, tz=offset)
    return dt.isoformat()


def _read_git_reflog_entry() -> Optional[Dict[str, Optional[str]]]:
    """Return commit metadata from the HEAD reflog if available."""

    git_dir = _resolve_git_directory()
    if git_dir is None:
        return None

    reflog_path = git_dir / "logs" / "HEAD"
    try:
        lines = reflog_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue

        if "\t" in line:
            metadata, message = line.split("\t", 1)
        else:
            metadata, message = line, ""

        metadata = metadata.strip()
        if not metadata:
            continue

        parts = metadata.split()
        if len(parts) < 4:
            continue

        new_commit = parts[1].strip() or None
        timestamp = parts[-2]
        tz_offset = parts[-1]
        formatted_date = _format_reflog_timestamp(timestamp, tz_offset)

        return {
            "commit": new_commit,
            "date": formatted_date,
            "message": message.strip() or None,
        }

    return None


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


def get_git_metadata() -> Dict[str, str]:
    """Return commit metadata without relying on git CLI tools."""

    commit = _resolve_git_commit()
    branch = _read_env_branch() or _read_git_branch()
    env_date, env_message = _read_env_commit_details()

    reflog_entry = _read_git_reflog_entry()
    if reflog_entry:
        commit = commit or reflog_entry.get("commit")
        commit_date = env_date or reflog_entry.get("date")
        commit_message = env_message or reflog_entry.get("message")
    else:
        commit_date = env_date
        commit_message = env_message

    commit_hash_full = commit or "unknown"

    return {
        "commit_hash": commit_hash_full[:8] if commit_hash_full != "unknown" else "unknown",
        "commit_hash_full": commit_hash_full,
        "branch": branch or "unknown",
        "commit_date": commit_date or "unknown",
        "commit_message": commit_message or "unknown",
    }


def get_git_tree_state() -> Optional[bool]:
    """Return the git tree cleanliness derived from environment metadata."""

    state = os.getenv("GIT_TREE_STATE")
    if not state:
        return None

    normalized = state.strip().lower()
    if normalized in {"clean", "true", "1", "yes"}:
        return True
    if normalized in {"dirty", "false", "0", "no"}:
        return False

    return None


__all__ = [
    "get_current_version",
    "get_current_commit",
    "get_git_metadata",
    "get_git_tree_state",
]
