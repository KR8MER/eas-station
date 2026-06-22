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

"""Zigbee subsystem subprocess entry point.

Phase 4 of the hardware_service.py split.  Owns the zigpy-znp
coordinator stack and the ``/api/zigbee/*`` blueprint.  Listens on
port 5102.  Isolating Zigbee in its own process means a dongle hang
(stuck serial reads, ZNP firmware deadlock) can't block OLED rendering
or GPS sampling.
"""

import logging
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, jsonify

from services.common import (
    configure_logging,
    get_redis,
    init_database,
    init_runtime,
    install_signal_handlers,
    load_environment,
    publish_zigbee_metrics,
)
from services.zigbee import (
    create_blueprint,
    initialize_zigbee_coordinator,
)
from services.zigbee.controller import ZigpyController

PORT = 5102
SUBSYSTEM = "zigbee"
HEARTBEAT_INTERVAL_S = 5

_running = True
_zigpy_controller: Optional[ZigpyController] = None


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
            "coordinator_running": bool(
                _zigpy_controller is not None
                and getattr(_zigpy_controller, "running", False)
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    app.register_blueprint(
        create_blueprint(get_zigpy_controller=lambda: _zigpy_controller)
    )
    return app


def _run_api_server(app: Flask) -> None:
    log = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        log.error(f"[{SUBSYSTEM}] API server crashed: {e}", exc_info=True)


def main() -> None:
    global _zigpy_controller

    configure_logging()
    logger = logging.getLogger(__name__)
    load_environment(logger)

    logger.info("=" * 60)
    logger.info(f"📡 EAS Station - Zigbee Subsystem (port {PORT})")
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
        flask_app, _ = init_database()
        logger.info("✅ Database connected")

        logger.info("Initializing Zigbee coordinator...")
        with flask_app.app_context():
            _zigpy_controller = initialize_zigbee_coordinator(redis_client)

        api_app = _build_app()
        logger.info(f"Starting Zigbee API server on port {PORT}...")
        api_thread = threading.Thread(
            target=_run_api_server, args=(api_app,), daemon=True, name="zigbee-api"
        )
        api_thread.start()
        logger.info("✅ Zigbee API server started")

        last_heartbeat = 0.0
        while _running:
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                publish_zigbee_metrics(
                    redis_client=redis_client,
                    flask_app=flask_app,
                    zigpy_controller=_zigpy_controller,
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
        if _zigpy_controller is not None:
            try:
                _zigpy_controller.stop()
            except Exception as exc:
                logger.error(f"Error stopping Zigbee controller: {exc}")
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
        logger.info(f"[{SUBSYSTEM}] ✅ stopped cleanly")


if __name__ == "__main__":
    main()
