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

import sys
import time
import logging
import redis
import threading
from typing import Optional
from datetime import datetime, timezone
from flask import Flask, jsonify

# Shared bootstrap scaffolding for all split hardware-side services.
# See services/common/bootstrap.py for the full rationale (glibc tuning,
# memdiag hooks, etc.) — this is the exact same startup behaviour that
# used to be inlined here, factored out so the per-subsystem services
# can reuse it.
from services.common import (
    configure_logging,
    init_database,
    init_runtime,
    install_signal_handlers,
    load_environment,
    get_redis,
    publish_hardware_metrics as _publish_hardware_metrics_impl,
)

# Per-subsystem services extracted from this module in Phase 2 of the
# hardware_service.py split.  Each package exposes a pure ``initialize``
# function that returns the controller (so the orchestrator below owns
# the lifetime via module-level globals) plus any periodic helpers.
from services.displays import (
    create_blueprint as _create_displays_blueprint,
    initialize_led_controller as _initialize_led_controller_impl,
    initialize_oled_display as _initialize_oled_display_impl,
    initialize_screen_manager as _initialize_screen_manager_impl,
    initialize_vfd_controller as _initialize_vfd_controller_impl,
)
from services.gpio import (
    initialize_gpio_controller as _initialize_gpio_controller_impl,
    initialize_neopixel_controller as _initialize_neopixel_controller_impl,
    initialize_tower_light_controller as _initialize_tower_light_controller_impl,
    update_alert_indicators as _update_alert_indicators_impl,
)
from services.gps import (
    GPS_TRENDS_DEFAULT_WINDOW,
    GPS_TRENDS_INTERVAL_S,
    GPS_TRENDS_MAX_SAMPLES,
    GPS_TRENDS_RAW_MAX_SAMPLES,
    GPS_TRENDS_REDIS_KEY,
    GPS_TRENDS_TIERS,
    GPS_TRENDS_WINDOW_TO_TIER,
    create_blueprint as _create_gps_blueprint,
    initialize_gps_manager as _initialize_gps_manager_impl,
    new_last_bucket_ids as _new_gps_last_bucket_ids,
)
from services.gps import trends as _gps_trends
from services.network import create_blueprint as _create_network_blueprint
from services.zigbee import (
    create_blueprint as _create_zigbee_blueprint,
    initialize_zigbee_coordinator as _initialize_zigbee_coordinator_impl,
    publish_zigbee_status as _publish_zigbee_status_impl,
)

configure_logging()
logger = logging.getLogger(__name__)

# Load environment variables from persistent config volume
# This must happen before initializing hardware controllers
load_environment(logger)

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


def _on_shutdown_signal(signum: int) -> None:
    """Flip the process-local _running flag in response to SIGTERM/SIGINT."""
    global _running
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _running = False


def get_redis_client() -> redis.Redis:
    """Get or create Redis client with retry logic.

    Thin wrapper around ``services.common.bootstrap.get_redis`` that
    keeps the module-level ``_redis_client`` in sync so downstream
    helpers can continue to read it directly.
    """
    global _redis_client
    _redis_client = get_redis()
    return _redis_client


def initialize_database():
    """Initialize database connection for hardware configuration."""
    return init_database()


def initialize_led_controller():
    """Initialize LED sign controller (delegates to ``services.displays``)."""
    _initialize_led_controller_impl()


def initialize_vfd_controller():
    """Initialize VFD display controller (delegates to ``services.displays``)."""
    _initialize_vfd_controller_impl()


def initialize_oled_display():
    """Initialize OLED display (delegates to ``services.displays``)."""
    _initialize_oled_display_impl()


def initialize_zigbee_coordinator():
    """Initialize Zigbee coordinator (delegates to ``services.zigbee``).

    Captures the returned ``ZigpyController`` (if any) in
    ``_zigpy_controller`` so the Flask API and the shutdown handler can
    drive it.
    """
    global _zigpy_controller
    _zigpy_controller = _initialize_zigbee_coordinator_impl(_redis_client)


def initialize_gps_manager():
    """Initialize the GPS receiver manager (delegates to ``services.gps``).

    Captures the returned ``GPSManager`` (if any) in ``_gps_manager`` so
    the Flask API can serve live status from it and the shutdown handler
    can stop it.
    """
    global _gps_manager
    _gps_manager = _initialize_gps_manager_impl(_redis_client, logger)


def initialize_screen_manager(app):
    """Initialize screen manager (delegates to ``services.displays``)."""
    global _screen_manager
    _screen_manager = _initialize_screen_manager_impl(app)


def initialize_gpio_controller(db_session=None):
    """Initialize GPIO controller (delegates to ``services.gpio``)."""
    global _gpio_controller
    _gpio_controller = _initialize_gpio_controller_impl(db_session=db_session)


def initialize_tower_light_controller():
    """Initialize USB tower light controller (delegates to ``services.gpio``)."""
    global _tower_light_controller
    _tower_light_controller = _initialize_tower_light_controller_impl()


def initialize_neopixel_controller():
    """Initialize NeoPixel controller (delegates to ``services.gpio``)."""
    global _neopixel_controller
    _neopixel_controller = _initialize_neopixel_controller_impl()


# ---------------------------------------------------------------------------
# GPS / chrony trend sampler — thin wrappers around ``services.gps.trends``.
#
# The implementation lives in ``services/gps/trends.py`` as pure functions
# that accept the redis client and per-tier bucket-id dict as arguments.
# This module owns the runtime state (``_redis_client``,
# ``_gps_trend_last_bucket_ids``, ``_gps_manager``) and passes it in so
# the orchestrator stays the single source of process-wide state.
#
# Constants (``GPS_TRENDS_TIERS`` etc.) are re-exported at the top of the
# file so the Flask API in this module and ``tests/test_gps_trends_archive``
# can both keep their existing import paths working.
# ---------------------------------------------------------------------------
_gps_trend_last_bucket_ids: "dict[str, Optional[int]]" = _new_gps_last_bucket_ids()


def _gps_trend_redis_key(tier: str) -> str:
    return _gps_trends.redis_key_for_tier(tier)


def _collect_chrony_tracking_for_trends() -> dict:
    return _gps_trends.collect_chrony_tracking()


def _collect_gps_for_trends() -> dict:
    return _gps_trends.collect_gps_status(_gps_manager)


def _aggregate_gps_trend_samples(
    rows: list, bucket_start_ms: int, bucket_end_ms: int
) -> Optional[dict]:
    return _gps_trends.aggregate_samples(rows, bucket_start_ms, bucket_end_ms)


def _emit_gps_trend_rollups(now_ms: int) -> None:
    _gps_trends.emit_rollups(_redis_client, _gps_trend_last_bucket_ids, now_ms)


def publish_gps_trend_sample() -> None:
    """Append one trend sample to the Redis ring buffer.

    Thin wrapper that hands the orchestrator-owned state to the pure
    sampler in ``services.gps.trends``.
    """
    _gps_trends.publish_sample(
        _redis_client, _gps_manager, _gps_trend_last_bucket_ids
    )


def publish_hardware_metrics():
    """Publish hardware status and metrics to Redis.

    Thin wrapper that hands the orchestrator-owned state to the
    cross-subsystem publisher in ``services.common.metrics``.
    """
    _publish_hardware_metrics_impl(
        redis_client=_redis_client,
        flask_app=_flask_app,
        screen_manager=_screen_manager,
        gpio_controller=_gpio_controller,
    )


def publish_display_state():
    """Publish detailed display state (delegates to ``services.displays``)."""
    from services.displays import publish_display_state as _impl
    _impl(_redis_client, _screen_manager)


def publish_zigbee_status():
    """Refresh Zigbee coordinator status (delegates to ``services.zigbee``)."""
    _publish_zigbee_status_impl(_redis_client)


def _restart_gps_manager(enabled: bool) -> None:
    """Stop any running GPS manager and start a new one when ``enabled``.

    Used by the ``/api/hardware/gps/configure`` route after persisting
    new settings to the DB.  Lives here (not in the blueprint) because
    the manager and its Flask app context are orchestrator-owned state.
    """
    global _gps_manager
    if _gps_manager is not None:
        _gps_manager.stop()
        _gps_manager = None
    if enabled and _flask_app is not None:
        with _flask_app.app_context():
            initialize_gps_manager()


def create_api_app():
    """Assemble the hardware-service Flask app from per-subsystem blueprints.

    Phase 3 of the ``hardware_service.py`` split.  All route definitions
    have moved into the matching ``services.<subsystem>.api`` modules;
    this function is now a thin wiring layer that builds each blueprint
    with the orchestrator-owned runtime state it needs and registers
    them on a single Flask app (still a single process listening on
    port 5001 — process-split is Phase 4).
    """
    api_app = Flask(__name__)

    # Bare health probe — not part of any subsystem.  Kept inline so the
    # health endpoint stays available even if every blueprint fails to
    # import (defensive: lets systemd see "process up" while a single
    # subsystem is broken).
    @api_app.route('/health', methods=['GET'])
    def health():
        """Health check endpoint."""
        return jsonify({
            'status': 'ok',
            'service': 'hardware-service',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Per-subsystem blueprints.  Each blueprint takes getter callables
    # for orchestrator-owned runtime state (controllers / clients /
    # Flask app) so it picks up restarts without re-registration.
    api_app.register_blueprint(_create_network_blueprint())
    api_app.register_blueprint(
        _create_zigbee_blueprint(get_zigpy_controller=lambda: _zigpy_controller)
    )
    api_app.register_blueprint(
        _create_gps_blueprint(
            get_gps_manager=lambda: _gps_manager,
            get_redis_client=lambda: _redis_client,
            restart_gps_manager=_restart_gps_manager,
        )
    )
    api_app.register_blueprint(
        _create_displays_blueprint(get_flask_app=lambda: _flask_app)
    )

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
    """Drive tower light + NeoPixel based on broadcast / incoming alert state.

    Thin wrapper that hands the orchestrator-owned controllers to the
    pure state-machine in ``services.gpio.alert_indicators``.
    """
    return _update_alert_indicators_impl(
        broadcast_was_active,
        incoming_was_active,
        tower_light_controller=_tower_light_controller,
        neopixel_controller=_neopixel_controller,
    )


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
                # The trend sampler runs at the same cadence as the metrics
                # publish (5 s) — see GPS_TRENDS_INTERVAL_S.  Keeping them
                # in lockstep avoids adding a second timer to this loop.
                publish_gps_trend_sample()
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

    # Apply glibc tuning + start the malloc_trim ticker + install the
    # SIGUSR1/SIGUSR2 memory-diagnostic handlers in one call.  Must
    # happen before any worker threads spawn — see
    # services/common/bootstrap.py for the full rationale.
    init_runtime("hardware")

    install_signal_handlers(_on_shutdown_signal)

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
