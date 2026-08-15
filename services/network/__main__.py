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

"""Network subsystem subprocess entry point.

Phase 4 of the hardware_service.py split.  Runs the ``/api/network/*``
blueprint (nmcli proxy, hostname helpers) in its own process so a
NetworkManager / DBus stall can't take down OLED rendering or GPS
sampling.  Listens on port 5101.

The network subsystem has no long-lived controllers — every endpoint
shells out to nmcli or reads ``/proc`` on demand — so the runtime loop
is minimal: it exists only to publish a periodic "I am alive" heartbeat
into ``hardware:metrics:network`` while serving the Flask blueprint in
a background thread.
"""

import logging
import sys
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify

from services.common import (
    configure_logging,
    get_redis,
    init_runtime,
    install_service_auth,
    install_signal_handlers,
    load_environment,
    publish_network_metrics,
)
from services.network import create_blueprint

PORT = 5101
SUBSYSTEM = "network"
HEARTBEAT_INTERVAL_S = 5

_running = True


def _on_shutdown_signal(signum: int) -> None:
    """Flip the process-local _running flag in response to SIGTERM/SIGINT."""
    global _running
    logging.getLogger(__name__).info(
        f"[{SUBSYSTEM}] received signal {signum}, initiating graceful shutdown..."
    )
    _running = False


def _build_app() -> Flask:
    """Assemble the network subsystem Flask app."""
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok",
            "service": f"eas-station-{SUBSYSTEM}",
            "port": PORT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    app.register_blueprint(create_blueprint())
    install_service_auth(app, SUBSYSTEM)
    return app


def _run_api_server(app: Flask) -> None:
    """Run Flask API server in a background thread."""
    log = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        log.error(f"[{SUBSYSTEM}] API server crashed: {e}", exc_info=True)


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    load_environment(logger)

    logger.info("=" * 60)
    logger.info(f"🌐 EAS Station - Network Subsystem (port {PORT})")
    logger.info("=" * 60)

    init_runtime(SUBSYSTEM)
    install_signal_handlers(_on_shutdown_signal)

    redis_client = None
    try:
        logger.info("Connecting to Redis...")
        redis_client = get_redis()
        logger.info("✅ Connected to Redis")

        app = _build_app()
        logger.info(f"Starting network API server on port {PORT}...")
        api_thread = threading.Thread(
            target=_run_api_server, args=(app,), daemon=True, name="network-api"
        )
        api_thread.start()
        logger.info("✅ Network API server started")

        last_heartbeat = 0.0
        while _running:
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                publish_network_metrics(redis_client=redis_client)
                last_heartbeat = now
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info(f"[{SUBSYSTEM}] received interrupt signal")
    except Exception as e:
        logger.error(f"[{SUBSYSTEM}] fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info(f"[{SUBSYSTEM}] shutting down...")
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
        logger.info(f"[{SUBSYSTEM}] ✅ stopped cleanly")


if __name__ == "__main__":
    main()
