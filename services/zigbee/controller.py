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

"""Zigpy-znp coordinator background controller."""

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ZigpyController:
    """Runs the zigpy-znp coordinator stack in a background asyncio thread.

    Handles permit_join (pairing mode), publishes device and status data
    to Redis so the web UI can display live information.
    """

    def __init__(self, port, baudrate, channel, pan_id, redis_client, db_path):
        self.port = port
        self.baudrate = int(baudrate)
        self.channel = int(channel)
        # Accept pan_id as hex string ("0x1A62") or int
        if isinstance(pan_id, str):
            self.pan_id = int(pan_id, 16) if pan_id.lower().startswith('0x') else int(pan_id)
        else:
            self.pan_id = int(pan_id)
        self._redis = redis_client
        self._db_path = db_path
        self._app = None
        self._loop = None
        self._thread = None
        self._running = False
        self._starting = False
        self._permit_join_active = False
        self._permit_join_deadline = None  # UTC timestamp float
        self._permit_join_timer = None

    # ------------------------------------------------------------------ start/stop

    def start(self):
        self._starting = True
        self._publish_status()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name='zigpy-controller'
        )
        self._thread.start()

    def stop(self):
        if self._permit_join_timer:
            self._permit_join_timer.cancel()
        if self._loop and self._app and self._running:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._app.shutdown(), self._loop
                ).result(timeout=10)
            except Exception as e:
                logger.warning(f"Zigpy shutdown error: {e}")
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._running = False

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_app())
            if self._running:
                self._loop.run_forever()
        except Exception as e:
            logger.error(f"Zigpy controller fatal error: {e}", exc_info=True)
        finally:
            self._running = False
            self._starting = False
            self._publish_status()

    async def _start_app(self):
        try:
            from zigpy_znp.zigbee.application import ControllerApplication
        except ImportError:
            logger.error(
                "zigpy-znp not installed. Run: pip install zigpy zigpy-znp"
            )
            self._starting = False
            return

        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        config = ControllerApplication.SCHEMA({
            "database_path": self._db_path,
            "device": {
                "path": self.port,
                "baudrate": self.baudrate,
            },
        })

        self._app = ControllerApplication(config)
        self._app.add_listener(self)

        try:
            await self._app.startup(auto_form=True)
            self._running = True
            self._starting = False
            logger.info(
                f"Zigpy coordinator running on {self.port} "
                f"(channel {self.channel}, PAN ID {hex(self.pan_id)})"
            )
            self._publish_status()
        except Exception as e:
            logger.error(f"Zigpy startup failed: {e}", exc_info=True)
            self._starting = False
            self._publish_status()

    # ------------------------------------------------------------------ permit join

    def permit_join(self, duration=60):
        """Open the join window for *duration* seconds."""
        if not self._app or not self._running:
            raise RuntimeError("Zigpy coordinator is not running")

        asyncio.run_coroutine_threadsafe(
            self._app.permit_joining(duration), self._loop
        ).result(timeout=10)

        self._permit_join_active = True
        self._permit_join_deadline = datetime.now(timezone.utc).timestamp() + duration

        # Cancel any outstanding auto-close timer
        if self._permit_join_timer:
            self._permit_join_timer.cancel()

        def _auto_close():
            self._permit_join_active = False
            self._permit_join_deadline = None
            self._permit_join_timer = None
            self._publish_status()

        self._permit_join_timer = threading.Timer(duration, _auto_close)
        self._permit_join_timer.daemon = True
        self._permit_join_timer.start()
        self._publish_status()

    def close_join(self):
        """Close the join window immediately."""
        if self._app and self._running:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._app.permit_joining(0), self._loop
                ).result(timeout=10)
            except Exception as e:
                logger.warning(f"Error closing join window: {e}")
        if self._permit_join_timer:
            self._permit_join_timer.cancel()
            self._permit_join_timer = None
        self._permit_join_active = False
        self._permit_join_deadline = None
        self._publish_status()

    # ------------------------------------------------------------------ zigpy callbacks

    def device_joined(self, device):
        logger.info(f"Zigbee device joined: {device.ieee}")
        self._publish_device(device)

    def device_initialized(self, device):
        logger.info(
            f"Zigbee device initialized: {device.ieee} "
            f"model={getattr(device, 'model', None)}"
        )
        self._publish_device(device)

    # ------------------------------------------------------------------ redis helpers

    def _publish_device(self, device):
        if not self._redis:
            return
        try:
            key = f"zigbee:device:{device.ieee}"
            data = {
                "ieee": str(device.ieee),
                "network_address": device.nwk,
                "model": getattr(device, 'model', None),
                "manufacturer": getattr(device, 'manufacturer', None),
                "name": getattr(device, 'model', None) or str(device.ieee),
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }
            self._redis.set(key, json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to publish device to Redis: {e}")

    def _publish_status(self):
        if not self._redis:
            return
        try:
            if self._running:
                status = "running"
            elif self._starting:
                status = "starting"
            else:
                status = "stopped"

            self._redis.setex("zigbee:coordinator", 120, json.dumps({
                "enabled": True,
                "port": self.port,
                "baudrate": self.baudrate,
                "channel": self.channel,
                "pan_id": hex(self.pan_id).upper().replace('X', 'x'),
                "status": status,
                "port_accessible": self._running or self._starting,
                "permit_join_active": self._permit_join_active,
                "permit_join_deadline": self._permit_join_deadline,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception as e:
            logger.debug(f"Failed to publish Zigbee status to Redis: {e}")

    # ------------------------------------------------------------------ properties

    @property
    def running(self):
        return self._running

    @property
    def permit_join_active(self):
        return self._permit_join_active

    @property
    def permit_join_deadline(self):
        return self._permit_join_deadline
