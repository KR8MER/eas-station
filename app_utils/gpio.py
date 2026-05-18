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

try:  # pragma: no cover - rpi_ws281x requires DMA hardware and root on Raspberry Pi
    from rpi_ws281x import PixelStrip, Color as NeopixelColor  # type: ignore
    _NEOPIXEL_LIB_AVAILABLE = True
except Exception:  # pragma: no cover - not available on non-Pi environments
    PixelStrip = None  # type: ignore[assignment]
    NeopixelColor = None  # type: ignore[assignment]
    _NEOPIXEL_LIB_AVAILABLE = False

try:  # pragma: no cover - allow fallback to a mock pin factory when hardware is absent
    from gpiozero.pins.mock import MockFactory
except Exception:  # pragma: no cover - mock factory may be unavailable in minimal installs
    MockFactory = None  # type: ignore[assignment]

# NOTE: lgpio is intentionally NOT imported here at module level.
# Importing lgpio starts a native background notification thread immediately,
# which deadlocks gunicorn gevent workers (the thread blocks gevent's
# monkey-patched I/O loop for the full worker timeout).  The web process
# imports this module eagerly via webapp/eas/workflow.py and
# webapp/routes/system_controls.py, so any top-level lgpio import poisons
# every gunicorn worker even though the web process never touches GPIO.
# lgpio is imported lazily inside _LGPIOBackend.__init__ so it is only loaded
# in processes that actually instantiate the backend (hardware_service.py).

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
        # Import lazily: lgpio starts a native background thread on import,
        # which deadlocks gevent workers.  Only import when the backend is
        # actually instantiated (i.e., in hardware_service, not in the web app).
        try:  # pragma: no cover - only present on Raspberry Pi
            import lgpio as _lgpio  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("lgpio module unavailable") from exc
        self._lgpio = _lgpio
        self.BCM = "BCM"  # Pin numbering hint for logging purposes
        self.OUT = "out"
        self.HIGH = 1
        self.LOW = 0
        self._claimed_pins: set[int] = set()
        self._chip: Optional[int] = None
        self._free = getattr(_lgpio, "gpio_free", getattr(_lgpio, "gpio_release", None))

    def _ensure_chip(self) -> None:
        if self._chip is None:
            # Open the primary gpiochip (0). On Pi boards BCM numbering maps here.
            self._chip = self._lgpio.gpiochip_open(0)

    def setmode(self, mode: object) -> None:  # pragma: no cover - lgpio ignores modes
        self._ensure_chip()

    def setup(self, pin: int, mode: object, *, initial: int) -> None:
        self._ensure_chip()
        # Claim the line for output and drive it to the requested resting level.
        self._lgpio.gpio_claim_output(self._chip, pin, initial)
        self._claimed_pins.add(pin)

    def output(self, pin: int, value: int) -> None:
        if self._chip is None:
            raise RuntimeError("lgpio chip handle not initialized")
        self._lgpio.gpio_write(self._chip, pin, value)

    def read(self, pin: int) -> int:
        if self._chip is None:
            raise RuntimeError("lgpio chip handle not initialized")
        return int(self._lgpio.gpio_read(self._chip, pin))

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
                self._lgpio.gpio_write(self._chip, line, self.LOW)
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
            self._lgpio.gpiochip_close(self._chip)
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
    # _LGPIOBackend imports lgpio lazily in __init__; if lgpio is unavailable
    # the constructor raises RuntimeError and the factory try/except skips it.
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
        self._watchdog_stop_events: Dict[int, threading.Event] = {}
        self._flash_threads: Dict[int, threading.Thread] = {}  # Flash pattern threads
        self._flash_stop_events: Dict[int, threading.Event] = {}  # Flash stop signals
        self._devices: Dict[int, Any] = {}
        self._last_verification: Dict[int, Dict[str, Any]] = {}
        self._backend: Optional[GPIOBackend] = None
        self._backend_failures: Set[type] = set()
        self._environment_issues: Set[str] = set()
        self._max_environment_issues: int = 256
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
        if not message:
            return
        if message in self._environment_issues:
            return
        if len(self._environment_issues) >= self._max_environment_issues:
            return
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
        # Cancel any existing watchdog for this pin before starting a new one.
        self._stop_watchdog(pin)
        stop_event = threading.Event()
        self._watchdog_stop_events[pin] = stop_event

        def watchdog():
            if stop_event.wait(timeout_seconds):
                return
            with self._lock:
                # Ignore stale timers replaced by newer activations.
                if self._watchdog_stop_events.get(pin) is not stop_event:
                    return
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
        stop_event = self._watchdog_stop_events.pop(pin, None)
        if stop_event is not None:
            stop_event.set()

        thread = self._watchdog_threads.pop(pin, None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.2)

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

        hold_behaviors = [GPIOBehavior.DURATION_OF_ALERT, GPIOBehavior.PLAYOUT]
        if forwarded:
            hold_behaviors.append(GPIOBehavior.FORWARDING_ALERT)

        for behavior in hold_behaviors:
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
        forwarded: bool = False,
    ) -> None:
        """Release any pins held for alert playout behaviors."""

        if not self.controller:
            return

        reason = reason or "Alert playout completed"

        hold_behaviors = [GPIOBehavior.DURATION_OF_ALERT, GPIOBehavior.PLAYOUT]
        if forwarded:
            hold_behaviors.append(GPIOBehavior.FORWARDING_ALERT)

        for behavior in hold_behaviors:
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


# ---------------------------------------------------------------------------
# NeoPixel / WS2812B addressable LED strip support
# ---------------------------------------------------------------------------

# Neopixel strip type constants (mirrors rpi_ws281x constants)
WS2811_STRIP_GRB = 0x00081000
WS2811_STRIP_RGB = 0x00081000  # same ordering bits, differs in channel setup
_NEO_STRIP_TYPES: Dict[str, int] = {
    "GRB": WS2811_STRIP_GRB,
    "RGB": 0x00080100,
    "BGR": 0x00080001,
    "RGBW": 0x18081000,
    "GRBW": 0x18081000,
}

# Frequency and DMA defaults for rpi_ws281x
_NEO_FREQ_HZ = 800_000  # 800kHz signal frequency
_NEO_DMA = 10           # DMA channel (safe default)
_NEO_INVERT = False     # Invert signal (for NPN transistor-level shifters)
_NEO_CHANNEL = 0        # PWM channel (0 = GPIO 18/12, 1 = GPIO 13/19)


@dataclass
class NeopixelConfig:
    """Configuration for a NeoPixel (WS2812B) LED strip attached to a single GPIO pin."""

    gpio_pin: int = 18          # BCM pin; 18 (hw PWM ch0) recommended for best timing
    num_pixels: int = 1         # Number of LEDs in the strip
    brightness: int = 128       # Global brightness 0-255
    led_order: str = "GRB"      # Byte order of the LEDs (WS2812B default is GRB)
    standby_color: tuple = (0, 10, 0)    # (r, g, b) shown when idle
    alert_color: tuple = (255, 0, 0)     # (r, g, b) shown during active alert
    flash_on_alert: bool = True          # Flash strip during active alert
    flash_interval_ms: int = 500         # Flash period in milliseconds


class _NullNeopixelStrip:
    """No-op strip used when rpi_ws281x hardware is unavailable."""

    def __init__(self, num_pixels: int) -> None:
        self._num_pixels = num_pixels
        self._pixels: List[int] = [0] * num_pixels

    def begin(self) -> None:
        pass

    def setPixelColor(self, n: int, color: int) -> None:
        if 0 <= n < self._num_pixels:
            self._pixels[n] = color

    def show(self) -> None:
        pass

    def setBrightness(self, brightness: int) -> None:
        pass

    def numPixels(self) -> int:
        return self._num_pixels

    @property
    def pixels(self) -> List[int]:
        return list(self._pixels)


def _make_neo_color(r: int, g: int, b: int) -> int:
    """Pack an (r, g, b) tuple into a 24-bit integer as used by rpi_ws281x."""
    if NeopixelColor is not None:
        return int(NeopixelColor(r, g, b))
    return (r << 16) | (g << 8) | b


class NeopixelController:
    """Controller for NeoPixel (WS2812B) addressable LED strips.

    Provides graceful degradation when ``rpi_ws281x`` is not installed or the
    underlying DMA hardware cannot be claimed (e.g. running in Docker or on a
    non-Raspberry-Pi host).

    Example::

        config = NeopixelConfig(gpio_pin=18, num_pixels=8, brightness=128)
        neo = NeopixelController(config, logger=logger)
        if neo.start():
            neo.start_alert()   # red flash during an EAS alert
            ...
            neo.end_alert()     # return to dim green standby
            neo.cleanup()
    """

    def __init__(self, config: NeopixelConfig, logger=None) -> None:
        self.config = config
        self.logger = logger
        self._strip: Optional[Any] = None
        self._available = False
        self._lock = threading.RLock()
        self._flash_thread: Optional[threading.Thread] = None
        self._flash_stop = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle

    def start(self) -> bool:
        """Initialise hardware and set the strip to the standby colour.

        Returns ``True`` when the real hardware was successfully claimed, or
        ``False`` when falling back to the null backend (no hardware / library
        not installed).
        """
        with self._lock:
            if _NEOPIXEL_LIB_AVAILABLE and PixelStrip is not None:
                strip_type = _NEO_STRIP_TYPES.get(
                    self.config.led_order.upper(), WS2811_STRIP_GRB
                )
                try:
                    strip = PixelStrip(
                        self.config.num_pixels,
                        self.config.gpio_pin,
                        _NEO_FREQ_HZ,
                        _NEO_DMA,
                        _NEO_INVERT,
                        self.config.brightness,
                        _NEO_CHANNEL,
                        strip_type,
                    )
                    strip.begin()
                    self._strip = strip
                    self._available = True
                    if self.logger:
                        self.logger.info(
                            "NeoPixel strip initialized: %d pixel(s) on GPIO %d "
                            "(order=%s, brightness=%d)",
                            self.config.num_pixels,
                            self.config.gpio_pin,
                            self.config.led_order,
                            self.config.brightness,
                        )
                except Exception as exc:  # pragma: no cover - DMA access depends on host
                    if self.logger:
                        self.logger.warning(
                            "NeoPixel hardware unavailable on GPIO %d: %s – "
                            "falling back to null strip (no LEDs will light)",
                            self.config.gpio_pin,
                            exc,
                        )
                    self._strip = _NullNeopixelStrip(self.config.num_pixels)
                    self._available = False
            else:
                if self.logger:
                    self.logger.warning(
                        "rpi_ws281x library not installed – NeoPixel strip on GPIO %d "
                        "running in null (no-op) mode.  Install rpi-ws281x to enable real LEDs.",
                        self.config.gpio_pin,
                    )
                self._strip = _NullNeopixelStrip(self.config.num_pixels)
                self._available = False

            self.set_standby()
            return self._available

    def cleanup(self) -> None:
        """Stop flash, turn off all pixels, and release hardware."""
        self.stop_flash()
        with self._lock:
            self.off()
            self._strip = None
            self._available = False

    # ------------------------------------------------------------------
    # Colour control

    def set_color(self, r: int, g: int, b: int) -> None:
        """Set every pixel to the given colour and push the update."""
        with self._lock:
            if self._strip is None:
                return
            color = _make_neo_color(r, g, b)
            for i in range(self.config.num_pixels):
                self._strip.setPixelColor(i, color)
            self._strip.show()

    def set_standby(self) -> None:
        """Show the configured standby colour."""
        r, g, b = self.config.standby_color
        self.set_color(r, g, b)

    def off(self) -> None:
        """Turn all pixels off."""
        self.set_color(0, 0, 0)

    # ------------------------------------------------------------------
    # Alert integration

    def start_alert(
        self,
        r: Optional[int] = None,
        g: Optional[int] = None,
        b: Optional[int] = None,
    ) -> None:
        """React to an active EAS alert.

        Sets the alert colour (or the configured default) and begins the
        flash pattern when ``flash_on_alert`` is enabled.

        Args:
            r: Red component override (0-255).  Uses ``config.alert_color`` when
               ``None``.
            g: Green component override.
            b: Blue component override.
        """
        ar, ag, ab = self.config.alert_color
        red = r if r is not None else ar
        green = g if g is not None else ag
        blue = b if b is not None else ab

        if self.config.flash_on_alert:
            self.start_flash(red, green, blue)
        else:
            self.stop_flash()
            self.set_color(red, green, blue)

        if self.logger:
            self.logger.info(
                "NeoPixel alert active: color=(%d,%d,%d), flash=%s",
                red, green, blue, self.config.flash_on_alert,
            )

    def end_alert(self) -> None:
        """Return the strip to standby after an alert has ended."""
        self.stop_flash()
        self.set_standby()
        if self.logger:
            self.logger.info("NeoPixel alert ended; returning to standby colour")

    # ------------------------------------------------------------------
    # Flash pattern

    def start_flash(self, r: int, g: int, b: int) -> None:
        """Begin an alternating flash between (r, g, b) and off.

        If a flash is already running it is replaced.
        """
        self.stop_flash()

        self._flash_stop.clear()
        self._flash_thread = threading.Thread(
            target=self._flash_worker,
            kwargs={"r": r, "g": g, "b": b},
            daemon=True,
            name=f"neopixel-flash-gpio{self.config.gpio_pin}",
        )
        self._flash_thread.start()

    def stop_flash(self) -> None:
        """Signal the flash thread to stop and wait for it to exit."""
        self._flash_stop.set()
        thread = self._flash_thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._flash_thread = None

    def _flash_worker(self, *, r: int, g: int, b: int) -> None:
        interval = max(MIN_FLASH_INTERVAL_MS, self.config.flash_interval_ms) / 1000.0
        phase = 0
        while not self._flash_stop.is_set():
            if phase == 0:
                self.set_color(r, g, b)
            else:
                self.set_color(0, 0, 0)
            phase = 1 - phase
            if self._flash_stop.wait(interval):
                break
        # Leave strip in standby state when flash ends
        self.set_standby()

    # ------------------------------------------------------------------
    # Status

    @property
    def is_available(self) -> bool:
        """``True`` when the real rpi_ws281x hardware is in use."""
        return self._available

    def get_status(self) -> Dict[str, Any]:
        """Return a status dict suitable for the web UI / Redis metrics."""
        return {
            "available": self._available,
            "gpio_pin": self.config.gpio_pin,
            "num_pixels": self.config.num_pixels,
            "brightness": self.config.brightness,
            "led_order": self.config.led_order,
            "standby_color": self.config.standby_color,
            "alert_color": self.config.alert_color,
            "flash_on_alert": self.config.flash_on_alert,
            "flash_interval_ms": self.config.flash_interval_ms,
            "flashing": self._flash_thread is not None and self._flash_thread.is_alive(),
        }


# ---------------------------------------------------------------------------
# USB Tower Light support (Adafruit #5125 / CH34x-based stack lights)
# ---------------------------------------------------------------------------

# Command byte protocol: high-nibble = action (0x1x=on, 0x2x=off, 0x4x=blink)
#                        low-nibble  = segment (0x?1=red, 0x?2=yellow,
#                                               0x?4=green, 0x?8=buzzer)
_TOWER_CMD_RED_ON     = 0x11
_TOWER_CMD_RED_OFF    = 0x21
_TOWER_CMD_RED_BLINK  = 0x41
_TOWER_CMD_YEL_ON     = 0x12
_TOWER_CMD_YEL_OFF    = 0x22
_TOWER_CMD_YEL_BLINK  = 0x42
_TOWER_CMD_GRN_ON     = 0x14
_TOWER_CMD_GRN_OFF    = 0x24
_TOWER_CMD_GRN_BLINK  = 0x44
_TOWER_CMD_BUZ_ON     = 0x18
_TOWER_CMD_BUZ_OFF    = 0x28
_TOWER_CMD_BUZ_BLINK  = 0x48


@dataclass
class TowerLightConfig:
    """Configuration for an Adafruit USB Tri-Color Tower Light (product #5125).

    The device communicates via a CH34x USB-to-serial adapter at 9600 baud.
    It exposes three independent LED segments (red, yellow, green) plus a
    buzzer, each controllable with single-byte serial commands.
    """

    serial_port: str = "/dev/ttyUSB0"  # Serial port path (e.g. /dev/ttyUSB0)
    baudrate: int = 9600               # Fixed at 9600 for this device
    # Alert response configuration
    alert_buzzer: bool = False         # Sound buzzer on active alert
    incoming_uses_yellow: bool = True  # Yellow blinks when alert first arrives
    blink_on_alert: bool = True        # Use hardware blink mode during active alert


class TowerLightController:
    """Controller for the Adafruit USB Tri-Color Tower Light (product #5125).

    Uses a single-byte serial command protocol to independently control three
    LED colours (red, yellow, green) and a buzzer over a CH34x USB-UART
    adapter.

    The device is entirely self-contained; no GPIO pins are required.  It
    integrates with the same alert lifecycle as :class:`GPIOController` and
    :class:`NeopixelController`.

    Example::

        config = TowerLightConfig(serial_port="/dev/ttyUSB1")
        tower = TowerLightController(config, logger=logger)
        if tower.start():
            tower.start_alert()    # Red blink + optional buzzer
            ...
            tower.end_alert()      # Return to green standby
            tower.cleanup()
    """

    def __init__(self, config: TowerLightConfig, logger=None) -> None:
        self.config = config
        self.logger = logger
        self._serial: Optional[Any] = None
        self._available = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Lifecycle

    def start(self) -> bool:
        """Open the serial port and set the tower to standby (green on).

        Returns ``True`` when the port was opened successfully.
        """
        with self._lock:
            try:
                import serial  # pyserial – already in requirements.txt

                self._serial = serial.Serial(
                    self.config.serial_port,
                    self.config.baudrate,
                    timeout=1,
                )
                self._available = True
                if self.logger:
                    self.logger.info(
                        "USB tower light opened on %s at %d baud",
                        self.config.serial_port,
                        self.config.baudrate,
                    )
            except Exception as exc:  # pragma: no cover - device-dependent
                self._available = False
                if self.logger:
                    self.logger.warning(
                        "USB tower light unavailable on %s: %s",
                        self.config.serial_port,
                        exc,
                    )

            self.set_standby()
            return self._available

    def cleanup(self) -> None:
        """Turn everything off and close the serial port."""
        with self._lock:
            self.all_off()
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
            self._available = False

    # ------------------------------------------------------------------
    # Low-level command dispatch

    def _send(self, command: int) -> bool:
        """Write a single command byte to the serial port.

        Returns ``True`` on success, ``False`` on failure (e.g. port closed).
        """
        if self._serial is None:
            return False
        try:
            self._serial.write(bytes([command]))
            return True
        except Exception as exc:  # pragma: no cover - device-dependent
            if self.logger:
                self.logger.warning("Tower light write failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Segment control

    def red(self, state: str = "on") -> None:
        """Control the red segment.  *state* is ``'on'``, ``'off'``, or ``'blink'``."""
        with self._lock:
            cmd = {
                "on":    _TOWER_CMD_RED_ON,
                "off":   _TOWER_CMD_RED_OFF,
                "blink": _TOWER_CMD_RED_BLINK,
            }.get(state.lower(), _TOWER_CMD_RED_OFF)
            self._send(cmd)

    def yellow(self, state: str = "on") -> None:
        """Control the yellow segment.  *state* is ``'on'``, ``'off'``, or ``'blink'``."""
        with self._lock:
            cmd = {
                "on":    _TOWER_CMD_YEL_ON,
                "off":   _TOWER_CMD_YEL_OFF,
                "blink": _TOWER_CMD_YEL_BLINK,
            }.get(state.lower(), _TOWER_CMD_YEL_OFF)
            self._send(cmd)

    def green(self, state: str = "on") -> None:
        """Control the green segment.  *state* is ``'on'``, ``'off'``, or ``'blink'``."""
        with self._lock:
            cmd = {
                "on":    _TOWER_CMD_GRN_ON,
                "off":   _TOWER_CMD_GRN_OFF,
                "blink": _TOWER_CMD_GRN_BLINK,
            }.get(state.lower(), _TOWER_CMD_GRN_OFF)
            self._send(cmd)

    def buzzer(self, state: str = "on") -> None:
        """Control the buzzer.  *state* is ``'on'``, ``'off'``, or ``'blink'``."""
        with self._lock:
            cmd = {
                "on":    _TOWER_CMD_BUZ_ON,
                "off":   _TOWER_CMD_BUZ_OFF,
                "blink": _TOWER_CMD_BUZ_BLINK,
            }.get(state.lower(), _TOWER_CMD_BUZ_OFF)
            self._send(cmd)

    def all_off(self) -> None:
        """Turn all segments and the buzzer off."""
        with self._lock:
            for cmd in (
                _TOWER_CMD_RED_OFF,
                _TOWER_CMD_YEL_OFF,
                _TOWER_CMD_GRN_OFF,
                _TOWER_CMD_BUZ_OFF,
            ):
                self._send(cmd)

    def set_standby(self) -> None:
        """Show 'system ready' state: green on, red/yellow/buzzer off."""
        with self._lock:
            for cmd in (_TOWER_CMD_RED_OFF, _TOWER_CMD_YEL_OFF, _TOWER_CMD_BUZ_OFF):
                self._send(cmd)
            self._send(_TOWER_CMD_GRN_ON)

    # ------------------------------------------------------------------
    # Alert integration

    def start_incoming_alert(self) -> None:
        """Signal that an alert has been received but playout has not started.

        Shows yellow (blink or solid) to indicate an incoming alert decision.
        Does nothing when :attr:`TowerLightConfig.incoming_uses_yellow` is
        ``False``.
        """
        if not self.config.incoming_uses_yellow:
            return

        with self._lock:
            yellow_state = "blink" if self.config.blink_on_alert else "on"
            for cmd in (_TOWER_CMD_GRN_OFF, _TOWER_CMD_RED_OFF):
                self._send(cmd)
            cmd = (
                _TOWER_CMD_YEL_BLINK if self.config.blink_on_alert
                else _TOWER_CMD_YEL_ON
            )
            self._send(cmd)

        if self.logger:
            self.logger.info("Tower light: incoming alert (yellow %s)", yellow_state)

    def start_alert(self) -> None:
        """Signal an active alert: red on/blink, optional buzzer, others off."""
        with self._lock:
            for cmd in (_TOWER_CMD_GRN_OFF, _TOWER_CMD_YEL_OFF):
                self._send(cmd)
            red_cmd = (
                _TOWER_CMD_RED_BLINK if self.config.blink_on_alert
                else _TOWER_CMD_RED_ON
            )
            self._send(red_cmd)
            if self.config.alert_buzzer:
                self._send(_TOWER_CMD_BUZ_ON)

        if self.logger:
            red_state = "blink" if self.config.blink_on_alert else "on"
            self.logger.info(
                "Tower light: alert active (red %s, buzzer=%s)",
                red_state, self.config.alert_buzzer,
            )

    def end_alert(self) -> None:
        """Return to standby after an alert ends."""
        self.set_standby()
        if self.logger:
            self.logger.info("Tower light: alert ended; returning to standby")

    # ------------------------------------------------------------------
    # Status

    @property
    def is_available(self) -> bool:
        """``True`` when the serial port was successfully opened."""
        return self._available

    def get_status(self) -> Dict[str, Any]:
        """Return a status dict suitable for the web UI / Redis metrics."""
        return {
            "available": self._available,
            "serial_port": self.config.serial_port,
            "baudrate": self.config.baudrate,
            "alert_buzzer": self.config.alert_buzzer,
            "blink_on_alert": self.config.blink_on_alert,
        }


def load_tower_light_config_from_db(logger=None) -> Optional[TowerLightConfig]:
    """Load USB tower light configuration from the database.

    Returns a :class:`TowerLightConfig` when the feature is enabled, or
    ``None`` when it is disabled or the settings module is unavailable.
    """
    if not _GPIO_SETTINGS_AVAILABLE:
        return None

    try:
        from app_core.hardware_settings import get_tower_light_settings
        settings = get_tower_light_settings()
    except Exception as exc:
        if logger:
            logger.warning("Failed to load tower light settings from database: %s", exc)
        return None

    if not settings.get("enabled", False):
        return None

    return TowerLightConfig(
        serial_port=str(settings.get("serial_port", "/dev/ttyUSB0")),
        baudrate=int(settings.get("baudrate", 9600)),
        alert_buzzer=bool(settings.get("alert_buzzer", False)),
        incoming_uses_yellow=bool(settings.get("incoming_uses_yellow", True)),
        blink_on_alert=bool(settings.get("blink_on_alert", True)),
    )


def load_neopixel_config_from_db(logger=None) -> Optional[NeopixelConfig]:
    """Load NeoPixel configuration from the database.

    Hardware settings are configured via the web UI at ``/admin/hardware``
    and stored in the database.  Environment variables are NOT supported for
    NeoPixel configuration.

    Returns:
        A :class:`NeopixelConfig` when the feature is enabled in the
        database, or ``None`` when it is disabled or no settings row exists.
    """
    if not _GPIO_SETTINGS_AVAILABLE:
        return None

    try:
        from app_core.hardware_settings import get_neopixel_settings
        settings = get_neopixel_settings()
    except Exception as exc:
        if logger:
            logger.warning("Failed to load NeoPixel settings from database: %s", exc)
        return None

    if not settings.get("enabled", False):
        return None

    gpio_pin = int(settings.get("gpio_pin", 18))
    if gpio_pin < 2 or gpio_pin > 27:
        if logger:
            logger.error(
                "NeoPixel GPIO pin %d is outside the supported BCM range (2-27)", gpio_pin
            )
        return None

    def _clamp(value: Any, lo: int, hi: int, default: int) -> int:
        try:
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default

    def _rgb(raw: Any, default: tuple) -> tuple:
        if isinstance(raw, dict):
            try:
                return (
                    _clamp(raw.get("r", 0), 0, 255, 0),
                    _clamp(raw.get("g", 0), 0, 255, 0),
                    _clamp(raw.get("b", 0), 0, 255, 0),
                )
            except Exception:
                pass
        return default

    return NeopixelConfig(
        gpio_pin=gpio_pin,
        num_pixels=_clamp(settings.get("num_pixels", 1), 1, 1024, 1),
        brightness=_clamp(settings.get("brightness", 128), 0, 255, 128),
        led_order=str(settings.get("led_order", "GRB")).upper(),
        standby_color=_rgb(settings.get("standby_color"), (0, 10, 0)),
        alert_color=_rgb(settings.get("alert_color"), (255, 0, 0)),
        flash_on_alert=bool(settings.get("flash_on_alert", True)),
        flash_interval_ms=_clamp(settings.get("flash_interval_ms", 500), 50, 5000, 500),
    )
