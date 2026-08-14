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

"""Gated-alerts (Pending Review) scene builders for the display rotation.

Split out of scripts/screen_manager.py -- that module was already at the
~1600-line soft cap in AGENTS.md, so the new "N alerts pending review" scene
for OLED/LED/VFD lives here instead. ScreenManager owns the rotation timing
and priority wiring (see screen_manager.py's _check_oled_rotation /
_check_led_rotation / _check_vfd_rotation); the functions in this module are
pure builders that turn a GatedAlert summary into a renderer-ready payload.

Not to be confused with ScreenManager._pending_alert, an unrelated
pre-existing concept: the next *active* CAPAlert waiting to interrupt the
OLED scroll. This module is about the GatedAlert hold-off queue (the
"Pending Alerts" queue at /admin/pending-alerts) -- alerts held for operator
review, not yet broadcasting.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Screens are small; this is a display summary, not a full listing (the full
# list lives at /admin/pending-alerts). Keep the DB round-trip cheap.
DEFAULT_QUERY_LIMIT = 8
OLED_MAX_ITEMS = 3
LED_MESSAGE_MAX_CHARS = 120
VFD_LINE_MAX_CHARS = 20


def query_gated_pending_summary(
    limit: int = DEFAULT_QUERY_LIMIT,
    gated_alert_cls: Optional[Any] = None,
) -> Tuple[int, List[Dict[str, str]]]:
    """Return ``(count, items)`` for pending GatedAlert rows.

    Mirrors the query in ``webapp/admin/pending_alerts.py``
    (``GatedAlert.without_audio().filter_by(status='pending')
    .order_by(GatedAlert.hold_until.asc())``), capped to ``limit`` for
    display purposes. ``count`` is ``len(items)`` -- i.e. capped at
    ``limit`` too -- since the hold-off window is normally short (seconds
    to a couple of minutes), it is extremely unlikely for the queue to ever
    exceed a handful of rows in practice.

    ``gated_alert_cls`` is injectable for unit tests; production callers
    should omit it -- the real model is imported lazily so this module has
    no hard dependency on a live app context at import time (it is only
    needed when this function actually runs, same lazy-import pattern used
    throughout screen_manager.py).
    """
    if gated_alert_cls is None:
        from app_core.models import GatedAlert as gated_alert_cls  # type: ignore

    rows = (
        gated_alert_cls.without_audio()
        .filter_by(status="pending")
        .order_by(gated_alert_cls.hold_until.asc())
        .limit(limit)
        .all()
    )

    items: List[Dict[str, str]] = []
    for row in rows:
        event_code = (getattr(row, "event_code", None) or "").strip()
        headline = (
            getattr(row, "headline", None)
            or getattr(row, "event", None)
            or "Pending alert"
        )
        items.append({"event_code": event_code, "headline": str(headline).strip()})

    return len(items), items


def _truncate(text: str, max_chars: int) -> str:
    """Character-count truncation with an ellipsis.

    Used for LED/VFD, which have no font-metrics helper available off the
    physical hardware. OLED truncation instead goes through
    ``ArgonOLEDController._fit_text_to_width`` (pixel-accurate), driven by
    the ``max_width``/``overflow`` element keys built below.
    """
    text = text or ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1].rstrip() + "…"


def build_oled_pending_elements(
    count: int,
    items: List[Dict[str, str]],
    width: int = 128,
    height: int = 64,
) -> Optional[List[Dict[str, Any]]]:
    """Elements-format OLED frame for the gated-alerts Pending Review scene.

    Uses the same element vocabulary as ``SNAPSHOT_SCREEN_TEMPLATE`` in
    screen_manager.py (consumed by ``ArgonOLEDController.render_frame``).
    Returns ``None`` when there is nothing pending -- callers must not
    display an empty scene.
    """
    if count <= 0:
        return None

    elements: List[Dict[str, Any]] = [
        # Inverted header bar, matching the style of other built-in screens.
        {"type": "rectangle", "x": 0, "y": 0, "width": width, "height": 12, "filled": True},
        {"type": "text", "text": "PENDING REVIEW", "x": 4, "y": 1, "font": "small", "invert": True},
        {
            "type": "text",
            "text": str(count),
            "x": width - 4, "y": 1,
            "font": "small", "invert": True,
            "align": "right", "max_width": 24, "overflow": "trim",
        },
    ]

    row_y = 16
    row_height = 15
    shown = items[:OLED_MAX_ITEMS]
    for entry in shown:
        label = entry.get("event_code") or ""
        headline = entry.get("headline") or ""
        line_text = f"{label} {headline}".strip() if label else headline
        elements.append({
            "type": "text",
            "text": line_text or "(no headline)",
            "x": 4, "y": row_y,
            "font": "small",
            "max_width": width - 8,
            "overflow": "ellipsis",
        })
        row_y += row_height

    remaining = len(items) - len(shown)
    if remaining > 0 and row_y < height:
        elements.append({
            "type": "text",
            "text": f"+{remaining} more",
            "x": 4, "y": row_y,
            "font": "small",
            "max_width": width - 8,
            "overflow": "ellipsis",
        })

    return elements


def build_led_pending_message(
    count: int,
    items: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """LED sign message for the Pending Review scene.

    A single scrolling line naming the count and the top item, in the
    ``{'lines', 'color', 'mode', 'speed'}`` shape ScreenManager already
    expects from a rendered LED screen (see ``_display_led_screen``).
    Returns ``None`` when nothing is pending. Uses YELLOW/SCROLL to stay
    visually distinct from an active/incoming alert (reserved for more
    urgent colours/modes elsewhere) while still standing out from routine
    rotation content.
    """
    if count <= 0:
        return None

    top = items[0] if items else {}
    label = top.get("event_code") or ""
    headline = top.get("headline") or ""
    detail = f"{label} {headline}".strip() if label else headline

    plural = "" if count == 1 else "S"
    message = f"PENDING REVIEW: {count} ALERT{plural}"
    if detail:
        message = f"{message} - {detail}"

    message = _truncate(message, LED_MESSAGE_MAX_CHARS)

    return {
        "lines": [message],
        "color": "YELLOW",
        "mode": "SCROLL",
        "speed": "SPEED_3",
    }


def build_vfd_pending_elements(
    count: int,
    items: List[Dict[str, str]],
    width: int = 140,
    height: int = 32,
) -> Optional[List[Dict[str, Any]]]:
    """VFD element list for the Pending Review scene, in
    scripts.vfd_controller.render_vfd_elements()'s native shape (the same
    contract render_frame() and the OLED engine both use). Returns ``None``
    when nothing is pending.
    """
    if count <= 0:
        return None

    header = _truncate(f"PENDING REVIEW: {count}", VFD_LINE_MAX_CHARS)

    top = items[0] if items else {}
    label = top.get("event_code") or ""
    headline = top.get("headline") or ""
    detail = f"{label} {headline}".strip() if label else headline
    detail_line = _truncate(detail, VFD_LINE_MAX_CHARS) if detail else ""

    elements: List[Dict[str, Any]] = [
        {"type": "rectangle", "x": 0, "y": 0, "width": width, "height": 11, "filled": True},
        {"type": "icon", "name": "warning", "x": 2, "y": 1, "size": 9, "invert": True},
        {"type": "text", "x": 14, "y": 1, "text": header, "invert": True},
    ]
    if detail_line:
        elements.append({"type": "text", "x": 2, "y": 16, "text": detail_line})

    return elements


def push_oled_pending_scene(controller, count: int, items: List[Dict[str, str]]) -> bool:
    """Build and render the Pending Review scene on an OLED controller.

    Returns True if a frame was drawn. Exceptions from the hardware call are
    caught and logged here (mirrors the try/except-per-render convention
    used throughout screen_manager.py) so a bad frame can never take down
    the rotation loop.
    """
    elements = build_oled_pending_elements(count, items, width=controller.width, height=controller.height)
    if not elements:
        return False
    try:
        controller.render_frame(elements, clear=True, invert=None)
    except Exception as exc:
        logger.error("Error rendering gated-pending OLED scene: %s", exc)
        return False
    return True


def push_led_pending_scene(led_module, count: int, items: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """Build and send the Pending Review message to the LED sign controller.

    Returns the rendered payload (for the caller to cache for the live
    preview, mirroring ``_last_led_render`` in screen_manager.py) or None if
    nothing was sent.
    """
    message = build_led_pending_message(count, items)
    if not message or not led_module.led_controller:
        return None

    def _enum(enum_cls, name, fallback):
        if enum_cls is None:
            return fallback
        return getattr(enum_cls, name, fallback)

    color = _enum(led_module.Color, message["color"], message["color"])
    mode = _enum(led_module.DisplayMode, message["mode"], message["mode"])
    speed = _enum(led_module.Speed, message["speed"], message["speed"])

    try:
        led_module.led_controller.send_message(
            lines=message["lines"],
            color=color,
            mode=mode,
            speed=speed,
        )
    except Exception as exc:
        logger.error("Error sending gated-pending LED message: %s", exc)
        return None

    return message


def push_vfd_pending_scene(vfd_module, count: int, items: List[Dict[str, str]]) -> Optional[List[Dict[str, Any]]]:
    """Build and send the Pending Review scene to the VFD controller.

    Returns the rendered element list (for the caller to cache for the live
    preview, mirroring ``_last_vfd_elements`` in screen_manager.py) or None
    if nothing was sent.
    """
    elements = build_vfd_pending_elements(count, items)
    if not elements or not vfd_module.vfd_controller:
        return None

    try:
        vfd_module.vfd_controller.render_frame(elements)
    except Exception as exc:
        logger.error("Error sending gated-pending VFD frame: %s", exc)
        return None

    return elements
