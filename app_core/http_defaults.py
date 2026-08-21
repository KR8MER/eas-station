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

"""Shared outbound HTTP defaults.

Single source of truth for the station's outbound ``User-Agent`` string.
``poller/cap_poller.py`` originated this DB -> env -> hardcoded-default
fallback chain (NOAA's Weather API terms require a descriptive User-Agent
with contact info); every other outbound "health check" request --
the uptime dead-man's-switch heartbeat, Icecast connectivity/status probes
-- used to go out with the bare ``python-requests/x.x`` default instead,
which is confusing on the receiving end (a third-party monitor's or an
Icecast server's request log showing an unidentified Python client rather
than "this is the EAS Station"). Route every such call through
:func:`get_default_user_agent` instead of hardcoding a UA string per
call site, which is exactly how the five slightly-different UA strings
already scattered around this codebase happened.
"""

import os


def get_default_user_agent() -> str:
    """Return the station's configured outbound ``User-Agent`` string.

    Precedence: the DB-configured value (Settings -> Poller ->
    ``PollerSettings.noaa_user_agent``) -> the ``NOAA_USER_AGENT``
    environment variable (legacy fallback) -> a hardcoded compliant
    default. Mirrors ``poller/cap_poller.py``'s own fallback chain exactly
    so every outbound request identifies the station consistently,
    regardless of which subsystem sent it.

    Never raises: the DB lookup is best-effort (this may run outside an
    application/request context, or before the database is reachable),
    matching the CAP poller's own defensive ``try/except`` around the
    same query.
    """
    db_user_agent = None
    try:
        from app_core.models import PollerSettings
        settings = PollerSettings.query.first()
        if settings and settings.noaa_user_agent:
            db_user_agent = settings.noaa_user_agent
    except Exception:
        pass

    return (
        db_user_agent
        or os.getenv('NOAA_USER_AGENT', '')
        or 'EAS Station/2.12 (+https://github.com/KR8MER/eas-station; support@easstation.com)'
    )
