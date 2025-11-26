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
Dedicated SDR Service

This service handles ONLY SDR hardware management:
- Initialize and manage SDR devices (Airspy, RTL-SDR, etc.)
- Capture and stream IQ samples
- Provide samples to audio-service via Redis pub/sub
- Device health monitoring

Architecture Benefits:
- Hardware isolation - SDR issues don't affect other services
- Clean separation - one service per function
- Independent restart - can restart SDR without affecting audio processing
- Better debugging - clear responsibility boundaries
- Resource management - USB access only where needed

The audio-service subscribes to samples and handles all audio processing.
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
_radio_manager = None


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
    """Initialize database connection for SDR configuration."""
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


def initialize_radio_manager(app):
    """Initialize radio manager and start configured receivers."""
    global _radio_manager

    from app_core.extensions import get_radio_manager
    from app_core.models import RadioReceiver

    try:
        with app.app_context():
            _radio_manager = get_radio_manager()

            # Load enabled receivers from database
            enabled_receivers = RadioReceiver.query.filter_by(enabled=True).all()
            logger.info(f"Found {len(enabled_receivers)} enabled SDR receiver(s) in database")

            if not enabled_receivers:
                logger.warning("⚠️  No enabled receivers configured. Add receivers via web UI at /settings/radio")
                return

            # Configure radio manager
            _radio_manager.configure_from_records(enabled_receivers)

            # Start auto-start receivers
            started_count = 0
            for receiver in enabled_receivers:
                if receiver.auto_start:
                    try:
                        instance = _radio_manager.get_receiver(receiver.identifier)
                        if instance:
                            instance.start()
                            started_count += 1
                            logger.info(f"✅ Started SDR receiver: {receiver.identifier} ({receiver.display_name})")
                    except Exception as e:
                        logger.error(f"❌ Failed to start receiver {receiver.identifier}: {e}")

            logger.info(f"✅ SDR service initialized with {started_count} active receiver(s)")

    except Exception as e:
        logger.error(f"❌ Failed to initialize radio manager: {e}", exc_info=True)
        raise


def publish_receiver_metrics():
    """Publish receiver status and metrics to Redis for monitoring."""
    if not _radio_manager or not _redis_client:
        return

    try:
        receivers = _radio_manager.list_receivers()
        metrics = {}

        for receiver_id in receivers:
            try:
                instance = _radio_manager.get_receiver(receiver_id)
                if not instance:
                    continue

                status = instance.get_status()
                health = instance.get_connection_health() if hasattr(instance, 'get_connection_health') else {}

                metrics[receiver_id] = {
                    "identifier": status.identifier,
                    "locked": status.locked,
                    "signal_strength": status.signal_strength,
                    "last_error": status.last_error,
                    "reported_at": status.reported_at.isoformat() if status.reported_at else None,
                    "running": instance.is_running() if hasattr(instance, 'is_running') else False,
                    "connection_health": health,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            except Exception as e:
                logger.debug(f"Failed to get metrics for receiver {receiver_id}: {e}")
                continue

        # Publish to Redis
        if metrics:
            _redis_client.setex(
                "sdr:metrics",
                60,  # 60 second TTL
                json.dumps(metrics)
            )

    except Exception as e:
        logger.debug(f"Failed to publish receiver metrics: {e}")


def health_check_loop():
    """Periodic health check and metrics publishing."""
    global _running

    logger.info("📊 SDR health monitoring started")
    last_metrics_publish = 0
    metrics_interval = 5  # Publish metrics every 5 seconds

    while _running:
        try:
            current_time = time.time()

            # Publish metrics periodically
            if current_time - last_metrics_publish >= metrics_interval:
                publish_receiver_metrics()
                last_metrics_publish = current_time

            # Sleep briefly
            time.sleep(1)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error in health check loop: {e}", exc_info=True)
            time.sleep(5)


def main():
    """Main entry point for SDR service."""
    global _running

    logger.info("=" * 60)
    logger.info("🎛️  EAS Station - Dedicated SDR Service")
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

        # Initialize radio manager
        logger.info("Initializing SDR receivers...")
        initialize_radio_manager(app)

        # Start health check loop
        health_check_loop()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error in SDR service: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        logger.info("Shutting down SDR service...")

        if _radio_manager:
            try:
                logger.info("Stopping all receivers...")
                for receiver_id in _radio_manager.list_receivers():
                    try:
                        instance = _radio_manager.get_receiver(receiver_id)
                        if instance and hasattr(instance, 'stop'):
                            instance.stop()
                    except Exception as e:
                        logger.error(f"Error stopping receiver {receiver_id}: {e}")
            except Exception as e:
                logger.error(f"Error during receiver cleanup: {e}")

        if _redis_client:
            try:
                _redis_client.close()
            except Exception:
                pass

        logger.info("✅ SDR service stopped cleanly")


if __name__ == "__main__":
    main()
