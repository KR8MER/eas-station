"""Core abstractions for coordinating one or more radio receivers."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from app_core.models import RadioReceiver, RadioReceiverStatus


@dataclass(frozen=True)
class ReceiverConfig:
    """Configuration describing how to initialise a receiver driver."""

    identifier: str
    driver: str
    frequency_hz: float
    sample_rate: int
    gain: Optional[float] = None
    channel: Optional[int] = None
    enabled: bool = True


@dataclass
class ReceiverStatus:
    """Lightweight status report emitted by receiver drivers."""

    identifier: str
    locked: bool
    signal_strength: Optional[float] = None
    last_error: Optional[str] = None


class ReceiverInterface(ABC):
    """Base interface implemented by all receiver driver backends."""

    def __init__(self, config: ReceiverConfig) -> None:
        self.config = config

    @abstractmethod
    def start(self) -> None:
        """Begin streaming or monitoring on the configured frequency."""

    @abstractmethod
    def stop(self) -> None:
        """Halt streaming and release hardware resources."""

    @abstractmethod
    def get_status(self) -> ReceiverStatus:
        """Return the latest health information for the receiver."""


class RadioManager:
    """Coordinate SDR receivers and expose a unified management surface."""

    def __init__(self) -> None:
        self._drivers: Dict[str, type[ReceiverInterface]] = {}
        self._receivers: Dict[str, ReceiverInterface] = {}
        self._lock = threading.RLock()

    def register_driver(self, name: str, driver: type[ReceiverInterface]) -> None:
        """Register a receiver implementation that can be instantiated by name."""

        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Driver name must not be empty")

        with self._lock:
            self._drivers[normalized] = driver

    def available_drivers(self) -> Mapping[str, type[ReceiverInterface]]:
        """Return a snapshot of the registered drivers."""

        with self._lock:
            return dict(self._drivers)

    def configure_receivers(self, configs: Iterable[ReceiverConfig]) -> None:
        """Instantiate and track receivers for the provided configurations."""

        with self._lock:
            desired: Dict[str, ReceiverInterface] = {}
            for config in configs:
                if not config.enabled:
                    continue
                driver_cls = self._drivers.get(config.driver.lower())
                if not driver_cls:
                    raise KeyError(f"No driver registered for '{config.driver}'")

                existing = self._receivers.get(config.identifier)
                if existing is not None:
                    existing.stop()

                receiver = driver_cls(config)
                desired[config.identifier] = receiver

            for identifier, receiver in self._receivers.items():
                if identifier not in desired:
                    receiver.stop()

            self._receivers = desired

    def configure_from_records(self, receiver_rows: Iterable["RadioReceiver"]) -> None:
        """Convenience helper that builds configs from database records."""

        configs: List[ReceiverConfig] = []
        for row in receiver_rows:
            config = row.to_receiver_config()
            configs.append(config)

        self.configure_receivers(configs)

    def start_all(self) -> None:
        """Start all configured receivers."""

        with self._lock:
            for receiver in self._receivers.values():
                receiver.start()

    def stop_all(self) -> None:
        """Stop all configured receivers."""

        with self._lock:
            for receiver in self._receivers.values():
                receiver.stop()

    def get_status_reports(self) -> List[ReceiverStatus]:
        """Collect status reports from every active receiver."""

        with self._lock:
            return [receiver.get_status() for receiver in self._receivers.values()]

    @staticmethod
    def build_status_from_rows(
        status_rows: Iterable["RadioReceiverStatus"],
    ) -> List[ReceiverStatus]:
        """Convert database status entries into manager-friendly reports."""

        reports: List[ReceiverStatus] = []
        for row in status_rows:
            reports.append(row.to_receiver_status())

        return reports
