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

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Iterable, List, Optional, Set

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


class GPIOBehavior(Enum):
    """Lifecycle triggers that can drive GPIO relays."""

    DURATION_OF_ALERT = "duration_of_alert"
    PLAYOUT = "playout"
    FLASH = "flash"
    FIVE_SECONDS = "five_seconds"
    INCOMING_ALERT = "incoming_alert"
    FORWARDING_ALERT = "forwarding_alert"

    @classmethod
    def from_value(cls, value: str) -> Optional["GPIOBehavior"]:
        """Convert a raw string into a :class:`GPIOBehavior` member."""

        if not value:
            return None

        try:
            return cls(value)
        except ValueError:
            normalized = str(value).strip().lower()
            for member in cls:
                if member.value == normalized:
                    return member
        return None


GPIO_BEHAVIOR_LABELS = {
    GPIOBehavior.DURATION_OF_ALERT: "Duration of Alert",
    GPIOBehavior.PLAYOUT: "Audio Playout",
    GPIOBehavior.FLASH: "Flash Beacon",
    GPIOBehavior.FIVE_SECONDS: "5 Second Pulse",
    GPIOBehavior.INCOMING_ALERT: "Incoming Alert",
    GPIOBehavior.FORWARDING_ALERT: "Forwarding Alert",
}


GPIO_BEHAVIOR_PULSE_DEFAULTS = {
    GPIOBehavior.INCOMING_ALERT: 3.0,
    GPIOBehavior.FORWARDING_ALERT: 5.0,
    GPIOBehavior.FIVE_SECONDS: 5.0,
    GPIOBehavior.FLASH: 0.35,
}


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

            self._pins[config.pin] = config

            if not self._initialized or RPiGPIO is None:
                # Record the configuration even when GPIO hardware isn't available so the
                # application can still display configured pins in the UI.
                self._states[config.pin] = GPIOState.ERROR
                if self.logger:
                    self.logger.warning(
                        f"Configured pin {config.pin} but GPIO hardware is not available"
                    )
                return

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


def load_gpio_pin_configs_from_env(logger=None) -> List[GPIOPinConfig]:
    """Load GPIO pin configurations from environment variables.

    The loader understands the following environment variables:

    - ``EAS_GPIO_PIN`` / ``EAS_GPIO_ACTIVE_STATE`` / ``EAS_GPIO_HOLD_SECONDS`` /
      ``EAS_GPIO_WATCHDOG_SECONDS`` for the primary transmitter relay.
    - ``GPIO_ADDITIONAL_PINS``: comma or newline separated entries in the form
      ``pin:name:state:hold:watchdog`` where state is ``HIGH``/``LOW``.
    - ``GPIO_PIN_<N>`` variables for pin-specific overrides using
      ``STATE:HOLD:WATCHDOG:NAME`` or a simplified value such as ``HIGH``.

    Args:
        logger: Optional logger used for diagnostic warnings.

    Returns:
        List of :class:`GPIOPinConfig` entries ready to be registered with a
        :class:`GPIOController` instance.
    """

    def _log(level: str, message: str) -> None:
        if logger is None:
            return
        log_method = getattr(logger, level, None)
        if callable(log_method):
            log_method(message)

    def _parse_active_state(value: Optional[str], default: bool = True) -> bool:
        if value is None:
            return default
        return str(value).strip().upper() != "LOW"

    def _parse_float(value: Optional[str], default: float) -> float:
        if value is None or value == "":
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _add_config(
        configs: List[GPIOPinConfig],
        seen: set,
        pin: int,
        name: str,
        active_high: bool,
        hold_seconds: float,
        watchdog_seconds: float,
    ) -> None:
        if pin in seen:
            _log("warning", f"Duplicate GPIO pin {pin} ignored")
            return
        if pin < 2 or pin > 27:
            _log("error", f"GPIO pin {pin} is outside the supported BCM range (2-27)")
            return

        configs.append(
            GPIOPinConfig(
                pin=pin,
                name=name or f"GPIO Pin {pin}",
                active_high=active_high,
                hold_seconds=max(0.1, hold_seconds or 0.0),
                watchdog_seconds=max(1.0, watchdog_seconds or 0.0),
                enabled=True,
            )
        )
        seen.add(pin)

    configs: List[GPIOPinConfig] = []
    seen_pins: set = set()

    # Primary EAS GPIO pin
    eas_gpio_pin = os.getenv("EAS_GPIO_PIN", "").strip()
    if eas_gpio_pin:
        try:
            pin_number = int(eas_gpio_pin)
        except ValueError:
            _log("error", f"Invalid EAS_GPIO_PIN value '{eas_gpio_pin}' - expected integer")
        else:
            active_high = _parse_active_state(os.getenv("EAS_GPIO_ACTIVE_STATE", "HIGH"))
            hold_seconds = _parse_float(os.getenv("EAS_GPIO_HOLD_SECONDS"), 5.0)
            watchdog_seconds = _parse_float(os.getenv("EAS_GPIO_WATCHDOG_SECONDS"), 300.0)
            _add_config(
                configs,
                seen_pins,
                pin_number,
                "EAS Transmitter PTT",
                active_high,
                hold_seconds,
                watchdog_seconds,
            )

    # Additional pins declared in GPIO_ADDITIONAL_PINS
    additional = os.getenv("GPIO_ADDITIONAL_PINS", "").strip()
    if additional:
        entries = [entry.strip() for entry in re.split(r"[,\n]+", additional) if entry.strip()]
        for entry in entries:
            parts = [part.strip() for part in entry.split(":")]
            if not parts:
                continue
            try:
                pin_number = int(parts[0])
            except ValueError:
                _log("error", f"Invalid GPIO_ADDITIONAL_PINS entry '{entry}' - pin must be numeric")
                continue

            name = parts[1] if len(parts) > 1 and parts[1] else f"GPIO Pin {pin_number}"
            active_high = _parse_active_state(parts[2] if len(parts) > 2 else None)
            hold_seconds = _parse_float(parts[3] if len(parts) > 3 else None, 5.0)
            watchdog_seconds = _parse_float(parts[4] if len(parts) > 4 else None, 300.0)

            _add_config(
                configs,
                seen_pins,
                pin_number,
                name,
                active_high,
                hold_seconds,
                watchdog_seconds,
            )

    # Individual GPIO_PIN_<number> overrides
    pin_pattern = re.compile(r"^GPIO_PIN_(\d+)$")
    for key, value in os.environ.items():
        match = pin_pattern.match(key)
        if not match:
            continue

        pin_number = int(match.group(1))
        raw_value = (value or "").strip()

        active_high = True
        hold_seconds = 5.0
        watchdog_seconds = 300.0
        name = f"GPIO Pin {pin_number}"

        if ":" in raw_value:
            parts = [part.strip() for part in raw_value.split(":")]
            active_high = _parse_active_state(parts[0] if parts else None)
            if len(parts) > 1:
                hold_seconds = _parse_float(parts[1], 5.0)
            if len(parts) > 2:
                watchdog_seconds = _parse_float(parts[2], 300.0)
            if len(parts) > 3 and parts[3]:
                name = parts[3]
        elif raw_value:
            upper_value = raw_value.upper()
            if upper_value in {"HIGH", "LOW"}:
                active_high = upper_value != "LOW"
            else:
                try:
                    int(raw_value)
                except ValueError:
                    _log("warning", f"Ignoring GPIO_PIN_{pin_number} value '{raw_value}' - expected HIGH/LOW or numeric pin")
                # Name defaults; hold/watchdog remain defaults

        _add_config(
            configs,
            seen_pins,
            pin_number,
            name,
            active_high,
            hold_seconds,
            watchdog_seconds,
        )

    return configs


def _stringify_behavior_matrix(matrix: Dict[int, Iterable[GPIOBehavior]]) -> Dict[str, List[str]]:
    """Convert behavior matrix keys/values to JSON-serializable primitives."""

    result: Dict[str, List[str]] = {}
    for pin, behaviors in matrix.items():
        if not behaviors:
            continue
        result[str(pin)] = sorted({behavior.value for behavior in behaviors})
    return result


def serialize_gpio_behavior_matrix(matrix: Dict[int, Iterable[GPIOBehavior]]) -> str:
    """Serialize a behavior matrix to a compact JSON string."""

    if not matrix:
        return ""

    serializable = _stringify_behavior_matrix(matrix)
    if not serializable:
        return ""
    return json.dumps(serializable, separators=(",", ":"), sort_keys=True)


def load_gpio_behavior_matrix_from_env(logger=None) -> Dict[int, Set[GPIOBehavior]]:
    """Load GPIO behavior assignments from ``GPIO_PIN_BEHAVIOR_MATRIX``."""

    raw = os.getenv("GPIO_PIN_BEHAVIOR_MATRIX", "").strip()
    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        if logger is not None:
            logger.warning(
                "Failed to parse GPIO_PIN_BEHAVIOR_MATRIX: %s", exc
            )
        return {}

    matrix: Dict[int, Set[GPIOBehavior]] = {}
    for key, values in data.items():
        try:
            pin = int(key)
        except (TypeError, ValueError):
            if logger is not None:
                logger.warning("Ignoring invalid GPIO behavior pin key %r", key)
            continue

        behaviors: Set[GPIOBehavior] = set()
        if isinstance(values, (list, tuple, set)):
            iterable: Iterable = values
        else:
            iterable = [values]

        for value in iterable:
            behavior = GPIOBehavior.from_value(value)
            if behavior is None:
                if logger is not None:
                    logger.warning(
                        "Ignoring unknown GPIO behavior %r for pin %s",
                        value,
                        pin,
                    )
                continue
            behaviors.add(behavior)

        if behaviors:
            matrix[pin] = behaviors

    return matrix


class GPIOBehaviorManager:
    """Coordinate GPIO actions tied to alert lifecycle events."""

    FLASH_PULSE_COUNT = 6

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
        self._flash_threads: Dict[int, threading.Event] = {}
        self._warned_unconfigured: Set[int] = set()
        self._lock = threading.RLock()

        self._rebuild_behavior_index()

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
    ) -> bool:
        """Begin alert playout behaviors.

        Returns ``True`` when the manager is actively holding pins and should
        receive a matching :meth:`end_alert` call.
        """

        if not self.controller:
            return False

        reason = reason or "Automatic alert playout"
        hold_started = False

        for behavior in (GPIOBehavior.DURATION_OF_ALERT, GPIOBehavior.PLAYOUT):
            for pin in self._pins_for_behavior(behavior):
                if self._add_hold(pin, behavior, alert_id, event_code, reason):
                    hold_started = True

        flash_started = self._start_flash(alert_id, event_code, reason)

        pulse_triggered = self._pulse_behavior(
            GPIOBehavior.FIVE_SECONDS,
            alert_id,
            event_code,
            pulse_seconds=GPIO_BEHAVIOR_PULSE_DEFAULTS[GPIOBehavior.FIVE_SECONDS],
        )

        return hold_started or flash_started or pulse_triggered

    def end_alert(
        self,
        *,
        alert_id: Optional[str] = None,
        event_code: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Release any pins held for alert playout behaviors."""

        if not self.controller:
            return

        reason = reason or "Alert playout completed"

        for behavior in (GPIOBehavior.DURATION_OF_ALERT, GPIOBehavior.PLAYOUT):
            for pin in self._pins_for_behavior(behavior):
                self._release_hold(pin, behavior, alert_id, event_code, reason)

        self._stop_flash(alert_id, event_code)

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

        success = self.controller.activate(
            pin=pin,
            activation_type=GPIOActivationType.AUTOMATIC,
            alert_id=alert_id,
            reason=activation_reason,
        )
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
            self.controller.deactivate(pin)
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
        pins = self._pins_for_behavior(GPIOBehavior.FLASH)
        if not pins or not self.controller:
            return False

        started = False
        for pin in pins:
            with self._lock:
                if pin in self._flash_threads:
                    continue
                stop_event = threading.Event()
                self._flash_threads[pin] = stop_event

            thread = threading.Thread(
                target=self._flash_worker,
                name=f"gpio-flash-{pin}",
                kwargs={
                    "pin": pin,
                    "stop_event": stop_event,
                    "alert_id": alert_id,
                    "reason": reason,
                },
                daemon=True,
            )
            thread.start()
            started = True

        return started

    def _flash_worker(
        self,
        *,
        pin: int,
        stop_event: threading.Event,
        alert_id: Optional[str],
        reason: str,
    ) -> None:
        pulses = self.FLASH_PULSE_COUNT
        interval = GPIO_BEHAVIOR_PULSE_DEFAULTS.get(GPIOBehavior.FLASH, 0.35)
        for _ in range(pulses):
            if stop_event.is_set():
                break
            success = self.controller.activate(
                pin=pin,
                activation_type=GPIOActivationType.AUTOMATIC,
                alert_id=alert_id,
                reason=f"Flash beacon ({reason})",
            )
            if success:
                time.sleep(interval)
                try:
                    self.controller.deactivate(pin, force=True)
                except Exception as exc:  # pragma: no cover - hardware specific
                    if self.logger:
                        self.logger.warning(
                            "Failed to step flash cycle for pin %s: %s",
                            pin,
                            exc,
                        )
            time.sleep(interval)

        stop_event.set()
        with self._lock:
            self._flash_threads.pop(pin, None)

    def _stop_flash(
        self,
        alert_id: Optional[str],
        event_code: Optional[str],
    ) -> None:
        with self._lock:
            items = list(self._flash_threads.items())
            self._flash_threads.clear()

        for pin, event in items:
            event.set()
            try:
                self.controller.deactivate(pin, force=True)
            except Exception:  # pragma: no cover - hardware specific
                pass


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
