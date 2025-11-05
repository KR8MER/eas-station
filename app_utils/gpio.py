"""Unified GPIO control for transmitter keying and peripheral hardware.

This module provides reliable, auditable control over GPIO pins with features including:
- Active-high/low configuration
- Debounce logic
- Watchdog timers for stuck relay detection
- Activation history and audit trails
- Multiple relay/pin management
- Thread-safe operations
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

try:  # pragma: no cover - GPIO hardware is optional and platform specific
    import RPi.GPIO as RPiGPIO  # type: ignore
except Exception:  # pragma: no cover - gracefully handle non-RPi environments
    RPiGPIO = None


class GPIOState(Enum):
    """GPIO pin state enumeration."""
    INACTIVE = "inactive"
    ACTIVE = "active"
    ERROR = "error"
    WATCHDOG_TIMEOUT = "watchdog_timeout"


class GPIOActivationType(Enum):
    """Type of GPIO activation."""
    MANUAL = "manual"  # Manual operator activation
    AUTOMATIC = "automatic"  # Triggered by alert processing
    TEST = "test"  # Test activation
    OVERRIDE = "override"  # Override/emergency activation


@dataclass
class GPIOActivationEvent:
    """Record of a GPIO activation event for audit trail."""
    pin: int
    activation_type: GPIOActivationType
    activated_at: datetime
    deactivated_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    operator: Optional[str] = None  # Username if manual/override
    alert_id: Optional[str] = None  # Alert identifier if automatic
    reason: Optional[str] = None  # Human-readable reason
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage."""
        return {
            'pin': self.pin,
            'activation_type': self.activation_type.value,
            'activated_at': self.activated_at.isoformat(),
            'deactivated_at': self.deactivated_at.isoformat() if self.deactivated_at else None,
            'duration_seconds': self.duration_seconds,
            'operator': self.operator,
            'alert_id': self.alert_id,
            'reason': self.reason,
            'success': self.success,
            'error_message': self.error_message,
        }


@dataclass
class GPIOPinConfig:
    """Configuration for a single GPIO pin."""
    pin: int
    name: str  # Descriptive name (e.g., "Transmitter PTT", "Emergency Relay")
    active_high: bool = True
    debounce_ms: int = 50  # Debounce time in milliseconds
    hold_seconds: float = 5.0  # Minimum hold time before release
    watchdog_seconds: float = 300.0  # Maximum activation time (5 minutes default)
    enabled: bool = True


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

    def __init__(self, db_session=None, logger=None):
        """Initialize GPIO controller.

        Args:
            db_session: SQLAlchemy session for audit logging (optional)
            logger: Logger instance for diagnostics (optional)
        """
        self.db_session = db_session
        self.logger = logger
        self._pins: Dict[int, GPIOPinConfig] = {}
        self._states: Dict[int, GPIOState] = {}
        self._activation_times: Dict[int, float] = {}
        self._current_events: Dict[int, GPIOActivationEvent] = {}
        self._lock = threading.RLock()
        self._watchdog_threads: Dict[int, threading.Thread] = {}
        self._initialized = False

        if RPiGPIO is not None:
            try:
                RPiGPIO.setmode(RPiGPIO.BCM)
                self._initialized = True
                if self.logger:
                    self.logger.info("GPIO controller initialized in BCM mode")
            except Exception as exc:
                if self.logger:
                    self.logger.error(f"Failed to initialize GPIO: {exc}")
                self._initialized = False
        else:
            if self.logger:
                self.logger.warning("RPi.GPIO not available - GPIO control disabled")

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

            if not self._initialized:
                if self.logger:
                    self.logger.warning(f"Cannot configure pin {config.pin}: GPIO not available")
                return

            self._pins[config.pin] = config
            self._states[config.pin] = GPIOState.INACTIVE

            # Setup the pin
            active_level = RPiGPIO.HIGH if config.active_high else RPiGPIO.LOW
            resting_level = RPiGPIO.LOW if config.active_high else RPiGPIO.HIGH

            try:
                RPiGPIO.setup(config.pin, RPiGPIO.OUT, initial=resting_level)
                if self.logger:
                    self.logger.info(
                        f"Configured GPIO pin {config.pin} ({config.name}): "
                        f"active_{'high' if config.active_high else 'low'}, "
                        f"hold={config.hold_seconds}s, watchdog={config.watchdog_seconds}s"
                    )
            except Exception as exc:
                self._states[config.pin] = GPIOState.ERROR
                if self.logger:
                    self.logger.error(f"Failed to setup pin {config.pin}: {exc}")
                raise

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
                if self._initialized and RPiGPIO is not None:
                    try:
                        RPiGPIO.cleanup(pin)
                    except Exception as exc:
                        if self.logger:
                            self.logger.warning(f"Error cleaning up pin {pin}: {exc}")

                del self._pins[pin]
                del self._states[pin]

                if self.logger:
                    self.logger.info(f"Removed GPIO pin {pin}")

    def activate(
        self,
        pin: int,
        activation_type: GPIOActivationType = GPIOActivationType.AUTOMATIC,
        operator: Optional[str] = None,
        alert_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Activate a GPIO pin.

        Args:
            pin: Pin number to activate
            activation_type: Type of activation (manual, automatic, test, override)
            operator: Username if manual/override activation
            alert_id: Alert identifier if automatic activation
            reason: Human-readable reason for activation

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

            if not self._initialized or RPiGPIO is None:
                if self.logger:
                    self.logger.warning(f"Cannot activate pin {pin}: GPIO not available")
                return False

            try:
                # Apply debounce delay
                if config.debounce_ms > 0:
                    time.sleep(config.debounce_ms / 1000.0)

                # Activate the pin
                active_level = RPiGPIO.HIGH if config.active_high else RPiGPIO.LOW
                RPiGPIO.output(pin, active_level)

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

                # Start watchdog timer
                self._start_watchdog(pin, config.watchdog_seconds)

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

            if not self._initialized or RPiGPIO is None:
                if self.logger:
                    self.logger.warning(f"Cannot deactivate pin {pin}: GPIO not available")
                return False

            try:
                # Respect hold time unless forced
                if not force and pin in self._activation_times:
                    elapsed = time.monotonic() - self._activation_times[pin]
                    remaining = max(0.0, config.hold_seconds - elapsed)
                    if remaining > 0:
                        if self.logger:
                            self.logger.debug(f"Waiting {remaining:.2f}s for hold time on pin {pin}")
                        time.sleep(remaining)

                # Deactivate the pin
                resting_level = RPiGPIO.LOW if config.active_high else RPiGPIO.HIGH
                RPiGPIO.output(pin, resting_level)

                self._states[pin] = GPIOState.INACTIVE

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
                }

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
                    self._states[pin] = GPIOState.WATCHDOG_TIMEOUT
                    self.deactivate(pin, force=True)

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

    def _save_activation_event(self, event: GPIOActivationEvent) -> None:
        """Save activation event to database for audit trail.

        Args:
            event: Activation event to save
        """
        if self.db_session is None:
            return

        try:
            from app_core.models import GPIOActivationLog

            log_entry = GPIOActivationLog(
                pin=event.pin,
                activation_type=event.activation_type.value,
                activated_at=event.activated_at,
                deactivated_at=event.deactivated_at,
                duration_seconds=event.duration_seconds,
                operator=event.operator,
                alert_id=event.alert_id,
                reason=event.reason,
                success=event.success,
                error_message=event.error_message,
            )

            self.db_session.add(log_entry)
            self.db_session.commit()

            if self.logger:
                self.logger.debug(f"Saved GPIO activation log for pin {event.pin}")

        except Exception as exc:
            if self.logger:
                self.logger.error(f"Failed to save GPIO activation log: {exc}")
            if self.db_session:
                self.db_session.rollback()

    def cleanup(self) -> None:
        """Cleanup all GPIO pins and stop watchdogs."""
        with self._lock:
            # Deactivate all active pins
            for pin in list(self._pins.keys()):
                if self._states.get(pin) == GPIOState.ACTIVE:
                    self.deactivate(pin, force=True)

            # Cleanup GPIO
            if self._initialized and RPiGPIO is not None:
                try:
                    RPiGPIO.cleanup()
                    if self.logger:
                        self.logger.info("GPIO cleanup complete")
                except Exception as exc:
                    if self.logger:
                        self.logger.warning(f"Error during GPIO cleanup: {exc}")

    def __del__(self):
        """Destructor to ensure cleanup."""
        try:
            self.cleanup()
        except Exception:
            pass  # Suppress exceptions in destructor


# Backwards compatibility wrapper for existing code
@dataclass
class GPIORelayController:
    """Legacy GPIO relay controller for backwards compatibility.

    This class is deprecated. New code should use GPIOController instead.
    """
    pin: int
    active_high: bool
    hold_seconds: float
    activated_at: Optional[float] = field(default=None, init=False)

    def __post_init__(self) -> None:  # pragma: no cover - hardware specific
        if RPiGPIO is None:
            raise RuntimeError('RPi.GPIO not available')
        self._active_level = RPiGPIO.HIGH if self.active_high else RPiGPIO.LOW
        self._resting_level = RPiGPIO.LOW if self.active_high else RPiGPIO.HIGH
        RPiGPIO.setmode(RPiGPIO.BCM)
        RPiGPIO.setup(self.pin, RPiGPIO.OUT, initial=self._resting_level)

    def activate(self, logger) -> None:  # pragma: no cover - hardware specific
        if RPiGPIO is None:
            return
        RPiGPIO.output(self.pin, self._active_level)
        self.activated_at = time.monotonic()
        if logger:
            logger.debug('Activated GPIO relay on pin %s', self.pin)

    def deactivate(self, logger) -> None:  # pragma: no cover - hardware specific
        if RPiGPIO is None:
            return
        if self.activated_at is not None:
            elapsed = time.monotonic() - self.activated_at
            remaining = max(0.0, self.hold_seconds - elapsed)
            if remaining > 0:
                time.sleep(remaining)
        RPiGPIO.output(self.pin, self._resting_level)
        self.activated_at = None
        if logger:
            logger.debug('Released GPIO relay on pin %s', self.pin)
