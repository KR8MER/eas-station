"""Utilities for tracking and resolving the application's release version."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_VERSION_PATH = _ROOT / "VERSION"


@lru_cache()
def get_current_version() -> str:
    """Return the effective application version.

    Priority order:
    1. ``APP_BUILD_VERSION`` environment variable (used in production builds).
    2. Contents of the repository ``VERSION`` file.
    3. ``"0.0.0"`` when no explicit version is available.
    """

    env_version = os.environ.get("APP_BUILD_VERSION")
    if env_version:
        return env_version.strip()

    try:
        return _VERSION_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0"


__all__ = ["get_current_version"]
