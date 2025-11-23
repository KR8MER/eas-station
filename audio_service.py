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
Standalone Audio Processing Service

This service handles ALL audio processing independently from the web application:
- Audio source ingestion (SDR, Icecast streams, etc.)
- EAS monitoring and SAME decoding
- Icecast streaming output
- Metrics publishing to Redis

Architecture Benefits:
- Web crashes don't affect audio monitoring
- Audio service can be restarted independently
- Simpler, more focused codebase
- Better resource management
- Easier debugging

The web application reads metrics from Redis and serves the UI.
"""

import os
import sys
import time
import signal
import logging
import redis
import json
from typing import Optional

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
_audio_controller = None
_eas_monitor = None


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _running
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _running = False


def get_redis_client() -> redis.Redis:
    """Get or create Redis client."""
    global _redis_client

    if _redis_client is None:
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_db = int(os.getenv("REDIS_DB", "0"))

        _redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
        )

        # Test connection
        _redis_client.ping()
        logger.info(f"✅ Connected to Redis at {redis_host}:{redis_port}")

    return _redis_client


def initialize_database():
    """Initialize database connection for configuration."""
    from webapp.models import db
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

    db.init_app(app)

    return app


def initialize_audio_controller(app):
    """Initialize audio ingestion controller."""
    global _audio_controller

    with app.app_context():
        from app_core.audio.ingest import AudioIngestController
        from webapp.models import AudioSourceConfigDB

        logger.info("Initializing audio controller...")

        # Create controller
        _audio_controller = AudioIngestController()

        # Load audio sources from database
        configs = AudioSourceConfigDB.query.all()
        logger.info(f"Loading {len(configs)} audio source configurations from database")

        for config in configs:
            try:
                if config.source_type == 'icecast':
                    _audio_controller.add_icecast_source(
                        name=config.name,
                        url=config.icecast_url,
                        sample_rate=config.sample_rate or 44100,
                        enabled=config.enabled
                    )
                elif config.source_type == 'sdr':
                    _audio_controller.add_sdr_source(
                        name=config.name,
                        frequency_mhz=config.sdr_frequency,
                        sample_rate=config.sample_rate or 1024000,
                        sdr_args=config.sdr_args or "",
                        enabled=config.enabled
                    )

                logger.info(f"Loaded audio source: {config.name} ({config.source_type})")

            except Exception as e:
                logger.error(f"Error loading source '{config.name}': {e}")

        # Start auto-start sources
        for config in configs:
            if config.enabled and config.auto_start:
                try:
                    logger.info(f"Auto-starting source: {config.name}")
                    _audio_controller.start_source(config.name)
                except Exception as e:
                    logger.error(f"Error auto-starting '{config.name}': {e}")

        logger.info("✅ Audio controller initialized")
        return _audio_controller


def initialize_eas_monitor(app, audio_controller):
    """Initialize EAS monitoring system."""
    global _eas_monitor

    with app.app_context():
        from app_core.audio.eas_monitor import ContinuousEASMonitor, create_fips_filtering_callback
        from app_core.audio.broadcast_adapter import BroadcastAudioAdapter
        from app_core.audio.startup_integration import load_fips_codes_from_config

        logger.info("Initializing EAS monitor...")

        # Get broadcast queue for non-destructive audio access
        broadcast_queue = audio_controller.get_broadcast_queue()
        ingest_sample_rate = audio_controller.get_active_sample_rate() or 44100

        # Create broadcast adapter
        audio_adapter = BroadcastAudioAdapter(
            broadcast_queue=broadcast_queue,
            subscriber_id="eas-monitor",
            sample_rate=int(ingest_sample_rate)
        )

        # Load FIPS codes
        configured_fips = load_fips_codes_from_config()
        logger.info(f"Loaded {len(configured_fips)} FIPS codes for alert filtering")

        # Create alert callback with filtering
        def forward_alert_handler(alert):
            """Forward matched alerts."""
            from app_core.audio.alert_forwarding import forward_alert_to_api
            logger.info(f"Forwarding alert: {alert.get('event_code')} for {alert.get('location_codes')}")
            forward_alert_to_api(alert)

        alert_callback = create_fips_filtering_callback(
            target_fips_codes=configured_fips,
            forward_callback=forward_alert_handler,
            logger_instance=logger
        )

        # Create EAS monitor (16 kHz for optimal SAME decoding)
        _eas_monitor = ContinuousEASMonitor(
            audio_manager=audio_adapter,
            sample_rate=16000,
            alert_callback=alert_callback,
            save_audio_files=True,
            audio_archive_dir="/tmp/eas-audio"
        )

        # Start monitoring
        if _eas_monitor.start():
            logger.info("✅ EAS monitor started successfully")
        else:
            logger.error("❌ EAS monitor failed to start")
            return None

        return _eas_monitor


def collect_metrics():
    """Collect metrics from audio controller and EAS monitor."""
    metrics = {
        "audio_controller": None,
        "eas_monitor": None,
        "broadcast_queue": None,
        "timestamp": time.time()
    }

    try:
        # Get audio controller stats
        if _audio_controller:
            controller_stats = {
                "sources": {},
                "active_source": _audio_controller.get_active_source_name(),
            }

            for name, source in _audio_controller._sources.items():
                try:
                    controller_stats["sources"][name] = {
                        "status": source.status.value if hasattr(source.status, 'value') else str(source.status),
                        "sample_rate": getattr(source, 'sample_rate', None),
                    }
                except Exception as e:
                    logger.error(f"Error getting source stats for '{name}': {e}")

            metrics["audio_controller"] = controller_stats

            # Get broadcast queue stats
            try:
                broadcast_queue = _audio_controller.get_broadcast_queue()
                if broadcast_queue:
                    metrics["broadcast_queue"] = broadcast_queue.get_stats()
            except Exception as e:
                logger.error(f"Error getting broadcast queue stats: {e}")

        # Get EAS monitor stats
        if _eas_monitor:
            try:
                metrics["eas_monitor"] = _eas_monitor.get_stats()
            except Exception as e:
                logger.error(f"Error getting EAS monitor stats: {e}")

    except Exception as e:
        logger.error(f"Error collecting metrics: {e}")

    return metrics


def publish_metrics_to_redis(metrics):
    """Publish metrics to Redis for web application."""
    try:
        r = get_redis_client()

        # Flatten nested dicts to strings for Redis hash
        flat_metrics = {}
        for key, value in metrics.items():
            if isinstance(value, (dict, list)):
                flat_metrics[key] = json.dumps(value)
            else:
                flat_metrics[key] = str(value)

        # Store in Redis with pipeline for atomicity
        pipe = r.pipeline()
        pipe.delete("eas:metrics")  # Use same key as worker coordinator
        pipe.hset("eas:metrics", mapping=flat_metrics)
        pipe.expire("eas:metrics", 60)  # Expire if service dies
        pipe.execute()

        # Publish notification for real-time updates
        r.publish("eas:metrics:update", "1")

    except Exception as e:
        logger.error(f"Error publishing metrics to Redis: {e}")


def main():
    """Main service loop."""
    global _running

    logger.info("=" * 80)
    logger.info("EAS Station - Standalone Audio Processing Service")
    logger.info("=" * 80)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Initialize Redis
        logger.info("Connecting to Redis...")
        r = get_redis_client()

        # Initialize database
        logger.info("Initializing database connection...")
        app = initialize_database()

        # Initialize audio controller
        logger.info("Initializing audio controller...")
        audio_controller = initialize_audio_controller(app)

        if not audio_controller:
            logger.error("Failed to initialize audio controller")
            return 1

        # Initialize EAS monitor
        logger.info("Initializing EAS monitor...")
        eas_monitor = initialize_eas_monitor(app, audio_controller)

        if not eas_monitor:
            logger.error("Failed to initialize EAS monitor")
            return 1

        logger.info("=" * 80)
        logger.info("✅ Audio service started successfully")
        logger.info("   - Audio ingestion: ACTIVE")
        logger.info("   - EAS monitoring: ACTIVE")
        logger.info("   - Metrics publishing: ACTIVE")
        logger.info("=" * 80)

        # Main loop: publish metrics every 5 seconds
        last_metrics_time = 0
        metrics_interval = 5.0

        while _running:
            try:
                current_time = time.time()

                # Publish metrics periodically
                if current_time - last_metrics_time >= metrics_interval:
                    metrics = collect_metrics()
                    publish_metrics_to_redis(metrics)
                    last_metrics_time = current_time

                    # Log health status
                    if metrics.get("eas_monitor"):
                        samples = metrics["eas_monitor"].get("samples_processed", 0)
                        running = metrics["eas_monitor"].get("running", False)
                        logger.debug(f"EAS Monitor: running={running}, samples={samples}")

                # Sleep briefly
                time.sleep(1)

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(5)

        logger.info("Shutting down audio service...")

        # Stop EAS monitor
        if _eas_monitor:
            logger.info("Stopping EAS monitor...")
            _eas_monitor.stop()

        # Stop audio controller
        if _audio_controller:
            logger.info("Stopping audio controller...")
            # Audio controller doesn't have explicit stop, sources will be cleaned up

        # Close Redis connection
        if _redis_client:
            logger.info("Closing Redis connection...")
            _redis_client.close()

        logger.info("✅ Audio service shut down gracefully")
        return 0

    except Exception as e:
        logger.error(f"Fatal error in audio service: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
