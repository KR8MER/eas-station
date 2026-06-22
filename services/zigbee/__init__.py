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

"""Zigbee subsystem.

Owns coordinator detection, the zigpy-znp asyncio controller, and the
Redis status publisher previously inlined in ``hardware_service.py``.
"""

from services.zigbee.api import create_blueprint
from services.zigbee.controller import ZigpyController
from services.zigbee.coordinator import (
    initialize_zigbee_coordinator,
    publish_zigbee_status,
)
from services.zigbee.detection import detect_zigbee_coordinator

__all__ = [
    "ZigpyController",
    "create_blueprint",
    "detect_zigbee_coordinator",
    "initialize_zigbee_coordinator",
    "publish_zigbee_status",
]
