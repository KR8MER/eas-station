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

"""Drive tower-light + NeoPixel based on broadcast / incoming alert state.

The tower light follows a resolved-state model rather than pure edge
transitions: every refresh computes the *desired* state from the alert
pipeline, the Redis health probe, and the wall clock (quiet hours), and
only writes to the hardware when the desired state differs from the
last applied one. Priority order:

    fault > active broadcast (test / severity / plain)
          > incoming / active alert present > quiet hours > standby

"Active alert present" mirrors the website stack light
(``templates/components/navbar.html``): once audio playout finishes the
transient broadcast marker clears, but the light must stay lit (yellow,
flashing) while there is still at least one unexpired alert in the
system, instead of dropping straight back to green standby.
"""

import logging
import threading
from datetime import datetime
from typing import Callable, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)

#: SAME event codes that are tests, not live alerts.
TEST_EVENT_CODES = frozenset({"RWT", "RMT", "NPT", "DMO"})


class TowerState(NamedTuple):
    """A fully resolved tower-light state, ready to apply."""

    name: str       # 'standby' / 'incoming' / 'alert*' / 'test' / 'fault' / 'quiet'
    color: str      # preferred colour (may be 'off')
    fallback: str   # colour used when the protocol can't render `color`
    flash: bool
    buzzer: bool    # raw request — the controller enforces the master kill switch


def _parse_hhmm(value) -> int:
    """Parse 'HH:MM' to minutes-since-midnight; raises ValueError when invalid."""
    parts = str(value or "").strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"not HH:MM: {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"out of range: {value!r}")
    return hour * 60 + minute


def in_quiet_hours(start, end, now: Optional[datetime] = None) -> bool:
    """True when local time *now* falls inside [start, end), wrapping midnight.

    Invalid or equal start/end values disable quiet hours rather than
    erroring — a malformed schedule must never black out the indicator.
    """
    try:
        start_min, end_min = _parse_hhmm(start), _parse_hhmm(end)
    except (TypeError, ValueError):
        return False
    if start_min == end_min:
        return False
    current = now if now is not None else datetime.now()
    minutes = current.hour * 60 + current.minute
    if start_min < end_min:
        return start_min <= minutes < end_min
    return minutes >= start_min or minutes < end_min


def _product_class(event_code: str) -> str:
    """Return 'WRN' / 'WCH' / 'ADV' / 'TEST' / '' for a SAME event code."""
    try:
        from app_utils.event_codes import EVENT_CODE_REGISTRY
        entry = EVENT_CODE_REGISTRY.get((event_code or "").strip().upper()) or {}
        return str(entry.get("default_product", "")).upper()
    except Exception:
        return ""


def resolve_tower_state(
    config,
    broadcast_state: dict,
    incoming_active: bool,
    redis_ok: bool,
    now: Optional[datetime] = None,
    active_alert_count: int = 0,
    pending_gate_count: int = 0,
) -> TowerState:
    """Pure resolver — decide what the tower light should show right now.

    *config* is a :class:`app_utils.gpio.TowerLightConfig` (duck-typed).
    Active and incoming alerts always override quiet hours: a dark
    standby light must never suppress an alert indication.

    *active_alert_count* is the number of unexpired alerts currently in the
    system.  When it is positive but no broadcast is on air, the light holds
    the incoming (yellow, flashing) indication instead of returning to green
    standby — matching the website stack light, which stays lit while alerts
    are active rather than dropping to green the moment audio playout ends.

    *pending_gate_count* is the number of alerts sitting in the gated-alerts
    Pending Alerts queue (held for operator review before broadcast). It
    ranks below an active/incoming alert -- a live alert must never be
    visually buried by a "needs review" indication -- but above quiet hours,
    since an operator action item shouldn't be silenced by a dark schedule.
    """
    if not redis_ok and getattr(config, "fault_enabled", True):
        return TowerState("fault", config.fault_color, "red", True, False)

    if broadcast_state.get("active"):
        code = str(broadcast_state.get("event_code") or "").strip().upper()
        flash = config.blink_on_alert
        if code in TEST_EVENT_CODES:
            # Routine tests are visually distinct and never sound the buzzer.
            return TowerState("test", config.test_color, "green", flash, False)
        if getattr(config, "severity_colors_enabled", False):
            product = _product_class(code)
            if product == "WCH":
                return TowerState(
                    "alert_watch", config.watch_color, "yellow", flash, config.alert_buzzer
                )
            if product == "ADV":
                return TowerState(
                    "alert_advisory", config.advisory_color, "yellow", flash, config.alert_buzzer
                )
            # WRN and anything unknown gets the most urgent rendering.
            return TowerState(
                "alert_warning", config.warning_color, "red", flash, config.alert_buzzer
            )
        return TowerState("alert", config.alert_color, "red", flash, config.alert_buzzer)

    # An alert has either just been received (the short-lived "incoming"
    # marker) or there is still at least one unexpired alert in the system
    # after its broadcast finished.  Both render the same yellow/flashing
    # indication; only the state name differs so the transition is logged
    # accurately.  This is the fix for the light dropping to green standby
    # while an alert is still active.
    if (incoming_active or active_alert_count > 0) and config.incoming_uses_yellow:
        name = "incoming" if incoming_active else "active"
        return TowerState(
            name, config.incoming_color, "yellow", config.blink_on_alert, False
        )

    if pending_gate_count > 0 and getattr(config, "gate_pending_enabled", True):
        return TowerState(
            "gate_pending", config.gate_pending_color, "yellow", config.blink_on_alert, False
        )

    if getattr(config, "quiet_enabled", False) and in_quiet_hours(
        getattr(config, "quiet_start", None), getattr(config, "quiet_end", None), now
    ):
        return TowerState("quiet", "off", "off", False, False)

    return TowerState("standby", config.standby_color, "green", False, False)


def _redis_ok() -> bool:
    """Probe Redis directly — get_broadcast_state() swallows failures, so a
    dead Redis would otherwise be indistinguishable from a quiet one."""
    try:
        from app_core.redis_client import get_redis_client
        client = get_redis_client()
        if client is None:
            return False
        client.ping()
        return True
    except Exception:
        return False


def _key_relay_on_edges(
    gpio_controller,
    broadcast_state: dict,
    broadcast_active: bool,
    broadcast_was_active: bool,
    incoming_state: dict,
    incoming_active: bool,
    incoming_was_active: bool,
    relay_state: Optional[dict] = None,
) -> None:
    """Key the relay (PTT / audio-mute / duration / flash) on broadcast edges.

    The GPIO subprocess is the single owner of the physical relay lines, so it
    keys them off the same Redis broadcast-state marker every producer already
    publishes — rather than each producer building its own (contending,
    no-op-falling-back) controller.  Edge-triggered to mirror the NeoPixel:
    start on the rising edge of a broadcast, release on the falling edge.

    *relay_state* is caller-owned scratch state carried between edges.  It
    records which path keyed the rising edge so the falling edge can mirror it:
    a rising edge that fell back to ``activate_all`` must be released with
    ``deactivate_all``, because ``end_alert`` only drops pins the behavior
    manager is actually holding.  Without that pairing the fallback left every
    pin energised until the 300 s watchdog fired — the "relay held for the full
    watchdog instead of the broadcast length" failure.

    The 300 s controller watchdog remains a backstop: if a falling edge is ever
    missed (e.g. the marker TTL lapses without a clean clear) the relay still
    drops automatically.
    """
    if gpio_controller is None:
        return

    if relay_state is None:
        relay_state = {}

    behavior_manager = getattr(gpio_controller, "behavior_manager", None)

    # Incoming alert just arrived -> short pre-broadcast pulse.
    if incoming_active and not incoming_was_active and behavior_manager is not None:
        try:
            behavior_manager.trigger_incoming_alert(
                alert_id=str(incoming_state.get("identifier") or "") or None,
                event_code=str(incoming_state.get("event_code") or "") or None,
            )
        except Exception as exc:
            logger.warning("GPIO incoming-alert pulse failed: %s", exc)

    if broadcast_active and not broadcast_was_active:
        identifier = str(broadcast_state.get("identifier") or "") or None
        event_code = str(broadcast_state.get("event_code") or "") or None
        source = str(broadcast_state.get("source") or "").lower()
        forwarded = source == "forwarded"
        reason = f"Broadcast playout ({event_code or source or 'alert'})"
        handled = False
        if behavior_manager is not None:
            try:
                handled = bool(
                    behavior_manager.start_alert(
                        alert_id=identifier,
                        event_code=event_code,
                        reason=reason,
                        forwarded=forwarded,
                    )
                )
            except Exception as exc:
                logger.warning("GPIO start_alert failed: %s", exc)
        if not handled:
            # No behavior matrix configured (or it held nothing): fall back to
            # keying every configured pin for the broadcast, matching the
            # legacy producer behaviour.
            try:
                from app_utils.gpio import GPIOActivationType

                gpio_controller.activate_all(
                    activation_type=GPIOActivationType.AUTOMATIC,
                    alert_id=identifier,
                    reason=reason,
                )
            except Exception as exc:
                logger.warning("GPIO activate_all failed: %s", exc)
        # Remember which path keyed this broadcast so the falling edge can
        # release through the matching one.
        relay_state["managed"] = handled

    elif not broadcast_active and broadcast_was_active:
        identifier = str(broadcast_state.get("identifier") or "") or None
        event_code = str(broadcast_state.get("event_code") or "") or None
        # ``None`` when we never saw the rising edge (the subprocess started
        # mid-broadcast, or the marker appeared before this process was
        # listening).  We then can't tell which path keyed the relay, so we run
        # the blanket release too — leaving a transmitter keyed is far worse
        # than issuing a redundant deactivate, which is a no-op on an idle pin.
        managed = relay_state.pop("managed", None)

        # Always run through the manager when there is one, even if the rising
        # edge fell back: it keeps the manager's hold/flash bookkeeping in step
        # with the hardware, and is a no-op for anything it isn't holding.
        if behavior_manager is not None:
            try:
                # Release with forwarded=True so FORWARDING_ALERT hold pins are
                # always dropped.  The falling edge sees ``{"active": False}``
                # (the marker no longer carries the source), so we can't tell
                # whether the finished broadcast was forwarded — and end_alert is
                # a no-op for any behavior that wasn't actually held, so
                # releasing the superset is safe and prevents a forwarded-relay
                # from lingering until the watchdog.
                behavior_manager.end_alert(
                    alert_id=identifier,
                    event_code=event_code,
                    forwarded=True,
                )
            except Exception as exc:
                logger.warning("GPIO end_alert failed: %s", exc)

        if managed is not True:
            try:
                # force=True: the broadcast has ended, drop the air chain now
                # rather than waiting out each pin's anti-chatter min-hold.
                gpio_controller.deactivate_all(force=True)
            except Exception as exc:
                logger.warning("GPIO deactivate_all failed: %s", exc)


def update_alert_indicators(
    broadcast_was_active: bool,
    incoming_was_active: bool,
    tower_light_controller=None,
    neopixel_controller=None,
    tower_state_was: Optional[TowerState] = None,
    active_alert_count_fn: Optional[Callable[[], int]] = None,
    gpio_controller=None,
    relay_state: Optional[dict] = None,
    gate_pending_was_active: bool = False,
    pending_gate_count_fn: Optional[Callable[[], int]] = None,
) -> Tuple[bool, bool, Optional[TowerState], bool]:
    """Resolve and apply the indicator state for this refresh.

    The NeoPixel keeps its original edge-triggered behaviour (alert
    colour while a broadcast is active, standby otherwise). The tower
    light is driven by :func:`resolve_tower_state`; hardware is only
    written when the resolved state changes.

    *gpio_controller*, when supplied, is the subprocess's single owned relay
    controller.  Its relay pins are keyed off the broadcast-state edges here so
    no other process needs to (or can) claim the same lines.  *relay_state* is
    the caller-owned dict that carries relay bookkeeping between edges (see
    :func:`_key_relay_on_edges`); omitting it means each falling edge releases
    through both paths, which is safe but noisier.

    *active_alert_count_fn*, when supplied, returns the number of unexpired
    alerts in the system.  It lets the tower light stay lit while an alert is
    active after its broadcast has finished (see :func:`resolve_tower_state`).
    Any failure is swallowed and treated as zero so a database hiccup can never
    crash the indicator loop.

    *pending_gate_count_fn*, when supplied, returns the number of alerts
    currently sitting in the gated-alerts Pending Alerts queue. Drives both
    the GATE_PENDING relay behavior (a lamp/buzzer telling an operator
    something needs review) -- edge-triggered against *gate_pending_was_active*
    like the broadcast/incoming markers, since this is queue-depth level
    state, not a single alert's lifecycle -- and the tower light's
    ``gate_pending`` color state via :func:`resolve_tower_state`.

    Returns ``(broadcast_active, incoming_active, tower_state,
    gate_pending_active)`` so the caller can carry state across iterations.
    """
    redis_ok = _redis_ok()
    try:
        from app_utils.eas import get_broadcast_state, get_incoming_alert_state
        broadcast_state = get_broadcast_state() or {}
        broadcast_active = bool(broadcast_state.get("active", False))
        incoming_state = get_incoming_alert_state() or {}
        incoming_active = bool(incoming_state.get("incoming", False))
    except Exception:
        # State unreadable: keep the previous flags so the NeoPixel sees no
        # false edge, and let the fault state (below) inform the operator.
        broadcast_state = {}
        incoming_state = {}
        broadcast_active = broadcast_was_active
        incoming_active = incoming_was_active
        redis_ok = False

    active_alert_count = 0
    if active_alert_count_fn is not None:
        try:
            active_alert_count = int(active_alert_count_fn())
        except Exception as exc:
            logger.debug("active alert count lookup failed: %s", exc)
            active_alert_count = 0

    pending_gate_count = 0
    if pending_gate_count_fn is not None:
        try:
            pending_gate_count = int(pending_gate_count_fn())
        except Exception as exc:
            logger.debug("pending gate count lookup failed: %s", exc)
            pending_gate_count = 0
    gate_pending_active = pending_gate_count > 0

    # Relay (transmitter PTT / audio mute / duration / flash): keyed here in the
    # single pin-owning subprocess, off the broadcast-state edges.
    _key_relay_on_edges(
        gpio_controller,
        broadcast_state,
        broadcast_active,
        broadcast_was_active,
        incoming_state,
        incoming_active,
        incoming_was_active,
        relay_state=relay_state,
    )

    # GATE_PENDING relay: edge-triggered on queue depth crossing zero, not on
    # a single alert's lifecycle -- mirrors the incoming/broadcast edges above.
    if gate_pending_active != gate_pending_was_active:
        behavior_manager = getattr(gpio_controller, "behavior_manager", None)
        if behavior_manager is not None:
            try:
                behavior_manager.set_gate_pending(gate_pending_active)
            except Exception as exc:
                logger.warning("GPIO gate-pending indicator update failed: %s", exc)

    # NeoPixel: original two-state edge behaviour.
    if neopixel_controller:
        if broadcast_active and not broadcast_was_active:
            try:
                neopixel_controller.start_alert()
            except Exception as exc:
                logger.warning("NeoPixel start_alert failed: %s", exc)
        elif not broadcast_active and broadcast_was_active:
            try:
                neopixel_controller.end_alert()
            except Exception as exc:
                logger.warning("NeoPixel end_alert failed: %s", exc)

    # Tower light: resolved-state model.
    tower_state = tower_state_was
    if tower_light_controller is not None and getattr(
        tower_light_controller, "is_available", False
    ):
        desired = resolve_tower_state(
            tower_light_controller.config,
            broadcast_state,
            incoming_active,
            redis_ok,
            active_alert_count=active_alert_count,
            pending_gate_count=pending_gate_count,
        )
        if desired != tower_state_was:
            try:
                tower_light_controller.show_state(
                    desired.color,
                    flash=desired.flash,
                    buzzer=desired.buzzer,
                    fallback=desired.fallback,
                )
                logger.info(
                    "Tower light: %s -> %s (%s%s%s)",
                    tower_state_was.name if tower_state_was else "init",
                    desired.name,
                    desired.color,
                    ", flashing" if desired.flash else "",
                    ", buzzer" if desired.buzzer else "",
                )
                tower_state = desired
            except Exception as exc:
                # Keep the old state so the next refresh retries the write.
                logger.warning("Tower light state change failed: %s", exc)

    return broadcast_active, incoming_active, tower_state, gate_pending_active


class AlertIndicatorMonitor:
    """Thread-safe owner of the tower-light / NeoPixel alert-indicator state.

    Wraps :func:`update_alert_indicators` so it can be driven from two places at
    once without races:

    * a **pub/sub listener thread** that calls :meth:`refresh` the instant the
      broadcast pipeline publishes a state change (sub-second response), and
    * a **periodic poll** that calls :meth:`refresh` every second as a safety net
      in case a notification is ever missed (Redis reconnect, dropped message).
      The poll also drives the time-based transitions (quiet hours) and the
      fault probe, which have no pub/sub trigger.

    Previous-state tracking lives here behind a lock, so concurrent refreshes
    serialise cleanly and a single state change can never be applied twice.
    """

    def __init__(
        self,
        tower_light_controller=None,
        neopixel_controller=None,
        active_alert_count_fn: Optional[Callable[[], int]] = None,
        gpio_controller=None,
        pending_gate_count_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        self.tower_light_controller = tower_light_controller
        self.neopixel_controller = neopixel_controller
        self.active_alert_count_fn = active_alert_count_fn
        self.gpio_controller = gpio_controller
        self.pending_gate_count_fn = pending_gate_count_fn
        self._broadcast_was_active = False
        self._incoming_was_active = False
        self._tower_state: Optional[TowerState] = None
        self._gate_pending_was_active = False
        #: Relay bookkeeping carried between broadcast edges (which keying path
        #: the rising edge used).  Guarded by the same lock as the edge flags.
        self._relay_state: dict = {}
        self._lock = threading.Lock()

    def refresh(self) -> Tuple[bool, bool]:
        """Re-read alert state and apply any transition to the indicators.

        Safe to call concurrently from the listener thread and the poll loop;
        calls are serialised so each state change is applied exactly once.
        """
        with self._lock:
            (
                self._broadcast_was_active,
                self._incoming_was_active,
                self._tower_state,
                self._gate_pending_was_active,
            ) = update_alert_indicators(
                self._broadcast_was_active,
                self._incoming_was_active,
                tower_light_controller=self.tower_light_controller,
                neopixel_controller=self.neopixel_controller,
                tower_state_was=self._tower_state,
                active_alert_count_fn=self.active_alert_count_fn,
                gpio_controller=self.gpio_controller,
                relay_state=self._relay_state,
                gate_pending_was_active=self._gate_pending_was_active,
                pending_gate_count_fn=self.pending_gate_count_fn,
            )
            return self._broadcast_was_active, self._incoming_was_active
