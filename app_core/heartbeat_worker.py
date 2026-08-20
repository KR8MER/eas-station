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

"""Outbound dead-man's-switch heartbeat worker.

Every other health check in this application is inward-facing. This
background thread periodically pings an external monitoring service
(healthchecks.io-style) so that total loss of power, network, or a wedged
OS -- conditions under which this box cannot report its own status to
anyone -- is what raises the alarm, on a channel outside this box.

Deliberately NOT gated on internal system health (that's what
HealthAlertWorker is for): the ping fires unconditionally on schedule, so
its only failure mode is "this process stopped running," which is exactly
the condition it exists to catch.
"""

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_MIN_INTERVAL_SECONDS = 60

_worker_instance: Optional["HeartbeatWorker"] = None
_worker_lock = threading.Lock()


class HeartbeatWorker:
    """Background daemon thread that pings an external uptime monitor."""

    def __init__(self, app) -> None:
        self._app = app
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="HeartbeatWorker", daemon=True)
        self._thread.start()
        logger.info("Heartbeat worker started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            interval = _MIN_INTERVAL_SECONDS
            try:
                with self._app.app_context():
                    interval = self._ping_once()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Heartbeat worker iteration failed: %s", exc)
            self._stop_event.wait(max(interval, _MIN_INTERVAL_SECONDS))

    def _ping_once(self) -> int:
        """Send one ping if configured/enabled. Returns the configured interval."""
        from app_core.extensions import db
        from app_core.models import HeartbeatSettings

        settings = HeartbeatSettings.query.first()
        if not settings or not settings.enabled or not settings.ping_url:
            return _MIN_INTERVAL_SECONDS

        interval = max(settings.interval_seconds or _MIN_INTERVAL_SECONDS, _MIN_INTERVAL_SECONDS)
        success, error = send_heartbeat_ping(settings.ping_url)

        settings.last_ping_at = _utc_now()
        settings.last_ping_success = success
        settings.last_ping_error = error
        try:
            db.session.commit()
        except Exception as exc:
            logger.error("Failed to record heartbeat ping result: %s", exc)
            db.session.rollback()

        return interval


def send_heartbeat_ping(ping_url: str, timeout: int = 10):
    """Send one heartbeat GET request. Returns (success, error_message)."""
    try:
        response = requests.get(ping_url, timeout=timeout)
        if 200 <= response.status_code < 300:
            return True, None
        return False, f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        return False, str(exc)


def _utc_now():
    from app_utils import utc_now
    return utc_now()


def start_heartbeat_worker(app) -> "HeartbeatWorker":
    global _worker_instance
    with _worker_lock:
        if _worker_instance is not None and _worker_instance.is_running:
            return _worker_instance
        worker = HeartbeatWorker(app)
        worker.start()
        _worker_instance = worker
        return worker


def stop_heartbeat_worker() -> None:
    global _worker_instance
    with _worker_lock:
        if _worker_instance is not None:
            _worker_instance.stop()
            _worker_instance = None


__all__ = ["HeartbeatWorker", "send_heartbeat_ping", "start_heartbeat_worker", "stop_heartbeat_worker"]
