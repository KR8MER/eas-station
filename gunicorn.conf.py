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

"""Gunicorn configuration for the EAS Station web application.

Adds a systemd watchdog heartbeat to the arbiter (master) process. The unit
already has ``Restart=always``, which recovers from a crashed arbiter, but
does nothing for a *wedged* one (e.g. deadlocked on a fork/signal race) --
the process is still alive, so systemd sees no reason to restart it and the
site silently stops accepting connections. ``when_ready`` runs in the
arbiter once every worker has booted; the background thread it starts keeps
kicking ``WATCHDOG=1`` for as long as the arbiter's own event loop is still
running. This does not cover a single hung gevent worker -- that's already
handled by gunicorn's own ``--timeout``, which kills and respawns it.
"""

import threading
import time

from app_utils.system.sd_notify import notify as sd_notify, Watchdog

_watchdog_stop = threading.Event()


def when_ready(server):  # noqa: ARG001 -- server is required by gunicorn's hook API
    sd_notify("READY=1")
    watchdog = Watchdog()

    def _tick():
        while not _watchdog_stop.is_set():
            watchdog.kick()
            time.sleep(5)

    threading.Thread(target=_tick, daemon=True, name="gunicorn-watchdog").start()


def on_exit(server):  # noqa: ARG001 -- server is required by gunicorn's hook API
    _watchdog_stop.set()
