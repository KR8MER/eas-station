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

"""Lifecycle helpers for administrator login sessions (``admin_sessions`` table).

Historically an ``AdminSession`` row was created on login and only closed on an
explicit logout or a manual "Terminate" click. Users almost never log out — they
close the tab or let the Flask cookie expire — so every login left an orphaned
row that showed as "Active" forever. These helpers add idle-timeout tracking so
stale rows are marked ``expired`` and the Active Sessions page reflects reality:

* :func:`start_session`   - create a row on login and link it to the cookie.
* :func:`end_session`     - close the cookie's row on logout.
* :func:`record_heartbeat`- refresh ``last_seen_at`` while the user is active.
* :func:`expire_stale_sessions` - bulk-close rows idle past the timeout.
"""

import time
from datetime import timedelta
from typing import Optional

from flask import current_app, request, session

from app_core.extensions import db
from app_core.models import AdminSession
from app_utils import utc_now

# Flask-session cookie keys linking a browser session to its admin_sessions row.
SESSION_ROW_KEY = "admin_session_id"
SESSION_SEEN_KEY = "admin_session_seen"  # epoch seconds of last heartbeat write

# Write ``last_seen_at`` to the DB at most once per this many seconds so an active
# user browsing many pages does not trigger a DB write/commit on every request.
HEARTBEAT_WRITE_INTERVAL_SECONDS = 60


def get_idle_timeout() -> timedelta:
    """Return the idle window after which a session is treated as dead.

    Reuses the cookie lifetime (``permanent_session_lifetime``, driven by
    ``SESSION_LIFETIME_HOURS``) so the database record and the browser cookie
    expire together. Falls back to 12 hours when unavailable.
    """
    try:
        lifetime = current_app.permanent_session_lifetime
    except Exception:
        lifetime = None
    if not lifetime or lifetime.total_seconds() <= 0:
        return timedelta(hours=12)
    return lifetime


def start_session(user_id: int) -> Optional[int]:
    """Create an ``AdminSession`` row for a fresh login and link it to the cookie.

    The row id is stored in ``session[SESSION_ROW_KEY]`` so later heartbeats and
    the eventual logout update the correct row. Returns the new id, or ``None``
    if the record could not be created (non-critical — login still proceeds).
    """
    try:
        row = AdminSession(
            user_id=user_id,
            ip_address=request.remote_addr if request else None,
            user_agent=(request.headers.get("User-Agent", "")[:512] if request else ""),
            last_seen_at=utc_now(),
        )
        db.session.add(row)
        db.session.flush()  # populate row.id without committing
        session[SESSION_ROW_KEY] = row.id
        session[SESSION_SEEN_KEY] = int(time.time())
        return row.id
    except Exception as exc:  # pragma: no cover - non-critical
        current_app.logger.warning("Could not create AdminSession record: %s", exc)
        return None


def end_session(user_id: int, reason: str = "logout") -> None:
    """Mark the current login's ``AdminSession`` row as ended.

    Prefers the row linked to this cookie; falls back to the most recent active
    row for the user (covers sessions created before cookie linkage existed).
    """
    try:
        row = None
        row_id = session.get(SESSION_ROW_KEY)
        if row_id is not None:
            row = AdminSession.query.filter_by(id=row_id, ended_at=None).first()
        if row is None:
            row = (
                AdminSession.query
                .filter_by(user_id=user_id, ended_at=None)
                .order_by(AdminSession.created_at.desc())
                .first()
            )
        if row is not None:
            row.ended_at = utc_now()
            row.ended_reason = reason
    except Exception as exc:  # pragma: no cover - non-critical
        current_app.logger.warning("Could not end AdminSession record: %s", exc)
    finally:
        session.pop(SESSION_ROW_KEY, None)
        session.pop(SESSION_SEEN_KEY, None)


def _ensure_linked(user_id: int) -> Optional[int]:
    """Attach the current cookie to an ``admin_sessions`` row if not linked yet.

    Sessions that were already logged in before heartbeat tracking shipped have
    no ``SESSION_ROW_KEY`` in their cookie. Rather than leave them untracked
    (and let the sweep wrongly expire their live row), adopt the most recent
    active row for the user, or create a fresh one.
    """
    row_id = session.get(SESSION_ROW_KEY)
    if row_id is not None:
        return row_id
    try:
        existing = (
            AdminSession.query
            .filter_by(user_id=user_id, ended_at=None)
            .order_by(AdminSession.created_at.desc())
            .first()
        )
        if existing is not None:
            session[SESSION_ROW_KEY] = existing.id
            session[SESSION_SEEN_KEY] = int(time.time())
            return existing.id
    except Exception as exc:  # pragma: no cover - non-critical
        current_app.logger.debug("Could not adopt existing session row: %s", exc)
    return start_session(user_id)


def record_heartbeat(user_id: int) -> None:
    """Refresh ``last_seen_at`` for the active user's session row (throttled).

    Called from the global ``before_request`` hook for authenticated requests.
    Writes at most once per :data:`HEARTBEAT_WRITE_INTERVAL_SECONDS`; on each
    write it also runs an inline :func:`expire_stale_sessions` sweep so idle
    rows are reaped even when nobody opens the Active Sessions page.
    """
    now_epoch = int(time.time())
    last = session.get(SESSION_SEEN_KEY, 0)
    if session.get(SESSION_ROW_KEY) is not None and now_epoch - last < HEARTBEAT_WRITE_INTERVAL_SECONDS:
        return

    row_id = _ensure_linked(user_id)
    if row_id is None:
        return
    try:
        (
            AdminSession.query
            .filter_by(id=row_id, ended_at=None)
            .update({AdminSession.last_seen_at: utc_now()}, synchronize_session=False)
        )
        db.session.commit()
        session[SESSION_SEEN_KEY] = now_epoch
    except Exception as exc:  # pragma: no cover - non-critical
        db.session.rollback()
        current_app.logger.debug("Session heartbeat update failed: %s", exc)
        return

    expire_stale_sessions()


def expire_stale_sessions() -> int:
    """Close active sessions idle longer than the timeout and return the count.

    Uses ``last_seen_at`` when present, falling back to ``created_at`` for rows
    that predate heartbeat tracking, so the long backlog of never-closed rows is
    swept on the first run.
    """
    from sqlalchemy import func

    cutoff = utc_now() - get_idle_timeout()
    last_activity = func.coalesce(AdminSession.last_seen_at, AdminSession.created_at)
    try:
        count = (
            AdminSession.query
            .filter(AdminSession.ended_at.is_(None))
            .filter(last_activity < cutoff)
            .update(
                {AdminSession.ended_at: utc_now(), AdminSession.ended_reason: "expired"},
                synchronize_session=False,
            )
        )
        db.session.commit()
        if count:
            current_app.logger.info("Expired %d stale administrator session(s).", count)
        return count or 0
    except Exception as exc:  # pragma: no cover - non-critical
        db.session.rollback()
        current_app.logger.warning("Could not expire stale sessions: %s", exc)
        return 0


__all__ = [
    "SESSION_ROW_KEY",
    "SESSION_SEEN_KEY",
    "HEARTBEAT_WRITE_INTERVAL_SECONDS",
    "get_idle_timeout",
    "start_session",
    "end_session",
    "record_heartbeat",
    "expire_stale_sessions",
]
