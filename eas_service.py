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
Standalone EAS Service

This service handles ONLY EAS monitoring and alert detection:
- Subscribes to Redis audio streams from audio-service
- Runs continuous EAS/SAME header detection
- Stores detected alerts in database
- NO audio processing, NO SDR hardware access

Architecture:
                    ┌─────────────────┐
                    │   audio-service │
                    │ (Audio from SDR)│
                    └────────┬────────┘
                             │ Redis audio pub/sub
                             ▼
            ┌────────────────────────────────┐
            │         eas_service.py         │
            │   (This file - EAS only)       │
            │                                │
            │  - Subscribe to Redis audio   │
            │  - SAME header detection       │
            │  - FIPS code filtering         │
            │  - Alert database storage      │
            └────────────────────────────────┘

Benefits:
- EAS crashes don't affect audio processing
- EAS service can be restarted independently
- Clear separation of concerns
- Easy to scale EAS monitoring across multiple audio sources
"""

import os
import sys
import time
import signal
import logging
import json
import redis
from typing import Optional, Any, Dict
from dotenv import load_dotenv

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
_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    if os.path.exists(_config_path):
        load_dotenv(_config_path, override=True)
        logger.info(f"✅ Loaded environment from: {_config_path}")
    else:
        logger.warning(f"⚠️  CONFIG_PATH set but file not found: {_config_path}")
        load_dotenv(override=True)
else:
    load_dotenv(override=True)
    logger.info("Loaded environment from .env file")

# Global state
_flask_app: Optional[Any] = None
_eas_monitor: Optional[Any] = None
_redis_client: Optional[redis.Redis] = None
_running = True


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global _running
    logger.info(f"Received signal {signum}, shutting down...")
    _running = False


def get_redis_client() -> redis.Redis:
    """Get or create Redis client with retry logic."""
    global _redis_client

    # Use robust Redis client with retry logic
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


def create_app():
    """Create minimal Flask app for database access."""
    from flask import Flask
    from app_core.extensions import db

    app = Flask(__name__)

    # Database configuration
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 5,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
    }

    # Initialize extensions
    db.init_app(app)

    logger.info("✅ Flask app created for database access")
    return app


def initialize_eas_monitor(app):
    """Initialize EAS monitor that subscribes to Redis audio."""
    global _eas_monitor

    with app.app_context():
        from app_core.audio.eas_monitor import EASMonitor, create_fips_filtering_callback
        from app_core.audio.redis_audio_adapter import RedisAudioAdapter
        from app_core.audio.startup_integration import load_fips_codes_from_config
        from app_core.audio.alert_forwarding import forward_alert_to_api

        logger.info("Initializing EAS monitor...")

        # Load FIPS codes from configuration
        configured_fips = load_fips_codes_from_config()
        logger.info(f"Loaded {len(configured_fips)} FIPS codes for monitoring")

        # Create alert forwarding handler
        def forward_alert_handler(alert):
            """Forward matched alerts to API and air chain broadcast."""
            source_name = alert.get('source_name', 'unknown')
            event_code = alert.get('event_code', 'UNKNOWN')
            location_codes = alert.get('location_codes', [])
            logger.info(
                f"Forwarding alert from source '{source_name}': "
                f"{event_code} for {location_codes}"
            )
            result = forward_alert_to_api(alert)
            # Return result so _extract_message_id can link the broadcast record
            return result

        # Create FIPS filtering callback
        _fips_callback_inner = create_fips_filtering_callback(
            configured_fips_codes=configured_fips,
            forward_callback=forward_alert_handler,
            logger_instance=logger
        )

        # Wrap the callback so the EAS monitor thread always runs with a Flask
        # application context.  Without this, forward_alert_to_api →
        # _auto_forward_to_air_chain checks has_app_context() → False and
        # silently drops every OTA alert (Bug 1).
        def alert_callback(alert):
            with app.app_context():
                return _fips_callback_inner(alert)

        # Create Redis audio adapter
        # Subscribes to audio:samples:* channels published by audio-service
        audio_adapter = RedisAudioAdapter(
            subscriber_id="eas-monitor",
            sample_rate=16000,  # EAS monitor expects 16kHz
            read_timeout=0.5
        )

        # Create EAS monitor
        _eas_monitor = EASMonitor(
            audio_source=audio_adapter,
            sample_rate=16000,
            alert_callback=alert_callback,
            source_name="eas-service"
        )

        # Start monitoring
        if _eas_monitor.start():
            logger.info("✅ EAS monitor started successfully")
        else:
            raise RuntimeError("Failed to start EAS monitor")

        return _eas_monitor


def _sanitize_value(value: Any) -> Any:
    """Convert runtime values to JSON-serializable primitives."""
    try:
        import numpy as np  # type: ignore

        if isinstance(value, (np.floating, np.integer)):
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
    except Exception:
        # numpy is optional in some deployments; ignore if unavailable
        pass

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(k): _sanitize_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(v) for v in value]

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    try:
        return float(value)
    except Exception:
        return str(value)


def collect_eas_metrics() -> Dict[str, Any]:
    """Collect metrics from EAS monitor."""
    metrics = {
        "eas_monitor": None,
        "timestamp": time.time()
    }

    try:
        if _eas_monitor:
            # Get EAS monitor status (complete UI metrics)
            # Use get_status() not get_stats() - get_status() returns full metrics
            # including health_percentage, runtime_seconds, samples_per_second, etc.
            eas_stats = _eas_monitor.get_status()
            if eas_stats:
                metrics["eas_monitor"] = _sanitize_value(eas_stats)
                
                # Format diagnostic log message with key operational metrics
                audio_flowing = eas_stats.get('audio_flowing', False)
                samples_processed = eas_stats.get('samples_processed', 0)
                samples_per_sec = eas_stats.get('samples_per_second', 0)
                health_pct = eas_stats.get('health_percentage', 0)
                time_since_audio = eas_stats.get('time_since_last_audio', float('inf'))
                alerts_detected = eas_stats.get('alerts_detected', 0)
                
                # Create status indicator
                status_icon = "✅" if audio_flowing else "⚠️"
                
                # Format time_since_audio for display
                if time_since_audio == float('inf') or time_since_audio >= 999999:
                    time_display = "unknown"
                else:
                    time_display = f"{time_since_audio:.1f}s"
                
                logger.info(
                    f"📊 EAS Monitor Status: {status_icon} "
                    f"audio_flowing={audio_flowing}, "
                    f"samples={samples_processed:,} "
                    f"({samples_per_sec:,}/sec), "
                    f"health={health_pct:.1%}, "
                    f"time_since_audio={time_display}, "
                    f"alerts={alerts_detected}"
                )
            else:
                logger.warning("EAS monitor returned no stats")
                metrics["eas_monitor"] = {
                    "running": False,
                    "error": "No stats available from EAS monitor"
                }
        else:
            logger.debug("EAS monitor not initialized")
            metrics["eas_monitor"] = {
                "running": False,
                "error": "EAS monitor not initialized"
            }

    except Exception as e:
        logger.error(f"Error collecting EAS metrics: {e}")
        metrics["eas_monitor"] = {
            "running": False,
            "error": str(e)
        }

    return metrics


def publish_eas_metrics_to_redis(metrics: Dict[str, Any]):
    """Publish EAS metrics to Redis for web application.

    Merges EAS monitor metrics into the existing eas:metrics hash
    published by audio-service, so webapp can read both audio and EAS
    metrics from the same Redis key.

    IMPORTANT: If the audio-service (eas_monitoring_service.py) is already
    publishing eas_monitor data via its V3 UnifiedEASMonitorService, we
    defer to it since it has direct access to audio sources and provides
    more authoritative status. This prevents state oscillation where two
    services alternate overwriting the eas_monitor key.
    """
    try:
        r = get_redis_client()

        # Add heartbeat timestamp and process ID
        metrics["_eas_heartbeat"] = time.time()
        metrics["_eas_pid"] = os.getpid()

        # Read existing metrics from audio-service (if any)
        existing_metrics = r.hgetall("eas:metrics")

        # Check if audio-service (eas_monitoring_service.py) is already publishing
        # authoritative eas_monitor data via its V3 unified monitor.
        # If so, defer to it to prevent state oscillation.
        if existing_metrics and "eas_monitor" in existing_metrics:
            try:
                existing_eas_raw = existing_metrics["eas_monitor"]
                if isinstance(existing_eas_raw, bytes):
                    existing_eas_raw = existing_eas_raw.decode("utf-8")
                existing_eas = json.loads(existing_eas_raw) if isinstance(existing_eas_raw, str) else existing_eas_raw
                if isinstance(existing_eas, dict) and existing_eas.get("mode") == "unified-streaming":
                    # V3 unified monitor from audio-service is active - don't overwrite
                    metrics.pop("eas_monitor", None)
                    logger.debug(
                        "Deferring eas_monitor to audio-service V3 unified monitor"
                    )
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass  # Can't parse existing data, proceed with our own

        # Flatten nested dicts to strings for Redis hash
        flat_metrics = {}

        # Keep existing metrics from audio-service
        if existing_metrics:
            flat_metrics.update(existing_metrics)

        # Add/update EAS metrics
        for key, value in metrics.items():
            if isinstance(value, (dict, list)):
                flat_metrics[key] = json.dumps(value)
            else:
                flat_metrics[key] = str(value)

        # Store in Redis with pipeline for atomicity
        pipe = r.pipeline()
        pipe.hset("eas:metrics", mapping=flat_metrics)
        pipe.expire("eas:metrics", 60)  # Expire if service dies
        pipe.execute()

        # Publish notification for real-time updates
        r.publish("eas:metrics:update", "1")

        logger.info(f"✅ Published EAS metrics to Redis: {len(flat_metrics)} keys, eas_monitor={metrics.get('eas_monitor', {}).get('running', 'N/A') if isinstance(metrics.get('eas_monitor'), dict) else 'deferred'}")

    except Exception as e:
        logger.error(f"Error publishing EAS metrics to Redis: {e}")


def main():
    """Main entry point for EAS service."""
    global _flask_app, _eas_monitor, _running

    logger.info("=" * 80)
    logger.info("EAS Station - Standalone EAS Service")
    logger.info("Handles EAS/SAME detection and alert storage ONLY")
    logger.info("=" * 80)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Initialize Redis
        logger.info("Connecting to Redis...")
        r = get_redis_client()
        logger.info("✅ Connected to Redis")

        # Create Flask app for database access
        _flask_app = create_app()

        # Initialize EAS monitor
        _eas_monitor = initialize_eas_monitor(_flask_app)

        logger.info("=" * 80)
        logger.info("✅ EAS service started successfully")
        logger.info("   - EAS monitoring: ACTIVE")
        logger.info("   - Metrics publishing: ACTIVE")
        logger.info("=" * 80)
        logger.info("Monitoring for EAS alerts...")

        # Main loop - publish metrics every 5 seconds
        last_metrics_time = 0
        metrics_interval = 5.0

        while _running:
            try:
                current_time = time.time()

                # Publish metrics periodically
                if current_time - last_metrics_time >= metrics_interval:
                    metrics = collect_eas_metrics()
                    publish_eas_metrics_to_redis(metrics)
                    last_metrics_time = current_time

                # Sleep briefly
                time.sleep(0.5)

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(5)

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error in EAS service: {e}", exc_info=True)
        return 1
    finally:
        # Cleanup
        if _eas_monitor:
            try:
                _eas_monitor.stop()
                logger.info("✅ EAS monitor stopped")
            except Exception as e:
                logger.exception("Error stopping EAS monitor")

        # Close Redis connection
        if _redis_client:
            logger.info("Closing Redis connection...")
            _redis_client.close()

        logger.info("EAS service shutdown complete")

    return 0


if __name__ == "__main__":
    sys.exit(main())
