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

from sqlalchemy import func

from app_core.extensions import db
from app_core.analytics.web_traffic import TrafficAnalyticsSettings, WebRequestLog
from app_utils import utc_now

logger = logging.getLogger(__name__)

DEFAULT_FLUSH_INTERVAL_SECONDS = 5
DEFAULT_BATCH_SIZE = 500
DEFAULT_BUFFER_MAX = 10000
CONFIG_REFRESH_SECONDS = 30
PRUNE_INTERVAL_SECONDS = 3600
# How often the background thread retries reverse-DNS for rows that still have no
# hostname, and how many fresh IPs to resolve per pass. Hostnames are recorded
# once at insert time, so rows captured before "Resolve hostnames" was enabled —
# or during a transient DNS hiccup, or for an IP that only later published a PTR
# record — would otherwise stay a bare IP forever. This backfills them.
HOSTNAME_BACKFILL_INTERVAL_SECONDS = 600
HOSTNAME_BACKFILL_BATCH = 50          # unique IPs resolved per pass
HOSTNAME_BACKFILL_SCAN = 500          # distinct unresolved IPs scanned per pass
HOSTNAME_TRIED_MAX = 100000           # cap on the in-memory "already attempted" set


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
        self._last_hostname_backfill_at = 0.0
        # IPs we've already attempted to reverse-resolve this process, so we don't
        # repeatedly re-query a host that has no PTR record. Cleared if it grows
        # unbounded; a process restart naturally retries (recovering from any
        # earlier transient resolver failures).
        self._hostname_tried: set = set()
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
                    self._maybe_backfill_hostnames()
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
        self._resolve_hostnames(rows)
        try:
            db.session.bulk_insert_mappings(WebRequestLog, rows)
            db.session.commit()
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.warning("Failed to flush %d traffic rows: %s", len(rows), exc)
            try:
                db.session.rollback()
            except Exception:
                pass

    def _resolve_hostnames(self, rows: list) -> None:
        """Fill in reverse-DNS hostnames for buffered rows (awstats-style).

        Runs in the background flush thread (never on the request path). Each
        unique IP in the batch is resolved at most once thanks to the cache in
        ``geo.resolve_hostname``; results are written back onto the row dicts
        before the bulk insert.
        """
        if not self._config.get("resolve_hostnames", False):
            return
        try:
            from app_core.analytics.geo import resolve_hostname
        except Exception:  # pragma: no cover - defensive
            return
        resolved: Dict[str, Optional[str]] = {}
        for row in rows:
            if row.get("hostname"):
                continue
            ip = row.get("ip_address")
            if not ip:
                continue
            if ip not in resolved:
                try:
                    resolved[ip] = resolve_hostname(ip)
                except Exception:  # pragma: no cover - defensive
                    resolved[ip] = None
            row["hostname"] = resolved[ip]

    def _maybe_backfill_hostnames(self) -> None:
        """Reverse-resolve rows that still have a NULL hostname (awstats-style).

        Only runs when "Resolve hostnames" is enabled. Picks the most-recently
        active unresolved IPs first (real visitors over stale scanner noise),
        resolves a bounded batch per pass off the request path, and writes the
        hostname back onto every row for that IP. IPs with no PTR record are
        attempted once and remembered so they aren't re-queried each pass.
        """
        if not self._config.get("resolve_hostnames", False):
            return
        now = time.monotonic()
        if (now - self._last_hostname_backfill_at) < HOSTNAME_BACKFILL_INTERVAL_SECONDS:
            return
        self._last_hostname_backfill_at = now

        try:
            from app_core.analytics.geo import resolve_hostname
        except Exception:  # pragma: no cover - defensive
            return

        try:
            rows = (
                db.session.query(
                    WebRequestLog.ip_address,
                    func.max(WebRequestLog.timestamp).label("last_seen"),
                )
                .filter(
                    WebRequestLog.hostname.is_(None),
                    WebRequestLog.ip_address.isnot(None),
                )
                .group_by(WebRequestLog.ip_address)
                .order_by(func.max(WebRequestLog.timestamp).desc())
                .limit(HOSTNAME_BACKFILL_SCAN)
                .all()
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._logger.debug("Hostname backfill scan failed: %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass
            return

        # Take the first batch of IPs we haven't already attempted this process.
        candidates = []
        for ip, _ in rows:
            if ip in self._hostname_tried:
                continue
            candidates.append(ip)
            if len(candidates) >= HOSTNAME_BACKFILL_BATCH:
                break
        if not candidates:
            return

        if len(self._hostname_tried) > HOSTNAME_TRIED_MAX:
            self._hostname_tried.clear()

        updated = 0
        for ip in candidates:
            try:
                name, status = resolve_hostname(ip, return_status=True)
            except Exception:  # pragma: no cover - defensive
                name, status = None, "error"
            # Only remember IPs whose outcome was *definitive* (resolved or an
            # authoritative "no PTR record"). A transient failure — most often a
            # slow IPv6 ip6.arpa lookup — is left out of the tried-set so the next
            # backfill pass retries it instead of locking in a one-shot miss.
            if status != "error":
                self._hostname_tried.add(ip)
            if not name:
                continue
            try:
                updated += (
                    db.session.query(WebRequestLog)
                    .filter(
                        WebRequestLog.ip_address == ip,
                        WebRequestLog.hostname.is_(None),
                    )
                    .update({WebRequestLog.hostname: name}, synchronize_session=False)
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.debug("Hostname backfill update failed for %s: %s", ip, exc)
                try:
                    db.session.rollback()
                except Exception:
                    pass
        if updated:
            try:
                db.session.commit()
                self._logger.info("Backfilled reverse-DNS hostnames for %d rows", updated)
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.warning("Failed to commit hostname backfill: %s", exc)
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
