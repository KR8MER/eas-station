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

"""Helpers for working with embedded static assets."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[1]
_TECH_STACK_LOGO_DIR = _ROOT / "static" / "img" / "tech-stack-logos"


def _normalise_slug(slug: str) -> str:
    """Return a filesystem-safe slug for the given logo name."""

    slug = slug.strip().lower().replace(" ", "-")
    return "".join(ch for ch in slug if ch.isalnum() or ch in {"-", "_"})


@lru_cache(maxsize=32)
def get_shield_logo_data(slug: str) -> Optional[str]:
    """Return a data URI for the requested tech stack badge logo."""

    normalised = _normalise_slug(slug)
    if not normalised:
        return None

    logo_path = _TECH_STACK_LOGO_DIR / f"{normalised}.svg"
    try:
        data = logo_path.read_bytes()
    except FileNotFoundError:
        return None

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


__all__ = ["get_shield_logo_data"]
