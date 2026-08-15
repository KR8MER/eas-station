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

"""GPS subsystem subprocess entry point.

Phase 4 of the hardware_service.py split.  Owns the GPS receiver
manager (NMEA reader, PPS jitter ring, chrony parser), the multi-tier
trend archive sampler, and the ``/api/hardware/gps/*`` blueprint.
Listens on port 5103.

The GPS subprocess is the only home for the per-tier
``_gps_trend_last_bucket_ids`` state that used to live as a global on
``hardware_service.py``.  Moving it here means a wedged GPS serial
port can never starve the OLED screen rotation — that runs in
eas-station-displays.service, in a different process.
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
    install_service_auth,
    install_signal_handlers,
    load_environment,
    publish_gps_metrics,
)
from services.gps import (
    GPS_TRENDS_INTERVAL_S,
    EventDetector,
    create_blueprint,
    initialize_gps_manager,
    new_last_bucket_ids,
    publish_events,
)
from services.gps import trends as _gps_trends
from services.gps.trends import collect_chrony_tracking

PORT = 5103
SUBSYSTEM = "gps"
HEARTBEAT_INTERVAL_S = 5

_running = True
_gps_manager: Optional[Any] = None
_flask_app: Optional[Flask] = None
_redis_client = None

# Per-tier "last seen bucket id" — was a module global on
# hardware_service.py; now lives here so the GPS subprocess owns the
# only copy.  See services.gps.trends.emit_rollups for the semantics.
_gps_trend_last_bucket_ids = new_last_bucket_ids()

# Server-side equivalent of the JS detectEvents() that used to populate
# the dashboard's Events & Alarms panel.  Runs on every trend tick so
# state-change events get logged even when no browser is open; the
# dashboard hydrates from Redis on page load.
_event_detector = EventDetector()


def _on_shutdown_signal(signum: int) -> None:
    global _running
    logging.getLogger(__name__).info(
        f"[{SUBSYSTEM}] received signal {signum}, initiating graceful shutdown..."
    )
    _running = False


def _restart_gps_manager(enabled: bool) -> None:
    """Stop any running GPS manager and start a new one when ``enabled``.

    Called by the ``/api/hardware/gps/configure`` route after persisting
    new settings to the DB.  Owns the Flask app context so the new
    manager can read its config from the database.
    """
    global _gps_manager
    if _gps_manager is not None:
        try:
            _gps_manager.stop()
        except Exception as exc:
            logging.getLogger(__name__).error(f"Error stopping GPS manager: {exc}")
        _gps_manager = None
    if enabled and _flask_app is not None:
        with _flask_app.app_context():
            _gps_manager = initialize_gps_manager(_redis_client, logging.getLogger(__name__))


def _build_app() -> Flask:
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        has_fix = False
        if _gps_manager is not None:
            try:
                status = _gps_manager.get_status() or {}
                has_fix = bool(status.get("has_fix"))
            except Exception:
                pass
        return jsonify({
            "status": "ok",
            "service": f"eas-station-{SUBSYSTEM}",
            "port": PORT,
            "manager_running": _gps_manager is not None,
            "has_fix": has_fix,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    app.register_blueprint(
        create_blueprint(
            get_gps_manager=lambda: _gps_manager,
            get_redis_client=lambda: _redis_client,
            restart_gps_manager=_restart_gps_manager,
        )
    )
    install_service_auth(app, SUBSYSTEM)
    return app


def _run_api_server(app: Flask) -> None:
    log = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        log.error(f"[{SUBSYSTEM}] API server crashed: {e}", exc_info=True)


def main() -> None:
    global _gps_manager, _flask_app, _redis_client

    configure_logging()
    logger = logging.getLogger(__name__)
    load_environment(logger)

    logger.info("=" * 60)
    logger.info(f"🛰  EAS Station - GPS Subsystem (port {PORT})")
    logger.info("=" * 60)

    init_runtime(SUBSYSTEM)
    install_signal_handlers(_on_shutdown_signal)

    try:
        logger.info("Connecting to Redis...")
        _redis_client = get_redis()
        logger.info("✅ Connected to Redis")

        logger.info("Initializing database connection...")
        _flask_app, _ = init_database()
        logger.info("✅ Database connected")

        logger.info("Initializing GPS receiver...")
        with _flask_app.app_context():
            _gps_manager = initialize_gps_manager(_redis_client, logger)

        api_app = _build_app()
        logger.info(f"Starting GPS API server on port {PORT}...")
        api_thread = threading.Thread(
            target=_run_api_server, args=(api_app,), daemon=True, name="gps-api"
        )
        api_thread.start()
        logger.info("✅ GPS API server started")

        last_sample = 0.0
        last_heartbeat = 0.0
        while _running:
            now = time.time()
            # Trend sampler at GPS_TRENDS_INTERVAL_S (5 s) — produces
            # one row of NMEA / chrony / PPS-jitter data and rolls up
            # closed 1m/10m/1h buckets.  Was driven by
            # hardware_service.health_check_loop in Phase 3; now lives
            # alongside its data source.
            if now - last_sample >= GPS_TRENDS_INTERVAL_S:
                _gps_trends.publish_sample(
                    _redis_client, _gps_manager, _gps_trend_last_bucket_ids
                )
                # State-change events run on the same cadence as trend
                # samples.  Build a snapshot in the same shape the
                # dashboard sees so the detector logic stays a 1:1 port
                # of the JS version it replaces.
                try:
                    gps_status: Any = {}
                    if _gps_manager is not None:
                        gps_status = _gps_manager.get_status() or {}
                    chrony_fields = collect_chrony_tracking() or {}
                    snapshot = {
                        "gps": gps_status,
                        "chrony": {"tracking": chrony_fields},
                    }
                    new_events = _event_detector.detect(snapshot)
                    publish_events(_redis_client, new_events)
                except Exception as exc:
                    logger.debug("Event detector tick failed: %s", exc)
                last_sample = now
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                publish_gps_metrics(redis_client=_redis_client, gps_manager=_gps_manager)
                last_heartbeat = now
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info(f"[{SUBSYSTEM}] received interrupt signal")
    except Exception as e:
        logger.error(f"[{SUBSYSTEM}] fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info(f"[{SUBSYSTEM}] shutting down...")
        if _gps_manager is not None:
            try:
                _gps_manager.stop()
            except Exception as exc:
                logger.error(f"Error stopping GPS manager: {exc}")
        if _redis_client is not None:
            try:
                _redis_client.close()
            except Exception:
                pass
        logger.info(f"[{SUBSYSTEM}] ✅ stopped cleanly")


if __name__ == "__main__":
    main()
