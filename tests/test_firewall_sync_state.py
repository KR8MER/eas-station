"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

Regression tests for firewall ban-list ↔ jail sync-state detection.

Background: the actuator jail enforces bans with ``fail2ban-client ... banip``,
which only accepts single routable IPs. CIDR ranges and loopback addresses on
the application ban list are therefore enforced at the application layer only
and never mirrored to the firewall jail. The "is the firewall in sync?" checks
used to compare the jail's IP count against the *full* ban-list size, so a list
holding even one CIDR range looked permanently out of sync: ``heal_firewall_bans``
fired a no-op ``resync_bans`` on every cycle and the Security Center showed a
"Some bans aren't mirrored yet — click Resync bans" banner that Resync could
never clear. These tests pin the comparison to the *mirrorable* subset.
"""

from __future__ import annotations

import pytest

pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")


@pytest.fixture
def app_with_tables():
    """Minimal Flask app + in-memory SQLite with firewall mirroring enabled."""
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
        # Firewall mirroring on; fail2ban availability is monkeypatched per-test.
        db.session.add(Fail2banSettings(id=1, enabled=True, protect_ssh=False))
        db.session.commit()
        yield app, db


def _patch_firewall(monkeypatch, jail_ips):
    """Believe fail2ban is up with the eas-station jail loaded holding *jail_ips*.

    Returns the list of captured ``_client`` calls (so a resync is observable).
    add_to_blocklist's firewall mirroring is stubbed so it doesn't shell out.
    """
    from app_core.auth import firewall

    calls = []
    monkeypatch.setattr(firewall, "_fail2ban_available", lambda: True)
    monkeypatch.setattr(firewall, "_loaded_jails", lambda: {firewall.EAS_JAIL})
    monkeypatch.setattr(
        firewall, "_jail_banned_ips",
        lambda jail: list(jail_ips) if jail == firewall.EAS_JAIL else [],
    )
    monkeypatch.setattr(firewall, "_client", lambda *args, **kw: calls.append(args) or True)
    monkeypatch.setattr("app_core.auth.ip_filter.firewall_ban", lambda *a, **k: None,
                        raising=False)
    return calls


def test_cidr_range_does_not_make_firewall_look_out_of_sync(app_with_tables, monkeypatch):
    """A CIDR range on the ban list must not register as a pending/un-mirrored ban.

    The single IP is already in the jail, so the firewall is fully synced even
    though the ban list is "larger" (it also holds a range). heal must not resync
    and there must be zero pending bans.
    """
    app, _ = app_with_tables
    from app_core.auth import firewall
    from app_core.auth.ip_filter import IPFilter, IPFilterReason, IPFilterSource

    # Jail already holds the one mirrorable IP.
    calls = _patch_firewall(monkeypatch, ["203.0.113.50"])
    with app.app_context():
        IPFilter.add_to_blocklist(
            "203.0.113.50",
            reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
            source=IPFilterSource.SSH_BRUTE_FORCE.value,
        )
        # A manually-banned CIDR range — never mirrorable to the jail.
        IPFilter.add_to_blocklist(
            "198.51.100.0/24",
            reason=IPFilterReason.MANUAL.value,
            source=IPFilterSource.MANUAL.value,
        )
        calls.clear()  # ignore mirroring side-effects of building the ban list

        assert firewall.mirrorable_blocklist_ips() == {"203.0.113.50"}
        assert firewall.firewall_pending_bans() == 0
        # No drift ⇒ no resync (previously this fired a no-op resync every cycle).
        assert firewall.heal_firewall_bans() is False
        assert calls == []


def test_missing_single_ip_is_detected_and_healed(app_with_tables, monkeypatch):
    """A genuinely un-mirrored single IP is still detected and re-pushed."""
    app, _ = app_with_tables
    from app_core.auth import firewall
    from app_core.auth.ip_filter import IPFilter, IPFilterReason, IPFilterSource

    # Jail holds one IP; the ban list has two single IPs.
    calls = _patch_firewall(monkeypatch, ["203.0.113.50"])
    with app.app_context():
        IPFilter.add_to_blocklist(
            "203.0.113.50",
            reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
            source=IPFilterSource.SSH_BRUTE_FORCE.value,
        )
        IPFilter.add_to_blocklist(
            "203.0.113.51",
            reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
            source=IPFilterSource.SSH_BRUTE_FORCE.value,
        )
        calls.clear()  # ignore mirroring side-effects of building the ban list

        assert firewall.firewall_pending_bans() == 1
        assert firewall.heal_firewall_bans() is True
        # resync re-pushed the missing IP into the eas-station jail.
        assert ("set", firewall.EAS_JAIL, "banip", "203.0.113.51") in calls
