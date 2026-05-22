"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""LED / VFD / OLED / screen-manager bootstrap."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def initialize_led_controller():
    """Initialize LED sign controller."""
    try:
        from app_core.led import initialise_led_controller, ensure_led_tables

        # Call initialise_led_controller() directly - it checks the database
        # enabled setting internally. Do NOT gate on LED_AVAILABLE here because
        # that flag is False at import time and only set True *after*
        # initialise_led_controller() succeeds.
        controller = initialise_led_controller(logger)
        if controller:
            logger.info("✅ LED controller initialized")
            # Ensure database tables exist
            try:
                ensure_led_tables()
            except Exception as e:
                logger.warning(f"⚠️  Failed to ensure LED tables: {e}")
        else:
            logger.info("LED controller disabled or unavailable")

    except Exception as e:
        logger.warning(f"⚠️  LED controller not available: {e}")
        logger.info("Continuing without LED support")


def initialize_vfd_controller():
    """Initialize VFD display controller."""
    try:
        from app_core.vfd import initialise_vfd_controller, ensure_vfd_tables

        # Call initialise_vfd_controller() directly - it checks the database
        # enabled setting internally. Do NOT gate on VFD_AVAILABLE here because
        # that flag is False at import time and only set True *after*
        # initialise_vfd_controller() succeeds.
        controller = initialise_vfd_controller(logger)
        if controller:
            logger.info("✅ VFD controller initialized")
            # Ensure database tables exist
            try:
                ensure_vfd_tables()
            except Exception as e:
                logger.warning(f"⚠️  Failed to ensure VFD tables: {e}")
        else:
            logger.info("VFD controller disabled or unavailable")

    except Exception as e:
        logger.warning(f"⚠️  VFD controller not available: {e}")
        logger.info("Continuing without VFD support")


def initialize_oled_display():
    """Initialize OLED display."""
    try:
        from app_core.oled import initialise_oled_display, ensure_oled_button

        # Call initialise_oled_display() directly - it checks the database
        # enabled setting internally. Do NOT gate on OLED_AVAILABLE here because
        # that flag is False at import time and only set True *after*
        # initialise_oled_display() succeeds.
        controller = initialise_oled_display(logger)
        if controller:
            logger.info("✅ OLED display initialized")

            # Initialize OLED button (GPIO pin 4)
            button = ensure_oled_button(logger)
            if button:
                logger.info("✅ OLED button initialized on GPIO 4")
            else:
                logger.info("OLED button disabled or unavailable")
        else:
            logger.info("OLED display disabled or unavailable")

    except Exception as e:
        logger.warning(f"⚠️  OLED display not available: {e}")
        logger.info("Continuing without OLED support")


def initialize_screen_manager(app):
    """Initialize screen manager for OLED/LED/VFD displays.

    Returns the started ``screen_manager`` singleton (or ``None`` on
    failure) so the orchestrator can register it for shutdown cleanup.
    """
    try:
        from scripts.screen_manager import screen_manager

        with app.app_context():
            screen_manager.init_app(app)

            # Start screen rotation if enabled (read from database, not env var)
            auto_start = True  # default
            try:
                from app_core.hardware_settings import get_oled_settings
                oled_settings = get_oled_settings()
                auto_start = oled_settings.get('screens_auto_start', True)
            except Exception:
                pass  # Fall back to default True if database unavailable

            if auto_start:
                screen_manager.start()
                logger.info("✅ Screen manager started with automatic rotation")
            else:
                logger.info("Screen manager initialized (auto-start disabled)")

        return screen_manager

    except Exception as e:
        logger.warning(f"⚠️  Screen manager not available: {e}")
        logger.info("Continuing without display support")
        return None
