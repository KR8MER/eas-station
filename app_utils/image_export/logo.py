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

"""Canonical brand logo raster used inside the share image."""

import os
from typing import Optional

from PIL import Image


# ─── Canonical brand logo ──────────────────────────────────────────────────
# Single source of truth for the EAS Station brand logo raster used inside
# the share image.  Update both the SVG (static/img/eas-system-wordmark.svg)
# and re-rasterize this PNG to refresh every consumer — favicons, on-page
# <img> tags, this share-image renderer.
#
# Three levels up from app_utils/image_export/logo.py is the repository root.
# This was two levels when the renderer was a single app_utils/image_export.py;
# the package split moved every module one directory deeper.  Getting this
# wrong is silent — _load_logo() swallows the failure and renders the card
# without a logo — so it is asserted in tests/test_image_export_themes.py.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOGO_PATH = os.path.join(_REPO_ROOT, 'static', 'img', 'eas-system-wordmark.png')
_LOGO_CACHE: Optional[Image.Image] = None


def _load_logo() -> Optional[Image.Image]:
    """Load the canonical EAS Station logo PNG (cached, RGBA).

    The PNG keeps the full SVG viewBox dimensions (favicons + apple
    touch icon assume those), but for the share-card renderer the
    trailing transparent margin on the right (where the SVG reserved
    blank space past "INFRASTRUCTURE") would force the visible wordmark
    to sit ~100 px inside ``brand_right``.  We trim that right margin
    here — and only that — so the cached image's right edge matches the
    rightmost pixel of "STATION™".  When the renderer pastes at
    ``brand_right - logo_w`` the visible wordmark then anchors flush
    against the canvas right margin instead of floating away from it.
    Vertical bounds are preserved so the height-to-width ratio (and the
    title shrink-to-fit math that depends on it) stays the same.
    """
    global _LOGO_CACHE
    if _LOGO_CACHE is not None:
        return _LOGO_CACHE
    try:
        with Image.open(_LOGO_PATH) as im:
            rgba = im.convert('RGBA')
            bbox = rgba.getbbox()
            if bbox is not None:
                # Trim trailing right transparent margin only — leave
                # the vertical extent and the left padding alone.
                rgba = rgba.crop((0, 0, bbox[2], rgba.height))
            _LOGO_CACHE = rgba.copy()
        return _LOGO_CACHE
    except Exception:
        return None
