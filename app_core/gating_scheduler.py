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

"""Background release sweeper for the gated-alerts hold-off timer (OTA path).

Runs inside eas_monitoring_service.py, which owns a Flask app object, so this
scheduler follows app_core.retention.RetentionScheduler's shape almost
exactly: a threading.Event-based daemon thread with interruptible sleep.

The CAP poller path needs a *different* scheduler shape (poller/cap_poller.py
has no Flask app and manages its own raw-SQLAlchemy session) -- that variant
lives inline in poller/cap_poller.py next to its existing local model mirrors,
not here.

Only one instance of this scheduler should ever run (inside the eas-monitor
service). It must NOT be started from the Gunicorn web app -- Approve/Cancel
release alerts synchronously within the request instead.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 20
STARTUP_DELAY_SECONDS = 15


def _release_ota_gate_row(gate_row) -> Dict[str, Any]:
    """Flip a pending OTA GatedAlert row to released and replay it through
    the normal OTA auto-forward path.

    Must run inside a Flask app context -- _auto_forward_to_air_chain()
    requires one and returns None immediately without it.
    """
    from app_core.extensions import db
    from app_core.models import GatedAlert
    from app_core.audio.alert_forwarding import _auto_forward_to_air_chain
    from app_utils import utc_now

    gate_row.status = 'released'
    gate_row.resolved_at = utc_now()
    gate_row.resolution_reason = 'Hold-off timer expired'
    db.session.add(gate_row)
    db.session.commit()

    alert_dict = dict(gate_row.ota_payload or {})
    alert_dict['identifier'] = gate_row.identifier
    if gate_row.ota_audio_wav:
        alert_dict['relay_audio_wav'] = gate_row.ota_audio_wav

    result = _auto_forward_to_air_chain(alert_dict) or {}

    gate_row.broadcast_result = result
    db.session.add(gate_row)
    db.session.commit()
    return result


class GatedAlertScheduler:
    """Daemon thread that releases OTA-sourced gated alerts once their
    hold-off timer expires."""

    def __init__(
        self,
        app,
        interval_seconds: int = SWEEP_INTERVAL_SECONDS,
        startup_delay_seconds: int = STARTUP_DELAY_SECONDS,
    ) -> None:
        self._app = app
        self._interval = max(int(interval_seconds), 5)
        self._startup_delay = max(int(startup_delay_seconds), 0)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="gated-alert-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Gated-alert release scheduler started (interval=%ss, first sweep in %ss)",
            self._interval, self._startup_delay,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("Gated-alert release scheduler stopped")

    def run_sweep_now(self) -> Dict[str, Any]:
        """Release every due OTA pending row. Used by the loop and tests."""
        with self._app.app_context():
            from app_core.models import GatedAlert

            now = datetime.now(timezone.utc)
            due = (
                GatedAlert.without_audio()
                .filter_by(source='ota', status='pending')
                .filter(GatedAlert.hold_until <= now)
                .all()
            )
            released = []
            for gate_row in due:
                try:
                    # Re-fetch with audio for the actual release call.
                    from app_core.models import GatedAlert as _GA
                    from app_core.extensions import db
                    full_row = db.session.get(_GA, gate_row.id)
                    if full_row is None or full_row.status != 'pending':
                        continue
                    _release_ota_gate_row(full_row)
                    released.append(full_row.id)
                except Exception as exc:
                    logger.error(
                        "Failed to release gated OTA alert id=%s: %s",
                        gate_row.id, exc, exc_info=True,
                    )
            return {"released": released}

    def _run(self) -> None:
        if self._stop_event.wait(self._startup_delay):
            return
        while not self._stop_event.is_set():
            try:
                self.run_sweep_now()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("Gated-alert release sweep failed: %s", exc, exc_info=True)
                try:
                    from app_core.extensions import db
                    db.session.rollback()
                except Exception:
                    pass
            self._stop_event.wait(self._interval)


_scheduler_instance: Optional[GatedAlertScheduler] = None
_scheduler_lock = threading.Lock()


def start_scheduler(app) -> GatedAlertScheduler:
    """Start the global gated-alert release scheduler (idempotent)."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.is_running:
            return _scheduler_instance
        scheduler = GatedAlertScheduler(app)
        scheduler.start()
        _scheduler_instance = scheduler
        return scheduler


def stop_scheduler() -> None:
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None:
            _scheduler_instance.stop()
            _scheduler_instance = None


__all__ = [
    "GatedAlertScheduler",
    "start_scheduler",
    "stop_scheduler",
]
