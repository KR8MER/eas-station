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

"""Periodic hardware-metrics publisher.

Coordinates the per-subsystem publishers (display state, Zigbee status)
and writes the high-level ``hardware:metrics`` key that the web UI's
health-check banner reads.  Kept under ``services.common`` because it
touches more than one subsystem and is owned by the orchestrator
(``hardware_service.main()``), not by any one piece of hardware.
"""

import json
import logging
from datetime import datetime, timezone

from services.displays import publish_display_state
from services.zigbee import publish_zigbee_status

logger = logging.getLogger(__name__)


def publish_hardware_metrics(
    *,
    redis_client,
    flask_app,
    screen_manager,
    gpio_controller,
) -> None:
    """Publish hardware status and metrics to Redis.

    IMPORTANT: This is called from the hardware service's health loop
    which runs outside any Flask app context.  Functions that access
    the database (``publish_display_state``, ``publish_zigbee_status``)
    require app context for Flask-SQLAlchemy queries.  We push the app
    context here so all downstream functions can use the DB.
    """
    if not redis_client:
        return

    # Push Flask app context for database operations in publish_display_state()
    # and publish_zigbee_status() which call get_*_settings() -> HardwareSettings.query
    if flask_app:
        ctx = flask_app.app_context()
        ctx.push()
    else:
        ctx = None

    try:
        metrics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "screen_manager_running": screen_manager is not None and getattr(screen_manager, '_running', False),
            "gpio_controller_available": gpio_controller is not None,
        }

        # Add screen manager metrics if available
        if screen_manager:
            try:
                metrics["screens"] = {
                    "oled_active": getattr(screen_manager, '_oled_rotation', None) is not None,
                    "led_active": getattr(screen_manager, '_led_rotation', None) is not None,
                    "vfd_active": getattr(screen_manager, '_vfd_rotation', None) is not None,
                }
            except Exception:
                pass

        # Publish basic metrics to Redis
        redis_client.setex(
            "hardware:metrics",
            60,  # 60 second TTL
            json.dumps(metrics)
        )

        # Publish detailed display state for preview (separate key for larger data)
        publish_display_state(redis_client, screen_manager)

        # Refresh Zigbee coordinator status in Redis (keeps key alive beyond initial publish)
        publish_zigbee_status(redis_client)

    except Exception as e:
        logger.debug(f"Failed to publish hardware metrics: {e}")
    finally:
        if ctx is not None:
            ctx.pop()
