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

"""Unified GPIO control for transmitter keying and peripheral hardware.

This module provides reliable, auditable control over GPIO pins with features including:
- Active-high/low configuration
- Debounce logic
- Watchdog timers for stuck relay detection
- Activation history and audit trails
- Multiple relay/pin management
- Thread-safe operations
"""

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Set

from app_utils.pi_pinout import ARGON_OLED_RESERVED_BCM, ARGON_OLED_RESERVED_PHYSICAL

# Flash pattern configuration constants
MIN_FLASH_INTERVAL_MS = 50  # Minimum flash interval (20Hz)
MAX_FLASH_INTERVAL_MS = 5000  # Maximum flash interval (0.2Hz)

# Import hardware settings helper
try:
    from app_core.hardware_settings import get_gpio_settings
    _GPIO_SETTINGS_AVAILABLE = True
except ImportError:
    _GPIO_SETTINGS_AVAILABLE = False

    def get_gpio_settings():
        """Fallback when settings module not available."""
        return {}

try:  # pragma: no cover - GPIO hardware is optional and platform specific
    from gpiozero import Device, OutputDevice
except Exception:  # pragma: no cover - gracefully handle non-RPi environments
    Device = None  # type: ignore[assignment]
    OutputDevice = None  # type: ignore[assignment]

try:  # pragma: no cover - allow fallback to a mock pin factory when hardware is absent
    from gpiozero.pins.mock import MockFactory
except Exception:  # pragma: no cover - mock factory may be unavailable in minimal installs
    MockFactory = None  # type: ignore[assignment]

try:  # pragma: no cover - Pi 5 prefers lgpio backend
    import lgpio as LGPIO  # type: ignore
except Exception:  # pragma: no cover - not all environments ship with lgpio
    LGPIO = None

# NOTE: The legacy RPi.GPIO library is deprecated upstream and no longer
# supported by this project. We rely on gpiozero's abstractions (with optional
# lgpio support) and a mock factory for non-hardware environments.


class GPIOBackend(Protocol):
    """Protocol describing the backend interface needed by the controller."""

    BCM: object
    OUT: object
    HIGH: int
    LOW: int

    def setmode(self, mode: object) -> None:
        ...

    def setup(self, pin: int, mode: object, *, initial: int) -> None:
        ...

    def output(self, pin: int, value: int) -> None:
        ...

    def read(self, pin: int) -> int:
        ...

    def cleanup(self, pin: Optional[int] = None) -> None:
        ...


class _LGPIOBackend:
    """Adapter for the modern lgpio library used on Raspberry Pi 5."""

    def __init__(self) -> None:
        if LGPIO is None:  # pragma: no cover - guard in case import fails later
            raise RuntimeError("lgpio module unavailable")
        self.BCM = "BCM"  # Pin numbering hint for logging purposes
        self.OUT = "out"
        self.HIGH = 1
        self.LOW = 0
        self._claimed_pins: set[int] = set()
        self._chip: Optional[int] = None
        self._free = getattr(LGPIO, "gpio_free", getattr(LGPIO, "gpio_release", None))

    def _ensure_chip(self) -> None:
        if self._chip is None:
            # Open the primary gpiochip (0). On Pi boards BCM numbering maps here.
            self._chip = LGPIO.gpiochip_open(0)

    def setmode(self, mode: object) -> None:  # pragma: no cover - lgpio ignores modes
        self._ensure_chip()

    def setup(self, pin: int, mode: object, *, initial: int) -> None:
        self._ensure_chip()
        # Claim the line for output and drive it to the requested resting level.
        LGPIO.gpio_claim_output(self._chip, pin, initial)
        self._claimed_pins.add(pin)

    def output(self, pin: int, value: int) -> None:
        if self._chip is None:
            raise RuntimeError("lgpio chip handle not initialized")
        LGPIO.gpio_write(self._chip, pin, value)

    def read(self, pin: int) -> int:
        if self._chip is None:
            raise RuntimeError("lgpio chip handle not initialized")
        return int(LGPIO.gpio_read(self._chip, pin))

    def cleanup(self, pin: Optional[int] = None) -> None:
        if self._chip is None:
            return

        if pin is None:
            pins = list(self._claimed_pins)
        else:
            pins = [pin] if pin in self._claimed_pins else []

        for line in pins:
            try:
                # Drive the line low before releasing for predictable state.
                LGPIO.gpio_write(self._chip, line, self.LOW)
            except Exception:
                # Ignore failures when releasing (e.g., already freed)
                pass
            if self._free is not None:
                try:
                    self._free(self._chip, line)
                except Exception:
                    pass
            self._claimed_pins.discard(line)

        if pin is None or not self._claimed_pins:
            LGPIO.gpiochip_close(self._chip)
            self._chip = None


class _SysfsGPIOBackend:
    """Fallback backend that drives GPIO via the Linux sysfs interface."""

    def __init__(self) -> None:
        self.BCM = "BCM"
        self.OUT = "out"
        self.HIGH = 1
        self.LOW = 0
        self._base_path = Path("/sys/class/gpio")
        if not self._base_path.exists():
            raise RuntimeError("/sys/class/gpio is not available on this system")
        self._export_path = self._base_path / "export"
        self._unexport_path = self._base_path / "unexport"
        self._active_pins: Set[int] = set()

    def setmode(self, mode: object) -> None:  # pragma: no cover - sysfs ignores modes
        return

    def _write(self, path: Path, value: str) -> None:
        try:
            with path.open("w") as handle:
                handle.write(value)
        except FileNotFoundError as exc:  # pragma: no cover - platform specific
            raise RuntimeError(f"GPIO path {path} not found") from exc
        except PermissionError as exc:  # pragma: no cover - requires elevated perms
            raise RuntimeError(f"Permission denied writing to {path}") from exc
        except OSError as exc:  # pragma: no cover - unexpected IO failure
            raise RuntimeError(f"Failed to write to {path}: {exc}") from exc

    def setup(self, pin: int, mode: object, *, initial: int) -> None:
        if mode != self.OUT:
            raise ValueError("sysfs backend supports output mode only")

        gpio_path = self._base_path / f"gpio{pin}"
        if not gpio_path.exists():
            self._write(self._export_path, f"{pin}")
            deadline = time.monotonic() + 1.0
            while not gpio_path.exists():  # pragma: no cover - timing sensitive
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Timed out waiting for {gpio_path} to appear")
                time.sleep(0.01)

        self._write(gpio_path / "direction", "out")
        self._write(gpio_path / "value", "1" if initial == self.HIGH else "0")
        self._active_pins.add(pin)

    def output(self, pin: int, value: int) -> None:
        if pin not in self._active_pins:
            self.setup(pin, self.OUT, initial=self.LOW)
        gpio_path = self._base_path / f"gpio{pin}" / "value"
        self._write(gpio_path, "1" if value == self.HIGH else "0")

    def read(self, pin: int) -> int:
        gpio_path = self._base_path / f"gpio{pin}" / "value"
        try:
            return int(gpio_path.read_text(encoding="utf-8").strip() or "0")
        except Exception as exc:  # pragma: no cover - platform specific file access
            raise RuntimeError(f"Failed to read {gpio_path}: {exc}") from exc

    def cleanup(self, pin: Optional[int] = None) -> None:
        if pin is None:
            pins = list(self._active_pins)
        else:
            pins = [pin] if pin in self._active_pins else []

        for number in pins:
            value_path = self._base_path / f"gpio{number}" / "value"
            try:
                self._write(value_path, "0")
            except Exception:
                pass
            try:
                self._write(self._unexport_path, f"{number}")
            except Exception:
                pass
            self._active_pins.discard(number)


class _NullGPIOBackend:
    """Safe no-op backend for environments without GPIO access."""

    def __init__(self) -> None:
        self.BCM = "BCM"
        self.OUT = "out"
        self.HIGH = 1
        self.LOW = 0
        self._states: Dict[int, int] = {}

    def setmode(self, mode: object) -> None:  # pragma: no cover - no hardware state
        return

    def setup(self, pin: int, mode: object, *, initial: int) -> None:
        if mode != self.OUT:
            raise ValueError("Null backend supports output mode only")
        self._states[pin] = initial

    def output(self, pin: int, value: int) -> None:
        self._states[pin] = value

    def read(self, pin: int) -> int:
        return self._states.get(pin, self.LOW)

    def cleanup(self, pin: Optional[int] = None) -> None:
        if pin is None:
            self._states.clear()
        else:
            self._states.pop(pin, None)


_PIN_FACTORY_READY = False
_PIN_FACTORY_ATTEMPTED = False


def _explain_environment_issue(detail: str) -> Optional[str]:
    """Return a human-friendly explanation for a GPIO backend failure."""

    message = detail.strip()
    if not message:
        return None

    lowered = message.lower()

    if "/dev/gpiomem" in lowered or "/dev/mem" in lowered:
        return (
            "Process cannot open /dev/gpiomem. Run the service as root or add the "
            "service user to the gpio group: sudo usermod -a -G gpio eas-station"
        )

    if "permission denied" in lowered and "/sys/class/gpio" in lowered:
        return (
            "Kernel sysfs GPIO interface is present but permission denied. Ensure "
            "the service user has write access to /sys/class/gpio or run as root."
        )

    if "read-only file system" in lowered and "/sys/class/gpio" in lowered:
        return (
            "The GPIO sysfs filesystem is mounted read-only. Remount it writable or "
            "start the container with --privileged and pass the host /sys/class/gpio "
            "through."
        )

    if "unable to load any default pin factory" in lowered:
        return (
            "gpiozero could not find a working pin factory. Install lgpio or pigpio, "
            "or expose Raspberry Pi GPIO devices to the container."
        )

    return None


def _ensure_pin_factory(
    logger=None, issue_recorder: Optional[Callable[[str], None]] = None
) -> bool:
    """Ensure gpiozero has a usable pin factory, falling back to MockFactory."""

    global _PIN_FACTORY_READY, _PIN_FACTORY_ATTEMPTED

    if _PIN_FACTORY_READY:
        return True

    if OutputDevice is None or Device is None:
        return False

    if not _PIN_FACTORY_ATTEMPTED:
        _PIN_FACTORY_ATTEMPTED = True
        try:
            # Accessing ``Device.pin_factory`` forces gpiozero to initialize its
            # preferred backend. When that fails (e.g., no GPIO hardware
            # available) the property access raises an exception which we catch
            # to install a mock fallback instead.
            factory = Device.pin_factory  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - depends on host environment
            factory = None
            fallback_exc = exc
        else:
            fallback_exc = None

        if factory is None:
            if MockFactory is not None:
                try:
                    Device.pin_factory = MockFactory()  # type: ignore[attr-defined]
                    _PIN_FACTORY_READY = True
                    if logger:
                        logger.warning(
                            "gpiozero hardware backends unavailable; using MockFactory fallback"
                        )
                except Exception as mock_exc:  # pragma: no cover - unexpected failure
                    if issue_recorder is not None:
                        issue_recorder(str(mock_exc))
                    if logger:
                        logger.error(
                            "Failed to initialize gpiozero MockFactory fallback: %s",
                            mock_exc,
                        )
            else:
                if issue_recorder is not None:
                    issue_recorder(str(fallback_exc))
                if logger:
                    reason = fallback_exc or RuntimeError(
                        "gpiozero pin factory returned None"
                    )
                    logger.error(
                        "gpiozero pin factory initialization failed and MockFactory "
                        "is unavailable: %s",
                        reason,
                    )
        else:
            _PIN_FACTORY_READY = True

    return _PIN_FACTORY_READY


def ensure_gpiozero_pin_factory(
    logger=None, issue_recorder: Optional[Callable[[str], None]] = None
) -> bool:
    """Public helper to initialise gpiozero's pin factory."""

    return _ensure_pin_factory(logger=logger, issue_recorder=issue_recorder)


def _create_gpio_backend(exclude: Optional[Set[type]] = None) -> Optional[GPIOBackend]:
    """Return the best available GPIO backend for this platform."""

    exclude_set = exclude if exclude is not None else set()

    candidates: List[tuple[type, Callable[[], GPIOBackend]]] = []
    if LGPIO is not None:
        candidates.append((_LGPIOBackend, _LGPIOBackend))
    candidates.append((_SysfsGPIOBackend, _SysfsGPIOBackend))
    candidates.append((_NullGPIOBackend, _NullGPIOBackend))

    for backend_type, factory in candidates:
        if backend_type in exclude_set:
            continue
        try:
            backend = factory()
        except Exception:
            exclude_set.add(backend_type)
            continue
        return backend

    return None


class _BackendPinDevice:
    """Adapter that exposes gpiozero-like methods for GPIOBackend instances."""

    def __init__(self, backend: GPIOBackend, pin: int, active_high: bool) -> None:
        self._backend = backend
        self._pin = pin
        self._active_value = backend.HIGH if active_high else backend.LOW
        self._inactive_value = backend.LOW if active_high else backend.HIGH
        self._backend.setup(self._pin, self._backend.OUT, initial=self._inactive_value)

    def on(self) -> None:
        self._backend.output(self._pin, self._active_value)

    def off(self) -> None:
        self._backend.output(self._pin, self._inactive_value)

    def close(self) -> None:
        self._backend.cleanup(self._pin)

    @property
    def value(self) -> bool:
        return self._backend.read(self._pin) == self._active_value


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
    # Flash pattern configuration for stack lights
    flash_enabled: bool = False  # Enable flash/alternating pattern
    flash_interval_ms: int = 500  # Flash interval in milliseconds (default 500ms = 2Hz)
    flash_partner_pin: Optional[int] = None  # Partner pin for two-phase alternating pattern


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

                # Start watchdog timer
                self._start_watchdog(pin, config.watchdog_seconds)

                # Start flash pattern if enabled
                if config.flash_enabled:
                    self._start_flash(pin)

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

    def _start_flash(self, pin: int) -> None:
        """Start flash pattern for a pin (two-phase alternating with partner).

        Args:
            pin: Pin number to flash
        """
        config = self._pins.get(pin)
        if not config or not config.flash_enabled:
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
                
                # Cleanup: ensure pin is in proper state when flash stops
                with self._lock:
                    device = self._devices.get(pin)
                    if device and pin in self._states:
                        # Set to solid on if still active
                        if self._states[pin] == GPIOState.ACTIVE:
                            device.on()
                        
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


def load_gpio_pin_configs_from_db(logger=None, oled_enabled: bool = False) -> List[GPIOPinConfig]:
    """Load GPIO pin configurations from database.

    Hardware settings (GPIO, OLED, LED Sign, VFD) are configured via the web UI
    at /admin/hardware and stored in the database. Environment variables are
    NOT supported for hardware configuration.

    The pin map is stored as a JSON object mapping pin numbers to their configuration.

    Example pin_map format:
    {
      "17": {"name": "EAS Transmitter PTT", "active_high": true, "hold_seconds": 5.0, "watchdog_seconds": 300.0},
      "27": {"name": "Backup Relay", "active_high": true}
    }

    Args:
        logger: Optional logger used for diagnostic warnings.
        oled_enabled: Whether the OLED display is enabled. If True, pins 2, 3, 4, and 14
                      will be blocked as they are reserved for the OLED module.

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

    def _parse_bool(value: Any, default: bool = True) -> bool:
        """Parse a boolean value from JSON (true/false) or string (HIGH/LOW)."""
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        str_value = str(value).strip().upper()
        if str_value in {"TRUE", "1", "YES", "HIGH"}:
            return True
        if str_value in {"FALSE", "0", "NO", "LOW"}:
            return False
        return default

    def _parse_float(value: Any, default: float) -> float:
        """Parse a float value from JSON or string."""
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
        flash_enabled: bool = False,
        flash_interval_ms: int = 500,
        flash_partner_pin: Optional[int] = None,
    ) -> None:
        if pin in seen:
            _log("warning", f"Duplicate GPIO pin {pin} ignored")
            return

        # Only block OLED reserved pins if OLED is actually enabled
        if oled_enabled and pin in ARGON_OLED_RESERVED_BCM:
            reserved_physical = ", ".join(str(p) for p in sorted(ARGON_OLED_RESERVED_PHYSICAL))
            _log(
                "error",
                (
                    f"GPIO pin {pin} is reserved for the Argon OLED module (physical pins {reserved_physical}) "
                    "and cannot be configured while OLED is enabled"
                ),
            )
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
                flash_enabled=flash_enabled,
                flash_interval_ms=max(MIN_FLASH_INTERVAL_MS, min(MAX_FLASH_INTERVAL_MS, flash_interval_ms)),
                flash_partner_pin=flash_partner_pin,
            )
        )
        seen.add(pin)

    configs: List[GPIOPinConfig] = []
    seen_pins: set = set()

    # Load from database (hardware settings are only configured via /admin/hardware)
    gpio_pin_map = {}
    if _GPIO_SETTINGS_AVAILABLE:
        try:
            gpio_settings = get_gpio_settings()
            gpio_pin_map = gpio_settings.get('pin_map', {})
            if gpio_pin_map and logger:
                logger.debug("Loaded GPIO pin map from database")
        except Exception as exc:
            if logger:
                logger.warning("Failed to load GPIO settings from database: %s", exc)

    # No pins configured in database
    if not gpio_pin_map:
        _log("info", "No GPIO pins configured (configure in Admin > Hardware Settings)")
        return configs

    if not isinstance(gpio_pin_map, dict):
        _log("error", "GPIO pin_map must be a JSON object mapping pin numbers to configurations")
        return configs

    # Process each pin in the map
    for pin_key, pin_config in gpio_pin_map.items():
        try:
            pin_number = int(pin_key)
        except (TypeError, ValueError):
            _log("error", f"Invalid GPIO pin number '{pin_key}' in gpio_pin_map - must be an integer")
            continue

        if not isinstance(pin_config, dict):
            _log("error", f"Invalid configuration for GPIO pin {pin_number} - must be an object")
            continue

        # Extract configuration with defaults
        name = pin_config.get("name", f"GPIO Pin {pin_number}")
        active_high = _parse_bool(pin_config.get("active_high"), default=True)
        hold_seconds = _parse_float(pin_config.get("hold_seconds"), 5.0)
        watchdog_seconds = _parse_float(pin_config.get("watchdog_seconds"), 300.0)
        
        # Flash pattern configuration
        flash_enabled = _parse_bool(pin_config.get("flash_enabled"), default=False)
        flash_interval_ms = int(_parse_float(pin_config.get("flash_interval_ms"), 500.0))
        flash_partner_pin_value = pin_config.get("flash_partner_pin")
        flash_partner_pin = None
        if flash_partner_pin_value is not None and flash_partner_pin_value != "":
            try:
                flash_partner_pin = int(flash_partner_pin_value)
            except (TypeError, ValueError):
                _log("warning", f"Invalid flash_partner_pin '{flash_partner_pin_value}' for GPIO pin {pin_number}")

        _add_config(
            configs,
            seen_pins,
            pin_number,
            name,
            active_high,
            hold_seconds,
            watchdog_seconds,
            flash_enabled,
            flash_interval_ms,
            flash_partner_pin,
        )

    return configs


def _stringify_behavior_matrix(matrix: Dict[int, Iterable[GPIOBehavior]]) -> Dict[str, List[str]]:
    """Convert behavior matrix keys/values to JSON-serializable primitives."""

    result: Dict[str, List[str]] = {}
    for pin, behaviors in matrix.items():
        if not behaviors:
            continue
        if pin in ARGON_OLED_RESERVED_BCM:
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


def load_gpio_behavior_matrix_from_db(logger=None, oled_enabled: bool = False) -> Dict[int, Set[GPIOBehavior]]:
    """Load GPIO behavior assignments from database.

    Hardware settings (GPIO, OLED, LED Sign, VFD) are configured via the web UI
    at /admin/hardware and stored in the database. Environment variables are
    NOT supported for hardware configuration.

    Args:
        logger: Optional logger used for diagnostic warnings.
        oled_enabled: Whether the OLED display is enabled. If True, pins 2, 3, 4, and 14
                      will be blocked as they are reserved for the OLED module.

    Returns:
        Dictionary mapping pin numbers to sets of GPIO behaviors.
    """

    # Load from database (hardware settings are only configured via /admin/hardware)
    data = None
    if _GPIO_SETTINGS_AVAILABLE:
        try:
            gpio_settings = get_gpio_settings()
            data = gpio_settings.get('behavior_matrix', {})
            if data and logger:
                logger.debug("Loaded GPIO behavior matrix from database")
        except Exception as exc:
            if logger is not None:
                logger.warning("Failed to load GPIO behavior matrix from database: %s", exc)

    # No behavior matrix configured
    if not data:
        return {}

    matrix: Dict[int, Set[GPIOBehavior]] = {}
    for key, values in data.items():
        try:
            pin = int(key)
        except (TypeError, ValueError):
            if logger is not None:
                logger.warning("Ignoring invalid GPIO behavior pin key %r", key)
            continue

        # Only block OLED reserved pins if OLED is actually enabled
        if oled_enabled and pin in ARGON_OLED_RESERVED_BCM:
            if logger is not None:
                logger.warning(
                    "Ignoring GPIO behavior assignment for OLED-reserved pin %s (OLED is enabled)", pin
                )
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
        staged: Set[int] = set()

        for pin in sorted(pins):
            config = self.pin_configs.get(pin)
            partner_pin = config.flash_partner_pin if config else None
            if partner_pin not in pins:
                partner_pin = None
            # If partner pair already staged in earlier loop iteration, skip to avoid
            # duplicate opposing flash threads fighting each other.
            if partner_pin is not None and partner_pin in staged:
                continue

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
                    "partner_pin": partner_pin,
                    "interval": (
                        max(MIN_FLASH_INTERVAL_MS, min(MAX_FLASH_INTERVAL_MS, config.flash_interval_ms)) / 1000.0
                        if config
                        else GPIO_BEHAVIOR_PULSE_DEFAULTS.get(GPIOBehavior.FLASH, 0.35)
                    ),
                },
                daemon=True,
            )
            thread.start()
            started = True
            staged.add(pin)
            if partner_pin is not None:
                staged.add(partner_pin)

        return started

    def _flash_worker(
        self,
        *,
        pin: int,
        stop_event: threading.Event,
        alert_id: Optional[str],
        reason: str,
        partner_pin: Optional[int],
        interval: float,
    ) -> None:
        phase = 0
        while not stop_event.is_set():
            if partner_pin is None:
                active_pin = pin if phase == 0 else None
                inactive_pin = pin if phase == 1 else None
            else:
                active_pin = pin if phase == 0 else partner_pin
                inactive_pin = partner_pin if phase == 0 else pin

            if stop_event.is_set():
                break

            if active_pin is not None:
                self.controller.activate(
                    pin=active_pin,
                    activation_type=GPIOActivationType.AUTOMATIC,
                    alert_id=alert_id,
                    reason=f"Flash beacon active phase ({reason})",
                )
            if inactive_pin is not None:
                try:
                    self.controller.deactivate(inactive_pin, force=True)
                except Exception as exc:  # pragma: no cover - hardware specific
                    if self.logger:
                        self.logger.warning(
                            "Failed to step flash cycle for pin %s: %s",
                            inactive_pin,
                            exc,
                        )

            phase = 1 - phase
            if stop_event.wait(interval):
                break

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
            targets = {pin}
            config = self.pin_configs.get(pin)
            if config and config.flash_partner_pin is not None:
                targets.add(config.flash_partner_pin)
            for target_pin in targets:
                try:
                    self.controller.deactivate(target_pin, force=True)
                except Exception:  # pragma: no cover - hardware specific
                    pass
