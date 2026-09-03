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

This same loop also drives a second, independent signal: TickstemSettings'
"service heartbeat", which -- unlike the one above -- IS gated on
get_system_health()'s aggregate status, so a crashed/failed subsystem (or a
lost database connection) shows up as a missed heartbeat too. Sharing the
loop keeps this to one background thread rather than two near-identical
ones; each signal tracks its own last-ping time and interval independently.
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
        # Fixed tick rather than "sleep for the configured interval": once
        # several independently-scheduled signals (one per service
        # heartbeat, on top of the unconditional one) share this loop, a
        # single sleep duration can't serve all of them correctly. Each
        # ping below checks its own last-ping timestamp and decides for
        # itself whether it's due.
        while not self._stop_event.is_set():
            try:
                with self._app.app_context():
                    self._ping_once()
                    self._ping_service_heartbeats_once()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Heartbeat worker iteration failed: %s", exc)
            self._stop_event.wait(_MIN_INTERVAL_SECONDS)

    def _ping_once(self) -> None:
        """Send the unconditional "box is alive" ping if it's due."""
        from app_core.extensions import db
        from app_core.models import HeartbeatSettings

        settings = HeartbeatSettings.query.first()
        if not settings or not settings.enabled or not settings.ping_url:
            return

        interval = max(settings.interval_seconds or _MIN_INTERVAL_SECONDS, _MIN_INTERVAL_SECONDS)
        if not _is_due(settings.last_ping_at, interval):
            return

        success, error = send_heartbeat_ping(settings.ping_url)

        settings.last_ping_at = _utc_now()
        settings.last_ping_success = success
        settings.last_ping_error = error
        try:
            db.session.commit()
        except Exception as exc:
            logger.error("Failed to record heartbeat ping result: %s", exc)
            db.session.rollback()

    def _ping_service_heartbeats_once(self) -> None:
        """Ping each per-service heartbeat that's due and whose own service
        is currently active -- silent otherwise, so Tickstem's own
        missed-ping alerting surfaces exactly which subsystem failed. Each
        row is independent: one down/disabled service never blocks pings
        for the others.
        """
        from app_core.models import TickstemServiceHeartbeat

        rows = TickstemServiceHeartbeat.query.filter_by(enabled=True).all()
        if not rows:
            return

        try:
            service_status = _current_service_status()
        except Exception as exc:
            logger.error("Service-heartbeat health check failed: %s", exc)
            return

        for row in rows:
            interval = max(row.interval_secs or _MIN_INTERVAL_SECONDS, _MIN_INTERVAL_SECONDS)
            if not _is_due(row.last_ping_at, interval):
                continue
            if not service_status.get(row.service_name):
                continue  # that service isn't active right now -- stay silent, let the ping lapse
            self._ping_one_service_heartbeat(row)

    def _ping_one_service_heartbeat(self, row) -> None:
        from app_core.extensions import db

        success, error = send_heartbeat_ping(row.ping_url)

        row.last_ping_at = _utc_now()
        row.last_ping_success = success
        row.last_ping_error = error
        try:
            db.session.commit()
        except Exception as exc:
            logger.error("Failed to record service heartbeat ping result for %s: %s", row.service_name, exc)
            db.session.rollback()


def send_heartbeat_ping(ping_url: str, timeout: int = 10):
    """Send one heartbeat request. Returns (success, error_message).

    POST rather than GET: healthchecks.io accepts either, but some
    healthchecks.io-alternative services (e.g. Tickstem) only recognize
    POST on the ping route and reply 401 "missing authorization" to a
    GET -- misleading, since the real problem is the HTTP method, not
    a missing credential. POST is the safe superset.
    """
    from app_core.http_defaults import get_default_user_agent
    try:
        response = requests.post(
            ping_url, timeout=timeout,
            headers={'User-Agent': get_default_user_agent()},
        )
        if 200 <= response.status_code < 300:
            return True, None
        return False, f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        return False, str(exc)


def _current_service_status() -> dict:
    """service_name -> is_running, from the same cached snapshot the System
    Health page shows (get_system_health()["systemd"]["services"]).
    """
    from app_core.system_health import get_system_health
    systemd = get_system_health(logger).get("systemd", {})
    return {
        service.get("name"): bool(service.get("is_running"))
        for service in systemd.get("services", [])
        if service.get("name")
    }


def _utc_now():
    from app_utils import utc_now
    return utc_now()


def _is_due(last_at, interval_seconds: int) -> bool:
    """True if last_at is None (never pinged) or interval_seconds have
    elapsed since it. last_at may be naive (as stored via _utc_now()) or
    aware -- normalize both sides to compare directly.
    """
    if last_at is None:
        return True
    from app_utils import utc_now
    now = utc_now()
    if last_at.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    elif last_at.tzinfo is not None and now.tzinfo is None:
        last_at = last_at.replace(tzinfo=None)
    return (now - last_at).total_seconds() >= interval_seconds


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
