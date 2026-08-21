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

from __future__ import annotations

"""Web-app-side consumer for GPIO input-pin trigger events.

The ``eas-station-gpio`` subprocess only reads pins and publishes an event
(see ``app_utils.gpio.input_watcher.GPIOInputWatcher`` and
``app_core.gpio_commands.GPIO_INPUT_EVENT_CHANNEL``) -- the actual actions an
input can invoke (running an RWT, forwarding an alert, aborting a broadcast)
all live in the main web app. This module is the subscriber that turns a
published event into the real action call.

Started alongside the RWT scheduler (``app_core/rwt_scheduler.py``) in
``app.py``, since it already runs in-process there and dispatching RUN_RWT
just calls straight into that same module.
"""

import json
import logging
import threading
import time

logger = logging.getLogger(__name__)


def start_gpio_input_listener(app) -> threading.Thread:
    """Start the background listener thread. Returns the started thread."""
    thread = threading.Thread(
        target=_run_input_event_listener, args=(app,), daemon=True,
        name="gpio-input-listener",
    )
    thread.start()
    return thread


def _run_input_event_listener(app) -> None:
    """Subscribe to GPIO_INPUT_EVENT_CHANNEL and dispatch each trigger.

    Reconnect-with-backoff pubsub loop, mirroring the GPIO subprocess's own
    ``_run_command_listener`` (``services/gpio/__main__.py``).
    """
    from app_core.gpio_commands import GPIO_INPUT_EVENT_CHANNEL
    from app_core.redis_client import get_redis_client

    backoff = 1.0
    while True:
        pubsub = None
        try:
            client = get_redis_client()
            if client is None:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(GPIO_INPUT_EVENT_CHANNEL)
            logger.info("GPIO input event listener subscribed to '%s'", GPIO_INPUT_EVENT_CHANNEL)
            backoff = 1.0
            while True:
                message = pubsub.get_message(timeout=1.0)
                if message is None:
                    continue
                try:
                    event = json.loads(message.get("data") or "{}")
                except (ValueError, TypeError) as exc:
                    logger.warning("Ignoring malformed GPIO input event: %s", exc)
                    continue
                try:
                    with app.app_context():
                        _dispatch_input_action(event)
                except Exception as exc:
                    logger.warning("GPIO input action dispatch failed: %s", exc)
        except Exception as exc:
            logger.warning("GPIO input event listener disconnected (%s); retrying in %.0fs", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass


def _dispatch_input_action(event: dict) -> None:
    from app_utils.gpio.pin_types import GPIOInputAction

    pin = event.get("pin")
    action_value = event.get("action")
    action = GPIOInputAction.from_value(action_value)

    if action == GPIOInputAction.RUN_RWT:
        logger.info("GPIO input pin %s triggered: Run RWT Now", pin)
        _trigger_rwt_from_input()
    elif action == GPIOInputAction.FORWARD_LAST_ALERT:
        logger.info("GPIO input pin %s triggered Forward Last Alert (not yet implemented)", pin)
    elif action == GPIOInputAction.DUMP_BROADCAST:
        logger.info("GPIO input pin %s triggered Dump Broadcast (not yet implemented)", pin)
    else:
        logger.warning("Ignoring GPIO input event with unknown action %r (pin %s)", action_value, pin)


def _trigger_rwt_from_input() -> None:
    """Run an RWT the same way the manual 'Run Test Now' button does.

    Mirrors POST /api/rwt-schedule/test (webapp/routes_rwt_schedule.py)
    exactly: same config lookup, same live-broadcast guard, same trigger
    function -- a GPIO input is just a second trigger source for the
    identical, already-reviewed action.
    """
    from app_core.models import RWTScheduleConfig
    from app_core.rwt_scheduler import trigger_rwt_broadcast
    from app_utils.eas import get_broadcast_state

    config = RWTScheduleConfig.query.first()
    if config is None:
        logger.warning("GPIO-triggered RWT skipped: no RWT schedule configuration found")
        return

    broadcast_state = get_broadcast_state()
    if broadcast_state.get("active"):
        logger.warning(
            "GPIO-triggered RWT skipped: a broadcast is already in progress"
        )
        return

    trigger_rwt_broadcast(config, logger)
