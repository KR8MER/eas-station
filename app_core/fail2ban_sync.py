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
import os
import threading
import uuid
from typing import Optional

from app_core.extensions import db

logger = logging.getLogger(__name__)

# SSH bans should surface in the Global Ban List promptly, not hours later, so
# this sweep runs far more often than the storage-maintenance schedulers. Each
# cycle is a lightweight no-op unless fail2ban is installed, active, and SSH
# protection is enabled, so a short interval is inexpensive.
SYNC_INTERVAL_SECONDS = 60
STARTUP_DELAY_SECONDS = 30

# Cross-worker leader lock, same Redis-SETNX pattern used by
# app_core/rwt_scheduler.py: this module is imported by every Gunicorn
# worker, so without a lock an N-worker deployment runs N independent
# copies of this loop, each on its own 60s cycle offset by that worker's
# startup time. In production this was visible as clusters of
# `fail2ban-client status` sudo calls firing every ~15-20s (once per
# worker's cycle) instead of once every SYNC_INTERVAL_SECONDS. The lock
# is a renewable lease (TTL = 3x the sync interval) rather than a one-shot
# claim, so if the leader worker dies or is recycled, another worker takes
# over on its next tick instead of leaving the sync permanently orphaned.
_LEADER_LOCK_KEY = "fail2ban_sync:leader"

# Atomically renews the lock's TTL only if we still hold it. A plain
# get()-then-expire() pair has a check-then-act race: the key can expire and
# be claimed by another worker between the two calls, letting the renewing
# worker wrongly believe it is still leader.
_RENEW_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
else
    return 0
end
"""


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
        self._worker_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

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

    def _acquire_or_renew_leader_lock(self) -> bool:
        """True if this worker process should run this cycle.

        Falls back to True (best-effort fire from every worker, the
        historical behaviour) if Redis is unreachable, rather than block
        the sync entirely on a Redis outage.
        """
        try:
            from app_core.extensions import get_redis_client
            redis_client = get_redis_client()
            ttl = self._interval * 3
            if redis_client.set(_LEADER_LOCK_KEY, self._worker_id, nx=True, ex=ttl):
                return True
            return bool(redis_client.eval(_RENEW_LOCK_SCRIPT, 1, _LEADER_LOCK_KEY, self._worker_id, ttl))
        except Exception as exc:
            logger.warning(
                "Could not acquire fail2ban-sync leader lock (Redis unreachable?): %s "
                "— proceeding without cross-worker deduplication",
                exc,
            )
            return True

    def _run(self) -> None:
        if self._stop_event.wait(self._startup_delay):
            return
        while not self._stop_event.is_set():
            if self._acquire_or_renew_leader_lock():
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
