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

"""Coordinate GPIO actions against the alert lifecycle."""

import threading
import time
from typing import Dict, Iterable, List, Optional, Set


from .pin_types import (
    GPIO_BEHAVIOR_LABELS, GPIO_BEHAVIOR_PULSE_DEFAULTS, TRANSMIT_CAPABLE_BEHAVIORS, GPIOActivationType, GPIOBehavior, GPIOPinConfig, GPIOState,
)
from .controller import GPIOController

class GPIOBehaviorManager:
    """Coordinate GPIO actions tied to alert lifecycle events."""

    def __init__(
        self,
        controller: Optional["GPIOController"],
        pin_configs: Iterable[GPIOPinConfig],
        behavior_matrix: Optional[Dict[int, Set[GPIOBehavior]]] = None,
        logger=None,
    ) -> None:
        self.controller = controller
        self.logger = logger
        self.behavior_matrix: Dict[int, Set[GPIOBehavior]] = behavior_matrix or {}
        self.pin_configs: Dict[int, GPIOPinConfig] = {
            cfg.pin: cfg for cfg in pin_configs
        }

        self._behavior_to_pins: Dict[GPIOBehavior, Set[int]] = {}
        self._hold_map: Dict[int, Set[GPIOBehavior]] = {}
        # Pins currently flashing under the FLASH behavior.  The actual flash
        # threads live in the controller (the single flash engine); the manager
        # only tracks which pins it asked the controller to flash so it can stop
        # them on end_alert / shutdown.
        self._flash_pins: Set[int] = set()
        self._warned_unconfigured: Set[int] = set()
        self._lock = threading.RLock()

        self._rebuild_behavior_index()

        # Surface silent-failure footguns (e.g. nothing keys the transmitter) as
        # soon as the manager is wired up, while we still have a logger handy.
        if self.logger:
            for warning in self.validate_configuration():
                self.logger.warning("GPIO behavior configuration: %s", warning)

    @property
    def is_configured(self) -> bool:
        """Return ``True`` if any behaviors have been assigned."""

        return bool(self.controller and self.behavior_matrix)

    def update_pin_configs(self, configs: Iterable[GPIOPinConfig]) -> None:
        """Refresh the active pin configuration mapping."""

        self.pin_configs = {cfg.pin: cfg for cfg in configs}

    def update_behavior_matrix(self, matrix: Dict[int, Set[GPIOBehavior]]) -> None:
        """Replace the behavior matrix and rebuild indexes."""

        self.behavior_matrix = matrix or {}
        self._rebuild_behavior_index()

    def trigger_incoming_alert(
        self,
        *,
        alert_id: Optional[str] = None,
        event_code: Optional[str] = None,
    ) -> None:
        """Pulse pins that should react when an alert arrives."""

        self._pulse_behavior(GPIOBehavior.INCOMING_ALERT, alert_id, event_code)

    def trigger_forwarding_alert(
        self,
        *,
        alert_id: Optional[str] = None,
        event_code: Optional[str] = None,
    ) -> None:
        """Pulse pins that signal an alert forwarding decision."""

        self._pulse_behavior(GPIOBehavior.FORWARDING_ALERT, alert_id, event_code)

    def start_alert(
        self,
        *,
        alert_id: Optional[str] = None,
        event_code: Optional[str] = None,
        reason: Optional[str] = None,
        forwarded: bool = False,
    ) -> bool:
        """Begin alert playout behaviors.

        When *forwarded* is ``True`` (alert is being relayed from a monitoring
        input), pins configured for :attr:`GPIOBehavior.FORWARDING_ALERT` are
        held HIGH for the full broadcast duration instead of the normal 5-second
        pulse.  This ensures the relay stays active the entire time the station
        has control of the airchain.

        Returns ``True`` when the manager is actively holding pins and should
        receive a matching :meth:`end_alert` call.
        """

        if not self.controller:
            return False

        reason = reason or "Automatic alert playout"
        hold_started = False

        # FLASH owns its pins exclusively.  A pin assigned FLASH blinks for the
        # whole alert and is never also driven as a solid hold — otherwise the
        # hold (solid ON) and the flash engine would fight over the same line.
        flash_pins = self._pins_for_behavior(GPIOBehavior.FLASH)

        # Behaviors that hold a relay solid for the broadcast window.
        #   TRANSMITTER_PTT — keys the station transmitter (held for the whole alert)
        #   AUDIO_MUTE      — mutes / ducks program audio while EAS audio is on air
        hold_behaviors = [
            GPIOBehavior.DURATION_OF_ALERT,
            GPIOBehavior.PLAYOUT,
            GPIOBehavior.TRANSMITTER_PTT,
            GPIOBehavior.AUDIO_MUTE,
        ]
        if forwarded:
            hold_behaviors.append(GPIOBehavior.FORWARDING_ALERT)

        for behavior in hold_behaviors:
            for pin in self._pins_for_behavior(behavior):
                if pin in flash_pins:
                    continue  # FLASH takes precedence on shared pins
                if self._add_hold(pin, behavior, alert_id, event_code, reason):
                    hold_started = True

        flash_started = self._start_flash(alert_id, event_code, reason)

        self._pulse_behavior(
            GPIOBehavior.FIVE_SECONDS,
            alert_id,
            event_code,
            pulse_seconds=GPIO_BEHAVIOR_PULSE_DEFAULTS[GPIOBehavior.FIVE_SECONDS],
        )

        # Only holds and flashes count as "handled".  The caller treats a False
        # return as "the matrix took nothing for this broadcast" and falls back
        # to keying every configured pin, which is what keeps the air chain up.
        #
        # A FIVE_SECONDS pulse used to count too, and that silently dropped the
        # transmitter: on a station whose relay is assigned FORWARDING_ALERT
        # (held only for forwarded alerts) plus a 5-second beacon pulse, an
        # automated RWT held nothing, pulsed the beacon, reported "handled", and
        # so skipped the fallback — the beacon blinked and the transmitter never
        # keyed. A five-second pulse cannot carry a broadcast that runs for
        # minutes, so it must not suppress the fallback.
        handled = hold_started or flash_started
        if not handled and self.logger:
            self.logger.warning(
                "GPIO behavior matrix held no pin for this broadcast "
                "(event=%s, forwarded=%s); falling back to keying all configured "
                "pins. Assign a transmit-capable behavior (Transmitter PTT, "
                "Duration of Alert or Audio Playout) to the relay pin to control "
                "this explicitly.",
                event_code or "unknown",
                forwarded,
            )
        return handled

    def end_alert(
        self,
        *,
        alert_id: Optional[str] = None,
        event_code: Optional[str] = None,
        reason: Optional[str] = None,
        forwarded: bool = False,
    ) -> None:
        """Release any pins held for alert playout behaviors."""

        if not self.controller:
            return

        reason = reason or "Alert playout completed"

        hold_behaviors = [
            GPIOBehavior.DURATION_OF_ALERT,
            GPIOBehavior.PLAYOUT,
            GPIOBehavior.TRANSMITTER_PTT,
            GPIOBehavior.AUDIO_MUTE,
        ]
        if forwarded:
            hold_behaviors.append(GPIOBehavior.FORWARDING_ALERT)

        for behavior in hold_behaviors:
            for pin in self._pins_for_behavior(behavior):
                self._release_hold(pin, behavior, alert_id, event_code, reason)

        self._stop_flash(alert_id, event_code)

    def validate_configuration(self) -> List[str]:
        """Return human-readable warnings about the behavior configuration.

        Surfaces silent-failure footguns at startup so an operator finds out
        *before* a real alert that, for example, nothing will key their
        transmitter.  Returns an empty list when the configuration looks sound.
        """

        warnings: List[str] = []

        if not self.behavior_matrix:
            return warnings

        assigned: Set[GPIOBehavior] = set()
        for behaviors in self.behavior_matrix.values():
            assigned.update(behaviors)

        # 1. No pin will key the transmitter / hold the airchain during an alert.
        if not (assigned & TRANSMIT_CAPABLE_BEHAVIORS):
            transmit_labels = ", ".join(
                sorted(GPIO_BEHAVIOR_LABELS[b] for b in TRANSMIT_CAPABLE_BEHAVIORS)
            )
            warnings.append(
                "No GPIO pin is assigned a transmit-capable behavior "
                f"({transmit_labels}); the transmitter will NOT be keyed during a "
                "broadcast. Assign one of these behaviors to the transmit relay pin."
            )

        # 2. A behavior references a pin that is not an active GPIO pin.
        for pin, behaviors in self.behavior_matrix.items():
            if pin not in self.pin_configs:
                labels = ", ".join(
                    sorted(
                        GPIO_BEHAVIOR_LABELS.get(b, b.value) for b in behaviors
                    )
                )
                warnings.append(
                    f"GPIO pin {pin} has behaviors assigned ({labels}) but is not an "
                    "active pin in GPIO settings; those behaviors will be ignored."
                )

        # 3. A FLASH pin names a partner that is not itself flashing — the
        #    alternating pattern will not work as expected.
        flash_pins = self._behavior_to_pins.get(GPIOBehavior.FLASH, set())
        for pin in flash_pins:
            config = self.pin_configs.get(pin)
            if config is None:
                continue
            partner = config.flash_partner_pin
            if partner is not None and partner not in flash_pins:
                warnings.append(
                    f"GPIO pin {pin} flashes with partner pin {partner}, but pin "
                    f"{partner} is not assigned the Flash Beacon behavior; the "
                    "two-phase alternating pattern will not run."
                )

        return warnings

    def shutdown(self) -> None:
        """Release every pin the manager is holding and stop all flashing.

        Called from :meth:`GPIOController.cleanup` so a process shutdown can
        never leave a manager-driven relay energised (e.g. transmitter still
        keyed) waiting on the watchdog timeout.
        """

        self._stop_flash(None, None)

        with self._lock:
            held = list(self._hold_map.keys())
            self._hold_map.clear()

        for pin in held:
            try:
                self.controller.deactivate(pin, force=True)
            except Exception as exc:  # pragma: no cover - hardware specific
                if self.logger:
                    self.logger.warning(
                        "Failed to release GPIO pin %s during shutdown: %s", pin, exc
                    )

    # ------------------------------------------------------------------
    # Internal helpers

    def _rebuild_behavior_index(self) -> None:
        index: Dict[GPIOBehavior, Set[int]] = {behavior: set() for behavior in GPIOBehavior}
        for pin, behaviors in (self.behavior_matrix or {}).items():
            for behavior in behaviors:
                index.setdefault(behavior, set()).add(pin)
        self._behavior_to_pins = index

    def _pins_for_behavior(self, behavior: GPIOBehavior) -> Set[int]:
        pins = self._behavior_to_pins.get(behavior, set())
        if not pins:
            return set()

        valid: Set[int] = set()
        for pin in pins:
            if pin in self.pin_configs:
                valid.add(pin)
            elif pin not in self._warned_unconfigured:
                if self.logger:
                    self.logger.warning(
                        "GPIO behavior configured for pin %s but pin is not active in GPIO settings",
                        pin,
                    )
                self._warned_unconfigured.add(pin)
        return valid

    def _add_hold(
        self,
        pin: int,
        behavior: GPIOBehavior,
        alert_id: Optional[str],
        event_code: Optional[str],
        reason: str,
    ) -> bool:
        with self._lock:
            hold_behaviors = self._hold_map.setdefault(pin, set())
            if behavior in hold_behaviors:
                return True

        label = GPIO_BEHAVIOR_LABELS.get(behavior, behavior.value.replace("_", " ").title())
        activation_reason = f"{label} activation"
        if reason:
            activation_reason = f"{activation_reason} - {reason}"

        # flash=False keeps the relay solid for the whole hold even if the pin
        # config happens to set flash_enabled — flashing is driven exclusively
        # by the FLASH behavior, not by held relays (PTT, audio mute, etc.).
        success = self.controller.activate(
            pin=pin,
            activation_type=GPIOActivationType.AUTOMATIC,
            alert_id=alert_id,
            reason=activation_reason,
            flash=False,
        )
        if not success:
            # ``activate()`` refuses a pin that is already ACTIVE, which happens
            # routinely: a second hold behavior assigned to the same pin, or a
            # still-running INCOMING_ALERT pulse the broadcast overlapped.  The
            # relay is energised either way, so adopt it into the hold map —
            # otherwise _release_hold() sees no hold to release at
            # end-of-broadcast and the pin stays keyed until the watchdog fires.
            try:
                success = self.controller.get_state(pin) == GPIOState.ACTIVE
            except Exception:  # pragma: no cover - hardware specific
                success = False

        if success:
            with self._lock:
                self._hold_map.setdefault(pin, set()).add(behavior)
        return success

    def _release_hold(
        self,
        pin: int,
        behavior: GPIOBehavior,
        alert_id: Optional[str],
        event_code: Optional[str],
        reason: str,
    ) -> None:
        with self._lock:
            hold_behaviors = self._hold_map.get(pin)
            if not hold_behaviors or behavior not in hold_behaviors:
                return
            hold_behaviors.discard(behavior)
            if hold_behaviors:
                return
            self._hold_map.pop(pin, None)

        try:
            # force=True: the broadcast has genuinely ended, so the relay must
            # drop now.  Without it, deactivate() honours the pin's min-hold
            # (hold_seconds) by sleeping the remaining time while the relay is
            # still asserted — which, on a pin whose hold_seconds exceeds the
            # playout (e.g. a long anti-chatter value), keeps the transmitter
            # keyed and the on-air overlay up long after the audio finished.
            # The min-hold is anti-chatter for rapid toggles, not a reason to
            # hold the air chain past end-of-message.
            self.controller.deactivate(pin, force=True)
        except Exception as exc:  # pragma: no cover - hardware specific
            if self.logger:
                self.logger.warning(
                    "Failed to release GPIO pin %s after %s: %s",
                    pin,
                    behavior.value,
                    exc,
                )

    def _pulse_behavior(
        self,
        behavior: GPIOBehavior,
        alert_id: Optional[str],
        event_code: Optional[str],
        pulse_seconds: Optional[float] = None,
    ) -> bool:
        if not self.controller:
            return False

        pins = self._pins_for_behavior(behavior)
        if not pins:
            return False

        duration = pulse_seconds or GPIO_BEHAVIOR_PULSE_DEFAULTS.get(behavior, 3.0)
        label = GPIO_BEHAVIOR_LABELS.get(behavior, behavior.value)

        for pin in pins:
            threading.Thread(
                target=self._pulse_pin,
                name=f"gpio-pulse-{pin}-{behavior.value}",
                kwargs={
                    "pin": pin,
                    "duration": duration,
                    "label": label,
                    "alert_id": alert_id,
                },
                daemon=True,
            ).start()

        return True

    def _pulse_pin(
        self,
        *,
        pin: int,
        duration: float,
        label: str,
        alert_id: Optional[str],
    ) -> None:
        success = self.controller.activate(
            pin=pin,
            activation_type=GPIOActivationType.AUTOMATIC,
            alert_id=alert_id,
            reason=f"{label} pulse",
        )
        if not success:
            return

        time.sleep(max(0.1, duration))

        with self._lock:
            if self._hold_map.get(pin) or pin in self._flash_pins:
                # A broadcast starting during this pulse adopted the pin as a
                # hold (or handed it to the flash engine).  Releasing here would
                # un-key the transmitter mid-alert; the owning behavior drops it
                # at end-of-broadcast instead.
                return

        try:
            self.controller.deactivate(pin, force=True)
        except Exception as exc:  # pragma: no cover - hardware specific
            if self.logger:
                self.logger.warning(
                    "Failed to release GPIO pin %s after pulse: %s",
                    pin,
                    exc,
                )

    def _start_flash(
        self,
        alert_id: Optional[str],
        event_code: Optional[str],
        reason: str,
    ) -> bool:
        """Start the FLASH behavior by delegating to the controller flash engine.

        The controller is the single flash authority: ``activate(flash=True)``
        spins up exactly one flash thread per pin and drives the configured
        ``flash_partner_pin`` in opposite phase.  The manager only records which
        pins it started so it can stop them in :meth:`_stop_flash`.
        """
        pins = self._pins_for_behavior(GPIOBehavior.FLASH)
        if not pins or not self.controller:
            return False

        started = False
        staged: Set[int] = set()

        for pin in sorted(pins):
            config = self.pin_configs.get(pin)
            partner_pin = config.flash_partner_pin if config else None
            if partner_pin not in pins:
                partner_pin = None
            # The controller flash thread drives both halves of a partner pair,
            # so only start one pin per pair to avoid two threads fighting.
            if partner_pin is not None and partner_pin in staged:
                continue

            with self._lock:
                if pin in self._flash_pins:
                    continue
                self._flash_pins.add(pin)

            ok = self.controller.activate(
                pin=pin,
                activation_type=GPIOActivationType.AUTOMATIC,
                alert_id=alert_id,
                reason=f"Flash beacon ({reason})",
                flash=True,
            )
            if ok:
                started = True
                staged.add(pin)
                if partner_pin is not None:
                    staged.add(partner_pin)
            else:
                with self._lock:
                    self._flash_pins.discard(pin)

        return started

    def _stop_flash(
        self,
        alert_id: Optional[str],
        event_code: Optional[str],
    ) -> None:
        with self._lock:
            pins = list(self._flash_pins)
            self._flash_pins.clear()

        for pin in pins:
            # Deactivating the pin stops the controller flash thread, which rests
            # both the pin and its partner OFF as part of its cleanup.
            try:
                self.controller.deactivate(pin, force=True)
            except Exception:  # pragma: no cover - hardware specific
                pass
