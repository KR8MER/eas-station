#!/usr/bin/env python3
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

"""
Dedicated Hardware Service

This service handles GPIO, displays, and Zigbee hardware:
- GPIO pin control (relays, transmitter keying)
- OLED/LED/VFD display management
- Screen rotation and rendering
- Zigbee coordinator (if configured)
- Hardware status monitoring

Architecture Benefits:
- Fault isolation - display/GPIO issues don't affect SDR
- Independent restart - can restart hardware service without affecting audio
- Clean separation - one service per hardware type
- Better debugging - clear responsibility boundaries

The web UI communicates with this service via HTTP API for hardware control.
"""

import os
import sys
import time
import signal
import logging
import json
import redis
import subprocess
import threading
import ipaddress
from typing import Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, jsonify, request

# Network utilities (extracted for reuse)
from app_utils.network import (
    run_command,
    check_nmcli_available,
    get_wifi_interface,
    enhance_error_message,
    get_hostname,
    set_hostname,
    HOSTNAME_PATTERN,
)

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Load environment variables from persistent config volume
# This must happen before initializing hardware controllers
_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    if os.path.exists(_config_path):
        load_dotenv(_config_path, override=True)
        logger.info(f"✅ Loaded environment from: {_config_path}")
    else:
        logger.warning(f"⚠️  CONFIG_PATH set but file not found: {_config_path}")
        load_dotenv(override=True)  # Fall back to default .env
else:
    load_dotenv(override=True)  # Use default .env location

# Global state
_running = True
_redis_client: Optional[redis.Redis] = None
_flask_app: Optional[Flask] = None
_screen_manager = None
_gpio_controller = None
_neopixel_controller = None
_tower_light_controller = None
_gps_manager = None
_zigpy_controller = None


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _running
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _running = False


def get_redis_client() -> redis.Redis:
    """Get or create Redis client with retry logic."""
    global _redis_client

    from app_core.redis_client import get_redis_client as get_robust_client

    try:
        _redis_client = get_robust_client(
            max_retries=5,
            initial_backoff=1.0,
            max_backoff=30.0
        )
        return _redis_client
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
        raise


def initialize_database():
    """Initialize database connection for hardware configuration."""
    from app_core.extensions import db
    from flask import Flask

    # Create minimal Flask app for database access
    app = Flask(__name__)

    # Database configuration
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    db.init_app(app)
    return app, db


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


# Known Zigbee coordinator USB device signatures (vid, pid, label)
# Used for auto-detection via pyserial and /dev/serial/by-id
_ZIGBEE_USB_SIGNATURES = [
    (0x10c4, 0xea60, "Silicon Labs CP210x — Argon Industria V5 / SONOFF / SMLIGHT / CC2652P"),
    (0x10c4, 0x8a2a, "Silicon Labs CP2105"),
    (0x1cf1, 0x0030, "Dresden Elektronik ConBee II"),
    (0x0451, 0x16a8, "Texas Instruments CC2531"),
    (0x1a86, 0x7523, "CH340 USB-Serial"),
    (0x0403, 0x6001, "FTDI FT232R"),
    (0x0403, 0x6015, "FTDI FT231X"),
]

# Substrings in /dev/serial/by-id symlink names that suggest a Zigbee coordinator
_ZIGBEE_BYID_KEYWORDS = [
    "cp210", "silabs", "silicon_labs", "sonoff", "itead", "conbee",
    "dresden", "argon", "smlight", "cc2531", "cc2652", "skyconnect",
]


def detect_zigbee_coordinator():
    """Detect connected Zigbee coordinator USB devices.

    Returns a list of dicts, each with keys:
        port        - device path e.g. /dev/ttyUSB0
        description - human-readable label
        confidence  - 'high' (VID/PID match) or 'medium' (by-id name match)
    Ordered by confidence (high first), then by port path.
    """
    detected = {}  # keyed by port path to avoid duplicates

    # Method 1: pyserial list_ports — gives USB VID/PID, most reliable
    try:
        from serial.tools import list_ports
        for info in list_ports.comports():
            if info.vid is None:
                continue
            for vid, pid, label in _ZIGBEE_USB_SIGNATURES:
                if info.vid == vid and info.pid == pid:
                    detected[info.device] = {
                        'port': info.device,
                        'description': f"{label}",
                        'vid': f"{vid:04x}",
                        'pid': f"{pid:04x}",
                        'confidence': 'high',
                    }
                    break
    except Exception:
        pass

    # Method 2: /dev/serial/by-id symlinks — works without pyserial VID/PID support
    try:
        import glob as _glob
        for symlink in _glob.glob('/dev/serial/by-id/*'):
            real = os.path.realpath(symlink)
            name_lower = os.path.basename(symlink).lower()
            if any(kw in name_lower for kw in _ZIGBEE_BYID_KEYWORDS):
                if real not in detected:
                    detected[real] = {
                        'port': real,
                        'description': os.path.basename(symlink),
                        'confidence': 'medium',
                    }
    except Exception:
        pass

    results = sorted(
        detected.values(),
        key=lambda x: (0 if x['confidence'] == 'high' else 1, x['port'])
    )
    return results


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


def initialize_zigbee_coordinator():
    """Initialize Zigbee coordinator if enabled in hardware settings."""
    try:
        from app_core.hardware_settings import get_zigbee_settings

        zigbee_settings = get_zigbee_settings()
        if not zigbee_settings.get('enabled', False):
            logger.info("Zigbee coordinator disabled (enable in Admin > Hardware Settings)")
            return

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
                if _redis_client:
                    try:
                        _redis_client.setex(
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
                return

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
        if _redis_client:
            try:
                _redis_client.setex(
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

        if port_usable:
            logger.info(
                f"✅ Zigbee coordinator configured on {port} "
                f"(channel {channel}, PAN ID {pan_id})"
            )
            # Start the zigpy protocol stack in a background thread
            try:
                global _zigpy_controller
                db_path = os.environ.get(
                    'ZIGBEE_DB_PATH',
                    '/var/lib/eas-station/zigbee.db'
                )
                _zigpy_controller = ZigpyController(
                    port, baudrate, channel, pan_id, _redis_client, db_path
                )
                _zigpy_controller.start()
                logger.info("Zigpy coordinator stack starting in background…")
            except Exception as e:
                logger.warning(f"Could not start zigpy controller: {e}")
        else:
            logger.warning(
                f"⚠️  Zigbee coordinator configured on {port} but port is not usable"
            )

    except Exception as e:
        logger.warning(f"⚠️  Zigbee coordinator not available: {e}")
        logger.info("Continuing without Zigbee support")


def initialize_gps_manager():
    """Initialize GPS receiver manager (Adafruit Ultimate GPS HAT #2324) if enabled."""
    global _gps_manager

    try:
        from app_core.hardware_settings import get_gps_settings
        from app_core.gps import GPSManager

        gps_settings = get_gps_settings()
        if not gps_settings.get('enabled', False):
            logger.info("GPS receiver disabled (enable in Admin > Hardware Settings)")
            return

        _gps_manager = GPSManager(
            config=gps_settings,
            redis_client=_redis_client,
            logger=logger.getChild("gps"),
        )
        _gps_manager.start()
        # Keep manager alive even on start() failure so get_status() can
        # return the specific error reason (port_not_found, pyserial_missing, etc.)

    except Exception as e:
        logger.warning(f"⚠️  GPS manager not available: {e}")
        logger.info("Continuing without GPS support")


def initialize_screen_manager(app):
    """Initialize screen manager for OLED/LED/VFD displays."""
    global _screen_manager

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

    except Exception as e:
        logger.warning(f"⚠️  Screen manager not available: {e}")
        logger.info("Continuing without display support")


def initialize_gpio_controller(db_session=None):
    """Initialize GPIO controller for relay/transmitter control."""
    global _gpio_controller

    try:
        from app_utils.gpio import (
            GPIOController,
            GPIOBehaviorManager,
            load_gpio_pin_configs_from_db,
            load_gpio_behavior_matrix_from_db,
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
            return

        # Load GPIO pin configurations (from database with env fallback)
        # Pass oled_enabled to ensure reserved pins are only blocked when OLED is actually enabled
        gpio_configs = load_gpio_pin_configs_from_db(logger, oled_enabled=oled_enabled)
        if not gpio_configs:
            logger.info("No GPIO pins configured (configure in Admin > Hardware Settings)")
            return

        # Create GPIO controller with database session for audit logging
        _gpio_controller = GPIOController(
            db_session=db_session,
            logger=logger,
        )

        # Add each configured pin to the controller
        for config in gpio_configs:
            try:
                _gpio_controller.add_pin(config)
            except Exception as e:
                logger.error(f"Failed to add GPIO pin {config.pin}: {e}")

        # Load and configure GPIO behavior matrix
        behavior_matrix = load_gpio_behavior_matrix_from_db(logger, oled_enabled=oled_enabled)
        if behavior_matrix:
            gpio_behavior_manager = GPIOBehaviorManager(
                controller=_gpio_controller,
                pin_configs=gpio_configs,
                behavior_matrix=behavior_matrix,
                logger=logger,
            )
            _gpio_controller.behavior_manager = gpio_behavior_manager
            logger.info(f"✅ GPIO controller initialized with {len(gpio_configs)} pin(s) and behavior matrix")
        else:
            logger.info(f"✅ GPIO controller initialized with {len(gpio_configs)} pin(s)")

    except Exception as e:
        logger.warning(f"⚠️  GPIO controller not available: {e}")
        logger.info("Continuing without GPIO support")


def initialize_tower_light_controller():
    """Initialize USB tower light controller (Adafruit #5125 / CH34x serial)."""
    global _tower_light_controller

    try:
        from app_utils.gpio import TowerLightController, load_tower_light_config_from_db

        config = load_tower_light_config_from_db(logger)
        if config is None:
            logger.info("USB tower light disabled (enable in Admin > Hardware Settings)")
            return

        _tower_light_controller = TowerLightController(config, logger=logger)
        available = _tower_light_controller.start()

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

    except Exception as e:
        logger.warning(f"⚠️  USB tower light not available: {e}")
        logger.info("Continuing without USB tower light support")


def initialize_neopixel_controller():
    """Initialize NeoPixel / WS2812B LED strip controller."""
    global _neopixel_controller

    try:
        from app_utils.gpio import NeopixelController, load_neopixel_config_from_db

        config = load_neopixel_config_from_db(logger)
        if config is None:
            logger.info("NeoPixel controller disabled (enable in Admin > Hardware Settings)")
            return

        _neopixel_controller = NeopixelController(config, logger=logger)
        hardware_available = _neopixel_controller.start()

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

    except Exception as e:
        logger.warning(f"⚠️  NeoPixel controller not available: {e}")
        logger.info("Continuing without NeoPixel support")


def publish_hardware_metrics():
    """Publish hardware status and metrics to Redis.

    IMPORTANT: This is called from health_check_loop() which runs outside any
    Flask app context. Functions that access the database (publish_display_state,
    publish_zigbee_status) require app context for Flask-SQLAlchemy queries.
    We push the app context here so all downstream functions can use the DB.
    """
    if not _redis_client:
        return

    # Push Flask app context for database operations in publish_display_state()
    # and publish_zigbee_status() which call get_*_settings() -> HardwareSettings.query
    if _flask_app:
        ctx = _flask_app.app_context()
        ctx.push()
    else:
        ctx = None

    try:
        metrics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "screen_manager_running": _screen_manager is not None and getattr(_screen_manager, '_running', False),
            "gpio_controller_available": _gpio_controller is not None,
        }

        # Add screen manager metrics if available
        if _screen_manager:
            try:
                metrics["screens"] = {
                    "oled_active": getattr(_screen_manager, '_oled_rotation', None) is not None,
                    "led_active": getattr(_screen_manager, '_led_rotation', None) is not None,
                    "vfd_active": getattr(_screen_manager, '_vfd_rotation', None) is not None,
                }
            except Exception:
                pass

        # Publish basic metrics to Redis
        _redis_client.setex(
            "hardware:metrics",
            60,  # 60 second TTL
            json.dumps(metrics)
        )

        # Publish detailed display state for preview (separate key for larger data)
        publish_display_state()

        # Refresh Zigbee coordinator status in Redis (keeps key alive beyond initial publish)
        publish_zigbee_status()

    except Exception as e:
        logger.debug(f"Failed to publish hardware metrics: {e}")
    finally:
        if ctx is not None:
            ctx.pop()


def publish_display_state():
    """Publish detailed display state including preview images to Redis."""
    if not _redis_client:
        return

    try:
        # Import hardware settings helpers
        from app_core.hardware_settings import get_oled_settings, get_led_settings, get_vfd_settings
        
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
                if _screen_manager and hasattr(_screen_manager, '_current_oled_screen'):
                    current_screen = _screen_manager._current_oled_screen
                    if current_screen:
                        state["oled"]["current_screen"] = current_screen.name if hasattr(current_screen, 'name') else str(current_screen)

                # Get current alert state if scrolling
                if _screen_manager:
                    if hasattr(_screen_manager, '_oled_scroll_effect') and _screen_manager._oled_scroll_effect:
                        state["oled"]["alert_active"] = True
                        state["oled"]["scroll_offset"] = getattr(_screen_manager, '_oled_scroll_offset', 0)
                        state["oled"]["alert_text"] = getattr(_screen_manager, '_current_alert_text', "") or ""
                        state["oled"]["scroll_speed"] = getattr(_screen_manager, '_oled_scroll_speed', 4)

                        # Get cached header
                        if hasattr(_screen_manager, '_cached_header_text'):
                            state["oled"]["header_text"] = _screen_manager._cached_header_text

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
        except Exception as e:
            logger.debug(f"Error getting LED state: {e}")

        # Publish to Redis with short TTL (refreshes every 5 seconds)
        _redis_client.setex(
            "hardware:display_state",
            15,  # 15 second TTL (3x the publish interval for tolerance)
            json.dumps(state)
        )

    except Exception as e:
        logger.debug(f"Failed to publish display state: {e}")


def publish_zigbee_status():
    """Refresh Zigbee coordinator status in Redis.

    The initial publish in initialize_zigbee_coordinator() uses a 120s TTL.
    This function is called periodically from the health check loop to keep
    the key alive so the web UI always has current coordinator status.
    """
    if not _redis_client:
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

        _redis_client.setex(
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


def create_api_app():
    """Create Flask API application for hardware proxy operations."""
    api_app = Flask(__name__)

    @api_app.route('/health', methods=['GET'])
    def health():
        """Health check endpoint."""
        return jsonify({
            'status': 'ok',
            'service': 'hardware-service',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Network Management Proxy Endpoints

    @api_app.route('/api/network/status', methods=['GET'])
    def get_network_status():
        """Get current network connection status via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                logger.error("nmcli not available - NetworkManager may not be installed")
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get WiFi interface
            wifi_interface = get_wifi_interface()
            if not wifi_interface:
                logger.warning("No WiFi interface detected")
                return jsonify({
                    'success': True,
                    'wifi': None,
                    'interfaces': {}
                })

            # Get active WiFi connection on WiFi interface
            result = run_command([
                'nmcli', '-t', '-f', 
                'GENERAL.CONNECTION,GENERAL.STATE,IP4.ADDRESS,IP6.ADDRESS',
                'device', 'show', wifi_interface
            ], check=False, timeout=10)

            wifi_data = None
            interfaces = {}

            if result['success'] and result['stdout']:
                connection_name = None
                state = None
                ipv4_addrs = []
                ipv6_addrs = []

                for line in result['stdout'].split('\n'):
                    if line.strip():
                        if line.startswith('GENERAL.CONNECTION:'):
                            connection_name = line.split(':', 1)[1].strip()
                        elif line.startswith('GENERAL.STATE:'):
                            state = line.split(':', 1)[1].strip()
                        elif line.startswith('IP4.ADDRESS'):
                            addr_str = line.split(':', 1)[1].strip()
                            if addr_str and '/' in addr_str:
                                addr, prefix = addr_str.split('/')
                                ipv4_addrs.append({
                                    'family': 'inet',
                                    'address': addr,
                                    'prefixlen': int(prefix)
                                })
                        elif line.startswith('IP6.ADDRESS'):
                            addr_str = line.split(':', 1)[1].strip()
                            if addr_str and '/' in addr_str:
                                addr, prefix = addr_str.rsplit('/', 1)
                                ipv6_addrs.append({
                                    'family': 'inet6',
                                    'address': addr,
                                    'prefixlen': int(prefix)
                                })

                # Check if WiFi is connected
                if connection_name and connection_name != '--' and state and 'connected' in state.lower():
                    wifi_data = {
                        'ssid': connection_name,
                        'interface': wifi_interface,
                        'state': state
                    }
                    
                    # Add IP addresses to interfaces dict
                    if ipv4_addrs or ipv6_addrs:
                        interfaces[wifi_interface] = ipv4_addrs + ipv6_addrs

            return jsonify({
                'success': True,
                'wifi': wifi_data,
                'interfaces': interfaces
            })

        except Exception as e:
            logger.error(f"Error getting network status: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/scan', methods=['POST'])
    def scan_wifi():
        """Scan for available WiFi networks via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                logger.error("nmcli not available for WiFi scan")
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get WiFi interface
            wifi_interface = get_wifi_interface()
            if not wifi_interface:
                logger.error("No WiFi interface detected for scan")
                return jsonify({
                    'success': False,
                    'error': 'No WiFi interface found. Check if WiFi hardware is available.'
                }), 500

            logger.info(f"Starting WiFi scan on interface {wifi_interface}...")

            # Rescan networks on specific interface
            rescan_result = run_command(
                ['nmcli', 'device', 'wifi', 'rescan', 'ifname', wifi_interface],
                check=False,
                timeout=15
            )

            # Check if rescan failed
            if not rescan_result['success']:
                # Note: rescan often returns exit code 10 but still works
                # Only fail if there's a real error message
                if rescan_result.get('stderr') and 'not found' in rescan_result['stderr'].lower():
                    logger.error(f"WiFi rescan failed: {rescan_result.get('error', 'Unknown error')}")
                    return jsonify({
                        'success': False,
                        'error': f"WiFi scan failed: {rescan_result.get('stderr', 'Unknown error')}"
                    }), 500

            # Wait for scan to complete - use multiple shorter waits to check for completion
            max_wait = 10  # Maximum 10 seconds
            wait_interval = 1  # Check every 1 second
            waited = 0
            
            while waited < max_wait:
                time.sleep(wait_interval)
                waited += wait_interval
                
                # Try to get scan results
                list_result = run_command(
                    ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY,IN-USE', 'device', 'wifi', 'list', 'ifname', wifi_interface],
                    check=False,
                    timeout=10
                )
                
                # If we got results with content, break early
                if list_result['success'] and list_result['stdout']:
                    break

            # Get list of available networks
            result = run_command(
                ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY,IN-USE', 'device', 'wifi', 'list', 'ifname', wifi_interface],
                check=False,
                timeout=10
            )

            if not result['success']:
                logger.error(f"Failed to get WiFi list: {result.get('error', 'Unknown error')}")
                return jsonify({
                    'success': False,
                    'error': f"Failed to get WiFi networks: {result.get('stderr', result.get('error', 'Unknown error'))}"
                }), 500

            networks = []
            seen_ssids = set()  # Deduplicate networks (same SSID on multiple BSSIDs)

            if result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        parts = line.split(':')
                        if len(parts) >= 4:
                            ssid = parts[0].strip()
                            
                            # Skip empty SSIDs (hidden networks)
                            if not ssid or ssid == '--':
                                continue
                            
                            # Skip duplicates (keep the one with strongest signal)
                            if ssid in seen_ssids:
                                # Find existing network and update if this signal is stronger
                                for net in networks:
                                    if net['ssid'] == ssid:
                                        new_signal = int(parts[1]) if parts[1].isdigit() else 0
                                        if new_signal > net['signal']:
                                            net['signal'] = new_signal
                                            net['security'] = parts[2]
                                            net['in_use'] = parts[3] == '*'
                                        break
                                continue
                            
                            seen_ssids.add(ssid)
                            networks.append({
                                'ssid': ssid,
                                'signal': int(parts[1]) if parts[1].isdigit() else 0,
                                'security': parts[2],
                                'in_use': parts[3] == '*'
                            })

            # Sort networks by signal strength (strongest first)
            networks.sort(key=lambda x: x['signal'], reverse=True)

            logger.info(f"WiFi scan completed: found {len(networks)} networks")

            if not networks:
                logger.warning("WiFi scan returned no networks - this may indicate no networks in range or a hardware issue")

            return jsonify({
                'success': True,
                'networks': networks,
                'interface': wifi_interface
            })

        except Exception as e:
            logger.error(f"Error scanning WiFi: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connect', methods=['POST'])
    def connect_wifi():
        """Connect to a WiFi network via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            ssid = data.get('ssid')
            password = data.get('password', '')

            if not ssid:
                return jsonify({'success': False, 'error': 'SSID required'}), 400

            # Get WiFi interface
            wifi_interface = get_wifi_interface()
            if not wifi_interface:
                logger.warning("No WiFi interface detected, attempting connection anyway")

            logger.info(f"Attempting to connect to WiFi network: {ssid}")

            # Build nmcli command safely using list (prevents command injection)
            if password:
                cmd = ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password]
            else:
                cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]

            result = run_command(cmd, check=False, timeout=30)

            if result['success']:
                logger.info(f"Successfully connected to {ssid}")
                return jsonify({
                    'success': True,
                    'message': f'Connected to {ssid}'
                })
            else:
                error_msg = result.get('stderr', result.get('error', 'Connection failed'))
                logger.error(f"Failed to connect to {ssid}: {error_msg}")
                enhanced = enhance_error_message(error_msg, 'connect')
                return jsonify({
                    'success': False,
                    'error': enhanced['message'],
                    'hint': enhanced.get('hint', ''),
                    'technical': enhanced.get('technical', '')
                })

        except Exception as e:
            logger.error(f"Error connecting to WiFi: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/disconnect', methods=['POST'])
    def disconnect_network():
        """Disconnect from current network via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get WiFi interface
            wifi_interface = get_wifi_interface()
            if not wifi_interface:
                return jsonify({
                    'success': False,
                    'error': 'No WiFi interface found'
                }), 500

            # Get active connection on WiFi interface
            result = run_command([
                'nmcli', '-t', '-f', 'GENERAL.CONNECTION',
                'device', 'show', wifi_interface
            ], check=False, timeout=10)

            connection_name = None
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.startswith('GENERAL.CONNECTION:'):
                        connection_name = line.split(':', 1)[1].strip()
                        break

            if not connection_name or connection_name == '--':
                return jsonify({
                    'success': False,
                    'error': 'No active WiFi connection to disconnect'
                }), 400

            logger.info(f"Disconnecting from WiFi network: {connection_name}")

            # Disconnect using connection name
            cmd = ['nmcli', 'connection', 'down', connection_name]
            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                logger.info(f"Successfully disconnected from {connection_name}")
                return jsonify({
                    'success': True,
                    'message': f'Disconnected from {connection_name}'
                })
            else:
                logger.error(f"Failed to disconnect: {result.get('stderr', result.get('error', 'Unknown error'))}")
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to disconnect'))
                })

        except Exception as e:
            logger.error(f"Error disconnecting network: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/forget', methods=['POST'])
    def forget_network():
        """Forget a saved network connection via nmcli."""
        try:
            # Check if nmcli is available
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection_name = data.get('connection')

            if not connection_name:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Forgetting WiFi network: {connection_name}")

            # Use list arguments to prevent command injection
            cmd = ['nmcli', 'connection', 'delete', connection_name]
            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                logger.info(f"Successfully forgot network {connection_name}")
                return jsonify({
                    'success': True,
                    'message': f'Forgot network {connection_name}'
                })
            else:
                logger.error(f"Failed to forget network: {result.get('stderr', result.get('error', 'Unknown error'))}")
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to forget network'))
                })

        except Exception as e:
            logger.error(f"Error forgetting network: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # Phase 2: Core DASDEC3 Network Features

    @api_app.route('/api/network/interfaces', methods=['GET'])
    def get_network_interfaces():
        """Get all network interfaces (both WiFi and Ethernet)."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get all devices with their types and states
            result = run_command([
                'nmcli', '-t', '-f',
                'DEVICE,TYPE,STATE,CONNECTION',
                'device'
            ], check=False, timeout=10)

            interfaces = []
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        parts = line.split(':')
                        if len(parts) >= 4:
                            device = parts[0]
                            iface_type = parts[1]
                            state = parts[2]
                            connection = parts[3] if parts[3] != '--' else None

                            # Get detailed info for this interface
                            detail_result = run_command([
                                'nmcli', '-t', '-f',
                                'IP4.ADDRESS,IP4.GATEWAY,IP6.ADDRESS',
                                'device', 'show', device
                            ], check=False, timeout=10)

                            ipv4_addrs = []
                            ipv4_gateway = None
                            ipv6_addrs = []

                            if detail_result['success'] and detail_result['stdout']:
                                for detail_line in detail_result['stdout'].split('\n'):
                                    if detail_line.startswith('IP4.ADDRESS'):
                                        addr_str = detail_line.split(':', 1)[1].strip()
                                        if addr_str and '/' in addr_str:
                                            addr, prefix = addr_str.split('/')
                                            ipv4_addrs.append({
                                                'address': addr,
                                                'prefixlen': int(prefix)
                                            })
                                    elif detail_line.startswith('IP4.GATEWAY'):
                                        ipv4_gateway = detail_line.split(':', 1)[1].strip()
                                    elif detail_line.startswith('IP6.ADDRESS'):
                                        addr_str = detail_line.split(':', 1)[1].strip()
                                        if addr_str and '/' in addr_str:
                                            addr, prefix = addr_str.rsplit('/', 1)
                                            ipv6_addrs.append({
                                                'address': addr,
                                                'prefixlen': int(prefix)
                                            })

                            interfaces.append({
                                'device': device,
                                'type': iface_type,
                                'state': state,
                                'connection': connection,
                                'ipv4_addresses': ipv4_addrs,
                                'ipv4_gateway': ipv4_gateway,
                                'ipv6_addresses': ipv6_addrs
                            })

            return jsonify({
                'success': True,
                'interfaces': interfaces
            })

        except Exception as e:
            logger.error(f"Error getting network interfaces: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/interface/configure', methods=['POST'])
    def configure_interface():
        """Configure network interface with static IP or DHCP."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')
            method = data.get('method', 'auto')  # 'auto' (DHCP) or 'manual' (static)
            ip_address = data.get('ip_address')
            netmask = data.get('netmask')
            gateway = data.get('gateway')

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Configuring interface {connection} with method {method}")

            if method == 'manual':
                # Static IP configuration
                if not ip_address or not netmask:
                    return jsonify({
                        'success': False,
                        'error': 'IP address and netmask required for static configuration'
                    }), 400

                # Calculate CIDR prefix from netmask
                try:
                    prefix = ipaddress.IPv4Network(f'0.0.0.0/{netmask}').prefixlen
                except ValueError:
                    return jsonify({
                        'success': False,
                        'error': 'Invalid netmask format'
                    }), 400

                # Set static IP
                cmd = [
                    'nmcli', 'connection', 'modify', connection,
                    'ipv4.method', 'manual',
                    'ipv4.addresses', f'{ip_address}/{prefix}'
                ]

                if gateway:
                    cmd.extend(['ipv4.gateway', gateway])

                result = run_command(cmd, check=False, timeout=15)

                if not result['success']:
                    return jsonify({
                        'success': False,
                        'error': result.get('stderr', result.get('error', 'Failed to configure static IP'))
                    })

            else:
                # DHCP configuration
                cmd = [
                    'nmcli', 'connection', 'modify', connection,
                    'ipv4.method', 'auto',
                    'ipv4.addresses', '',
                    'ipv4.gateway', ''
                ]
                result = run_command(cmd, check=False, timeout=15)

                if not result['success']:
                    return jsonify({
                        'success': False,
                        'error': result.get('stderr', result.get('error', 'Failed to configure DHCP'))
                    })

            # Restart connection to apply changes
            restart_cmd = ['nmcli', 'connection', 'up', connection]
            restart_result = run_command(restart_cmd, check=False, timeout=20)

            if restart_result['success']:
                logger.info(f"Successfully configured {connection} with {method}")
                return jsonify({
                    'success': True,
                    'message': f'Interface configured with {method}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Configuration saved but failed to restart connection'
                })

        except Exception as e:
            logger.error(f"Error configuring interface: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/dns', methods=['GET'])
    def get_dns_servers():
        """Get current DNS server configuration."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get DNS servers from active connections
            result = run_command([
                'nmcli', '-t', '-f', 'IP4.DNS,IP6.DNS',
                'device', 'show'
            ], check=False, timeout=10)

            dns_servers = []
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip() and (line.startswith('IP4.DNS') or line.startswith('IP6.DNS')):
                        server = line.split(':', 1)[1].strip()
                        if server and server not in dns_servers:
                            dns_servers.append(server)

            return jsonify({
                'success': True,
                'dns_servers': dns_servers
            })

        except Exception as e:
            logger.error(f"Error getting DNS servers: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/dns/configure', methods=['POST'])
    def configure_dns():
        """Configure DNS servers for a connection."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')
            dns_servers = data.get('dns_servers', [])

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            # Validate DNS servers are valid IP addresses
            if dns_servers:
                for server in dns_servers:
                    try:
                        ipaddress.ip_address(server)
                    except ValueError:
                        return jsonify({
                            'success': False,
                            'error': f'Invalid DNS server IP address: {server}'
                        }), 400

            logger.info(f"Configuring DNS servers for {connection}")

            # Set DNS servers (space-separated list)
            dns_list = ' '.join(dns_servers) if dns_servers else ''
            cmd = [
                'nmcli', 'connection', 'modify', connection,
                'ipv4.dns', dns_list
            ]

            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                # Restart connection to apply changes
                restart_cmd = ['nmcli', 'connection', 'up', connection]
                restart_result = run_command(restart_cmd, check=False, timeout=20)

                if restart_result['success']:
                    logger.info(f"Successfully configured DNS for {connection}")
                    return jsonify({
                        'success': True,
                        'message': 'DNS servers configured'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'DNS configuration saved but failed to restart connection'
                    })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to configure DNS'))
                })

        except Exception as e:
            logger.error(f"Error configuring DNS: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/ping', methods=['POST'])
    def ping_host():
        """Ping a host to test connectivity."""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            host = data.get('host')
            count = data.get('count', 4)

            if not host:
                return jsonify({'success': False, 'error': 'Host required'}), 400

            # Validate count is reasonable
            try:
                count = int(count)
                if count < 1 or count > 10:
                    count = 4
            except ValueError:
                count = 4

            logger.info(f"Pinging {host} ({count} packets)")

            # Use ping command (works on most Linux systems)
            cmd = ['ping', '-c', str(count), '-W', '2', host]
            result = run_command(cmd, check=False, timeout=30)

            return jsonify({
                'success': result['success'],
                'output': result.get('stdout', ''),
                'error': result.get('stderr', '') if not result['success'] else None
            })

        except Exception as e:
            logger.error(f"Error pinging host: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/traceroute', methods=['POST'])
    def traceroute_host():
        """Traceroute to a host to see network path."""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            host = data.get('host')

            if not host:
                return jsonify({'success': False, 'error': 'Host required'}), 400

            logger.info(f"Traceroute to {host}")

            # Use traceroute command (may need to be installed)
            # Try traceroute first, fall back to tracepath
            cmd = ['traceroute', '-m', '15', '-w', '2', host]
            result = run_command(cmd, check=False, timeout=60)

            if not result['success'] and 'not found' in result.get('error', '').lower():
                # Try tracepath as fallback
                cmd = ['tracepath', '-m', '15', host]
                result = run_command(cmd, check=False, timeout=60)

            return jsonify({
                'success': result['success'],
                'output': result.get('stdout', ''),
                'error': result.get('stderr', '') if not result['success'] else None
            })

        except Exception as e:
            logger.error(f"Error traceroute: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/nslookup', methods=['POST'])
    def nslookup_host():
        """DNS lookup for a hostname."""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            host = data.get('host')

            if not host:
                return jsonify({'success': False, 'error': 'Host required'}), 400

            logger.info(f"DNS lookup for {host}")

            # Use nslookup or dig
            cmd = ['nslookup', host]
            result = run_command(cmd, check=False, timeout=15)

            if not result['success'] and 'not found' in result.get('error', '').lower():
                # Try dig as fallback
                cmd = ['dig', '+short', host]
                result = run_command(cmd, check=False, timeout=15)

            return jsonify({
                'success': result['success'],
                'output': result.get('stdout', ''),
                'error': result.get('stderr', '') if not result['success'] else None
            })

        except Exception as e:
            logger.error(f"Error DNS lookup: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/route', methods=['GET'])
    def get_routing_table():
        """Get system routing table."""
        try:
            logger.info("Getting routing table")

            # Use ip route command
            cmd = ['ip', 'route', 'show']
            result = run_command(cmd, check=False, timeout=10)

            if result['success']:
                return jsonify({
                    'success': True,
                    'output': result.get('stdout', '')
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to get routing table'))
                })

        except Exception as e:
            logger.error(f"Error getting routing table: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/diagnostics/gateway', methods=['GET'])
    def get_default_gateway():
        """Get default gateway information."""
        try:
            logger.info("Getting default gateway")

            # Get default route
            cmd = ['ip', 'route', 'show', 'default']
            result = run_command(cmd, check=False, timeout=10)

            gateway = None
            interface = None

            if result['success'] and result['stdout']:
                # Parse output: "default via 192.168.1.1 dev eth0"
                parts = result['stdout'].split()
                if 'via' in parts:
                    gateway_idx = parts.index('via') + 1
                    if gateway_idx < len(parts):
                        gateway = parts[gateway_idx]
                if 'dev' in parts:
                    dev_idx = parts.index('dev') + 1
                    if dev_idx < len(parts):
                        interface = parts[dev_idx]

            return jsonify({
                'success': True,
                'gateway': gateway,
                'interface': interface,
                'raw_output': result.get('stdout', '')
            })

        except Exception as e:
            logger.error(f"Error getting default gateway: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connections', methods=['GET'])
    def get_connections():
        """Get all saved NetworkManager connections."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            # Get all connections with details
            result = run_command([
                'nmcli', '-t', '-f',
                'NAME,TYPE,DEVICE,AUTOCONNECT',
                'connection', 'show'
            ], check=False, timeout=10)

            connections = []
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        parts = line.split(':')
                        if len(parts) >= 4:
                            connections.append({
                                'name': parts[0],
                                'type': parts[1],
                                'device': parts[2] if parts[2] != '--' else None,
                                'autoconnect': parts[3] == 'yes'
                            })

            return jsonify({
                'success': True,
                'connections': connections
            })

        except Exception as e:
            logger.error(f"Error getting connections: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connection/activate', methods=['POST'])
    def activate_connection():
        """Activate a saved connection."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Activating connection: {connection}")

            cmd = ['nmcli', 'connection', 'up', connection]
            result = run_command(cmd, check=False, timeout=20)

            if result['success']:
                logger.info(f"Successfully activated {connection}")
                return jsonify({
                    'success': True,
                    'message': f'Activated {connection}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to activate connection'))
                })

        except Exception as e:
            logger.error(f"Error activating connection: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connection/deactivate', methods=['POST'])
    def deactivate_connection():
        """Deactivate an active connection."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Deactivating connection: {connection}")

            cmd = ['nmcli', 'connection', 'down', connection]
            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                logger.info(f"Successfully deactivated {connection}")
                return jsonify({
                    'success': True,
                    'message': f'Deactivated {connection}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to deactivate connection'))
                })

        except Exception as e:
            logger.error(f"Error deactivating connection: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connection/autoconnect', methods=['POST'])
    def set_connection_autoconnect():
        """Set autoconnect status for a connection."""
        try:
            if not check_nmcli_available():
                return jsonify({
                    'success': False,
                    'error': 'NetworkManager (nmcli) not available'
                }), 500

            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            connection = data.get('connection')
            autoconnect = data.get('autoconnect', True)

            if not connection:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            logger.info(f"Setting autoconnect for {connection} to {autoconnect}")

            cmd = [
                'nmcli', 'connection', 'modify', connection,
                'connection.autoconnect', 'yes' if autoconnect else 'no'
            ]
            result = run_command(cmd, check=False, timeout=15)

            if result['success']:
                logger.info(f"Successfully set autoconnect for {connection}")
                return jsonify({
                    'success': True,
                    'message': f'Autoconnect {"enabled" if autoconnect else "disabled"}'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': result.get('stderr', result.get('error', 'Failed to set autoconnect'))
                })

        except Exception as e:
            logger.error(f"Error setting autoconnect: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # Zigbee Serial Port Proxy Endpoints

    @api_app.route('/api/zigbee/ports', methods=['GET'])
    def list_serial_ports():
        """List available serial ports for Zigbee coordinator."""
        try:
            import serial.tools.list_ports
            port_objects = []
            for p in sorted(serial.tools.list_ports.comports(), key=lambda x: x.device):
                if any(p.device.startswith(prefix) for prefix in ('/dev/ttyUSB', '/dev/ttyACM', '/dev/ttyAMA')):
                    port_objects.append({
                        'device': p.device,
                        'description': p.description or p.device,
                    })
            return jsonify({
                'success': True,
                'ports': port_objects,
            })
        except Exception as e:
            logger.error(f"Error listing serial ports: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/zigbee/test_port', methods=['POST'])
    def test_serial_port():
        """Test if a serial port is accessible."""
        try:
            data = request.json
            port = data.get('port')

            if not port:
                return jsonify({'success': False, 'error': 'Port required'}), 400

            # If the zigpy controller is running on this exact port, it holds the
            # serial lock — report it as accessible rather than "busy".
            if (_zigpy_controller and _zigpy_controller.port == port
                    and (_zigpy_controller.running or _zigpy_controller._starting)):
                return jsonify({
                    'success': True,
                    'accessible': True,
                    'message': 'Port in use by Zigbee coordinator',
                })

            if os.path.exists(port):
                import serial
                try:
                    ser = serial.Serial(port, 115200, timeout=1)
                    ser.close()
                    return jsonify({'success': True, 'accessible': True, 'message': 'Port accessible'})
                except serial.SerialException as e:
                    return jsonify({'success': False, 'accessible': False, 'error': f'Cannot open port: {str(e)}'})
            else:
                return jsonify({'success': False, 'accessible': False, 'error': 'Port does not exist'})

        except Exception as e:
            logger.error(f"Error testing serial port: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/zigbee/detect', methods=['GET'])
    def detect_zigbee_port():
        """Auto-detect Zigbee coordinator USB devices by VID/PID and /dev/serial/by-id.

        Add ?debug=1 to return full diagnostic information including all ports seen
        by pyserial, all /dev/serial/by-id entries, and any errors encountered.
        """
        debug = request.args.get('debug', '').lower() in ('1', 'true', 'yes')
        try:
            if not debug:
                results = detect_zigbee_coordinator()
                return jsonify({
                    'success': True,
                    'devices': results,
                    'count': len(results),
                })

            # Debug mode: capture all intermediate data and errors
            diag = {
                'all_serial_ports': [],
                'by_id_entries': [],
                'dev_tty_glob': [],
                'errors': [],
                'matched_devices': [],
            }

            # All ports pyserial can see
            try:
                from serial.tools import list_ports
                for p in list_ports.comports():
                    diag['all_serial_ports'].append({
                        'device': p.device,
                        'description': p.description,
                        'hwid': p.hwid,
                        'vid': f"0x{p.vid:04x}" if p.vid else None,
                        'pid': f"0x{p.pid:04x}" if p.pid else None,
                        'manufacturer': p.manufacturer,
                        'product': p.product,
                        'serial_number': p.serial_number,
                    })
            except ImportError:
                diag['errors'].append("pyserial not installed (pip install pyserial)")
            except Exception as e:
                diag['errors'].append(f"pyserial list_ports error: {e}")

            # /dev/serial/by-id entries
            try:
                import glob as _g
                for sym in sorted(_g.glob('/dev/serial/by-id/*')):
                    diag['by_id_entries'].append({
                        'symlink': sym,
                        'name': os.path.basename(sym),
                        'real_path': os.path.realpath(sym),
                    })
                if not diag['by_id_entries']:
                    diag['by_id_entries'] = []
            except Exception as e:
                diag['errors'].append(f"/dev/serial/by-id scan error: {e}")

            # Raw /dev/tty* globs
            try:
                import glob as _g
                for pattern in ('/dev/ttyUSB*', '/dev/ttyACM*', '/dev/ttyAMA*', '/dev/ttyS*'):
                    diag['dev_tty_glob'].extend(sorted(_g.glob(pattern)))
            except Exception as e:
                diag['errors'].append(f"/dev/tty glob error: {e}")

            # VID/PID signatures we're scanning for
            diag['known_signatures'] = [
                {'vid': f"0x{v:04x}", 'pid': f"0x{p:04x}", 'label': l}
                for v, p, l in _ZIGBEE_USB_SIGNATURES
            ]
            diag['known_byid_keywords'] = _ZIGBEE_BYID_KEYWORDS

            diag['matched_devices'] = detect_zigbee_coordinator()

            return jsonify({'success': True, 'debug': diag})

        except Exception as e:
            logger.error(f"Error detecting Zigbee coordinator: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/zigbee/permit_join', methods=['POST'])
    def api_permit_join():
        """Open the Zigbee join window so new devices can pair.

        Body (JSON): { "duration": 60 }   — duration in seconds (1-254, default 60)
        """
        try:
            if not _zigpy_controller:
                return jsonify({'success': False, 'error': 'Zigbee coordinator not initialised'}), 503
            body = request.get_json(silent=True) or {}
            duration = int(body.get('duration', 60))
            duration = max(1, min(duration, 254))
            _zigpy_controller.permit_join(duration)
            return jsonify({
                'success': True,
                'permit_join_active': True,
                'duration': duration,
                'deadline': _zigpy_controller.permit_join_deadline,
            })
        except RuntimeError as e:
            return jsonify({'success': False, 'error': str(e)}), 503
        except Exception as e:
            logger.error(f"permit_join error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/zigbee/permit_join', methods=['DELETE'])
    def api_close_join():
        """Close the Zigbee join window immediately."""
        try:
            if not _zigpy_controller:
                return jsonify({'success': False, 'error': 'Zigbee coordinator not initialised'}), 503
            _zigpy_controller.close_join()
            return jsonify({'success': True, 'permit_join_active': False})
        except Exception as e:
            logger.error(f"close_join error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/zigbee/join_status', methods=['GET'])
    def api_join_status():
        """Return current join-window state."""
        try:
            if not _zigpy_controller:
                return jsonify({'success': True, 'running': False, 'permit_join_active': False})
            return jsonify({
                'success': True,
                'running': _zigpy_controller.running,
                'permit_join_active': _zigpy_controller.permit_join_active,
                'deadline': _zigpy_controller.permit_join_deadline,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # Hostname Configuration Endpoints

    @api_app.route('/api/network/hostname', methods=['GET'])
    def api_get_hostname():
        """Get the current system hostname."""
        try:
            result = get_hostname()
            if result['success']:
                return jsonify(result)
            else:
                return jsonify(result), 500
        except Exception as e:
            logger.error(f"Error getting hostname: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/hostname', methods=['POST'])
    def api_set_hostname():
        """Set the system hostname."""
        try:
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

            new_hostname = data.get('hostname')
            if not new_hostname:
                return jsonify({'success': False, 'error': 'Hostname required'}), 400

            result = set_hostname(new_hostname)
            if result['success']:
                return jsonify(result)
            else:
                return jsonify(result), 400

        except Exception as e:
            logger.error(f"Error setting hostname: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # GPS Hardware Endpoints

    @api_app.route('/api/hardware/gps/status', methods=['GET'])
    def get_gps_status():
        """Return current GPS fix status from the GPS manager or Redis."""
        try:
            # Try live status from running manager first
            if _gps_manager is not None:
                return jsonify(_gps_manager.get_status())

            # Fall back to last-known status from Redis
            if _redis_client:
                try:
                    raw = _redis_client.get('gps:status')
                    if raw:
                        return jsonify(json.loads(raw))
                except Exception:
                    pass

            # GPS not configured or not started
            from app_core.hardware_settings import get_gps_settings
            gps_settings = get_gps_settings()
            return jsonify({
                'running': False,
                'has_fix': False,
                'status': 'disabled' if not gps_settings.get('enabled') else 'not_started',
                'serial_port': gps_settings.get('serial_port', '/dev/serial0'),
                'baudrate': gps_settings.get('baudrate', 9600),
                'pps_gpio_pin': gps_settings.get('pps_gpio_pin', 4),
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error(f"Error getting GPS status: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/hardware/gps/configure', methods=['POST'])
    def configure_gps():
        """Save GPS configuration and restart the GPS manager."""
        try:
            data = request.json or {}

            from app_core.hardware_settings import get_hardware_settings, update_hardware_settings

            settings = get_hardware_settings()
            update_fields = {}

            if 'enabled' in data:
                update_fields['gps_enabled'] = bool(data['enabled'])
            if 'serial_port' in data:
                update_fields['gps_serial_port'] = str(data['serial_port'])
            if 'baudrate' in data:
                update_fields['gps_baudrate'] = int(data['baudrate'])
            if 'pps_gpio_pin' in data:
                update_fields['gps_pps_gpio_pin'] = int(data['pps_gpio_pin'])
            if 'use_for_location' in data:
                update_fields['gps_use_for_location'] = bool(data['use_for_location'])
            if 'use_for_time' in data:
                update_fields['gps_use_for_time'] = bool(data['use_for_time'])
            if 'min_satellites' in data:
                update_fields['gps_min_satellites'] = max(1, int(data['min_satellites']))

            if update_fields:
                update_hardware_settings(update_fields)

            # Restart GPS manager with new settings
            global _gps_manager
            if _gps_manager is not None:
                _gps_manager.stop()
                _gps_manager = None

            if update_fields.get('gps_enabled', settings.gps_enabled):
                with api_app.app_context() if hasattr(api_app, 'app_context') else _flask_app.app_context():
                    initialize_gps_manager()

            return jsonify({'success': True, 'message': 'GPS configuration saved'})

        except Exception as e:
            logger.error(f"Error configuring GPS: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    # ------------------------------------------------------------------
    # Display push endpoint
    # Called by the web service (port 5000) to push a configured screen
    # to OLED / LED / VFD hardware without the web worker touching I2C
    # directly (which deadlocks the gevent event loop).
    # ------------------------------------------------------------------

    @api_app.route('/api/hardware/display/push', methods=['POST'])
    def push_screen_to_display():
        """Render a DisplayScreen and push it to the physical display.

        The web service proxies POST /api/screens/<id>/display here so that
        all blocking I2C / GPIO / serial ioctl() calls happen in this process
        (eas-station-hardware.service), never in the gevent web workers.

        Request body (JSON): { "screen_id": <int> }
        """
        try:
            data = request.json or {}
            screen_id = data.get('screen_id')
            if not screen_id:
                return jsonify({'success': False, 'error': 'screen_id is required'}), 400

            with _flask_app.app_context():
                from app_core.models import DisplayScreen
                from scripts.screen_renderer import ScreenRenderer

                screen = DisplayScreen.query.get(int(screen_id))
                if not screen:
                    return jsonify({'success': False, 'error': 'Screen not found'}), 404

                renderer = ScreenRenderer(allow_preview_samples=False)
                rendered = renderer.render_screen(screen.to_dict())
                if not rendered:
                    return jsonify({'success': False, 'error': 'Failed to render screen'}), 500

                if screen.display_type == 'oled':
                    from app_core.oled import oled_controller, OLEDLine
                    if not oled_controller:
                        return jsonify({'success': False, 'error': 'OLED controller not available'}), 503

                    # New elements-based format (bar graphs, shapes, icons, etc.)
                    raw_elements = rendered.get('elements')
                    if raw_elements is not None and isinstance(raw_elements, list):
                        oled_controller.render_frame(
                            raw_elements,
                            clear=rendered.get('clear', True),
                            invert=rendered.get('invert'),
                        )
                    else:
                        # Legacy lines-based format
                        raw_lines = rendered.get('lines', [])
                        line_objects = []
                        for entry in raw_lines:
                            if not isinstance(entry, dict):
                                continue
                            try:
                                x_val = int(entry.get('x', 0) or 0)
                            except (TypeError, ValueError):
                                x_val = 0
                            y_raw = entry.get('y')
                            try:
                                y_val = int(y_raw) if y_raw is not None else None
                            except (TypeError, ValueError):
                                y_val = None
                            mw_raw = entry.get('max_width')
                            try:
                                mw_val = int(mw_raw) if mw_raw is not None else None
                            except (TypeError, ValueError):
                                mw_val = None
                            try:
                                sp_val = int(entry.get('spacing', 2))
                            except (TypeError, ValueError):
                                sp_val = 2
                            line_objects.append(OLEDLine(
                                text=str(entry.get('text', '')),
                                x=x_val,
                                y=y_val,
                                font=str(entry.get('font', 'small')),
                                wrap=bool(entry.get('wrap', True)),
                                max_width=mw_val,
                                spacing=sp_val,
                                invert=entry.get('invert'),
                                allow_empty=bool(entry.get('allow_empty', False)),
                            ))
                        oled_controller.display_lines(
                            line_objects,
                            clear=rendered.get('clear', True),
                            invert=rendered.get('invert'),
                        )

                elif screen.display_type == 'led':
                    import app_core.led as led_module
                    if not led_module.led_controller:
                        return jsonify({'success': False, 'error': 'LED controller not available'}), 503
                    from webapp.routes_screens import _convert_led_enum
                    lines = rendered.get('lines', [])
                    color_str = rendered.get('color', 'AMBER')
                    mode_str = rendered.get('mode', 'HOLD')
                    speed_str = rendered.get('speed', 'SPEED_3')
                    color = _convert_led_enum(led_module.Color, color_str,
                                             led_module.Color.AMBER if led_module.Color else color_str)
                    mode = _convert_led_enum(led_module.DisplayMode, mode_str,
                                            led_module.DisplayMode.HOLD if led_module.DisplayMode else mode_str)
                    speed = _convert_led_enum(led_module.Speed, speed_str,
                                             led_module.Speed.SPEED_3 if led_module.Speed else speed_str)
                    led_module.led_controller.send_message(lines=lines, color=color, mode=mode, speed=speed)

                elif screen.display_type == 'vfd':
                    from app_core.vfd import vfd_controller
                    if not vfd_controller:
                        return jsonify({'success': False, 'error': 'VFD controller not available'}), 503
                    for command in rendered:
                        cmd_type = command.get('type')
                        if cmd_type == 'clear':
                            vfd_controller.clear_display()
                        elif cmd_type == 'text':
                            vfd_controller.draw_text(
                                command.get('text', ''), command.get('x', 0), command.get('y', 0))
                        elif cmd_type == 'rectangle':
                            vfd_controller.draw_rectangle(
                                command.get('x1', 0), command.get('y1', 0),
                                command.get('x2', 10), command.get('y2', 10),
                                filled=command.get('filled', False))
                        elif cmd_type == 'line':
                            vfd_controller.draw_line(
                                command.get('x1', 0), command.get('y1', 0),
                                command.get('x2', 10), command.get('y2', 10))
                else:
                    return jsonify({'success': False,
                                    'error': f"Unknown display_type '{screen.display_type}'"}), 400

                # Update display statistics
                screen.display_count = (screen.display_count or 0) + 1
                from app_utils import utc_now as _utc_now
                screen.last_displayed_at = _utc_now()
                from app_core.extensions import db as _db
                _db.session.commit()

            return jsonify({'success': True,
                            'message': f"Screen '{screen.name}' displayed on {screen.display_type}"})

        except Exception as exc:
            logger.error('Error pushing screen to display: %s', exc, exc_info=True)
            return jsonify({'success': False, 'error': str(exc)}), 500

    return api_app


def run_api_server():
    """Run Flask API server in background thread."""
    try:
        api_app = create_api_app()
        # Run on port 5001 (app uses 5000)
        api_app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Error running API server: {e}", exc_info=True)


def _update_alert_indicators(
    broadcast_was_active: bool,
    incoming_was_active: bool,
) -> tuple:
    """Drive tower light and NeoPixel controllers based on broadcast state.

    Reads the current ``eas:broadcast_active`` and ``eas:incoming_alert`` Redis
    keys and calls the appropriate alert-lifecycle methods on any configured
    hardware indicator controllers whenever the state changes.

    The tower light follows a three-state machine:
      idle → incoming (yellow) → active broadcast (red) → idle (green)

    Returns ``(broadcast_active, incoming_active)`` so the caller can track
    state across loop iterations.
    """
    try:
        from app_utils.eas import get_broadcast_state, get_incoming_alert_state
        state = get_broadcast_state()
        broadcast_active = bool(state.get('active', False))
        incoming_state = get_incoming_alert_state()
        incoming_active = bool(incoming_state.get('incoming', False))
    except Exception:
        return broadcast_was_active, incoming_was_active  # Leave light in current state on error

    # Transition: * → active broadcast (broadcast takes priority over incoming)
    if broadcast_active and not broadcast_was_active:
        if _tower_light_controller and _tower_light_controller.is_available:
            try:
                _tower_light_controller.start_alert()
            except Exception as exc:
                logger.warning("Tower light start_alert failed: %s", exc)
        if _neopixel_controller:
            try:
                _neopixel_controller.start_alert()
            except Exception as exc:
                logger.warning("NeoPixel start_alert failed: %s", exc)

    # Transition: active → idle (broadcast ended)
    elif not broadcast_active and broadcast_was_active:
        if _tower_light_controller and _tower_light_controller.is_available:
            try:
                _tower_light_controller.end_alert()
            except Exception as exc:
                logger.warning("Tower light end_alert failed: %s", exc)
        if _neopixel_controller:
            try:
                _neopixel_controller.end_alert()
            except Exception as exc:
                logger.warning("NeoPixel end_alert failed: %s", exc)

    # Transition: idle → incoming (alert received, broadcast not yet started)
    elif not broadcast_active and incoming_active and not incoming_was_active:
        if _tower_light_controller and _tower_light_controller.is_available:
            try:
                _tower_light_controller.start_incoming_alert()
            except Exception as exc:
                logger.warning("Tower light start_incoming_alert failed: %s", exc)

    # Transition: incoming → idle (alert rejected or expired without broadcast)
    elif not broadcast_active and not incoming_active and incoming_was_active:
        if _tower_light_controller and _tower_light_controller.is_available:
            try:
                _tower_light_controller.end_alert()
            except Exception as exc:
                logger.warning("Tower light end_alert (incoming expired) failed: %s", exc)

    return broadcast_active, incoming_active


def health_check_loop():
    """Periodic health check and metrics publishing."""
    global _running

    logger.info("📊 Hardware monitoring started")
    last_metrics_publish = 0
    metrics_interval = 5  # Publish metrics every 5 seconds
    broadcast_was_active = False  # Track last-known broadcast state
    incoming_was_active = False   # Track last-known incoming-alert state

    while _running:
        try:
            current_time = time.time()

            # Drive alert indicators (tower light, NeoPixel) based on
            # broadcast state; runs every loop iteration (1 s resolution).
            if _redis_client and (_tower_light_controller or _neopixel_controller):
                broadcast_was_active, incoming_was_active = _update_alert_indicators(
                    broadcast_was_active, incoming_was_active
                )

            # Publish metrics periodically
            if current_time - last_metrics_publish >= metrics_interval:
                publish_hardware_metrics()
                last_metrics_publish = current_time

            # Sleep briefly
            time.sleep(1)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error in health check loop: {e}", exc_info=True)
            time.sleep(5)


def main():
    """Main entry point for hardware service."""
    global _running, _flask_app

    logger.info("=" * 60)
    logger.info("🔌 EAS Station - Dedicated Hardware Service")
    logger.info("=" * 60)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Initialize Redis
        logger.info("Connecting to Redis...")
        get_redis_client()
        logger.info("✅ Connected to Redis")

        # Initialize database
        logger.info("Initializing database connection...")
        app, db = initialize_database()
        _flask_app = app  # Store for health check loop (publish_hardware_metrics needs app context)
        logger.info("✅ Database connected")

        # Initialize hardware controllers (must be done before screen manager)
        with app.app_context():
            logger.info("Initializing LED controller...")
            initialize_led_controller()

            logger.info("Initializing VFD controller...")
            initialize_vfd_controller()

            logger.info("Initializing OLED display...")
            initialize_oled_display()

        # Initialize screen manager (depends on LED/VFD/OLED controllers)
        logger.info("Initializing screen manager...")
        initialize_screen_manager(app)

        # Initialize GPIO controller (needs db session for audit logging)
        logger.info("Initializing GPIO controller...")
        with app.app_context():
            initialize_gpio_controller(db_session=db.session)

        # Initialize NeoPixel controller
        logger.info("Initializing NeoPixel controller...")
        with app.app_context():
            initialize_neopixel_controller()

        # Initialize USB tower light controller
        logger.info("Initializing USB tower light controller...")
        with app.app_context():
            initialize_tower_light_controller()

        # Initialize Zigbee coordinator (if configured)
        logger.info("Initializing Zigbee coordinator...")
        with app.app_context():
            initialize_zigbee_coordinator()

        # Initialize GPS receiver (if configured)
        logger.info("Initializing GPS receiver...")
        with app.app_context():
            initialize_gps_manager()

        # Start Flask API server in background thread
        logger.info("Starting hardware proxy API server on port 5001...")
        api_thread = threading.Thread(target=run_api_server, daemon=True)
        api_thread.start()
        logger.info("✅ Hardware proxy API server started")

        # Start health check loop
        health_check_loop()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error in hardware service: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        logger.info("Shutting down hardware service...")

        if _screen_manager:
            try:
                if hasattr(_screen_manager, 'stop'):
                    _screen_manager.stop()
            except Exception as e:
                logger.error(f"Error stopping screen manager: {e}")

        if _gpio_controller:
            try:
                if hasattr(_gpio_controller, 'cleanup'):
                    _gpio_controller.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up GPIO: {e}")

        if _neopixel_controller:
            try:
                _neopixel_controller.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up NeoPixel controller: {e}")

        if _tower_light_controller:
            try:
                _tower_light_controller.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up USB tower light: {e}")

        if _zigpy_controller:
            try:
                _zigpy_controller.stop()
            except Exception as e:
                logger.error(f"Error stopping Zigbee controller: {e}")

        if _gps_manager:
            try:
                _gps_manager.stop()
            except Exception as e:
                logger.error(f"Error stopping GPS manager: {e}")

        if _redis_client:
            try:
                _redis_client.close()
            except Exception:
                pass

        logger.info("✅ Hardware service stopped cleanly")


if __name__ == "__main__":
    main()
