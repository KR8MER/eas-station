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

"""Minimal sd_notify client for systemd ``Type=notify`` services.

No external dependency: writes directly to the AF_UNIX datagram socket
named by ``$NOTIFY_SOCKET``, exactly as ``sd_notify(3)`` documents. A no-op
when not launched under systemd (dev shell, tests, manual runs), so it is
always safe to call.
"""

import os
import socket
import time


def notify(state: str) -> bool:
    """Send a state string (e.g. ``"READY=1"``, ``"WATCHDOG=1"``) to systemd.

    Returns True if a notify socket was found and the message was sent,
    False otherwise (including when not running under systemd).
    """
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(state.encode("utf-8"), address)
        return True
    except OSError:
        return False


class Watchdog:
    """Throttled ``WATCHDOG=1`` kicker for a systemd ``Type=notify`` service.

    Call :meth:`kick` as often as convenient from a live code path -- a hot
    loop is fine. Actual notifications are throttled to roughly half of
    ``$WATCHDOG_USEC`` (or ``min_interval`` seconds if systemd didn't set
    one), matching systemd's own recommendation for watchdog cadence. A
    caller that stops calling ``kick()`` -- because it deadlocked -- simply
    stops refreshing the watchdog, and systemd kills + restarts the unit.
    """

    def __init__(self, min_interval: float = 5.0) -> None:
        watchdog_usec = os.environ.get("WATCHDOG_USEC")
        if watchdog_usec:
            try:
                min_interval = min(min_interval, (int(watchdog_usec) / 1_000_000) / 2)
            except ValueError:
                pass
        self._min_interval = max(0.5, min_interval)
        self._last_kick = 0.0

    def kick(self) -> None:
        now = time.monotonic()
        if now - self._last_kick >= self._min_interval:
            notify("WATCHDOG=1")
            self._last_kick = now
