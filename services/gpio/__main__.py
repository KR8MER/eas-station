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

"""GPIO subsystem subprocess entry point.

Phase 4 of the hardware_service.py split.  Owns the GPIO controller
(relay / transmitter keying), the NeoPixel strip, the USB tower light,
and the alert-indicator state machine that drove all three from the
old ``hardware_service.health_check_loop``.  Listens on port 5105.

This is the only subprocess where the ``broadcast_was_active`` /
``incoming_was_active`` tracking state from the old
``_update_alert_indicators`` call site lives — moving it out of the
shared health loop and into its own process means a stuck GPIO chip
ioctl can no longer freeze OLED rendering or GPS sampling.

No HTTP API beyond ``/health`` — the GPIO subsystem is purely
event-driven (driven by Redis pub/sub flags written by the broadcast
pipeline).  The Flask app exists so systemd / the web UI can verify
"is the GPIO subprocess up?" at a known port.
"""

import logging
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from flask import Flask, jsonify

from services.common import (
    configure_logging,
    get_redis,
    init_database,
    init_runtime,
    install_signal_handlers,
    load_environment,
    publish_gpio_metrics,
)
from services.gpio import (
    initialize_gpio_controller,
    initialize_neopixel_controller,
    initialize_tower_light_controller,
    update_alert_indicators,
)

PORT = 5105
SUBSYSTEM = "gpio"
HEARTBEAT_INTERVAL_S = 5

_running = True
_gpio_controller: Optional[Any] = None
_neopixel_controller: Optional[Any] = None
_tower_light_controller: Optional[Any] = None


def _on_shutdown_signal(signum: int) -> None:
    global _running
    logging.getLogger(__name__).info(
        f"[{SUBSYSTEM}] received signal {signum}, initiating graceful shutdown..."
    )
    _running = False


def _build_app() -> Flask:
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok",
            "service": f"eas-station-{SUBSYSTEM}",
            "port": PORT,
            "gpio_controller_available": _gpio_controller is not None,
            "neopixel_available": _neopixel_controller is not None,
            "tower_light_available": (
                _tower_light_controller is not None
                and getattr(_tower_light_controller, "is_available", False)
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return app


def _run_api_server(app: Flask) -> None:
    log = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        log.error(f"[{SUBSYSTEM}] API server crashed: {e}", exc_info=True)


def main() -> None:
    global _gpio_controller, _neopixel_controller, _tower_light_controller

    configure_logging()
    logger = logging.getLogger(__name__)
    load_environment(logger)

    logger.info("=" * 60)
    logger.info(f"🔌 EAS Station - GPIO Subsystem (port {PORT})")
    logger.info("=" * 60)

    init_runtime(SUBSYSTEM)
    install_signal_handlers(_on_shutdown_signal)

    redis_client = None
    flask_app = None
    try:
        logger.info("Connecting to Redis...")
        redis_client = get_redis()
        logger.info("✅ Connected to Redis")

        logger.info("Initializing database connection...")
        flask_app, db = init_database()
        logger.info("✅ Database connected")

        with flask_app.app_context():
            logger.info("Initializing GPIO controller...")
            _gpio_controller = initialize_gpio_controller(db_session=db.session)
            logger.info("Initializing NeoPixel controller...")
            _neopixel_controller = initialize_neopixel_controller()
            logger.info("Initializing USB tower light controller...")
            _tower_light_controller = initialize_tower_light_controller()

        api_app = _build_app()
        logger.info(f"Starting GPIO health server on port {PORT}...")
        api_thread = threading.Thread(
            target=_run_api_server, args=(api_app,), daemon=True, name="gpio-api"
        )
        api_thread.start()
        logger.info("✅ GPIO health server started")

        # Alert-indicator state machine — runs every loop iteration
        # (1 s resolution) because tower-light / NeoPixel transitions
        # are user-visible and must feel "instant" relative to the
        # operator hitting the broadcast button.
        broadcast_was_active = False
        incoming_was_active = False
        last_heartbeat = 0.0

        while _running:
            now = time.time()
            try:
                if redis_client and (_tower_light_controller or _neopixel_controller):
                    broadcast_was_active, incoming_was_active = update_alert_indicators(
                        broadcast_was_active,
                        incoming_was_active,
                        tower_light_controller=_tower_light_controller,
                        neopixel_controller=_neopixel_controller,
                    )
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                    publish_gpio_metrics(
                        redis_client=redis_client,
                        gpio_controller=_gpio_controller,
                        neopixel_controller=_neopixel_controller,
                        tower_light_controller=_tower_light_controller,
                    )
                    last_heartbeat = now
            except Exception as e:
                logger.error(f"[{SUBSYSTEM}] error in alert indicator loop: {e}", exc_info=True)
                time.sleep(5)
                continue

            time.sleep(1)

    except KeyboardInterrupt:
        logger.info(f"[{SUBSYSTEM}] received interrupt signal")
    except Exception as e:
        logger.error(f"[{SUBSYSTEM}] fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info(f"[{SUBSYSTEM}] shutting down...")
        if _gpio_controller is not None:
            try:
                if hasattr(_gpio_controller, "cleanup"):
                    _gpio_controller.cleanup()
            except Exception as exc:
                logger.error(f"Error cleaning up GPIO: {exc}")
        if _neopixel_controller is not None:
            try:
                _neopixel_controller.cleanup()
            except Exception as exc:
                logger.error(f"Error cleaning up NeoPixel controller: {exc}")
        if _tower_light_controller is not None:
            try:
                _tower_light_controller.cleanup()
            except Exception as exc:
                logger.error(f"Error cleaning up USB tower light: {exc}")
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
        logger.info(f"[{SUBSYSTEM}] ✅ stopped cleanly")


if __name__ == "__main__":
    main()
