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

"""GPIO / NeoPixel / USB tower-light bootstrap."""

import logging

logger = logging.getLogger(__name__)


def initialize_gpio_controller(db_session=None, db_app=None):
    """Initialize GPIO controller for relay/transmitter control.

    *db_app* is the Flask application owning *db_session*.  Relay keying runs
    on background threads (indicator loop, watchdogs, behavior holds) that have
    no application context of their own, and Flask-SQLAlchemy scopes its session
    to that context — without the app the controller cannot write its audit
    trail from those threads.

    Returns the constructed ``GPIOController`` (with its behaviour
    manager wired up) or ``None`` when GPIO is disabled / no pins are
    configured / the underlying package isn't available.
    """
    try:
        from app_utils.gpio import (
            GPIOController,
            GPIOBehaviorManager,
            load_gpio_pin_configs_from_db,
            load_gpio_behavior_matrix_from_db,
            load_gpio_interlock_groups_from_db,
        )

        # Try to load GPIO enabled flag from database first
        try:
            from app_core.hardware_settings import get_gpio_settings, get_oled_settings
            gpio_settings = get_gpio_settings()
            gpio_enabled = gpio_settings.get('enabled', False)

            # Check if OLED is enabled to avoid pin conflicts
            oled_settings = get_oled_settings()
            oled_enabled = oled_settings.get('enabled', False)
        except Exception:
            # Fallback if database not available
            gpio_enabled = False
            oled_enabled = False

        if not gpio_enabled:
            logger.info("GPIO controller disabled (enable in Admin > Hardware Settings)")
            return None

        # Load GPIO pin configurations (from database with env fallback)
        # Pass oled_enabled to ensure reserved pins are only blocked when OLED is actually enabled
        all_configs = load_gpio_pin_configs_from_db(logger, oled_enabled=oled_enabled)
        # Only OUTPUT-direction pins are relays this controller drives; INPUT
        # pins are read by GPIOInputWatcher instead (see
        # initialize_gpio_input_watcher below) -- a different concern with no
        # behavior/flash/watchdog semantics.
        gpio_configs = [c for c in all_configs if c.direction == "output"]
        if not gpio_configs:
            logger.info("No GPIO output pins configured (configure in Admin > Hardware Settings)")
            return None

        # Create GPIO controller with database session for audit logging
        controller = GPIOController(
            db_session=db_session,
            db_app=db_app,
            logger=logger,
        )

        # Add each configured pin to the controller
        for config in gpio_configs:
            try:
                controller.add_pin(config)
            except Exception as e:
                logger.error(f"Failed to add GPIO pin {config.pin}: {e}")

        # Load relay interlock (mutual-exclusion) groups. Wired onto the
        # controller the same way behavior_manager is below -- a plain
        # post-construction attribute, absent entirely when no groups are
        # configured (see GPIOController._check_interlock_conflict).
        interlock_groups = load_gpio_interlock_groups_from_db(logger)
        if interlock_groups:
            controller.interlock_groups = interlock_groups
            logger.info(f"✅ {len(interlock_groups)} relay interlock group(s) active")

        # Load and configure GPIO behavior matrix
        behavior_matrix = load_gpio_behavior_matrix_from_db(logger, oled_enabled=oled_enabled)
        if behavior_matrix:
            gpio_behavior_manager = GPIOBehaviorManager(
                controller=controller,
                pin_configs=gpio_configs,
                behavior_matrix=behavior_matrix,
                logger=logger,
                interlock_groups=interlock_groups,
            )
            controller.behavior_manager = gpio_behavior_manager
            logger.info(f"✅ GPIO controller initialized with {len(gpio_configs)} pin(s) and behavior matrix")
        else:
            logger.info(f"✅ GPIO controller initialized with {len(gpio_configs)} pin(s)")

        return controller

    except Exception as e:
        logger.warning(f"⚠️  GPIO controller not available: {e}")
        logger.info("Continuing without GPIO support")
        return None


def initialize_gpio_input_watcher():
    """Initialize the GPIO input watcher (physical buttons/contact closures).

    Independently loads its own pin configuration (same pattern as
    ``initialize_tower_light_controller``/``initialize_neopixel_controller``
    below) rather than sharing state with ``initialize_gpio_controller`` --
    input reading and output driving are different concerns.

    Returns the started ``GPIOInputWatcher``, or ``None`` when GPIO is
    disabled, no input pins are configured, or the underlying package isn't
    available.
    """
    try:
        from app_utils.gpio import GPIOInputWatcher, load_gpio_pin_configs_from_db

        try:
            from app_core.hardware_settings import get_gpio_settings, get_oled_settings
            gpio_enabled = get_gpio_settings().get('enabled', False)
            oled_enabled = get_oled_settings().get('enabled', False)
        except Exception:
            gpio_enabled = False
            oled_enabled = False

        if not gpio_enabled:
            return None

        all_configs = load_gpio_pin_configs_from_db(logger, oled_enabled=oled_enabled)
        input_configs = [c for c in all_configs if c.direction == "input"]
        if not input_configs:
            return None

        watcher = GPIOInputWatcher(input_configs, logger=logger)
        watcher.start()
        if watcher.active_pin_count:
            logger.info(f"✅ GPIO input watcher active: {watcher.active_pin_count} pin(s)")
            return watcher
        return None

    except Exception as e:
        logger.warning(f"⚠️  GPIO input watcher not available: {e}")
        logger.info("Continuing without GPIO input support")
        return None


def initialize_tower_light_controller():
    """Initialize USB tower light controller (Adafruit #5125 / CH34x serial).

    Returns the started ``TowerLightController`` or ``None`` when the
    controller is disabled or unavailable.
    """
    try:
        from app_utils.gpio import TowerLightController, load_tower_light_config_from_db

        config = load_tower_light_config_from_db(logger)
        if config is None:
            logger.info("USB tower light disabled (enable in Admin > Hardware Settings)")
            return None

        controller = TowerLightController(config, logger=logger)
        available = controller.start()

        if available:
            logger.info(
                "✅ USB tower light initialized on %s",
                config.serial_port,
            )
        else:
            logger.warning(
                "⚠️  USB tower light configured on %s but port could not be opened",
                config.serial_port,
            )

        return controller

    except Exception as e:
        logger.warning(f"⚠️  USB tower light not available: {e}")
        logger.info("Continuing without USB tower light support")
        return None


def initialize_neopixel_controller():
    """Initialize NeoPixel / WS2812B LED strip controller.

    Returns the started ``NeopixelController`` (which may be in null
    mode if the rpi_ws281x library is unavailable / DMA denied), or
    ``None`` when the controller is disabled.
    """
    try:
        from app_utils.gpio import NeopixelController, load_neopixel_config_from_db

        config = load_neopixel_config_from_db(logger)
        if config is None:
            logger.info("NeoPixel controller disabled (enable in Admin > Hardware Settings)")
            return None

        controller = NeopixelController(config, logger=logger)
        hardware_available = controller.start()

        if hardware_available:
            logger.info(
                "✅ NeoPixel controller initialized: %d pixel(s) on GPIO %d",
                config.num_pixels,
                config.gpio_pin,
            )
        else:
            logger.info(
                "NeoPixel controller running in null mode "
                "(rpi_ws281x library not available or DMA access denied)"
            )

        return controller

    except Exception as e:
        logger.warning(f"⚠️  NeoPixel controller not available: {e}")
        logger.info("Continuing without NeoPixel support")
        return None
