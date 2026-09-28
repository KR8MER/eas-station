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

"""Receiver roles, air-check settings and shared session helpers."""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROLE_MONITOR = "monitor"
ROLE_AIR_CHECK = "air_check"
RECEIVER_ROLES = (ROLE_MONITOR, ROLE_AIR_CHECK)

DEFAULT_GRACE_SECONDS = 60
MIN_GRACE_SECONDS = 10
MAX_GRACE_SECONDS = 900

#: How far back a decode may reach to find the transmission it belongs to,
#: and how far back a new transmission may reach to adopt an earlier decode.
MATCH_WINDOW = timedelta(minutes=15)

#: Upper bound on the playout time credited to one transmission, matching
#: the broadcaster's own max_activation_seconds default.
MAX_PLAYOUT_SECONDS = 300.0

_ROLE_CACHE_TTL = 30.0
_role_cache: Dict[str, Tuple[float, Optional[str], Optional[str]]] = {}


def _default_session():
    from app_core.extensions import db

    return db.session


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _rollback(session) -> None:
    try:
        session.rollback()
    except Exception:  # pragma: no cover - defensive
        pass


def _system_log(session, level: str, message: str, details: Dict[str, Any]) -> None:
    from app_core.models import SystemLog

    session.add(SystemLog(level=level, message=message, module="air_check", details=details))


def get_grace_seconds(session=None) -> int:
    """Configured grace period, falling back to the default."""
    session = session or _default_session()
    try:
        from app_core.models import AirCheckSettings

        row = session.query(AirCheckSettings).filter_by(id=1).first()
        if row and row.grace_seconds:
            return max(MIN_GRACE_SECONDS, min(int(row.grace_seconds), MAX_GRACE_SECONDS))
    except Exception as exc:
        logger.debug("Air-check settings unavailable, using default grace: %s", exc)
        _rollback(session)
    return DEFAULT_GRACE_SECONDS


def air_check_receivers(session=None) -> List[Any]:
    """Enabled receivers whose role is ``air_check``."""
    session = session or _default_session()
    try:
        from app_core.models import RadioReceiver

        return (
            session.query(RadioReceiver)
            .filter(RadioReceiver.role == ROLE_AIR_CHECK, RadioReceiver.enabled.is_(True))
            .all()
        )
    except Exception as exc:
        logger.debug("Could not list air-check receivers: %s", exc)
        _rollback(session)
        return []


def resolve_source_role(source_name: Optional[str], session=None) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(role, receiver_identifier)`` for an audio source name.

    Only SDR-backed sources have a role; anything else (HTTP streams, ALSA
    inputs) returns ``(None, None)`` and is treated as a monitor. Cached
    briefly because this runs for every decoded header.
    """
    if not source_name:
        return None, None
    cached = _role_cache.get(source_name)
    now = time.monotonic()
    if cached and now - cached[0] < _ROLE_CACHE_TTL:
        return cached[1], cached[2]

    role: Optional[str] = None
    identifier: Optional[str] = None
    session = session or _default_session()
    try:
        from app_core.models import AudioSourceConfigDB, RadioReceiver

        cfg = session.query(AudioSourceConfigDB).filter_by(name=source_name).first()
        params = (cfg.config_params or {}) if cfg else {}
        identifier = ((params.get("device_params") or {}).get("receiver_id")) or None
        if identifier:
            receiver = session.query(RadioReceiver).filter_by(identifier=identifier).first()
            if receiver is not None:
                role = receiver.role or ROLE_MONITOR
    except Exception as exc:
        logger.debug("Could not resolve role for source %s: %s", source_name, exc)
        _rollback(session)

    _role_cache[source_name] = (now, role, identifier)
    return role, identifier


def clear_role_cache() -> None:
    """Forget cached source roles (call after a receiver's role changes)."""
    _role_cache.clear()



__all__ = [
    "DEFAULT_GRACE_SECONDS",
    "MATCH_WINDOW",
    "MAX_GRACE_SECONDS",
    "MAX_PLAYOUT_SECONDS",
    "MIN_GRACE_SECONDS",
    "RECEIVER_ROLES",
    "ROLE_AIR_CHECK",
    "ROLE_MONITOR",
    "air_check_receivers",
    "clear_role_cache",
    "get_grace_seconds",
    "resolve_source_role",
]
