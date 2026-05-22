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

"""Displays subsystem subprocess entry point.

Phase 4 of the hardware_service.py split.  Owns the LED sign, the VFD,
the OLED display, and the screen_manager rotation thread, plus the
``/api/hardware/display/push`` endpoint.  Listens on port 5104.

Splitting displays into its own subprocess means a wedged I2C bus or a
serial VFD that stops draining its write buffer can never block the
GPS NMEA reader or the Zigbee coordinator — those run in different
processes now.
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
    publish_displays_metrics,
)
from services.displays import (
    create_blueprint,
    initialize_led_controller,
    initialize_oled_display,
    initialize_screen_manager,
    initialize_vfd_controller,
)

PORT = 5104
SUBSYSTEM = "displays"
HEARTBEAT_INTERVAL_S = 5

_running = True
_screen_manager: Optional[Any] = None
_flask_app: Optional[Flask] = None


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
            "screen_manager_running": (
                _screen_manager is not None
                and getattr(_screen_manager, "_running", False)
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    app.register_blueprint(create_blueprint(get_flask_app=lambda: _flask_app))
    return app


def _run_api_server(app: Flask) -> None:
    log = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        log.error(f"[{SUBSYSTEM}] API server crashed: {e}", exc_info=True)


def main() -> None:
    global _screen_manager, _flask_app

    configure_logging()
    logger = logging.getLogger(__name__)
    load_environment(logger)

    logger.info("=" * 60)
    logger.info(f"🖥  EAS Station - Displays Subsystem (port {PORT})")
    logger.info("=" * 60)

    init_runtime(SUBSYSTEM)
    install_signal_handlers(_on_shutdown_signal)

    redis_client = None
    try:
        logger.info("Connecting to Redis...")
        redis_client = get_redis()
        logger.info("✅ Connected to Redis")

        logger.info("Initializing database connection...")
        _flask_app, _ = init_database()
        logger.info("✅ Database connected")

        # Controller initialisation order matches Phase 3:
        # LED + VFD + OLED before screen_manager (which composes them).
        with _flask_app.app_context():
            logger.info("Initializing LED controller...")
            initialize_led_controller()
            logger.info("Initializing VFD controller...")
            initialize_vfd_controller()
            logger.info("Initializing OLED display...")
            initialize_oled_display()

        logger.info("Initializing screen manager...")
        _screen_manager = initialize_screen_manager(_flask_app)

        api_app = _build_app()
        logger.info(f"Starting Displays API server on port {PORT}...")
        api_thread = threading.Thread(
            target=_run_api_server, args=(api_app,), daemon=True, name="displays-api"
        )
        api_thread.start()
        logger.info("✅ Displays API server started")

        last_heartbeat = 0.0
        while _running:
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                publish_displays_metrics(
                    redis_client=redis_client,
                    flask_app=_flask_app,
                    screen_manager=_screen_manager,
                )
                last_heartbeat = now
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info(f"[{SUBSYSTEM}] received interrupt signal")
    except Exception as e:
        logger.error(f"[{SUBSYSTEM}] fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info(f"[{SUBSYSTEM}] shutting down...")
        if _screen_manager is not None:
            try:
                if hasattr(_screen_manager, "stop"):
                    _screen_manager.stop()
            except Exception as exc:
                logger.error(f"Error stopping screen manager: {exc}")
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
        logger.info(f"[{SUBSYSTEM}] ✅ stopped cleanly")


if __name__ == "__main__":
    main()
