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

"""Zigbee coordinator initialisation + Redis status publisher."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from services.zigbee.controller import ZigpyController
from services.zigbee.detection import detect_zigbee_coordinator

logger = logging.getLogger(__name__)


def initialize_zigbee_coordinator(redis_client) -> Optional[ZigpyController]:
    """Initialize Zigbee coordinator if enabled in hardware settings.

    Returns the started ``ZigpyController`` instance, or ``None`` if
    Zigbee is disabled, no port is reachable, or initialisation
    otherwise fails.
    """
    try:
        from app_core.hardware_settings import get_zigbee_settings

        zigbee_settings = get_zigbee_settings()
        if not zigbee_settings.get('enabled', False):
            logger.info("Zigbee coordinator disabled (enable in Admin > Hardware Settings)")
            return None

        port = zigbee_settings.get('port', '/dev/ttyAMA0')
        baudrate = zigbee_settings.get('baudrate', 115200)
        channel = zigbee_settings.get('channel', 15)
        pan_id = zigbee_settings.get('pan_id', '0x1A62')

        # Verify the configured serial port is accessible; auto-detect if missing
        if not os.path.exists(port):
            logger.warning(
                f"Zigbee serial port {port} does not exist — attempting auto-detection."
            )
            candidates = detect_zigbee_coordinator()
            if candidates:
                detected_port = candidates[0]['port']
                detected_desc = candidates[0].get('description', '')
                logger.info(
                    f"Auto-detected Zigbee coordinator: {detected_port} ({detected_desc}). "
                    "Update Hardware Settings to make this permanent."
                )
                port = detected_port
            else:
                logger.warning(
                    "No Zigbee coordinator detected. Connect a coordinator and check hardware settings."
                )
                if redis_client:
                    try:
                        redis_client.setex(
                            "zigbee:coordinator",
                            30,
                            json.dumps({
                                "enabled": True,
                                "port": zigbee_settings.get('port', '/dev/ttyAMA0'),
                                "baudrate": baudrate,
                                "channel": channel,
                                "pan_id": pan_id,
                                "status": "port_not_found",
                                "port_accessible": False,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                        )
                    except Exception:
                        pass
                return None

        # Verify the serial port can actually be opened (not just that the path exists)
        port_usable = False
        try:
            import serial
            ser = serial.Serial(port, baudrate, timeout=1)
            ser.close()
            port_usable = True
        except ImportError:
            logger.warning("pyserial not installed - cannot verify Zigbee serial port")
            port_usable = True  # Assume usable if we can't test
        except Exception as e:
            logger.warning(
                f"Zigbee serial port {port} exists but cannot be opened: {e}. "
                "Check permissions (user must be in 'dialout' group) and that "
                "no other process is using the port."
            )

        # Publish Zigbee coordinator config to Redis so the web UI can display status
        status = "configured" if port_usable else "port_open_failed"
        if redis_client:
            try:
                redis_client.setex(
                    "zigbee:coordinator",
                    30,  # Short TTL - refreshed by publish_zigbee_status() every 5s
                    json.dumps({
                        "enabled": True,
                        "port": port,
                        "baudrate": baudrate,
                        "channel": channel,
                        "pan_id": pan_id,
                        "status": status,
                        "port_accessible": port_usable,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                )
            except Exception as e:
                logger.debug(f"Failed to publish Zigbee config to Redis: {e}")

        if not port_usable:
            logger.warning(
                f"⚠️  Zigbee coordinator configured on {port} but port is not usable"
            )
            return None

        logger.info(
            f"✅ Zigbee coordinator configured on {port} "
            f"(channel {channel}, PAN ID {pan_id})"
        )
        # Start the zigpy protocol stack in a background thread
        try:
            db_path = os.environ.get(
                'ZIGBEE_DB_PATH',
                '/var/lib/eas-station/zigbee.db'
            )
            controller = ZigpyController(
                port, baudrate, channel, pan_id, redis_client, db_path
            )
            controller.start()
            logger.info("Zigpy coordinator stack starting in background…")
            return controller
        except Exception as e:
            logger.warning(f"Could not start zigpy controller: {e}")
            return None

    except Exception as e:
        logger.warning(f"⚠️  Zigbee coordinator not available: {e}")
        logger.info("Continuing without Zigbee support")
        return None


def publish_zigbee_status(redis_client) -> None:
    """Refresh Zigbee coordinator status in Redis.

    The initial publish in ``initialize_zigbee_coordinator()`` uses a 120s
    TTL.  This function is called periodically from the health check loop
    to keep the key alive so the web UI always has current coordinator
    status.
    """
    if not redis_client:
        return

    try:
        from app_core.hardware_settings import get_zigbee_settings

        zigbee_settings = get_zigbee_settings()
        if not zigbee_settings.get('enabled', False):
            return

        port = zigbee_settings.get('port', '/dev/ttyAMA0')
        baudrate = zigbee_settings.get('baudrate', 115200)
        channel = zigbee_settings.get('channel', 15)
        pan_id = zigbee_settings.get('pan_id', '0x1A62')

        # Check if the serial port is still accessible
        port_accessible = os.path.exists(port)

        redis_client.setex(
            "zigbee:coordinator",
            30,  # 30 second TTL (6x the 5s publish interval for tolerance)
            json.dumps({
                "enabled": True,
                "port": port,
                "baudrate": baudrate,
                "channel": channel,
                "pan_id": pan_id,
                "status": "configured" if port_accessible else "port_unavailable",
                "port_accessible": port_accessible,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        )
    except Exception as e:
        logger.debug(f"Failed to publish Zigbee status: {e}")
