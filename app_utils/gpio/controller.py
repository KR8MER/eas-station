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

"""The unified GPIO controller: pin management, keying, audit logging."""

import contextlib
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


from .pin_types import (
    GPIOActivationEvent,
    GPIOActivationType, GPIOPinConfig, GPIOState,
)
from .backends import (
    OutputDevice, GPIOBackend, _BackendPinDevice,
    _NullGPIOBackend, _create_gpio_backend,
    _ensure_pin_factory, _explain_environment_issue,
)

class GPIOController:
    """Unified GPIO controller with audit logging and safety features.

    This class provides centralized control over GPIO pins with:
    - Thread-safe activation/deactivation
    - Watchdog timers to prevent stuck relays
    - Debounce protection
    - Activation history for audit trails
    - Support for multiple pins with independent configuration

    Example:
        controller = GPIOController(db_session, logger)

        # Configure a pin
        config = GPIOPinConfig(
            pin=17,
            name="Transmitter PTT",
            active_high=True,
            hold_seconds=5.0,
            watchdog_seconds=300.0
        )
        controller.add_pin(config)

        # Activate for an alert
        controller.activate(
            pin=17,
            activation_type=GPIOActivationType.AUTOMATIC,
            alert_id="alert-123",
            reason="Tornado Warning"
        )

        # Deactivate
        controller.deactivate(pin=17)
    """

    def __init__(self, db_session=None, logger=None, db_app=None):
        """Initialize GPIO controller.

        Args:
            db_session: SQLAlchemy session for audit logging (optional)
            logger: Logger instance for diagnostics (optional)
            db_app: Flask application owning *db_session* (optional).  Required
                when the controller is driven from background threads — see
                :meth:`_db_context`.
        """
        self.db_session = db_session
        self.db_app = db_app
        self.logger = logger
        self._pins: Dict[int, GPIOPinConfig] = {}
        self._states: Dict[int, GPIOState] = {}
        self._activation_times: Dict[int, float] = {}
        self._current_events: Dict[int, GPIOActivationEvent] = {}
        self._lock = threading.RLock()
        self._watchdog_threads: Dict[int, threading.Thread] = {}
        self._flash_threads: Dict[int, threading.Thread] = {}  # Flash pattern threads
        self._flash_stop_events: Dict[int, threading.Event] = {}  # Flash stop signals
        self._devices: Dict[int, Any] = {}
        self._last_verification: Dict[int, Dict[str, Any]] = {}
        self._backend: Optional[GPIOBackend] = None
        self._backend_failures: Set[type] = set()
        self._environment_issues: Set[str] = set()
        self._gpiozero_available = bool(
            OutputDevice is not None
            and _ensure_pin_factory(
                logger,
                issue_recorder=self._record_environment_issue,
            )
        )
        self._initialized = self._gpiozero_available

        if self._gpiozero_available:
            if self.logger:
                self.logger.info("GPIO controller initialized using gpiozero OutputDevice")
        elif self._ensure_backend():
            self._initialized = True
            if self.logger:
                self.logger.info(
                    "GPIO controller initialized using %s",
                    self._current_backend_label(),
                )
        elif self.logger:
            self.logger.warning("gpiozero OutputDevice not available - GPIO control disabled")

    def _record_environment_issue(self, detail: str) -> None:
        explanation = _explain_environment_issue(detail)
        message = explanation or detail
        if message:
            self._environment_issues.add(message)

    def _current_backend_label(self, backend: Optional[GPIOBackend] = None) -> str:
        target = backend if backend is not None else self._backend
        if target is None:
            return "gpiozero OutputDevice"
        name = target.__class__.__name__.lstrip("_")
        if name.lower().endswith("backend"):
            name = name[:-7]
        return f"{name or 'GPIO'} backend"

    def _ensure_backend(self) -> bool:
        if self._backend is not None:
            return True

        while True:
            backend = _create_gpio_backend(self._backend_failures)
            if backend is None:
                return False

            try:
                backend.setmode(backend.BCM)
            except Exception as exc:
                if self.logger:
                    self.logger.error(
                        "Failed to initialize fallback GPIO backend %s: %s",
                        self._current_backend_label(backend),
                        exc,
                    )
                self._record_environment_issue(str(exc))
                self._backend_failures.add(type(backend))
                continue

            self._backend = backend
            return True

    def _setup_backend_device(
        self, config: GPIOPinConfig, *, fallback_reason: Optional[str] = None
    ) -> Optional[_BackendPinDevice]:
        failure_messages: List[str] = []
        combined_reason = fallback_reason or ""

        while True:
            if not self._ensure_backend():
                if self.logger and (combined_reason or failure_messages):
                    details = "; ".join(filter(None, [combined_reason, *failure_messages]))
                    self.logger.error(
                        "GPIO fallback backend unavailable after previous failures on pin %s: %s",
                        config.pin,
                        details,
                    )
                return None

            assert self._backend is not None
            backend = self._backend

            try:
                device = _BackendPinDevice(backend, config.pin, config.active_high)
            except Exception as exc:
                if self.logger:
                    self.logger.error(
                        "Failed to setup pin %s using %s: %s",
                        config.pin,
                        self._current_backend_label(backend),
                        exc,
                    )
                self._record_environment_issue(str(exc))
                self._backend_failures.add(type(backend))
                self._backend = None
                failure_messages.append(
                    f"{self._current_backend_label(backend)} error: {exc}"
                )
                if combined_reason:
                    combined_reason = f"{combined_reason}; {exc}"
                else:
                    combined_reason = str(exc)
                continue

            device.off()
            self._initialized = True
            self._gpiozero_available = False

            if self.logger and (fallback_reason or failure_messages):
                details = "; ".join(filter(None, [fallback_reason, *failure_messages]))
                self.logger.warning(
                    "Falling back to %s for pin %s: %s",
                    self._current_backend_label(backend),
                    config.pin,
                    details,
                )

            return device

    def _get_or_create_device(self, config: GPIOPinConfig) -> Optional[Any]:
        device = self._devices.get(config.pin)
        if device is not None:
            return device

        if self._gpiozero_available and OutputDevice is not None:
            try:
                device = OutputDevice(
                    config.pin,
                    active_high=config.active_high,
                    initial_value=False,
                )
                device.off()
                self._devices[config.pin] = device
                return device
            except Exception as exc:
                if self.logger:
                    self.logger.error(
                        "Failed to initialize gpiozero OutputDevice for pin %s: %s",
                        config.pin,
                        exc,
                    )
                self._record_environment_issue(str(exc))
                self._gpiozero_available = False
                device = self._setup_backend_device(config, fallback_reason=str(exc))
                if device is not None:
                    self._devices[config.pin] = device
                return device

        device = self._setup_backend_device(config)
        if device is not None:
            self._devices[config.pin] = device
        return device

    def _verify_device_state(self, pin: int, device: Any, should_be_active: bool) -> Dict[str, Any]:
        """Validate the observed GPIO output state after a transition."""

        result = {
            "verified": None,
            "expected": "active" if should_be_active else "inactive",
            "observed": "unknown",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "detail": None,
        }

        try:
            value = bool(getattr(device, "value"))
            result["observed"] = "active" if value else "inactive"
            result["verified"] = value == should_be_active
            if not result["verified"]:
                result["detail"] = (
                    f"GPIO state mismatch: expected {result['expected']}, observed {result['observed']}"
                )
        except Exception as exc:
            result["verified"] = None
            result["detail"] = f"Unable to read GPIO state for verification: {exc}"

        self._last_verification[pin] = result
        return result

    def add_pin(self, config: GPIOPinConfig) -> None:
        """Add a GPIO pin to the controller.

        Args:
            config: Pin configuration

        Raises:
            RuntimeError: If GPIO is not available
            ValueError: If pin is already configured
        """
        with self._lock:
            if config.pin in self._pins:
                raise ValueError(f"Pin {config.pin} is already configured")

            self._pins[config.pin] = config

            device = self._get_or_create_device(config)
        if device is None:
            # Record the configuration even when GPIO hardware isn't available so the
            # application can still display configured pins in the UI.
            self._states[config.pin] = GPIOState.ERROR
            if self.logger:
                self.logger.warning(
                    f"Configured pin {config.pin} but GPIO hardware is not available"
                )
            return

        self._states[config.pin] = GPIOState.INACTIVE
        if self.logger:
            active_label = "high" if config.active_high else "low"
            if isinstance(self._backend, _NullGPIOBackend):
                self.logger.info(
                    "Configured GPIO pin %s (%s) using simulated GPIO backend: "
                    "active_%s, hold=%ss, watchdog=%ss",
                    config.pin,
                    config.name,
                    active_label,
                    config.hold_seconds,
                    config.watchdog_seconds,
                )
            else:
                self.logger.info(
                    f"Configured GPIO pin {config.pin} ({config.name}) using {self._current_backend_label()}: "
                    f"active_{active_label}, "
                    f"hold={config.hold_seconds}s, watchdog={config.watchdog_seconds}s"
                )

    def remove_pin(self, pin: int) -> None:
        """Remove a GPIO pin from the controller.

        Args:
            pin: Pin number to remove
        """
        with self._lock:
            if pin in self._pins:
                # Ensure pin is deactivated first
                if self._states.get(pin) == GPIOState.ACTIVE:
                    self.deactivate(pin, force=True)

                # Cleanup the pin
                device = self._devices.pop(pin, None)
                if device is not None:
                    try:
                        device.close()
                    except Exception as exc:
                        if self.logger:
                            self.logger.warning(f"Error cleaning up pin {pin}: {exc}")

                del self._pins[pin]
                del self._states[pin]

                if self.logger:
                    self.logger.info(f"Removed GPIO pin {pin}")

    def _check_interlock_conflict(self, pin: int):
        """Return ``(group, conflicting_pin)`` if activating *pin* would violate
        a relay interlock group, else ``None``.

        ``self.interlock_groups`` is wired in post-construction (same pattern
        as ``self.behavior_manager``) -- absent entirely when no groups are
        configured, so this is a no-op by default.
        """
        groups = getattr(self, "interlock_groups", None) or []
        for group in groups:
            if pin not in group.pins:
                continue
            for sibling in group.pins:
                if sibling != pin and self._states.get(sibling) == GPIOState.ACTIVE:
                    return group, sibling
        return None

    def activate(
        self,
        pin: int,
        activation_type: GPIOActivationType = GPIOActivationType.AUTOMATIC,
        operator: Optional[str] = None,
        alert_id: Optional[str] = None,
        reason: Optional[str] = None,
        flash: Optional[bool] = None,
    ) -> bool:
        """Activate a GPIO pin.

        Args:
            pin: Pin number to activate
            activation_type: Type of activation (manual, automatic, test, override)
            operator: Username if manual/override activation
            alert_id: Alert identifier if automatic activation
            reason: Human-readable reason for activation
            flash: Tri-state flash override.  ``None`` uses the pin's configured
                ``flash_enabled`` flag (legacy / manual behaviour).  ``True``
                forces the flash pattern on even when ``flash_enabled`` is unset
                (used by the FLASH lifecycle behavior, which is the single
                authority for flashing during an alert).  ``False`` suppresses
                flashing so a held relay (PTT, audio mute, duration) stays solid
                even if ``flash_enabled`` happens to be set in its config.

        Returns:
            True if activation succeeded, False otherwise
        """
        with self._lock:
            if pin not in self._pins:
                if self.logger:
                    self.logger.error(f"Cannot activate pin {pin}: not configured")
                return False

            config = self._pins[pin]

            if not config.enabled:
                if self.logger:
                    self.logger.warning(f"Cannot activate pin {pin}: disabled in configuration")
                return False

            if self._states[pin] == GPIOState.ACTIVE:
                if self.logger:
                    self.logger.warning(f"Pin {pin} is already active")
                return False

            interlock_refusal = self._check_interlock_conflict(pin)
            if interlock_refusal is not None:
                group, conflicting_pin = interlock_refusal
                if group.force_deactivate_conflict:
                    if self.logger:
                        self.logger.warning(
                            f"Interlock group '{group.name}': force-deactivating pin "
                            f"{conflicting_pin} to activate pin {pin}"
                        )
                    self.deactivate(conflicting_pin, force=True)
                else:
                    conflicting_name = self._pins[conflicting_pin].name if conflicting_pin in self._pins else str(conflicting_pin)
                    error_msg = (
                        f"Blocked by interlock group '{group.name}': pin {conflicting_pin} "
                        f"({conflicting_name}) is already active"
                    )
                    if self.logger:
                        self.logger.warning(error_msg)
                    event = GPIOActivationEvent(
                        pin=pin,
                        activation_type=activation_type,
                        activated_at=datetime.now(timezone.utc),
                        operator=operator,
                        alert_id=alert_id,
                        reason=reason,
                        success=False,
                        error_message=error_msg,
                    )
                    self._save_activation_event(event)
                    return False

            try:
                # Apply debounce delay
                if config.debounce_ms > 0:
                    time.sleep(config.debounce_ms / 1000.0)

                device = self._get_or_create_device(config)
                if device is None:
                    error_msg = f"GPIO hardware not available for pin {pin}"
                    if self.logger:
                        self.logger.warning(error_msg)
                    
                    # Log failed activation due to hardware unavailability
                    event = GPIOActivationEvent(
                        pin=pin,
                        activation_type=activation_type,
                        activated_at=datetime.now(timezone.utc),
                        operator=operator,
                        alert_id=alert_id,
                        reason=reason,
                        success=False,
                        error_message=error_msg,
                    )
                    self._save_activation_event(event)
                    return False

                # Activate the pin
                device.on()

                verification = self._verify_device_state(pin, device, should_be_active=True)
                
                # Log successful GPIO firing
                if self.logger:
                    self.logger.info(
                        f"✓ GPIO pin {pin} fired successfully: "
                        f"device={device.__class__.__name__}, "
                        f"active_high={config.active_high}, "
                        f"type={activation_type.value}, "
                        f"verified={verification.get('verified')}"
                    )
                    if verification.get("verified") is False:
                        self.logger.warning(verification.get("detail"))

                activation_time = time.monotonic()
                self._activation_times[pin] = activation_time
                self._states[pin] = GPIOState.ACTIVE

                # Create activation event for audit trail
                event = GPIOActivationEvent(
                    pin=pin,
                    activation_type=activation_type,
                    activated_at=datetime.now(timezone.utc),
                    operator=operator,
                    alert_id=alert_id,
                    reason=reason,
                    success=True,
                )
                self._current_events[pin] = event

                # Start watchdog timer.  This must come before the audit write
                # below: the relay is already physically ON, and the watchdog is
                # the backstop that eventually drops it if no release arrives.
                # ``_save_activation_event`` commits synchronously while holding
                # the controller-wide lock, so a slow or hung database would
                # otherwise delay this pin's safety timer *and* block every
                # other pin's activate/deactivate — including watchdog-driven
                # forced releases.  Starting a thread does not block.
                self._start_watchdog(pin, config.watchdog_seconds)

                # Start flash pattern.  ``flash`` overrides the pin's configured
                # ``flash_enabled`` flag so the FLASH lifecycle behavior can be
                # the single flash authority during an alert (flash=True) while
                # held relays stay solid (flash=False).
                should_flash = config.flash_enabled if flash is None else flash
                if should_flash:
                    self._start_flash(pin, force=True)

                # Persist immediately rather than waiting for the release, so an
                # activation that is still on air — or one that never gets
                # released because the process died mid-broadcast — still shows
                # up in the audit trail.  The release updates this same row with
                # the duration (the Logs view renders "Active" until then).
                self._save_activation_event(event)

                if self.logger:
                    self.logger.info(
                        f"Activated GPIO pin {pin} ({config.name}): "
                        f"type={activation_type.value}, reason={reason}"
                    )

                return True

            except Exception as exc:
                self._states[pin] = GPIOState.ERROR

                # Log failed activation
                event = GPIOActivationEvent(
                    pin=pin,
                    activation_type=activation_type,
                    activated_at=datetime.now(timezone.utc),
                    operator=operator,
                    alert_id=alert_id,
                    reason=reason,
                    success=False,
                    error_message=str(exc),
                )
                self._save_activation_event(event)

                self._record_environment_issue(str(exc))
                if self.logger:
                    self.logger.error(f"Failed to activate pin {pin}: {exc}")

                return False

    def deactivate(self, pin: int, force: bool = False) -> bool:
        """Deactivate a GPIO pin.

        Args:
            pin: Pin number to deactivate
            force: If True, ignore hold time and deactivate immediately

        Returns:
            True if deactivation succeeded, False otherwise
        """
        with self._lock:
            if pin not in self._pins:
                if self.logger:
                    self.logger.error(f"Cannot deactivate pin {pin}: not configured")
                return False

            config = self._pins[pin]

            if self._states[pin] != GPIOState.ACTIVE:
                if self.logger:
                    self.logger.debug(f"Pin {pin} is not active")
                return True  # Already inactive

            try:
                # Respect hold time unless forced
                if not force and pin in self._activation_times:
                    elapsed = time.monotonic() - self._activation_times[pin]
                    remaining = max(0.0, config.hold_seconds - elapsed)
                    if remaining > 0:
                        if self.logger:
                            self.logger.debug(f"Waiting {remaining:.2f}s for hold time on pin {pin}")
                        time.sleep(remaining)

                device = self._get_or_create_device(config)
                if device is None:
                    error_msg = f"GPIO hardware not available for pin {pin}"
                    if self.logger:
                        self.logger.warning(error_msg)
                    return False

                device.off()

                verification = self._verify_device_state(pin, device, should_be_active=False)
                
                # Log successful GPIO deactivation
                if self.logger:
                    elapsed = time.monotonic() - self._activation_times.get(pin, 0)
                    self.logger.info(
                        f"✓ GPIO pin {pin} deactivated successfully: "
                        f"active_time={elapsed:.2f}s, "
                        f"forced={force}, "
                        f"verified={verification.get('verified')}"
                    )
                    if verification.get("verified") is False:
                        self.logger.warning(verification.get("detail"))

                self._states[pin] = GPIOState.INACTIVE

                # Stop flash pattern if running
                self._stop_flash(pin)

                # Complete activation event
                if pin in self._current_events:
                    event = self._current_events[pin]
                    event.deactivated_at = datetime.now(timezone.utc)
                    event.duration_seconds = (event.deactivated_at - event.activated_at).total_seconds()
                    self._save_activation_event(event)
                    del self._current_events[pin]

                # Stop watchdog
                self._stop_watchdog(pin)

                if pin in self._activation_times:
                    del self._activation_times[pin]

                if self.logger:
                    self.logger.info(f"Deactivated GPIO pin {pin} ({config.name})")

                return True

            except Exception as exc:
                self._states[pin] = GPIOState.ERROR
                self._record_environment_issue(str(exc))
                if self.logger:
                    self.logger.error(f"Failed to deactivate pin {pin}: {exc}")
                return False

    def get_state(self, pin: int) -> Optional[GPIOState]:
        """Get current state of a GPIO pin.

        Args:
            pin: Pin number

        Returns:
            Current state or None if pin not configured
        """
        with self._lock:
            return self._states.get(pin)

    def get_all_states(self) -> Dict[int, Dict]:
        """Get states of all configured pins.

        Returns:
            Dictionary mapping pin numbers to state info
        """
        with self._lock:
            result = {}
            for pin, config in self._pins.items():
                state = self._states[pin]
                result[pin] = {
                    'pin': pin,
                    'name': config.name,
                    'state': state.value,
                    'enabled': config.enabled,
                    'active_high': config.active_high,
                    'is_active': state == GPIOState.ACTIVE,
                    'flash_enabled': config.flash_enabled,
                    'flash_interval_ms': config.flash_interval_ms,
                    'flash_partner_pin': config.flash_partner_pin,
                }

                verification = self._last_verification.get(pin)
                if verification is not None:
                    result[pin]['verification'] = verification

                # Include timing info if active
                if state == GPIOState.ACTIVE and pin in self._activation_times:
                    elapsed = time.monotonic() - self._activation_times[pin]
                    result[pin]['active_seconds'] = elapsed
                    result[pin]['watchdog_seconds'] = config.watchdog_seconds

                # Include current event info if active
                if pin in self._current_events:
                    event = self._current_events[pin]
                    result[pin]['activation_type'] = event.activation_type.value
                    result[pin]['reason'] = event.reason
                    result[pin]['alert_id'] = event.alert_id
                    result[pin]['operator'] = event.operator

            return result

    def get_environment_issues(self) -> List[str]:
        """Return detected environment issues preventing GPIO access."""

        with self._lock:
            return sorted(self._environment_issues)

    def activate_all(
        self,
        activation_type: GPIOActivationType = GPIOActivationType.AUTOMATIC,
        operator: Optional[str] = None,
        alert_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[int, bool]:
        """Activate all configured pins.

        Args:
            activation_type: Reason for the activation (manual/automatic/test/override)
            operator: Operator username if applicable
            alert_id: Alert identifier when triggered by alert processing
            reason: Human-readable explanation for the activation

        Returns:
            Mapping of pin number to activation success state.
        """

        results: Dict[int, bool] = {}
        with self._lock:
            pins = list(self._pins.keys())

        for pin in pins:
            results[pin] = self.activate(
                pin=pin,
                activation_type=activation_type,
                operator=operator,
                alert_id=alert_id,
                reason=reason,
            )

        return results

    def deactivate_all(self, force: bool = False) -> Dict[int, bool]:
        """Deactivate all configured pins.

        Args:
            force: If ``True`` the hold time is ignored for each pin.

        Returns:
            Mapping of pin number to deactivation success state.
        """

        results: Dict[int, bool] = {}
        with self._lock:
            pins = list(self._pins.keys())

        for pin in pins:
            results[pin] = self.deactivate(pin=pin, force=force)

        return results

    def _start_watchdog(self, pin: int, timeout_seconds: float) -> None:
        """Start watchdog timer for a pin.

        Args:
            pin: Pin number
            timeout_seconds: Watchdog timeout in seconds
        """
        def watchdog():
            time.sleep(timeout_seconds)
            with self._lock:
                if self._states.get(pin) == GPIOState.ACTIVE:
                    if self.logger:
                        self.logger.error(
                            f"Watchdog timeout on pin {pin} after {timeout_seconds}s - forcing deactivation"
                        )
                    # Deactivate first, then mark as watchdog timeout
                    self.deactivate(pin, force=True)
                    # Mark as watchdog timeout after successful deactivation
                    if self._states.get(pin) == GPIOState.INACTIVE:
                        self._states[pin] = GPIOState.WATCHDOG_TIMEOUT

        thread = threading.Thread(target=watchdog, daemon=True, name=f"gpio-watchdog-{pin}")
        self._watchdog_threads[pin] = thread
        thread.start()

    def _stop_watchdog(self, pin: int) -> None:
        """Stop watchdog timer for a pin.

        Args:
            pin: Pin number
        """
        if pin in self._watchdog_threads:
            # Thread will exit naturally when it checks the state
            del self._watchdog_threads[pin]

    def _start_flash(self, pin: int, force: bool = False) -> None:
        """Start flash pattern for a pin (two-phase alternating with partner).

        Args:
            pin: Pin number to flash
            force: When ``True`` start flashing even if ``flash_enabled`` is not
                set on the pin config.  Used by the FLASH lifecycle behavior,
                which assigns flashing per-alert rather than per-pin.
        """
        config = self._pins.get(pin)
        if not config:
            return
        if not config.flash_enabled and not force:
            return

        # Avoid starting a second flash thread for a pin already flashing.
        if pin in self._flash_threads:
            return

        # Create stop event for this flash thread
        stop_event = threading.Event()
        self._flash_stop_events[pin] = stop_event

        def flash_pattern():
            """Flash pattern thread - alternates pin on/off with partner."""
            try:
                interval = config.flash_interval_ms / 1000.0  # Convert to seconds
                partner_pin = config.flash_partner_pin
                
                # Track if we have a partner and it's configured
                has_partner = (
                    partner_pin is not None 
                    and partner_pin in self._pins 
                    and partner_pin != pin
                )
                
                phase = 0  # 0 or 1 to alternate
                
                while not stop_event.is_set():
                    try:
                        with self._lock:
                            # Get devices
                            device = self._devices.get(pin)
                            partner_device = self._devices.get(partner_pin) if has_partner else None
                            
                            if device is None:
                                if self.logger:
                                    self.logger.warning(f"Flash pattern stopped: device for pin {pin} not available")
                                break
                            
                            # Alternate pattern: when this pin is on, partner is off
                            if phase == 0:
                                device.on()
                                if partner_device:
                                    partner_device.off()
                            else:
                                device.off()
                                if partner_device:
                                    partner_device.on()
                        
                        # Toggle phase
                        phase = 1 - phase
                        
                        # Sleep for interval (check stop event periodically)
                        if stop_event.wait(interval):
                            break
                            
                    except Exception as exc:
                        if self.logger:
                            self.logger.error(f"Error in flash pattern for pin {pin}: {exc}")
                        break
                
                # Cleanup: ensure pins rest in a defined state when flash stops.
                with self._lock:
                    device = self._devices.get(pin)
                    if device and pin in self._states:
                        # Solid ON if the pin is still active, otherwise OFF so a
                        # flash that ends mid-"off-phase" doesn't latch the relay.
                        if self._states[pin] == GPIOState.ACTIVE:
                            device.on()
                        else:
                            device.off()
                    # The partner pin is driven directly by this thread and is
                    # not tracked in the state machine, so always rest it OFF —
                    # otherwise it can be left energised after flashing stops.
                    partner_device = self._devices.get(partner_pin) if has_partner else None
                    if partner_device is not None:
                        partner_device.off()

            except Exception as exc:
                if self.logger:
                    self.logger.error(f"Flash pattern thread crashed for pin {pin}: {exc}")

        thread = threading.Thread(target=flash_pattern, daemon=True, name=f"gpio-flash-{pin}")
        self._flash_threads[pin] = thread
        thread.start()

        if self.logger:
            partner_info = f" with partner GPIO{config.flash_partner_pin}" if config.flash_partner_pin else ""
            self.logger.info(
                f"Started flash pattern on GPIO pin {pin} "
                f"(interval={config.flash_interval_ms}ms{partner_info})"
            )

    def _stop_flash(self, pin: int) -> None:
        """Stop flash pattern for a pin.

        Args:
            pin: Pin number
        """
        if pin in self._flash_stop_events:
            self._flash_stop_events[pin].set()
            del self._flash_stop_events[pin]
        
        if pin in self._flash_threads:
            thread = self._flash_threads[pin]
            # Give thread time to clean up
            thread.join(timeout=0.5)
            del self._flash_threads[pin]
            
            if self.logger:
                self.logger.debug(f"Stopped flash pattern on GPIO pin {pin}")

    @contextlib.contextmanager
    def _db_context(self):
        """Run a database operation inside a Flask application context.

        Relay keying lives in the ``eas-station-gpio`` subprocess and is driven
        entirely from background threads: the alert-indicator poll loop and its
        Redis pub/sub listener, the per-pin watchdog timers, and the behavior
        manager's hold / pulse / flash threads.  None of those run inside an
        application context.  Flask-SQLAlchemy 3.x scopes ``db.session`` to the
        active application context, so every ``session.add()`` from one of those
        threads raises ``RuntimeError: Working outside of application context``
        and the activation is silently dropped from the audit trail — which is
        why the Logs -> GPIO view stopped receiving entries once keying moved
        into the subprocess.

        Pushing a context here (only when the caller has not already done so)
        gives those threads a real session.  Without ``db_app`` — e.g. a plain
        SQLAlchemy session in tests — this is a no-op.
        """
        if self.db_app is None:
            yield
            return

        try:
            from flask import has_app_context
        except ImportError:  # pragma: no cover - Flask always present in-app
            yield
            return

        if has_app_context():
            yield
            return

        with self.db_app.app_context():
            yield

    def _save_activation_event(self, event: GPIOActivationEvent) -> None:
        """Write (or update) the audit-trail row for an activation event.

        Called twice for a normal activation: once when the pin is energised —
        so an in-flight or never-released activation is visible immediately
        rather than only appearing when the relay finally drops — and again on
        release to fill in ``deactivated_at`` / ``duration_seconds`` on that same
        row.  ``event.record_id`` carries the row identity between the two calls.

        Args:
            event: Activation event to persist
        """
        if self.db_session is None:
            return

        try:
            from app_core.models import GPIOActivationLog

            with self._db_context():
                log_entry = None
                if event.record_id is not None:
                    log_entry = self.db_session.get(GPIOActivationLog, event.record_id)

                if log_entry is None:
                    log_entry = GPIOActivationLog(pin=event.pin)
                    self.db_session.add(log_entry)

                log_entry.activation_type = event.activation_type.value
                log_entry.activated_at = event.activated_at
                log_entry.deactivated_at = event.deactivated_at
                log_entry.duration_seconds = event.duration_seconds
                log_entry.operator = event.operator
                log_entry.alert_id = event.alert_id
                log_entry.reason = event.reason
                log_entry.success = event.success
                log_entry.error_message = event.error_message

                self.db_session.commit()
                event.record_id = log_entry.id

            if self.logger:
                self.logger.debug(f"Saved GPIO activation log for pin {event.pin}")

        except Exception as exc:
            if self.logger:
                self.logger.error(f"Failed to save GPIO activation log: {exc}")
            try:
                with self._db_context():
                    self.db_session.rollback()
            except Exception as rollback_exc:  # pragma: no cover - best effort
                # Never let a failed rollback mask the original error above, but
                # don't discard it silently either — a session left in an
                # unknown state is exactly the kind of invisible audit failure
                # this method exists to avoid.
                if self.logger:
                    self.logger.debug(
                        f"GPIO activation log rollback failed: {rollback_exc}"
                    )

    def cleanup(self) -> None:
        """Cleanup all GPIO pins and stop watchdogs."""
        # Stop any alert-lifecycle behaviors first so a manager-driven flash or
        # hold thread can't re-energise a pin after we deactivate it below.
        manager = getattr(self, "behavior_manager", None)
        if manager is not None:
            try:
                manager.shutdown()
            except Exception as exc:  # pragma: no cover - defensive
                if self.logger:
                    self.logger.warning(f"Error shutting down GPIO behavior manager: {exc}")

        with self._lock:
            # Deactivate all active pins
            for pin in list(self._pins.keys()):
                if self._states.get(pin) == GPIOState.ACTIVE:
                    self.deactivate(pin, force=True)

            # Cleanup GPIO devices
            for pin, device in list(self._devices.items()):
                try:
                    device.close()
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"Error during GPIO cleanup for pin {pin}: {exc}")
                finally:
                    self._devices.pop(pin, None)

            if self._initialized and self.logger:
                self.logger.info("GPIO cleanup complete")

    def __del__(self):
        """Destructor to ensure cleanup."""
        try:
            self.cleanup()
        except Exception:
            pass  # Suppress exceptions in destructor
