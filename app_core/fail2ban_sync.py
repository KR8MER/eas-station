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

"""Background fail2ban → Global Ban List sync service.

fail2ban's ``sshd`` jail catches SSH brute-force attempts and drops them at the
host firewall continuously, day and night. But the Security Center's Global Ban
List lives in the database (``ip_filters``), and a sshd-jail ban only becomes a
visible ban-list entry once it is copied there by
``webapp.admin.fail2ban._import_ssh_bans``.

That import used to run *only* as a side effect of a web request — specifically
while the Security Center page was open and polling ``/admin/fail2ban/status``.
The consequence was the symptom operators reported: SSH attacks appeared to
happen "only while I'm working on the UI" and never overnight, because nothing
recorded them into the ban list unless someone had the page open. The
``created_at`` of each entry reflected when an operator next loaded the UI, not
when fail2ban actually banned the offender.

This module closes that gap with a small daemon thread that periodically runs
the same import + firewall self-heal (``run_background_sync``) regardless of
whether anyone has the UI open. It mirrors the other background schedulers in
``app_core`` (auto-purge, retention, backups): start it once at app startup,
it re-reads settings every cycle, and it is a cheap no-op when fail2ban or SSH
protection is not in use.
"""

import logging
import threading
from typing import Optional

from app_core.extensions import db

logger = logging.getLogger(__name__)

# SSH bans should surface in the Global Ban List promptly, not hours later, so
# this sweep runs far more often than the storage-maintenance schedulers. Each
# cycle is a lightweight no-op unless fail2ban is installed, active, and SSH
# protection is enabled, so a short interval is inexpensive.
SYNC_INTERVAL_SECONDS = 60
STARTUP_DELAY_SECONDS = 30


def run_sync_cycle() -> dict:
    """Run one fail2ban sync cycle. Must be called inside a Flask app context.

    Performs the same work the Security Center page used to trigger only while
    open, but as plain ``app_core`` calls (no ``webapp`` import, so this stays
    on the right side of the layering and is cheap from a background thread):

    * ``import_ssh_bans`` — copy any new sshd-jail bans into the Global Ban List.
    * ``heal_firewall_bans`` — re-mirror the ban list into the firewall jail if
      the two have drifted (e.g. after a fail2ban restart flushed it).

    Both are no-ops unless fail2ban is up and the relevant feature is enabled,
    and the self-heal only re-pushes bans when it detects drift, so a steady
    state costs just a couple of ``fail2ban-client status`` reads per cycle.
    Re-applying SSH offenders back into the ``sshd`` jail after a restart is left
    to the Security Center's apply/restart/resync paths (``resync_ssh_bans``),
    which is where a flush actually happens — doing it every cycle would re-issue
    a ``banip`` for every already-banned offender on every tick for no benefit.

    Returns a small summary; never raises.
    """
    from app_core.auth import firewall

    summary = {"imported": 0, "firewall_healed": False}
    try:
        summary["imported"] = firewall.import_ssh_bans()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("SSH ban import skipped: %s", exc)
    try:
        summary["firewall_healed"] = firewall.heal_firewall_bans()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Firewall self-heal skipped: %s", exc)
    return summary


class Fail2banSyncScheduler:
    """Daemon thread that imports new sshd-jail bans into the Global Ban List
    and self-heals the firewall mirror shortly after startup and then on a
    fixed interval. Settings are re-read from the database on every cycle, so
    enabling/disabling SSH protection takes effect without a restart.
    """

    def __init__(
        self,
        app,
        interval_seconds: int = SYNC_INTERVAL_SECONDS,
        startup_delay_seconds: int = STARTUP_DELAY_SECONDS,
    ) -> None:
        self._app = app
        self._interval = max(int(interval_seconds), 15)
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
            name="fail2ban-sync-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "fail2ban sync scheduler started (interval=%ss, first run in %ss)",
            self._interval,
            self._startup_delay,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        logger.info("fail2ban sync scheduler stopped")

    def run_now(self) -> dict:
        with self._app.app_context():
            return run_sync_cycle()

    def _run(self) -> None:
        if self._stop_event.wait(self._startup_delay):
            return
        while not self._stop_event.is_set():
            try:
                self.run_now()
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("fail2ban sync cycle failed: %s", exc, exc_info=True)
                try:
                    db.session.rollback()
                except Exception:
                    pass
            self._stop_event.wait(self._interval)


_scheduler_instance: Optional[Fail2banSyncScheduler] = None
_scheduler_lock = threading.Lock()


def start_scheduler(app) -> Fail2banSyncScheduler:
    """Start the global fail2ban sync scheduler (idempotent)."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.is_running:
            return _scheduler_instance
        scheduler = Fail2banSyncScheduler(app)
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
    "Fail2banSyncScheduler",
    "STARTUP_DELAY_SECONDS",
    "SYNC_INTERVAL_SECONDS",
    "run_sync_cycle",
    "start_scheduler",
    "stop_scheduler",
]
