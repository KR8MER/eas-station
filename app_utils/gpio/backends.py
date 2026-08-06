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

"""GPIO backend abstraction and hardware probing.

Three interchangeable backends (lgpio, sysfs, null) behind one Protocol, plus
the gpiozero pin-factory setup that picks a real or mock factory depending on
what the host actually has.
"""

import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Set



try:  # pragma: no cover - GPIO hardware is optional and platform specific
    from gpiozero import Device, OutputDevice
except Exception:  # pragma: no cover - gracefully handle non-RPi environments
    Device = None  # type: ignore[assignment]
    OutputDevice = None  # type: ignore[assignment]

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
# in processes that actually instantiate the backend (the gpio and gps
# subsystem subprocesses — services.gpio and services.gps — since they
# own the only call sites that need a GPIO backend after the Phase 4
# split of the hardware service).

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
        # actually instantiated (i.e., in the gpio / gps subprocesses, not
        # in the web app).
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
