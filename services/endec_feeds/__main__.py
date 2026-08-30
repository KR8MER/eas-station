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

"""ENDEC device-feed subsystem entry point.

Runs the TCP fan-out for the Sage-ENDEC-compatible device feeds. Subscribes
to the Redis feed-event channel (published by
``app_core.audio.endec_feed_publisher``), renders each event into the wire
format configured for every feed, and pushes the bytes to connected TCP
clients. A second control channel triggers a hot reload of the feed config
when an operator saves changes in the admin UI.

Exposes a minimal ``/health`` endpoint on port 5111 so systemd and the web UI
can confirm the subprocess is up.
"""

import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify

from services.common import (
    configure_logging,
    get_redis,
    init_database,
    init_runtime,
    install_signal_handlers,
    load_environment,
)
from services.endec_feeds.server import FeedManager, normalize_feeds
from app_core.audio.endec_feed_publisher import (
    ENDEC_FEED_CHANNEL,
    ENDEC_FEED_RELOAD_CHANNEL as RELOAD_CHANNEL,
)
from app_utils.endec_feeds import feed_event_from_payload
from app_utils.system.sd_notify import notify as sd_notify, Watchdog

PORT = 5111
SUBSYSTEM = "endec-feeds"

_running = True


def _on_shutdown_signal(signum: int) -> None:
    global _running
    logging.getLogger(__name__).info(
        f"[{SUBSYSTEM}] received signal {signum}, initiating graceful shutdown..."
    )
    _running = False


def _load_feeds(app) -> list:
    """Read the current feed configuration from the database."""
    from app_core.models import EASSettings

    with app.app_context():
        settings = EASSettings.query.get(1)
        if settings is None:
            return []
        master = bool(getattr(settings, "endec_feeds_enabled", False))
        raw = getattr(settings, "endec_feeds", None) or []
        return normalize_feeds(raw, master_enabled=master)


def _build_app(manager: FeedManager) -> Flask:
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "ok",
            "service": f"eas-station-{SUBSYSTEM}",
            "port": PORT,
            "active_feed_ports": manager.active_ports,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return app


def _run_api_server(app: Flask) -> None:
    log = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as exc:
        log.error(f"[{SUBSYSTEM}] health API crashed: {exc}", exc_info=True)


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    load_environment(logger)

    logger.info("=" * 60)
    logger.info(f"📡 EAS Station - ENDEC Device Feeds (health port {PORT})")
    logger.info("=" * 60)

    init_runtime(SUBSYSTEM)
    install_signal_handlers(_on_shutdown_signal)

    manager = FeedManager()
    db_app = None
    redis_client = None

    try:
        db_app, _ = init_database()
        feeds = _load_feeds(db_app)
        manager.reconfigure(feeds)
        logger.info("Started %d ENDEC feed listener(s): ports=%s",
                    len(manager.active_ports), manager.active_ports)

        # Health endpoint in a background thread.
        health_thread = threading.Thread(
            target=_run_api_server, args=(_build_app(manager),),
            daemon=True, name="endec-feeds-health",
        )
        health_thread.start()

        redis_client = get_redis()
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(ENDEC_FEED_CHANNEL, RELOAD_CHANNEL)
        logger.info("Subscribed to '%s' and '%s'", ENDEC_FEED_CHANNEL, RELOAD_CHANNEL)

        # Tell systemd we're up (Type=notify + WatchdogSec= on this unit) and
        # start kicking the watchdog from inside the loop -- a hang stops the
        # kicks and systemd restarts the unit.
        sd_notify("READY=1")
        systemd_watchdog = Watchdog()

        while _running:
            systemd_watchdog.kick()
            message = pubsub.get_message(timeout=1.0)
            if not message or message.get("type") != "message":
                continue

            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8", "replace")

            if channel == RELOAD_CHANNEL:
                logger.info("Reloading ENDEC feed configuration...")
                try:
                    manager.reconfigure(_load_feeds(db_app))
                    logger.info("Reloaded; active ports=%s", manager.active_ports)
                except Exception as exc:
                    logger.error("Feed reload failed: %s", exc, exc_info=True)
                continue

            # Feed event
            try:
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8", "replace")
                event = feed_event_from_payload(json.loads(data))
                manager.dispatch(event)
            except Exception as exc:
                logger.debug("Dropped malformed feed event: %s", exc)

    except KeyboardInterrupt:
        logger.info(f"[{SUBSYSTEM}] received interrupt signal")
    except Exception as exc:
        logger.error(f"[{SUBSYSTEM}] fatal error: {exc}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info(f"[{SUBSYSTEM}] shutting down...")
        manager.stop_all()
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
        logger.info(f"[{SUBSYSTEM}] ✅ stopped cleanly")


if __name__ == "__main__":
    main()
