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

"""Publish detailed display state (with preview images) to Redis."""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def publish_display_state(redis_client, screen_manager) -> None:
    """Publish detailed display state including preview images to Redis."""
    if not redis_client:
        return

    try:
        # Import hardware settings helpers
        from app_core.hardware_settings import get_oled_settings, get_led_settings, get_vfd_settings

        # Gated-alerts hold-off queue ("Pending Review" scene) -- how many
        # GatedAlert rows are currently status='pending'. Read straight off
        # the screen_manager's own cache (refreshed every ~1s in
        # _update_rotations) rather than re-querying the DB here, since this
        # function already runs on a tight publish interval.
        pending_gate_count = getattr(screen_manager, "_gated_pending_count", 0) if screen_manager else 0

        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pending_gate_count": pending_gate_count,
            "oled": {
                "enabled": False,
                "width": 128,
                "height": 64,
                "current_screen": None,
                "scroll_offset": 0,
                "alert_active": False,
            },
            "vfd": {
                "enabled": False,
                "width": 140,
                "height": 32,
                "current_screen": None,
            },
            "led": {
                "enabled": False,
                "lines": 4,
                "chars_per_line": 20,
                "current_message": None,
                "color": "AMBER",
            },
        }

        # Get OLED state from database and module
        try:
            oled_settings = get_oled_settings()
            oled_enabled_in_db = oled_settings.get('enabled', False)

            # Import after getting settings to avoid circular imports
            import app_core.oled as oled_module

            # Only show as enabled if both database setting is true AND controller exists
            if oled_enabled_in_db and oled_module.oled_controller:
                state["oled"]["enabled"] = True
                state["oled"]["width"] = oled_module.oled_controller.width
                state["oled"]["height"] = oled_module.oled_controller.height

                # Get current screen name if available
                if screen_manager and hasattr(screen_manager, '_current_oled_screen'):
                    current_screen = screen_manager._current_oled_screen
                    if current_screen:
                        state["oled"]["current_screen"] = current_screen.name if hasattr(current_screen, 'name') else str(current_screen)

                # Get current alert state if scrolling
                if screen_manager:
                    if hasattr(screen_manager, '_oled_scroll_effect') and screen_manager._oled_scroll_effect:
                        state["oled"]["alert_active"] = True
                        state["oled"]["scroll_offset"] = getattr(screen_manager, '_oled_scroll_offset', 0)
                        state["oled"]["alert_text"] = getattr(screen_manager, '_current_alert_text', "") or ""
                        state["oled"]["scroll_speed"] = getattr(screen_manager, '_oled_scroll_speed', 4)

                        # Get cached header
                        if hasattr(screen_manager, '_cached_header_text'):
                            state["oled"]["header_text"] = screen_manager._cached_header_text

                # Get preview image
                try:
                    preview_image = oled_module.oled_controller.get_preview_image_base64()
                    if preview_image:
                        state["oled"]["preview_image"] = preview_image
                except Exception as e:
                    logger.debug(f"Failed to get OLED preview image: {e}")
        except Exception as e:
            logger.debug(f"Error getting OLED state: {e}")

        # Get VFD state from database and module
        try:
            vfd_settings = get_vfd_settings()
            vfd_enabled_in_db = vfd_settings.get('enabled', False)

            from app_core.vfd import vfd_controller

            # Only show as enabled if both database setting is true AND controller exists
            if vfd_enabled_in_db and vfd_controller:
                state["vfd"]["enabled"] = True

                # Render a faithful preview of the blue-green VFD from the
                # draw-commands last sent to the panel (falling back to an idle
                # screen when nothing has been displayed yet).
                try:
                    from services.displays.preview_render import (
                        render_vfd_preview, render_vfd_idle,
                    )
                    commands = getattr(screen_manager, "_last_vfd_commands", None) if screen_manager else None
                    preview = render_vfd_preview(commands) if commands else render_vfd_idle()
                    if preview:
                        state["vfd"]["preview_image"] = preview
                except Exception as e:
                    logger.debug(f"Failed to render VFD preview: {e}")
        except Exception as e:
            logger.debug(f"Error getting VFD state: {e}")

        # Get LED state from database and module
        try:
            led_settings = get_led_settings()
            led_enabled_in_db = led_settings.get('enabled', False)

            import app_core.led as led_module

            # Only show as enabled if both database setting is true AND controller exists
            if led_enabled_in_db and led_module.led_controller:
                state["led"]["enabled"] = True

                # Render a faithful dot-matrix preview from the LED content last
                # rendered by the rotation engine (lines + M-Protocol colour).
                try:
                    from services.displays.preview_render import render_led_preview
                    led_render = getattr(screen_manager, "_last_led_render", None) if screen_manager else None
                    if led_render:
                        lines = led_render.get("lines") or []
                        color = led_render.get("color", "AMBER")
                        state["led"]["color"] = color
                        state["led"]["current_message"] = {
                            "lines": [
                                (ln.get("text", "") if isinstance(ln, dict) else str(ln))
                                for ln in lines
                            ]
                        }
                        preview = render_led_preview(lines, color)
                    else:
                        preview = render_led_preview(["", "EAS STATION READY", "", ""], "AMBER")
                    if preview:
                        state["led"]["preview_image"] = preview
                except Exception as e:
                    logger.debug(f"Failed to render LED preview: {e}")
        except Exception as e:
            logger.debug(f"Error getting LED state: {e}")

        # Publish to Redis with short TTL (refreshes every 5 seconds)
        redis_client.setex(
            "hardware:display_state",
            15,  # 15 second TTL (3x the publish interval for tolerance)
            json.dumps(state)
        )

    except Exception as e:
        logger.debug(f"Failed to publish display state: {e}")
