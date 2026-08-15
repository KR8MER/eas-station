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

"""Server-side preview image renderer for the OLED display.

Split out of services/displays/preview_render.py (which re-exports this
function) to keep that module under the repo's file-size guideline once it
grew a third display type. Best-effort: if Pillow is unavailable or anything
goes wrong this returns ``None`` and the page falls back to a simple idle
message.
"""

import logging
from typing import Any, Dict, Optional, Sequence

from scripts.preview_render_common import (
    Image,
    ImageChops,
    ImageFilter,
    ImageOps,
    PIL_AVAILABLE,
    encode_preview_png,
)

logger = logging.getLogger(__name__)

# Cool blue-white OLED phosphor, matching the gallery renders in
# docs/screenshots/oled-displays.png.
_OLED_ON = (220, 230, 255)
_OLED_BG = (10, 12, 16)


class _NullOLEDDevice:
    """No-op stand-in for luma.oled's device object.

    ``ArgonOLEDController.render_frame()`` ends with ``self.device.display
    (image)`` -- this swallows that call instead of writing to a real I2C
    device.
    """

    def display(self, image: "Image.Image") -> None:  # noqa: ARG002
        pass


def render_oled_elements_preview(
    elements: Optional[Sequence[Dict[str, Any]]],
    width: Optional[int] = None,
    height: Optional[int] = None,
    scale: int = 4,
) -> Optional[str]:
    """Render a resolved OLED element list to a glowing blue-white PNG.

    ``width``/``height`` default to the operator's actual configured panel
    size (``app_core.hardware_settings.get_oled_settings()``) rather than
    assuming the stock 128x64 SSD1306, so a preview for a differently
    sized panel doesn't draw at the wrong resolution.

    ArgonOLEDController (app_core/oled.py) couples rendering to real I2C
    hardware in its constructor (``i2c(...)`` / ``ssd1306(...)`` run
    unconditionally in ``__init__``), unlike scripts.vfd_controller's and
    scripts.led_sign_controller's pure module-level render functions --
    so unlike render_vfd_elements_preview()/render_led_elements_preview(),
    this builds the controller via ``__new__`` (skipping ``__init__``
    entirely) and fills in only the instance attributes ``render_frame()``
    touches, with a ``_NullOLEDDevice`` standing in for the real driver.
    That avoids ever calling into the I2C driver, and -- unlike patching
    ``app_core.oled.i2c``/``ssd1306`` -- touches no shared module state, so
    concurrent preview requests (this runs under gunicorn's gevent
    workers) can't race on a global patch.
    """
    if not PIL_AVAILABLE or not elements:
        return None
    try:
        from app_core.oled import ArgonOLEDController

        if width is None or height is None:
            # Best-effort: get_oled_settings() needs a DB/app context, which
            # isn't always available to a caller (e.g. tests exercising this
            # module standalone) -- fall back to the stock SSD1306 128x64
            # panel rather than failing the whole render over a dimension
            # lookup.
            try:
                from app_core.hardware_settings import get_oled_settings

                oled_settings = get_oled_settings()
            except Exception:
                oled_settings = {}
            if width is None:
                width = int(oled_settings.get('width') or 128)
            if height is None:
                height = int(oled_settings.get('height') or 64)

        controller = ArgonOLEDController.__new__(ArgonOLEDController)
        controller.width = width
        controller.height = height
        controller.default_invert = False
        controller._fonts = ArgonOLEDController._load_fonts(controller, None)
        controller.device = _NullOLEDDevice()
        controller._last_image = None
        controller.render_frame(list(elements))
        mono = controller._last_image

        if mono is None:
            return None

        rgb = mono.convert("L").resize((width * scale, height * scale), Image.NEAREST)
        base = ImageOps.colorize(rgb, black=_OLED_BG, white=_OLED_ON)
        glow = base.filter(ImageFilter.GaussianBlur(scale * 0.5))
        glow = Image.eval(glow, lambda v: int(v * 0.6))
        return encode_preview_png(ImageChops.screen(base, glow))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("OLED elements preview render failed: %s", exc)
        return None
