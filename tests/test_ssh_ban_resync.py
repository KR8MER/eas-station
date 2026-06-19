"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

Regression tests for SSH-ban persistence across a fail2ban restart.

Background: fail2ban flushes every live ban when it restarts, and the Security
Center restarts the service on every "Save & Apply". Web bans were restored
afterwards (``resync_bans`` re-pushes the ``eas-station`` jail from the
database), but SSH-jail bans were not restored to any jail — so an apply/restart
silently un-banned known SSH attackers until they were re-detected.
``resync_ssh_bans`` closes that gap by re-applying still-active SSH-sourced bans
into the ``sshd`` jail. These tests pin down its selection logic.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")

from app_utils import utc_now


@pytest.fixture
def app_with_tables():
    """Minimal Flask app + in-memory SQLite with the tables resync_ssh_bans needs."""
    from flask import Flask
    from app_core.extensions import db

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    from app_core import models  # noqa: F401  (registers mappers)

    with app.app_context():
        from app_core.auth.ip_filter import IPFilter
        from app_core.models import Fail2banSettings

        IPFilter.__table__.create(db.engine)
        Fail2banSettings.__table__.create(db.engine)
        # SSH protection on; fail2ban availability is monkeypatched per-test.
        db.session.add(Fail2banSettings(id=1, enabled=False, protect_ssh=True))
        db.session.commit()
        yield app, db


def _capture_client(monkeypatch):
    """Patch fail2ban availability + the client, returning the captured calls."""
    from app_core.auth import firewall

    calls = []
    monkeypatch.setattr(firewall, "_fail2ban_available", lambda: True)
    monkeypatch.setattr(firewall, "_client", lambda *args, **kw: calls.append(args) or True)
    return calls


def test_active_ssh_ban_is_reapplied_to_sshd_jail(app_with_tables, monkeypatch):
    """An active SSH-sourced ban is pushed back into the sshd jail on resync."""
    app, _ = app_with_tables
    from app_core.auth import firewall
    from app_core.auth.ip_filter import IPFilter, IPFilterReason, IPFilterSource

    calls = _capture_client(monkeypatch)
    with app.app_context():
        IPFilter.add_to_blocklist(
            "203.0.113.7",
            reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
            source=IPFilterSource.SSH_BRUTE_FORCE.value,
            expires_in_hours=24,
        )
        assert firewall.resync_ssh_bans() == 1
        assert ("set", firewall.SSH_JAIL, "banip", "203.0.113.7") in calls


def test_non_ssh_ban_is_not_pushed_to_sshd_jail(app_with_tables, monkeypatch):
    """A non-SSH (e.g. manual/web) ban is never re-applied to the sshd jail."""
    app, _ = app_with_tables
    from app_core.auth import firewall
    from app_core.auth.ip_filter import IPFilter, IPFilterReason, IPFilterSource

    calls = _capture_client(monkeypatch)
    with app.app_context():
        # A manually-banned web offender must not land in the sshd jail.
        IPFilter.add_to_blocklist(
            "203.0.113.8",
            reason=IPFilterReason.MANUAL.value,
            source=IPFilterSource.MANUAL.value,
        )
        assert firewall.resync_ssh_bans() == 0
        assert calls == []


def test_expired_and_loopback_ssh_bans_are_skipped(app_with_tables, monkeypatch):
    """Expired entries and loopback addresses are excluded from the resync."""
    app, db = app_with_tables
    from app_core.auth import firewall
    from app_core.auth.ip_filter import IPFilter, IPFilterReason, IPFilterSource

    calls = _capture_client(monkeypatch)
    with app.app_context():
        expired = IPFilter.add_to_blocklist(
            "203.0.113.9",
            reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
            source=IPFilterSource.SSH_BRUTE_FORCE.value,
        )
        expired.expires_at = utc_now() - timedelta(hours=1)
        # Loopback must never be firewall-banned (can't lock the box out of itself).
        IPFilter.add_to_blocklist(
            "127.0.0.1",
            reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
            source=IPFilterSource.SSH_BRUTE_FORCE.value,
        )
        db.session.commit()

        assert firewall.resync_ssh_bans() == 0
        assert calls == []


def test_resync_is_noop_when_ssh_protection_disabled(app_with_tables, monkeypatch):
    """With SSH protection off, resync does nothing even if SSH bans exist."""
    app, db = app_with_tables
    from app_core.auth import firewall
    from app_core.auth.ip_filter import IPFilter, IPFilterReason, IPFilterSource
    from app_core.models import Fail2banSettings

    calls = _capture_client(monkeypatch)
    with app.app_context():
        Fail2banSettings.query.get(1).protect_ssh = False
        db.session.commit()
        IPFilter.add_to_blocklist(
            "203.0.113.10",
            reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
            source=IPFilterSource.SSH_BRUTE_FORCE.value,
        )
        assert firewall.resync_ssh_bans() == 0
        assert calls == []
