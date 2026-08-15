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

"""Shared Pillow plumbing for the VFD/LED/OLED preview-image renderers.

Split out of services/displays/preview_render.py so that module could stay
under the repo's file-size guideline once it grew a third renderer -- see
scripts/led_preview_render.py, scripts/vfd_preview_render.py and
scripts/oled_preview_render.py, which all depend on this module.
"""

import base64
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised wherever Pillow is installed
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
    PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Image = ImageChops = ImageDraw = ImageFilter = ImageOps = None  # type: ignore[assignment]
    PIL_AVAILABLE = False


def encode_preview_png(img: "Image.Image", colors: int = 64) -> Optional[str]:
    """Encode a preview image as a base64 PNG data URI.

    The glow/bloom produces smooth gradients that balloon a truecolour PNG
    (and this gets published to Redis and polled by the browser every second),
    so the image is quantised to an adaptive palette first.  At 64 colours the
    glow is visually indistinguishable but the payload shrinks by ~10x.
    """
    try:
        out = img.convert("P", palette=Image.ADAPTIVE, colors=colors)
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to encode preview PNG: %s", exc)
        return None
