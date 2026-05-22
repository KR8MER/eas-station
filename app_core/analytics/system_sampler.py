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

"""Background sampler that persists system-health metrics to PostgreSQL.

Snapshots are captured at a fixed interval (default 30 s) so the
Performance Trends chart and sparklines on the system-info dashboard can
show meaningful history even when the page has not been open.  The
sampler reuses the cached ``get_system_health()`` snapshot so it adds
essentially no extra psutil load.

Retention defaults to 30 days; older rows are pruned hourly.
"""

import logging
import threading
from datetime import timedelta
from typing import Any, Dict, Optional

from app_core.extensions import db
from app_core.analytics.models import SystemMetricSample
from app_core.system_health import get_system_health
from app_utils import utc_now

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_INTERVAL_SECONDS = 30
DEFAULT_RETENTION_DAYS = 30
PRUNE_INTERVAL_SECONDS = 3600


def _pick_root_storage_percent(disk: Any) -> Optional[float]:
    if not isinstance(disk, list):
        return None
    for entry in disk:
        if isinstance(entry, dict) and entry.get("mountpoint") == "/":
            pct = entry.get("percentage")
            if isinstance(pct, (int, float)):
                return float(pct)
    return None


def _pick_primary_temperature(temperature: Any) -> Optional[float]:
    """Best-effort extraction of a representative temperature in °C.

    Mirrors the front-end ``pickPrimaryTemp`` logic so the persisted
    series matches what the dashboard plots when it has live data.
    """
    if not isinstance(temperature, dict):
        return None
    for key in ("current", "cpu", "value"):
        val = temperature.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    for value in temperature.values():
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            current = value.get("current")
            if isinstance(current, (int, float)):
                return float(current)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                current = first.get("current")
                if isinstance(current, (int, float)):
                    return float(current)
    return None


def _extract_sample_fields(snapshot: Dict[str, Any]) -> Dict[str, Optional[float]]:
    cpu = snapshot.get("cpu") or {}
    memory = snapshot.get("memory") or {}
    system = snapshot.get("system") or {}
    load_averages = system.get("load_averages")
    if not isinstance(load_averages, (list, tuple)):
        load_averages = snapshot.get("load_averages")

    def _load(idx: int) -> Optional[float]:
        if isinstance(load_averages, (list, tuple)) and len(load_averages) > idx:
            val = load_averages[idx]
            if isinstance(val, (int, float)):
                return float(val)
        return None

    network = snapshot.get("network") or {}
    traffic = network.get("traffic") if isinstance(network, dict) else None
    net_rx = net_tx = None
    if isinstance(traffic, dict):
        rx = traffic.get("bytes_recv") or traffic.get("rx_bytes")
        tx = traffic.get("bytes_sent") or traffic.get("tx_bytes")
        if isinstance(rx, (int, float)):
            net_rx = int(rx)
        if isinstance(tx, (int, float)):
            net_tx = int(tx)

    return {
        "cpu_percent": float(cpu.get("cpu_usage_percent")) if isinstance(cpu.get("cpu_usage_percent"), (int, float)) else None,
        "memory_percent": float(memory.get("percentage")) if isinstance(memory.get("percentage"), (int, float)) else None,
        "swap_percent": float(memory.get("swap_percentage")) if isinstance(memory.get("swap_percentage"), (int, float)) else None,
        "load_1m": _load(0),
        "load_5m": _load(1),
        "load_15m": _load(2),
        "storage_percent": _pick_root_storage_percent(snapshot.get("disk")),
        "temperature_c": _pick_primary_temperature(snapshot.get("temperature")),
        "net_rx_bytes": net_rx,
        "net_tx_bytes": net_tx,
    }


class SystemMetricsSampler:
    """Background thread that records system-health samples to the database."""

    def __init__(
        self,
        app,
        interval_seconds: int = DEFAULT_SAMPLE_INTERVAL_SECONDS,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self._app = app
        self._interval = max(int(interval_seconds), 5)
        self._retention = max(int(retention_days), 1)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._logger = logger
        self._last_prune_at = 0.0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="SystemMetricsSampler",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "System metrics sampler started (interval=%ss, retention=%sd)",
            self._interval,
            self._retention,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        # First iteration runs immediately so the dashboard gets a fresh
        # row on app startup rather than waiting one full interval.
        while not self._stop_event.is_set():
            try:
                with self._app.app_context():
                    self._record_sample()
                    self._maybe_prune()
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.error(
                    "System metrics sampler iteration failed: %s", exc, exc_info=True
                )
                try:
                    db.session.rollback()
                except Exception:
                    pass
            self._stop_event.wait(self._interval)

    def _record_sample(self) -> None:
        snapshot = get_system_health(logger=self._logger)
        fields = _extract_sample_fields(snapshot)
        # Skip writing a row when every numeric field is None — there's no
        # signal to store and it would just bloat the table.
        if all(v is None for k, v in fields.items() if k != "recorded_at"):
            return
        sample = SystemMetricSample(recorded_at=utc_now(), **fields)
        db.session.add(sample)
        db.session.commit()

    def _maybe_prune(self) -> None:
        import time as _time

        now = _time.monotonic()
        if (now - self._last_prune_at) < PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune_at = now
        cutoff = utc_now() - timedelta(days=self._retention)
        try:
            deleted = (
                db.session.query(SystemMetricSample)
                .filter(SystemMetricSample.recorded_at < cutoff)
                .delete(synchronize_session=False)
            )
            db.session.commit()
            if deleted:
                self._logger.info(
                    "Pruned %d system metric samples older than %s",
                    deleted,
                    cutoff.isoformat(),
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.warning("Failed to prune system metric samples: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass


_sampler_instance: Optional[SystemMetricsSampler] = None
_sampler_lock = threading.Lock()


def start_system_sampler(app, interval_seconds: Optional[int] = None) -> SystemMetricsSampler:
    """Start the global system-metrics sampler, creating it on first call."""
    global _sampler_instance
    with _sampler_lock:
        if _sampler_instance is not None and _sampler_instance.is_running:
            return _sampler_instance
        interval = interval_seconds or int(
            app.config.get("SYSTEM_METRICS_SAMPLE_INTERVAL", DEFAULT_SAMPLE_INTERVAL_SECONDS)
        )
        retention = int(
            app.config.get("SYSTEM_METRICS_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)
        )
        sampler = SystemMetricsSampler(app, interval_seconds=interval, retention_days=retention)
        sampler.start()
        _sampler_instance = sampler
        return sampler


def stop_system_sampler() -> None:
    global _sampler_instance
    with _sampler_lock:
        if _sampler_instance is not None:
            _sampler_instance.stop()
            _sampler_instance = None


__all__ = [
    "SystemMetricsSampler",
    "start_system_sampler",
    "stop_system_sampler",
]
