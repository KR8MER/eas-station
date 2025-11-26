#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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
from typing import Optional
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Global state
_running = True
_redis_client: Optional[redis.Redis] = None
_screen_manager = None
_gpio_controller = None


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
    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port = os.getenv("POSTGRES_PORT", "5432")
    postgres_db = os.getenv("POSTGRES_DB", "alerts")
    postgres_user = os.getenv("POSTGRES_USER", "postgres")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{postgres_user}:{postgres_password}@"
        f"{postgres_host}:{postgres_port}/{postgres_db}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    db.init_app(app)
    return app, db


def initialize_screen_manager(app):
    """Initialize screen manager for OLED/LED/VFD displays."""
    global _screen_manager

    try:
        from scripts.screen_manager import screen_manager

        with app.app_context():
            screen_manager.init_app(app)

            # Start screen rotation if enabled
            auto_start = os.getenv("SCREENS_AUTO_START", "true").lower() in ("true", "1", "yes")
            if auto_start:
                screen_manager.start()
                logger.info("✅ Screen manager started with automatic rotation")
            else:
                logger.info("Screen manager initialized (auto-start disabled)")

    except Exception as e:
        logger.warning(f"⚠️  Screen manager not available: {e}")
        logger.info("Continuing without display support")


def initialize_gpio_controller():
    """Initialize GPIO controller for relay/transmitter control."""
    global _gpio_controller

    try:
        from app_utils.gpio import GPIOController

        # Check if GPIO is enabled
        gpio_enabled = os.getenv("GPIO_ENABLED", "false").lower() in ("true", "1", "yes")

        if not gpio_enabled:
            logger.info("GPIO controller disabled (GPIO_ENABLED=false)")
            return

        _gpio_controller = GPIOController()
        logger.info("✅ GPIO controller initialized")

    except Exception as e:
        logger.warning(f"⚠️  GPIO controller not available: {e}")
        logger.info("Continuing without GPIO support")


def publish_hardware_metrics():
    """Publish hardware status and metrics to Redis."""
    if not _redis_client:
        return

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

        # Publish to Redis
        _redis_client.setex(
            "hardware:metrics",
            60,  # 60 second TTL
            json.dumps(metrics)
        )

    except Exception as e:
        logger.debug(f"Failed to publish hardware metrics: {e}")


def health_check_loop():
    """Periodic health check and metrics publishing."""
    global _running

    logger.info("📊 Hardware monitoring started")
    last_metrics_publish = 0
    metrics_interval = 5  # Publish metrics every 5 seconds

    while _running:
        try:
            current_time = time.time()

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
    global _running

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
        logger.info("✅ Database connected")

        # Initialize screen manager
        logger.info("Initializing screen manager...")
        initialize_screen_manager(app)

        # Initialize GPIO controller
        logger.info("Initializing GPIO controller...")
        initialize_gpio_controller()

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

        if _redis_client:
            try:
                _redis_client.close()
            except Exception:
                pass

        logger.info("✅ Hardware service stopped cleanly")


if __name__ == "__main__":
    main()
