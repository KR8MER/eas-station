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

"""Server-side preview image renderers for the OLED, VFD and LED Network Sign.

The Live Display Preview page used to draw hardcoded placeholder text for the
VFD (always green "EAS STATION - VFD") and flat single-colour HTML for the LED
sign, neither of which resembled the real hardware.  Following the same pattern
the OLED already uses -- where the controller ships an actual rendered
framebuffer as a base64 PNG -- these helpers render the *current* display
content to an image so the preview shows what the hardware is really putting
out:

* OLED -- SSD1306 (or the operator's configured panel size): rendered by
  building a throwaway ArgonOLEDController and reusing its render_frame().
* VFD  -- Noritake GU140x32F-7000B: 140x32 graphical VFD with the
  characteristic blue-green (CIG phosphor) glow on dark glass.  Rendered from
  the same draw-command list that drives the panel.
* LED  -- Alpha 9120C: 4 lines x 20 chars, dot-matrix, in the M-Protocol
  colour the message was sent with.

All functions are best-effort: if Pillow is unavailable or anything goes wrong
they return ``None`` and the page falls back to a simple idle message, so a
rendering problem can never take the preview API down.

This module is a thin re-export facade -- the actual renderers live in
scripts/led_preview_render.py, scripts/vfd_preview_render.py and
scripts/oled_preview_render.py (split out to stay under the repo's file-size
guideline once a third display type was added). They live under scripts/
rather than services/displays/ deliberately: tests/test_display_preview_render.py
loads *this* file directly by path so it doesn't pull in services.displays's
__init__ (which imports Flask and the rest of the displays subsystem) --
sibling modules living inside services/displays/ would defeat that, since an
absolute import of any services.displays.* name still runs that __init__
first regardless of how this file itself was loaded.
"""

from scripts.led_preview_render import (
    render_led_elements_preview,
    render_led_preview,
)
from scripts.oled_preview_render import render_oled_elements_preview
from scripts.preview_render_common import PIL_AVAILABLE as _PIL_AVAILABLE
from scripts.vfd_preview_render import (
    render_vfd_elements_preview,
    render_vfd_idle,
    render_vfd_preview,
)

__all__ = [
    "render_led_preview",
    "render_led_elements_preview",
    "render_oled_elements_preview",
    "render_vfd_preview",
    "render_vfd_elements_preview",
    "render_vfd_idle",
]
