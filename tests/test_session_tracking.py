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

"""Regression tests for administrator session lifecycle tracking.

These cover the bug where ``admin_sessions`` rows were never closed unless the
user explicitly logged out, leaving dozens of rows showing as "Active" forever.
The fix adds idle-timeout expiry plus heartbeat tracking; these tests verify
stale rows are reaped while active ones survive.
"""

from datetime import timedelta

import pytest

# Skip the whole module if the Flask app stack isn't importable.
pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")


@pytest.fixture
def app_with_db():
    """Minimal Flask app + in-memory SQLite bound to the project's models."""
    from flask import Flask
    from app_core.extensions import db

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.permanent_session_lifetime = timedelta(hours=12)
    db.init_app(app)

    from app_core import models  # noqa: F401  (registers mappers)

    with app.app_context():
        from app_core.models import AdminSession, AdminUser
        from app_core.auth.roles import Role
        # AdminSession.user is joined-loaded and AdminUser.role chains to roles,
        # so all three tables must exist for db.session.get() to resolve.
        Role.__table__.create(db.engine)
        AdminUser.__table__.create(db.engine)
        AdminSession.__table__.create(db.engine)
        yield app, db


def _make_session(db, **overrides):
    from app_core.models import AdminSession
    from app_utils import utc_now

    row = AdminSession(
        user_id=overrides.pop("user_id", 1),
        ip_address=overrides.pop("ip_address", "127.0.0.1"),
        user_agent=overrides.pop("user_agent", "pytest"),
        created_at=overrides.pop("created_at", utc_now()),
        last_seen_at=overrides.pop("last_seen_at", utc_now()),
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    db.session.add(row)
    db.session.commit()
    return row.id


def test_expire_closes_idle_rows_but_keeps_active(app_with_db):
    app, db = app_with_db
    from app_core.auth.session_tracking import expire_stale_sessions
    from app_core.models import AdminSession
    from app_utils import utc_now

    with app.app_context():
        stale_id = _make_session(db, last_seen_at=utc_now() - timedelta(hours=24))
        fresh_id = _make_session(db, last_seen_at=utc_now() - timedelta(minutes=5))

        count = expire_stale_sessions()

        assert count == 1
        assert db.session.get(AdminSession, stale_id).ended_reason == "expired"
        assert db.session.get(AdminSession, stale_id).ended_at is not None
        assert db.session.get(AdminSession, fresh_id).ended_at is None


def test_expire_falls_back_to_created_at_for_legacy_rows(app_with_db):
    """Rows created before heartbeat tracking have a NULL last_seen_at; the
    sweep must still close them based on created_at."""
    app, db = app_with_db
    from app_core.auth.session_tracking import expire_stale_sessions
    from app_core.models import AdminSession
    from app_utils import utc_now

    with app.app_context():
        legacy_id = _make_session(db, created_at=utc_now() - timedelta(days=7))
        # The column default would backfill last_seen_at, so NULL it explicitly
        # to mimic a row written before heartbeat tracking existed.
        AdminSession.query.filter_by(id=legacy_id).update(
            {AdminSession.last_seen_at: None}, synchronize_session=False
        )
        db.session.commit()

        assert expire_stale_sessions() == 1
        assert db.session.get(AdminSession, legacy_id).ended_reason == "expired"


def test_start_session_links_cookie_and_end_closes_it(app_with_db):
    app, db = app_with_db
    from app_core.auth.session_tracking import (
        start_session,
        end_session,
        SESSION_ROW_KEY,
    )
    from app_core.models import AdminSession
    from flask import session

    with app.test_request_context("/login", method="POST"):
        row_id = start_session(user_id=1)
        db.session.commit()
        assert row_id is not None
        assert session.get(SESSION_ROW_KEY) == row_id
        assert db.session.get(AdminSession, row_id).ended_at is None

        end_session(user_id=1, reason="logout")
        db.session.commit()
        assert SESSION_ROW_KEY not in session
        closed = db.session.get(AdminSession, row_id)
        assert closed.ended_at is not None
        assert closed.ended_reason == "logout"


def test_heartbeat_refreshes_last_seen_for_active_session(app_with_db):
    app, db = app_with_db
    from app_core.auth.session_tracking import (
        record_heartbeat,
        SESSION_ROW_KEY,
        SESSION_SEEN_KEY,
    )
    from app_core.models import AdminSession
    from app_utils import utc_now
    from flask import session

    with app.app_context():
        row_id = _make_session(db, last_seen_at=utc_now() - timedelta(hours=1))

    with app.test_request_context("/dashboard"):
        session[SESSION_ROW_KEY] = row_id
        session[SESSION_SEEN_KEY] = 0  # force the throttle gate open
        record_heartbeat(user_id=1)

        refreshed = db.session.get(AdminSession, row_id)
        assert refreshed.ended_at is None
        # last_seen_at moved forward to (approximately) now.  SQLite returns the
        # timestamp tz-naive, so normalize both sides before comparing.
        from datetime import timezone
        last_seen = refreshed.last_seen_at
        if last_seen.tzinfo is not None:
            last_seen = last_seen.astimezone(timezone.utc).replace(tzinfo=None)
        now_naive = utc_now().replace(tzinfo=None)
        assert last_seen > now_naive - timedelta(minutes=1)
