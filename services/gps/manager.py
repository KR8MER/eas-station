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

Repository: https://github.com/KR8MER/EAS-Station
"""

from __future__ import annotations

"""GPS manager bootstrap (Uputronics GPS/RTC HAT, Adafruit #2324, etc.)."""

import logging
from typing import Optional


def initialize_gps_manager(redis_client, logger: Optional[logging.Logger] = None):
    """Initialize the GPS receiver manager if enabled in hardware settings.

    Returns the started manager (kept alive even on ``start()`` failure
    so ``get_status()`` can report the specific error reason).  Returns
    ``None`` when GPS is disabled or the underlying package isn't
    available.
    """
    log = logger or logging.getLogger(__name__)

    try:
        from app_core.hardware_settings import get_gps_settings
        from app_core.gps import GPSManager

        gps_settings = get_gps_settings()
        if not gps_settings.get('enabled', False):
            log.info("GPS receiver disabled (enable in Admin > Hardware Settings)")
            return None

        manager = GPSManager(
            config=gps_settings,
            redis_client=redis_client,
            logger=log.getChild("gps"),
        )
        manager.start()
        # Keep manager alive even on start() failure so get_status() can
        # return the specific error reason (port_not_found, pyserial_missing, etc.)
        return manager

    except Exception as e:
        log.warning(f"⚠️  GPS manager not available: {e}")
        log.info("Continuing without GPS support")
        return None
