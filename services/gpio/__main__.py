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

import atexit
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
    AlertIndicatorMonitor,
    initialize_gpio_controller,
    initialize_neopixel_controller,
    initialize_tower_light_controller,
)

PORT = 5105
SUBSYSTEM = "gpio"
HEARTBEAT_INTERVAL_S = 5

_running = True
_gpio_controller: Optional[Any] = None
_neopixel_controller: Optional[Any] = None
_tower_light_controller: Optional[Any] = None
_cleaned_up = False
_cleanup_lock = threading.Lock()


def _cleanup_controllers() -> None:
    """Release every hardware controller exactly once.

    Shared by the ``main()`` finally block and an ``atexit`` backstop so a
    relay (e.g. a keyed transmitter) is never left energised on shutdown,
    regardless of which exit path the process takes.  Idempotent and
    thread-safe.
    """
    global _cleaned_up
    with _cleanup_lock:
        if _cleaned_up:
            return
        _cleaned_up = True

    log = logging.getLogger(__name__)
    if _gpio_controller is not None:
        try:
            if hasattr(_gpio_controller, "cleanup"):
                _gpio_controller.cleanup()
        except Exception as exc:
            log.error(f"Error cleaning up GPIO: {exc}")
    if _neopixel_controller is not None:
        try:
            _neopixel_controller.cleanup()
        except Exception as exc:
            log.error(f"Error cleaning up NeoPixel controller: {exc}")
    if _tower_light_controller is not None:
        try:
            _tower_light_controller.cleanup()
        except Exception as exc:
            log.error(f"Error cleaning up USB tower light: {exc}")


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


def _make_active_alert_counter(flask_app):
    """Return a callable counting unexpired alerts in its own app context.

    Mirrors ``/api/broadcast/state`` (webapp/routes_monitoring.py) so the
    physical tower light and the website stack light agree on what "an alert is
    active" means.  Runs inside ``flask_app.app_context()`` because the
    indicator refresh loop and pub/sub listener run outside the bootstrap
    context.  Any failure returns 0 so a database hiccup never crashes the
    indicator loop or blacks out the light.
    """

    def _count() -> int:
        try:
            from datetime import datetime, timezone
            from app_core.models import CAPAlert

            with flask_app.app_context():
                now_utc = datetime.now(timezone.utc)
                return int(CAPAlert.query.filter(CAPAlert.expires > now_utc).count())
        except Exception as exc:  # pragma: no cover - defensive
            logging.getLogger(__name__).debug("active alert count failed: %s", exc)
            return 0

    return _count


def _run_indicator_listener(monitor: "AlertIndicatorMonitor") -> None:
    """Subscribe to indicator events and refresh the moment state changes.

    Gives the tower light / NeoPixel sub-second response instead of waiting for
    the 1-second poll.  Reconnects with backoff if Redis drops; the poll loop in
    :func:`main` keeps indicators correct in the gaps.
    """
    log = logging.getLogger(__name__)
    from app_utils.eas import _INDICATOR_CHANNEL

    backoff = 1.0
    while _running:
        pubsub = None
        try:
            client = get_redis()
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(_INDICATOR_CHANNEL)
            log.info(f"[{SUBSYSTEM}] subscribed to indicator events on '{_INDICATOR_CHANNEL}'")
            backoff = 1.0  # reset after a clean connection
            # Block briefly for messages so we can still notice shutdown.
            while _running:
                message = pubsub.get_message(timeout=1.0)
                if message is not None:
                    try:
                        monitor.refresh()
                    except Exception as exc:
                        log.warning(f"[{SUBSYSTEM}] indicator refresh on event failed: {exc}")
        except Exception as exc:
            if _running:
                log.warning(
                    f"[{SUBSYSTEM}] indicator listener disconnected ({exc}); "
                    f"retrying in {backoff:.0f}s"
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass


def _publish_pin_state_snapshot(redis_client) -> None:
    """Publish the relay controller's live pin states for the web UI to read.

    The web app no longer builds its own controller (it can't claim the pins),
    so it renders the GPIO Control page from this snapshot instead.
    """
    if redis_client is None or _gpio_controller is None:
        return
    try:
        from app_core.gpio_commands import publish_pin_states

        states = list(_gpio_controller.get_all_states().values())
        publish_pin_states(redis_client, states)
    except Exception as exc:  # pragma: no cover - defensive
        logging.getLogger(__name__).debug("pin-state publish failed: %s", exc)


def _run_command_listener(flask_app) -> None:
    """Execute manual GPIO commands published by the web UI.

    Subscribes to the GPIO command channel and dispatches each command to the
    single owned controller, then republishes the pin-state snapshot so the UI
    reflects the change immediately.  Reconnects with backoff if Redis drops.
    """
    log = logging.getLogger(__name__)
    from app_core.gpio_commands import GPIO_COMMAND_CHANNEL, dispatch_gpio_command

    import json as _json

    backoff = 1.0
    while _running:
        pubsub = None
        try:
            client = get_redis()
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(GPIO_COMMAND_CHANNEL)
            log.info(f"[{SUBSYSTEM}] subscribed to GPIO commands on '{GPIO_COMMAND_CHANNEL}'")
            backoff = 1.0
            while _running:
                message = pubsub.get_message(timeout=1.0)
                if message is None:
                    continue
                try:
                    command = _json.loads(message.get("data") or "{}")
                except (ValueError, TypeError) as exc:
                    log.warning(f"[{SUBSYSTEM}] ignoring malformed GPIO command: {exc}")
                    continue
                try:
                    # Activation logging needs an application/database context.
                    with flask_app.app_context():
                        dispatch_gpio_command(_gpio_controller, command, logger=log)
                    _publish_pin_state_snapshot(client)
                except Exception as exc:
                    log.warning(f"[{SUBSYSTEM}] GPIO command execution failed: {exc}")
        except Exception as exc:
            if _running:
                log.warning(
                    f"[{SUBSYSTEM}] GPIO command listener disconnected ({exc}); "
                    f"retrying in {backoff:.0f}s"
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass


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

        # Backstop: guarantee every controller is released on *any* process exit
        # (including non-signal paths like sys.exit), not just the finally block
        # below.  Registered atexit handlers run last-in-first-out.
        atexit.register(_cleanup_controllers)

        api_app = _build_app()
        logger.info(f"Starting GPIO health server on port {PORT}...")
        api_thread = threading.Thread(
            target=_run_api_server, args=(api_app,), daemon=True, name="gpio-api"
        )
        api_thread.start()
        logger.info("✅ GPIO health server started")

        # Alert-indicator state machine.  Driven two ways:
        #   1. event-driven via a Redis pub/sub listener (sub-second response), and
        #   2. a 1-second poll below as a safety net for any missed notification.
        # Both call the same thread-safe monitor so a state change is applied once.
        indicator_monitor = AlertIndicatorMonitor(
            tower_light_controller=_tower_light_controller,
            neopixel_controller=_neopixel_controller,
            active_alert_count_fn=_make_active_alert_counter(flask_app),
            gpio_controller=_gpio_controller,
        )
        # The monitor now also keys the relay off the broadcast-state marker, so
        # it must run whenever a relay controller exists — not only when a tower
        # light / NeoPixel is attached.
        indicators_active = bool(
            _tower_light_controller or _neopixel_controller or _gpio_controller
        )
        if indicators_active:
            listener_thread = threading.Thread(
                target=_run_indicator_listener,
                args=(indicator_monitor,),
                daemon=True,
                name="gpio-indicator-listener",
            )
            listener_thread.start()
            logger.info("✅ GPIO indicator event listener started")

        # Manual GPIO control commands from the web UI (the GPIO Control page
        # "test" buttons) arrive on a Redis channel because only this process
        # owns the physical lines.
        if _gpio_controller is not None:
            command_thread = threading.Thread(
                target=_run_command_listener,
                args=(flask_app,),
                daemon=True,
                name="gpio-command-listener",
            )
            command_thread.start()
            logger.info("✅ GPIO command listener started")

        last_heartbeat = 0.0

        while _running:
            now = time.time()
            try:
                if redis_client and indicators_active:
                    # Safety-net poll; the listener handles the fast path.
                    indicator_monitor.refresh()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                    publish_gpio_metrics(
                        redis_client=redis_client,
                        gpio_controller=_gpio_controller,
                        neopixel_controller=_neopixel_controller,
                        tower_light_controller=_tower_light_controller,
                    )
                    _publish_pin_state_snapshot(redis_client)
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
        _cleanup_controllers()
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
        logger.info(f"[{SUBSYSTEM}] ✅ stopped cleanly")


if __name__ == "__main__":
    main()
