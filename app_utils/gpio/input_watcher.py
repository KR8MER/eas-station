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

"""Read GPIO INPUT pins (physical buttons/contact closures) and turn presses
into cross-process events.

Unlike the rest of ``app_utils.gpio`` (entirely output-only -- relays driven
via :class:`~app_utils.gpio.controller.GPIOController`), this module reads
pins. It runs inside the ``eas-station-gpio`` subprocess, alongside but
independent of ``GPIOController``, since reading is a different concern from
driving and shares only the physical-pin-ownership boundary.

Pattern mirrors the Argon OLED button (``app_core/oled.py``: lazily-imported
``gpiozero.Button`` to dodge gevent monkey-patch conflicts, debounce via
``bounce_time``) and its dispatch model (``scripts/screen_manager.py``:
gpiozero's own callback thread only enqueues an action string; a separate
loop drains the queue and acts on it -- business logic never runs on the
interrupt callback thread).
"""

import logging
import queue
import threading
from typing import Any, Dict, List, Optional

from .backends import ensure_gpiozero_pin_factory
from .pin_types import GPIO_INPUT_ACTION_IMPLEMENTED, GPIOInputAction, GPIOPinConfig

# gpiozero Button is imported lazily, same rationale as app_core/oled.py: the
# import must not happen at module load time, since some processes that
# import this package (the web app) run gevent-patched and gpiozero conflicts
# with that patching.
_Button = None


def _get_gpiozero_button():
    global _Button
    if _Button is None:
        try:
            from gpiozero import Button as _ButtonClass
            _Button = _ButtonClass
        except Exception:
            pass
    return _Button


class GPIOInputWatcher:
    """Owns one ``gpiozero.Button`` per configured GPIO input pin.

    Construct with the input-direction :class:`GPIOPinConfig` entries, then
    call :meth:`start`. Each button press is queued (never dispatched
    directly from gpiozero's callback thread) and drained by a dedicated
    thread that publishes a :data:`GPIO_INPUT_EVENT_CHANNEL` event for the
    web app to act on.
    """

    def __init__(self, input_pins: List[GPIOPinConfig], logger=None) -> None:
        self.input_pins = list(input_pins)
        self.logger = logger or logging.getLogger(__name__)
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._buttons: Dict[int, Any] = {}
        self._dispatch_thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def active_pin_count(self) -> int:
        return len(self._buttons)

    def start(self) -> None:
        """Build a Button for each implemented, actionable input pin and
        start the dispatch thread. No-op if there is nothing to watch."""
        if not self.input_pins:
            return

        button_class = _get_gpiozero_button()
        if button_class is None:
            self.logger.warning("gpiozero unavailable; GPIO input pins will not be read")
            return
        if not ensure_gpiozero_pin_factory(self.logger):
            self.logger.warning("gpiozero pin factory unavailable; cannot read GPIO input pins")
            return

        for config in self.input_pins:
            action = GPIOInputAction.from_value(config.input_action) if config.input_action else None
            if action is None or action == GPIOInputAction.NONE:
                continue
            if action not in GPIO_INPUT_ACTION_IMPLEMENTED:
                self.logger.info(
                    "GPIO input pin %s assigned action '%s', which is not yet "
                    "implemented; ignoring", config.pin, action.value,
                )
                continue

            try:
                button = button_class(
                    config.pin,
                    pull_up=not config.active_high,
                    bounce_time=max(0.001, config.input_bounce_ms / 1000.0),
                )
            except Exception as exc:  # pragma: no cover - hardware specific
                self.logger.warning("Failed to initialize GPIO input pin %s: %s", config.pin, exc)
                continue

            if action == GPIOInputAction.DUMP_BROADCAST:
                # A momentary bump or contact bounce must not be able to
                # abort a live broadcast -- require a sustained hold instead
                # of a plain press.
                button.hold_time = config.input_hold_confirm_seconds or 3.0
                button.when_held = self._make_handler(config.pin, action)
            else:
                button.when_pressed = self._make_handler(config.pin, action)

            self._buttons[config.pin] = button
            self.logger.info("GPIO input pin %s configured for action '%s'", config.pin, action.value)

        if not self._buttons:
            return

        self._running = True
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="gpio-input-dispatch",
        )
        self._dispatch_thread.start()
        self.logger.info("GPIO input watcher started (%d pin(s))", len(self._buttons))

    def stop(self) -> None:
        self._running = False
        for pin, button in self._buttons.items():
            try:
                button.close()
            except Exception:  # pragma: no cover - hardware specific
                self.logger.debug("Error closing GPIO input pin %s", pin)
        self._buttons.clear()

    def _make_handler(self, pin: int, action: GPIOInputAction):
        # Runs on gpiozero's own callback thread -- must never call into
        # application/business logic directly, only enqueue.
        def _handler() -> None:
            self._queue.put((pin, action.value))
        return _handler

    def _dispatch_loop(self) -> None:
        from app_core.gpio_commands import publish_gpio_input_event

        while self._running:
            try:
                pin, action_value = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                publish_gpio_input_event(pin, action_value)
                self.logger.info("GPIO input pin %s triggered action '%s'", pin, action_value)
            except Exception as exc:  # pragma: no cover - best effort
                self.logger.warning("Failed to publish GPIO input event: %s", exc)
