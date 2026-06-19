"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

Regression tests for the background fail2ban → Global Ban List sync.

Background: fail2ban's sshd jail blocks SSH brute-force at the host firewall
around the clock, but sshd-jail bans only became visible in the Global Ban List
(``ip_filters``) when the import ran — and that import used to fire *only* as a
side effect of the Security Center page polling ``/admin/fail2ban/status``. So
bans were enforced overnight but never recorded unless an operator had the UI
open, which is exactly the symptom reported ("SSH attacks only appear while I'm
working on the UI"). The ``created_at`` of each entry reflected when an operator
next loaded the UI, not when fail2ban actually banned the offender.

``app_core.fail2ban_sync`` fixes that with a daemon thread that runs the same
import (now in ``app_core.auth.firewall``) on an interval, independent of the
UI. These tests pin down that a background cycle records sshd-jail bans into the
ban list with no web request involved.
"""

from __future__ import annotations

import pytest

pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")


@pytest.fixture
def app_with_tables():
    """Minimal Flask app + in-memory SQLite with the tables the sync needs."""
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


def _patch_sshd_jail(monkeypatch, banned_ips):
    """Make the firewall bridge believe fail2ban is up and the sshd jail holds
    *banned_ips* — without touching the host. Firewall mirroring is stubbed so
    add_to_blocklist doesn't shell out."""
    from app_core.auth import firewall

    monkeypatch.setattr(firewall, "_fail2ban_available", lambda: True)
    monkeypatch.setattr(
        firewall, "_jail_banned_ips",
        lambda jail: list(banned_ips) if jail == firewall.SSH_JAIL else [],
    )
    monkeypatch.setattr("app_core.auth.ip_filter.firewall_ban", lambda *a, **k: None,
                        raising=False)


def test_background_cycle_imports_ssh_bans_without_web_request(app_with_tables, monkeypatch):
    """A background sync cycle records a live sshd-jail ban into the ban list.

    This is the core fix: no Flask request, no open UI — the offender still
    lands in the Global Ban List.
    """
    app, _ = app_with_tables
    from app_core.fail2ban_sync import run_sync_cycle
    from app_core.auth.ip_filter import IPFilter, IPFilterType, IPFilterSource

    _patch_sshd_jail(monkeypatch, ["198.51.100.23"])

    with app.app_context():
        # Nothing in the ban list to start with.
        assert IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value, is_active=True
        ).count() == 0

        summary = run_sync_cycle()
        assert summary["imported"] == 1

        entry = IPFilter.query.filter_by(
            ip_address="198.51.100.23",
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True,
        ).first()
        assert entry is not None
        assert entry.source == IPFilterSource.SSH_BRUTE_FORCE.value


def test_background_cycle_is_idempotent(app_with_tables, monkeypatch):
    """Running the cycle twice does not duplicate an already-imported ban."""
    app, _ = app_with_tables
    from app_core.fail2ban_sync import run_sync_cycle
    from app_core.auth.ip_filter import IPFilter, IPFilterType

    _patch_sshd_jail(monkeypatch, ["198.51.100.24"])

    with app.app_context():
        run_sync_cycle()
        run_sync_cycle()

        assert IPFilter.query.filter_by(
            ip_address="198.51.100.24",
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True,
        ).count() == 1


def test_background_cycle_noop_when_ssh_protection_disabled(app_with_tables, monkeypatch):
    """With SSH protection off, the cycle imports nothing even if the jail has bans."""
    app, db = app_with_tables
    from app_core.fail2ban_sync import run_sync_cycle
    from app_core.auth.ip_filter import IPFilter, IPFilterType
    from app_core.models import Fail2banSettings

    _patch_sshd_jail(monkeypatch, ["198.51.100.25"])

    with app.app_context():
        Fail2banSettings.query.get(1).protect_ssh = False
        db.session.commit()

        summary = run_sync_cycle()
        assert summary["imported"] == 0

        assert IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value, is_active=True
        ).count() == 0
