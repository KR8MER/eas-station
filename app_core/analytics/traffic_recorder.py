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

"""Buffered, asynchronous recorder for web-traffic analytics.

The Flask ``after_request`` hook hands each recordable request to
:func:`record_request`, which simply appends a lightweight dict to an in-memory
buffer — no database work happens on the request path. A daemon thread drains
the buffer every few seconds with a single bulk insert, refreshes the cached
collection config, and prunes rows past the retention window once an hour.

This mirrors the lifecycle of ``system_sampler.SystemMetricsSampler`` so the two
background writers behave consistently across gunicorn workers.
"""

import logging
import threading
import time
from collections import deque
from datetime import timedelta
from typing import Any, Deque, Dict, Optional

from app_core.extensions import db
from app_core.analytics.web_traffic import TrafficAnalyticsSettings, WebRequestLog
from app_utils import utc_now

logger = logging.getLogger(__name__)

DEFAULT_FLUSH_INTERVAL_SECONDS = 5
DEFAULT_BATCH_SIZE = 500
DEFAULT_BUFFER_MAX = 10000
CONFIG_REFRESH_SECONDS = 30
PRUNE_INTERVAL_SECONDS = 3600


class TrafficRecorder:
    """Background writer that batches :class:`WebRequestLog` inserts."""

    def __init__(
        self,
        app,
        flush_interval: int = DEFAULT_FLUSH_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        buffer_max: int = DEFAULT_BUFFER_MAX,
    ) -> None:
        self._app = app
        self._flush_interval = max(int(flush_interval), 1)
        self._batch_size = max(int(batch_size), 1)
        # ``maxlen`` makes the buffer self-limiting: under a flood the oldest
        # unflushed entries are dropped rather than growing memory unbounded.
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=buffer_max)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._logger = logger
        self._last_prune_at = 0.0
        self._last_config_at = 0.0
        self._config: Dict[str, Any] = dict(TrafficAnalyticsSettings.DEFAULTS)

    # ------------------------------------------------------------------ config
    @property
    def config(self) -> Dict[str, Any]:
        """The most recently cached collection config (never hits the DB)."""
        return self._config

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _refresh_config(self) -> None:
        """Reload collection settings from the database into the cache."""
        try:
            row = TrafficAnalyticsSettings.query.first()
            self._config = row.as_config() if row else dict(TrafficAnalyticsSettings.DEFAULTS)
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.debug("Could not refresh traffic config: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass

    # ------------------------------------------------------------------ record
    def record(self, entry: Dict[str, Any]) -> None:
        """Queue a request record for asynchronous persistence."""
        if not self._config.get("enabled", True):
            return
        with self._lock:
            self._buffer.append(entry)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        # Prime the config once up front so the very first requests honour the
        # operator's stored preferences instead of the in-code defaults.
        try:
            with self._app.app_context():
                self._refresh_config()
        except Exception:  # pragma: no cover - defensive
            pass
        self._thread = threading.Thread(
            target=self._run, name="TrafficRecorder", daemon=True
        )
        self._thread.start()
        self._logger.info(
            "Traffic recorder started (flush=%ss, batch=%s)",
            self._flush_interval,
            self._batch_size,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        # Best-effort final flush so a clean shutdown doesn't lose buffered rows.
        try:
            with self._app.app_context():
                self._flush()
        except Exception:  # pragma: no cover - defensive
            pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with self._app.app_context():
                    self._maybe_refresh_config()
                    self._flush()
                    self._maybe_prune()
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.error(
                    "Traffic recorder iteration failed: %s", exc, exc_info=True
                )
                try:
                    db.session.rollback()
                except Exception:
                    pass
            self._stop_event.wait(self._flush_interval)

    def _maybe_refresh_config(self) -> None:
        now = time.monotonic()
        if (now - self._last_config_at) < CONFIG_REFRESH_SECONDS:
            return
        self._last_config_at = now
        self._refresh_config()

    def _drain(self) -> list:
        with self._lock:
            if not self._buffer:
                return []
            rows = list(self._buffer)
            self._buffer.clear()
        return rows

    def _flush(self) -> None:
        rows = self._drain()
        if not rows:
            return
        try:
            db.session.bulk_insert_mappings(WebRequestLog, rows)
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.warning("Failed to flush %d traffic rows: %s", len(rows), exc)
            try:
                db.session.rollback()
            except Exception:
                pass

    def _maybe_prune(self) -> None:
        now = time.monotonic()
        if (now - self._last_prune_at) < PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune_at = now
        retention_days = int(self._config.get("retention_days", 90) or 90)
        cutoff = utc_now() - timedelta(days=max(retention_days, 1))
        try:
            deleted = (
                db.session.query(WebRequestLog)
                .filter(WebRequestLog.timestamp < cutoff)
                .delete(synchronize_session=False)
            )
            db.session.commit()
            if deleted:
                self._logger.info(
                    "Pruned %d web request log rows older than %s",
                    deleted,
                    cutoff.isoformat(),
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.warning("Failed to prune web request logs: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass


_recorder_instance: Optional[TrafficRecorder] = None
_recorder_lock = threading.Lock()


def start_traffic_recorder(app) -> TrafficRecorder:
    """Start the global traffic recorder, creating it on first call."""
    global _recorder_instance
    with _recorder_lock:
        if _recorder_instance is not None and _recorder_instance.is_running:
            return _recorder_instance
        recorder = TrafficRecorder(app)
        recorder.start()
        _recorder_instance = recorder
        return recorder


def get_traffic_recorder() -> Optional[TrafficRecorder]:
    """Return the global recorder instance (or ``None`` if not started)."""
    return _recorder_instance


def stop_traffic_recorder() -> None:
    global _recorder_instance
    with _recorder_lock:
        if _recorder_instance is not None:
            _recorder_instance.stop()
            _recorder_instance = None


def record_request(entry: Dict[str, Any]) -> None:
    """Queue a request record if the recorder is running (no-op otherwise)."""
    recorder = _recorder_instance
    if recorder is not None:
        recorder.record(entry)


__all__ = [
    "TrafficRecorder",
    "start_traffic_recorder",
    "stop_traffic_recorder",
    "get_traffic_recorder",
    "record_request",
]
