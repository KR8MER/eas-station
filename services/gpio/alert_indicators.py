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

from __future__ import annotations

"""Drive tower-light + NeoPixel based on broadcast / incoming alert state."""

import logging
import threading
from typing import Tuple

logger = logging.getLogger(__name__)


def update_alert_indicators(
    broadcast_was_active: bool,
    incoming_was_active: bool,
    tower_light_controller=None,
    neopixel_controller=None,
) -> Tuple[bool, bool]:
    """Drive tower light and NeoPixel controllers based on broadcast state.

    Reads the current ``eas:broadcast_active`` and ``eas:incoming_alert``
    Redis keys and calls the appropriate alert-lifecycle methods on any
    configured hardware indicator controllers whenever the state changes.

    The tower light follows a three-state machine:
      idle → incoming (yellow) → active broadcast (red) → idle (green)

    Returns ``(broadcast_active, incoming_active)`` so the caller can
    track state across loop iterations.
    """
    try:
        from app_utils.eas import get_broadcast_state, get_incoming_alert_state
        state = get_broadcast_state()
        broadcast_active = bool(state.get('active', False))
        incoming_state = get_incoming_alert_state()
        incoming_active = bool(incoming_state.get('incoming', False))
    except Exception:
        return broadcast_was_active, incoming_was_active  # Leave light in current state on error

    # Transition: * → active broadcast (broadcast takes priority over incoming)
    if broadcast_active and not broadcast_was_active:
        if tower_light_controller and tower_light_controller.is_available:
            try:
                tower_light_controller.start_alert()
            except Exception as exc:
                logger.warning("Tower light start_alert failed: %s", exc)
        if neopixel_controller:
            try:
                neopixel_controller.start_alert()
            except Exception as exc:
                logger.warning("NeoPixel start_alert failed: %s", exc)

    # Transition: active → idle (broadcast ended)
    elif not broadcast_active and broadcast_was_active:
        if tower_light_controller and tower_light_controller.is_available:
            try:
                tower_light_controller.end_alert()
            except Exception as exc:
                logger.warning("Tower light end_alert failed: %s", exc)
        if neopixel_controller:
            try:
                neopixel_controller.end_alert()
            except Exception as exc:
                logger.warning("NeoPixel end_alert failed: %s", exc)

    # Transition: idle → incoming (alert received, broadcast not yet started)
    elif not broadcast_active and incoming_active and not incoming_was_active:
        if tower_light_controller and tower_light_controller.is_available:
            try:
                tower_light_controller.start_incoming_alert()
            except Exception as exc:
                logger.warning("Tower light start_incoming_alert failed: %s", exc)

    # Transition: incoming → idle (alert rejected or expired without broadcast)
    elif not broadcast_active and not incoming_active and incoming_was_active:
        if tower_light_controller and tower_light_controller.is_available:
            try:
                tower_light_controller.end_alert()
            except Exception as exc:
                logger.warning("Tower light end_alert (incoming expired) failed: %s", exc)

    return broadcast_active, incoming_active


class AlertIndicatorMonitor:
    """Thread-safe owner of the tower-light / NeoPixel alert-indicator state.

    Wraps :func:`update_alert_indicators` so it can be driven from two places at
    once without races:

    * a **pub/sub listener thread** that calls :meth:`refresh` the instant the
      broadcast pipeline publishes a state change (sub-second response), and
    * a **periodic poll** that calls :meth:`refresh` every second as a safety net
      in case a notification is ever missed (Redis reconnect, dropped message).

    The previous-state tracking that used to live as two loop locals in the GPIO
    subprocess now lives here behind a lock, so concurrent refreshes serialise
    cleanly and a single state change can never be applied twice.
    """

    def __init__(self, tower_light_controller=None, neopixel_controller=None) -> None:
        self.tower_light_controller = tower_light_controller
        self.neopixel_controller = neopixel_controller
        self._broadcast_was_active = False
        self._incoming_was_active = False
        self._lock = threading.Lock()

    def refresh(self) -> Tuple[bool, bool]:
        """Re-read alert state and apply any transition to the indicators.

        Safe to call concurrently from the listener thread and the poll loop;
        calls are serialised so each state change is applied exactly once.
        """
        with self._lock:
            self._broadcast_was_active, self._incoming_was_active = update_alert_indicators(
                self._broadcast_was_active,
                self._incoming_was_active,
                tower_light_controller=self.tower_light_controller,
                neopixel_controller=self.neopixel_controller,
            )
            return self._broadcast_was_active, self._incoming_was_active
